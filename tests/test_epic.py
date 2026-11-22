import json
import os
from pathlib import Path

import pytest

from gamehub.core.library.epic import EpicDetector
from gamehub.core.library.models import GameSource, GameTarget, LaunchTarget

FIXTURE = Path(__file__).parent / "fixtures" / "epic" / "synthetic-game.item"


@pytest.fixture
def epic_game(tmp_path: Path) -> tuple[Path, Path, dict]:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    install = tmp_path / "games" / "Epic"
    (install / "Bin").mkdir(parents=True)
    (install / "Bin" / "SyntheticGame.exe").touch()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["InstallLocation"] = str(install)
    return manifests, install, data


def _write_item(directory: Path, name: str, data: dict) -> None:
    (directory / name).write_text(json.dumps(data), encoding="utf-8")


def test_epic_scan_keeps_good_game_when_another_manifest_is_broken(epic_game) -> None:
    manifests, install, data = epic_game
    _write_item(manifests, "good.item", data)
    (manifests / "broken.item").write_text("[", encoding="utf-8")
    _write_item(manifests, "incomplete.item", {**data, "AppName": "Installing", "bIsIncompleteInstall": True})
    _write_item(manifests, "addon.item", {**data, "AppName": "Addon", "MainGameAppName": data["AppName"]})

    batch = EpicDetector(manifests).discover()

    assert batch.state == "partial"
    assert batch.diagnostics == ("epic_manifest_unreadable",)
    game, = batch.games
    assert (game.source, game.source_id, game.name, game.install_dir) == (
        GameSource.EPIC, "GameHubSample", "Synthetic Epic Game", install,
    )
    assert game.targets == (GameTarget("exe_path", os.path.normcase(str(install / "Bin" / "SyntheticGame.exe"))),)
    assert game.launch_target == LaunchTarget(
        "epic_uri",
        "com.epicgames.launcher://apps/synthetic-sandbox%3Asynthetic-catalog%3AGameHubSample"
        "?action=launch&silent=true",
    )


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("AppName", "game?target=other"),
        ("CatalogItemId", "catalog%3Aother"),
        ("InstallLocation", r"\\network\share"),
        ("LaunchExecutable", r"..\SyntheticGame.exe"),
        ("LaunchExecutable", r"C:\SyntheticGame.exe"),
        ("LaunchExecutable", r"Bin\SyntheticGame.exe:other"),
    ],
)
def test_epic_rejects_unsafe_manifest_fields(epic_game, field: str, unsafe: str) -> None:
    manifests, _, data = epic_game
    _write_item(manifests, "unsafe.item", {**data, field: unsafe})

    batch = EpicDetector(manifests).discover()

    assert not batch.games
    assert batch.state == "partial"


def test_epic_uses_artifact_uri_for_old_manifests(epic_game) -> None:
    manifests, _, data = epic_game
    del data["CatalogNamespace"], data["CatalogItemId"]
    _write_item(manifests, "legacy.item", data)

    batch = EpicDetector(manifests).discover()

    assert batch.state == "complete"
    game, = batch.games
    assert game.launch_target == LaunchTarget(
        "epic_uri", "com.epicgames.launcher://apps/GameHubSample?action=launch&silent=true",
    )


def test_epic_missing_launcher_is_unavailable(tmp_path: Path) -> None:
    batch = EpicDetector(tmp_path / "missing").discover()

    assert not batch.games
    assert batch.state == "unavailable"
