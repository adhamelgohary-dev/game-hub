"""Persist discovered games, explicit match targets, and library queries."""

import os
import sqlite3
import stat
from pathlib import Path
from time import time_ns
from uuid import uuid4

from gamehub.core.library.models import (
    DetectedGame,
    DiscoveryBatch,
    GameSource,
    GameSummary,
    LaunchTarget,
)
from gamehub.core.library.paths import local_path
from gamehub.core.storage.db import Database

_UPSERT_GAME = """
INSERT INTO games (
    id, source, source_id, name, install_dir, cover_path, added_at, launch_kind, launch_value
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source, source_id) DO UPDATE SET
    name = excluded.name,
    install_dir = excluded.install_dir,
    cover_path = excluded.cover_path,
    launch_kind = excluded.launch_kind,
    launch_value = excluded.launch_value,
    installed = 1
RETURNING id
"""

_GAME_SUMMARIES = """
SELECT game.*,
    MAX(session.started_at) AS last_played,
    COALESCE(SUM(session.duration_sec), 0) AS total_playtime,
    game.installed AND EXISTS (
        SELECT 1 FROM game_targets own
        WHERE own.game_id = game.id AND (own.origin = 'manual' OR NOT EXISTS (
            SELECT 1 FROM game_targets other
            JOIN games other_game ON other_game.id = other.game_id
            WHERE other.kind = own.kind AND other.match_key = own.match_key
                AND other.game_id <> own.game_id
                AND (other.origin = 'manual' OR other_game.installed = 1)
        ))
    ) AS tracking
FROM games game
LEFT JOIN sessions session ON session.game_id = game.id
WHERE game.hidden = 0
"""


def _required_exe(exe: Path) -> Path:
    try:
        path = local_path(exe)
        if path is not None and path.suffix.lower() == ".exe":
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and not (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                return path
    except OSError as error:
        raise ValueError("Select an accessible local executable.") from error
    raise ValueError("Select an accessible local executable.")


def _upsert_game(connection: sqlite3.Connection, game: DetectedGame, game_id: str) -> str:
    launch = game.launch_target
    row = connection.execute(
        _UPSERT_GAME,
        (
            game_id,
            game.source,
            game.source_id,
            game.name,
            str(game.install_dir) if game.install_dir is not None else None,
            str(game.cover_path) if game.cover_path is not None else None,
            time_ns() // 1_000_000,
            launch.kind if launch is not None else None,
            launch.value if launch is not None else None,
        ),
    ).fetchone()
    return row["id"]


def _manual_owner(connection: sqlite3.Connection, match_key: str) -> str | None:
    row = connection.execute(
        "SELECT game_id FROM game_targets "
        "WHERE kind = 'exe_path' AND match_key = ? AND origin = 'manual'",
        (match_key,),
    ).fetchone()
    return row["game_id"] if row is not None else None


def _set_manual_target(connection: sqlite3.Connection, game_id: str, match_key: str) -> None:
    connection.execute(
        """
        INSERT INTO game_targets (id, game_id, kind, match_key, origin)
        VALUES (?, ?, 'exe_path', ?, 'manual')
        ON CONFLICT (game_id, kind, match_key) DO UPDATE SET origin = 'manual'
        """,
        (str(uuid4()), game_id, match_key),
    )


def _summary(row: sqlite3.Row) -> GameSummary:
    installed = bool(row["installed"])
    launch = row["launch_kind"]
    return GameSummary(
        id=row["id"],
        name=row["name"],
        source=GameSource(row["source"]),
        install_dir=Path(row["install_dir"]) if row["install_dir"] is not None else None,
        cover_path=Path(row["cover_path"]) if row["cover_path"] is not None else None,
        last_played=row["last_played"],
        total_playtime=row["total_playtime"],
        installed=installed,
        launch_target=LaunchTarget(launch, row["launch_value"]) if installed and launch else None,
        tracking=bool(row["tracking"]),
    )


class LibraryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def reconcile(self, source: GameSource, batch: DiscoveryBatch) -> tuple[str, ...]:
        """Apply valid sightings and archive missing games only on a complete scan."""
        if source == GameSource.MANUAL or batch.state not in {"complete", "partial", "unavailable"}:
            raise ValueError("Invalid library discovery batch.")
        if batch.state == "unavailable":
            return ()

        with self._database.write() as connection:
            installed = set()
            if batch.state == "complete":
                installed = {
                    row["id"]
                    for row in connection.execute(
                        "SELECT id FROM games WHERE source = ? AND installed = 1", (source,)
                    )
                }

            seen: dict[str, None] = {}
            for game in batch.games:
                if game.source != source:
                    raise ValueError("Discovery returned a game for a different source.")
                game_id = _upsert_game(connection, game, str(uuid4()))
                seen[game_id] = None
                connection.execute(
                    "DELETE FROM game_targets WHERE game_id = ? AND origin = 'discovery'",
                    (game_id,),
                )
                connection.executemany(
                    """
                    INSERT INTO game_targets (id, game_id, kind, match_key, origin)
                    VALUES (?, ?, ?, ?, 'discovery')
                    ON CONFLICT (game_id, kind, match_key) DO NOTHING
                    """,
                    ((str(uuid4()), game_id, entry.kind, entry.match_key) for entry in game.targets),
                )

            missing = sorted(installed.difference(seen))
            connection.executemany(
                "UPDATE games SET installed = 0 WHERE id = ?", ((game_id,) for game_id in missing)
            )
            return (*seen, *missing)

    def add_manual(self, exe: Path) -> str:
        path = _required_exe(exe)
        match_key = os.path.normcase(str(path))
        with self._database.write() as connection:
            owner = _manual_owner(connection, match_key)
            if owner is not None:
                return owner

            game_id = str(uuid4())
            game = DetectedGame(
                source=GameSource.MANUAL,
                source_id=game_id,
                name=path.stem,
                install_dir=path.parent,
                launch_target=LaunchTarget("exe", str(path)),
            )
            _upsert_game(connection, game, game_id)
            _set_manual_target(connection, game_id, match_key)
            return game_id

    def assign_target(self, game_id: str, exe: Path) -> str:
        path = _required_exe(exe)
        match_key = os.path.normcase(str(path))
        with self._database.write() as connection:
            game = connection.execute("SELECT source FROM games WHERE id = ?", (game_id,)).fetchone()
            if game is None or game["source"] == GameSource.MANUAL:
                raise ValueError("Select a launcher game before assigning its executable.")
            owner = _manual_owner(connection, match_key)
            if owner is not None and owner != game_id:
                raise ValueError("This executable is already assigned to another game.")

            connection.execute(
                "DELETE FROM game_targets WHERE game_id = ? AND kind = 'exe_path' "
                "AND origin = 'manual' AND match_key <> ?",
                (game_id, match_key),
            )
            _set_manual_target(connection, game_id, match_key)
            return game_id

    def list_games(self) -> tuple[GameSummary, ...]:
        with self._database.read() as connection:
            rows = connection.execute(
                _GAME_SUMMARIES + "GROUP BY game.id ORDER BY game.name COLLATE NOCASE, game.id"
            )
            return tuple(_summary(row) for row in rows)

    def get_game(self, game_id: str) -> GameSummary | None:
        with self._database.read() as connection:
            row = connection.execute(
                _GAME_SUMMARIES + "AND game.id = ? GROUP BY game.id", (game_id,)
            ).fetchone()
            return _summary(row) if row is not None else None
