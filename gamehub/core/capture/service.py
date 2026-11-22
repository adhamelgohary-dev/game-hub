"""Gate screenshot capture on foreground identity and active session state."""

import logging
from io import BytesIO
from time import monotonic, perf_counter_ns, time_ns

from PIL import Image

from gamehub.core.capture.models import CaptureFrame, CaptureLease
from gamehub.core.capture.windows import WgcCapture, WindowProbe
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.storage.screenshots import ScreenshotRepository

LOGGER = logging.getLogger(__name__)
DEFAULT_INTERVAL_SEC = 30
DEFAULT_BUFFER_SIZE = 10
LEASE_SECONDS = 2.0
MAX_FRAME_PIXELS = 33_177_600


class CaptureService:
    def __init__(
        self,
        windows: WindowProbe,
        tracker: SessionTracker,
        capture: WgcCapture,
        screenshots: ScreenshotRepository,
        *,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        self._windows = windows
        self._tracker = tracker
        self._capture = capture
        self._screenshots = screenshots
        self._buffer_size = buffer_size

    def set_buffer_size(self, buffer_size: int) -> None:
        self._buffer_size = buffer_size

    def acquire(self) -> CaptureLease | None:
        window = self._windows.foreground()
        if window is None:
            return None
        session = self._tracker.active_for(window.process)
        if session is None:
            return None
        return CaptureLease(window, session, monotonic() + LEASE_SECONDS, perf_counter_ns() // 100)

    def is_current(self, lease: CaptureLease) -> bool:
        return (
            monotonic() < lease.expires_at
            and self._windows.foreground() == lease.window
            and self._tracker.active_for(lease.window.process) == lease.session
        )

    def capture_webp(self, lease: CaptureLease) -> bytes | None:
        """Capture and encode one verified foreground frame without saving it to the ring."""
        if not self.is_current(lease):
            return None
        try:
            frame = self._capture.capture_once(lease, self.is_current)
            if frame is None:
                return None
            data = _encode(frame)
            if data is None:
                LOGGER.warning("capture_empty_or_invalid_frame")
                return None
            if not self.is_current(lease):
                return None
            return data
        except (OSError, RuntimeError, ValueError):
            LOGGER.warning("capture_request_unavailable")
            return None

    def sample(self, lease: CaptureLease) -> bool:
        data = self.capture_webp(lease)
        if data is None:
            return False
        captured_at = time_ns() // 1_000_000
        try:
            if not self.is_current(lease):
                return False
            return self._screenshots.append(
                lease.session.game_id, lease.session.session_id, data, captured_at, self._buffer_size
            )
        except (OSError, RuntimeError, ValueError):
            LOGGER.warning("capture_request_unavailable")
            return False


def _encode(frame: CaptureFrame) -> bytes | None:
    width, height = frame.width, frame.height
    if width <= 0 or height <= 0 or width * height > MAX_FRAME_PIXELS:
        return None
    if len(frame.pixels) != width * height * 4:
        return None
    with (
        Image.frombytes("RGBA", (width, height), frame.pixels, "raw", "BGRA") as source,
        source.convert("RGB") as image,
        BytesIO() as output,
    ):
        if max(high for _, high in image.getextrema()) <= 8:
            return None
        image.thumbnail((1600, 1000))
        image.save(output, "WEBP", quality=82, method=3)
        return output.getvalue()
