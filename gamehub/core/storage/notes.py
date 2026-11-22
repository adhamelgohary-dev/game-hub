"""Store session text, microphone notes, and the close-prompt preference."""

import json
import logging
import re
import sqlite3
from pathlib import Path, PurePosixPath
from time import time_ns
from uuid import uuid4

from gamehub.core.storage import media
from gamehub.core.storage.db import Database, StorageError

LOGGER = logging.getLogger(__name__)
MAX_TEXT_LENGTH = 8_000
_MAX_VOICE_BYTES = 8 * 1024 * 1024
_FILENAME = re.compile(rf"note_{media.UUID_PATTERN}\.ogg(?:\.tmp)?")
_PROMPT_KEY = "memory.prompt_on_end"


def _relative(game_id: str, session_id: str, note_id: str) -> PurePosixPath:
    return PurePosixPath("media", game_id, session_id, f"note_{note_id}.ogg")


def _session_game(connection: sqlite3.Connection, session_id: str) -> str:
    row = connection.execute("SELECT game_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise ValueError("The game session for this note is unavailable.")
    return row["game_id"]


def _insert_note(
    connection: sqlite3.Connection, note_id: str, session_id: str, kind: str, value: str, source: str
) -> None:
    connection.execute(
        "INSERT INTO notes (id, session_id, kind, path_or_text, created_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (note_id, session_id, kind, value, time_ns() // 1_000_000, source),
    )


class NoteRepository:
    def __init__(self, database: Database, data_root: Path) -> None:
        self._database = database
        self._root = media.validate_root(data_root, database.path)
        self._media = self._root / "media"

    def save_text(self, session_id: str, text: str) -> str:
        if not text.strip() or "\0" in text or len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Enter a nonblank text note within the length limit.")
        note_id = str(uuid4())
        with self._database.write() as connection:
            _session_game(connection, session_id)
            _insert_note(connection, note_id, session_id, "text", text, "popup")
        return note_id

    def save_voice(self, session_id: str, data: bytes, source: str) -> str:
        if source not in {"popup", "hotkey"}:
            raise ValueError("Unknown voice note source.")
        if not data.startswith(b"OggS\x00") or not 27 <= len(data) <= _MAX_VOICE_BYTES:
            raise ValueError("Expected a bounded Ogg voice note.")

        note_id = str(uuid4())
        try:
            with self._database.write() as connection:
                game_id = _session_game(connection, session_id)
                if not (media.UUID.fullmatch(game_id) and media.UUID.fullmatch(session_id)):
                    raise StorageError("Game Hub could not validate the note's session.")
                relative = _relative(game_id, session_id, note_id)
                media.stage_file(self._media, self._root.joinpath(*relative.parts), data)
                _insert_note(connection, note_id, session_id, "voice", relative.as_posix(), source)
        except OSError as error:
            raise StorageError("Game Hub could not save the voice note.") from error
        return note_id

    def prompt_enabled(self) -> bool:
        with self._database.read() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (_PROMPT_KEY,)).fetchone()
        if row is not None:
            try:
                value = json.loads(row["value"])
            except ValueError:
                value = None
            if isinstance(value, bool):
                return value
            LOGGER.warning("invalid_setting key=%s", _PROMPT_KEY)
        return True

    def set_prompt_enabled(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("The close-prompt setting must be a boolean.")
        with self._database.write() as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (_PROMPT_KEY, json.dumps(enabled)),
            )

    def recover_files(self) -> None:
        """Remove abandoned generated clips while preserving recorded notes and other media."""
        with self._database.write() as connection:
            rows = connection.execute(
                "SELECT notes.id, session_id, path_or_text, game_id FROM notes "
                "JOIN sessions ON sessions.id = notes.session_id WHERE notes.kind = 'voice'"
            )
            owned = {
                row["path_or_text"] for row in rows
                if all(media.UUID.fullmatch(row[key]) for key in ("game_id", "session_id", "id"))
                and row["path_or_text"] == _relative(row["game_id"], row["session_id"], row["id"]).as_posix()
            }
            media.reconcile_files(self._media, owned, _FILENAME, "voice_note_reconciliation_incomplete")
