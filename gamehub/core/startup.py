"""Remove legacy v1.0 per-user Windows startup entries without creating new ones."""

import logging
import os
from collections.abc import Callable

if os.name == "nt":
    import winreg

LOGGER = logging.getLogger(__name__)
_RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "GameHub"


def _delete_windows_run() -> None:
    if os.name != "nt":
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_SUBKEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        return


def remove_legacy_startup_entry(
    *, deleter: Callable[[], None] = _delete_windows_run
) -> bool:
    """Delete any legacy v1.0 HKCU Run\\GameHub value if present. Never creates keys."""
    try:
        deleter()
        return True
    except OSError:
        LOGGER.warning("legacy_startup_cleanup_failed")
        return False
