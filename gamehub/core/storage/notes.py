"""Store session text, microphone notes, and the close-prompt preference."""

import re
import sqlite3
from pathlib import Path, PurePosixPath
from time import time_ns
from uuid import uuid4

from gamehub.core.storage import media, settings
from gamehub.core.storage.db import Database, StorageError

MAX_TEXT_LENGTH = 8_000
MAX_VOICE_BYTES = 8 * 1024 * 1024
_FILENAME = re.compile(rf"note_{media.UUID_PATTERN}\.ogg(?:\.tmp)?")
_PROMPT_KEY = "memory.prompt_on_end"


def voice_path(game_id: str, session_id: str, note_id: str) -> PurePosixPath:
    return PurePosixPath("media", game_id, session_id, f"note_{note_id}.ogg")


def is_bounded_ogg(data: bytes) -> bool:
    return data.startswith(b"OggS\x00") and 27 <= len(data) <= MAX_VOICE_BYTES


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
        if not is_bounded_ogg(data):
            raise ValueError("Expected a bounded Ogg voice note.")

        note_id = str(uuid4())
        try:
            with self._database.write() as connection:
                game_id = _session_game(connection, session_id)
                if not (media.UUID.fullmatch(game_id) and media.UUID.fullmatch(session_id)):
                    raise StorageError("GameRewind could not validate the note's session.")
                relative = voice_path(game_id, session_id, note_id)
                media.stage_file(self._media, self._root.joinpath(*relative.parts), data)
                _insert_note(connection, note_id, session_id, "voice", relative.as_posix(), source)
        except OSError as error:
            raise StorageError("GameRewind could not save the voice note.") from error
        return note_id

    def prompt_enabled(self) -> bool:
        with self._database.read() as connection:
            return settings.read_boolean(connection, _PROMPT_KEY, default=True)

    def set_prompt_enabled(self, enabled: bool) -> None:
        settings.write_boolean(self._database, _PROMPT_KEY, enabled)

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
                and row["path_or_text"] == voice_path(row["game_id"], row["session_id"], row["id"]).as_posix()
            }
            media.reconcile_files(self._media, owned, _FILENAME, "voice_note_reconciliation_incomplete")
