"""Read-only EA app / Electronic Arts game detector."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_MAX_ENTRIES = 4096
_OFFER_ID_RE = re.compile(r"[A-Za-z0-9._:,-]{1,128}\Z")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NON_GAME_NAMES = (
    "ea app",
    "origin",
    "ea anticheat",
    "ea javelin",
    "electronic arts app",
)
_HELPER_PREFIXES = (
    "unins",
    "cleanup",
    "touchup",
    "activationui",
    "eaanticheat",
    "easyanticheat",
    "beservice",
    "crash",
    "setup",
    "install",
    "redist",
    "vcredist",
    "dxsetup",
    "ue4prereq",
    "ueprereq",
    "eadest",
    "eadesktop",
    "ealauncher",
    "link2ea",
)
_COVER_NAMES = ("header.jpg", "cover.jpg", "cover.png", "banner.jpg", "boxart.jpg")


@dataclass(frozen=True, slots=True)
class EaRegistryEntry:
    source_id: str
    display_name: str
    install_location: str
    display_icon: str = ""
    offer_id: str = ""


def _reg_str(key: object, name: str) -> str:
    import winreg

    try:
        val, _ = winreg.QueryValueEx(key, name)
        return val.strip() if isinstance(val, str) else ""
    except OSError:
        return ""


def _is_non_game_name(name: str) -> bool:
    low = name.casefold().strip()
    return any(tok in low for tok in _NON_GAME_NAMES)


def _slug(text: str) -> str:
    cleaned = _SLUG_RE.sub("-", text.casefold()).strip("-")
    return cleaned[:96] or "ea-game"


def _read_ea_registry() -> tuple[EaRegistryEntry, ...]:
    if os.name != "nt":
        return ()
    import winreg

    found: dict[str, EaRegistryEntry] = {}

    # 1. HKLM\SOFTWARE\EA Games\* (and WOW6432Node)
    for sub in (r"SOFTWARE\EA Games", r"SOFTWARE\WOW6432Node\EA Games"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for idx in range(min(count, _MAX_ENTRIES)):
                    try:
                        key_name = winreg.EnumKey(root, idx)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, key_name, 0, winreg.KEY_READ) as sk:
                            loc = _reg_str(sk, "Install Dir") or _reg_str(sk, "InstallLocation")
                            dn = _reg_str(sk, "DisplayName") or key_name
                            if loc and dn and not _is_non_game_name(dn):
                                sid = _slug(dn)
                                found.setdefault(sid, EaRegistryEntry(sid, dn, loc))
                    except OSError:
                        continue
        except OSError:
            continue

    # 2. Uninstall keys with Electronic Arts publisher
    uninstall_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    )
    for hive, sub in uninstall_roots:
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for idx in range(min(count, _MAX_ENTRIES)):
                    try:
                        key_name = winreg.EnumKey(root, idx)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, key_name, 0, winreg.KEY_READ) as sk:
                            pub = _reg_str(sk, "Publisher").casefold()
                            if "electronic arts" not in pub:
                                continue
                            dn = _reg_str(sk, "DisplayName")
                            loc = _reg_str(sk, "InstallLocation")
                            icon = _reg_str(sk, "DisplayIcon")
                            if not dn or not loc or _is_non_game_name(dn):
                                continue
                            sid = _slug(dn)
                            found[sid] = EaRegistryEntry(sid, dn, loc, display_icon=icon)
                    except OSError:
                        continue
        except OSError:
            continue

    return tuple(found.values())


def _pick_ea_exe(install_dir: Path, display_icon: str = "") -> Path | None:
    if display_icon:
        raw = display_icon.split(",", 1)[0].strip().strip('"')
        icon_p = local_path(raw) if raw else None
        if (
            icon_p is not None
            and icon_p.is_file()
            and icon_p.suffix.lower() == ".exe"
            and not icon_p.stem.casefold().startswith(_HELPER_PREFIXES)
            and str(icon_p).casefold().startswith(str(install_dir).casefold())
        ):
            return icon_p
    try:
        candidates: list[Path] = []
        for idx, child in enumerate(install_dir.iterdir()):
            if idx >= 128:
                break
            if child.suffix.lower() != ".exe":
                continue
            if child.stem.casefold().startswith(_HELPER_PREFIXES):
                continue
            safe = contained_file(install_dir, child.name)
            if safe is not None:
                candidates.append(safe)
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # Prefer largest executable as main game binary
            candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
            return candidates[0]
    except OSError:
        return None
    return None


def _find_cover(install_dir: Path) -> Path | None:
    for name in _COVER_NAMES:
        cand = contained_file(install_dir, name)
        if cand is not None:
            return cand
    return None


class EaDetector:
    source = GameSource.EA

    def __init__(
        self,
        install_data_dir: Path | None = None,
        *,
        registry_provider: Callable[[], Iterable[EaRegistryEntry]] | None = None,
    ) -> None:
        pd = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        self._explicit_dir = install_data_dir is not None
        self._install_data_dir = (
            install_data_dir
            if install_data_dir is not None
            else pd / "EA Desktop" / "InstallData"
        )
        if registry_provider is not None:
            self._registry_provider: Callable[[], Iterable[EaRegistryEntry]] | None = (
                registry_provider
            )
        elif not self._explicit_dir:
            self._registry_provider = _read_ea_registry
        else:
            self._registry_provider = None

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        dir_available = False

        data_dir = local_path(self._install_data_dir)
        if data_dir is not None and data_dir.is_dir():
            dir_available = True
            self._scan_install_data(data_dir, games, diagnostics)

        reg_found = False
        if self._registry_provider is not None:
            try:
                for entry in self._registry_provider():
                    game = self._from_entry(entry)
                    if game is not None:
                        reg_found = True
                        games.setdefault(game.source_id, game)
            except OSError:
                diagnostics.add("ea_registry_unreadable")

        if not dir_available and not reg_found and not games and not diagnostics:
            return DiscoveryBatch((), "unavailable", ())
        state = "partial" if diagnostics else "complete"
        return DiscoveryBatch(tuple(games.values()), state, tuple(sorted(diagnostics)))

    def _scan_install_data(
        self,
        data_dir: Path,
        games: dict[str, DetectedGame],
        diagnostics: set[str],
    ) -> None:
        try:
            with os.scandir(data_dir) as it:
                for idx, entry in enumerate(it):
                    if idx >= _MAX_ENTRIES:
                        break
                    if not entry.name.lower().endswith(".json"):
                        continue
                    safe = contained_file(data_dir, entry.name)
                    if safe is None:
                        continue
                    try:
                        payload = json.loads(safe.read_text(encoding="utf-8"))
                        if not isinstance(payload, dict):
                            continue
                        dn = str(payload.get("displayName") or payload.get("name") or "").strip()
                        loc = str(
                            payload.get("installLocation") or payload.get("installDir") or ""
                        ).strip()
                        offer = str(payload.get("offerId") or payload.get("contentId") or "").strip()
                        if not dn or not loc or _is_non_game_name(dn):
                            continue
                        sid = offer if _OFFER_ID_RE.fullmatch(offer) else _slug(dn)
                        game = self._from_entry(EaRegistryEntry(sid, dn, loc, offer_id=offer))
                        if game is not None:
                            games.setdefault(game.source_id, game)
                    except (OSError, ValueError, TypeError):
                        diagnostics.add("ea_metadata_unreadable")
        except OSError:
            diagnostics.add("ea_metadata_unreadable")

    def _from_entry(self, entry: EaRegistryEntry) -> DetectedGame | None:
        dn = entry.display_name.strip()
        if not dn or len(dn) > 256 or not dn.isprintable() or _is_non_game_name(dn):
            return None
        install_dir = local_path(entry.install_location)
        if install_dir is None or not install_dir.is_dir():
            return None
        exe = _pick_ea_exe(install_dir, entry.display_icon)
        targets = (GameTarget("exe_path", os.path.normcase(str(exe))),) if exe is not None else ()
        launch: LaunchTarget | None = None
        if entry.offer_id and _OFFER_ID_RE.fullmatch(entry.offer_id):
            launch = LaunchTarget("ea_uri", f"origin2://game/launch?offerIds={entry.offer_id}")
        elif exe is not None:
            launch = LaunchTarget("exe", str(exe))
        cover = _find_cover(install_dir)
        return DetectedGame(
            GameSource.EA,
            entry.source_id,
            dn,
            install_dir,
            cover,
            launch,
            targets,
        )
