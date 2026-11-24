"""Run library work off the Qt thread and publish the result to the view."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from gamehub.core.library.models import GameSource
from gamehub.core.library.service import LibraryService, LibrarySnapshot, ScanIssue
from gamehub.core.sessions.models import GameStarted, GameStopped
from gamehub.core.storage.db import StorageError
from gamehub.ui.library_view import LibraryView

SOURCE_NAMES = {
    GameSource.STEAM: "Steam",
    GameSource.EPIC: "Epic Games",
    GameSource.RIOT: "Riot Games",
    GameSource.GOG: "GOG",
    GameSource.EA: "EA app",
    GameSource.UBISOFT: "Ubisoft Connect",
    GameSource.BATTLENET: "Battle.net",
    GameSource.ITCH: "itch.io",
    GameSource.XBOX: "Xbox",
    GameSource.FOLDER: "Scanned folder",
    GameSource.MANUAL: "Manual",
}


class LibraryController(QObject):
    _completed = Signal(object, bool)

    def __init__(self, view: LibraryView, service: LibraryService) -> None:
        super().__init__(view)
        self._view = view
        self._service = service
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="library")
        self._busy = False
        self._quiet_running = False
        self._session_update_pending = False
        self._completed.connect(self._show_result)
        view.refreshRequested.connect(self.refresh)
        view.addRequested.connect(self._add)
        view.assignRequested.connect(self._assign)

    def refresh(self) -> None:
        self._run(self._service.refresh)

    def session_updated(self, _event: GameStarted | GameStopped) -> None:
        if self._busy or self._quiet_running:
            self._session_update_pending = True
        else:
            self._run(self._service.current, quiet=True)

    def _add(self, path: str) -> None:
        self._run(lambda: self._service.add_manual(Path(path)))

    def assign_target(self, game_id: str, path: str) -> None:
        self._assign(game_id, path)

    def apply_scan_folder(
        self, folder: Path, choices: list[tuple[Path, str, str | None]]
    ) -> None:
        self._run(lambda: self._service.apply_scan_folder(folder, choices))

    def remove_scan_folder(self, folder: Path) -> None:
        self._run(lambda: self._service.remove_scan_folder(folder))

    def _assign(self, game_id: str, path: str) -> None:
        self._run(lambda: self._service.assign_target(game_id, Path(path)))

    def _run(self, task: Callable[[], LibrarySnapshot], *, quiet: bool = False) -> None:
        if self._busy:
            return
        if quiet:
            self._quiet_running = True
        else:
            self._busy = True
            self._view.clear_error()
            self._view.set_busy(True)
        self._worker.submit(task).add_done_callback(
            lambda future: self._completed.emit(future, quiet)
        )

    def _show_result(self, future: Future[LibrarySnapshot], quiet: bool) -> None:
        if quiet:
            self._quiet_running = False
        else:
            self._busy = False
            self._view.set_busy(False)
        try:
            self._apply_result(future, quiet=quiet)
        finally:
            if self._session_update_pending and not self._busy and not self._quiet_running:
                self._session_update_pending = False
                self._run(self._service.current, quiet=True)

    def _describe_issue(self, issue: ScanIssue) -> str:
        name = SOURCE_NAMES.get(issue.source, issue.source.value)
        code = issue.reason_code
        if "index" in code or "folder" in code or "directory" in code or "drive" in code:
            return self.tr("{launcher}: some game folders could not be read.").format(
                launcher=name
            )
        if "manifest" in code or "metadata" in code or "installs" in code:
            return self.tr("{launcher}: some game entries could not be read.").format(
                launcher=name
            )
        if "database" in code:
            return self.tr("{launcher}: its local library database could not be read.").format(
                launcher=name
            )
        if "registry" in code or "package" in code:
            return self.tr("{launcher}: installed app records could not be read.").format(
                launcher=name
            )
        if "limit" in code:
            return self.tr("{launcher}: too many items to scan at once.").format(launcher=name)
        return self.tr("{launcher}: could only be scanned partially.").format(launcher=name)

    def _apply_result(self, future: Future[LibrarySnapshot], *, quiet: bool) -> None:
        try:
            result = future.result()
        except ValueError:
            self._view.show_error(
                self.tr("Choose a local game executable that is available for tracking.")
            )
            return
        except (OSError, StorageError):
            if not quiet:
                self._view.show_error(
                    self.tr("GameRewind could not read or update your library. Try again.")
                )
            return
        self._view.present_games(result.games)
        if result.scan_issues:
            # Deduplicate human-readable messages while keeping order.
            seen: dict[str, None] = {}
            for issue in result.scan_issues:
                seen[self._describe_issue(issue)] = None
            lines = list(seen.keys())
            summary = " ".join(lines[:2])
            if len(lines) > 2:
                summary += " " + self.tr("({count} more)").format(count=len(lines) - 2)
            details = "\n".join(f"• {line}" for line in lines) + "\n\n" + self.tr(
                "If a game is on an external drive, reconnect the drive and press Retry. "
                "You can also use Scan folder or Add game to add games directly."
            )
            self._view.show_scan_warning(summary, details)
        elif result.partial_sources:
            names = ", ".join(
                SOURCE_NAMES.get(source, source.value) for source in result.partial_sources
            )
            summary = self.tr("These launchers could only be partially scanned: {names}.").format(
                names=names
            )
            self._view.show_scan_warning(summary, summary)

    def close(self, *, wait: bool = True) -> None:
        self._worker.shutdown(wait=wait, cancel_futures=True)
