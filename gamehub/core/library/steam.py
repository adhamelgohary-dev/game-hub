"""Read the local Steam library and game manifests."""

import os
import re
import winreg
from pathlib import Path

import vdf

from gamehub.core.library.models import (
    DetectedGame,
    DiscoveryBatch,
    GameSource,
    GameTarget,
    LaunchTarget,
)
from gamehub.core.library.paths import contained_file, local_path

MANIFEST_NAME = re.compile(r"appmanifest_([0-9]{1,10})\.acf\Z", re.IGNORECASE)
MAX_VDF_BYTES = 2 * 1024 * 1024
MAX_LIBRARIES = 64
MAX_ENTRIES = 4096
HELPER_PREFIXES = ("crash", "unins", "setup", "install", "redist", "steamerror", "dxsetup")


def _read_vdf(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(MAX_VDF_BYTES + 1)
    if len(data) > MAX_VDF_BYTES:
        raise ValueError("Steam metadata exceeds the size limit")
    return vdf.loads(data.decode("utf-8-sig"))


def _steam_home() -> Path | None:
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath", 0),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", "InstallPath", winreg.KEY_WOW64_32KEY),
    )
    for hive, key, name, view in keys:
        try:
            with winreg.OpenKey(hive, key, access=winreg.KEY_READ | view) as registry:
                value, _ = winreg.QueryValueEx(registry, name)
            path = local_path(value) if isinstance(value, str) else None
            if path is not None and path.is_dir():
                return path
        except OSError:
            continue

    program_files = os.environ.get("ProgramFiles(x86)")
    if program_files:
        candidate = local_path(Path(program_files) / "Steam")
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def _is_unmounted_windows_drive(raw_path: str) -> bool:
    if os.name != "nt":
        return False
    p = Path(raw_path)
    if not p.is_absolute() or len(p.anchor) != 3 or p.anchor[1:] != ":\\" or not p.anchor[0].isalpha():
        return False
    import ctypes

    # Skip offline/disconnected/removable/mapped-network drive letters in libraryfolders.vdf
    # (DRIVE_NO_ROOT_DIR=1, DRIVE_REMOVABLE=2, DRIVE_REMOTE=4, DRIVE_CDROM=5) without failing scan.
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(p.anchor))
    return drive_type in {1, 2, 4, 5}


def _library_paths(path: Path) -> tuple[list[Path], bool]:
    entries = _read_vdf(path).get("libraryfolders")
    if not isinstance(entries, dict):
        raise TypeError("Steam library folders missing")
    libraries = []
    invalid = False
    for key, value in entries.items():
        if key.isascii() and key.isdecimal():
            if len(libraries) == MAX_LIBRARIES:
                return libraries, True
            raw_path = value.get("path") if isinstance(value, dict) else value
            if isinstance(raw_path, str) and _is_unmounted_windows_drive(raw_path):
                # Unmounted external/secondary drive in Steam's VDF is normal; skip cleanly.
                continue
            try:
                library = local_path(raw_path) if isinstance(raw_path, str) else None
            except OSError:
                library = None
            if library is None:
                invalid = True
            else:
                libraries.append(library)
    return libraries, invalid


def _single_executable(directory: Path) -> Path | None:
    candidates = []
    for index, child in enumerate(directory.iterdir()):
        if index == MAX_ENTRIES:
            return None
        if child.suffix.casefold() != ".exe" or child.stem.casefold().startswith(HELPER_PREFIXES):
            continue
        executable = contained_file(directory, child.name)
        if executable is not None:
            candidates.append(executable)
        if len(candidates) > 1:
            return None
    return candidates[0] if candidates else None


_WIDE_COVER_CANDIDATES = (
    "header.jpg",
    "library_header.jpg",
    "library_hero.jpg",
    "header.png",
    "library_header.png",
    "library_hero.png",
)
_VERTICAL_COVER_CANDIDATES = (
    "library_capsule.jpg",
    "library_600x900.jpg",
    "library_capsule.png",
    "library_600x900.png",
)


def _search_cover_names(
    cache_dir: Path,
    app_id: str,
    app_dir: Path | None,
    hashed_dirs: list[Path],
    candidates: tuple[str, ...],
) -> Path | None:
    # 1. Flat layout: librarycache/<appid>_<name>
    for name in candidates:
        found = contained_file(cache_dir, f"{app_id}_{name}")
        if found is not None:
            return found
    if app_dir is None:
        return None
    # 2. Direct per-AppID folder: librarycache/<appid>/<name>
    for name in candidates:
        found = contained_file(app_dir, name)
        if found is not None:
            return found
    # 3. Hashed subdirectories: librarycache/<appid>/<hash>/<name>
    for sub in hashed_dirs:
        for name in candidates:
            found = contained_file(sub, name)
            if found is not None:
                return found
    return None


def _find_cover(steam_home: Path, app_id: str) -> Path | None:
    """Locate Steam's locally cached cover art (landscape-first) without network calls."""
    cache_dir = local_path(steam_home / "appcache" / "librarycache")
    if cache_dir is None or not cache_dir.is_dir():
        return None

    app_dir = local_path(cache_dir / app_id)
    if app_dir is not None and not app_dir.is_dir():
        app_dir = None

    hashed_dirs: list[Path] = []
    fallback: Path | None = None
    if app_dir is not None:
        try:
            for index, child in enumerate(app_dir.iterdir()):
                if index >= 64:
                    break
                if child.is_dir():
                    hashed_dirs.append(child)
                elif (
                    fallback is None
                    and child.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}
                    and "blur" not in child.stem.casefold()
                    and child.stem.casefold() != "logo"
                ):
                    safe = contained_file(app_dir, child.name)
                    if safe is not None:
                        fallback = safe
        except OSError:
            pass

    # Pass 1: Landscape / wide assets first across flat, nested, and hashed layouts.
    wide = _search_cover_names(cache_dir, app_id, app_dir, hashed_dirs, _WIDE_COVER_CANDIDATES)
    if wide is not None:
        return wide

    # Pass 2: Fall back to vertical capsule assets only when no wide cover exists.
    vertical = _search_cover_names(
        cache_dir, app_id, app_dir, hashed_dirs, _VERTICAL_COVER_CANDIDATES
    )
    if vertical is not None:
        return vertical

    return fallback


def _read_game(
    path: Path, app_id: str, steamapps: Path, *, steam_home: Path | None = None
) -> DetectedGame | None:
    manifest = _read_vdf(path).get("AppState")
    if not isinstance(manifest, dict) or manifest.get("appid") != app_id:
        raise ValueError("Steam application ID mismatch")
    name = manifest.get("name")
    folder = manifest.get("installdir")
    flags = manifest.get("StateFlags", "4")
    if not isinstance(name, str) or not name.strip() or len(name) > 512:
        raise ValueError("Steam title is invalid")
    if (
        not isinstance(folder, str) or len(folder) > 255
        or any(mark in folder for mark in ("/", "\\", ":")) or folder in ("", ".", "..")
    ):
        raise ValueError("Steam installation name is invalid")
    if not isinstance(flags, str) or not flags.isascii() or not flags.isdecimal() or len(flags) > 10:
        raise ValueError("Steam installation state is invalid")
    if not int(flags) & 4 or app_id == "228980":
        return None
    directory = local_path(steamapps / "common" / folder)
    if directory is None or not directory.is_dir():
        return None
    executable = _single_executable(directory)
    targets = (GameTarget("exe_path", os.path.normcase(str(executable))),) if executable else ()
    cover_path = _find_cover(steam_home, app_id) if steam_home is not None else None
    return DetectedGame(
        GameSource.STEAM,
        app_id,
        name.strip(),
        directory,
        cover_path=cover_path,
        launch_target=LaunchTarget("steam_uri", f"steam://rungameid/{app_id}"),
        targets=targets,
    )


class SteamDetector:
    source = GameSource.STEAM

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics = set()
        try:
            home = local_path(self._root) if self._root is not None else _steam_home()
            if home is None or not home.is_dir():
                return DiscoveryBatch(state="unavailable", diagnostics=("steam_missing",))
            libraries = [home]
            index = contained_file(home, r"steamapps\libraryfolders.vdf")
            if index is not None:
                try:
                    extra_libraries, invalid = _library_paths(index)
                    libraries.extend(extra_libraries)
                    if invalid:
                        diagnostics.add("steam_index_invalid")
                except (OSError, ValueError, TypeError, SyntaxError, OverflowError, RecursionError):
                    diagnostics.add("steam_index_invalid")
            else:
                diagnostics.add("steam_index_missing")

            for library in dict.fromkeys(libraries):
                try:
                    directory = local_path(library / "steamapps")
                    if directory is None:
                        raise ValueError("Unsafe Steam library")
                    for index, path in enumerate(directory.iterdir()):
                        if index == MAX_ENTRIES:
                            diagnostics.add("steam_manifest_limit")
                            break
                        match = MANIFEST_NAME.fullmatch(path.name)
                        if match is None:
                            continue
                        try:
                            manifest = contained_file(directory, path.name)
                            if manifest is None:
                                raise ValueError("Unsafe Steam manifest")
                            game = _read_game(manifest, match[1], directory, steam_home=home)
                            if game is not None:
                                games.setdefault(game.source_id, game)
                        except (OSError, ValueError, SyntaxError, OverflowError, RecursionError):
                            diagnostics.add("steam_manifest_invalid")
                except (OSError, ValueError):
                    diagnostics.add("steam_library_unavailable")
        except OSError:
            return DiscoveryBatch(state="unavailable", diagnostics=("steam_library_unavailable",))

        return DiscoveryBatch(
            tuple(games.values()), "partial" if diagnostics else "complete", tuple(sorted(diagnostics))
        )
