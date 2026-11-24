"""Persist discovered games, explicit match targets, and library queries."""

import ntpath
import os
import sqlite3
import stat
from collections import defaultdict
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
    cover_path = CASE WHEN games.custom_cover = 1 THEN games.cover_path ELSE excluded.cover_path END,
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
        source_id=row["source_id"],
        protection_mode=row["protection_mode"],
        exit_after_launch=bool(row["exit_after_launch"]),
        custom_cover=bool(row["custom_cover"]),
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

    def set_protection(
        self,
        game_id: str,
        protection_mode: str,
        *,
        exit_after_launch: bool | None = None,
    ) -> None:
        if protection_mode not in {"auto", "strict", "full"}:
            raise ValueError("Invalid protection mode.")
        with self._database.write() as connection:
            if exit_after_launch is None:
                connection.execute(
                    "UPDATE games SET protection_mode = ? WHERE id = ?",
                    (protection_mode, game_id),
                )
            else:
                connection.execute(
                    "UPDATE games SET protection_mode = ?, exit_after_launch = ? WHERE id = ?",
                    (protection_mode, int(exit_after_launch), game_id),
                )

    def list_target_basenames(self) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, set[str]] = defaultdict(set)
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT game_id, kind, match_key FROM game_targets WHERE kind = 'exe_path'"
            ).fetchall()
            for row in rows:
                base = ntpath.normcase(ntpath.basename(row["match_key"]))
                if base:
                    grouped[row["game_id"]].add(base)
        return {game_id: tuple(sorted(names)) for game_id, names in grouped.items()}

    def set_custom_cover(self, game_id: str, cover_path: Path | None, *, custom: bool = True) -> None:
        with self._database.write() as connection:
            connection.execute(
                "UPDATE games SET cover_path = ?, custom_cover = ? WHERE id = ?",
                (str(cover_path) if cover_path is not None else None, int(custom), game_id),
            )

    def reset_protection_defaults(self) -> None:
        with self._database.write() as connection:
            connection.execute("UPDATE games SET protection_mode = 'auto', exit_after_launch = 0")

    def list_scan_folders(self) -> tuple[Path, ...]:
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT path FROM scan_folders ORDER BY added_at ASC, path ASC"
            ).fetchall()
            return tuple(Path(row["path"]) for row in rows)

    def add_scan_folder(self, folder: Path) -> Path:
        safe = local_path(folder)
        if safe is None or not safe.is_dir():
            raise ValueError("Select an accessible local folder.")
        with self._database.write() as connection:
            connection.execute(
                "INSERT INTO scan_folders (path, added_at) VALUES (?, ?) "
                "ON CONFLICT (path) DO NOTHING",
                (str(safe), time_ns() // 1_000_000),
            )
        return safe

    def remove_scan_folder(self, folder: Path) -> None:
        norm = str(folder)
        with self._database.write() as connection:
            connection.execute("DELETE FROM scan_folders WHERE path = ?", (norm,))
            connection.execute("DELETE FROM scan_folder_choices WHERE folder_path = ?", (norm,))

    def list_scan_choices(self, folder: Path | None = None) -> dict[str, tuple[str, str | None]]:
        with self._database.read() as connection:
            if folder is None:
                rows = connection.execute(
                    "SELECT exe_path, decision, custom_name FROM scan_folder_choices"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT exe_path, decision, custom_name FROM scan_folder_choices WHERE folder_path = ?",
                    (str(folder),),
                ).fetchall()
            return {
                os.path.normcase(row["exe_path"]): (row["decision"], row["custom_name"])
                for row in rows
            }

    def save_scan_choices(
        self,
        folder: Path,
        choices: list[tuple[Path, str, str | None]],
    ) -> None:
        now = time_ns() // 1_000_000
        folder_str = str(folder)
        with self._database.write() as connection:
            connection.executemany(
                """
                INSERT INTO scan_folder_choices (exe_path, folder_path, decision, custom_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (exe_path) DO UPDATE SET
                    folder_path = excluded.folder_path,
                    decision = excluded.decision,
                    custom_name = excluded.custom_name,
                    updated_at = excluded.updated_at
                """,
                [
                    (os.path.normcase(str(exe)), folder_str, decision, custom_name, now)
                    for exe, decision, custom_name in choices
                ],
            )
