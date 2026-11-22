import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import get_ident

import pytest
from PySide6.QtWidgets import QApplication

from gamehub.core.events import EventBus


@dataclass(frozen=True, slots=True)
class PlaytimeChanged:
    seconds: int


class OtherEvent:
    pass


@pytest.fixture(scope="module")
def app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Game Hub test"])


def test_workers_and_ui_publish_in_order_on_qt_thread(app: QApplication) -> None:
    bus = EventBus()
    delivered = []
    ui_thread = get_ident()
    bus.subscribe(PlaytimeChanged, lambda event: delivered.append((event.seconds, get_ident())))

    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(bus.publish, PlaytimeChanged(10)).result(timeout=2)
    bus.publish(OtherEvent())
    bus.publish(PlaytimeChanged(20))

    assert delivered == []
    app.processEvents()
    assert delivered == [(10, ui_thread), (20, ui_thread)]


def test_closed_listener_and_late_listener_skip_pending_events(app: QApplication) -> None:
    bus = EventBus()
    delivered = []
    closed = bus.subscribe(PlaytimeChanged, lambda event: delivered.append(("closed", event.seconds)))

    bus.publish(PlaytimeChanged(10))
    closed.close()
    closed.close()
    bus.subscribe(PlaytimeChanged, lambda event: delivered.append(("active", event.seconds)))
    bus.publish(PlaytimeChanged(20))
    app.processEvents()

    assert delivered == [("active", 20)]


def test_listener_failure_keeps_payload_private_and_continues(
    app: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    bus = EventBus()
    delivered = []

    def fail(event: PlaytimeChanged) -> None:
        raise ValueError("private session details")

    bus.subscribe(PlaytimeChanged, fail)
    bus.subscribe(PlaytimeChanged, lambda event: delivered.append(event.seconds))
    bus.publish(PlaytimeChanged(30))
    app.processEvents()

    assert delivered == [30]
    assert "event_handler_failed event=PlaytimeChanged" in caplog.text
    assert "private session details" not in caplog.text
