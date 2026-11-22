import os
from pathlib import Path

from gamehub.core.library.models import GameSource, GameTarget, LaunchTarget
from gamehub.core.library.xbox import XboxDetector, XboxPackage

FIXTURE = Path(__file__).parent / "fixtures" / "xbox" / "MicrosoftGame.config"
PACKAGE_NAME = "Example.SyntheticGame"
PUBLISHER = "CN=Example Studio"
PACKAGE_FAMILY = "Example.SyntheticGame_1234567890abc"


def _make_game(folder: Path) -> Path:
    (folder / "Bin").mkdir(parents=True)
    executable = folder / "Bin" / "SyntheticGame.exe"
    executable.touch()
    (folder / "Debug.exe").touch()
    (folder / "Console.exe").touch()
    (folder / "MicrosoftGame.config").write_bytes(FIXTURE.read_bytes())
    return executable


def test_xbox_merges_folder_and_registered_package(tmp_path: Path) -> None:
    root = tmp_path / "XboxGames"
    installed = root / "Example Game" / "Content"
    executable = _make_game(installed)
    package = XboxPackage(PACKAGE_NAME, PUBLISHER, PACKAGE_FAMILY, installed)

    batch = XboxDetector([root], lambda: [package]).discover()

    assert batch.state == "complete"
    game, = batch.games
    assert (game.source, game.name, game.install_dir) == (GameSource.XBOX, "Synthetic Xbox Game", installed)
    assert game.launch_target == LaunchTarget("exe", str(executable))
    assert game.targets == (
        GameTarget("exe_path", os.path.normcase(str(executable))),
        GameTarget("package_id", PACKAGE_FAMILY.lower()),
    )


def test_xbox_package_inventory_does_not_list_ordinary_apps(tmp_path: Path) -> None:
    readable = tmp_path / "PackageGame"
    _make_game(readable)
    other = tmp_path / "NonGame"
    other.mkdir()
    records = [
        XboxPackage(PACKAGE_NAME, PUBLISHER, PACKAGE_FAMILY, readable),
        XboxPackage("Example.Editor", PUBLISHER, "Example.Editor_1234567890abc", other),
    ]

    batch = XboxDetector([], lambda: records).discover()

    game, = batch.games
    assert game.install_dir == readable
    assert GameTarget("package_id", PACKAGE_FAMILY.lower()) in game.targets


def test_xbox_keeps_folder_results_if_package_scan_fails(tmp_path: Path) -> None:
    root = tmp_path / "XboxGames"
    _make_game(root / "Example Game")

    def denied():
        raise PermissionError("Synthetic package access denial")

    batch = XboxDetector([root], denied).discover()

    assert len(batch.games) == 1
    assert batch.state == "partial"
    assert batch.diagnostics == ("xbox_package_list_unavailable",)


def test_xbox_rejects_doctype_and_external_target(tmp_path: Path) -> None:
    root = tmp_path / "XboxGames"
    valid = root / "External Target"
    _make_game(valid)
    (root / "outside.exe").touch()
    config = FIXTURE.read_text(encoding="utf-8").replace(r"Bin\SyntheticGame.exe", r"..\outside.exe")
    (valid / "MicrosoftGame.config").write_text(config, encoding="utf-8")
    unsafe = root / "External Config"
    unsafe.mkdir()
    (unsafe / "MicrosoftGame.config").write_text(
        '<!DOCTYPE Game [<!ENTITY sample SYSTEM "file:///not-a-local-game">]><Game>&sample;</Game>',
        encoding="utf-8",
    )

    batch = XboxDetector([root], list).discover()

    assert batch.state == "partial"
    assert batch.diagnostics == ("xbox_folder_metadata_unreadable",)
    game, = batch.games
    assert game.install_dir == valid
    assert game.launch_target is None
    assert not game.targets
