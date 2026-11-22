"""Find locally readable GDK game metadata and current-user Xbox packages."""

import codecs
import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_MAX_ENTRIES = 4096
_MAX_CONFIG_BYTES = 256 * 1024
_PACKAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}")
_PACKAGE_FAMILY = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}_[a-z0-9]{13}", re.IGNORECASE)
_PACKAGE_COMMAND = (
    "$ErrorActionPreference = 'Stop'; "
    '$env:PSModulePath = "$PSHOME\\Modules"; '
    "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
    "Get-AppxPackage -PackageTypeFilter Main | Select-Object -First 4097 "
    "Name,Publisher,PackageFamilyName,InstallLocation | ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class XboxPackage:
    name: str
    publisher: str
    family: str
    install_dir: Path


class XboxDetector:
    source = GameSource.XBOX

    def __init__(
        self,
        roots: Iterable[Path] | None = None,
        package_provider: Callable[[], Iterable[XboxPackage]] | None = None,
    ) -> None:
        self._roots = tuple(roots) if roots is not None else None
        self._packages = package_provider if package_provider is not None else _installed_packages

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        families: dict[str, set[str]] = {}
        packages_available = self._discover_packages(games, families, diagnostics)
        try:
            roots = self._roots
            if roots is None:
                roots = tuple(Path(drive) / "XboxGames" for drive in os.listdrives()) if os.name == "nt" else ()
        except OSError:
            roots = ()
            diagnostics.add("xbox_drive_list_unavailable")

        folders_available = False
        for root in roots:
            if self._discover_root(root, games, diagnostics):
                folders_available = True

        if not packages_available and not folders_available and not games:
            state = "unavailable"
        else:
            state = "partial" if diagnostics else "complete"
        results = tuple(_with_package_family(game, families) for game in games.values())
        return DiscoveryBatch(results, state, tuple(sorted(diagnostics)))

    def _discover_packages(
        self,
        games: dict[str, DetectedGame],
        families: dict[str, set[str]],
        diagnostics: set[str],
    ) -> bool:
        try:
            for index, package in enumerate(self._packages()):
                if index == _MAX_ENTRIES:
                    diagnostics.add("xbox_package_limit")
                    break
                source_id = _source_id(package.name, package.publisher)
                if source_id is None or not _PACKAGE_FAMILY.fullmatch(package.family):
                    diagnostics.add("xbox_package_identity_invalid")
                    continue
                family, _, _ = package.family.rpartition("_")
                if family.casefold() != package.name.casefold():
                    diagnostics.add("xbox_package_identity_invalid")
                    continue
                families.setdefault(source_id, set()).add(package.family.lower())
                try:
                    install_dir = local_path(package.install_dir)
                    if install_dir is None:
                        continue
                    config = contained_file(install_dir, "MicrosoftGame.config")
                    if config is not None:
                        game = _read_config(config, package.name)
                        if game is None:
                            continue
                        if game.source_id != source_id:
                            raise ValueError("Package identity does not match game config")
                        _merge_game(games, game)
                except (OSError, ValueError, ET.ParseError):
                    diagnostics.add("xbox_package_metadata_unreadable")
        except (OSError, TypeError, ValueError, subprocess.SubprocessError):
            diagnostics.add("xbox_package_list_unavailable")
            return False
        return True

    def _discover_root(
        self,
        root: Path,
        games: dict[str, DetectedGame],
        diagnostics: set[str],
    ) -> bool:
        try:
            directory = local_path(root)
            if directory is None:
                return False
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index == _MAX_ENTRIES:
                        diagnostics.add("xbox_folder_limit")
                        break
                    try:
                        config = contained_file(directory, f"{entry.name}\\Content\\MicrosoftGame.config")
                        if config is None:
                            config = contained_file(directory, f"{entry.name}\\MicrosoftGame.config")
                        if config is not None:
                            game = _read_config(config, entry.name)
                            if game is not None:
                                _merge_game(games, game)
                    except (OSError, ValueError, ET.ParseError):
                        diagnostics.add("xbox_folder_metadata_unreadable")
        except (FileNotFoundError, NotADirectoryError):
            return False
        except OSError:
            diagnostics.add("xbox_folder_unreadable")
            return False
        return True


def _installed_packages() -> Iterable[XboxPackage]:
    if os.name != "nt":
        raise OSError("Current-user Xbox package inventory requires Windows")

    import ctypes

    system = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system))
    if length == 0 or length >= len(system):
        raise OSError("Could not locate Windows System32")
    powershell = Path(system.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", _PACKAGE_COMMAND],
        capture_output=True,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=True,
        timeout=8,
        encoding="utf-8",
    )
    if not result.stdout.strip():
        return ()
    records = json.loads(result.stdout)
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise TypeError("Unexpected current-user package inventory")
    packages = []
    for record in records:
        if not isinstance(record, dict):
            continue
        fields = [record.get(key) for key in ("Name", "Publisher", "PackageFamilyName", "InstallLocation")]
        if all(isinstance(value, str) and value for value in fields):
            name, publisher, family, install_dir = fields
            packages.append(XboxPackage(name, publisher, family, Path(install_dir)))
    return packages


def _source_id(name: str, publisher: str) -> str | None:
    if not _PACKAGE_NAME.fullmatch(name) or not publisher or len(publisher) > 512:
        return None
    fingerprint = hashlib.sha256(publisher.strip().casefold().encode()).hexdigest()[:16]
    return f"{name.lower()}:{fingerprint}"


def _read_config(config: Path, fallback_name: str) -> DetectedGame | None:
    with config.open("rb") as infile:
        content = infile.read(_MAX_CONFIG_BYTES + 1)
    if len(content) > _MAX_CONFIG_BYTES:
        raise ValueError("Oversized GDK config")
    encoding = "utf-16" if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    xml = content.decode(encoding)
    if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        raise ValueError("Unexpected XML declaration in GDK config")
    game = ET.fromstring(xml)
    identity = game.find("Identity")
    if game.tag != "Game" or identity is None:
        raise ValueError("Missing GDK game identity")
    source_id = _source_id(identity.get("Name", ""), identity.get("Publisher", ""))
    if source_id is None:
        raise ValueError("Invalid GDK game identity")

    visual = game.find("ShellVisuals")
    title = visual.get("DefaultDisplayName", "").strip() if visual is not None else ""
    if not title or title.startswith("ms-resource:") or len(title) > 256 or not title.isprintable():
        title = fallback_name

    install_dir = config.parent
    executables: list[Path] = []
    is_pc_game = False
    for entry in game.findall("./ExecutableList/Executable"):
        family = entry.get("TargetDeviceFamily", "").casefold()
        if entry.get("IsDevOnly", "").casefold() in {"true", "1"} or (family and family != "pc"):
            continue
        raw_executable = entry.get("Name", "")
        if not raw_executable.lower().endswith(".exe"):
            continue
        is_pc_game = True
        executable = contained_file(install_dir, raw_executable)
        if executable is not None:
            executables.append(executable)
    if not is_pc_game:
        return None

    targets = tuple(dict.fromkeys(GameTarget("exe_path", os.path.normcase(str(path))) for path in executables))
    launch = LaunchTarget("exe", str(executables[0])) if executables else None
    return DetectedGame(GameSource.XBOX, source_id, title, install_dir, None, launch, targets)


def _with_package_family(game: DetectedGame, families: dict[str, set[str]]) -> DetectedGame:
    matches = families.get(game.source_id, set())
    if len(matches) != 1:
        return game
    target = GameTarget("package_id", next(iter(matches)))
    return replace(game, targets=(*game.targets, target))


def _merge_game(games: dict[str, DetectedGame], game: DetectedGame) -> None:
    existing = games.get(game.source_id)
    if existing is None:
        games[game.source_id] = game
        return
    playable = game if game.launch_target is not None and existing.launch_target is None else existing
    targets = tuple(dict.fromkeys((*existing.targets, *game.targets)))
    games[game.source_id] = replace(playable, targets=targets)
