"""Load and query the bundled + optional user-override protected-games catalog (schema v1 & v2)."""

import json
import logging
import ntpath
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gamehub.core.library.models import GameSource

LOGGER = logging.getLogger(__name__)
BUNDLED_CATALOG_PATH = Path(__file__).resolve().with_name("protected_games.json")
OVERRIDE_FILENAME = "protected_games_override.json"
_TITLE_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm_title(text: str) -> str:
    cleaned = text.replace("™", "").replace("®", "").replace("©", "").replace("'", "")
    return _TITLE_NORM_RE.sub(" ", cleaned.casefold()).strip()

DEFAULT_ALWAYS_STRICT_LAUNCHERS: dict[str, tuple[str, ...]] = {
    "riot": (
        "riotclientservices.exe",
        "riotclientux.exe",
        "riotclientuxrender.exe",
        "riotclientcrashhandler.exe",
        "riot client.exe",
        "leagueclient.exe",
        "leagueclientux.exe",
        "leagueclientuxrender.exe",
    )
}
DEFAULT_OPTIONAL_STRICT_LAUNCHERS: dict[str, tuple[str, ...]] = {
    "epic": ("epicgameslauncher.exe",),
    "ea": ("eadesktop.exe", "ealocalhostsvc.exe"),
    "battlenet": ("battle.net.exe",),
    "ubisoft": ("upc.exe", "ubisoftconnect.exe"),
    "steam": ("steam.exe",),
}
DEFAULT_ANTI_CHEAT_SERVICES: tuple[str, ...] = (
    "EasyAntiCheat_EOS",
    "EasyAntiCheat",
    "BEService",
)
DEFAULT_GLOBAL_ANTI_CHEAT_EXES: tuple[str, ...] = (
    "easyanticheat.exe",
    "easyanticheat_eos.exe",
    "beservice.exe",
    "beservice_x64.exe",
    "eaanticheat.gameservicelauncher.exe",
    "start_protected_game.exe",
    "gamemon.des",
    "gamemon64.des",
    "sguard64.exe",
    "sguardsvc64.exe",
)


class CatalogLoadError(RuntimeError):
    """Raised in fail-closed mode when the protected-games catalog cannot be loaded safely."""


def _default_bundled_catalog_path() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            frozen = Path(meipass) / "gamehub" / "core" / "protection" / "protected_games.json"
            if frozen.is_file():
                return frozen
    return BUNDLED_CATALOG_PATH


def _norm_exe_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    seen: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        norm = ntpath.normcase(ntpath.basename(text))
        if norm and norm not in seen:
            seen.append(norm)
    return tuple(seen)


def _norm_str_tuple(values: object, *, fold: bool = False) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    out: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        item = text.casefold() if fold else text
        if item not in out:
            out.append(item)
    return tuple(out)


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
    riot_product_ids: tuple[str, ...] = ()
    ubisoft_ids: tuple[str, ...] = ()
    battlenet_ids: tuple[str, ...] = ()
    ea_ids: tuple[str, ...] = ()
    xbox_package_prefixes: tuple[str, ...] = ()
    title_aliases: tuple[str, ...] = ()
    launcher_stage_exes: tuple[str, ...] = ()
    anti_cheat_exes: tuple[str, ...] = ()
    game_exes: tuple[str, ...] = ()
    exe_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.exe_names and (
            self.launcher_stage_exes or self.anti_cheat_exes or self.game_exes
        ):
            combined = tuple(
                dict.fromkeys(
                    (*self.launcher_stage_exes, *self.anti_cheat_exes, *self.game_exes)
                )
            )
            object.__setattr__(self, "exe_names", combined)
        elif self.exe_names and not (
            self.launcher_stage_exes or self.anti_cheat_exes or self.game_exes
        ):
            object.__setattr__(self, "game_exes", self.exe_names)


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


@dataclass(frozen=True, slots=True)
class _ParsedCatalogFile:
    entries: tuple[ProtectedGameEntry, ...]
    always_strict_launchers: dict[str, tuple[str, ...]] | None
    optional_strict_launchers: dict[str, tuple[str, ...]] | None
    anti_cheat_services: tuple[str, ...] | None
    global_anti_cheat_exes: tuple[str, ...] | None


def _parse_launcher_map(raw: object) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, tuple[str, ...]] = {}
    for key, val in raw.items():
        k = str(key).strip().lower()
        if not k:
            continue
        out[k] = _norm_exe_tuple(val)
    return out


def _parse_file(path: Path) -> _ParsedCatalogFile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema_ver = raw.get("schema_version") if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or type(schema_ver) is not int or schema_ver not in {1, 2}:
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

        launcher_stage = _norm_exe_tuple(item.get("launcher_stage_exes", ()))
        anti_cheat_exes = _norm_exe_tuple(item.get("anti_cheat_exes", ()))
        game_exes = _norm_exe_tuple(item.get("game_exes", ()))
        legacy_exes = _norm_exe_tuple(item.get("exe_names", ()))
        combined = tuple(dict.fromkeys((*launcher_stage, *anti_cheat_exes, *game_exes, *legacy_exes)))
        if not game_exes and legacy_exes:
            game_exes = legacy_exes

        parsed.append(
            ProtectedGameEntry(
                id=entry_id,
                name=name,
                anti_cheat=str(item.get("anti_cheat", "Anti-Cheat")).strip() or "Anti-Cheat",
                privilege=str(item.get("privilege", "kernel")).strip().lower() or "kernel",
                starts_at=str(item.get("starts_at", "launch")).strip().lower() or "launch",
                default_mode=str(item.get("default_mode", "strict")).strip().lower() or "strict",
                steam_app_ids=_norm_str_tuple(item.get("steam_app_ids", ())),
                epic_app_names=_norm_str_tuple(item.get("epic_app_names", ()), fold=True),
                riot_product_ids=_norm_str_tuple(item.get("riot_product_ids", ()), fold=True),
                ubisoft_ids=_norm_str_tuple(item.get("ubisoft_ids", ()), fold=True),
                battlenet_ids=_norm_str_tuple(item.get("battlenet_ids", ()), fold=True),
                ea_ids=_norm_str_tuple(item.get("ea_ids", ()), fold=True),
                xbox_package_prefixes=_norm_str_tuple(
                    item.get("xbox_package_prefixes", ()), fold=True
                ),
                title_aliases=tuple(
                    dict.fromkeys(
                        norm
                        for raw_alias in (
                            item.get("title_aliases", ())
                            if isinstance(item.get("title_aliases", ()), (list, tuple))
                            else ()
                        )
                        if (norm := _norm_title(str(raw_alias)))
                    )
                ),
                launcher_stage_exes=launcher_stage,
                anti_cheat_exes=anti_cheat_exes,
                game_exes=game_exes,
                exe_names=combined,
            )
        )

    services_raw = raw.get("anti_cheat_services")
    services = _norm_str_tuple(services_raw) if isinstance(services_raw, list) else None
    global_ac_raw = raw.get("global_anti_cheat_exes")
    global_ac = _norm_exe_tuple(global_ac_raw) if isinstance(global_ac_raw, list) else None

    return _ParsedCatalogFile(
        entries=tuple(parsed),
        always_strict_launchers=_parse_launcher_map(raw.get("always_strict_launchers")),
        optional_strict_launchers=_parse_launcher_map(raw.get("optional_strict_launchers")),
        anti_cheat_services=services,
        global_anti_cheat_exes=global_ac,
    )


class ProtectedGamesCatalog:
    """In-memory index over bundled and optional local override protected-games lists."""

    def __init__(
        self,
        entries: Sequence[ProtectedGameEntry],
        *,
        always_strict_launchers: Mapping[str, Sequence[str]] | None = None,
        optional_strict_launchers: Mapping[str, Sequence[str]] | None = None,
        anti_cheat_services: Sequence[str] | None = None,
        global_anti_cheat_exes: Sequence[str] | None = None,
    ) -> None:
        self._entries = tuple(entries)
        self._always_strict_launchers: dict[str, tuple[str, ...]] = {
            k: tuple(ntpath.normcase(ntpath.basename(e)) for e in v)
            for k, v in (
                always_strict_launchers
                if always_strict_launchers is not None
                else DEFAULT_ALWAYS_STRICT_LAUNCHERS
            ).items()
        }
        self._optional_strict_launchers: dict[str, tuple[str, ...]] = {
            k: tuple(ntpath.normcase(ntpath.basename(e)) for e in v)
            for k, v in (
                optional_strict_launchers
                if optional_strict_launchers is not None
                else DEFAULT_OPTIONAL_STRICT_LAUNCHERS
            ).items()
        }
        self._anti_cheat_services: tuple[str, ...] = tuple(
            anti_cheat_services if anti_cheat_services is not None else DEFAULT_ANTI_CHEAT_SERVICES
        )
        self._global_anti_cheat_exes: frozenset[str] = frozenset(
            ntpath.normcase(ntpath.basename(e))
            for e in (
                global_anti_cheat_exes
                if global_anti_cheat_exes is not None
                else DEFAULT_GLOBAL_ANTI_CHEAT_EXES
            )
        )

        self._by_id = {entry.id: entry for entry in self._entries}
        self._by_steam: dict[str, ProtectedGameEntry] = {}
        self._by_epic: dict[str, ProtectedGameEntry] = {}
        self._by_riot: dict[str, ProtectedGameEntry] = {}
        self._by_ubisoft: dict[str, ProtectedGameEntry] = {}
        self._by_battlenet: dict[str, ProtectedGameEntry] = {}
        self._by_ea: dict[str, ProtectedGameEntry] = {}
        self._by_exe: dict[str, ProtectedGameEntry] = {}
        self._by_launcher_stage_exe: dict[str, ProtectedGameEntry] = {}
        self._by_anti_cheat_exe: dict[str, ProtectedGameEntry] = {}
        self._by_game_exe: dict[str, ProtectedGameEntry] = {}

        for entry in self._entries:
            for app_id in entry.steam_app_ids:
                self._by_steam.setdefault(app_id, entry)
            for epic_name in entry.epic_app_names:
                self._by_epic.setdefault(epic_name, entry)
            for riot_id in entry.riot_product_ids:
                self._by_riot.setdefault(riot_id, entry)
            for ubi_id in entry.ubisoft_ids:
                self._by_ubisoft.setdefault(ubi_id, entry)
            for bnet_id in entry.battlenet_ids:
                self._by_battlenet.setdefault(bnet_id, entry)
            for ea_id in entry.ea_ids:
                self._by_ea.setdefault(ea_id, entry)
            for exe in entry.launcher_stage_exes:
                self._by_launcher_stage_exe.setdefault(exe, entry)
                self._by_exe.setdefault(exe, entry)
            for exe in entry.anti_cheat_exes:
                self._by_anti_cheat_exe.setdefault(exe, entry)
                self._by_exe.setdefault(exe, entry)
            for exe in entry.game_exes:
                self._by_game_exe.setdefault(exe, entry)
                self._by_exe.setdefault(exe, entry)

    @staticmethod
    def _merge_override_entry(
        base: ProtectedGameEntry, override: ProtectedGameEntry
    ) -> ProtectedGameEntry:
        """Strictly additive merge: an override can never weaken or strip bundled protection."""
        return ProtectedGameEntry(
            id=base.id,
            name=base.name,
            anti_cheat=base.anti_cheat,
            privilege=base.privilege,
            starts_at=base.starts_at,
            default_mode="strict" if base.default_mode == "strict" else override.default_mode,
            steam_app_ids=tuple(dict.fromkeys((*base.steam_app_ids, *override.steam_app_ids))),
            epic_app_names=tuple(dict.fromkeys((*base.epic_app_names, *override.epic_app_names))),
            riot_product_ids=tuple(
                dict.fromkeys((*base.riot_product_ids, *override.riot_product_ids))
            ),
            ubisoft_ids=tuple(dict.fromkeys((*base.ubisoft_ids, *override.ubisoft_ids))),
            battlenet_ids=tuple(dict.fromkeys((*base.battlenet_ids, *override.battlenet_ids))),
            ea_ids=tuple(dict.fromkeys((*base.ea_ids, *override.ea_ids))),
            xbox_package_prefixes=tuple(
                dict.fromkeys((*base.xbox_package_prefixes, *override.xbox_package_prefixes))
            ),
            title_aliases=tuple(
                dict.fromkeys((*base.title_aliases, *override.title_aliases))
            ),
            launcher_stage_exes=tuple(
                dict.fromkeys((*base.launcher_stage_exes, *override.launcher_stage_exes))
            ),
            anti_cheat_exes=tuple(
                dict.fromkeys((*base.anti_cheat_exes, *override.anti_cheat_exes))
            ),
            game_exes=tuple(dict.fromkeys((*base.game_exes, *override.game_exes))),
        )

    @classmethod
    def load(
        cls,
        bundled_path: Path | None = None,
        override_path: Path | None = None,
        *,
        strict_load: bool = False,
    ) -> "ProtectedGamesCatalog":
        base_path = bundled_path if bundled_path is not None else _default_bundled_catalog_path()
        by_id: dict[str, ProtectedGameEntry] = {}
        always_strict = dict(DEFAULT_ALWAYS_STRICT_LAUNCHERS)
        optional_strict = dict(DEFAULT_OPTIONAL_STRICT_LAUNCHERS)
        services = list(DEFAULT_ANTI_CHEAT_SERVICES)
        global_ac = list(DEFAULT_GLOBAL_ANTI_CHEAT_EXES)

        try:
            parsed = _parse_file(base_path)
            for entry in parsed.entries:
                by_id[entry.id] = entry
            if parsed.always_strict_launchers is not None:
                for key, exes in parsed.always_strict_launchers.items():
                    always_strict[key] = tuple(
                        dict.fromkeys((*always_strict.get(key, ()), *exes))
                    )
            if parsed.optional_strict_launchers is not None:
                for key, exes in parsed.optional_strict_launchers.items():
                    optional_strict[key] = tuple(
                        dict.fromkeys((*optional_strict.get(key, ()), *exes))
                    )
            if parsed.anti_cheat_services is not None:
                services = list(dict.fromkeys((*services, *parsed.anti_cheat_services)))
            if parsed.global_anti_cheat_exes is not None:
                global_ac = list(dict.fromkeys((*global_ac, *parsed.global_anti_cheat_exes)))
        except (OSError, TypeError, ValueError, RecursionError) as exc:
            LOGGER.warning("protected_catalog_load_failed")
            if strict_load:
                raise CatalogLoadError("Bundled protected-games catalog could not be loaded.") from exc

        if strict_load and not by_id:
            raise CatalogLoadError("Bundled protected-games catalog is empty.")

        if override_path is not None and override_path.is_file():
            try:
                override = _parse_file(override_path)
                for entry in override.entries:
                    if entry.id in by_id:
                        by_id[entry.id] = cls._merge_override_entry(by_id[entry.id], entry)
                    else:
                        # New override entries can only ADD strict protection, never weaken defaults.
                        by_id[entry.id] = ProtectedGameEntry(
                            id=entry.id,
                            name=entry.name,
                            anti_cheat=entry.anti_cheat,
                            privilege=entry.privilege,
                            starts_at=entry.starts_at,
                            default_mode="strict",
                            steam_app_ids=entry.steam_app_ids,
                            epic_app_names=entry.epic_app_names,
                            riot_product_ids=entry.riot_product_ids,
                            ubisoft_ids=entry.ubisoft_ids,
                            battlenet_ids=entry.battlenet_ids,
                            ea_ids=entry.ea_ids,
                            xbox_package_prefixes=entry.xbox_package_prefixes,
                            title_aliases=entry.title_aliases,
                            launcher_stage_exes=entry.launcher_stage_exes,
                            anti_cheat_exes=entry.anti_cheat_exes,
                            game_exes=entry.game_exes,
                            exe_names=entry.exe_names,
                        )
                if override.anti_cheat_services:
                    services = list(dict.fromkeys((*services, *override.anti_cheat_services)))
                if override.global_anti_cheat_exes:
                    global_ac = list(dict.fromkeys((*global_ac, *override.global_anti_cheat_exes)))
            except (OSError, TypeError, ValueError, RecursionError):
                LOGGER.warning("protected_catalog_override_invalid")

        return cls(
            tuple(by_id.values()),
            always_strict_launchers=always_strict,
            optional_strict_launchers=optional_strict,
            anti_cheat_services=tuple(services),
            global_anti_cheat_exes=tuple(global_ac),
        )

    @property
    def entries(self) -> tuple[ProtectedGameEntry, ...]:
        return self._entries

    @property
    def always_strict_launchers(self) -> Mapping[str, tuple[str, ...]]:
        return self._always_strict_launchers

    @property
    def optional_strict_launchers(self) -> Mapping[str, tuple[str, ...]]:
        return self._optional_strict_launchers

    @property
    def anti_cheat_services(self) -> tuple[str, ...]:
        return self._anti_cheat_services

    @property
    def global_anti_cheat_exes(self) -> frozenset[str]:
        return self._global_anti_cheat_exes

    def all_exe_names(self) -> frozenset[str]:
        all_names = set(self._by_exe)
        all_names.update(self._global_anti_cheat_exes)
        for exes in self._always_strict_launchers.values():
            all_names.update(exes)
        return frozenset(all_names)

    def all_launcher_exe_names(self) -> frozenset[str]:
        names: set[str] = set()
        for exes in self._always_strict_launchers.values():
            names.update(exes)
        for exes in self._optional_strict_launchers.values():
            names.update(exes)
        return frozenset(names)

    def match_exe_name(self, basename: str) -> ProtectedGameEntry | None:
        if not basename:
            return None
        norm = ntpath.normcase(ntpath.basename(basename))
        return (
            self._by_game_exe.get(norm)
            or self._by_launcher_stage_exe.get(norm)
            or self._by_anti_cheat_exe.get(norm)
            or self._by_exe.get(norm)
        )

    def match_launcher_stage_exe(self, basename: str) -> ProtectedGameEntry | None:
        if not basename:
            return None
        return self._by_launcher_stage_exe.get(ntpath.normcase(ntpath.basename(basename)))

    def match_game_exe(self, basename: str) -> ProtectedGameEntry | None:
        if not basename:
            return None
        return self._by_game_exe.get(ntpath.normcase(ntpath.basename(basename)))

    def match_game(
        self,
        source: GameSource,
        source_id: str,
        exe_names: Iterable[str] = (),
        *,
        game_name: str = "",
    ) -> ProtectedGameEntry | None:
        if source == GameSource.STEAM and source_id:
            found = self._by_steam.get(source_id.strip())
            if found is not None:
                return found
        elif source == GameSource.EPIC and source_id:
            # Support both bare AppName ("Fortnite") and "ns:item:AppName" formats.
            cleaned = source_id.strip().casefold()
            found = self._by_epic.get(cleaned) or self._by_epic.get(cleaned.rsplit(":", 1)[-1])
            if found is not None:
                return found
        elif source.value == "riot" and source_id:
            cleaned = source_id.strip().casefold().split(".", 1)[0]
            found = self._by_riot.get(cleaned)
            if found is not None:
                return found
        elif source == GameSource.UBISOFT and source_id:
            found = self._by_ubisoft.get(source_id.strip().casefold())
            if found is not None:
                return found
        elif source == GameSource.BATTLENET and source_id:
            found = self._by_battlenet.get(source_id.strip().casefold())
            if found is not None:
                return found
        elif source == GameSource.EA and source_id:
            found = self._by_ea.get(source_id.strip().casefold())
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

        if game_name:
            norm_name = _norm_title(game_name)
            if norm_name:
                for entry in self._entries:
                    for alias in entry.title_aliases:
                        if norm_name == alias or norm_name.startswith(f"{alias} "):
                            return entry
        return None

    def effective_mode(
        self,
        protection_mode: str,
        source: GameSource,
        source_id: str,
        exe_names: Iterable[str] = (),
        *,
        game_name: str = "",
    ) -> Literal["strict", "full"]:
        if protection_mode == "strict":
            return "strict"
        if protection_mode == "full":
            return "full"
        matched = self.match_game(source, source_id, exe_names, game_name=game_name)
        if matched is not None and matched.default_mode == "strict":
            return "strict"
        return "full"
