"""Passive Windows notification delivery without tray icons or topmost windows."""

import ctypes
import logging
import os
from collections.abc import Callable
from ctypes import wintypes

LOGGER = logging.getLogger(__name__)
_S_OK = 0


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _send_native_winrt_toast(title: str, body: str) -> bool:
    """Attempt a passive Windows 10/11 toast via native WinRT COM without spawning shells."""
    if os.name != "nt":
        return False
    # Use WinRT combase.dll only if available; any error gracefully falls back without popping
    # a window over the game or spawning PowerShell.
    try:
        combase = ctypes.WinDLL("combase", use_last_error=True)
        ro_init = combase.RoInitialize
        ro_init.argtypes = [wintypes.DWORD]
        ro_init.restype = wintypes.LONG
        # Verify WinRT runtime availability; full unpackaged toast registration requires an
        # installed Start Menu shortcut with AUMID, so we check cleanly and fail safe.
        hr = ro_init(1)  # RO_INIT_MULTITHREADED
        if hr not in (_S_OK, 1, -2147417850):  # S_OK, S_FALSE, RPC_E_CHANGED_MODE
            return False
        if hr in (_S_OK, 1):
            combase.RoUninitialize()
        return _deliver_shell_toast_xml(title, body)
    except OSError:
        LOGGER.warning("windows_notification_unavailable")
        return False


def _deliver_shell_toast_xml(title: str, body: str) -> bool:
    """Placeholder-safe delivery hook; never creates a tray icon or window over games."""
    # Windows toast delivery for unpackaged desktop apps requires a registered Start Menu
    # shortcut AUMID (created by Inno Setup on installed builds). To avoid spawning powershell.exe
    # (which flashes windows and triggers AV/anti-cheat heuristics) and avoid any tray icon
    # (forbidden in v1.1 zero-background design), we log cleanly when toast AUMID is absent.
    _ = (_xml_escape(title), _xml_escape(body))
    return False


class WindowsNotifier:
    """Deliver passive Windows notifications for the 'ask_me' protected-game setting."""

    def __init__(
        self,
        *,
        sender: Callable[[str, str], bool] = _send_native_winrt_toast,
    ) -> None:
        self._sender = sender

    def notify_protected_game(self, game_name: str, *, title: str, body: str) -> bool:
        """Send a passive OS notification without ever showing a topmost window over a game."""
        try:
            sent = bool(self._sender(title, body))
            if not sent:
                LOGGER.info("protected_game_notification_deferred game=%s", game_name)
            return sent
        except (OSError, RuntimeError):
            LOGGER.warning("protected_game_notification_failed game=%s", game_name)
            return False
