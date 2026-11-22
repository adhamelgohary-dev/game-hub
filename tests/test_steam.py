from pathlib import Path

import pytest
import vdf

from gamehub.core.library import steam
from gamehub.core.library.steam import SteamDetector

FIXTURES = Path(__file__).parent / "fixtures" / "steam"


def _install(root: Path, appid: str, folder: str, name: str) -> Path:
    game = root / "steamapps" / "common" / folder
    game.mkdir(parents=True)
    manifest = root / "steamapps" / f"appmanifest_{appid}.acf"
    manifest.write_text(
        vdf.dumps({"AppState": {"appid": appid, "name": name, "installdir": folder}}),
        encoding="utf-8",
    )
    (game / "Game.exe").touch()
    return game


def test_steam_reads_multiple_libraries_with_stable_ids(tmp_path: Path) -> None:
    main = tmp_path / "Steam"
    secondary = tmp_path / "Secondary"
    first = _install(main, "910001", "Example Adventure", "Example Adventure")
    (first / "Uninstall.exe").touch()
    (main / "steamapps" / "appmanifest_910001.acf").write_bytes(
        (FIXTURES / "appmanifest_910001.acf").read_bytes()
    )
    _install(secondary, "910002", "Example Two", "Example Two")
    index = (FIXTURES / "libraryfolders.vdf").read_text(encoding="utf-8")
    (main / "steamapps" / "libraryfolders.vdf").write_text(
        index.replace("__MAIN__", main.as_posix()).replace("__SECONDARY__", secondary.as_posix()),
        encoding="utf-8",
    )
    batch = SteamDetector(main).discover()
    assert batch.state == "complete"
    games = {game.source_id: game for game in batch.games}
    assert games.keys() == {"910001", "910002"}
    assert games["910001"].install_dir == first
    assert games["910001"].launch_target.value == "steam://rungameid/910001"
    assert len(games["910001"].targets) == 1


def test_steam_bad_manifest_preserves_discovery_and_avoids_ambiguous_exe(tmp_path: Path) -> None:
    game = _install(tmp_path, "910002", "Example Two", "Example Two")
    (game / "Bonus.exe").touch()
    steamapps = tmp_path / "steamapps"
    (steamapps / "appmanifest_910003.acf").write_text(
        vdf.dumps({"AppState": {"appid": "910003", "name": "Invalid", "installdir": "..\\outside"}}),
        encoding="utf-8",
    )
    batch = SteamDetector(tmp_path).discover()
    assert batch.state == "partial"
    assert "steam_manifest_invalid" in batch.diagnostics
    assert [game.source_id for game in batch.games] == ["910002"]
    assert not batch.games[0].targets


def test_inaccessible_index_entry_does_not_hide_other_steam_libraries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "Main"
    secondary = tmp_path / "Secondary"
    (main / "steamapps").mkdir(parents=True)
    _install(secondary, "910002", "Example Two", "Example Two")
    inaccessible = (tmp_path / "Inaccessible").as_posix()
    (main / "steamapps" / "libraryfolders.vdf").write_text(
        vdf.dumps({"libraryfolders": {"0": inaccessible, "1": secondary.as_posix()}}),
        encoding="utf-8",
    )
    original = steam.local_path

    def reject_inaccessible_location(path: str | Path) -> Path | None:
        if path == inaccessible:
            raise PermissionError
        return original(path)

    monkeypatch.setattr(steam, "local_path", reject_inaccessible_location)
    batch = SteamDetector(main).discover()
    assert batch.state == "partial"
    assert [game.source_id for game in batch.games] == ["910002"]
