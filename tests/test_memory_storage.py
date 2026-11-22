from io import BytesIO
from pathlib import Path
from uuid import uuid4

import numpy
import soundfile
from PIL import Image

from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.memory import MemoryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository


def _voice_clip() -> bytes:
    samples = 0.1 * numpy.sin(2 * numpy.pi * 440 * numpy.arange(1600) / 16000)
    with BytesIO() as output:
        soundfile.write(output, samples, 16000, format="OGG", subtype="VORBIS")
        return output.getvalue()


def _webp_bytes(color: tuple[int, int, int]) -> bytes:
    with BytesIO() as output:
        Image.new("RGB", (16, 16), color).save(output, format="WEBP")
        return output.getvalue()


def _setup_game(tmp_path: Path):
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    screenshots = ScreenshotRepository(db, tmp_path)
    notes = NoteRepository(db, tmp_path)
    memory = MemoryRepository(db, tmp_path)
    exe = tmp_path / "Solo Quest.exe"
    exe.touch()
    game_id = library.add_manual(exe)
    return db, library, sessions, screenshots, notes, memory, game_id


def test_last_time_selects_prior_ended_session_and_independent_notes(tmp_path: Path) -> None:
    _, _, sessions, screenshots, notes, memory, game_id = _setup_game(tmp_path)
    clip = _voice_clip()

    first = sessions.open(game_id, 1000)
    assert screenshots.append(game_id, first, _webp_bytes((10, 20, 30)), 1500, 10)
    notes.save_voice(first, clip, "hotkey")
    sessions.finish(first, 61_000, 60, "completed")

    second = sessions.open(game_id, 100_000)
    assert screenshots.append(game_id, second, _webp_bytes((40, 50, 60)), 110_000, 10)
    assert screenshots.append(game_id, second, _webp_bytes((70, 80, 90)), 120_000, 10)
    sessions.finish(second, 220_000, 120, "interrupted")
    notes.save_text(second, "Check the northern gate key.")

    # An open session must be ignored by Last time queries.
    active = sessions.open(game_id, 300_000)
    notes.save_voice(active, clip, "hotkey")

    snapshot = memory.last_time(game_id, exclude_session_id=active)
    assert snapshot is not None
    assert snapshot.game_name == "Solo Quest"
    assert snapshot.session_count == 2
    assert snapshot.total_playtime == 180
    assert snapshot.last_session is not None
    assert snapshot.last_session.id == second
    assert snapshot.last_session.status == "interrupted"
    assert snapshot.last_session.duration_sec == 120
    assert snapshot.voice_note is not None
    assert snapshot.voice_note.session_id == first
    assert snapshot.voice_note.available is True
    assert memory.read_voice(snapshot.voice_note.path) == clip
    assert snapshot.text_note is not None
    assert snapshot.text_note.session_id == second
    assert snapshot.text_note.text == "Check the northern gate key."
    assert len(snapshot.screenshots) == 2
    assert all(path.parent.name == second for path in snapshot.screenshots)


def test_last_time_empty_state_for_new_or_only_open_game(tmp_path: Path) -> None:
    _, _, sessions, _, _, memory, game_id = _setup_game(tmp_path)
    active = sessions.open(game_id, 5000)

    snapshot = memory.last_time(game_id, exclude_session_id=active)
    assert snapshot is not None
    assert snapshot.last_session is None
    assert snapshot.total_playtime == 0
    assert snapshot.session_count == 0
    assert snapshot.voice_note is None
    assert snapshot.text_note is None
    assert snapshot.screenshots == ()
    assert snapshot.controls == ()


def test_missing_or_unowned_voice_file_is_handled_safely(tmp_path: Path) -> None:
    _, _, sessions, _, notes, memory, game_id = _setup_game(tmp_path)
    clip = _voice_clip()
    session_id = sessions.open(game_id, 1000)
    notes.save_voice(session_id, clip, "popup")
    sessions.finish(session_id, 9000, 8, "completed")

    before = memory.last_time(game_id)
    assert before is not None and before.voice_note is not None
    voice_path = before.voice_note.path
    voice_path.unlink()

    after = memory.last_time(game_id)
    assert after is not None and after.voice_note is not None
    assert after.voice_note.available is False
    assert memory.read_voice(voice_path) is None

    unowned = tmp_path / "media" / game_id / session_id / f"note_{uuid4()}.ogg"
    unowned.parent.mkdir(parents=True, exist_ok=True)
    unowned.write_bytes(clip)
    assert memory.read_voice(unowned) is None
    assert memory.read_voice(tmp_path / "outside.ogg") is None
    assert memory.read_voice(tmp_path / "media" / ".." / "outside.ogg") is None

    # Truncated Ogg header (< 27 bytes) must be treated as unavailable.
    voice_path.write_bytes(b"OggS\x00short")
    truncated = memory.last_time(game_id)
    assert truncated is not None and truncated.voice_note is not None
    assert truncated.voice_note.available is False
    assert memory.read_voice(voice_path) is None


def test_autoplay_preference_persists_and_recovers_from_invalid_value(tmp_path: Path) -> None:
    db, _, _, _, _, memory, _ = _setup_game(tmp_path)
    assert memory.autoplay_enabled() is True
    memory.set_autoplay_enabled(False)
    assert memory.autoplay_enabled() is False
    memory.set_autoplay_enabled(True)
    assert memory.autoplay_enabled() is True

    with db.write() as connection:
        connection.execute(
            "UPDATE settings SET value = '\"not-a-bool\"' WHERE key = 'memory.autoplay_voice'"
        )
    assert memory.autoplay_enabled() is True
