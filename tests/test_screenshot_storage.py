import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from gamehub.core.storage import db
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.media import protect_directory
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository


@pytest.fixture
def screenshot_store(tmp_path: Path):
    database = db.Database(tmp_path / "gamehub.db")
    executable = tmp_path / "Fixture.exe"
    executable.touch()
    game = LibraryRepository(database).add_manual(executable)
    sessions = SessionRepository(database)
    session = sessions.open(game, 1000)
    return database, ScreenshotRepository(database, tmp_path), sessions, game, session


def _frame(index: int) -> bytes:
    return b"RIFF\x04\x00\x00\x00WEBP" + bytes([index])


def _legacy_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        for statement in db.INITIAL_SCHEMA:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO games (id, source, source_id, name, added_at) "
            "VALUES ('game-1', 'steam', '1001', 'Fixture', 1000)"
        )
        connection.execute(
            "INSERT INTO sessions (id, game_id, started_at, ended_at, last_seen_at, duration_sec, status) "
            "VALUES ('session-1', 'game-1', 1000, 5000, 5000, 4, 'completed')"
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()


def test_version_one_upgrades_with_consistent_backup(tmp_path: Path) -> None:
    path = tmp_path / "gamehub.db"
    _legacy_database(path)
    database = db.Database(path)

    with database.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 0
    assert LibraryRepository(database).get_game("game-1").total_playtime == 4

    backup = tmp_path / "gamehub.db-v1.bak"
    assert backup.is_file()
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT id, duration_sec FROM sessions").fetchone() == ("session-1", 4)


def test_migration_failure_preserves_version_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "gamehub.db"
    _legacy_database(path)
    monkeypatch.setattr(db, "SCREENSHOT_SCHEMA", (*db.SCREENSHOT_SCHEMA, "INVALID STATEMENT"))
    with pytest.raises(db.StorageError):
        db.Database(path)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name = 'screenshots'").fetchone() is None
    assert (tmp_path / "gamehub.db-v1.bak").is_file()


def test_ring_keeps_ten_latest_and_finalizes_on_game_exit(screenshot_store) -> None:
    database, screenshots, sessions, game, session = screenshot_store
    for index in range(12):
        assert screenshots.append(game, session, _frame(index), 1100 + index, 10)

    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 10
        assert connection.execute("SELECT SUM(is_last_moment) FROM screenshots").fetchone()[0] == 0
    assert screenshots.last_moments(game) == ()
    sessions.finish(session, 3000, 2, "completed")

    images = screenshots.last_moments(game)
    assert [screenshots.read_image(image) for image in images] == [_frame(index) for index in range(2, 12)]
    assert sorted(images[0].parent.glob("*.webp")) == sorted(images)
    assert not screenshots.append(game, session, _frame(12), 3001, 10)


def test_ring_retains_latest_capture_across_wall_clock_jump(screenshot_store) -> None:
    _, screenshots, sessions, game, session = screenshot_store
    screenshots.append(game, session, _frame(1), 2100, 2)
    screenshots.append(game, session, _frame(2), 2200, 2)
    screenshots.append(game, session, _frame(3), 1200, 2)
    sessions.finish(session, 3000, 2, "completed")
    assert [screenshots.read_image(path) for path in screenshots.last_moments(game)] == [_frame(2), _frame(3)]


def test_capture_uses_latest_terminal_session_and_pins_recovered_frames(screenshot_store) -> None:
    _, screenshots, sessions, game, session = screenshot_store
    screenshots.append(game, session, _frame(1), 2000, 10)
    sessions.finish(session, 3000, 2, "completed")
    next_session = sessions.open(game, 4000)
    assert [file.read_bytes() for file in screenshots.last_moments(game)] == [_frame(1)]
    screenshots.append(game, next_session, _frame(2), 5000, 10)
    assert sessions.recover() == 1
    assert [file.read_bytes() for file in screenshots.last_moments(game)] == [_frame(2)]


def test_finalization_rolls_back_if_marking_last_moments_fails(screenshot_store) -> None:
    database, screenshots, sessions, game, session = screenshot_store
    screenshots.append(game, session, _frame(1), 2000, 10)
    with database.write() as connection:
        connection.execute(
            "CREATE TRIGGER reject_test_finalization BEFORE UPDATE ON screenshots "
            "BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END"
        )

    with pytest.raises(db.StorageError):
        sessions.finish(session, 3000, 2, "completed")

    with database.read() as connection:
        assert connection.execute("SELECT status FROM sessions").fetchone()[0] == "open"
        assert connection.execute("SELECT is_last_moment FROM screenshots").fetchone()[0] == 0


def test_failed_reference_and_missing_files_are_reconciled(screenshot_store) -> None:
    database, screenshots, sessions, game, session = screenshot_store
    screenshots.append(game, session, _frame(1), 2000, 10)
    folder = database.path.parent / "media" / game / session
    abandoned = folder / f"shot_{uuid4()}.webp.tmp"
    abandoned.write_bytes(b"unfinished")
    unrecognized = folder / "user-owned.webp"
    unrecognized.write_bytes(b"unrelated")

    with database.write() as connection:
        connection.execute(
            "CREATE TRIGGER reject_test_reference BEFORE INSERT ON screenshots "
            "BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END"
        )

    with pytest.raises(db.StorageError):
        screenshots.append(game, session, _frame(2), 3000, 10)
    assert len(tuple(folder.glob("shot_*.webp"))) == 2

    screenshots.recover_files()
    assert unrecognized.is_file()
    assert not abandoned.exists()
    (retained,) = folder.glob("shot_*.webp")
    assert retained.read_bytes() == _frame(1)
    retained.unlink()
    sessions.finish(session, 4000, 3, "completed")
    assert screenshots.last_moments(game) == (retained,)
    assert screenshots.read_image(retained) is None
    screenshots.recover_files()
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1


def test_mismatched_session_and_invalid_ids_never_create_directories(screenshot_store) -> None:
    database, screenshots, _, _, session = screenshot_store
    assert not screenshots.append(str(uuid4()), session, _frame(1), 1500, 10)
    assert not screenshots.append("../outside", session, _frame(1), 1500, 10)
    assert not (database.path.parent / "media").exists()


def test_image_reads_reject_unowned_paths_and_files_above_the_limit(screenshot_store) -> None:
    _, screenshots, sessions, game, session = screenshot_store
    screenshots.append(game, session, _frame(1), 2000, 10)
    sessions.finish(session, 3000, 2, "completed")
    (retained,) = screenshots.last_moments(game)
    orphan = retained.parent / f"shot_{uuid4()}.webp"
    orphan.write_bytes(_frame(2))
    assert screenshots.read_image(orphan) is None
    with retained.open("r+b") as output:
        output.truncate(17 * 1024 * 1024)
    assert screenshots.read_image(retained) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows directory share modes")
def test_directory_chain_cannot_be_renamed_while_pinned(screenshot_store) -> None:
    database, screenshots, _, game, session = screenshot_store
    screenshots.append(game, session, _frame(1), 2000, 10)
    folder = database.path.parent / "media" / game / session
    renamed = folder.with_name("renamed")

    with protect_directory(folder), pytest.raises(OSError):
        folder.rename(renamed)

    folder.rename(renamed)
    assert renamed.is_dir()
