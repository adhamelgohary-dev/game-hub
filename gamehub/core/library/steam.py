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


def _read_game(path: Path, app_id: str, steamapps: Path) -> DetectedGame | None:
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
    return DetectedGame(
        GameSource.STEAM,
        app_id,
        name.strip(),
        directory,
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
                            game = _read_game(manifest, match[1], directory)
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
