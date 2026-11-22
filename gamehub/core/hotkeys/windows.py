"""Register game shortcuts without installing a keyboard hook."""

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

LOGGER = logging.getLogger(__name__)
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
RECORD_NOTE_ID = 0x6600
LAST_TIME_ID = 0x6601
PIN_CONTROLS_ID = 0x6602
_PROBE_ID = 0x66FF

_MODIFIER_MAP = {
    "ctrl": ("Ctrl", MOD_CONTROL),
    "control": ("Ctrl", MOD_CONTROL),
    "alt": ("Alt", MOD_ALT),
    "shift": ("Shift", MOD_SHIFT),
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift")
_FUNCTION_KEYS = {f"F{num}": 0x6F + num for num in range(1, 13)}


def parse_shortcut(text: str) -> tuple[int, int] | None:
    """Parse a supported shortcut string into Windows (modifiers, virtual_key)."""
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    parts = [part.strip() for part in cleaned.split("+")]
    if len(parts) < 2 or any(not part for part in parts):
        return None

    modifiers = 0
    seen_mods: set[str] = set()
    for part in parts[:-1]:
        entry = _MODIFIER_MAP.get(part.casefold())
        if entry is None or entry[0] in seen_mods:
            return None
        seen_mods.add(entry[0])
        modifiers |= entry[1]

    raw_key = parts[-1].upper()
    if len(raw_key) == 1 and raw_key.isascii() and raw_key.isalnum():
        if modifiers == MOD_SHIFT:
            return None
        return modifiers, ord(raw_key)
    if raw_key in _FUNCTION_KEYS:
        return modifiers, _FUNCTION_KEYS[raw_key]
    return None


def canonical_shortcut(text: str) -> str | None:
    """Return canonical 'Ctrl+Alt+Key' form, '' for disabled, or None if invalid."""
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return ""
    parsed = parse_shortcut(cleaned)
    if parsed is None:
        return None
    modifiers, key = parsed
    mod_names = []
    if modifiers & MOD_CONTROL:
        mod_names.append("Ctrl")
    if modifiers & MOD_ALT:
        mod_names.append("Alt")
    if modifiers & MOD_SHIFT:
        mod_names.append("Shift")
    if 0x70 <= key <= 0x7B:
        key_name = f"F{key - 0x6F}"
    else:
        key_name = chr(key)
    return "+".join((*mod_names, key_name))


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
        self._bindings: dict[int, tuple[int, int]] = {}
        self._suspended_bindings: dict[int, tuple[int, int, Callable[[], None]]] = {}
        self._suspended = False
        self._app.installNativeEventFilter(self)

    @property
    def is_suspended(self) -> bool:
        return self._suspended

    def suspend(self) -> None:
        """Unregister all Win32 hotkeys during Strict mode without losing configuration."""
        if self._suspended:
            return
        self._suspended = True
        self._suspended_bindings = {
            identifier: (self._bindings[identifier][0], self._bindings[identifier][1], handler)
            for identifier, handler in self._handlers.items()
            if identifier in self._bindings
        }
        for identifier in tuple(self._handlers):
            if not self._unregister(None, identifier):
                LOGGER.warning("hotkey_release_failed code=%s", ctypes.get_last_error())
        self._handlers.clear()
        self._bindings.clear()

    def resume(self) -> None:
        """Re-register saved hotkeys after leaving Strict mode."""
        if not self._suspended:
            return
        self._suspended = False
        saved = dict(self._suspended_bindings)
        self._suspended_bindings.clear()
        for identifier, (modifiers, key, handler) in saved.items():
            self.bind(identifier, modifiers, key, handler)

    def bind(self, identifier: int, modifiers: int, key: int, handler: Callable[[], None]) -> bool:
        if identifier in self._handlers:
            return False
        if not self._register(None, identifier, modifiers | MOD_NOREPEAT, key):
            LOGGER.warning("hotkey_registration_failed code=%s", ctypes.get_last_error())
            return False
        self._handlers[identifier] = handler
        self._bindings[identifier] = (modifiers, key)
        return True

    def bind_shortcut(self, identifier: int, shortcut: str, handler: Callable[[], None]) -> bool:
        if not shortcut:
            return True
        parsed = parse_shortcut(shortcut)
        if parsed is None:
            return False
        return self.bind(identifier, parsed[0], parsed[1], handler)

    def unbind(self, identifier: int) -> None:
        if identifier not in self._handlers:
            return
        if not self._unregister(None, identifier):
            LOGGER.warning("hotkey_release_failed code=%s", ctypes.get_last_error())
        self._handlers.pop(identifier, None)
        self._bindings.pop(identifier, None)

    def rebind(self, identifier: int, shortcut: str, handler: Callable[[], None]) -> bool:
        """Atomically replace a shortcut while keeping the working binding on conflict."""
        if not shortcut:
            self.unbind(identifier)
            return True
        parsed = parse_shortcut(shortcut)
        if parsed is None:
            return False
        modifiers, key = parsed
        current = self._bindings.get(identifier)
        if current == (modifiers, key):
            self._handlers[identifier] = handler
            return True

        # Probe the replacement before releasing the existing working binding.
        if not self._register(None, _PROBE_ID, modifiers | MOD_NOREPEAT, key):
            LOGGER.warning("hotkey_rebind_conflict code=%s", ctypes.get_last_error())
            return False
        self._unregister(None, _PROBE_ID)

        previous_handler = self._handlers.get(identifier)
        if current is not None:
            self.unbind(identifier)
        if self.bind(identifier, modifiers, key, handler):
            return True
        if current is not None and previous_handler is not None:
            self.bind(identifier, current[0], current[1], previous_handler)
        return False

    def rebind_batch(
        self, changes: dict[int, tuple[str, Callable[[], None]]]
    ) -> tuple[bool, int | None]:
        """Atomically apply multiple hotkey updates, supporting swaps between actions."""
        parsed_targets: dict[int, tuple[tuple[int, int] | None, Callable[[], None]]] = {}
        for identifier, (shortcut, handler) in changes.items():
            if not shortcut:
                parsed_targets[identifier] = (None, handler)
            else:
                parsed = parse_shortcut(shortcut)
                if parsed is None:
                    return False, identifier
                parsed_targets[identifier] = (parsed, handler)

        if self._suspended:
            for identifier, (target, handler) in parsed_targets.items():
                if target is None:
                    self._suspended_bindings.pop(identifier, None)
                else:
                    self._suspended_bindings[identifier] = (target[0], target[1], handler)
            return True, None

        owned_by_batch = {
            self._bindings[identifier]
            for identifier in changes
            if identifier in self._bindings
        }
        # Phase 1: probe every newly introduced chord before touching existing bindings.
        for identifier, (target, _handler) in parsed_targets.items():
            if target is None or target in owned_by_batch:
                continue
            if not self._register(None, _PROBE_ID, target[0] | MOD_NOREPEAT, target[1]):
                LOGGER.warning("hotkey_rebind_conflict code=%s", ctypes.get_last_error())
                return False, identifier
            self._unregister(None, _PROBE_ID)

        # Phase 2: snapshot previous bindings, unbind changing IDs, bind replacements.
        previous = {
            identifier: (self._bindings.get(identifier), self._handlers.get(identifier))
            for identifier in changes
        }
        for identifier in changes:
            self.unbind(identifier)

        applied: list[int] = []
        for identifier, (target, handler) in parsed_targets.items():
            if target is None:
                applied.append(identifier)
                continue
            if not self.bind(identifier, target[0], target[1], handler):
                for done_id in applied:
                    self.unbind(done_id)
                for prev_id, (prev_chord, prev_handler) in previous.items():
                    if prev_chord is not None and prev_handler is not None:
                        self.bind(prev_id, prev_chord[0], prev_chord[1], prev_handler)
                return False, identifier
            applied.append(identifier)
        return True, None

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
        for identifier in tuple(self._handlers):
            if not self._unregister(None, identifier):
                LOGGER.warning("hotkey_release_failed code=%s", ctypes.get_last_error())
        self._handlers.clear()
        self._bindings.clear()
        self._suspended_bindings.clear()
        self._suspended = False
