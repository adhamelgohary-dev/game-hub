"""Read-only Battle.net (Blizzard Entertainment) game detector."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_MAX_ENTRIES = 4096
_UID_RE = re.compile(r"--uid=([a-z0-9_.-]{1,64})", re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PRODUCT_CODES = {
    "pro": "Pro",
    "fenris": "Fen",
    "d4": "Fen",
    "d3": "D3",
    "osi": "OSI",
    "wow": "WoW",
    "wow_classic": "WoW",
    "s2": "S2",
    "s1": "S1",
    "w3": "W3",
    "hero": "Hero",
    "wtcg": "WTCG",
    "viper": "VIPR",
    "odin": "ODIN",
    "fore": "FORE",
    "auks": "AUKS",
    "lazr": "LAZR",
}
_HELPER_PREFIXES = (
    "unins",
    "battle.net",
    "blizzarderror",
    "crash",
    "setup",
    "updater",
    "launcher",
)
_COVER_NAMES = ("header.jpg", "cover.jpg", "cover.png", "banner.jpg")


@dataclass(frozen=True, slots=True)
class BattleNetRegistryEntry:
    key_name: str
    display_name: str
    install_location: str
    display_icon: str = ""
    uninstall_string: str = ""


def _reg_str(key: object, name: str) -> str:
    import winreg

    try:
        val, _ = winreg.QueryValueEx(key, name)
        return val.strip() if isinstance(val, str) else ""
    except OSError:
        return ""


def _read_battlenet_registry() -> tuple[BattleNetRegistryEntry, ...]:
    if os.name != "nt":
        return ()
    import winreg

    found: dict[str, BattleNetRegistryEntry] = {}
    for sub in (
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for idx in range(min(count, _MAX_ENTRIES)):
                    try:
                        kn = winreg.EnumKey(root, idx)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, kn, 0, winreg.KEY_READ) as sk:
                            pub = _reg_str(sk, "Publisher").casefold()
                            if "blizzard" not in pub:
                                continue
                            dn = _reg_str(sk, "DisplayName")
                            loc = _reg_str(sk, "InstallLocation")
                            icon = _reg_str(sk, "DisplayIcon")
                            uninst = _reg_str(sk, "UninstallString")
                            if not dn or not loc:
                                continue
                            if dn.casefold().strip() in {"battle.net", "blizzard battle.net"}:
                                continue
                            found.setdefault(
                                kn.casefold(),
                                BattleNetRegistryEntry(kn, dn, loc, icon, uninst),
                            )
                    except OSError:
                        continue
        except OSError:
            continue
    return tuple(found.values())


def _pick_exe(install_dir: Path, display_icon: str = "") -> Path | None:
    if display_icon:
        raw = display_icon.split(",", 1)[0].strip().strip('"')
        cand = local_path(raw) if raw else None
        if (
            cand is not None
            and cand.is_file()
            and cand.suffix.lower() == ".exe"
            and not cand.stem.casefold().startswith(_HELPER_PREFIXES)
            and str(cand).casefold().startswith(str(install_dir).casefold())
        ):
            return cand
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
    except OSError:
        return None
    return None


class BattleNetDetector:
    source = GameSource.BATTLENET

    def __init__(
        self,
        *,
        registry_provider: Callable[[], Iterable[BattleNetRegistryEntry]] | None = None,
    ) -> None:
        self._registry_provider = (
            registry_provider if registry_provider is not None else _read_battlenet_registry
        )

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        try:
            entries = tuple(self._registry_provider())
        except OSError:
            return DiscoveryBatch((), "partial", ("battlenet_registry_unreadable",))

        if not entries:
            return DiscoveryBatch((), "unavailable", ())

        for entry in entries:
            dn = entry.display_name.strip()
            if not dn or len(dn) > 256 or not dn.isprintable():
                continue
            install_dir = local_path(entry.install_location)
            if install_dir is None or not install_dir.is_dir():
                continue
            uid_match = _UID_RE.search(entry.uninstall_string)
            uid = uid_match.group(1).lower() if uid_match is not None else ""
            source_id = uid or _SLUG_RE.sub("-", dn.casefold()).strip("-")[:64]
            if not source_id:
                continue
            exe = _pick_exe(install_dir, entry.display_icon)
            targets = (GameTarget("exe_path", os.path.normcase(str(exe))),) if exe is not None else ()
            code = _PRODUCT_CODES.get(uid)
            launch: LaunchTarget | None = None
            if code is not None:
                launch = LaunchTarget("battlenet_uri", f"battlenet://{code}")
            elif exe is not None:
                launch = LaunchTarget("exe", str(exe))
            cover: Path | None = None
            for name in _COVER_NAMES:
                found = contained_file(install_dir, name)
                if found is not None:
                    cover = found
                    break
            games[source_id] = DetectedGame(
                GameSource.BATTLENET,
                source_id,
                dn,
                install_dir,
                cover,
                launch,
                targets,
            )

        return DiscoveryBatch(tuple(games.values()), "complete", ())
