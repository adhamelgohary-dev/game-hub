"""Manage per-user Windows startup registration without elevation."""

import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

if os.name == "nt":
    import winreg

LOGGER = logging.getLogger(__name__)
_RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "GameHub"


def default_startup_command() -> str:
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    return f'"{executable}" -m gamehub.app'


def _set_windows_run(command: str | None) -> None:
    if os.name != "nt":
        raise OSError("Windows startup registration requires Windows.")
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _RUN_SUBKEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if command is None:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, command)


def _read_windows_run() -> str | None:
    if os.name != "nt":
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_SUBKEY, 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return value if isinstance(value, str) else None
    except FileNotFoundError:
        return None


class StartupRegistration:
    """Coordinate the per-user HKCU Run entry for Game Hub."""

    def __init__(
        self,
        *,
        command: str | None = None,
        writer: Callable[[str | None], None] = _set_windows_run,
        reader: Callable[[], str | None] = _read_windows_run,
    ) -> None:
        self._command = command if command is not None else default_startup_command()
        self._writer = writer
        self._reader = reader

    def is_enabled(self) -> bool:
        try:
            return bool(self._reader())
        except OSError:
            return False

    def apply(self, enabled: bool) -> tuple[bool, str | None]:
        try:
            self._writer(self._command if enabled else None)
            return True, None
        except OSError:
            LOGGER.warning("startup_registration_failed")
            return False, "startup_unavailable"
