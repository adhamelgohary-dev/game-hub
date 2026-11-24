"""Read-only Ubisoft Connect game detector."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_INSTALL_ID_RE = re.compile(r"[0-9]{1,10}\Z")
_MAX_ENTRIES = 4096
_HELPER_PREFIXES = (
    "unins",
    "uplay",
    "upc",
    "ubisoft",
    "easyanticheat",
    "beservice",
    "battleye",
    "crash",
    "setup",
    "redist",
    "vcredist",
    "dxsetup",
)
_COVER_NAMES = ("header.jpg", "cover.jpg", "cover.png", "banner.jpg")


@dataclass(frozen=True, slots=True)
class UbisoftRegistryEntry:
    install_id: str
    display_name: str
    install_dir: str
    display_icon: str = ""


def _reg_str(key: object, name: str) -> str:
    import winreg

    try:
        val, _ = winreg.QueryValueEx(key, name)
        return val.strip() if isinstance(val, str) else ""
    except OSError:
        return ""


def _read_ubisoft_registry() -> tuple[UbisoftRegistryEntry, ...]:
    if os.name != "nt":
        return ()
    import winreg

    uninstall_meta: dict[str, tuple[str, str]] = {}
    for uninst_sub in (
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, uninst_sub, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for idx in range(min(count, _MAX_ENTRIES)):
                    try:
                        kn = winreg.EnumKey(root, idx)
                    except OSError:
                        break
                    if not kn.startswith("Uplay Install "):
                        continue
                    uid = kn.removeprefix("Uplay Install ").strip()
                    if not _INSTALL_ID_RE.fullmatch(uid):
                        continue
                    try:
                        with winreg.OpenKey(root, kn, 0, winreg.KEY_READ) as sk:
                            dn = _reg_str(sk, "DisplayName")
                            icon = _reg_str(sk, "DisplayIcon")
                            if dn:
                                uninstall_meta[uid] = (dn, icon)
                    except OSError:
                        continue
        except OSError:
            continue

    entries: dict[str, UbisoftRegistryEntry] = {}
    for sub in (
        r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs",
        r"SOFTWARE\Ubisoft\Launcher\Installs",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for idx in range(min(count, _MAX_ENTRIES)):
                    try:
                        uid = winreg.EnumKey(root, idx)
                    except OSError:
                        break
                    if not _INSTALL_ID_RE.fullmatch(uid):
                        continue
                    try:
                        with winreg.OpenKey(root, uid, 0, winreg.KEY_READ) as sk:
                            install_dir = _reg_str(sk, "InstallDir")
                            if not install_dir:
                                continue
                            dn, icon = uninstall_meta.get(uid, ("", ""))
                            if not dn:
                                dn = Path(install_dir.rstrip("\\/")).name
                            entries.setdefault(uid, UbisoftRegistryEntry(uid, dn, install_dir, icon))
                    except OSError:
                        continue
        except OSError:
            continue

    return tuple(entries.values())


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


class UbisoftDetector:
    source = GameSource.UBISOFT

    def __init__(
        self,
        *,
        registry_provider: Callable[[], Iterable[UbisoftRegistryEntry]] | None = None,
    ) -> None:
        self._registry_provider = (
            registry_provider if registry_provider is not None else _read_ubisoft_registry
        )

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        try:
            entries = tuple(self._registry_provider())
        except OSError:
            return DiscoveryBatch((), "partial", ("ubisoft_registry_unreadable",))

        if not entries:
            return DiscoveryBatch((), "unavailable", ())

        for entry in entries:
            uid = entry.install_id.strip()
            dn = entry.display_name.strip()
            if not _INSTALL_ID_RE.fullmatch(uid) or not dn or len(dn) > 256 or not dn.isprintable():
                continue
            install_dir = local_path(entry.install_dir)
            if install_dir is None or not install_dir.is_dir():
                continue
            exe = _pick_exe(install_dir, entry.display_icon)
            targets = (GameTarget("exe_path", os.path.normcase(str(exe))),) if exe is not None else ()
            cover: Path | None = None
            for name in _COVER_NAMES:
                found = contained_file(install_dir, name)
                if found is not None:
                    cover = found
                    break
            launch = LaunchTarget("ubisoft_uri", f"uplay://launch/{uid}/0")
            games[uid] = DetectedGame(
                GameSource.UBISOFT, uid, dn, install_dir, cover, launch, targets
            )

        state = "partial" if diagnostics else "complete"
        return DiscoveryBatch(tuple(games.values()), state, tuple(sorted(diagnostics)))
