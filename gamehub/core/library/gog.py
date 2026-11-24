"""Read-only GOG Galaxy and standalone GOG game detector."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_GAME_ID_RE = re.compile(r"[0-9]{1,16}\Z")
_MAX_ENTRIES = 4096
_COVER_NAMES = (
    "header.jpg",
    "cover.jpg",
    "cover.png",
    "cover.webp",
    "banner.jpg",
)


@dataclass(frozen=True, slots=True)
class GogRegistryEntry:
    game_id: str
    name: str
    install_dir: str
    exe_path: str = ""


def _reg_str(key: object, name: str) -> str:
    import winreg

    try:
        val, _ = winreg.QueryValueEx(key, name)
        return val.strip() if isinstance(val, str) else ""
    except OSError:
        return ""


def _read_gog_registry() -> tuple[GogRegistryEntry, ...]:
    if os.name != "nt":
        return ()
    import winreg

    entries: dict[str, GogRegistryEntry] = {}
    roots = (
        r"SOFTWARE\WOW6432Node\GOG.com\Games",
        r"SOFTWARE\GOG.com\Games",
    )
    for sub in roots:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for idx in range(min(count, _MAX_ENTRIES)):
                    try:
                        key_name = winreg.EnumKey(root, idx)
                    except OSError:
                        break
                    if not _GAME_ID_RE.fullmatch(key_name):
                        continue
                    try:
                        with winreg.OpenKey(root, key_name, 0, winreg.KEY_READ) as sk:
                            gid = _reg_str(sk, "gameID") or key_name
                            name = _reg_str(sk, "gameName")
                            path = _reg_str(sk, "path")
                            exe = _reg_str(sk, "exe")
                            if gid and name and path and _GAME_ID_RE.fullmatch(gid):
                                entries.setdefault(gid, GogRegistryEntry(gid, name, path, exe))
                    except OSError:
                        continue
        except OSError:
            continue
    return tuple(entries.values())


def _find_gog_cover(install_dir: Path, game_id: str) -> Path | None:
    for name in _COVER_NAMES:
        found = contained_file(install_dir, name)
        if found is not None:
            return found
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".ico"):
        found = contained_file(install_dir, f"goggame-{game_id}{ext}")
        if found is not None:
            return found
    return None


class GogDetector:
    source = GameSource.GOG

    def __init__(
        self,
        galaxy_db_path: Path | None = None,
        *,
        registry_provider: Callable[[], Iterable[GogRegistryEntry]] | None = None,
    ) -> None:
        pd = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        self._explicit_db = galaxy_db_path is not None
        self._db_path = (
            galaxy_db_path
            if galaxy_db_path is not None
            else pd / "GOG.com" / "Galaxy" / "storage" / "galaxy-2.0.db"
        )
        if registry_provider is not None:
            self._registry_provider: Callable[[], Iterable[GogRegistryEntry]] | None = (
                registry_provider
            )
        elif not self._explicit_db:
            self._registry_provider = _read_gog_registry
        else:
            self._registry_provider = None

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        db_file = local_path(self._db_path)
        galaxy_present = db_file is not None and db_file.is_file()

        if galaxy_present and db_file is not None:
            self._read_galaxy_db(db_file, games, diagnostics)

        reg_found = False
        if self._registry_provider is not None:
            try:
                for entry in self._registry_provider():
                    game = self._from_registry_entry(entry, galaxy_present=galaxy_present)
                    if game is not None:
                        reg_found = True
                        if game.source_id in games:
                            existing = games[game.source_id]
                            if not existing.targets and game.targets:
                                games[game.source_id] = DetectedGame(
                                    existing.source,
                                    existing.source_id,
                                    existing.name,
                                    existing.install_dir,
                                    existing.cover_path or game.cover_path,
                                    existing.launch_target or game.launch_target,
                                    game.targets,
                                )
                        else:
                            games[game.source_id] = game
            except OSError:
                diagnostics.add("gog_registry_unreadable")

        if not galaxy_present and not reg_found and not games and not diagnostics:
            return DiscoveryBatch((), "unavailable", ())
        state = "partial" if diagnostics else "complete"
        return DiscoveryBatch(tuple(games.values()), state, tuple(sorted(diagnostics)))

    def _read_galaxy_db(
        self,
        db_file: Path,
        games: dict[str, DetectedGame],
        diagnostics: set[str],
    ) -> None:
        uri = f"{db_file.absolute().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as conn:
                conn.row_factory = sqlite3.Row
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                if "InstalledBaseProducts" not in tables:
                    return
                title_map: dict[str, str] = {}
                if "LimitedDetails" in tables:
                    try:
                        for row in conn.execute(
                            "SELECT productId, title FROM LimitedDetails WHERE title IS NOT NULL"
                        ):
                            pid = str(row["productId"]).strip()
                            title = str(row["title"]).strip()
                            if pid and title:
                                title_map[pid] = title
                    except sqlite3.Error:
                        pass
                rows = conn.execute(
                    "SELECT productId, installationPath FROM InstalledBaseProducts"
                ).fetchall()
                for row in rows[:_MAX_ENTRIES]:
                    pid = str(row["productId"]).strip()
                    raw_path = row["installationPath"]
                    if not _GAME_ID_RE.fullmatch(pid) or not isinstance(raw_path, str):
                        continue
                    install_dir = local_path(raw_path)
                    if install_dir is None or not install_dir.is_dir():
                        continue
                    title = title_map.get(pid) or install_dir.name
                    if not title or len(title) > 256 or not title.isprintable():
                        continue
                    cover = _find_gog_cover(install_dir, pid)
                    launch = LaunchTarget("gog_uri", f"goggalaxy://openGameView/{pid}")
                    games[pid] = DetectedGame(
                        GameSource.GOG,
                        pid,
                        title,
                        install_dir,
                        cover,
                        launch,
                        (),
                    )
        except sqlite3.Error:
            diagnostics.add("gog_database_unreadable")

    def _from_registry_entry(
        self, entry: GogRegistryEntry, *, galaxy_present: bool
    ) -> DetectedGame | None:
        gid = entry.game_id.strip()
        name = entry.name.strip()
        if not _GAME_ID_RE.fullmatch(gid) or not name or len(name) > 256 or not name.isprintable():
            return None
        install_dir = local_path(entry.install_dir)
        if install_dir is None or not install_dir.is_dir():
            return None
        targets: tuple[GameTarget, ...] = ()
        exe_file: Path | None = None
        if entry.exe_path:
            cand = local_path(entry.exe_path)
            if cand is not None and cand.is_file() and cand.suffix.lower() == ".exe":
                exe_file = cand
                targets = (GameTarget("exe_path", os.path.normcase(str(cand))),)
        if galaxy_present:
            launch: LaunchTarget | None = LaunchTarget("gog_uri", f"goggalaxy://openGameView/{gid}")
        elif exe_file is not None:
            launch = LaunchTarget("exe", str(exe_file))
        else:
            launch = None
        cover = _find_gog_cover(install_dir, gid)
        return DetectedGame(GameSource.GOG, gid, name, install_dir, cover, launch, targets)
