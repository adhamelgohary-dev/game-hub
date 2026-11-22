import ctypes
from ctypes import wintypes
from unittest.mock import Mock

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication

from gamehub.core.hotkeys.windows import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    RECORD_NOTE_ID,
    WM_HOTKEY,
    GlobalHotkeys,
)


def test_windows_filter_dispatches_only_bound_hotkey(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["hotkey test"])
    hotkeys = GlobalHotkeys(app)
    hotkeys._register = Mock(return_value=1)
    hotkeys._unregister = Mock(return_value=1)
    handler = Mock()
    try:
        assert hotkeys.bind(RECORD_NOTE_ID, MOD_ALT | MOD_CONTROL, ord("N"), handler)
        assert not hotkeys.bind(RECORD_NOTE_ID, MOD_ALT | MOD_CONTROL, ord("N"), handler)
        hotkeys._register.assert_called_once_with(None, RECORD_NOTE_ID, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, ord("N"))
        message = wintypes.MSG()
        message.message = WM_HOTKEY
        message.wParam = RECORD_NOTE_ID + 1
        dispatcher = QByteArray(b"windows_dispatcher_MSG")
        assert hotkeys.nativeEventFilter(dispatcher, ctypes.addressof(message)) == (False, 0)
        handler.assert_not_called()
        message.wParam = RECORD_NOTE_ID
        assert hotkeys.nativeEventFilter(dispatcher, ctypes.addressof(message)) == (True, 0)
        handler.assert_called_once_with()
    finally:
        hotkeys.close()
    hotkeys._unregister.assert_called_once_with(None, RECORD_NOTE_ID)
