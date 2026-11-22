"""Run library work off the Qt thread and publish the result to the view."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from gamehub.core.library.models import GameSource
from gamehub.core.library.service import LibraryService, LibrarySnapshot
from gamehub.core.storage.db import StorageError
from gamehub.ui.library_view import LibraryView

SOURCE_NAMES = {
    GameSource.STEAM: "Steam",
    GameSource.EPIC: "Epic Games",
    GameSource.XBOX: "Xbox",
}


class LibraryController(QObject):
    _completed = Signal(object)

    def __init__(self, view: LibraryView, service: LibraryService) -> None:
        super().__init__(view)
        self._view = view
        self._service = service
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="library")
        self._busy = False
        self._completed.connect(self._show_result)
        view.refreshRequested.connect(self.refresh)
        view.addRequested.connect(self._add)
        view.assignRequested.connect(self._assign)

    def refresh(self) -> None:
        self._run(self._service.refresh)

    def _add(self, path: str) -> None:
        self._run(lambda: self._service.add_manual(Path(path)))

    def _assign(self, game_id: str, path: str) -> None:
        self._run(lambda: self._service.assign_target(game_id, Path(path)))

    def _run(self, task: Callable[[], LibrarySnapshot]) -> None:
        if self._busy:
            return
        self._busy = True
        self._view.clear_error()
        self._view.set_busy(True)
        self._worker.submit(task).add_done_callback(self._completed.emit)

    def _show_result(self, future: Future[LibrarySnapshot]) -> None:
        self._busy = False
        self._view.set_busy(False)
        try:
            result = future.result()
        except ValueError:
            self._view.show_error("Choose a local game executable that is available for tracking.")
            return
        except (OSError, StorageError):
            self._view.show_error("Game Hub could not read or update your library. Try again.")
            return
        self._view.present_games(result.games)
        if result.partial_sources:
            names = ", ".join(SOURCE_NAMES[source] for source in result.partial_sources)
            self._view.show_error(f"These launchers could only be partially scanned: {names}.")

    def close(self) -> None:
        self._worker.shutdown(cancel_futures=True)
