"""Load and query the bundled + optional user-override protected-games catalog."""

import json
import logging
import ntpath
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gamehub.core.library.models import GameSource

LOGGER = logging.getLogger(__name__)
BUNDLED_CATALOG_PATH = Path(__file__).resolve().with_name("protected_games.json")
OVERRIDE_FILENAME = "protected_games_override.json"


def _default_bundled_catalog_path() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            frozen = Path(meipass) / "gamehub" / "core" / "protection" / "protected_games.json"
            if frozen.is_file():
                return frozen
    return BUNDLED_CATALOG_PATH


@dataclass(frozen=True, slots=True)
class ProtectedGameEntry:
    id: str
    name: str
    anti_cheat: str
    privilege: str
    starts_at: str
    default_mode: str
    steam_app_ids: tuple[str, ...] = ()
    epic_app_names: tuple[str, ...] = ()
    xbox_package_prefixes: tuple[str, ...] = ()
    exe_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProtectedGameDetected:
    entry_id: str
    entry_name: str
    anti_cheat: str
    exe_name: str
    game_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProtectedGameExited:
    entry_id: str


def _parse_entries(path: Path) -> tuple[ProtectedGameEntry, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Unsupported protected-games catalog schema.")
    items = raw.get("games")
    if not isinstance(items, list):
        raise TypeError("Protected-games catalog is missing 'games' list.")

    parsed: list[ProtectedGameEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not entry_id or not name:
            continue
        parsed.append(
            ProtectedGameEntry(
                id=entry_id,
                name=name,
                anti_cheat=str(item.get("anti_cheat", "Anti-Cheat")).strip() or "Anti-Cheat",
                privilege=str(item.get("privilege", "kernel")).strip().lower() or "kernel",
                starts_at=str(item.get("starts_at", "launch")).strip().lower() or "launch",
                default_mode=str(item.get("default_mode", "strict")).strip().lower() or "strict",
                steam_app_ids=tuple(
                    str(v).strip() for v in item.get("steam_app_ids", ()) if str(v).strip()
                ),
                epic_app_names=tuple(
                    str(v).strip().casefold()
                    for v in item.get("epic_app_names", ())
                    if str(v).strip()
                ),
                xbox_package_prefixes=tuple(
                    str(v).strip().casefold()
                    for v in item.get("xbox_package_prefixes", ())
                    if str(v).strip()
                ),
                exe_names=tuple(
                    ntpath.normcase(ntpath.basename(str(v).strip()))
                    for v in item.get("exe_names", ())
                    if str(v).strip()
                ),
            )
        )
    return tuple(parsed)


class ProtectedGamesCatalog:
    """In-memory index over bundled and optional local override protected-games lists."""

    def __init__(self, entries: Sequence[ProtectedGameEntry]) -> None:
        self._entries = tuple(entries)
        self._by_id = {entry.id: entry for entry in self._entries}
        self._by_steam: dict[str, ProtectedGameEntry] = {}
        self._by_epic: dict[str, ProtectedGameEntry] = {}
        self._by_exe: dict[str, ProtectedGameEntry] = {}
        for entry in self._entries:
            for app_id in entry.steam_app_ids:
                self._by_steam[app_id] = entry
            for epic_name in entry.epic_app_names:
                self._by_epic[epic_name] = entry
            for exe in entry.exe_names:
                self._by_exe[exe] = entry

    @classmethod
    def load(
        cls,
        bundled_path: Path | None = None,
        override_path: Path | None = None,
    ) -> "ProtectedGamesCatalog":
        base_path = bundled_path if bundled_path is not None else _default_bundled_catalog_path()
        by_id: dict[str, ProtectedGameEntry] = {}
        try:
            for entry in _parse_entries(base_path):
                by_id[entry.id] = entry
        except (OSError, TypeError, ValueError):
            LOGGER.warning("protected_catalog_load_failed")

        if override_path is not None and override_path.is_file():
            try:
                for entry in _parse_entries(override_path):
                    by_id[entry.id] = entry
            except (OSError, TypeError, ValueError):
                LOGGER.warning("protected_catalog_override_invalid")

        return cls(tuple(by_id.values()))

    @property
    def entries(self) -> tuple[ProtectedGameEntry, ...]:
        return self._entries

    def all_exe_names(self) -> frozenset[str]:
        return frozenset(self._by_exe)

    def match_exe_name(self, basename: str) -> ProtectedGameEntry | None:
        if not basename:
            return None
        return self._by_exe.get(ntpath.normcase(ntpath.basename(basename)))

    def match_game(
        self,
        source: GameSource,
        source_id: str,
        exe_names: Iterable[str] = (),
    ) -> ProtectedGameEntry | None:
        if source == GameSource.STEAM and source_id:
            found = self._by_steam.get(source_id.strip())
            if found is not None:
                return found
        elif source == GameSource.EPIC and source_id:
            found = self._by_epic.get(source_id.strip().casefold())
            if found is not None:
                return found
        elif source == GameSource.XBOX and source_id:
            lowered = source_id.strip().casefold()
            for entry in self._entries:
                if any(lowered.startswith(prefix) for prefix in entry.xbox_package_prefixes):
                    return entry

        for exe in exe_names:
            found = self.match_exe_name(exe)
            if found is not None:
                return found
        return None

    def effective_mode(
        self,
        protection_mode: str,
        source: GameSource,
        source_id: str,
        exe_names: Iterable[str] = (),
    ) -> Literal["strict", "full"]:
        if protection_mode == "strict":
            return "strict"
        if protection_mode == "full":
            return "full"
        matched = self.match_game(source, source_id, exe_names)
        if matched is not None and matched.default_mode == "strict":
            return "strict"
        return "full"
