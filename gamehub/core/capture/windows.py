"""Bind Windows Graphics Capture to one verified foreground game window."""

import ctypes
import logging
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic

import psutil

from gamehub.core.sessions.models import ProcessIdentity

from .models import CaptureFrame, CaptureLease, WindowIdentity

LOGGER = logging.getLogger(__name__)
_WINDOW_CAPTURE_BUILD = 18362
_CURSOR_OPTION_BUILD = 19041
_SECONDARY_WINDOWS_OPTION_BUILD = 26100
_DWMWA_CLOAKED = 14
_GA_ROOT = 2
_MAX_FRAME_PIXELS = 16 * 1024 * 1024


class WindowProbe:
    def __init__(self) -> None:
        user = ctypes.WinDLL("user32", use_last_error=True)
        self._foreground = user.GetForegroundWindow
        self._desktop = user.GetDesktopWindow
        self._shell = user.GetShellWindow
        for get_window in (self._foreground, self._desktop, self._shell):
            get_window.argtypes = []
            get_window.restype = wintypes.HWND
        self._visible = user.IsWindowVisible
        self._minimized = user.IsIconic
        for check_window in (self._visible, self._minimized):
            check_window.argtypes = [wintypes.HWND]
            check_window.restype = wintypes.BOOL
        self._root = user.GetAncestor
        self._root.argtypes = [wintypes.HWND, wintypes.UINT]
        self._root.restype = wintypes.HWND
        self._window_process = user.GetWindowThreadProcessId
        self._window_process.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._window_process.restype = wintypes.DWORD

        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self._dwm_attribute = dwm.DwmGetWindowAttribute
        self._dwm_attribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        ]
        self._dwm_attribute.restype = wintypes.LONG

    def foreground(self) -> WindowIdentity | None:
        hwnd = self._foreground()
        if not hwnd:
            return None
        pid = self._eligible_owner(hwnd)
        if not pid:
            return None
        try:
            created_at = psutil.Process(pid).create_time()
        except (psutil.Error, OSError):
            return None
        if self._eligible_owner(hwnd) != pid:
            return None
        return WindowIdentity(hwnd, ProcessIdentity(pid, created_at))

    def _eligible_owner(self, hwnd: int) -> int:
        if (
            hwnd != self._foreground()
            or hwnd == self._desktop()
            or self._root(hwnd, _GA_ROOT) != hwnd
            or not self._visible(hwnd)
            or self._minimized(hwnd)
        ):
            return 0

        cloaked = wintypes.DWORD()
        if self._dwm_attribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) != 0:
            return 0
        if cloaked.value:
            return 0

        pid = self._owner(hwnd)
        shell = self._shell()
        if shell and pid == self._owner(shell):
            return 0
        return pid

    def _owner(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        if self._window_process(hwnd, ctypes.byref(pid)):
            return pid.value
        return 0


def _native_capture(**options):
    from windows_capture import WindowsCapture

    return WindowsCapture(**options)


@dataclass(slots=True)
class _PendingCapture:
    done: Event = field(default_factory=Event)
    expired: Event = field(default_factory=Event)
    frame: CaptureFrame | None = None


class WgcCapture:
    """At most one native capture may run, even if a driver delays shutdown."""

    def __init__(
        self,
        factory: Callable = _native_capture,
        build: int | None = None,
    ) -> None:
        self._factory = factory
        self._build = sys.getwindowsversion().build if build is None and sys.platform == "win32" else build or 0
        self._lock = Lock()
        self._busy = False

    def capture_once(
        self, lease: CaptureLease, is_current: Callable[[CaptureLease], bool]
    ) -> CaptureFrame | None:
        if self._build < _WINDOW_CAPTURE_BUILD or not lease.window.hwnd or not is_current(lease):
            return None
        if lease.expires_at <= monotonic():
            return None
        pending = _PendingCapture()
        with self._lock:
            if self._busy:
                return None
            self._busy = True
            worker = Thread(
                target=self._capture,
                args=(pending, lease, is_current),
                name="gamehub-window-capture",
                daemon=True,
            )
            try:
                worker.start()
            except (OSError, RuntimeError):
                self._busy = False
                LOGGER.warning("capture_worker_unavailable")
                return None

        if not pending.done.wait(max(0.0, lease.expires_at - monotonic())):
            pending.expired.set()
            return None
        if not self._can_capture(pending, lease, is_current):
            return None
        return pending.frame

    def _capture(
        self,
        pending: _PendingCapture,
        lease: CaptureLease,
        is_current: Callable[[CaptureLease], bool],
    ) -> None:
        settled = Event()
        control = None
        try:
            if not self._can_capture(pending, lease, is_current):
                return
            capture = self._factory(
                window_hwnd=lease.window.hwnd,
                cursor_capture=False if self._build >= _CURSOR_OPTION_BUILD else None,
                secondary_window=False if self._build >= _SECONDARY_WINDOWS_OPTION_BUILD else None,
            )

            @capture.event
            def on_frame_arrived(frame, internal_control):
                if settled.is_set():
                    internal_control.stop()
                    return
                if not self._can_capture(pending, lease, is_current):
                    internal_control.stop()
                    settled.set()
                    return
                if frame.timespan < lease.not_before_qpc:
                    return
                pending.frame = _copy_frame(frame)
                internal_control.stop()
                settled.set()

            @capture.event
            def on_closed():
                pending.expired.set()
                settled.set()

            if not self._can_capture(pending, lease, is_current):
                return
            control = capture.start_free_threaded()
            while self._can_capture(pending, lease, is_current):
                remaining = lease.expires_at - monotonic()
                if settled.wait(min(0.025, max(0.0, remaining))) or control.is_finished():
                    break
        except Exception:  # noqa: BLE001 - the native wheel raises generic Python exceptions.
            pending.frame = None
            LOGGER.warning("capture_window_unavailable")
        finally:
            try:
                if control is not None:
                    if control.is_finished():
                        control.wait()
                    else:
                        control.stop()
            except Exception:  # noqa: BLE001 - native stop joins and reports worker errors here.
                pending.frame = None
                LOGGER.warning("capture_window_cleanup_failed")
            finally:
                with self._lock:
                    self._busy = False
                    pending.done.set()

    @staticmethod
    def _can_capture(
        pending: _PendingCapture,
        lease: CaptureLease,
        is_current: Callable[[CaptureLease], bool],
    ) -> bool:
        if pending.expired.is_set():
            return False
        if monotonic() >= lease.expires_at or not is_current(lease):
            pending.expired.set()
            return False
        return True


def _copy_frame(frame) -> CaptureFrame | None:
    width, height = frame.width, frame.height
    if width <= 0 or height <= 0 or width * height > _MAX_FRAME_PIXELS:
        return None
    buffer = frame.frame_buffer
    if buffer.shape != (height, width, 4) or str(buffer.dtype) != "uint8":
        return None
    pixels = buffer.tobytes(order="C")
    if len(pixels) != width * height * 4:
        return None
    return CaptureFrame(pixels, width, height)
