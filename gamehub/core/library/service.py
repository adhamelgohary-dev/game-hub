"""Coordinate independent game detectors and persistence."""

from __future__ import annotations

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
class ScanIssue:
    source: GameSource
    reason_code: str


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    games: tuple[GameSummary, ...]
    partial_sources: tuple[GameSource, ...] = ()
    scan_issues: tuple[ScanIssue, ...] = ()


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
        partial_sources: list[GameSource] = []
        scan_issues: list[ScanIssue] = []
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
                if batch.diagnostics:
                    for code in batch.diagnostics:
                        scan_issues.append(ScanIssue(detector.source, code))
                else:
                    scan_issues.append(ScanIssue(detector.source, "launcher_scan_failed"))
        return LibrarySnapshot(
            self._repository.list_games(),
            tuple(partial_sources),
            tuple(scan_issues),
        )

    def current(self) -> LibrarySnapshot:
        return LibrarySnapshot(self._repository.list_games())

    def add_manual(self, executable: Path) -> LibrarySnapshot:
        self._notify((self._repository.add_manual(executable),))
        return self.current()

    def assign_target(self, game_id: str, executable: Path) -> LibrarySnapshot:
        self._notify((self._repository.assign_target(game_id, executable),))
        return self.current()

    def apply_scan_folder(
        self,
        folder: Path,
        choices: list[tuple[Path, str, str | None]],
    ) -> LibrarySnapshot:
        safe = self._repository.add_scan_folder(folder)
        if choices:
            self._repository.save_scan_choices(safe, choices)
        return self.refresh_source(GameSource.FOLDER)

    def remove_scan_folder(self, folder: Path) -> LibrarySnapshot:
        self._repository.remove_scan_folder(folder)
        return self.refresh_source(GameSource.FOLDER)

    def refresh_source(self, source: GameSource) -> LibrarySnapshot:
        for detector in self._detectors:
            if detector.source == source:
                batch = detector.discover()
                self._notify(self._repository.reconcile(source, batch))
                break
        return self.current()

    def _notify(self, game_ids: tuple[str, ...]) -> None:
        if self._publish is not None and game_ids:
            self._publish(LibraryChanged(game_ids))
