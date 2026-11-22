"""Discover locally installed Epic Games Store titles from launcher manifests."""

import json
import os
import re
from pathlib import Path

from .models import DetectedGame, DiscoveryBatch, GameSource, GameTarget, LaunchTarget
from .paths import contained_file, local_path

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_DIRECTORY_ENTRIES = 4096


class EpicDetector:
    source = GameSource.EPIC

    def __init__(self, manifest_dir: Path | None = None) -> None:
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        self._manifest_dir = (
            manifest_dir
            if manifest_dir is not None
            else program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        )

    def discover(self) -> DiscoveryBatch:
        games: dict[str, DetectedGame] = {}
        diagnostics: set[str] = set()
        try:
            directory = local_path(self._manifest_dir)
            if directory is None:
                return DiscoveryBatch((), "unavailable", ("epic_manifest_directory_unsafe",))
            with os.scandir(directory) as entries:
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
            return DiscoveryBatch((), "unavailable", ())
        except OSError:
            diagnostics.add("epic_manifest_directory_unreadable")

        state = "partial" if diagnostics else "complete"
        return DiscoveryBatch(tuple(games.values()), state, tuple(sorted(diagnostics)))


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


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
    launch = LaunchTarget("epic_uri", f"com.epicgames.launcher://apps/{artifact}?action=launch&silent=true")
    return DetectedGame(GameSource.EPIC, app_name, display_name.strip(), install_dir, None, launch, targets)
