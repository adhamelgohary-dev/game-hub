import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication

from gamehub.core.hotkeys.windows import (
    LAST_TIME_ID,
    MOD_ALT,
    MOD_CONTROL,
    RECORD_NOTE_ID,
    GlobalHotkeys,
    canonical_shortcut,
    parse_shortcut,
)
from gamehub.core.settings import SettingsChanged, SettingsService
from gamehub.core.startup import StartupRegistration
from gamehub.core.storage.db import Database, StorageError


def test_shortcut_parsing_and_canonicalization() -> None:
    assert canonical_shortcut("alt+ctrl+l") == "Ctrl+Alt+L"
    assert canonical_shortcut("  shift + ctrl + f9 ") == "Ctrl+Shift+F9"
    assert canonical_shortcut("shift+f5") == "Shift+F5"
    assert canonical_shortcut("") == ""
    assert canonical_shortcut("   ") == ""
    assert canonical_shortcut("N") is None
    assert canonical_shortcut("Shift+A") is None
    assert canonical_shortcut("Shift+1") is None
    assert canonical_shortcut("Ctrl+Ctrl+N") is None
    assert canonical_shortcut("Win+L") is None
    assert canonical_shortcut("Ctrl+F13") is None
    assert parse_shortcut("Ctrl+Alt+N") == (MOD_CONTROL | MOD_ALT, ord("N"))


def test_global_hotkeys_rebind_keeps_working_binding_on_conflict() -> None:
    app = QCoreApplication.instance() or QCoreApplication(["hotkey rebind test"])
    hotkeys = GlobalHotkeys(app)
    registered: dict[int, tuple[int, int]] = {}
    conflict_key = ord("X")

    def fake_register(_hwnd, ident, mods, key):
        if key == conflict_key:
            return 0
        registered[ident] = (mods, key)
        return 1

    def fake_unregister(_hwnd, ident):
        registered.pop(ident, None)
        return 1

    hotkeys._register = fake_register
    hotkeys._unregister = fake_unregister
    try:
        handler = Mock()
        assert hotkeys.bind_shortcut(LAST_TIME_ID, "Ctrl+Alt+L", handler) is True
        assert LAST_TIME_ID in registered

        # Conflict on Ctrl+Alt+X leaves Ctrl+Alt+L registered and working!
        assert hotkeys.rebind(LAST_TIME_ID, "Ctrl+Alt+X", handler) is False
        assert registered[LAST_TIME_ID][1] == ord("L")

        # Valid rebind succeeds and replaces binding.
        assert hotkeys.rebind(LAST_TIME_ID, "Ctrl+Alt+K", handler) is True
        assert registered[LAST_TIME_ID][1] == ord("K")

        # Empty shortcut disables binding cleanly.
        assert hotkeys.rebind(LAST_TIME_ID, "", handler) is True
        assert LAST_TIME_ID not in registered

        # Batch rebind supports swapping two active shortcuts without false self-conflict!
        assert hotkeys.bind_shortcut(RECORD_NOTE_ID, "Ctrl+Alt+N", handler) is True
        assert hotkeys.bind_shortcut(LAST_TIME_ID, "Ctrl+Alt+L", handler) is True
        ok, failed = hotkeys.rebind_batch(
            {RECORD_NOTE_ID: ("Ctrl+Alt+L", handler), LAST_TIME_ID: ("Ctrl+Alt+N", handler)}
        )
        assert (ok, failed) == (True, None)
        assert registered[RECORD_NOTE_ID][1] == ord("L")
        assert registered[LAST_TIME_ID][1] == ord("N")
    finally:
        hotkeys.close()


def test_settings_persistence_validation_and_corrupt_value_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = Database(tmp_path / "gamehub.db")
    events: list[SettingsChanged] = []
    service = SettingsService(db, publish=events.append)

    initial = service.read()
    assert initial.language == "en"
    assert initial.capture_interval_sec == 30
    assert initial.capture_buffer_size == 10
    assert initial.autoplay_voice is True
    assert initial.prompt_on_end is True
    assert initial.hotkey_record_note == "Ctrl+Alt+N"

    # Reject out-of-range and duplicate shortcuts without writing anything.
    bad = service.update(
        {
            "capture.interval_sec": 2,
            "capture.buffer_size": 99,
            "hotkey.record_note": "Ctrl+Alt+K",
            "hotkey.last_time": "alt+ctrl+k",
        }
    )
    assert bad.ok is False
    assert bad.errors["capture.interval_sec"] == "invalid_capture_interval"
    assert bad.errors["capture.buffer_size"] == "invalid_buffer_size"
    assert bad.errors["hotkey.record_note"] == "duplicate_shortcut"
    assert bad.errors["hotkey.last_time"] == "duplicate_shortcut"
    assert events == []

    # Valid update persists and publishes SettingsChanged.
    good = service.update(
        {
            "ui.language": "ar",
            "capture.interval_sec": 15,
            "capture.buffer_size": 20,
            "memory.autoplay_voice": False,
            "hotkey.pin_controls": "",
        }
    )
    assert good.ok is True
    assert good.snapshot.language == "ar"
    assert good.snapshot.capture_interval_sec == 15
    assert good.snapshot.capture_buffer_size == 20
    assert good.snapshot.autoplay_voice is False
    assert good.snapshot.hotkey_pin_controls == ""
    assert len(events) == 1

    # Reopen confirms persistence.
    reopened = SettingsService(Database(tmp_path / "gamehub.db")).read()
    assert reopened.language == "ar"
    assert reopened.capture_interval_sec == 15
    assert reopened.hotkey_pin_controls == ""

    # Corrupt value falls back to default and logs key without leaking raw value.
    with db.write() as connection:
        connection.execute(
            "UPDATE settings SET value = '\"SECRET-INVALID\"' WHERE key = 'ui.language'"
        )
    with caplog.at_level(logging.WARNING):
        recovered = service.read()
    assert recovered.language == "en"
    assert "ui.language" in caplog.text
    assert "SECRET-INVALID" not in caplog.text


def test_settings_rolls_back_side_effects_on_hotkey_or_startup_failure(tmp_path: Path) -> None:
    db = Database(tmp_path / "gamehub.db")
    applied_hotkeys: list[tuple[str, str]] = []

    def fake_rebind(key: str, shortcut: str) -> bool:
        if key == "hotkey.last_time" and shortcut == "Ctrl+Alt+Z":
            return False
        applied_hotkeys.append((key, shortcut))
        return True

    reg_value: list[str | None] = [None]
    fail_startup = [False]

    def fake_writer(cmd: str | None) -> None:
        if fail_startup[0]:
            raise OSError("denied")
        reg_value[0] = cmd

    startup = StartupRegistration(
        command='"C:\\GameHub\\GameHub.exe"',
        writer=fake_writer,
        reader=lambda: reg_value[0],
    )
    service = SettingsService(db, rebind_hotkey=fake_rebind, startup=startup)

    # Second hotkey conflicts -> first hotkey is rolled back, DB untouched.
    res = service.update(
        {"hotkey.record_note": "Ctrl+Alt+M", "hotkey.last_time": "Ctrl+Alt+Z"}
    )
    assert res.ok is False
    assert res.errors == {"hotkey.last_time": "shortcut_conflict"}
    assert applied_hotkeys[-1] == ("hotkey.record_note", "Ctrl+Alt+N")
    assert service.read().hotkey_record_note == "Ctrl+Alt+N"

    # Startup failure rolls back hotkey change and keeps startup False.
    fail_startup[0] = True
    applied_hotkeys.clear()
    res2 = service.update({"hotkey.record_note": "Ctrl+Alt+M", "app.start_with_windows": True})
    assert res2.ok is False
    assert res2.errors == {"app.start_with_windows": "startup_unavailable"}
    assert applied_hotkeys[-1] == ("hotkey.record_note", "Ctrl+Alt+N")

    # Startup succeeds when writer succeeds.
    fail_startup[0] = False
    res3 = service.update({"app.start_with_windows": True})
    assert res3.ok is True
    assert startup.is_enabled() is True
    assert reg_value[0] == '"C:\\GameHub\\GameHub.exe"'

    # SQLite write failure rolls back both hotkey and startup side effects.
    original_write = db.write

    def failing_write():
        raise StorageError("disk full")

    db.write = failing_write  # type: ignore[method-assign]
    try:
        res4 = service.update(
            {"hotkey.record_note": "Ctrl+Alt+Q", "app.start_with_windows": False}
        )
        assert res4.ok is False
        assert res4.errors == {"_storage": "storage_unavailable"}
        assert startup.is_enabled() is True
        assert applied_hotkeys[-1] == ("hotkey.record_note", "Ctrl+Alt+N")
    finally:
        db.write = original_write  # type: ignore[method-assign]
