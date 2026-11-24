"""Read-only itch.io (butler.db) game detector."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_MAX_ENTRIES = 4096
_HELPER_PREFIXES = ("unins", "crash", "setup", "redist", "vcredist", "dxsetup", "updater")
_COVER_NAMES = ("header.jpg", "cover.jpg", "cover.png", "cover.webp", "banner.jpg")


def _default_butler_db() -> Path:
    appdata = Path(os.environ.get("APPDATA", ""))
    return appdata / "itch" / "db" / "butler.db"


def _pick_exe(install_dir: Path, verdict_json: str | None = None) -> Path | None:
    if verdict_json:
        try:
            verdict = json.loads(verdict_json)
            candidates = verdict.get("candidates") if isinstance(verdict, dict) else None
            if isinstance(candidates, list):
                for item in candidates:
                    rel = item.get("path") if isinstance(item, dict) else None
                    if isinstance(rel, str) and rel.lower().endswith(".exe"):
                        safe = contained_file(install_dir, rel)
                        if safe is not None:
                            return safe
        except (ValueError, TypeError):
            pass
    try:
        exes: list[Path] = []
        for idx, child in enumerate(install_dir.iterdir()):
            if idx >= 128:
                break
            if child.suffix.lower() != ".exe":
                continue
            if child.stem.casefold().startswith(_HELPER_PREFIXES):
                continue
            safe = contained_file(install_dir, child.name)
            if safe is not None:
                exes.append(safe)
        if len(exes) == 1:
            return exes[0]
    except OSError:
        return None
    return None


class ItchDetector:
    source = GameSource.ITCH

    def __init__(self, butler_db_path: Path | None = None) -> None:
        self._db_path = butler_db_path if butler_db_path is not None else _default_butler_db()

    def discover(self) -> DiscoveryBatch:
        db_file = local_path(self._db_path)
        if db_file is None or not db_file.is_file():
            return DiscoveryBatch((), "unavailable", ())

        games: dict[str, DetectedGame] = {}
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
                if not {"caves", "games"}.issubset(tables):
                    return DiscoveryBatch((), "complete", ())

                cols = {
                    row[1] for row in conn.execute("PRAGMA table_info(caves)").fetchall()
                }
                has_locs = "install_locations" in tables and "install_location_id" in cols
                verdict_col = "c.verdict_json" if "verdict_json" in cols else "NULL AS verdict_json"
                if has_locs and "install_folder_name" in cols:
                    query = (
                        f"SELECT c.id AS cave_id, g.id AS game_id, g.title AS title, "
                        f"l.path AS base_path, c.install_folder_name AS folder_name, {verdict_col} "
                        f"FROM caves c "
                        f"JOIN games g ON g.id = c.game_id "
                        f"JOIN install_locations l ON l.id = c.install_location_id"
                    )
                elif "install_folder_name" in cols:
                    query = (
                        f"SELECT c.id AS cave_id, g.id AS game_id, g.title AS title, "
                        f"NULL AS base_path, c.install_folder_name AS folder_name, {verdict_col} "
                        f"FROM caves c JOIN games g ON g.id = c.game_id"
                    )
                else:
                    return DiscoveryBatch((), "complete", ())

                rows = conn.execute(query).fetchall()
                for row in rows[:_MAX_ENTRIES]:
                    title = str(row["title"] or "").strip()
                    folder_name = str(row["folder_name"] or "").strip()
                    base_path = row["base_path"]
                    if not title or len(title) > 256 or not title.isprintable() or not folder_name:
                        continue
                    raw_dir = Path(base_path) / folder_name if base_path else Path(folder_name)
                    install_dir = local_path(raw_dir)
                    if install_dir is None or not install_dir.is_dir():
                        continue
                    source_id = str(row["cave_id"] or row["game_id"])
                    exe = _pick_exe(install_dir, row["verdict_json"])
                    targets = (
                        (GameTarget("exe_path", os.path.normcase(str(exe))),)
                        if exe is not None
                        else ()
                    )
                    launch = LaunchTarget("exe", str(exe)) if exe is not None else None
                    cover: Path | None = None
                    for name in _COVER_NAMES:
                        found = contained_file(install_dir, name)
                        if found is not None:
                            cover = found
                            break
                    games[source_id] = DetectedGame(
                        GameSource.ITCH,
                        source_id,
                        title,
                        install_dir,
                        cover,
                        launch,
                        targets,
                    )
        except sqlite3.Error:
            return DiscoveryBatch((), "partial", ("itch_database_unreadable",))

        return DiscoveryBatch(tuple(games.values()), "complete", ())
