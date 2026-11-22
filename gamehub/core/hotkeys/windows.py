"""Register game shortcuts without installing a keyboard hook."""

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

LOGGER = logging.getLogger(__name__)
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
RECORD_NOTE_ID = 0x6600
LAST_TIME_ID = 0x6601


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self, app: QCoreApplication) -> None:
        super().__init__()
        user = ctypes.WinDLL("user32", use_last_error=True)
        self._register = user.RegisterHotKey
        self._register.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._register.restype = wintypes.BOOL
        self._unregister = user.UnregisterHotKey
        self._unregister.argtypes = [wintypes.HWND, ctypes.c_int]
        self._unregister.restype = wintypes.BOOL
        self._app = app
        self._handlers: dict[int, Callable[[], None]] = {}
        self._app.installNativeEventFilter(self)

    def bind(self, identifier: int, modifiers: int, key: int, handler: Callable[[], None]) -> bool:
        if identifier in self._handlers:
            return False
        if not self._register(None, identifier, modifiers | MOD_NOREPEAT, key):
            LOGGER.warning("hotkey_registration_failed code=%s", ctypes.get_last_error())
            return False
        self._handlers[identifier] = handler
        return True

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) not in {b"windows_generic_MSG", b"windows_dispatcher_MSG"}:
            return False, 0
        native = wintypes.MSG.from_address(int(message))
        if native.message != WM_HOTKEY:
            return False, 0
        handler = self._handlers.get(native.wParam)
        if handler is None:
            return False, 0
        handler()
        return True, 0

    def close(self) -> None:
        self._app.removeNativeEventFilter(self)
        for identifier in self._handlers:
            if not self._unregister(None, identifier):
                LOGGER.warning("hotkey_release_failed code=%s", ctypes.get_last_error())
        self._handlers.clear()
