"""Persist observed play sessions and provide exact targets to the watcher."""

from uuid import uuid4

from gamehub.core.sessions.models import WatchTarget
from gamehub.core.storage.db import Database

_WATCH_TARGETS = """
SELECT own.game_id, own.kind, own.match_key
FROM game_targets own
JOIN games game ON game.id = own.game_id
WHERE game.installed = 1 AND game.hidden = 0
AND (own.origin = 'manual' OR NOT EXISTS (
    SELECT 1 FROM game_targets other
    JOIN games other_game ON other_game.id = other.game_id
    WHERE other.kind = own.kind AND other.match_key = own.match_key
        AND other.game_id <> own.game_id
        AND (other.origin = 'manual' OR other_game.installed = 1)
))
ORDER BY own.kind, own.match_key, own.game_id
"""


class SessionRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def open(self, game_id: str, started_at: int) -> str:
        """Open one session per game and reuse it if the same start is retried."""
        with self._database.write() as connection:
            existing = connection.execute(
                "SELECT id FROM sessions WHERE game_id = ? AND status = 'open'",
                (game_id,),
            ).fetchone()
            if existing is not None:
                return existing["id"]

            session_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO sessions (id, game_id, started_at, last_seen_at, status)
                VALUES (?, ?, ?, ?, 'open')
                """,
                (session_id, game_id, started_at, started_at),
            )
            return session_id

    def checkpoint(self, session_id: str, seen_at: int, duration_sec: int) -> None:
        """Persist confirmed playtime while the session remains open."""
        if duration_sec < 0:
            raise ValueError("Observed playtime cannot be negative.")
        with self._database.write() as connection:
            connection.execute(
                """
                UPDATE sessions SET last_seen_at = MAX(last_seen_at, ?), duration_sec = ?
                WHERE id = ? AND status = 'open' AND duration_sec <= ?
                """,
                (seen_at, duration_sec, session_id, duration_sec),
            )

    def finish(self, session_id: str, ended_at: int, duration_sec: int, status: str) -> None:
        """Finalize once, retaining the latest committed playtime if a write is retried."""
        if status not in {"completed", "interrupted"}:
            raise ValueError("A finished session must have a terminal status.")
        if duration_sec < 0:
            raise ValueError("Observed playtime cannot be negative.")
        with self._database.write() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = ?, ended_at = MAX(last_seen_at, ?), duration_sec = MAX(duration_sec, ?)
                WHERE id = ? AND status = 'open'
                """,
                (status, ended_at, duration_sec, session_id),
            )

    def recover(self) -> int:
        """Close sessions left open by the previous run at their last committed checkpoint."""
        with self._database.write() as connection:
            update = connection.execute(
                "UPDATE sessions SET status = 'interrupted', ended_at = last_seen_at "
                "WHERE status = 'open'"
            )
            return update.rowcount

    def watch_targets(self) -> tuple[WatchTarget, ...]:
        """Offer installed, unambiguous targets and prioritize explicit ownership."""
        with self._database.read() as connection:
            return tuple(
                WatchTarget(row["game_id"], row["kind"], row["match_key"])
                for row in connection.execute(_WATCH_TARGETS)
            )
