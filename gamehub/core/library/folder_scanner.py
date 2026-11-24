"""Depth-bounded, symlink-safe folder scanner and persistent FolderDetector."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from gamehub.core.storage.library import LibraryRepository

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

MAX_SCAN_DEPTH = 4
MAX_SCAN_ENTRIES = 8192

_HELPER_PREFIXES = (
    "unins",
    "uninstall",
    "crash",
    "bugsplat",
    "ue4prereq",
    "ue5prereq",
    "ueprereq",
    "vcredist",
    "vc_redist",
    "dxsetup",
    "directx",
    "dotnet",
    "ndp",
    "physx",
    "openal",
    "oalinst",
    "launcher",
    "updater",
    "patcher",
    "setup",
    "install",
    "redist",
    "bootstrap",
    "easyanticheat",
    "beservice",
    "battleye",
    "vgc",
    "eaanticheat",
    "eac_",
    "be_",
    "ffmpeg",
    "7z",
)
_HELPER_SUBSTRINGS = (
    "crashhandler",
    "crashreporter",
    "crashpad",
    "uninstaller",
    "vcredist",
    "prereq",
    "easyanticheat",
    "battleye",
    "eaanticheat",
    "webhelper",
    "cefsubprocess",
    "redistributable",
    "dxwebsetup",
    "dotnetfx",
)
_SKIP_DIR_NAMES = {
    "_commonredist",
    "redist",
    "__installer",
    "directx",
    "vcredist",
    "easyanticheat",
    "battleye",
    "support",
    "prereq",
    "prerequisites",
    "crashreportclient",
}
_GENERIC_EXE_STEMS = {
    "game",
    "play",
    "start",
    "client",
    "win64",
    "win32",
    "shipping",
    "main",
    "app",
    "application",
}
_COVER_NAMES = (
    "header.jpg",
    "cover.jpg",
    "cover.png",
    "cover.webp",
    "banner.jpg",
    "boxart.jpg",
    "boxart.png",
)


@dataclass(frozen=True, slots=True)
class FolderCandidate:
    exe_path: Path
    folder_path: Path
    suggested_name: str
    previous_decision: str | None = None  # "include" | "ignore" | None


def is_helper_executable(exe: Path) -> bool:
    stem = exe.stem.casefold()
    if not stem:
        return True
    if stem.startswith(_HELPER_PREFIXES):
        return True
    return any(sub in stem for sub in _HELPER_SUBSTRINGS)


def suggest_game_name(folder_root: Path, exe_path: Path) -> str:
    """Pick a clean human-readable title from the game's subfolder or executable stem."""
    try:
        rel = exe_path.relative_to(folder_root)
    except ValueError:
        return exe_path.stem

    stem = exe_path.stem
    parts = rel.parts
    # If nested inside a game subfolder (e.g. D:\Games\Hollow Knight\hollow_knight.exe or Binaries\Win64\Foo-Win64-Shipping.exe)
    if len(parts) >= 2:
        top_folder = parts[0].strip()
        if top_folder and (
            stem.casefold() in _GENERIC_EXE_STEMS
            or stem.casefold().endswith("-win64-shipping")
            or stem.casefold().endswith("-win32-shipping")
            or len(parts) >= 3
        ):
            return top_folder
        if top_folder:
            return top_folder
    return stem.replace("_", " ").strip() or exe_path.stem


def _is_safe_non_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return not bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def scan_folder_candidates(
    folder: Path,
    *,
    existing_choices: dict[str, tuple[str, str | None]] | None = None,
    known_exe_keys: set[str] | None = None,
    include_ignored: bool = False,
    max_depth: int = MAX_SCAN_DEPTH,
) -> tuple[FolderCandidate, ...]:
    """Safely scan a local folder for candidate game executables."""
    root = local_path(folder)
    if root is None or not root.is_dir():
        raise ValueError("Select an accessible local folder.")

    choices = existing_choices or {}
    known = known_exe_keys or set()
    candidates: list[FolderCandidate] = []
    visited_entries = 0

    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and visited_entries < MAX_SCAN_ENTRIES:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                children = sorted(it, key=lambda e: e.name.casefold())
        except OSError:
            continue

        subdirs: list[Path] = []
        for entry in children:
            visited_entries += 1
            if visited_entries > MAX_SCAN_ENTRIES:
                break
            entry_path = Path(entry.path)
            if not _is_safe_non_reparse(entry_path):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth and entry.name.casefold() not in _SKIP_DIR_NAMES:
                        subdirs.append(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue

            if entry_path.suffix.lower() != ".exe":
                continue
            if is_helper_executable(entry_path):
                continue

            norm_key = os.path.normcase(str(entry_path))
            if norm_key in known:
                continue

            prev = choices.get(norm_key)
            prev_decision = prev[0] if prev is not None else None
            prev_name = prev[1] if prev is not None else None
            if prev_decision == "ignore" and not include_ignored:
                continue

            name = prev_name.strip() if prev_name and prev_name.strip() else suggest_game_name(root, entry_path)
            candidates.append(
                FolderCandidate(
                    exe_path=entry_path,
                    folder_path=root,
                    suggested_name=name,
                    previous_decision=prev_decision,
                )
            )

        for sd in reversed(subdirs):
            stack.append((sd, depth + 1))

    candidates.sort(key=lambda c: (c.suggested_name.casefold(), str(c.exe_path).casefold()))
    return tuple(candidates)


def _find_local_cover(exe_path: Path, folder_root: Path) -> Path | None:
    search_dirs = [exe_path.parent]
    try:
        rel = exe_path.relative_to(folder_root)
        if len(rel.parts) >= 2:
            top_dir = folder_root / rel.parts[0]
            if top_dir != exe_path.parent and top_dir.is_dir():
                search_dirs.append(top_dir)
    except ValueError:
        pass
    for directory in search_dirs:
        for name in _COVER_NAMES:
            found = contained_file(directory, name)
            if found is not None:
                return found
    return None


def _folder_source_id(exe_path: Path) -> str:
    norm = os.path.normcase(str(exe_path))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]


class FolderDetector:
    """Reconcile user-approved executables from saved Scan Folders."""

    source = GameSource.FOLDER

    def __init__(self, repository: LibraryRepository) -> None:
        self._repository = repository

    def discover(self) -> DiscoveryBatch:
        folders = self._repository.list_scan_folders()
        if not folders:
            return DiscoveryBatch((), "complete", ())

        games: dict[str, DetectedGame] = {}
        for folder in folders:
            root = local_path(folder)
            if root is None or not root.is_dir():
                continue
            choices = self._repository.list_scan_choices(folder)
            for norm_exe, (decision, custom_name) in choices.items():
                if decision != "include":
                    continue
                exe = local_path(norm_exe)
                if exe is None or not exe.is_file() or exe.suffix.lower() != ".exe":
                    continue
                if not _is_safe_non_reparse(exe):
                    continue
                name = (
                    custom_name.strip()
                    if custom_name and custom_name.strip()
                    else suggest_game_name(root, exe)
                )
                sid = _folder_source_id(exe)
                games[sid] = DetectedGame(
                    source=GameSource.FOLDER,
                    source_id=sid,
                    name=name,
                    install_dir=exe.parent,
                    cover_path=_find_local_cover(exe, root),
                    launch_target=LaunchTarget("exe", str(exe)),
                    targets=(GameTarget("exe_path", os.path.normcase(str(exe))),),
                )

        return DiscoveryBatch(tuple(games.values()), "complete", ())
