import ctypes
from ctypes import wintypes
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gamehub.core.capture.models import CaptureFrame, CaptureLease, WindowIdentity
from gamehub.core.capture.windows import WgcCapture, WindowProbe
from gamehub.core.sessions.models import ProcessIdentity, SessionIdentity


def _lease(duration: float = 1.0) -> CaptureLease:
    return CaptureLease(
        WindowIdentity(100, ProcessIdentity(200, 300.0)),
        SessionIdentity("game", "session"),
        monotonic() + duration,
        1000,
    )


class FakeBuffer:
    shape = (1, 2, 4)
    dtype = "uint8"

    def __init__(self) -> None:
        self.pixels = bytearray(b"\x11\x22\x33\xff\x44\x55\x66\xff")

    def tobytes(self, *, order: str) -> bytes:
        assert order == "C"
        return bytes(self.pixels)


def _frame(timestamp: int = 1000, width: int = 2, height: int = 1):
    return SimpleNamespace(timespan=timestamp, width=width, height=height, frame_buffer=FakeBuffer())


class FakeNative:
    def __init__(self, *frames) -> None:
        self.frames = frames
        self.callbacks = {}
        self.control = Mock()
        self.control.is_finished.return_value = True
        self.internal = Mock()

    def event(self, callback):
        self.callbacks[callback.__name__] = callback
        return callback

    def start_free_threaded(self):
        for frame in self.frames:
            self.callbacks["on_frame_arrived"](frame, self.internal)
            if self.internal.stop.called:
                break
        return self.control


@pytest.mark.parametrize("build,cursor,secondary", [
    (18362, None, None),
    (19041, False, None),
    (26100, False, False),
])
def test_exact_hwnd_options_keep_older_builds_supported(build, cursor, secondary) -> None:
    fresh = _frame()
    native = FakeNative(_frame(timestamp=999), fresh, _frame(timestamp=1002))
    factory = Mock(return_value=native)

    captured = WgcCapture(factory=factory, build=build).capture_once(_lease(), lambda _lease: True)
    fresh.frame_buffer.pixels[:] = b"\0" * 8

    assert captured == CaptureFrame(b"\x11\x22\x33\xff\x44\x55\x66\xff", 2, 1)
    factory.assert_called_once_with(window_hwnd=100, cursor_capture=cursor, secondary_window=secondary)
    native.internal.stop.assert_called_once()
    native.control.wait.assert_called_once()


def test_unsupported_windows_and_stale_initial_lease_do_not_start_capture() -> None:
    factory = Mock()

    assert WgcCapture(factory=factory, build=17763).capture_once(_lease(), lambda _lease: True) is None
    assert WgcCapture(factory=factory, build=19041).capture_once(_lease(), lambda _lease: False) is None
    factory.assert_not_called()


@pytest.mark.parametrize("frame", [_frame(timestamp=999), _frame(width=16384, height=16384)])
def test_old_or_oversized_frame_is_discarded(frame) -> None:
    native = FakeNative(frame)

    captured = WgcCapture(factory=lambda **_kwargs: native, build=19041).capture_once(
        _lease(), lambda _lease: True,
    )

    assert captured is None


def test_observed_focus_loss_discards_frame_even_if_focus_returns() -> None:
    native = FakeNative(_frame())
    checks = iter((True, True, True, False, True, True))

    captured = WgcCapture(factory=lambda **_kwargs: native, build=19041).capture_once(
        _lease(), lambda _lease: next(checks),
    )

    assert captured is None
    native.internal.stop.assert_called_once()


def test_native_stop_hang_cannot_block_caller_or_start_another_capture() -> None:
    native = FakeNative(_frame())
    native.control.is_finished.return_value = False
    stop_started = Event()
    stop_released = Event()

    def stuck_stop():
        stop_started.set()
        stop_released.wait(2)

    native.control.stop.side_effect = stuck_stop
    factory = Mock(return_value=native)
    adapter = WgcCapture(factory=factory, build=19041)
    try:
        assert adapter.capture_once(_lease(duration=0.2), lambda _lease: True) is None
        assert stop_started.wait(0.5)
        assert not stop_released.is_set()
        assert adapter.capture_once(_lease(), lambda _lease: True) is None
        factory.assert_called_once()
    finally:
        stop_released.set()


def _window_probe(monkeypatch, *, cloaked=0, minimized=False, shell_owner=999):
    probe = WindowProbe.__new__(WindowProbe)
    probe._foreground = Mock(return_value=100)
    probe._desktop = Mock(return_value=900)
    probe._shell = Mock(return_value=901)
    probe._root = lambda hwnd, _flag: hwnd
    probe._visible = Mock(return_value=True)
    probe._minimized = Mock(return_value=minimized)

    def set_value(pointer, value):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = value

    def window_process(hwnd, output_pid):
        set_value(output_pid, shell_owner if hwnd == 901 else 200)
        return 123

    def dwm_attribute(_hwnd, _attribute, output_value, _size):
        set_value(output_value, cloaked)
        return 0

    probe._window_process = window_process
    probe._dwm_attribute = dwm_attribute
    process = Mock()
    process.create_time.return_value = 300.0
    monkeypatch.setattr("gamehub.core.capture.windows.psutil.Process", Mock(return_value=process))
    return probe


def test_foreground_rechecks_the_same_visible_uncloaked_window(monkeypatch) -> None:
    probe = _window_probe(monkeypatch)

    assert probe.foreground() == WindowIdentity(100, ProcessIdentity(200, 300.0))
    probe._foreground.side_effect = [100, 100, 101]
    assert probe.foreground() is None


@pytest.mark.parametrize("options", [{"cloaked": 2}, {"minimized": True}, {"shell_owner": 200}])
def test_foreground_rejects_cloaked_minimized_or_shell_window(monkeypatch, options) -> None:
    assert _window_probe(monkeypatch, **options).foreground() is None
