"""Tests for M15: Epic HKCU/dat, Steam offline drives, Riot/GOG/EA/Ubisoft/Battle.net/itch, Scan Folders & plain warnings."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gamehub.core.library.battlenet import BattleNetDetector, BattleNetRegistryEntry
from gamehub.core.library.ea import EaDetector, EaRegistryEntry
from gamehub.core.library.epic import EpicDetector, EpicRegistryEntry
from gamehub.core.library.folder_scanner import (
    FolderDetector,
    is_helper_executable,
    scan_folder_candidates,
)
from gamehub.core.library.gog import GogDetector, GogRegistryEntry
from gamehub.core.library.itch import ItchDetector
from gamehub.core.library.models import DiscoveryBatch, GameSource
from gamehub.core.library.riot import RiotDetector, RiotUninstallEntry
from gamehub.core.library.service import LibraryService
from gamehub.core.library.steam import SteamDetector
from gamehub.core.library.ubisoft import UbisoftDetector, UbisoftRegistryEntry
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.ui.library_controller import LibraryController
from gamehub.ui.library_view import LibraryView
from gamehub.ui.scan_folders_dialog import ScanFolderDialog


def test_epic_discovers_modern_hkcu_and_launcher_installed(tmp_path: Path) -> None:
    ds_dir = tmp_path / "DeathStranding"
    ds_dir.mkdir()
    ds_exe = ds_dir / "ds.exe"
    ds_exe.write_bytes(b"MZ")

    hue_dir = tmp_path / "Hue"
    hue_dir.mkdir()
    hue_exe = hue_dir / "Hue.exe"
    hue_exe.write_bytes(b"MZ")

    dat = tmp_path / "LauncherInstalled.dat"
    dat.write_text(
        '{"InstallationList": ['
        f'{{"InstallLocation": "{str(hue_dir).replace(chr(92), chr(92)*2)}", '
        '"NamespaceId": "ns1", "ItemId": "it1", "AppName": "HueApp"}'
        "]}",
        encoding="utf-8",
    )

    entries = [
        EpicRegistryEntry(
            key_name="EpicGames-DeathStranding",
            display_name="DEATH STRANDING",
            install_location=str(ds_dir),
            epic_app_id="ns2:cat2:DeathStrandingApp",
            display_icon=f'"{ds_exe}",0',
        )
    ]

    detector = EpicDetector(
        manifest_dir=tmp_path / "MissingManifests",
        registry_provider=lambda: entries,
        launcher_installed_path=dat,
    )
    batch = detector.discover()
    assert batch.state == "complete"
    assert batch.diagnostics == ()
    by_id = {g.source_id: g for g in batch.games}
    assert set(by_id) == {"DeathStrandingApp", "HueApp"}
    assert by_id["DeathStrandingApp"].launch_target is not None
    assert "ns2%3Acat2%3ADeathStrandingApp" in by_id["DeathStrandingApp"].launch_target.value
    assert by_id["DeathStrandingApp"].targets[0].match_key == os.path.normcase(str(ds_exe))


def test_steam_skips_unmounted_offline_drive_without_partial_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    common = steamapps / "common" / "Hollow Knight"
    common.mkdir(parents=True)
    (common / "hollow_knight.exe").write_bytes(b"MZ")
    (steamapps / "appmanifest_367520.acf").write_text(
        '"AppState"\n{\n"appid" "367520"\n"name" "Hollow Knight"\n'
        '"installdir" "Hollow Knight"\n"StateFlags" "4"\n}\n',
        encoding="utf-8",
    )
    import vdf

    (steamapps / "libraryfolders.vdf").write_text(
        vdf.dumps(
            {
                "libraryfolders": {
                    "0": {"path": str(steam_root)},
                    "1": {"path": r"Q:\SteamLibrary"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "gamehub.core.library.steam._is_unmounted_windows_drive",
        lambda raw: raw.upper().startswith("Q:"),
    )
    batch = SteamDetector(steam_root).discover()
    assert batch.state == "complete"
    assert batch.diagnostics == ()
    assert [g.name for g in batch.games] == ["Hollow Knight"]


def test_riot_detector_discovers_valorant_from_registry_and_installs_json(tmp_path: Path) -> None:
    pd = tmp_path / "Riot Games"
    pd.mkdir()
    rc_dir = tmp_path / "Riot Client"
    rc_dir.mkdir()
    rc_exe = rc_dir / "RiotClientServices.exe"
    rc_exe.write_bytes(b"MZ")

    val_dir = tmp_path / "VALORANT" / "live"
    val_bin = val_dir / "ShooterGame" / "Binaries" / "Win64"
    val_bin.mkdir(parents=True)
    val_exe = val_bin / "VALORANT-Win64-Shipping.exe"
    val_exe.write_bytes(b"MZ")

    (pd / "RiotClientInstalls.json").write_text(
        f'{{"rc_live": "{str(rc_exe).replace(chr(92), chr(92)*2)}"}}',
        encoding="utf-8",
    )
    entries = [
        RiotUninstallEntry(
            key_name="Riot Game valorant.live",
            display_name="VALORANT",
            install_location=str(val_dir),
        )
    ]
    batch = RiotDetector(pd, registry_provider=lambda: entries).discover()
    assert batch.state == "complete"
    assert len(batch.games) == 1
    game = batch.games[0]
    assert game.source == GameSource.RIOT
    assert game.source_id == "valorant.live"
    assert game.launch_target is not None
    assert game.launch_target.kind == "riot_client"
    assert game.launch_target.value.endswith("|valorant|live")
    assert any(t.match_key == os.path.normcase(str(val_exe)) for t in game.targets)


def test_gog_detector_reads_galaxy_sqlite_and_registry(tmp_path: Path) -> None:
    game_dir = tmp_path / "Cyberpunk 2077"
    game_dir.mkdir()
    exe = game_dir / "Cyberpunk2077.exe"
    exe.write_bytes(b"MZ")

    db_file = tmp_path / "galaxy-2.0.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE InstalledBaseProducts (productId TEXT, installationPath TEXT)")
    conn.execute("CREATE TABLE LimitedDetails (productId TEXT, title TEXT)")
    conn.execute("INSERT INTO InstalledBaseProducts VALUES (?, ?)", ("1423049311", str(game_dir)))
    conn.execute("INSERT INTO LimitedDetails VALUES (?, ?)", ("1423049311", "Cyberpunk 2077"))
    conn.commit()
    conn.close()

    reg = [GogRegistryEntry("1423049311", "Cyberpunk 2077", str(game_dir), str(exe))]
    batch = GogDetector(db_file, registry_provider=lambda: reg).discover()
    assert batch.state == "complete"
    assert len(batch.games) == 1
    g = batch.games[0]
    assert g.source == GameSource.GOG
    assert g.launch_target is not None
    assert g.launch_target.value == "goggalaxy://openGameView/1423049311"
    assert len(g.targets) == 1


def test_ea_ubisoft_battlenet_and_itch_detectors(tmp_path: Path) -> None:
    # EA
    ea_dir = tmp_path / "EA FC 26"
    ea_dir.mkdir()
    fc_exe = ea_dir / "FC26.exe"
    fc_exe.write_bytes(b"MZ" * 100)
    (ea_dir / "EAAntiCheat.GameServiceLauncher.exe").write_bytes(b"MZ")
    ea_batch = EaDetector(
        install_data_dir=tmp_path / "missing_ea",
        registry_provider=lambda: [
            EaRegistryEntry("ea-sports-fc-26", "EA SPORTS FC 26", str(ea_dir), offer_id="OFFER123")
        ],
    ).discover()
    assert ea_batch.state == "complete"
    assert ea_batch.games[0].launch_target is not None
    assert ea_batch.games[0].launch_target.kind == "ea_uri"
    assert ea_batch.games[0].targets[0].match_key == os.path.normcase(str(fc_exe))

    # Ubisoft
    ubi_dir = tmp_path / "AssassinsCreed"
    ubi_dir.mkdir()
    ac_exe = ubi_dir / "ACMirage.exe"
    ac_exe.write_bytes(b"MZ")
    ubi_batch = UbisoftDetector(
        registry_provider=lambda: [
            UbisoftRegistryEntry("6100", "Assassin's Creed Mirage", str(ubi_dir))
        ]
    ).discover()
    assert ubi_batch.state == "complete"
    assert ubi_batch.games[0].launch_target.value == "uplay://launch/6100/0"

    # Battle.net
    bn_dir = tmp_path / "Overwatch"
    bn_dir.mkdir()
    ow_exe = bn_dir / "Overwatch.exe"
    ow_exe.write_bytes(b"MZ")
    bn_batch = BattleNetDetector(
        registry_provider=lambda: [
            BattleNetRegistryEntry(
                "Overwatch",
                "Overwatch",
                str(bn_dir),
                display_icon=str(ow_exe),
                uninstall_string='"C:\\ProgramData\\Battle.net\\Agent\\Blizzard Uninstaller.exe" --uid=pro',
            )
        ]
    ).discover()
    assert bn_batch.state == "complete"
    assert bn_batch.games[0].launch_target.value == "battlenet://Pro"

    # itch.io
    itch_base = tmp_path / "itch_apps"
    cave_dir = itch_base / "celeste-classic"
    cave_dir.mkdir(parents=True)
    itch_exe = cave_dir / "Celeste.exe"
    itch_exe.write_bytes(b"MZ")
    butler_db = tmp_path / "butler.db"
    conn = sqlite3.connect(butler_db)
    conn.execute("CREATE TABLE games (id INTEGER, title TEXT)")
    conn.execute("CREATE TABLE install_locations (id TEXT, path TEXT)")
    conn.execute(
        "CREATE TABLE caves (id TEXT, game_id INTEGER, install_location_id TEXT, install_folder_name TEXT)"
    )
    conn.execute("INSERT INTO games VALUES (42, 'Celeste Classic')")
    conn.execute("INSERT INTO install_locations VALUES ('loc1', ?)", (str(itch_base),))
    conn.execute("INSERT INTO caves VALUES ('cave1', 42, 'loc1', 'celeste-classic')")
    conn.commit()
    conn.close()
    itch_batch = ItchDetector(butler_db).discover()
    assert itch_batch.state == "complete"
    assert [g.name for g in itch_batch.games] == ["Celeste Classic"]
    assert itch_batch.games[0].launch_target.kind == "exe"


def test_folder_scanner_filters_helpers_remembers_choices_and_reconciles(tmp_path: Path) -> None:
    root = tmp_path / "MyGames"
    g1 = root / "Hollow Knight"
    g1.mkdir(parents=True)
    hk_exe = g1 / "hollow_knight.exe"
    hk_exe.write_bytes(b"MZ")
    (g1 / "unins000.exe").write_bytes(b"MZ")
    (g1 / "UnityCrashHandler64.exe").write_bytes(b"MZ")
    (g1 / "vc_redist.x64.exe").write_bytes(b"MZ")
    (g1 / "EasyAntiCheat_EOS_Setup.exe").write_bytes(b"MZ")

    g2 = root / "Indie Adventure"
    g2.mkdir(parents=True)
    indie_exe = g2 / "Game.exe"
    indie_exe.write_bytes(b"MZ")

    assert is_helper_executable(g1 / "unins000.exe")
    assert is_helper_executable(g1 / "UnityCrashHandler64.exe")
    assert not is_helper_executable(hk_exe)

    cands = scan_folder_candidates(root)
    assert [c.exe_path for c in cands] == [hk_exe, indie_exe]
    assert [c.suggested_name for c in cands] == ["Hollow Knight", "Indie Adventure"]

    db = Database(tmp_path / "gamehub.db")
    repo = LibraryRepository(db)
    service = LibraryService(repo, [FolderDetector(repo)])
    snap = service.apply_scan_folder(
        root,
        [
            (hk_exe, "include", "Hollow Knight Custom"),
            (indie_exe, "ignore", "Indie Adventure"),
        ],
    )
    assert [g.name for g in snap.games] == ["Hollow Knight Custom"]
    assert snap.games[0].source == GameSource.FOLDER

    # Ignored executable does not reappear on subsequent scans
    cands_after = scan_folder_candidates(root, existing_choices=repo.list_scan_choices(root))
    assert [c.exe_path for c in cands_after] == [hk_exe]


def test_scan_folder_dialog_and_plain_scan_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication(["Game Hub test"])

    folder = tmp_path / "Games"
    g = folder / "Hades"
    g.mkdir(parents=True)
    exe = g / "Hades.exe"
    exe.write_bytes(b"MZ")
    cands = scan_folder_candidates(folder)
    dlg = ScanFolderDialog(folder, cands)
    dlg._table.item(0, 0).setText("Hades Renamed")
    dlg._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert dlg.choices() == [(exe, "include", "Hades Renamed")]
    dlg.close()

    # Plain-language partial scan warning contains no raw diagnostic codes
    class _PartialSteam:
        source = GameSource.STEAM

        def discover(self) -> DiscoveryBatch:
            return DiscoveryBatch((), "partial", ("steam_index_invalid",))

    db = Database(tmp_path / "warn.db")
    repo = LibraryRepository(db)
    view = LibraryView()
    service = LibraryService(repo, [_PartialSteam()])
    controller = LibraryController(view, service)
    try:
        snap = service.refresh()
        assert len(snap.scan_issues) == 1
        desc = controller._describe_issue(snap.scan_issues[0])
        assert "Steam" in desc
        assert "steam_index_invalid" not in desc
        view.show_scan_warning(desc, desc)
        assert view._error_banner.isVisible() or view._error.text() == desc
        assert not view._retry_btn.isHidden()
        assert not view._learn_more_btn.isHidden()
    finally:
        controller.close()
        view.close()
        app.processEvents()
