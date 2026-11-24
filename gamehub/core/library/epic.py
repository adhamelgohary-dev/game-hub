"""Discover locally installed Epic Games Store titles from legacy manifests and modern HKCU uninstall entries."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_DIRECTORY_ENTRIES = 4096
_HELPER_PREFIXES = (
    "unins",
    "crash",
    "setup",
    "install",
    "redist",
    "vcredist",
    "dxsetup",
    "ue4prereq",
    "ueprereq",
    "easyanticheat",
    "beservice",
)


@dataclass(frozen=True, slots=True)
class EpicRegistryEntry:
    key_name: str
    display_name: str
    install_location: str
    epic_app_id: str = ""
    display_icon: str = ""


def _read_hkcu_epic_entries() -> tuple[EpicRegistryEntry, ...]:
    if os.name != "nt":
        return ()
    import winreg

    entries: list[EpicRegistryEntry] = []
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_READ) as root:
            count = winreg.QueryInfoKey(root)[0]
            for index in range(min(count, _MAX_DIRECTORY_ENTRIES)):
                try:
                    key_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                if not key_name.startswith("EpicGames-"):
                    continue
                try:
                    with winreg.OpenKey(root, key_name, 0, winreg.KEY_READ) as sk:
                        display_name = _reg_str(sk, "DisplayName")
                        install_loc = _reg_str(sk, "InstallLocation")
                        epic_app_id = _reg_str(sk, "EpicAppId")
                        display_icon = _reg_str(sk, "DisplayIcon")
                        if display_name and install_loc:
                            entries.append(
                                EpicRegistryEntry(
                                    key_name=key_name,
                                    display_name=display_name,
                                    install_location=install_loc,
                                    epic_app_id=epic_app_id,
                                    display_icon=display_icon,
                                )
                            )
                except OSError:
                    continue
    except OSError:
        return ()
    return tuple(entries)


def _reg_str(key: object, value_name: str) -> str:
    import winreg

    try:
        val, _ = winreg.QueryValueEx(key, value_name)
        return val.strip() if isinstance(val, str) else ""
    except OSError:
        return ""


class EpicDetector:
    source = GameSource.EPIC

    def __init__(
        self,
        manifest_dir: Path | None = None,
        *,
        registry_provider: Callable[[], Iterable[EpicRegistryEntry]] | None = None,
        launcher_installed_path: Path | None = None,
    ) -> None:
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        self._explicit_manifest_dir = manifest_dir is not None
        self._manifest_dir = (
            manifest_dir
            if manifest_dir is not None
            else program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        )
        if launcher_installed_path is not None:
            self._launcher_installed: Path | None = launcher_installed_path
        elif not self._explicit_manifest_dir:
            self._launcher_installed = (
                program_data / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
            )
        else:
            self._launcher_installed = None
        # Only query live HKCU registry by default when not given a synthetic test manifest_dir.
        if registry_provider is not None:
            self._registry_provider: Callable[[], Iterable[EpicRegistryEntry]] | None = (
                registry_provider
            )
        elif not self._explicit_manifest_dir:
            self._registry_provider = _read_hkcu_epic_entries
        else:
            self._registry_provider = None

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        manifest_available = False

        try:
            directory = local_path(self._manifest_dir)
            if directory is None:
                if self._registry_provider is None:
                    return DiscoveryBatch((), "unavailable", ("epic_manifest_directory_unsafe",))
            else:
                with os.scandir(directory) as entries:
                    manifest_available = True
                    for index, entry in enumerate(entries):
                        if index == _MAX_DIRECTORY_ENTRIES:
                            diagnostics.add("epic_scan_limit")
                            break
                        if Path(entry.name).suffix.lower() != ".item":
                            continue
                        try:
                            manifest = contained_file(directory, entry.name)
                            if manifest is None:
                                raise ValueError("Unusable Epic manifest")
                            game = _read_manifest(manifest)
                            if game is not None:
                                if game.source_id in games:
                                    diagnostics.add("epic_duplicate_game")
                                else:
                                    games[game.source_id] = game
                        except (OSError, TypeError, ValueError, RecursionError):
                            diagnostics.add("epic_manifest_unreadable")
        except (FileNotFoundError, NotADirectoryError):
            pass
        except OSError:
            diagnostics.add("epic_manifest_directory_unreadable")

        registry_found = False
        if self._registry_provider is not None:
            try:
                for reg_entry in self._registry_provider():
                    game = _from_registry_entry(reg_entry)
                    if game is not None:
                        registry_found = True
                        games.setdefault(game.source_id, game)
            except OSError:
                diagnostics.add("epic_registry_unreadable")

        dat_found = False
        if self._launcher_installed is not None:
            dat_file = local_path(self._launcher_installed)
            if dat_file is not None and dat_file.is_file():
                try:
                    for game in _read_launcher_installed(dat_file):
                        dat_found = True
                        games.setdefault(game.source_id, game)
                except (OSError, ValueError, TypeError):
                    diagnostics.add("epic_manifest_unreadable")

        if (
            not manifest_available
            and not registry_found
            and not dat_found
            and not games
            and not diagnostics
        ):
            return DiscoveryBatch((), "unavailable", ())

        state = "partial" if diagnostics else "complete"
        return DiscoveryBatch(tuple(games.values()), state, tuple(sorted(diagnostics)))


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


_EPIC_COVER_FILES = (
    "header.jpg",
    "cover.jpg",
    "cover.png",
    "banner.jpg",
    "boxart.jpg",
    "boxart.png",
)


def _find_epic_cover(install_dir: Path) -> Path | None:
    for name in _EPIC_COVER_FILES:
        candidate = contained_file(install_dir, name)
        if candidate is not None:
            return candidate
    return None


def _pick_exe_in_dir(install_dir: Path, display_icon: str = "") -> Path | None:
    if display_icon:
        raw_icon = display_icon.split(",", 1)[0].strip().strip('"')
        icon_path = local_path(raw_icon) if raw_icon else None
        if (
            icon_path is not None
            and icon_path.suffix.lower() == ".exe"
            and icon_path.is_file()
            and str(icon_path).casefold().startswith(str(install_dir).casefold())
        ):
            return icon_path
    try:
        candidates: list[Path] = []
        for index, child in enumerate(install_dir.iterdir()):
            if index >= 128:
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
        if not candidates:
            # Bounded depth-3 fallback for Unreal (Binaries/Win64/*.exe) or EA/nested layouts.
            nested: list[Path] = []
            stack: list[tuple[Path, int]] = [(install_dir, 0)]
            scanned = 0
            while stack and scanned < 512:
                cur, depth = stack.pop()
                try:
                    with os.scandir(cur) as it:
                        for entry in it:
                            scanned += 1
                            if scanned > 512:
                                break
                            try:
                                if entry.is_symlink():
                                    continue
                                if entry.is_dir(follow_symlinks=False):
                                    if depth < 3:
                                        stack.append((Path(entry.path), depth + 1))
                                elif entry.is_file(follow_symlinks=False):
                                    name_low = entry.name.casefold()
                                    if not name_low.endswith(".exe"):
                                        continue
                                    stem = Path(entry.name).stem.casefold()
                                    if stem.startswith(_HELPER_PREFIXES):
                                        continue
                                    rel = Path(entry.path).relative_to(install_dir)
                                    safe = contained_file(install_dir, str(rel))
                                    if safe is not None:
                                        nested.append(safe)
                            except OSError:
                                continue
                except OSError:
                    continue
            if len(nested) == 1:
                return nested[0]
            if nested:
                nested.sort(key=lambda p: p.stat().st_size, reverse=True)
                return nested[0]
    except OSError:
        return None
    return None


def _from_registry_entry(entry: EpicRegistryEntry) -> DetectedGame | None:
    display_name = entry.display_name.strip()
    if not display_name or len(display_name) > 256 or not display_name.isprintable():
        return None
    install_dir = local_path(entry.install_location)
    if install_dir is None or not install_dir.is_dir():
        return None

    # Modern EpicAppId format: "<namespace>:<catalogItemId>:<AppName>"
    artifact = ""
    app_name: str | None = None
    if entry.epic_app_id:
        parts = entry.epic_app_id.split(":")
        if len(parts) == 3 and all(_identifier(p) is not None for p in parts):
            ns, item, name = parts
            app_name = name
            artifact = f"{ns}%3A{item}%3A{name}"
        elif _identifier(entry.epic_app_id) is not None:
            app_name = entry.epic_app_id
            artifact = entry.epic_app_id

    if app_name is None:
        fallback = entry.key_name.removeprefix("EpicGames-")
        app_name = _identifier(fallback)
        if app_name is None:
            return None
        artifact = app_name

    launch = LaunchTarget(
        "epic_uri",
        f"com.epicgames.launcher://apps/{artifact}?action=launch&silent=true",
    )
    exe = _pick_exe_in_dir(install_dir, entry.display_icon)
    targets = (GameTarget("exe_path", os.path.normcase(str(exe))),) if exe is not None else ()
    cover_path = _find_epic_cover(install_dir)
    return DetectedGame(
        GameSource.EPIC,
        app_name,
        display_name,
        install_dir,
        cover_path,
        launch,
        targets,
    )


def _read_manifest(manifest: Path) -> DetectedGame | None:
    with manifest.open("rb") as infile:
        content = infile.read(_MAX_MANIFEST_BYTES + 1)
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError("Oversized Epic manifest")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise TypeError("Invalid Epic manifest")
    if data.get("bIsIncompleteInstall") is True or data.get("bIsApplication") is False:
        return None

    app_name = _identifier(data.get("AppName"))
    display_name = data.get("DisplayName")
    location = data.get("InstallLocation")
    if app_name is None or not isinstance(display_name, str) or not isinstance(location, str):
        raise ValueError("Missing Epic identity, title or location")
    if not display_name.strip() or len(display_name) > 256 or not display_name.isprintable():
        raise ValueError("Invalid Epic title")

    main_game = data.get("MainGameAppName")
    if isinstance(main_game, str) and main_game and main_game != app_name:
        return None

    install_dir = local_path(location)
    if install_dir is None:
        raise ValueError("Unsafe Epic install location")
    if not install_dir.is_dir():
        return None

    raw_executable = data.get("LaunchExecutable")
    executable = contained_file(install_dir, raw_executable)
    targets = ()
    if executable is not None and executable.suffix.lower() == ".exe":
        targets = (GameTarget("exe_path", os.path.normcase(str(executable))),)
    elif raw_executable:
        raise ValueError("Unusable Epic executable")

    namespace = _identifier(data.get("CatalogNamespace"))
    catalog = _identifier(data.get("CatalogItemId"))
    if namespace is not None and catalog is not None:
        artifact = f"{namespace}%3A{catalog}%3A{app_name}"
    elif not data.get("CatalogNamespace") and not data.get("CatalogItemId"):
        artifact = app_name  # Epic still supports the artifact-only URI.
    else:
        raise ValueError("Invalid Epic catalog identity")
    launch = LaunchTarget(
        "epic_uri", f"com.epicgames.launcher://apps/{artifact}?action=launch&silent=true"
    )
    cover_path = _find_epic_cover(install_dir)
    return DetectedGame(
        GameSource.EPIC, app_name, display_name.strip(), install_dir, cover_path, launch, targets
    )


def _read_launcher_installed(dat_path: Path) -> list[DetectedGame]:
    with dat_path.open("rb") as infile:
        content = infile.read(_MAX_MANIFEST_BYTES + 1)
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError("Oversized LauncherInstalled.dat")
    payload = json.loads(content)
    items = payload.get("InstallationList") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    found: list[DetectedGame] = []
    for item in items[:_MAX_DIRECTORY_ENTRIES]:
        if not isinstance(item, dict):
            continue
        app_name = _identifier(item.get("AppName"))
        location = item.get("InstallLocation")
        if app_name is None or not isinstance(location, str):
            continue
        install_dir = local_path(location)
        if install_dir is None or not install_dir.is_dir():
            continue
        ns = _identifier(item.get("NamespaceId"))
        cat = _identifier(item.get("ItemId"))
        artifact = f"{ns}%3A{cat}%3A{app_name}" if ns and cat else app_name
        launch = LaunchTarget(
            "epic_uri", f"com.epicgames.launcher://apps/{artifact}?action=launch&silent=true"
        )
        exe = _pick_exe_in_dir(install_dir)
        targets = (GameTarget("exe_path", os.path.normcase(str(exe))),) if exe is not None else ()
        cover_path = _find_epic_cover(install_dir)
        display_name = install_dir.name.strip() or app_name
        found.append(
            DetectedGame(
                GameSource.EPIC,
                app_name,
                display_name,
                install_dir,
                cover_path,
                launch,
                targets,
            )
        )
    return found
