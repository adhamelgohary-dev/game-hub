"""Coordinate the Last time card, local voice playback, Ctrl+Alt+L, and Play launches."""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QWidget

from gamehub.core.audio.player import VoicePlayer
from gamehub.core.library.launcher import LaunchCoordinator, LaunchResult
from gamehub.core.library.models import LaunchTarget
from gamehub.core.sessions.models import GameStarted, GameStopped, SessionIdentity
from gamehub.core.storage.db import StorageError
from gamehub.core.storage.memory import MemoryRepository
from gamehub.modules.memory.last_time_card import LastTimeCard

LOGGER = logging.getLogger(__name__)


class LastTimeController(QObject):
    _done = Signal(object, object)

    def __init__(
        self,
        parent: QWidget,
        memory: MemoryRepository,
        load_image: Callable[[Path], bytes | None],
        player: VoicePlayer,
        launcher: LaunchCoordinator,
        foreground_session: Callable[[], SessionIdentity | None],
        selected_game: Callable[[], str | None],
        reveal_library: Callable[[], None],
        notify: Callable[[str], None],
        *,
        load_control_image: Callable[[Path], bytes | None] | None = None,
        is_strict_game: Callable[[str], bool] | None = None,
        before_strict_launch: Callable[[str], None] | None = None,
        on_launch_accepted: Callable[[str, bool], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = parent
        self._memory = memory
        self._load_image = load_image
        self._load_control_image = load_control_image or (lambda _path: None)
        self._is_strict_game = is_strict_game or (lambda _game_id: False)
        self._before_strict_launch = before_strict_launch
        self._on_launch_accepted = on_launch_accepted
        self._player = player
        self._launcher = launcher
        self._foreground_session = foreground_session
        self._selected_game = selected_game
        self._reveal_library = reveal_library
        self._notify = notify
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game-memory")
        self._done.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self._active_sessions: dict[str, str] = {}
        self._card: LastTimeCard | None = None
        self._last_game_id: str | None = None
        self._voice_path: Path | None = None
        self._autoplay: bool | None = None
        self._closed = False

        self._player.playingChanged.connect(self._playing_changed)
        self._player.failed.connect(self._playback_failed)

    def set_autoplay_enabled(self, enabled: bool) -> None:
        self._autoplay = enabled
        if self._card is not None:
            self._card.set_autoplay_checked(enabled)

    def game_started(self, event: GameStarted) -> None:
        if self._closed:
            return
        self._active_sessions[event.game_id] = event.session_id
        if event.launch_attempt_id is not None:
            return
        if self._is_strict_game(event.game_id):
            return
        self._present(
            event.game_id,
            exclude_session_id=event.session_id,
            allow_launch=False,
            automatic=True,
            allow_autoplay=True,
        )

    def game_stopped(self, event: GameStopped) -> None:
        if self._active_sessions.get(event.game_id) == event.session_id:
            del self._active_sessions[event.game_id]

    def open_play_preview(self, game_id: str, *, exit_after_play: bool = False) -> None:
        if self._closed:
            return
        self._present(
            game_id,
            exclude_session_id=self._active_sessions.get(game_id),
            allow_launch=True,
            automatic=False,
            allow_autoplay=True,
            default_exit_after_play=exit_after_play,
        )

    def reopen_hotkey(self) -> None:
        if self._closed:
            return
        target = self._resolve_hotkey_target()
        if target is None:
            self._reveal_library()
            return
        game_id, exclude_session_id = target
        shown = self._present(
            game_id,
            exclude_session_id=exclude_session_id,
            allow_launch=False,
            automatic=False,
            allow_autoplay=False,
        )
        if not shown:
            self._reveal_library()

    def _resolve_hotkey_target(self) -> tuple[str, str | None] | None:
        foreground = self._foreground_session()
        if foreground is not None:
            return foreground.game_id, foreground.session_id

        if len(self._active_sessions) == 1:
            game_id, session_id = next(iter(self._active_sessions.items()))
            return game_id, session_id

        selected = self._selected_game()
        if len(self._active_sessions) > 1:
            if selected is not None:
                return selected, self._active_sessions.get(selected)
            self._notify(
                self.tr("Multiple games are running. Select a game in Library to view its Last time card.")
            )
            return None

        if selected is not None:
            return selected, None
        if self._last_game_id is not None:
            return self._last_game_id, None
        return None

    def _present(
        self,
        game_id: str,
        *,
        exclude_session_id: str | None,
        allow_launch: bool,
        automatic: bool,
        allow_autoplay: bool,
        default_exit_after_play: bool = False,
    ) -> bool:
        try:
            data = self._memory.last_time(game_id, exclude_session_id=exclude_session_id)
            autoplay = (
                self._autoplay if self._autoplay is not None else self._memory.autoplay_enabled()
            )
            self._autoplay = autoplay
        except (OSError, StorageError):
            LOGGER.warning("last_time_load_unavailable")
            self._notify(self.tr("GameRewind could not load the Last time card."))
            return False

        if data is None:
            return False

        self._replace_card()
        card = LastTimeCard(
            data,
            autoplay_enabled=autoplay,
            allow_launch=allow_launch,
            already_running=game_id in self._active_sessions,
            default_exit_after_play=default_exit_after_play,
            load_image=self._load_image,
            load_control_image=self._load_control_image,
            parent=None,
        )
        self._card = card
        self._last_game_id = game_id
        self._voice_path = (
            data.voice_note.path if data.voice_note is not None and data.voice_note.available else None
        )

        card.playVoiceRequested.connect(lambda c=card: self._play_voice(c))
        card.stopVoiceRequested.connect(self._player.stop)
        card.autoplayToggled.connect(lambda enabled, c=card: self._set_autoplay(c, enabled))
        card.launchRequested.connect(
            lambda c=card, g=game_id, t=data.launch_target: self._launch(c, g, t)
        )
        card.finished.connect(lambda _, c=card: self._card_closed(c))

        if automatic:
            card.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            card.show()
        else:
            card.show()
            card.raise_()
            card.activateWindow()

        if allow_autoplay and autoplay and self._voice_path is not None:
            self._play_voice(card)
        return True

    def _replace_card(self) -> None:
        previous = self._card
        self._card = None
        self._voice_path = None
        self._player.stop()
        if previous is not None:
            previous.reject()

    def _card_closed(self, card: LastTimeCard) -> None:
        if self._card is card:
            self._card = None
            self._voice_path = None
            self._player.stop()
        card.deleteLater()

    def _play_voice(self, card: LastTimeCard) -> None:
        if self._card is not card or self._voice_path is None:
            return
        card.clear_voice_error()
        clip = self._memory.read_voice(self._voice_path)
        if clip is None:
            card.show_voice_error(self.tr("This voice note is unavailable."))
            return
        if not self._player.play(clip):
            card.show_voice_error(self.tr("GameRewind could not play this voice note."))

    def _playing_changed(self, playing: bool) -> None:
        if self._card is not None:
            self._card.set_playing(playing)

    def _playback_failed(self) -> None:
        if self._card is not None:
            self._card.show_voice_error(self.tr("GameRewind could not play this voice note."))

    def _set_autoplay(self, card: LastTimeCard, enabled: bool) -> None:
        if self._closed:
            return
        previous = self._autoplay if self._autoplay is not None else not enabled
        self._autoplay = enabled

        def saved(future: Future) -> None:
            if self._closed:
                return
            try:
                future.result()
            except StorageError:
                self._autoplay = previous
                message = self.tr("GameRewind could not save the voice autoplay preference.")
                if self._card is card:
                    card.set_autoplay_checked(previous)
                    card.show_error(message)
                else:
                    self._notify(message)

        self._submit(lambda: self._memory.set_autoplay_enabled(enabled), saved)

    def _launch(self, card: LastTimeCard, game_id: str, target: LaunchTarget | None) -> None:
        if self._closed or self._card is not card or card.is_launching():
            return
        if game_id in self._active_sessions:
            card.show_error(self.tr("This game is already running."))
            return
        self._player.stop()
        if self._is_strict_game(game_id) and self._before_strict_launch is not None:
            self._before_strict_launch(game_id)
        card.clear_error()
        card.set_launching(True)
        self._submit(
            lambda: self._launcher.launch(game_id, target),
            lambda future: self._launch_finished(card, game_id, future),
        )

    def _launch_finished(self, card: LastTimeCard, game_id: str, future: Future) -> None:
        if self._closed:
            return
        try:
            result: LaunchResult = future.result()
        except (OSError, RuntimeError, ValueError):
            LOGGER.warning("launch_dispatch_unexpected_error")
            result = LaunchResult(accepted=False, diagnostic="launch_failed")
        if self._card is not card:
            return
        if result.accepted:
            exit_after_play = card.exit_after_play()
            card.accept()
            if self._on_launch_accepted is not None:
                self._on_launch_accepted(game_id, exit_after_play)
        else:
            card.set_launching(False)
            card.show_error(self._launch_error_message(result.diagnostic))

    def _launch_error_message(self, diagnostic: str | None) -> str:
        if diagnostic == "launch_handler_missing":
            return self.tr(
                "Windows could not find the launcher for this game. Check that the launcher is installed."
            )
        if diagnostic in {"launch_invalid_target", "launch_unavailable"}:
            return self.tr(
                "GameRewind could not launch this game. Check that its executable or launcher entry is still available."
            )
        return self.tr(
            "Windows could not start this game. You can try again or start it from its launcher."
        )

    def _submit(self, work: Callable, done: Callable[[Future], None]) -> None:
        self._worker.submit(work).add_done_callback(lambda future: self._done.emit(done, future))

    @Slot(object, object)
    def _complete(self, done: Callable[[Future], None], future: Future) -> None:
        done(future)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._player.playingChanged.disconnect(self._playing_changed)
            self._player.failed.disconnect(self._playback_failed)
        except RuntimeError:
            pass
        self._replace_card()
        self._worker.shutdown(wait=False, cancel_futures=True)
