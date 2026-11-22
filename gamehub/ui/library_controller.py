"""Run library work off the Qt thread and publish the result to the view."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from gamehub.core.library.models import GameSource
from gamehub.core.library.service import LibraryService, LibrarySnapshot
from gamehub.core.sessions.models import GameStarted, GameStopped
from gamehub.core.storage.db import StorageError
from gamehub.ui.library_view import LibraryView

SOURCE_NAMES = {
    GameSource.STEAM: "Steam",
    GameSource.EPIC: "Epic Games",
    GameSource.XBOX: "Xbox",
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

    def _apply_result(self, future: Future[LibrarySnapshot], *, quiet: bool) -> None:
        try:
            result = future.result()
        except ValueError:
            self._view.show_error("Choose a local game executable that is available for tracking.")
            return
        except (OSError, StorageError):
            if not quiet:
                self._view.show_error("Game Hub could not read or update your library. Try again.")
            return
        self._view.present_games(result.games)
        if result.partial_sources:
            names = ", ".join(SOURCE_NAMES[source] for source in result.partial_sources)
            self._view.show_error(f"These launchers could only be partially scanned: {names}.")

    def close(self) -> None:
        self._worker.shutdown(cancel_futures=True)
