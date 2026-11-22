"""Stage, retain, and recover screenshots in the local media store."""

import logging
import re
from pathlib import Path, PurePosixPath
from uuid import uuid4

from gamehub.core.storage import media
from gamehub.core.storage.db import Database, StorageError

LOGGER = logging.getLogger(__name__)
_SHOT_NAME = rf"shot_{media.UUID_PATTERN}\.webp"
_FILENAME = re.compile(rf"{_SHOT_NAME}(?:\.tmp)?")
_MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024


def _relative(game_id: str, session_id: str, screenshot_id: str) -> PurePosixPath:
    return PurePosixPath("media", game_id, session_id, f"shot_{screenshot_id}.webp")


def _is_bounded_webp(data: bytes) -> bool:
    return len(data) <= _MAX_SCREENSHOT_BYTES and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


class ScreenshotRepository:
    def __init__(self, database: Database, data_root: Path) -> None:
        self._database = database
        self._root = media.validate_root(data_root, database.path)
        self._media = self._root / "media"

    def append(self, game_id: str, session_id: str, data: bytes, captured_at: int, limit: int) -> bool:
        """Keep up to `limit` recent images for an open session and prune older frames."""
        if not (media.UUID.fullmatch(game_id) and media.UUID.fullmatch(session_id)):
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

                media.stage_file(self._media, path, data)
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
            if media.UUID.fullmatch(row["id"]) and row["path"] == old.as_posix():
                media.delete_file(self._root.joinpath(*old.parts), "screenshot_file_cleanup_failed")
        return True

    def recover_files(self) -> None:
        """Remove only recognizable, unreferenced screenshot files and abandoned staging files."""
        with self._database.write() as connection:
            rows = connection.execute(
                "SELECT screenshots.id, session_id, path, game_id FROM screenshots "
                "JOIN sessions ON sessions.id = screenshots.session_id"
            )
            owned = {
                row["path"] for row in rows
                if all(media.UUID.fullmatch(row[key]) for key in ("game_id", "session_id", "id"))
                and row["path"] == _relative(row["game_id"], row["session_id"], row["id"]).as_posix()
            }
            media.reconcile_files(self._media, owned, _FILENAME, "screenshot_reconciliation_incomplete")

    def last_moments(self, game_id: str) -> tuple[Path, ...]:
        """List safe references even when a screenshot's file is unavailable."""
        if not media.UUID.fullmatch(game_id):
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
            if media.UUID.fullmatch(row["session_id"]) and media.UUID.fullmatch(row["id"]):
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
            media.UUID.fullmatch(part) for part in parts[1:3]
        ) or not re.fullmatch(_SHOT_NAME, parts[3]):
            return None

        try:
            with self._database.read() as connection:
                if connection.execute("SELECT 1 FROM screenshots WHERE path = ?", (relative.as_posix(),)).fetchone() is None:
                    return None
            path = self._root.joinpath(*parts)
            data = media.read_file(path, _MAX_SCREENSHOT_BYTES)
            return data if data is not None and _is_bounded_webp(data) else None
        except FileNotFoundError:
            return None
        except (OSError, StorageError):
            LOGGER.warning("screenshot_read_incomplete")
            return None
