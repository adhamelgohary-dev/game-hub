"""Schedule bounded capture work without blocking the Qt thread."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from gamehub.core.capture.service import DEFAULT_INTERVAL_SEC, CaptureService


class CaptureScheduler(QObject):
    _pin_ready = Signal(object, str, str, object)

    def __init__(
        self,
        service: CaptureService,
        parent: QObject,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game-capture")
        self._current: Future | None = None
        self._closed = False
        self._pin_ready.connect(self._deliver_pin, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(round(interval_sec * 1000))
        self._timer.timeout.connect(self.sample_foreground)

    def start(self) -> None:
        self._timer.start()

    def sample_foreground(self) -> None:
        if self._closed or (self._current is not None and not self._current.done()):
            return
        lease = self._service.acquire()
        if lease is not None:
            self._current = self._worker.submit(self._service.sample, lease)

    def pin_foreground(self, on_done: Callable[[str, str, bytes | None], None]) -> str:
        """Capture one verified foreground frame on the single capture worker for Controls."""
        if self._closed:
            return "busy"
        if self._current is not None and not self._current.done():
            return "busy"
        lease = self._service.acquire()
        if lease is None:
            return "no_foreground_game"

        game_id = lease.session.game_id
        session_id = lease.session.session_id

        def run() -> bytes | None:
            try:
                return self._service.capture_webp(lease)
            except (OSError, RuntimeError, ValueError):
                return None

        future = self._worker.submit(run)
        self._current = future

        def notify(done: Future[bytes | None]) -> None:
            if self._closed:
                return
            data = None
            if not done.cancelled():
                try:
                    data = done.result()
                except (OSError, RuntimeError, ValueError):
                    data = None
            if not self._closed:
                self._pin_ready.emit(on_done, game_id, session_id, data)

        future.add_done_callback(notify)
        return "started"

    @Slot(object, str, str, object)
    def _deliver_pin(
        self,
        on_done: Callable[[str, str, bytes | None], None],
        game_id: str,
        session_id: str,
        data: bytes | None,
    ) -> None:
        if not self._closed:
            on_done(game_id, session_id, data)

    def close(self) -> None:
        self._closed = True
        self._timer.stop()
        self._worker.shutdown(wait=False, cancel_futures=True)
