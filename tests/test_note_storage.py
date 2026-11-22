import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from gamehub.core.storage import db
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.notes import MAX_TEXT_LENGTH, NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository

_CLIP = b"OggS\x00" + bytes(30)


@pytest.fixture
def note_store(tmp_path: Path):
    database = db.Database(tmp_path / "gamehub.db")
    exe = tmp_path / "Example.exe"
    exe.touch()
    game = LibraryRepository(database).add_manual(exe)
    sessions = SessionRepository(database)
    session = sessions.open(game, 1000)
    return database, NoteRepository(database, tmp_path), sessions, game, session


def _version_two(profile: Path) -> tuple[str, str, Path]:
    game, session, shot = (str(uuid4()) for _ in range(3))
    file = Path("media") / game / session / f"shot_{shot}.webp"
    with closing(sqlite3.connect(profile / "gamehub.db")) as connection:
        for statement in (*db.INITIAL_SCHEMA, *db.SCREENSHOT_SCHEMA):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO games (id, source, source_id, name, added_at) "
            "VALUES (?, 'manual', ?, 'Example', 1000)",
            (game, game),
        )
        connection.execute(
            "INSERT INTO sessions (id, game_id, started_at, ended_at, last_seen_at, duration_sec, status) "
            "VALUES (?, ?, 1000, 5000, 5000, 4, 'completed')",
            (session, game),
        )
        connection.execute(
            "INSERT INTO screenshots (id, session_id, path, captured_at, is_last_moment) "
            "VALUES (?, ?, ?, 4000, 1)",
            (shot, session, file.as_posix()),
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    return game, session, profile / file


def test_version_two_upgrade_preserves_saved_screenshots_and_history(tmp_path: Path) -> None:
    game, session, file = _version_two(tmp_path)
    file.parent.mkdir(parents=True)
    webp = b"RIFF\x04\x00\x00\x00WEBP"
    file.write_bytes(webp)

    database = db.Database(tmp_path / "gamehub.db")
    screenshots = ScreenshotRepository(database, tmp_path)
    assert screenshots.last_moments(game) == (file,)
    assert screenshots.read_image(file) == webp
    assert LibraryRepository(database).get_game(game).total_playtime == 4
    assert NoteRepository(database, tmp_path).save_text(session, "Migration verified")

    with closing(sqlite3.connect(tmp_path / "gamehub.db-v2.bak")) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
        assert backup.execute("SELECT session_id FROM screenshots").fetchone()[0] == session
        assert backup.execute("SELECT 1 FROM sqlite_schema WHERE name = 'notes'").fetchone() is None


def test_version_two_rolls_back_on_note_migration_failure(tmp_path: Path, monkeypatch) -> None:
    _version_two(tmp_path)
    path = tmp_path / "gamehub.db"
    monkeypatch.setattr(db, "NOTE_SCHEMA", (*db.NOTE_SCHEMA, "INVALID STATEMENT"))

    with pytest.raises(db.StorageError):
        db.Database(path)

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name = 'notes'").fetchone() is None
    assert (tmp_path / "gamehub.db-v2.bak").is_file()


def test_notes_persist_with_original_session_and_source(note_store) -> None:
    database, notes, sessions, game, session = note_store
    hotkey = notes.save_voice(session, _CLIP, "hotkey")
    sessions.finish(session, 3000, 2, "completed")
    popup = notes.save_voice(session, _CLIP, "popup")
    text = notes.save_text(session, "  First line\nSecond line  ")
    sessions.open(game, 4000)

    with db.Database(database.path).read() as reader:
        rows = {row["id"]: row for row in reader.execute("SELECT * FROM notes")}
    assert set(rows) == {hotkey, popup, text}
    assert {row["session_id"] for row in rows.values()} == {session}
    assert (rows[text]["kind"], rows[text]["source"]) == ("text", "popup")
    assert rows[text]["path_or_text"] == "  First line\nSecond line  "
    for note, source in ((hotkey, "hotkey"), (popup, "popup")):
        assert (rows[note]["kind"], rows[note]["source"]) == ("voice", source)
        relative = f"media/{game}/{session}/note_{note}.ogg"
        assert rows[note]["path_or_text"] == relative
        assert (database.path.parent / relative).read_bytes() == _CLIP


def test_invalid_notes_do_not_write_rows_or_files(note_store) -> None:
    database, notes, _, _, session = note_store
    for invalid in ("\t\n", "embedded\0null", "x" * (MAX_TEXT_LENGTH + 1)):
        with pytest.raises(ValueError):
            notes.save_text(session, invalid)
    with pytest.raises(ValueError, match="unavailable"):
        notes.save_text(str(uuid4()), "Unknown session")
    with pytest.raises(ValueError, match="unavailable"):
        notes.save_voice(str(uuid4()), _CLIP, "hotkey")
    with pytest.raises(ValueError, match="Unknown voice note source"):
        notes.save_voice(session, _CLIP, "other")
    with pytest.raises(ValueError, match="bounded Ogg"):
        notes.save_voice(session, b"not an Ogg clip", "popup")
    with database.read() as reader:
        assert reader.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert not (database.path.parent / "media").exists()


def test_prompt_setting_persists_and_bad_type_uses_default(note_store, caplog) -> None:
    database, notes, _, _, _ = note_store
    assert notes.prompt_enabled()
    notes.set_prompt_enabled(False)
    assert not NoteRepository(db.Database(database.path), database.path.parent).prompt_enabled()
    with pytest.raises(TypeError, match="must be a boolean"):
        notes.set_prompt_enabled(0)
    with database.write() as writer:
        writer.execute("UPDATE settings SET value = '0' WHERE key = 'memory.prompt_on_end'")
    assert notes.prompt_enabled()
    assert caplog.messages == ["invalid_setting key=memory.prompt_on_end"]


def test_failed_voice_note_commit_is_reconciled_without_touching_other_media(note_store) -> None:
    database, notes, _, game, session = note_store
    retained = notes.save_voice(session, _CLIP, "hotkey")
    directory = database.path.parent / "media" / game / session
    unrelated = directory / "user-note.ogg"
    unrelated.write_bytes(_CLIP)
    screenshot = directory / f"shot_{uuid4()}.webp"
    screenshot.touch()
    staged = directory / f"note_{uuid4()}.ogg.tmp"
    staged.touch()

    with database.write() as connection:
        connection.execute(
            "CREATE TRIGGER reject_test_voice BEFORE INSERT ON notes "
            "BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END"
        )
    with pytest.raises(db.StorageError):
        notes.save_voice(session, _CLIP, "popup")

    assert len(tuple(directory.glob("note_*.ogg"))) == 2
    notes.recover_files()
    assert {path.name for path in directory.iterdir()} == {
        f"note_{retained}.ogg", unrelated.name, screenshot.name,
    }
    assert (directory / f"note_{retained}.ogg").read_bytes() == _CLIP
