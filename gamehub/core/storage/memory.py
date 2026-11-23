"""Query prior ended sessions and voice playback media for the Last time card."""

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from gamehub.core.library.models import LaunchTarget
from gamehub.core.storage import controls as controls_storage
from gamehub.core.storage import media, notes, settings
from gamehub.core.storage.db import Database, StorageError

LOGGER = logging.getLogger(__name__)
_AUTOPLAY_KEY = "memory.autoplay_voice"
_VOICE_NAME = re.compile(rf"note_({media.UUID_PATTERN})\.ogg")
_OGG_PREFIX = b"OggS\x00"
_MIN_OGG_BYTES = 27


@dataclass(frozen=True, slots=True)
class LastSessionSummary:
    id: str
    started_at: int
    ended_at: int
    duration_sec: int
    status: str


@dataclass(frozen=True, slots=True)
class VoiceNoteSnapshot:
    id: str
    session_id: str
    created_at: int
    path: Path
    available: bool


@dataclass(frozen=True, slots=True)
class TextNoteSnapshot:
    id: str
    session_id: str
    created_at: int
    text: str


@dataclass(frozen=True, slots=True)
class MemoryChanged:
    game_id: str
    session_id: str | None
    item_kind: str
    item_id: str


@dataclass(frozen=True, slots=True)
class SessionCursor:
    started_at: int
    session_id: str


@dataclass(frozen=True, slots=True)
class TimelineSession:
    id: str
    started_at: int
    ended_at: int | None
    duration_sec: int
    status: str
    screenshots: tuple[Path, ...]
    voice_notes: tuple[VoiceNoteSnapshot, ...]
    text_notes: tuple[TextNoteSnapshot, ...]


@dataclass(frozen=True, slots=True)
class TimelinePage:
    sessions: tuple[TimelineSession, ...]
    next_cursor: SessionCursor | None = None


@dataclass(frozen=True, slots=True)
class LastTimeData:
    game_id: str
    game_name: str
    installed: bool
    launch_target: LaunchTarget | None
    last_session: LastSessionSummary | None
    total_playtime: int
    session_count: int
    voice_note: VoiceNoteSnapshot | None
    text_note: TextNoteSnapshot | None
    screenshots: tuple[Path, ...]
    controls: tuple[str, ...] = ()
    control_images: tuple[Path, ...] = ()
    cover_path: Path | None = None


def _screenshot_path(game_id: str, session_id: str, screenshot_id: str) -> PurePosixPath:
    return PurePosixPath("media", game_id, session_id, f"shot_{screenshot_id}.webp")


def _session_filter(game_id: str, exclude_session_id: str | None) -> tuple[str, tuple[str, ...]]:
    if exclude_session_id is not None:
        return "sessions.game_id = ? AND sessions.status != 'open' AND sessions.id != ?", (
            game_id,
            exclude_session_id,
        )
    return "sessions.game_id = ? AND sessions.status != 'open'", (game_id,)


def _latest_note(
    connection: sqlite3.Connection,
    where_clause: str,
    params: tuple[str, ...],
    kind: str,
) -> sqlite3.Row | None:
    return connection.execute(
        f"""
        SELECT notes.id, notes.session_id, notes.path_or_text, notes.created_at
        FROM notes
        JOIN sessions ON sessions.id = notes.session_id
        WHERE {where_clause} AND notes.kind = ?
        ORDER BY notes.created_at DESC, notes.id DESC
        LIMIT 1
        """,
        (*params, kind),
    ).fetchone()


class MemoryRepository:
    def __init__(self, database: Database, data_root: Path) -> None:
        self._database = database
        self._root = media.validate_root(data_root, database.path)
        self._media = self._root / "media"

    def last_time(
        self, game_id: str, exclude_session_id: str | None = None
    ) -> LastTimeData | None:
        """Read one consistent snapshot of prior ended sessions for a game."""
        if not media.UUID.fullmatch(game_id):
            return None

        where_clause, params = _session_filter(game_id, exclude_session_id)
        with self._database.read_snapshot() as connection:
            game = connection.execute(
                "SELECT id, name, installed, launch_kind, launch_value, cover_path "
                "FROM games WHERE id = ? AND hidden = 0",
                (game_id,),
            ).fetchone()
            if game is None:
                return None

            totals = connection.execute(
                f"""
                SELECT COUNT(*) AS session_count, COALESCE(SUM(duration_sec), 0) AS total_playtime
                FROM sessions
                WHERE {where_clause}
                """,
                params,
            ).fetchone()
            last_row = connection.execute(
                f"""
                SELECT id, started_at, ended_at, duration_sec, status
                FROM sessions
                WHERE {where_clause}
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
            voice_row = _latest_note(connection, where_clause, params, "voice")
            text_row = _latest_note(connection, where_clause, params, "text")
            shot_rows: list[sqlite3.Row] = []
            if last_row is not None:
                shot_rows = connection.execute(
                    """
                    SELECT id, session_id, path FROM screenshots
                    WHERE is_last_moment = 1 AND session_id = ?
                    ORDER BY captured_at, id
                    """,
                    (last_row["id"],),
                ).fetchall()
            control_rows = connection.execute(
                "SELECT id, kind, path_or_text FROM controls WHERE game_id = ? ORDER BY created_at, id",
                (game_id,),
            ).fetchall()

        installed = bool(game["installed"])
        launch = (
            LaunchTarget(game["launch_kind"], game["launch_value"])
            if installed and game["launch_kind"] and game["launch_value"]
            else None
        )
        last_session = (
            LastSessionSummary(
                id=last_row["id"],
                started_at=last_row["started_at"],
                ended_at=last_row["ended_at"],
                duration_sec=last_row["duration_sec"],
                status=last_row["status"],
            )
            if last_row is not None
            else None
        )
        voice_note = self._build_voice(game_id, voice_row)
        text_note = (
            TextNoteSnapshot(
                id=text_row["id"],
                session_id=text_row["session_id"],
                created_at=text_row["created_at"],
                text=text_row["path_or_text"],
            )
            if text_row is not None
            else None
        )
        screenshots = self._build_screenshots(game_id, last_session, shot_rows)
        control_texts, control_images = self._build_controls(game_id, control_rows)
        cover_path = Path(game["cover_path"]) if game["cover_path"] else None
        return LastTimeData(
            game_id=game["id"],
            game_name=game["name"],
            installed=installed,
            launch_target=launch,
            last_session=last_session,
            total_playtime=totals["total_playtime"],
            session_count=totals["session_count"],
            voice_note=voice_note,
            text_note=text_note,
            screenshots=screenshots,
            controls=control_texts,
            control_images=control_images,
            cover_path=cover_path,
        )

    def timeline(
        self,
        game_id: str,
        cursor: SessionCursor | None = None,
        limit: int = 20,
    ) -> TimelinePage:
        """Return newest-first sessions and their screenshots and notes from one snapshot."""
        if limit < 1:
            raise ValueError("Timeline page size must be at least one.")
        limit = min(limit, 100)
        if not media.UUID.fullmatch(game_id):
            return TimelinePage(())

        with self._database.read_snapshot() as connection:
            visible = connection.execute(
                "SELECT 1 FROM games WHERE id = ? AND hidden = 0", (game_id,)
            ).fetchone()
            if visible is None:
                return TimelinePage(())
            if cursor is not None:
                session_rows = connection.execute(
                    """
                    SELECT id, started_at, ended_at, duration_sec, status
                    FROM sessions
                    WHERE game_id = ?
                      AND (started_at < ? OR (started_at = ? AND id < ?))
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (game_id, cursor.started_at, cursor.started_at, cursor.session_id, limit + 1),
                ).fetchall()
            else:
                session_rows = connection.execute(
                    """
                    SELECT id, started_at, ended_at, duration_sec, status
                    FROM sessions
                    WHERE game_id = ?
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (game_id, limit + 1),
                ).fetchall()

            has_more = len(session_rows) > limit
            page_rows = session_rows[:limit]
            if not page_rows:
                return TimelinePage(())

            session_ids = [row["id"] for row in page_rows]
            placeholders = ", ".join("?" for _ in session_ids)
            shot_rows = connection.execute(
                f"""
                SELECT id, session_id, path FROM screenshots
                WHERE session_id IN ({placeholders})
                ORDER BY captured_at, id
                """,
                session_ids,
            ).fetchall()
            note_rows = connection.execute(
                f"""
                SELECT id, session_id, kind, path_or_text, created_at FROM notes
                WHERE session_id IN ({placeholders})
                ORDER BY created_at DESC, id DESC
                """,
                session_ids,
            ).fetchall()

        shots_by_session: dict[str, list[Path]] = {sid: [] for sid in session_ids}
        for row in shot_rows:
            sid = row["session_id"]
            if media.UUID.fullmatch(sid) and media.UUID.fullmatch(row["id"]):
                relative = _screenshot_path(game_id, sid, row["id"])
                if row["path"] == relative.as_posix():
                    shots_by_session[sid].append(self._root.joinpath(*relative.parts))

        voices_by_session: dict[str, list[VoiceNoteSnapshot]] = {sid: [] for sid in session_ids}
        texts_by_session: dict[str, list[TextNoteSnapshot]] = {sid: [] for sid in session_ids}
        for row in note_rows:
            sid = row["session_id"]
            if row["kind"] == "voice":
                voice = self._build_voice(game_id, row)
                if voice is not None:
                    voices_by_session[sid].append(voice)
            elif row["kind"] == "text":
                texts_by_session[sid].append(
                    TextNoteSnapshot(
                        id=row["id"],
                        session_id=sid,
                        created_at=row["created_at"],
                        text=row["path_or_text"],
                    )
                )

        items = tuple(
            TimelineSession(
                id=row["id"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                duration_sec=row["duration_sec"],
                status=row["status"],
                screenshots=tuple(shots_by_session[row["id"]]),
                voice_notes=tuple(voices_by_session[row["id"]]),
                text_notes=tuple(texts_by_session[row["id"]]),
            )
            for row in page_rows
        )
        next_cursor = (
            SessionCursor(items[-1].started_at, items[-1].id) if has_more else None
        )
        return TimelinePage(items, next_cursor)

    def read_voice(self, path: Path) -> bytes | None:
        """Read bounded Ogg bytes for a validated, database-owned voice note."""
        if not path.is_relative_to(self._media):
            return None
        relative = path.relative_to(self._root)
        parts = relative.parts
        match = _VOICE_NAME.fullmatch(parts[3]) if len(parts) == 4 else None
        if (
            match is None
            or parts[0] != "media"
            or not all(media.UUID.fullmatch(part) for part in parts[1:3])
        ):
            return None

        game_id, session_id, note_id = parts[1], parts[2], match[1]
        try:
            with self._database.read() as connection:
                owned = connection.execute(
                    """
                    SELECT 1 FROM notes
                    JOIN sessions ON sessions.id = notes.session_id
                    WHERE notes.id = ? AND notes.session_id = ?
                      AND sessions.game_id = ? AND notes.kind = 'voice'
                      AND notes.path_or_text = ?
                    """,
                    (note_id, session_id, game_id, relative.as_posix()),
                ).fetchone()
                if owned is None:
                    return None
            canonical = self._root.joinpath(*parts)
            data = media.read_file(canonical, notes.MAX_VOICE_BYTES)
            return data if data is not None and notes.is_bounded_ogg(data) else None
        except FileNotFoundError:
            return None
        except (OSError, StorageError):
            LOGGER.warning("voice_note_read_incomplete")
            return None

    def autoplay_enabled(self) -> bool:
        with self._database.read() as connection:
            return settings.read_boolean(connection, _AUTOPLAY_KEY, default=True)

    def set_autoplay_enabled(self, enabled: bool) -> None:
        settings.write_boolean(self._database, _AUTOPLAY_KEY, enabled)

    def _build_voice(self, game_id: str, row: sqlite3.Row | None) -> VoiceNoteSnapshot | None:
        if row is None:
            return None
        session_id = row["session_id"]
        note_id = row["id"]
        if not (media.UUID.fullmatch(session_id) and media.UUID.fullmatch(note_id)):
            return None
        relative = notes.voice_path(game_id, session_id, note_id)
        if row["path_or_text"] != relative.as_posix():
            return None
        path = self._root.joinpath(*relative.parts)
        return VoiceNoteSnapshot(
            id=note_id,
            session_id=session_id,
            created_at=row["created_at"],
            path=path,
            available=self._voice_available(path),
        )

    def _voice_available(self, path: Path) -> bool:
        try:
            prefix = media.read_file(path, notes.MAX_VOICE_BYTES, prefix_bytes=_MIN_OGG_BYTES)
        except (FileNotFoundError, OSError):
            return False
        return (
            prefix is not None
            and len(prefix) == _MIN_OGG_BYTES
            and prefix.startswith(_OGG_PREFIX)
        )

    def _build_screenshots(
        self,
        game_id: str,
        last_session: LastSessionSummary | None,
        rows: list[sqlite3.Row],
    ) -> tuple[Path, ...]:
        if last_session is None or not media.UUID.fullmatch(last_session.id):
            return ()
        paths = []
        for row in rows:
            if media.UUID.fullmatch(row["id"]):
                relative = _screenshot_path(game_id, last_session.id, row["id"])
                if row["path"] == relative.as_posix():
                    paths.append(self._root.joinpath(*relative.parts))
        return tuple(paths)

    def _build_controls(
        self, game_id: str, rows: list[sqlite3.Row]
    ) -> tuple[tuple[str, ...], tuple[Path, ...]]:
        texts: list[str] = []
        images: list[Path] = []
        for row in rows:
            if row["kind"] == "text":
                texts.append(row["path_or_text"])
            elif media.UUID.fullmatch(row["id"]):
                relative = controls_storage.control_image_path(game_id, row["id"])
                if row["path_or_text"] == relative.as_posix():
                    images.append(self._root.joinpath(*relative.parts))
        return tuple(texts), tuple(images)
