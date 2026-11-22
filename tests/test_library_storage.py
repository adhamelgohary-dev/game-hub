import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from gamehub.core.library.models import (
    DetectedGame,
    DiscoveryBatch,
    GameSource,
    GameTarget,
    LaunchTarget,
)
from gamehub.core.storage import db
from gamehub.core.storage.library import LibraryRepository


@pytest.fixture
def database(tmp_path: Path) -> db.Database:
    return db.Database(tmp_path / "store with spaces" / "gamehub.db")


def test_initial_schema_and_read_connection(database: db.Database) -> None:
    with database.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        assert {row["name"] for row in tables} == {
            "games", "game_targets", "sessions", "screenshots", "notes", "settings", "controls",
        }

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    with pytest.raises(db.StorageError), database.read() as reader:
        reader.execute("CREATE TABLE forbidden (id INTEGER)")


def test_schema_and_version_roll_back_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "gamehub.db"
    schema = (*db.INITIAL_SCHEMA, "CREATE TABLE invalid")
    with monkeypatch.context() as patch:
        patch.setattr(db, "INITIAL_SCHEMA", schema)
        with pytest.raises(db.StorageError):
            db.Database(path)

    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
        assert raw.execute("SELECT name FROM sqlite_schema").fetchall() == []

    with db.Database(path).read() as repaired:
        assert repaired.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_newer_schema_blocks_writes(tmp_path: Path) -> None:
    path = tmp_path / "gamehub.db"
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("PRAGMA user_version = 42")

    with pytest.raises(db.StorageError, match="newer version"):
        db.Database(path)

    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 42
        assert raw.execute("SELECT name FROM sqlite_schema").fetchall() == []


def test_refresh_preserves_history_and_only_archives_complete_source(
    database: db.Database, tmp_path: Path
) -> None:
    repository = LibraryRepository(database)
    steam = DetectedGame(
        GameSource.STEAM,
        "1001",
        "Fixture Steam Game",
        install_dir=tmp_path,
        launch_target=LaunchTarget("steam_uri", "steam://rungameid/1001"),
    )
    epic = DetectedGame(GameSource.EPIC, "fixture-epic", "Fixture Epic Game")
    steam_id, = repository.reconcile(GameSource.STEAM, DiscoveryBatch((steam,)))
    epic_id, = repository.reconcile(GameSource.EPIC, DiscoveryBatch((epic,)))

    with database.write() as writer:
        writer.executemany(
            """
            INSERT INTO sessions (id, game_id, started_at, ended_at, last_seen_at, duration_sec,
                status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ("session-1", steam_id, 1_000, 11_000, 11_000, 10, "completed"),
                ("session-2", steam_id, 20_000, 22_000, 22_000, 2, "interrupted"),
                ("session-3", steam_id, 30_000, None, 31_000, 1, "open"),
            ),
        )

    assert repository.reconcile(GameSource.STEAM, DiscoveryBatch(state="partial")) == ()
    assert repository.reconcile(GameSource.STEAM, DiscoveryBatch(state="unavailable")) == ()
    assert repository.get_game(steam_id).installed
    assert repository.reconcile(GameSource.STEAM, DiscoveryBatch()) == (steam_id,)
    archived = repository.get_game(steam_id)
    assert (archived.installed, archived.launch_target) == (False, None)
    assert (archived.last_played, archived.total_playtime) == (30_000, 13)
    assert repository.get_game(epic_id).installed

    renamed = replace(steam, name="Fixture Steam Game Reinstalled")
    reopened = LibraryRepository(db.Database(database.path))
    assert reopened.reconcile(GameSource.STEAM, DiscoveryBatch((renamed,))) == (steam_id,)
    assert reopened.get_game(steam_id).name == renamed.name
    assert reopened.get_game(steam_id).total_playtime == 13


def test_manual_executable_is_deduplicated_and_persisted(
    database: db.Database, tmp_path: Path
) -> None:
    repository = LibraryRepository(database)
    exe = tmp_path / "Fixture Game.exe"
    exe.write_bytes(b"synthetic executable selection")

    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = tuple(workers.map(repository.add_manual, (exe, exe)))

    assert ids[0] == ids[1]
    if os.name == "nt":
        assert repository.add_manual(exe.with_name(exe.name.swapcase())) == ids[0]
    games = LibraryRepository(db.Database(database.path)).list_games()
    assert len(games) == 1
    game = games[0]
    assert game.id == ids[0]
    assert game.name == "Fixture Game"
    assert game.source == GameSource.MANUAL
    assert game.install_dir == exe.parent
    assert game.launch_target == LaunchTarget("exe", str(exe))
    assert game.tracking

    with database.read() as reader:
        row = reader.execute("SELECT id, source_id FROM games").fetchone()
        assert row["id"] == row["source_id"]


def test_invalid_manual_paths_are_rejected(database: db.Database, tmp_path: Path) -> None:
    repository = LibraryRepository(database)
    directory = tmp_path / "Folder.exe"
    directory.mkdir()
    non_exe = tmp_path / "Fixture.txt"
    non_exe.touch()
    for path in (Path("relative.exe"), tmp_path / "missing.exe", directory, non_exe):
        with pytest.raises(ValueError, match="local executable"):
            repository.add_manual(path)

    assert repository.list_games() == ()


def test_explicit_owner_resolves_duplicate_targets_and_survives_discovery(
    database: db.Database, tmp_path: Path
) -> None:
    repository = LibraryRepository(database)
    exe = tmp_path / "Shared.exe"
    exe.touch()
    target = GameTarget("exe_path", os.path.normcase(str(exe)))
    steam = DetectedGame(GameSource.STEAM, "1001", "Fixture Steam", targets=(target,))
    epic = DetectedGame(GameSource.EPIC, "fixture-epic", "Fixture Epic", targets=(target,))
    steam_id, = repository.reconcile(GameSource.STEAM, DiscoveryBatch((steam,)))
    epic_id, = repository.reconcile(GameSource.EPIC, DiscoveryBatch((epic,)))

    assert not repository.get_game(steam_id).tracking
    assert not repository.get_game(epic_id).tracking
    assert repository.assign_target(steam_id, exe) == steam_id
    assert repository.add_manual(exe) == steam_id
    with pytest.raises(ValueError, match="already assigned"):
        repository.assign_target(epic_id, exe)

    repository.reconcile(GameSource.STEAM, DiscoveryBatch((replace(steam, targets=()),)))
    assert repository.get_game(steam_id).tracking
    assert not repository.get_game(epic_id).tracking


def test_invalid_batch_rolls_back_seen_rows(database: db.Database) -> None:
    repository = LibraryRepository(database)
    steam = DetectedGame(GameSource.STEAM, "1001", "Fixture Steam")
    epic = DetectedGame(GameSource.EPIC, "fixture-epic", "Fixture Epic")

    with pytest.raises(ValueError, match="different source"):
        repository.reconcile(GameSource.STEAM, DiscoveryBatch((steam, epic)))

    assert repository.list_games() == ()


def test_session_constraints_keep_relationships_valid(database: db.Database, tmp_path: Path) -> None:
    repository = LibraryRepository(database)
    exe = tmp_path / "Fixture.exe"
    exe.touch()
    game_id = repository.add_manual(exe)
    insert_open = """
    INSERT INTO sessions (id, game_id, started_at, last_seen_at, status)
    VALUES (?, ?, 1000, 1000, 'open')
    """
    with pytest.raises(db.StorageError), database.write() as writer:
        writer.execute(insert_open, ("session-1", "missing-game"))

    with database.write() as writer:
        writer.execute(insert_open, ("session-1", game_id))

    with pytest.raises(db.StorageError), database.write() as writer:
        writer.execute(insert_open, ("session-2", game_id))

    with database.read() as reader:
        assert [row["id"] for row in reader.execute("SELECT id FROM sessions")] == ["session-1"]
