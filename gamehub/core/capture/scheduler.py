"""Schedule bounded capture work without blocking the Qt thread."""

from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer

from gamehub.core.capture.service import DEFAULT_INTERVAL_SEC, CaptureService


class CaptureScheduler(QObject):
    def __init__(
        self,
        service: CaptureService,
        parent: QObject,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game-capture")
        self._current: Future[bool] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(round(interval_sec * 1000))
        self._timer.timeout.connect(self.sample_foreground)

    def start(self) -> None:
        self._timer.start()

    def sample_foreground(self) -> None:
        if self._current is not None and not self._current.done():
            return
        lease = self._service.acquire()
        if lease is not None:
            self._current = self._worker.submit(self._service.sample, lease)

    def close(self) -> None:
        self._timer.stop()
        self._worker.shutdown(cancel_futures=True)
