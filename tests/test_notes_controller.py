from io import BytesIO
from pathlib import Path
from threading import Event
from time import monotonic
from unittest.mock import Mock

import numpy
import pytest
import soundfile
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from gamehub.core.audio.recorder import RecordingError
from gamehub.core.sessions.models import GameStopped, SessionIdentity
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.sessions import SessionRepository
from gamehub.modules.memory.notes_controller import NotesController


def _until(predicate) -> None:
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        events = QEventLoop()
        QTimer.singleShot(10, events.quit)
        events.exec()
    assert predicate()


@pytest.fixture
def note_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["notes test"])
    original_quit_policy = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    window = QWidget()
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    targets = []
    for name in ("First Game", "Second Game"):
        path = tmp_path / f"{name}.exe"
        path.touch()
        game = library.add_manual(path)
        targets.append(SessionIdentity(game, sessions.open(game, 1000)))
    notes = NoteRepository(db, tmp_path)
    source = Mock(return_value=targets[0])
    indicator = Mock()
    notify = Mock()
    recorder = Mock()
    controller = NotesController(window, notes, library, recorder, source, indicator, notify)
    try:
        yield db, notes, sessions, targets, source, indicator, recorder, controller
    finally:
        if controller._dialog is not None:
            controller._dialog.reject()
        controller.close()
        window.close()
        app.setQuitOnLastWindowClosed(original_quit_policy)


def _voice_clip() -> bytes:
    time_values = numpy.arange(1600) / 16000
    with BytesIO() as output:
        soundfile.write(output, 0.1 * numpy.sin(440 * numpy.pi * time_values), 16000, format="OGG", subtype="VORBIS")
        return output.getvalue()


def test_hotkey_recording_remains_bound_when_focus_changes(note_context) -> None:
    db, _, _, targets, source, indicator, recorder, controller = note_context
    clip = _voice_clip()
    recorder.stop.return_value = clip
    controller.toggle_hotkey()
    _until(lambda: indicator.call_args is not None and indicator.call_args.args == (True,))
    source.return_value = targets[1]
    controller.toggle_hotkey()
    _until(lambda: controller._voice is None)
    with db.read() as connection:
        row = connection.execute("SELECT session_id, kind, source, path_or_text FROM notes").fetchone()
    assert tuple(row)[:3] == (targets[0].session_id, "voice", "hotkey")
    assert db.path.parent.joinpath(row["path_or_text"]).read_bytes() == clip


def test_mic_denial_leaves_text_and_prompt_preference_usable(note_context) -> None:
    db, notes, sessions, targets, _, _, recorder, controller = note_context
    first = targets[0]
    recorder.start.side_effect = RecordingError("unavailable")
    sessions.finish(first.session_id, 8000, 7, "completed")
    controller.game_stopped(GameStopped(first.game_id, first.session_id, 8000, 7, "completed", "process_exit"))
    dialog = controller._dialog
    assert dialog is not None
    dialog.recordRequested.emit()
    _until(lambda: "Microphone unavailable" in dialog._error.text())
    dialog._disable_prompt.setChecked(True)
    dialog.textRequested.emit("Remember the bridge.")
    _until(lambda: controller._dialog is None and not notes.prompt_enabled())
    with db.read() as connection:
        row = connection.execute("SELECT session_id, kind, path_or_text FROM notes").fetchone()
    assert tuple(row) == (first.session_id, "text", "Remember the bridge.")


def test_dismissal_cancels_queued_input_before_microphone_opens(note_context) -> None:
    _, _, sessions, targets, _, _, recorder, controller = note_context
    first = targets[0]
    sessions.finish(first.session_id, 8000, 7, "completed")
    controller.game_stopped(GameStopped(first.game_id, first.session_id, 8000, 7, "completed", "process_exit"))
    dialog = controller._dialog
    assert dialog is not None
    release = Event()
    controller._worker.submit(release.wait, 3)
    try:
        dialog.recordRequested.emit()
        dialog.reject()
    finally:
        release.set()
    _until(lambda: controller._voice is None)
    recorder.start.assert_not_called()


def test_voice_save_retry_keeps_encoded_draft_without_reopening_input(
    note_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, notes, sessions, targets, _, _, recorder, controller = note_context
    first = targets[0]
    recorder.stop.return_value = _voice_clip()
    original = notes.save_voice
    calls = []

    def save_once_ready(session_id, clip, source):
        calls.append((session_id, clip, source))
        if len(calls) == 1:
            raise StorageError("Temporary write failure")
        return original(session_id, clip, source)

    monkeypatch.setattr(notes, "save_voice", save_once_ready)
    sessions.finish(first.session_id, 8000, 7, "completed")
    controller.game_stopped(GameStopped(first.game_id, first.session_id, 8000, 7, "completed", "process_exit"))
    dialog = controller._dialog
    assert dialog is not None
    dialog.recordRequested.emit()
    _until(lambda: controller._voice is not None and controller._voice.phase == "recording")
    dialog.recordRequested.emit()
    _until(lambda: controller._voice is not None and controller._voice.phase == "retry")
    assert "retry" in dialog._error.text().lower()
    dialog.recordRequested.emit()
    _until(lambda: controller._voice is None)
    recorder.start.assert_called_once()
    recorder.stop.assert_called_once()
    assert calls[0] == calls[1]
    with db.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
