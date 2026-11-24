"""Coordinate Play-through, Strict-mode suspension, and external protected-game safeguards."""

import logging
from collections.abc import Callable
from time import time_ns

from gamehub.core.protection.catalog import ProtectedGameDetected, ProtectedGamesCatalog
from gamehub.core.sessions.models import GameStarted, GameStopped
from gamehub.core.storage.db import StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.pending_notes import PendingNoteRepository

LOGGER = logging.getLogger(__name__)


class LifecycleCoordinator:
    """Own game-aware runtime transitions without touching any game process."""

    def __init__(
        self,
        catalog: ProtectedGamesCatalog,
        library: LibraryRepository,
        pending_notes: PendingNoteRepository,
        *,
        external_behavior: str = "exit_app",
        suspend_hotkeys: Callable[[], None] = lambda: None,
        resume_hotkeys: Callable[[], None] = lambda: None,
        pause_capture: Callable[[], None] = lambda: None,
        resume_capture: Callable[[], None] = lambda: None,
        minimize_window: Callable[[], None] = lambda: None,
        restore_window: Callable[[], None] = lambda: None,
        exit_app: Callable[[], None] = lambda: None,
        show_status: Callable[[str], None] = lambda _msg: None,
        notify_passive: Callable[[str], None] = lambda _name: None,
        prompts_enabled: Callable[[], bool] = lambda: True,
        clock_ms: Callable[[], int] = lambda: time_ns() // 1_000_000,
    ) -> None:
        self._catalog = catalog
        self._library = library
        self._pending_notes = pending_notes
        self._external_behavior = external_behavior
        self._suspend_hotkeys = suspend_hotkeys
        self._resume_hotkeys = resume_hotkeys
        self._pause_capture = pause_capture
        self._resume_capture = resume_capture
        self._minimize_window = minimize_window
        self._restore_window = restore_window
        self._exit_app = exit_app
        self._show_status = show_status
        self._notify_passive = notify_passive
        self._prompts_enabled = prompts_enabled
        self._clock_ms = clock_ms

        self._active_strict_games: set[str] = set()
        self._external_strict_entries: set[str] = set()
        self._play_launched_games: dict[str, bool] = {}
        self._exit_after_prompt: set[str] = set()
        self._strict_enforced = False

    def set_external_behavior(self, behavior: str) -> None:
        if behavior in {"exit_app", "strict_mode", "ask_me"}:
            self._external_behavior = behavior

    def is_strict_active(self) -> bool:
        return bool(self._active_strict_games or self._external_strict_entries)

    def is_strict_game(self, game_id: str) -> bool:
        try:
            game = self._library.get_game(game_id)
            if game is None:
                return False
            exes = self._library.list_target_basenames().get(game_id, ())
        except StorageError:
            return False
        return (
            self._catalog.effective_mode(game.protection_mode, game.source, game.source_id, exes)
            == "strict"
        )

    def on_play_launched(self, game_id: str, *, exit_after_play: bool) -> bool:
        """Handle a Play launch. Returns True if GameRewind exited immediately.

        Layer 5 (Zero-Presence): any protected / strict game ALWAYS saves a deferred
        pending note and exits GameRewind immediately after the official launcher starts
        so GameRewind is never running alongside a protected game or its anti-cheat.
        """
        strict = self.is_strict_game(game_id)
        if strict:
            try:
                self._pending_notes.add(game_id, self._clock_ms())
            except StorageError:
                LOGGER.warning("pending_note_save_failed game=%s", game_id)
            self._exit_app()
            return True

        self._play_launched_games[game_id] = exit_after_play
        self._minimize_window()
        return False

    def on_game_started(self, event: GameStarted) -> None:
        if self.is_strict_game(event.game_id):
            self._active_strict_games.add(event.game_id)
            self._sync_strict_enforcement()

    def on_game_stopped(self, event: GameStopped) -> None:
        self._active_strict_games.discard(event.game_id)
        self._sync_strict_enforcement()

        exit_after_play = self._play_launched_games.pop(event.game_id, False)
        normal_exit = event.status == "completed" and event.reason == "process_exit"
        if not normal_exit:
            return
        if exit_after_play:
            if self._prompts_enabled():
                self._exit_after_prompt.add(event.game_id)
            else:
                self._exit_app()
                return
        if not self._prompts_enabled():
            self._restore_window()

    def on_note_prompt_finished(self, game_id: str) -> None:
        if game_id in self._exit_after_prompt:
            self._exit_after_prompt.discard(game_id)
            self._exit_app()
            return
        self._restore_window()

    def on_protected_detected(self, event: ProtectedGameDetected) -> None:
        """Handle the forgetful case: a protected game started outside GameRewind."""
        if event.game_id is not None and (
            event.game_id in self._play_launched_games
            or event.game_id in self._active_strict_games
        ):
            return

        behavior = self._external_behavior
        if behavior == "exit_app":
            LOGGER.info("protected_game_auto_exit id=%s name=%s", event.entry_id, event.entry_name)
            self._exit_app()
            return

        # Both strict_mode and ask_me immediately engage precautionary Strict mode.
        self._external_strict_entries.add(event.entry_id)
        self._sync_strict_enforcement()
        self._minimize_window()
        if behavior == "ask_me":
            self._notify_passive(event.entry_name)
        else:
            self._show_status(event.entry_name)

    def clear_external_protected(self, entry_id: str) -> None:
        if entry_id in self._external_strict_entries:
            self._external_strict_entries.discard(entry_id)
            self._sync_strict_enforcement()

    def _sync_strict_enforcement(self) -> None:
        want_strict = self.is_strict_active()
        if want_strict and not self._strict_enforced:
            self._strict_enforced = True
            self._suspend_hotkeys()
            self._pause_capture()
        elif not want_strict and self._strict_enforced:
            self._strict_enforced = False
            self._resume_hotkeys()
            self._resume_capture()
