"""Stage, retain, and recover screenshots in the local media store."""

import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from gamehub.core.library.paths import local_path
from gamehub.core.storage.db import Database, StorageError

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _open_file = _kernel.CreateFileW
    _open_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _open_file.restype = wintypes.HANDLE
    _close_handle = _kernel.CloseHandle
    _close_handle.argtypes = (wintypes.HANDLE,)
    _close_handle.restype = wintypes.BOOL
    _get_file_info = _kernel.GetFileInformationByHandleEx
    _get_file_info.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _get_file_info.restype = wintypes.BOOL
    _read_file = _kernel.ReadFile
    _read_file.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    )
    _read_file.restype = wintypes.BOOL
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _AttributeTagInfo(ctypes.Structure):
        _fields_ = (("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD))

    class _StandardInfo(ctypes.Structure):
        _fields_ = (
            ("allocated_bytes", ctypes.c_longlong), ("size", ctypes.c_longlong),
            ("links", wintypes.DWORD), ("delete_pending", ctypes.c_ubyte),
            ("directory", ctypes.c_ubyte),
        )

LOGGER = logging.getLogger(__name__)
_UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
_UUID = re.compile(_UUID_PATTERN)
_SHOT_NAME = rf"shot_{_UUID_PATTERN}\.webp"
_FILENAME = re.compile(rf"{_SHOT_NAME}(?:\.tmp)?")
_MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024
_FILE_LIST_DIRECTORY = 0x0001
_GENERIC_READ = 0x8000_0000
_FILE_SHARE_READ = 1
_FILE_SHARE_WRITE = 2
_OPEN_EXISTING = 3
_OPEN_REPARSE_POINT = 0x0020_0000
_BACKUP_SEMANTICS = 0x0200_0000


def _relative(game_id: str, session_id: str, screenshot_id: str) -> PurePosixPath:
    return PurePosixPath("media", game_id, session_id, f"shot_{screenshot_id}.webp")


def _is_reparse_point(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _is_regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and not _is_reparse_point(info)


def _is_bounded_webp(data: bytes) -> bool:
    return len(data) <= _MAX_SCREENSHOT_BYTES and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


@contextmanager
def _windows_handle(path: Path, access: int, share: int, flags: int) -> Iterator[int]:
    handle = _open_file(str(path), access, share, None, _OPEN_EXISTING, flags, None)
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield handle
    finally:
        _close_handle(handle)


def _handle_attributes(handle: int) -> int:
    info = _AttributeTagInfo()
    if not _get_file_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info.attributes


@contextmanager
def _pin_directory(path: Path) -> Iterator[None]:
    """Hold a Windows directory without sharing deletion or rename access."""
    if os.name != "nt":
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise OSError("Unsafe media directory")
        yield
        return

    # A metadata-only open does not enforce sharing, so request directory access.
    share = _FILE_SHARE_READ | _FILE_SHARE_WRITE
    flags = _OPEN_REPARSE_POINT | _BACKUP_SEMANTICS
    with _windows_handle(path, _FILE_LIST_DIRECTORY, share, flags) as handle:
        attributes = _handle_attributes(handle)
        if not attributes & stat.FILE_ATTRIBUTE_DIRECTORY or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError("Unsafe media directory")
        yield


def _read_screenshot(path: Path) -> bytes | None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return None
            return source.read(_MAX_SCREENSHOT_BYTES + 1)

    with _windows_handle(path, _GENERIC_READ, _FILE_SHARE_READ, _OPEN_REPARSE_POINT) as handle:
        attributes = _handle_attributes(handle)
        if attributes & (stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return None
        info = _StandardInfo()
        if not _get_file_info(handle, 1, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.links != 1 or not 12 <= info.size <= _MAX_SCREENSHOT_BYTES:
            return None
        data = ctypes.create_string_buffer(info.size)
        size = wintypes.DWORD()
        if not _read_file(handle, data, info.size, ctypes.byref(size), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return data.raw if size.value == info.size else None


class ScreenshotRepository:
    def __init__(self, database: Database, data_root: Path) -> None:
        self._database = database
        self._root = data_root.absolute()
        self._media = self._root / "media"
        if self._root != database.path.parent or local_path(self._root) is None:
            raise StorageError("Game Hub could not validate the screenshot data folder.")

    @contextmanager
    def _protect(self, directory: Path, *, create: bool = False) -> Iterator[None]:
        with ExitStack() as stack:
            for ancestor in (*reversed(directory.parents), directory):
                if create and ancestor.is_relative_to(self._media):
                    try:
                        ancestor.mkdir()
                    except FileExistsError:
                        pass
                stack.enter_context(_pin_directory(ancestor))
            yield

    def append(self, game_id: str, session_id: str, data: bytes, captured_at: int, limit: int) -> bool:
        """Keep up to `limit` recent images for an open session and prune older frames."""
        if not (_UUID.fullmatch(game_id) and _UUID.fullmatch(session_id)):
            return False
        if limit < 1:
            raise ValueError("The screenshot buffer must keep at least one frame.")
        if not _is_bounded_webp(data):
            raise ValueError("Expected a bounded WebP screenshot.")

        screenshot_id = str(uuid4())
        relative = _relative(game_id, session_id, screenshot_id)
        path = self._root.joinpath(*relative.parts)
        try:
            with self._database.write() as connection:
                session = connection.execute(
                    "SELECT 1 FROM sessions WHERE id = ? AND game_id = ? AND status = 'open'",
                    (session_id, game_id),
                ).fetchone()
                if session is None:
                    return False

                with self._protect(path.parent, create=True):
                    staged = path.with_suffix(".webp.tmp")
                    with staged.open("xb") as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    staged.replace(path)

                previous = connection.execute(
                    "SELECT MAX(captured_at) FROM screenshots WHERE session_id = ?", (session_id,)
                ).fetchone()[0]
                if previous is not None:
                    captured_at = max(captured_at, previous + 1)
                connection.execute(
                    "INSERT INTO screenshots (id, session_id, path, captured_at) VALUES (?, ?, ?, ?)",
                    (screenshot_id, session_id, relative.as_posix(), captured_at),
                )
                evicted = connection.execute(
                    """
                    SELECT id, path FROM screenshots WHERE session_id = ?
                    ORDER BY captured_at DESC, id DESC LIMIT -1 OFFSET ?
                    """,
                    (session_id, limit),
                ).fetchall()
                connection.executemany("DELETE FROM screenshots WHERE id = ?", ((row["id"],) for row in evicted))
        except OSError as error:
            raise StorageError("Game Hub could not save the screenshot.") from error

        for row in evicted:
            old = _relative(game_id, session_id, row["id"])
            if _UUID.fullmatch(row["id"]) and row["path"] == old.as_posix():
                self._delete_file(self._root.joinpath(*old.parts))
        return True

    def _delete_file(self, path: Path) -> None:
        try:
            with self._protect(path.parent):
                if _is_regular_file(path):
                    path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        except OSError:
            LOGGER.warning("screenshot_file_cleanup_failed")

    def recover_files(self) -> None:
        """Remove only recognizable, unreferenced screenshot files and abandoned staging files."""
        try:
            with self._database.write() as connection, self._protect(self._media):
                rows = connection.execute(
                    "SELECT screenshots.id, session_id, path, game_id FROM screenshots "
                    "JOIN sessions ON sessions.id = screenshots.session_id"
                )
                owned = {
                    row["path"] for row in rows
                    if all(_UUID.fullmatch(row[key]) for key in ("game_id", "session_id", "id"))
                    and row["path"] == _relative(row["game_id"], row["session_id"], row["id"]).as_posix()
                }
                self._remove_unowned(owned)
        except FileNotFoundError:
            pass
        except OSError:
            LOGGER.warning("screenshot_reconciliation_incomplete")

    def _remove_unowned(self, owned: set[str]) -> None:
        for game in self._media.iterdir():
            if not _UUID.fullmatch(game.name):
                continue
            try:
                with _pin_directory(game):
                    for session in game.iterdir():
                        if _UUID.fullmatch(session.name):
                            self._reconcile_session(session, owned)
            except OSError:
                LOGGER.warning("screenshot_reconciliation_incomplete")

    def _reconcile_session(self, session: Path, owned: set[str]) -> None:
        try:
            with _pin_directory(session):
                for item in session.iterdir():
                    relative = item.relative_to(self._root).as_posix()
                    if _FILENAME.fullmatch(item.name) and relative not in owned:
                        try:
                            if _is_regular_file(item):
                                item.unlink(missing_ok=True)
                        except OSError:
                            LOGGER.warning("screenshot_file_cleanup_failed")
        except OSError:
            LOGGER.warning("screenshot_reconciliation_incomplete")

    def last_moments(self, game_id: str) -> tuple[Path, ...]:
        """List safe references even when a screenshot's file is unavailable."""
        if not _UUID.fullmatch(game_id):
            return ()
        with self._database.read() as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, path FROM screenshots
                WHERE is_last_moment = 1 AND session_id = (
                    SELECT id FROM sessions WHERE game_id = ? AND status != 'open'
                    ORDER BY started_at DESC, id DESC LIMIT 1
                ) ORDER BY captured_at, id
                """,
                (game_id,),
            ).fetchall()
        paths = []
        for row in rows:
            if _UUID.fullmatch(row["session_id"]) and _UUID.fullmatch(row["id"]):
                relative = _relative(game_id, row["session_id"], row["id"])
                if row["path"] == relative.as_posix():
                    paths.append(self._root.joinpath(*relative.parts))
        return tuple(paths)

    def read_image(self, path: Path) -> bytes | None:
        """Read a bounded, owned WebP image using its safe opened file handle."""
        if not path.is_relative_to(self._media):
            return None
        relative = path.relative_to(self._root)
        parts = relative.parts
        if len(parts) != 4 or parts[0] != "media" or not all(
            _UUID.fullmatch(part) for part in parts[1:3]
        ) or not re.fullmatch(_SHOT_NAME, parts[3]):
            return None

        try:
            with self._database.read() as connection:
                if connection.execute("SELECT 1 FROM screenshots WHERE path = ?", (relative.as_posix(),)).fetchone() is None:
                    return None
            path = self._root.joinpath(*parts)
            with self._protect(path.parent):
                data = _read_screenshot(path)
                return data if data is not None and _is_bounded_webp(data) else None
        except FileNotFoundError:
            return None
        except (OSError, StorageError):
            LOGGER.warning("screenshot_read_incomplete")
            return None
