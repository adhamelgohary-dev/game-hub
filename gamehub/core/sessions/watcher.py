"""Sample the Windows process inventory on a dedicated worker."""

import logging
import ntpath
from collections import defaultdict
from collections.abc import Callable
from threading import Event, Lock, Thread
from time import monotonic, time_ns

from gamehub.core.library.models import LibraryChanged
from gamehub.core.protection.catalog import (
    ProtectedGameDetected,
    ProtectedGameExited,
    ProtectedGamesCatalog,
)
from gamehub.core.sessions.models import ClockReading, ProcessSnapshot, WatchTarget
from gamehub.core.sessions.processes import ProcessProbe
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.storage.db import StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.sessions import SessionRepository

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SEC = 3.0


class SessionWatcher:
    def __init__(
        self,
        store: SessionRepository,
        probe: ProcessProbe,
        tracker: SessionTracker,
        interval: float = POLL_INTERVAL_SEC,
        *,
        catalog: ProtectedGamesCatalog | None = None,
        library: LibraryRepository | None = None,
        publish_protected: Callable[[ProtectedGameDetected], None] | None = None,
    ) -> None:
        self._store = store
        self._probe = probe
        self._tracker = tracker
        self._interval = interval
        self._catalog = catalog
        self._library = library
        self._publish_protected = publish_protected
        self._stop = Event()
        self._paused = Event()
        self._poll_lock = Lock()
        self._reload_targets = Event()
        self._reload_targets.set()
        self._announced_protected: set[str] = set()
        self._ignored_lock = Lock()
        self._ignored_pids: set[int] = set()
        self._thread = Thread(target=self._run, name="game-session-watcher", daemon=True)

    def ignore_pid(self, pid: int) -> None:
        with self._ignored_lock:
            self._ignored_pids.add(int(pid))

    def unignore_pid(self, pid: int) -> None:
        with self._ignored_lock:
            self._ignored_pids.discard(int(pid))

    def start(self) -> None:
        self._store.recover()
        self._thread.start()

    def pause(self) -> None:
        """Pause polling and wait for any active poll cycle to finish."""
        self._paused.set()
        with self._poll_lock:
            pass

    def resume(self) -> None:
        self._paused.clear()

    def close(self, *, wait: bool = True, timeout: float = 0.5) -> None:
        self._stop.set()
        self._paused.clear()
        if wait and self._thread.ident is not None:
            self._thread.join(timeout=timeout)

    def library_changed(self, _event: LibraryChanged) -> None:
        self._reload_targets.set()

    def reload_protection(self) -> None:
        self._reload_targets.set()

    def _build_watch_plan(
        self, raw_targets: tuple[WatchTarget, ...]
    ) -> tuple[
        tuple[WatchTarget, ...],
        dict[str, frozenset[str]],
        frozenset[str],
        dict[str, str],
        frozenset[str],
    ]:
        if self._catalog is None:
            return raw_targets, {}, frozenset(), {}, frozenset()

        protected_exes = set(self._catalog.all_exe_names())
        strict_games: set[str] = set()
        full_override_exes: set[str] = set()
        passive_map: dict[str, set[str]] = defaultdict(set)
        exe_to_game: dict[str, str] = {}

        if self._library is not None:
            basenames_by_game = self._library.list_target_basenames()
            for game in self._library.list_games():
                if not game.installed:
                    continue
                target_exes = basenames_by_game.get(game.id, ())
                matched = self._catalog.match_game(
                    game.source, game.source_id, target_exes, game_name=game.name
                )
                mode = self._catalog.effective_mode(
                    game.protection_mode,
                    game.source,
                    game.source_id,
                    target_exes,
                    game_name=game.name,
                )
                combined_exes = set(target_exes)
                if matched is not None:
                    combined_exes.update(matched.exe_names)
                for exe in combined_exes:
                    exe_to_game.setdefault(exe, game.id)
                if mode == "strict":
                    strict_games.add(game.id)
                    for exe in combined_exes:
                        passive_map[exe].add(game.id)
                elif matched is not None and game.protection_mode == "full":
                    # User explicitly opted this game into Full mode: only exempt its game_exes,
                    # NEVER exempt global anti-cheat binaries or always-strict launchers.
                    full_override_exes.update(matched.game_exes)
                    full_override_exes.update(target_exes)

        games_with_exe = {target.game_id for target in raw_targets if target.kind == "exe_path"}
        active_targets = tuple(
            target
            for target in raw_targets
            if target.game_id not in strict_games
            and (target.kind == "exe_path" or target.game_id in games_with_exe)
        )
        always_protected = set(self._catalog.global_anti_cheat_exes)
        for exes in self._catalog.always_strict_launchers.values():
            always_protected.update(exes)
        for entry in self._catalog.entries:
            always_protected.update(entry.anti_cheat_exes)
        effective_protected = frozenset(
            protected_exes.difference(full_override_exes) | always_protected
        )
        passive_frozen = {exe: frozenset(ids) for exe, ids in passive_map.items()}
        return active_targets, passive_frozen, effective_protected, exe_to_game, frozenset(strict_games)

    def _run(self) -> None:
        raw_targets: tuple[WatchTarget, ...] = ()
        active_targets: tuple[WatchTarget, ...] = ()
        passive_basenames: dict[str, frozenset[str]] = {}
        protected_exes: frozenset[str] = frozenset()
        exe_to_game: dict[str, str] = {}
        strict_games: frozenset[str] = frozenset()
        try:
            while not self._stop.is_set():
                started = monotonic()
                if not self._paused.is_set():
                    with self._poll_lock:
                        if not self._paused.is_set() and not self._stop.is_set():
                            try:
                                next_raw = raw_targets
                                next_active = active_targets
                                next_passive = passive_basenames
                                next_protected = protected_exes
                                next_exe_to_game = exe_to_game
                                next_strict = strict_games
                                reloaded = False
                                if self._reload_targets.is_set():
                                    self._reload_targets.clear()
                                    reloaded = True
                                    next_raw = self._store.watch_targets()
                                    (
                                        next_active,
                                        next_passive,
                                        next_protected,
                                        next_exe_to_game,
                                        next_strict,
                                    ) = self._build_watch_plan(next_raw)

                                with self._ignored_lock:
                                    ignored_pids = frozenset(self._ignored_pids)
                                never_open = (
                                    self._catalog.all_launcher_exe_names()
                                    if self._catalog is not None
                                    else frozenset()
                                )
                                if next_passive or next_protected or ignored_pids or never_open:
                                    snapshot = self._probe.snapshot(
                                        next_active,
                                        passive_basenames=next_passive,
                                        protected_exes=next_protected,
                                        never_open_exes=never_open,
                                        ignored_pids=ignored_pids,
                                    )
                                else:
                                    snapshot = self._probe.snapshot(next_active)
                                if reloaded:
                                    if self._finish_removed_games(raw_targets, next_raw, snapshot):
                                        raw_targets = next_raw
                                        active_targets = next_active
                                        passive_basenames = next_passive
                                        protected_exes = next_protected
                                        exe_to_game = next_exe_to_game
                                        strict_games = next_strict
                                    else:
                                        self._reload_targets.set()
                                self._tracker.observe(
                                    snapshot, ClockReading(time_ns() // 1_000_000, monotonic())
                                )
                                self._emit_protected_detections(snapshot, exe_to_game)
                            except StorageError:
                                self._tracker.mark_unreliable()
                                self._reload_targets.set()
                                LOGGER.warning("session_storage_unavailable")
                delay = max(0.0, self._interval - (monotonic() - started))
                self._stop.wait(delay)
        finally:
            try:
                self._tracker.shutdown()
            except StorageError:
                LOGGER.warning("session_shutdown_checkpoint_retained")

    def _emit_protected_detections(
        self, snapshot: ProcessSnapshot, exe_to_game: dict[str, str]
    ) -> None:
        if self._catalog is None or self._publish_protected is None:
            return
        currently_seen: set[str] = set()
        for exe in sorted(snapshot.protected_exes):
            entry = self._catalog.match_exe_name(exe)
            if entry is None:
                continue
            currently_seen.add(entry.id)
            if entry.id not in self._announced_protected:
                self._announced_protected.add(entry.id)
                game_id = exe_to_game.get(ntpath.normcase(exe))
                LOGGER.info(
                    "protected_game_detected id=%s name=%s", entry.id, entry.name
                )
                self._publish_protected(
                    ProtectedGameDetected(
                        entry_id=entry.id,
                        entry_name=entry.name,
                        anti_cheat=entry.anti_cheat,
                        exe_name=exe,
                        game_id=game_id,
                    )
                )
        exited = self._announced_protected.difference(currently_seen)
        self._announced_protected.intersection_update(currently_seen)
        for entry_id in sorted(exited):
            self._publish_protected(ProtectedGameExited(entry_id=entry_id))

    def _finish_removed_games(
        self,
        previous: tuple[WatchTarget, ...],
        current: tuple[WatchTarget, ...],
        snapshot: ProcessSnapshot,
    ) -> bool:
        removed = set(previous).difference(current)
        affected = {target.game_id for target in removed}.difference(snapshot.games)
        uncertain = set()
        if not snapshot.complete:
            uncertain = affected.intersection(target.game_id for target in current)
        for game_id in affected.difference(uncertain):
            self._tracker.target_removed(game_id)
        return not uncertain
