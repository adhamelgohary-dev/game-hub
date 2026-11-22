"""Coordinate Ctrl+Alt+C foreground pinning and per-game controls imports."""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot

from gamehub.core.storage.controls import MAX_TEXT_LENGTH, ControlsRepository
from gamehub.core.storage.db import StorageError
from gamehub.core.storage.memory import MemoryChanged

LOGGER = logging.getLogger(__name__)


class ControlsController(QObject):
    _done = Signal(object, object)
    errorOccurred = Signal(str, str)

    def __init__(
        self,
        parent: QObject,
        controls: ControlsRepository,
        pin_foreground: Callable[[Callable[[str, str, bytes | None], None]], str] | None,
        publish: Callable[[MemoryChanged], None],
        notify: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._controls = controls
        self._pin_foreground = pin_foreground
        self._publish = publish
        self._notify = notify
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game-controls")
        self._done.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self._closed = False

    def pin_hotkey(self) -> None:
        if self._closed:
            return
        if self._pin_foreground is None:
            self._notify(
                self.tr(
                    "Window capture is unavailable. Upload a local controls image from the game page."
                )
            )
            return
        status = self._pin_foreground(self._pin_captured)
        if status == "no_foreground_game":
            self._notify(
                self.tr(
                    "Focus a tracked game window to pin controls, or upload an image from the game page."
                )
            )
        elif status == "busy":
            self._notify(
                self.tr("Capture is busy. Try Ctrl+Alt+C again or upload an image from the game page.")
            )

    def import_image(self, game_id: str, path: str) -> None:
        if self._closed:
            return

        def done(future: Future) -> None:
            if self._closed:
                return
            try:
                control_id = future.result()
            except ValueError:
                self.errorOccurred.emit(
                    game_id,
                    self.tr(
                        "Select a supported local image (PNG, JPEG, WebP, or BMP) up to 16 MB."
                    ),
                )
            except StorageError:
                self.errorOccurred.emit(
                    game_id, self.tr("Game Hub could not save this controls image.")
                )
            else:
                self._publish(MemoryChanged(game_id, None, "control_image", control_id))

        self._submit(lambda: self._controls.import_image(game_id, Path(path)), done)

    def save_text(self, game_id: str, text: str) -> None:
        if self._closed:
            return

        def done(future: Future) -> None:
            if self._closed:
                return
            try:
                control_id = future.result()
            except ValueError:
                self.errorOccurred.emit(
                    game_id,
                    self.tr("Enter a nonblank controls note of up to {limit} characters.").format(
                        limit=MAX_TEXT_LENGTH
                    ),
                )
            except StorageError:
                self.errorOccurred.emit(
                    game_id, self.tr("Game Hub could not save this controls note.")
                )
            else:
                self._publish(MemoryChanged(game_id, None, "control_text", control_id))

        self._submit(lambda: self._controls.pin_text(game_id, text), done)

    def _pin_captured(self, game_id: str, session_id: str, data: bytes | None) -> None:
        if self._closed:
            return
        if data is None:
            self._notify(
                self.tr(
                    "Could not capture the game window. Upload a local controls image from the game page."
                )
            )
            return

        def done(future: Future) -> None:
            if self._closed:
                return
            try:
                control_id = future.result()
            except (StorageError, ValueError):
                LOGGER.warning("controls_pin_save_failed")
                self._notify(
                    self.tr(
                        "Game Hub could not save the pinned controls image. "
                        "You can upload a local image from the game page."
                    )
                )
            else:
                self._publish(MemoryChanged(game_id, session_id, "control_image", control_id))
                self._notify(self.tr("Pinned controls screenshot."))

        self._submit(lambda: self._controls.pin_image(game_id, data), done)

    def _submit(self, work: Callable, done: Callable[[Future], None]) -> None:
        def forward(future: Future) -> None:
            if not self._closed:
                self._done.emit(done, future)

        self._worker.submit(work).add_done_callback(forward)

    @Slot(object, object)
    def _complete(self, done: Callable[[Future], None], future: Future) -> None:
        if not self._closed:
            done(future)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._worker.shutdown(wait=True)
