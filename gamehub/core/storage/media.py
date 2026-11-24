"""Shared directory pinning and filesystem operations for local media."""

import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from gamehub.core.library.paths import local_path
from gamehub.core.storage.db import StorageError

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
    _read_native_file = _kernel.ReadFile
    _read_native_file.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    )
    _read_native_file.restype = wintypes.BOOL
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
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
UUID = re.compile(UUID_PATTERN)
_FILE_LIST_DIRECTORY = 0x0001
_GENERIC_READ = 0x8000_0000
_FILE_SHARE_READ = 1
_FILE_SHARE_WRITE = 2
_OPEN_EXISTING = 3
_OPEN_REPARSE_POINT = 0x0020_0000
_BACKUP_SEMANTICS = 0x0200_0000

def validate_root(root: Path, database_path: Path) -> Path:
    root = root.absolute()
    if root != database_path.parent or local_path(root) is None:
        raise StorageError("GameRewind could not validate the media data folder.")
    return root


def _is_reparse_point(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _is_regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and not _is_reparse_point(info)


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


def _read_file(path: Path, max_bytes: int, prefix_bytes: int | None) -> bytes | None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes:
                return None
            data = source.read(prefix_bytes if prefix_bytes is not None else max_bytes + 1)
            return data if len(data) <= max_bytes else None

    with _windows_handle(path, _GENERIC_READ, _FILE_SHARE_READ, _OPEN_REPARSE_POINT) as handle:
        attributes = _handle_attributes(handle)
        if attributes & (stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return None
        info = _StandardInfo()
        if not _get_file_info(handle, 1, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.links != 1 or not 0 < info.size <= max_bytes:
            return None
        requested = min(info.size, prefix_bytes) if prefix_bytes is not None else info.size
        data = ctypes.create_string_buffer(requested)
        size = wintypes.DWORD()
        if not _read_native_file(handle, data, requested, ctypes.byref(size), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return data.raw if size.value == requested else None



@contextmanager
def protect_directory(directory: Path, *, create_from: Path | None = None) -> Iterator[None]:
    with ExitStack() as stack:
        for ancestor in (*reversed(directory.parents), directory):
            if create_from is not None and ancestor.is_relative_to(create_from):
                try:
                    ancestor.mkdir()
                except FileExistsError:
                    pass
            stack.enter_context(_pin_directory(ancestor))
        yield


def read_file(path: Path, max_bytes: int, *, prefix_bytes: int | None = None) -> bytes | None:
    """Read a previously validated media path with its parent directories pinned."""
    with protect_directory(path.parent):
        return _read_file(path, max_bytes, prefix_bytes)


def stage_file(media: Path, path: Path, data: bytes) -> None:
    """Write and flush a new staging file, then promote it on the same volume."""
    if not path.is_relative_to(media) or ".." in path.parts:
        raise StorageError("GameRewind found an invalid media location.")
    with protect_directory(path.parent, create_from=media):
        staged = path.with_suffix(f"{path.suffix}.tmp")
        with staged.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        staged.replace(path)


def delete_file(path: Path, failure_code: str) -> None:
    try:
        with protect_directory(path.parent):
            if _is_regular_file(path):
                path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except OSError:
        LOGGER.warning("%s", failure_code)


def _reconcile_session(
    session: Path, root: Path, owned: set[str], file_pattern: re.Pattern[str], failure_code: str
) -> None:
    try:
        with _pin_directory(session):
            for item in session.iterdir():
                relative = item.relative_to(root).as_posix()
                if file_pattern.fullmatch(item.name) and relative not in owned:
                    try:
                        if _is_regular_file(item):
                            item.unlink(missing_ok=True)
                    except OSError:
                        LOGGER.warning("%s", failure_code)
    except OSError:
        LOGGER.warning("%s", failure_code)


def reconcile_files(
    media: Path, owned: set[str], file_pattern: re.Pattern[str], failure_code: str
) -> None:
    """Sweep only files matching a repository's managed filename convention."""
    try:
        with protect_directory(media):
            for game in media.iterdir():
                if not UUID.fullmatch(game.name):
                    continue
                try:
                    with _pin_directory(game):
                        for session in game.iterdir():
                            if UUID.fullmatch(session.name):
                                _reconcile_session(session, media.parent, owned, file_pattern, failure_code)
                except OSError:
                    LOGGER.warning("%s", failure_code)
    except FileNotFoundError:
        pass
    except OSError:
        LOGGER.warning("%s", failure_code)


def reconcile_game_subfolder(
    media: Path,
    subfolder: str,
    owned: set[str],
    file_pattern: re.Pattern[str],
    failure_code: str,
) -> None:
    """Sweep managed files inside a fixed per-game subfolder such as controls."""
    try:
        with protect_directory(media):
            for game in media.iterdir():
                if not UUID.fullmatch(game.name):
                    continue
                try:
                    with _pin_directory(game):
                        target = game / subfolder
                        if target.exists():
                            _reconcile_session(target, media.parent, owned, file_pattern, failure_code)
                except OSError:
                    LOGGER.warning("%s", failure_code)
    except FileNotFoundError:
        pass
    except OSError:
        LOGGER.warning("%s", failure_code)
