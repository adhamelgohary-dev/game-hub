from io import BytesIO
from pathlib import Path
from time import monotonic
from unittest.mock import Mock

import numpy
import pytest
import soundfile
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from gamehub.core.capture.models import CaptureFrame, WindowIdentity
from gamehub.core.capture.scheduler import CaptureScheduler
from gamehub.core.capture.service import CaptureService
from gamehub.core.sessions.models import ProcessIdentity, SessionIdentity
from gamehub.core.storage.controls import ControlsRepository
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.memory import MemoryChanged, MemoryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository
from gamehub.modules.memory.controls_controller import ControlsController
from gamehub.modules.memory.last_time_card import LastTimeCard
from gamehub.ui.game_page import GamePage


def _until(predicate) -> None:
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        events = QEventLoop()
        QTimer.singleShot(10, events.quit)
        events.exec()
    assert predicate()


def _voice_clip() -> bytes:
    samples = 0.08 * numpy.sin(2 * numpy.pi * 440 * numpy.arange(1600) / 16000)
    with BytesIO() as output:
        soundfile.write(output, samples, 16000, format="OGG", subtype="VORBIS")
        return output.getvalue()


def _webp_bytes(color: tuple[int, int, int]) -> bytes:
    with BytesIO() as output:
        Image.new("RGB", (24, 24), color).save(output, format="WEBP")
        return output.getvalue()


def test_timeline_pagination_chronology_and_missing_media_resilience(tmp_path: Path) -> None:
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    screenshots = ScreenshotRepository(db, tmp_path)
    notes = NoteRepository(db, tmp_path)
    controls = ControlsRepository(db, tmp_path)
    memory = MemoryRepository(db, tmp_path)

    exe = tmp_path / "Chronicle.exe"
    exe.touch()
    game_id = library.add_manual(exe)

    # Empty timeline for a new game.
    assert memory.timeline(game_id).sessions == ()

    clip = _voice_clip()
    s1 = sessions.open(game_id, 1000)
    screenshots.append(game_id, s1, _webp_bytes((10, 20, 30)), 1100, 10)
    notes.save_voice(s1, clip, "hotkey")
    sessions.finish(s1, 5000, 4, "completed")

    s2 = sessions.open(game_id, 2000)
    notes.save_text(s2, "Found the hidden map.")
    sessions.finish(s2, 9000, 7, "interrupted")

    s3 = sessions.open(game_id, 3000)
    screenshots.append(game_id, s3, _webp_bytes((40, 80, 120)), 3100, 10)
    sessions.finish(s3, 12000, 9, "completed")

    # Delete session 1's voice file to verify missing media preserves the rest of the timeline.
    voice_files = list((tmp_path / "media" / game_id / s1).glob("note_*.ogg"))
    assert len(voice_files) == 1
    voice_files[0].unlink()

    page1 = memory.timeline(game_id, limit=2)
    assert [s.id for s in page1.sessions] == [s3, s2]
    assert page1.next_cursor is not None
    assert len(page1.sessions[0].screenshots) == 1
    assert page1.sessions[1].text_notes[0].text == "Found the hidden map."

    page2 = memory.timeline(game_id, cursor=page1.next_cursor, limit=2)
    assert [s.id for s in page2.sessions] == [s1]
    assert page2.next_cursor is None
    assert page2.sessions[0].voice_notes[0].available is False
    assert len(page2.sessions[0].screenshots) == 1

    # Controls pinned to this game appear in LastTimeData as well.
    controls.pin_text(game_id, "Hold Shift to sprint.")
    controls.pin_image(game_id, _webp_bytes((200, 100, 50)))
    snapshot = memory.last_time(game_id)
    assert snapshot is not None
    assert snapshot.controls == ("Hold Shift to sprint.",)
    assert len(snapshot.control_images) == 1


def test_controls_controller_pins_via_hotkey_and_handles_unavailable_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["controls test"])
    parent = QWidget()
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    controls = ControlsRepository(db, tmp_path)
    exe = tmp_path / "PinGame.exe"
    exe.touch()
    game_id = library.add_manual(exe)

    events: list[MemoryChanged] = []
    notices: list[str] = []
    errors: list[tuple[str, str]] = []
    captured_payload: list[bytes | None] = [_webp_bytes((50, 90, 140))]

    def fake_pin(callback):
        callback(game_id, "session-1", captured_payload[0])
        return "started"

    controller = ControlsController(parent, controls, fake_pin, events.append, notices.append)
    controller.errorOccurred.connect(lambda gid, msg: errors.append((gid, msg)))
    try:
        controller.pin_hotkey()
        _until(lambda: len(events) == 1)
        assert events[0].game_id == game_id
        assert events[0].item_kind == "control_image"
        assert len(controls.list_controls(game_id)) == 1
        assert any("pinned" in msg.lower() for msg in notices)

        # Unavailable capture (e.g., protected/black frame) guides the user to upload.
        captured_payload[0] = None
        controller.pin_hotkey()
        assert any("upload" in msg.lower() for msg in notices)

        # Text note validation and persistence.
        controller.save_text(game_id, "   ")
        _until(lambda: len(errors) == 1)
        controller.save_text(game_id, "R to reload")
        _until(lambda: len(events) == 2)
        assert events[1].item_kind == "control_text"

        # Image upload succeeds for valid PNG and emits error for invalid file.
        upload = tmp_path / "pad.png"
        Image.new("RGB", (32, 32), (80, 140, 200)).save(upload, format="PNG")
        controller.import_image(game_id, str(upload))
        _until(lambda: len(events) == 3)
        assert events[2].item_kind == "control_image"

        bad_file = tmp_path / "broken.png"
        bad_file.write_bytes(b"not-a-png")
        controller.import_image(game_id, str(bad_file))
        _until(lambda: len(errors) == 2)
        assert "supported local image" in errors[1][1].lower()
    finally:
        controller.close()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_capture_scheduler_pin_foreground_reuses_gate_without_touching_ring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["pin scheduler test"])
    parent = QWidget()
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    screenshots = ScreenshotRepository(db, tmp_path)
    exe = tmp_path / "GateGame.exe"
    exe.touch()
    game_id = library.add_manual(exe)
    session_id = sessions.open(game_id, 1000)

    proc = ProcessIdentity(42, 1.0)
    window = WindowIdentity(1001, proc)
    windows = Mock()
    windows.foreground.return_value = window
    tracker = Mock()
    tracker.active_for.return_value = SessionIdentity(game_id, session_id)
    capture = Mock()
    capture.capture_once.return_value = CaptureFrame(
        bytes([10, 120, 200, 255]) * (8 * 8), 8, 8
    )

    service = CaptureService(windows, tracker, capture, screenshots)
    scheduler = CaptureScheduler(service, parent)
    results = []
    try:
        assert scheduler.pin_foreground(lambda g, s, d: results.append((g, s, d))) == "started"
        _until(lambda: len(results) == 1)
        assert results[0][0] == game_id
        assert results[0][1] == session_id
        assert results[0][2] is not None and results[0][2][:4] == b"RIFF"
        # Pinned frame must NOT enter the session screenshot ring.
        with db.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 0

        # No focused tracked window returns no_foreground_game.
        windows.foreground.return_value = None
        assert scheduler.pin_foreground(lambda *_args: None) == "no_foreground_game"
    finally:
        scheduler.close()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_game_page_voice_switch_pagination_and_cross_game_draft_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["game page voice test"])
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    notes = NoteRepository(db, tmp_path)
    controls = ControlsRepository(db, tmp_path)
    memory = MemoryRepository(db, tmp_path)

    exe_a = tmp_path / "GameOne.exe"
    exe_b = tmp_path / "GameTwo.exe"
    exe_a.touch()
    exe_b.touch()
    game_a = library.add_manual(exe_a)
    game_b = library.add_manual(exe_b)

    clip = _voice_clip()
    s1 = sessions.open(game_a, 1000)
    n1 = notes.save_voice(s1, clip, "hotkey")
    sessions.finish(s1, 5000, 4, "completed")
    s2 = sessions.open(game_a, 2000)
    n2 = notes.save_voice(s2, clip, "hotkey")
    sessions.finish(s2, 6000, 4, "completed")

    page = GamePage()
    try:
        summary_a = library.get_game(game_a)
        summary_b = library.get_game(game_b)
        assert summary_a is not None and summary_b is not None
        first_page = memory.timeline(game_a, limit=1)
        page.show_game(summary_a, controls.list_controls(game_a), first_page)

        # Start playing note n2, then simulate track switch / replay where stop fires before play.
        play_btn, stop_btn = page._voice_buttons[n2]
        play_btn.click()
        page.set_voice_playing(False)
        page.set_voice_playing(True)
        assert stop_btn.isEnabled()

        # Appending older page preserves Stop button state on the currently playing note!
        second_page = memory.timeline(game_a, cursor=first_page.next_cursor, limit=1)
        page.present_timeline(second_page, append=True)
        assert page._voice_buttons[n2][1].isEnabled()
        assert not page._voice_buttons[n1][1].isEnabled()

        # Switching to Game B clears unsaved Game A controls draft.
        page._control_input.setPlainText("Game A unsaved tip")
        page.show_game(summary_b, controls.list_controls(game_b), memory.timeline(game_b))
        assert page._control_input.toPlainText() == ""
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_game_page_and_last_time_card_render_controls_and_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["game page test"])
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    screenshots = ScreenshotRepository(db, tmp_path)
    notes = NoteRepository(db, tmp_path)
    controls = ControlsRepository(db, tmp_path)
    memory = MemoryRepository(db, tmp_path)

    exe = tmp_path / "Horizon.exe"
    exe.touch()
    game_id = library.add_manual(exe)
    sid = sessions.open(game_id, 1000)
    screenshots.append(game_id, sid, _webp_bytes((10, 100, 200)), 1200, 10)
    notes.save_voice(sid, _voice_clip(), "hotkey")
    notes.save_text(sid, "Reached summit camp.")
    sessions.finish(sid, 15_000, 14, "completed")

    controls.pin_text(game_id, "Tab opens map.")
    controls.pin_image(game_id, _webp_bytes((120, 40, 200)))

    game = library.get_game(game_id)
    assert game is not None
    page = GamePage(
        load_control_image=controls.read_image,
        load_screenshot=screenshots.read_image,
    )
    play_clicked = Mock()
    page.playRequested.connect(play_clicked)
    page.show_game(game, controls.list_controls(game_id), memory.timeline(game_id))
    assert page.game_id == game_id
    assert page._title.text() == "Horizon"
    assert page._control_position.text() == "Controls image 1 of 1"
    assert not page._control_pixmap.isNull()
    page._play.click()
    play_clicked.assert_called_once_with(game_id)

    # LastTimeCard also shows pinned controls image and text.
    snapshot = memory.last_time(game_id)
    assert snapshot is not None
    card = LastTimeCard(
        snapshot,
        autoplay_enabled=False,
        allow_launch=False,
        load_image=screenshots.read_image,
        load_control_image=controls.read_image,
    )
    try:
        assert "Tab opens map." in card._controls.text()
        assert card._control_preview is not None
        assert not card._control_picture.isNull()
    finally:
        card.close()
        card.deleteLater()
        page.close()
        page.deleteLater()
        app.processEvents()
