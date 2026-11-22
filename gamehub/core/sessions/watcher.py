"""Sample the Windows process inventory on a dedicated worker."""

import logging
from threading import Event, Thread
from time import monotonic, time_ns

from gamehub.core.library.models import LibraryChanged
from gamehub.core.sessions.models import ClockReading, ProcessSnapshot, WatchTarget
from gamehub.core.sessions.processes import ProcessProbe
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.storage.db import StorageError
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
    ) -> None:
        self._store = store
        self._probe = probe
        self._tracker = tracker
        self._interval = interval
        self._stop = Event()
        self._reload_targets = Event()
        self._reload_targets.set()
        self._thread = Thread(target=self._run, name="game-session-watcher")

    def start(self) -> None:
        self._store.recover()
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join()

    def library_changed(self, _event: LibraryChanged) -> None:
        self._reload_targets.set()

    def _run(self) -> None:
        targets = ()
        try:
            while not self._stop.is_set():
                started = monotonic()
                try:
                    next_targets = targets
                    if self._reload_targets.is_set():
                        self._reload_targets.clear()
                        next_targets = self._store.watch_targets()
                    snapshot = self._probe.snapshot(next_targets)
                    if targets is not next_targets:
                        if self._finish_removed_games(targets, next_targets, snapshot):
                            targets = next_targets
                        else:
                            self._reload_targets.set()
                    self._tracker.observe(snapshot, ClockReading(time_ns() // 1_000_000, monotonic()))
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
