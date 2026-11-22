"""Coordinate independent game detectors and persistence."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from gamehub.core.library.models import (
    DiscoveryBatch,
    GameDetector,
    GameSource,
    GameSummary,
    LibraryChanged,
)
from gamehub.core.storage.library import LibraryRepository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    games: tuple[GameSummary, ...]
    partial_sources: tuple[GameSource, ...] = ()


class LibraryService:
    def __init__(
        self,
        repository: LibraryRepository,
        detectors: Sequence[GameDetector],
        publish: Callable[[LibraryChanged], None] | None = None,
    ) -> None:
        self._repository = repository
        self._detectors = tuple(detectors)
        self._publish = publish

    def refresh(self) -> LibrarySnapshot:
        partial_sources = []
        for detector in self._detectors:
            try:
                batch = detector.discover()
            except (OSError, ValueError):
                batch = DiscoveryBatch(state="partial", diagnostics=("launcher_scan_failed",))
            for diagnostic in batch.diagnostics:
                LOGGER.warning("library_scan source=%s status=%s", detector.source.value, diagnostic)
            self._notify(self._repository.reconcile(detector.source, batch))
            if batch.state == "partial":
                partial_sources.append(detector.source)
        return LibrarySnapshot(self._repository.list_games(), tuple(partial_sources))

    def current(self) -> LibrarySnapshot:
        return LibrarySnapshot(self._repository.list_games())

    def add_manual(self, executable: Path) -> LibrarySnapshot:
        self._notify((self._repository.add_manual(executable),))
        return self.current()

    def assign_target(self, game_id: str, executable: Path) -> LibrarySnapshot:
        self._notify((self._repository.assign_target(game_id, executable),))
        return self.current()

    def _notify(self, game_ids: tuple[str, ...]) -> None:
        if self._publish is not None and game_ids:
            self._publish(LibraryChanged(game_ids))
