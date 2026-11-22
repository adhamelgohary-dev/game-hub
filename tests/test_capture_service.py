from io import BytesIO
from unittest.mock import Mock

from PIL import Image

from gamehub.core.capture.models import CaptureFrame, WindowIdentity
from gamehub.core.capture.service import CaptureService
from gamehub.core.sessions.models import ProcessIdentity, SessionIdentity


def _setup():
    windows = Mock()
    window = WindowIdentity(101, ProcessIdentity(10, 1.0))
    windows.foreground.return_value = window
    tracker = Mock()
    tracker.active_for.return_value = SessionIdentity("game", "session")
    adapter = Mock()
    screenshots = Mock()
    screenshots.append.return_value = True
    return CaptureService(windows, tracker, adapter, screenshots), windows, tracker, adapter, screenshots


def test_foreground_target_and_session_must_remain_exact() -> None:
    service, windows, tracker, adapter, screenshots = _setup()
    tracker.active_for.return_value = None
    assert service.acquire() is None
    tracker.active_for.return_value = SessionIdentity("game", "session")
    lease = service.acquire()
    assert lease is not None
    windows.foreground.return_value = WindowIdentity(101, ProcessIdentity(10, 2.0))
    assert not service.sample(lease)
    adapter.capture_once.assert_not_called()
    screenshots.append.assert_not_called()


def test_capture_discards_black_frame_and_saves_valid_bgra_as_webp() -> None:
    service, _, _, adapter, screenshots = _setup()
    lease = service.acquire()
    assert lease is not None
    adapter.capture_once.return_value = CaptureFrame(bytes((0, 0, 0, 255)) * 16, 4, 4)
    assert not service.sample(lease)
    screenshots.append.assert_not_called()

    adapter.capture_once.return_value = CaptureFrame(bytes((13, 37, 244, 255)) * 16, 4, 4)
    assert service.sample(lease)
    game_id, session_id, data, captured_at, buffer_size = screenshots.append.call_args.args
    assert (game_id, session_id, buffer_size) == ("game", "session", 10)
    assert captured_at > 0
    with Image.open(BytesIO(data)) as image:
        assert image.format == "WEBP"
        assert image.size == (4, 4)
        red, green, blue = image.getpixel((0, 0))
        assert red > green > blue


def test_focus_loss_during_frame_delivery_drops_capture() -> None:
    service, windows, _, adapter, screenshots = _setup()
    lease = service.acquire()
    assert lease is not None

    def deliver(*_):
        windows.foreground.return_value = None
        return CaptureFrame(bytes((13, 37, 244, 255)) * 16, 4, 4)

    adapter.capture_once.side_effect = deliver
    assert not service.sample(lease)
    screenshots.append.assert_not_called()
