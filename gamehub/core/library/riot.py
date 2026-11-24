"""Read-only Riot Client game detector (Valorant, League of Legends, TFT)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_RIOT_UNINSTALL_PREFIX = "Riot Game "
_RIOT_PRODUCT_RE = re.compile(r"([a-z0-9_-]+)\.([a-z0-9_-]+)\Z", re.IGNORECASE)
_PRODUCT_NAMES = {
    "valorant": "VALORANT",
    "league_of_legends": "League of Legends",
    "teamfighttactics": "Teamfight Tactics",
    "bacon": "Legends of Runeterra",
    "lion": "2XKO",
}
_PRODUCT_MAIN_EXES = {
    "valorant": (
        r"ShooterGame\Binaries\Win64\VALORANT-Win64-Shipping.exe",
        "VALORANT.exe",
    ),
    "league_of_legends": (
        r"Game\League of Legends.exe",
        "LeagueClient.exe",
    ),
}


@dataclass(frozen=True, slots=True)
class RiotUninstallEntry:
    key_name: str
    display_name: str
    install_location: str
    display_icon: str = ""
    uninstall_string: str = ""


def _read_hkcu_riot_entries() -> tuple[RiotUninstallEntry, ...]:
    if os.name != "nt":
        return ()
    import winreg

    out: list[RiotUninstallEntry] = []
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_READ) as root:
            count = winreg.QueryInfoKey(root)[0]
            for idx in range(min(count, 4096)):
                try:
                    key_name = winreg.EnumKey(root, idx)
                except OSError:
                    break
                if not key_name.startswith(_RIOT_UNINSTALL_PREFIX):
                    continue
                if "riot_client" in key_name.lower():
                    continue
                try:
                    with winreg.OpenKey(root, key_name, 0, winreg.KEY_READ) as sk:
                        dn = _reg_str(sk, "DisplayName")
                        loc = _reg_str(sk, "InstallLocation")
                        icon = _reg_str(sk, "DisplayIcon")
                        uninst = _reg_str(sk, "UninstallString")
                        if dn and loc:
                            out.append(RiotUninstallEntry(key_name, dn, loc, icon, uninst))
                except OSError:
                    continue
    except OSError:
        return ()
    return tuple(out)


def _reg_str(key: object, name: str) -> str:
    import winreg

    try:
        val, _ = winreg.QueryValueEx(key, name)
        return val.strip() if isinstance(val, str) else ""
    except OSError:
        return ""


class RiotDetector:
    source = GameSource.RIOT

    def __init__(
        self,
        program_data_root: Path | None = None,
        *,
        registry_provider: Callable[[], Iterable[RiotUninstallEntry]] | None = None,
    ) -> None:
        default_pd = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Riot Games"
        self._explicit_root = program_data_root is not None
        self._root = program_data_root if program_data_root is not None else default_pd
        if registry_provider is not None:
            self._registry_provider: Callable[[], Iterable[RiotUninstallEntry]] | None = (
                registry_provider
            )
        elif not self._explicit_root:
            self._registry_provider = _read_hkcu_riot_entries
        else:
            self._registry_provider = None

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        installs_file = local_path(self._root / "RiotClientInstalls.json")
        client_exe: Path | None = None
        associated_dirs: dict[str, Path] = {}

        if installs_file is not None and installs_file.is_file():
            try:
                data = json.loads(installs_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key in ("rc_live", "rc_default"):
                        raw = data.get(key)
                        if isinstance(raw, str):
                            cand = local_path(raw)
                            if cand is not None and cand.is_file():
                                client_exe = cand
                                break
                    assoc = data.get("associated_client")
                    if isinstance(assoc, dict):
                        for game_path_str, rc_path_str in assoc.items():
                            gp = local_path(game_path_str)
                            if gp is not None and gp.is_dir():
                                associated_dirs[os.path.normcase(str(gp))] = gp
                                if client_exe is None and isinstance(rc_path_str, str):
                                    rc = local_path(rc_path_str)
                                    if rc is not None and rc.is_file():
                                        client_exe = rc
            except (OSError, ValueError, TypeError):
                diagnostics.add("riot_installs_unreadable")

        # 1. Registry uninstall entries (authoritative product + patchline + install dir + display name)
        if self._registry_provider is not None:
            try:
                for entry in self._registry_provider():
                    game = self._from_uninstall_entry(entry, client_exe)
                    if game is not None:
                        games.setdefault(game.source_id, game)
            except OSError:
                diagnostics.add("riot_registry_unreadable")

        # 2. Fallback from RiotClientInstalls.json associated_client paths (e.g. fixtures/portable)
        for gp in associated_dirs.values():
            parent_name = gp.parent.name.casefold()
            if parent_name == "valorant":
                source_id = "valorant.live"
                product, patchline = "valorant", "live"
            elif "league" in parent_name:
                source_id = "league_of_legends.live"
                product, patchline = "league_of_legends", "live"
            else:
                continue
            if source_id in games:
                continue
            cover = self._find_cover(source_id)
            launch = (
                LaunchTarget("riot_client", f"{client_exe}|{product}|{patchline}")
                if client_exe is not None
                else None
            )
            targets = self._targets_for_product(product, gp)
            games[source_id] = DetectedGame(
                GameSource.RIOT,
                source_id,
                _PRODUCT_NAMES.get(product, product.title()),
                gp,
                cover,
                launch,
                targets,
            )

        if not games and not diagnostics and (installs_file is None or not installs_file.is_file()):
            return DiscoveryBatch((), "unavailable", ())
        return DiscoveryBatch(
            tuple(games.values()), "partial" if diagnostics else "complete", tuple(sorted(diagnostics))
        )

    def _from_uninstall_entry(
        self, entry: RiotUninstallEntry, default_client: Path | None
    ) -> DetectedGame | None:
        install_dir = local_path(entry.install_location)
        if install_dir is None or not install_dir.is_dir():
            return None
        token = entry.key_name.removeprefix(_RIOT_UNINSTALL_PREFIX).strip()
        match = _RIOT_PRODUCT_RE.fullmatch(token)
        if match is None:
            return None
        product = match.group(1).lower()
        patchline = match.group(2).lower()
        source_id = f"{product}.{patchline}"

        client_exe = default_client
        if client_exe is None and entry.uninstall_string:
            raw_cmd = entry.uninstall_string.strip()
            if raw_cmd.startswith('"'):
                exe_str = raw_cmd.split('"', 2)[1]
            else:
                exe_str = raw_cmd.split(" ", 1)[0]
            cand = local_path(exe_str)
            if cand is not None and cand.is_file():
                client_exe = cand

        launch = (
            LaunchTarget("riot_client", f"{client_exe}|{product}|{patchline}")
            if client_exe is not None
            else None
        )
        cover: Path | None = None
        if entry.display_icon:
            ic = local_path(entry.display_icon.split(",", 1)[0].strip().strip('"'))
            if ic is not None and ic.is_file() and ic.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ico"}:
                cover = ic
        if cover is None:
            cover = self._find_cover(source_id)

        targets = self._targets_for_product(product, install_dir)
        return DetectedGame(
            GameSource.RIOT,
            source_id,
            entry.display_name.strip(),
            install_dir,
            cover,
            launch,
            targets,
        )

    def _find_cover(self, source_id: str) -> Path | None:
        meta_dir = local_path(self._root / "Metadata" / source_id)
        if meta_dir is None or not meta_dir.is_dir():
            return None
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".ico"):
            cand = contained_file(meta_dir, f"{source_id}{ext}")
            if cand is not None:
                return cand
        return None

    def _targets_for_product(self, product: str, install_dir: Path) -> tuple[GameTarget, ...]:
        targets: list[GameTarget] = []
        for rel in _PRODUCT_MAIN_EXES.get(product, ()):
            found = contained_file(install_dir, rel)
            if found is not None:
                targets.append(GameTarget("exe_path", os.path.normcase(str(found))))
        return tuple(targets)
