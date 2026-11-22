"""Store and consume deferred post-launch note prompts for Strict-mode games."""

from dataclasses import dataclass
from uuid import uuid4

from gamehub.core.storage.db import Database


@dataclass(frozen=True, slots=True)
class PendingNote:
    id: str
    game_id: str
    launched_at: int


class PendingNoteRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, game_id: str, launched_at: int) -> str:
        pending_id = str(uuid4())
        with self._database.write() as connection:
            connection.execute(
                "INSERT INTO pending_notes (id, game_id, launched_at) VALUES (?, ?, ?)",
                (pending_id, game_id, launched_at),
            )
        return pending_id

    def list_pending(self) -> tuple[PendingNote, ...]:
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT id, game_id, launched_at FROM pending_notes ORDER BY launched_at DESC, id"
            ).fetchall()
            return tuple(
                PendingNote(row["id"], row["game_id"], row["launched_at"]) for row in rows
            )

    def consume(self, pending_id: str) -> None:
        with self._database.write() as connection:
            connection.execute("DELETE FROM pending_notes WHERE id = ?", (pending_id,))

    def create_deferred_session(self, game_id: str, started_at: int, ended_at: int) -> str:
        """Create a completed session row so a deferred post-launch note links cleanly."""
        session_id = str(uuid4())
        safe_end = max(started_at, ended_at)
        with self._database.write() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, game_id, started_at, ended_at, last_seen_at, duration_sec, status)
                VALUES (?, ?, ?, ?, ?, 0, 'completed')
                """,
                (session_id, game_id, started_at, safe_end, safe_end),
            )
        return session_id
