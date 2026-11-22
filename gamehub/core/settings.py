"""Validated application settings, live change notifications, and side-effect coordination."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from gamehub.core.hotkeys.windows import canonical_shortcut
from gamehub.core.storage.db import Database, StorageError

LOGGER = logging.getLogger(__name__)

MIN_CAPTURE_INTERVAL_SEC = 5
MAX_CAPTURE_INTERVAL_SEC = 300
MIN_BUFFER_SIZE = 1
MAX_BUFFER_SIZE = 50
ALLOWED_LANGUAGES = ("en", "ar")
HOTKEY_KEYS = ("hotkey.record_note", "hotkey.last_time", "hotkey.pin_controls")


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    language: str = "en"
    capture_interval_sec: int = 30
    capture_buffer_size: int = 10
    autoplay_voice: bool = True
    prompt_on_end: bool = True
    hotkey_record_note: str = "Ctrl+Alt+N"
    hotkey_last_time: str = "Ctrl+Alt+L"
    hotkey_pin_controls: str = "Ctrl+Alt+C"
    revision: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "ui.language": self.language,
            "capture.interval_sec": self.capture_interval_sec,
            "capture.buffer_size": self.capture_buffer_size,
            "memory.autoplay_voice": self.autoplay_voice,
            "memory.prompt_on_end": self.prompt_on_end,
            "hotkey.record_note": self.hotkey_record_note,
            "hotkey.last_time": self.hotkey_last_time,
            "hotkey.pin_controls": self.hotkey_pin_controls,
        }


@dataclass(frozen=True, slots=True)
class SettingsChanged:
    keys: tuple[str, ...]
    revision: int
    snapshot: SettingsSnapshot


@dataclass(frozen=True, slots=True)
class SettingsResult:
    ok: bool
    snapshot: SettingsSnapshot
    errors: dict[str, str]


_FIELD_MAP = {
    "ui.language": "language",
    "capture.interval_sec": "capture_interval_sec",
    "capture.buffer_size": "capture_buffer_size",
    "memory.autoplay_voice": "autoplay_voice",
    "memory.prompt_on_end": "prompt_on_end",
    "hotkey.record_note": "hotkey_record_note",
    "hotkey.last_time": "hotkey_last_time",
    "hotkey.pin_controls": "hotkey_pin_controls",
}


def _validate_value(key: str, raw: object) -> tuple[bool, object, str | None]:
    if key == "ui.language":
        if isinstance(raw, str) and raw in ALLOWED_LANGUAGES:
            return True, raw, None
        return False, None, "invalid_language"
    if key == "capture.interval_sec":
        if (
            isinstance(raw, int)
            and not isinstance(raw, bool)
            and MIN_CAPTURE_INTERVAL_SEC <= raw <= MAX_CAPTURE_INTERVAL_SEC
        ):
            return True, raw, None
        return False, None, "invalid_capture_interval"
    if key == "capture.buffer_size":
        if (
            isinstance(raw, int)
            and not isinstance(raw, bool)
            and MIN_BUFFER_SIZE <= raw <= MAX_BUFFER_SIZE
        ):
            return True, raw, None
        return False, None, "invalid_buffer_size"
    if key in {"memory.autoplay_voice", "memory.prompt_on_end"}:
        if isinstance(raw, bool):
            return True, raw, None
        return False, None, "invalid_boolean"
    if key in HOTKEY_KEYS:
        if isinstance(raw, str):
            canonical = canonical_shortcut(raw)
            if canonical is not None:
                return True, canonical, None
        return False, None, "invalid_shortcut"
    return False, None, "unknown_setting"


class SettingsService:
    """Read, validate, coordinate OS side effects, and persist application settings."""

    def __init__(
        self,
        database: Database,
        *,
        publish: Callable[[SettingsChanged], None] | None = None,
        rebind_hotkey: Callable[[str, str], bool] | None = None,
        rebind_hotkeys: Callable[[dict[str, str]], tuple[bool, str | None, str | None]] | None = None,
    ) -> None:
        self._database = database
        self._publish = publish
        self._rebind_hotkey = rebind_hotkey
        self._rebind_hotkeys = rebind_hotkeys
        self._revision = 0

    def read(self) -> SettingsSnapshot:
        """Read all validated settings from one SQLite snapshot with safe default fallbacks."""
        defaults = SettingsSnapshot()
        values = defaults.as_dict()
        with self._database.read_snapshot() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()

        for row in rows:
            key = row["key"]
            if key not in _FIELD_MAP:
                continue
            try:
                parsed = json.loads(row["value"])
            except ValueError:
                LOGGER.warning("invalid_setting key=%s", key)
                continue
            ok, validated, _ = _validate_value(key, parsed)
            if ok:
                values[key] = validated
            else:
                LOGGER.warning("invalid_setting key=%s", key)

        # Resolve duplicate stored hotkeys by disabling colliding later keys.
        seen_hotkeys: set[str] = set()
        for key in HOTKEY_KEYS:
            val = values[key]
            assert isinstance(val, str)
            if val and val in seen_hotkeys:
                LOGGER.warning("invalid_setting key=%s", key)
                values[key] = ""
            elif val:
                seen_hotkeys.add(val)

        return SettingsSnapshot(
            language=values["ui.language"],  # type: ignore[arg-type]
            capture_interval_sec=values["capture.interval_sec"],  # type: ignore[arg-type]
            capture_buffer_size=values["capture.buffer_size"],  # type: ignore[arg-type]
            autoplay_voice=values["memory.autoplay_voice"],  # type: ignore[arg-type]
            prompt_on_end=values["memory.prompt_on_end"],  # type: ignore[arg-type]
            hotkey_record_note=values["hotkey.record_note"],  # type: ignore[arg-type]
            hotkey_last_time=values["hotkey.last_time"],  # type: ignore[arg-type]
            hotkey_pin_controls=values["hotkey.pin_controls"],  # type: ignore[arg-type]
            revision=self._revision,
        )

    def update(self, patch: dict[str, object]) -> SettingsResult:
        """Validate, apply hotkey/startup side effects atomically, and persist."""
        current = self.read()
        merged = current.as_dict()
        errors: dict[str, str] = {}
        validated_patch: dict[str, object] = {}

        for key, raw in patch.items():
            ok, value, error = _validate_value(key, raw)
            if not ok:
                errors[key] = error or "invalid_setting"
            else:
                validated_patch[key] = value
                merged[key] = value

        # Reject duplicate nonempty shortcuts across the three actions.
        seen: dict[str, str] = {}
        for key in HOTKEY_KEYS:
            val = merged[key]
            assert isinstance(val, str)
            if not val:
                continue
            if val in seen:
                errors[key] = "duplicate_shortcut"
                errors.setdefault(seen[val], "duplicate_shortcut")
            else:
                seen[val] = key

        if errors:
            return SettingsResult(False, current, errors)

        changed_keys = tuple(
            key for key, value in validated_patch.items() if current.as_dict()[key] != value
        )
        if not changed_keys:
            return SettingsResult(True, current, {})

        # Coordinate Windows hotkey side effects first; roll back all on conflict.
        hotkey_changes = {
            key: str(validated_patch[key]) for key in HOTKEY_KEYS if key in changed_keys
        }
        previous_hotkeys = {key: str(current.as_dict()[key]) for key in hotkey_changes}
        applied_hotkeys: list[tuple[str, str]] = []
        if hotkey_changes:
            if self._rebind_hotkeys is not None:
                ok, failed_key, diag = self._rebind_hotkeys(hotkey_changes)
                if not ok:
                    return SettingsResult(
                        False,
                        current,
                        {failed_key or "hotkey.record_note": diag or "shortcut_conflict"},
                    )
            elif self._rebind_hotkey is not None:
                for key, new_binding in hotkey_changes.items():
                    old_binding = previous_hotkeys[key]
                    if not self._rebind_hotkey(key, new_binding):
                        for prev_key, prev_binding in reversed(applied_hotkeys):
                            self._rebind_hotkey(prev_key, prev_binding)
                        return SettingsResult(False, current, {key: "shortcut_conflict"})
                    applied_hotkeys.append((key, old_binding))

        def rollback_hotkeys() -> None:
            if not hotkey_changes:
                return
            if self._rebind_hotkeys is not None:
                self._rebind_hotkeys(previous_hotkeys)
            elif self._rebind_hotkey is not None:
                for prev_key, prev_binding in reversed(applied_hotkeys):
                    self._rebind_hotkey(prev_key, prev_binding)

        # Persist to SQLite in a single transaction; roll back OS side effects on StorageError.
        try:
            with self._database.write() as connection:
                connection.executemany(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                    [(key, json.dumps(validated_patch[key])) for key in changed_keys],
                )
        except StorageError:
            rollback_hotkeys()
            return SettingsResult(False, current, {"_storage": "storage_unavailable"})

        self._revision += 1
        updated = replace(
            current,
            revision=self._revision,
            **{_FIELD_MAP[key]: validated_patch[key] for key in changed_keys},
        )
        if self._publish is not None:
            self._publish(SettingsChanged(changed_keys, self._revision, updated))
        return SettingsResult(True, updated, {})
