from io import BytesIO
from pathlib import Path
from time import monotonic
from unittest.mock import Mock

import numpy
import pytest
import soundfile
from PIL import Image
from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from gamehub.core.library.launcher import LaunchCoordinator, WindowsLauncher
from gamehub.core.library.models import (
    DetectedGame,
    DiscoveryBatch,
    GameSource,
    LaunchTarget,
)
from gamehub.core.sessions.models import GameStarted, GameStopped, SessionIdentity
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.memory import MemoryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository
from gamehub.modules.memory.last_time_controller import LastTimeController


class _FakePlayer(QObject):
    playingChanged = Signal(bool)
    failed = Signal()

    def __init__(self, *, should_fail: bool = False) -> None:
        super().__init__()
        self.should_fail = should_fail
        self.played: list[bytes] = []
        self.stops = 0

    def play(self, clip: bytes) -> bool:
        if self.should_fail:
            self.failed.emit()
            return False
        self.played.append(clip)
        self.playingChanged.emit(True)
        return True

    def stop(self) -> None:
        self.stops += 1
        self.playingChanged.emit(False)


def _until(predicate) -> None:
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        events = QEventLoop()
        QTimer.singleShot(10, events.quit)
        events.exec()
    assert predicate()


def _voice_clip() -> bytes:
    samples = 0.1 * numpy.sin(2 * numpy.pi * 440 * numpy.arange(1600) / 16000)
    with BytesIO() as output:
        soundfile.write(output, samples, 16000, format="OGG", subtype="VORBIS")
        return output.getvalue()


def _webp_bytes(color: tuple[int, int, int]) -> bytes:
    with BytesIO() as output:
        Image.new("RGB", (24, 24), color).save(output, format="WEBP")
        return output.getvalue()


@pytest.fixture
def memory_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["last time test"])
    original_quit_policy = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    window = QWidget()
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    screenshots = ScreenshotRepository(db, tmp_path)
    notes = NoteRepository(db, tmp_path)
    memory = MemoryRepository(db, tmp_path)

    steam_dir = tmp_path / "SteamGame"
    steam_dir.mkdir()
    game_ids = library.reconcile(
        GameSource.STEAM,
        DiscoveryBatch(
            games=(
                DetectedGame(
                    GameSource.STEAM,
                    "420",
                    "Starlight Hollow",
                    steam_dir,
                    launch_target=LaunchTarget("steam_uri", "steam://rungameid/420"),
                ),
                DetectedGame(
                    GameSource.STEAM,
                    "421",
                    "Empty Realm",
                    steam_dir,
                    launch_target=None,
                ),
            ),
            state="complete",
        ),
    )
    game_a, game_b = game_ids

    clip = _voice_clip()
    first = sessions.open(game_a, 1000)
    notes.save_voice(first, clip, "hotkey")
    sessions.finish(first, 61_000, 60, "completed")

    second = sessions.open(game_a, 100_000)
    screenshots.append(game_a, second, _webp_bytes((20, 120, 200)), 110_000, 10)
    screenshots.append(game_a, second, _webp_bytes((80, 160, 40)), 120_000, 10)
    sessions.finish(second, 220_000, 120, "interrupted")
    notes.save_text(second, "Boss weakness is lightning.")

    opened_uris: list[str] = []
    launch_error = [None]
    coordinator = LaunchCoordinator(
        WindowsLauncher(open_uri=lambda uri: (opened_uris.append(uri) or launch_error[0]))
    )
    player = _FakePlayer()
    foreground = Mock(return_value=None)
    selected = Mock(return_value=None)
    reveal = Mock()
    notify = Mock()

    controller = LastTimeController(
        window,
        memory,
        screenshots.read_image,
        player,
        coordinator,
        foreground,
        selected,
        reveal,
        notify,
    )
    try:
        yield {
            "db": db,
            "sessions": sessions,
            "memory": memory,
            "game_a": game_a,
            "game_b": game_b,
            "clip": clip,
            "player": player,
            "coordinator": coordinator,
            "opened_uris": opened_uris,
            "launch_error": launch_error,
            "foreground": foreground,
            "selected": selected,
            "reveal": reveal,
            "notify": notify,
            "controller": controller,
        }
    finally:
        controller.close()
        window.close()
        app.setQuitOnLastWindowClosed(original_quit_policy)


def test_automatic_start_shows_prior_snapshot_and_autoplays_once(memory_context) -> None:
    controller = memory_context["controller"]
    game_a = memory_context["game_a"]
    player = memory_context["player"]
    sessions = memory_context["sessions"]

    active = sessions.open(game_a, 500_000)
    controller.game_started(GameStarted(game_a, active, 500_000))
    card = controller._card
    assert card is not None
    assert card.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert "interrupted" in card._summary.text().lower()
    assert isinstance(card._text_note, QPlainTextEdit)
    assert card._text_note.toPlainText() == "Boss weakness is lightning."
    assert card._position.text() == "Screenshot 1 of 2"
    assert player.played == [memory_context["clip"]]
    assert card._stop_voice.isEnabled()

    # Clicking Stop halts playback; Replay plays again on demand with updated accessible name.
    card._stop_voice.click()
    assert not card._stop_voice.isEnabled()
    assert "Replay" in card._play_voice.text()
    assert card._play_voice.accessibleName() == "Replay voice note"
    assert card._previous.accessibleName() == "Previous screenshot"
    assert card._next.accessibleName() == "Next screenshot"
    card._play_voice.click()
    assert len(player.played) == 2

    # Arrow keys move the text cursor inside the read-only text note without flipping screenshots.
    card._text_note.setFocus()
    cursor = card._text_note.textCursor()
    cursor.setPosition(0)
    card._text_note.setTextCursor(cursor)
    QTest.keyClick(card._text_note, Qt.Key.Key_Right)
    assert card._text_note.textCursor().position() == 1
    assert card._index == 0

    # Arrow keys on a non-text button navigate the screenshot carousel.
    card._next.setFocus()
    QTest.keyClick(card._next, Qt.Key.Key_Right)
    assert card._index == 1
    assert card._position.text() == "Screenshot 2 of 2"


def test_autoplay_disabled_respects_preference_and_persists_toggle(memory_context) -> None:
    controller = memory_context["controller"]
    memory = memory_context["memory"]
    game_a = memory_context["game_a"]
    player = memory_context["player"]

    memory.set_autoplay_enabled(False)
    controller.game_started(GameStarted(game_a, "new-session", 500_000))
    card = controller._card
    assert card is not None
    assert player.played == []
    assert card._autoplay.isChecked() is False

    # Re-enabling autoplay from the card persists to SQLite.
    card._autoplay.setChecked(True)
    _until(memory.autoplay_enabled)


def test_play_preview_dispatches_on_launch_and_deduplicates_watcher_start(memory_context) -> None:
    controller = memory_context["controller"]
    game_a = memory_context["game_a"]
    player = memory_context["player"]
    coordinator = memory_context["coordinator"]
    opened_uris = memory_context["opened_uris"]

    controller.open_play_preview(game_a)
    card = controller._card
    assert card is not None
    assert card._launch is not None and card._launch.isEnabled()
    assert opened_uris == []
    assert len(player.played) == 1

    # Explicit Launch dispatches the Steam URI and closes the preview.
    card._launch.click()
    _until(lambda: controller._card is None)
    assert opened_uris == ["steam://rungameid/420"]

    # Watcher claims the attempt and emits GameStarted -> no duplicate card or autoplay!
    attempt_id = coordinator.claim(game_a)
    assert attempt_id is not None
    controller.game_started(GameStarted(game_a, "session-started", 600_000, attempt_id))
    assert controller._card is None
    assert len(player.played) == 1

    # Next external start (no attempt_id) shows the card again.
    controller.game_stopped(GameStopped(game_a, "session-started", 650_000, 50, "completed", "process_exit"))
    controller.game_started(GameStarted(game_a, "session-external", 700_000, None))
    assert controller._card is not None
    assert len(player.played) == 2


def test_failed_launch_keeps_preview_open_with_error(memory_context) -> None:
    controller = memory_context["controller"]
    game_a = memory_context["game_a"]
    memory_context["launch_error"][0] = "launch_handler_missing"

    controller.open_play_preview(game_a)
    card = controller._card
    assert card is not None and card._launch is not None
    card._launch.click()
    _until(lambda: card._error.isVisible() and card._launch.isEnabled())
    assert controller._card is card
    assert "launcher" in card._error.text().lower()


def test_empty_states_and_missing_launch_target_preserve_context(memory_context) -> None:
    controller = memory_context["controller"]
    game_b = memory_context["game_b"]

    controller.open_play_preview(game_b)
    card = controller._card
    assert card is not None
    assert "No previous ended sessions" in card._summary.text()
    assert "No voice note saved yet" in card._voice_status.text()
    assert "No screenshots saved" in card._preview.text()
    assert "No controls pinned yet" in card._controls.text()
    assert card._launch is not None and not card._launch.isEnabled()
    assert card._error.isVisible()


def test_reopen_hotkey_resolution_order_and_no_autoplay(memory_context) -> None:
    controller = memory_context["controller"]
    game_a = memory_context["game_a"]
    game_b = memory_context["game_b"]
    foreground = memory_context["foreground"]
    selected = memory_context["selected"]
    reveal = memory_context["reveal"]
    player = memory_context["player"]

    # Nothing active or selected -> reveals Library.
    controller.reopen_hotkey()
    reveal.assert_called_once()
    assert controller._card is None

    # Selected game in Library -> opens its card without autoplaying.
    selected.return_value = game_a
    controller.reopen_hotkey()
    assert controller._card is not None
    assert controller._card._data.game_id == game_a
    assert player.played == []

    # Single active tracked game wins over selected game.
    controller.game_started(GameStarted(game_b, "active-b", 900_000, "suppressed"))
    controller.reopen_hotkey()
    assert controller._card is not None
    assert controller._card._data.game_id == game_b

    # Focused tracked game wins over everything else.
    foreground.return_value = SessionIdentity(game_a, "active-a")
    controller.reopen_hotkey()
    assert controller._card is not None
    assert controller._card._data.game_id == game_a
    assert player.played == []

    # Multiple active games with no focus and no selection reveals Library.
    foreground.return_value = None
    selected.return_value = None
    controller.game_started(GameStarted(game_a, "active-a", 950_000, "suppressed-a"))
    controller._card.reject()
    controller.reopen_hotkey()
    assert reveal.call_count == 2
    assert memory_context["notify"].call_count == 1


def test_voice_failure_keeps_error_visible_and_preserves_other_controls(memory_context) -> None:
    controller = memory_context["controller"]
    game_a = memory_context["game_a"]
    player = memory_context["player"]
    player.should_fail = True

    controller.open_play_preview(game_a)
    card = controller._card
    assert card is not None
    # Simulate Qt emitting playingChanged(False) right after failed.
    player.playingChanged.emit(False)
    assert "could not play" in card._voice_status.text().lower()
    assert card._launch is not None and card._launch.isEnabled()


def test_play_preview_disables_launch_when_game_already_running(memory_context) -> None:
    controller = memory_context["controller"]
    game_a = memory_context["game_a"]
    controller.game_started(GameStarted(game_a, "running-1", 500_000, "suppressed"))

    controller.open_play_preview(game_a)
    card = controller._card
    assert card is not None
    assert card._launch is not None and not card._launch.isEnabled()
    assert "already running" in card._error.text().lower()
