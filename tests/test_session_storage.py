import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gamehub.core.library.models import (
    DetectedGame,
    DiscoveryBatch,
    GameSource,
    GameTarget,
)
from gamehub.core.sessions.models import WatchTarget
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.sessions import SessionRepository


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "gamehub.db")


def _add_game(
    database: Database, source: GameSource, source_id: str, *targets: GameTarget
) -> str:
    game = DetectedGame(source, source_id, f"Fixture {source_id}", targets=targets)
    (game_id,) = LibraryRepository(database).reconcile(source, DiscoveryBatch((game,), "partial"))
    return game_id


def _session(database: Database, session_id: str) -> sqlite3.Row:
    with database.read() as reader:
        return reader.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def test_open_retries_reuse_session_and_games_can_overlap(database: Database) -> None:
    first_game = _add_game(database, GameSource.STEAM, "1001")
    second_game = _add_game(database, GameSource.STEAM, "1002")
    repository = SessionRepository(database)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, retry = workers.map(lambda timestamp: repository.open(first_game, timestamp), (1000, 1000))
    second = repository.open(second_game, 2000)

    assert first == retry
    assert first != second
    row = _session(database, first)
    assert (row["started_at"], row["last_seen_at"], row["duration_sec"]) == (1000, 1000, 0)
    assert row["status"] == "open"
    assert _session(database, second)["status"] == "open"


def test_checkpoint_and_finish_are_safe_to_retry(database: Database) -> None:
    game = _add_game(database, GameSource.STEAM, "1001")
    repository = SessionRepository(database)
    session = repository.open(game, 1000)

    repository.checkpoint(session, 4000, 3)
    repository.checkpoint(session, 2000, 1)
    repository.checkpoint(session, 3000, 4)  # The wall clock moved backward.
    row = _session(database, session)
    assert (row["last_seen_at"], row["duration_sec"]) == (4000, 4)

    repository.finish(session, 3000, 3, "completed")
    repository.finish(session, 9000, 8, "interrupted")
    repository.checkpoint(session, 10_000, 9)
    row = _session(database, session)
    assert (row["status"], row["ended_at"], row["duration_sec"]) == ("completed", 4000, 4)
    summary = LibraryRepository(database).get_game(game)
    assert (summary.last_played, summary.total_playtime) == (1000, 4)


def test_recovery_closes_open_sessions_at_their_last_observation(database: Database) -> None:
    first_game = _add_game(database, GameSource.STEAM, "1001")
    second_game = _add_game(database, GameSource.EPIC, "FixtureEpic")
    repository = SessionRepository(database)
    completed = repository.open(first_game, 1000)
    repository.finish(completed, 5000, 4, "completed")
    interrupted = repository.open(first_game, 10_000)
    repository.checkpoint(interrupted, 15_000, 5)
    fresh = repository.open(second_game, 20_000)

    recovered = SessionRepository(Database(database.path))
    assert recovered.recover() == 2
    assert recovered.recover() == 0
    assert _session(database, completed)["status"] == "completed"
    row = _session(database, interrupted)
    assert (row["status"], row["ended_at"], row["duration_sec"]) == ("interrupted", 15_000, 5)
    row = _session(database, fresh)
    assert (row["status"], row["ended_at"], row["duration_sec"]) == ("interrupted", 20_000, 0)

    restarted = recovered.open(first_game, 1_000_000)
    assert restarted != interrupted
    assert LibraryRepository(database).get_game(first_game).total_playtime == 9


def test_invalid_checkpoints_and_status_leave_session_unchanged(database: Database) -> None:
    game = _add_game(database, GameSource.STEAM, "1001")
    repository = SessionRepository(database)
    session = repository.open(game, 1000)

    with pytest.raises(ValueError, match="cannot be negative"):
        repository.checkpoint(session, 2000, -1)
    with pytest.raises(ValueError, match="terminal status"):
        repository.finish(session, 2000, 1, "open")
    with pytest.raises(ValueError, match="cannot be negative"):
        repository.finish(session, 2000, -1, "completed")

    assert _session(database, session)["status"] == "open"


def test_watch_targets_skip_collisions_and_prefer_explicit_game(
    database: Database, tmp_path: Path
) -> None:
    exe = tmp_path / "Fixture.exe"
    exe.touch()
    key = os.path.normcase(str(exe))
    target = GameTarget("exe_path", key)
    package = GameTarget("package_id", "fixture_game_family")
    steam = _add_game(database, GameSource.STEAM, "1001", target)
    _add_game(database, GameSource.EPIC, "FixtureEpic", target)
    xbox = _add_game(database, GameSource.XBOX, "FixtureXbox", package)
    repository = SessionRepository(database)
    library = LibraryRepository(database)

    assert repository.watch_targets() == (WatchTarget(xbox, package.kind, package.match_key),)
    library.assign_target(steam, exe)
    assert repository.watch_targets() == (
        WatchTarget(steam, target.kind, target.match_key),
        WatchTarget(xbox, package.kind, package.match_key),
    )

    library.reconcile(GameSource.STEAM, DiscoveryBatch())
    assert repository.watch_targets() == (WatchTarget(xbox, package.kind, package.match_key),)
    with database.write() as writer:
        writer.execute("UPDATE games SET hidden = 1 WHERE id = ?", (xbox,))
    assert repository.watch_targets() == ()
