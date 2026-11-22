"""Capture values shared by the foreground policy and Windows adapter."""

from dataclasses import dataclass

from gamehub.core.sessions.models import ProcessIdentity, SessionIdentity


@dataclass(frozen=True, slots=True)
class WindowIdentity:
    hwnd: int
    process: ProcessIdentity


@dataclass(frozen=True, slots=True)
class CaptureLease:
    window: WindowIdentity
    session: SessionIdentity
    expires_at: float
    not_before_qpc: int


@dataclass(frozen=True, slots=True)
class CaptureFrame:
    pixels: bytes
    width: int
    height: int
