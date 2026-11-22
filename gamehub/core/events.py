"""Deliver typed, in-process notifications on the Qt application thread."""

import logging
from collections.abc import Callable
from threading import Lock
from typing import TypeVar, cast

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal, Slot

LOGGER = logging.getLogger(__name__)

E = TypeVar("E")


class Subscription:
    """A handle for removing exactly one event listener."""

    def __init__(self, remove: Callable[[], None]) -> None:
        self._remove = remove

    def close(self) -> None:
        """Remove the listener. Repeated calls are safe."""
        self._remove()


class EventBus(QObject):
    _published = Signal(object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise RuntimeError("Create EventBus on the Qt application thread.")
        super().__init__(parent)
        self._lock = Lock()
        self._handlers: dict[type[object], dict[object, Callable[[object], None]]] = {}
        self._published.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Subscription:
        """Listen for this exact event type until the returned handle closes."""
        token = object()
        with self._lock:
            self._handlers.setdefault(event_type, {})[token] = cast(Callable[[object], None], handler)
        return Subscription(lambda: self._remove(event_type, token))

    def publish(self, event: object) -> None:
        """Queue delivery in publication order, including calls from worker threads."""
        with self._lock:
            tokens = tuple(self._handlers.get(type(event), {}))
            if tokens:
                # A single lock orders updates and signal posts from different threads.
                self._published.emit(event, tokens)

    def _remove(self, event_type: type[object], token: object) -> None:
        with self._lock:
            handlers = self._handlers.get(event_type)
            if handlers is not None:
                handlers.pop(token, None)
                if not handlers:
                    del self._handlers[event_type]

    @Slot(object, object)
    def _dispatch(self, event: object, tokens: tuple[object, ...]) -> None:
        for token in tokens:
            with self._lock:
                handler = self._handlers.get(type(event), {}).get(token)
            if handler is not None:
                try:
                    handler(event)
                except Exception:  # noqa: BLE001
                    LOGGER.warning("event_handler_failed event=%s", type(event).__name__)
