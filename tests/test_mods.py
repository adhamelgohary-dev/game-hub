"""Tests for Translations & Mods engine, declarative manifest validator, journal recovery, and UI."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gamehub.app import GameHubWindow
from gamehub.core.i18n import apply_language
from gamehub.core.library.models import DetectedGame, DiscoveryBatch, GameSource
from gamehub.core.protection.catalog import ProtectedGamesCatalog
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.modules.mods.engine import ModsEngine
from gamehub.modules.mods.manifest import validate_zip_manifest
from gamehub.modules.mods.models import (
    GameRunningModError,
    ManifestValidationError,
    ModFilesystemError,
    ProtectedGameModError,
)
from gamehub.modules.mods.repository import ModsRepository
from gamehub.modules.mods.sample_pack import (
    build_sample_mod_zip,
    build_sample_translation_zip,
)


class _EmptyScanner:
    def __init__(self, procs: tuple[tuple[int, str], ...] = ()) -> None:
        self.procs = procs

    def list_processes(self) -> tuple[tuple[int, str], ...]:
        return self.procs


def _setup_singleplayer_game(tmp_path: Path) -> tuple[Database, LibraryRepository, ProtectedGamesCatalog, str, Path]:
    data_root = tmp_path / "data"
    db = Database(data_root / "gamehub.db")
    library = LibraryRepository(db)
    game_dir = tmp_path / "MafiaII"
    (game_dir / "localization").mkdir(parents=True)
    (game_dir / "Mafia2.exe").write_bytes(b"fake-exe")
    (game_dir / "localization" / "strings.txt").write_bytes(b"MENU_PLAY=Play\n")
    (game_dir / "localization" / "fonts.cfg").write_bytes(b"font_family=Default\nrtl=false\n")
    game_id = library.add_manual(game_dir / "Mafia2.exe")
    catalog = ProtectedGamesCatalog.load(strict_load=True)
    return db, library, catalog, game_id, game_dir


def test_manifest_validator_rejects_scripts_executables_traversal_and_symlinks(tmp_path: Path) -> None:
    def _make_zip(name: str, manifest: dict, members: dict[str, bytes], *, symlink_member: str | None = None) -> Path:
        zpath = tmp_path / name
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            for k, v in members.items():
                info = zipfile.ZipInfo(k)
                if symlink_member == k:
                    info.external_attr = (0o120777 << 16)
                zf.writestr(info, v)
        return zpath

    content = b"hello"
    sha = hashlib.sha256(content).hexdigest()

    # 1. Script/command key rejected
    z_script = _make_zip(
        "bad_script.zip",
        {
            "schema_version": 1,
            "id": "bad-script",
            "name": "Bad",
            "kind": "mod",
            "version": "1.0",
            "files_root": "files",
            "post_install": "calc.exe",
            "files": [{"src": "a.txt", "dest": "a.txt", "sha256": sha}],
        },
        {"files/a.txt": content},
    )
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(z_script)

    # 2. Executable / script extension rejected (.exe, .dll, .bat, .ps1, .py)
    for bad_ext in ("payload.exe", "hook.dll", "run.bat", "script.ps1", "helper.py"):
        z_exe = _make_zip(
            f"bad_{bad_ext}.zip",
            {
                "schema_version": 1,
                "id": "bad-ext",
                "name": "Bad Ext",
                "kind": "mod",
                "version": "1.0",
                "files_root": "files",
                "files": [{"src": bad_ext, "dest": bad_ext, "sha256": sha}],
            },
            {f"files/{bad_ext}": content},
        )
        with pytest.raises(ManifestValidationError):
            validate_zip_manifest(z_exe)

    # 3. Path traversal & absolute paths & reserved Windows names rejected
    for bad_dest in ("../escape.txt", "a/../../escape.txt", "/abs.txt", "C:/win.txt", "sub/CON.txt"):
        z_trav = _make_zip(
            f"trav_{abs(hash(bad_dest))}.zip",
            {
                "schema_version": 1,
                "id": "bad-path",
                "name": "Bad Path",
                "kind": "mod",
                "version": "1.0",
                "files_root": "files",
                "files": [{"src": "a.txt", "dest": bad_dest, "sha256": sha}],
            },
            {"files/a.txt": content},
        )
        with pytest.raises(ManifestValidationError):
            validate_zip_manifest(z_trav)

    # 4. Checksum mismatch rejected
    z_bad_sha = _make_zip(
        "bad_sha.zip",
        {
            "schema_version": 1,
            "id": "bad-sha",
            "name": "Bad SHA",
            "kind": "translation",
            "version": "1.0",
            "files_root": "files",
            "files": [{"src": "a.txt", "dest": "a.txt", "sha256": "0" * 64}],
        },
        {"files/a.txt": content},
    )
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(z_bad_sha)

    # 5. Zip symlink rejected
    z_sym = _make_zip(
        "bad_sym.zip",
        {
            "schema_version": 1,
            "id": "bad-sym",
            "name": "Bad Sym",
            "kind": "mod",
            "version": "1.0",
            "files_root": "files",
            "files": [{"src": "a.txt", "dest": "a.txt", "sha256": sha}],
        },
        {"files/a.txt": content},
        symlink_member="files/a.txt",
    )
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(z_sym)


def test_mods_engine_backup_toggle_conflict_remove_and_restore_original(tmp_path: Path) -> None:
    db, library, catalog, game_id, game_dir = _setup_singleplayer_game(tmp_path)
    data_root = tmp_path / "data"
    scanner = _EmptyScanner()
    engine = ModsEngine(db, data_root, library, catalog, process_scanner=scanner)

    tr_zip = build_sample_translation_zip(tmp_path / "sample-tr.zip")
    mod_zip = build_sample_mod_zip(tmp_path / "sample-mod.zip", conflict_with_translation=True)

    # Import translation (auto-enabled) -> backs up originals and deploys Arabic files
    tr_item = engine.import_zip(game_id, tr_zip, enable=True)
    state = engine.get_state(game_id)
    assert state.backed_up_count == 2
    assert state.has_mod_changes is True
    assert "ابدأ اللعب" in (game_dir / "localization" / "strings.txt").read_text(encoding="utf-8")
    assert b"SegoeUIArabic" in (game_dir / "localization" / "fonts.cfg").read_bytes()

    # Import conflicting HUD mod -> conflict detected in plain model, translation wins by default
    mod_item = engine.import_zip(game_id, mod_zip, enable=True)
    state = engine.get_state(game_id)
    assert len(state.conflicts) == 1
    assert state.conflicts[0].rel_paths == ("localization/fonts.cfg",)
    assert state.conflicts[0].winner_item_id == tr_item.id
    assert (game_dir / "ui" / "hud_theme.cfg").is_file()
    assert b"SegoeUIArabic" in (game_dir / "localization" / "fonts.cfg").read_bytes()

    # Switch conflict winner to HUD mod -> fonts.cfg switches cleanly
    state = engine.choose_conflict_winner(game_id, tr_item.id, mod_item.id, mod_item.id)
    assert state.conflicts[0].winner_item_id == mod_item.id
    assert b"ClassicHUD" in (game_dir / "localization" / "fonts.cfg").read_bytes()

    # Turn HUD mod Off -> ui/hud_theme.cfg removed, fonts.cfg reverts to translation
    state = engine.set_enabled(game_id, mod_item.id, False)
    assert not (game_dir / "ui" / "hud_theme.cfg").exists()
    assert b"SegoeUIArabic" in (game_dir / "localization" / "fonts.cfg").read_bytes()
    assert state.conflicts == ()

    # Turn HUD mod back On, then click "Restore the original game"
    engine.set_enabled(game_id, mod_item.id, True)
    state = engine.restore_original(game_id)
    assert state.has_mod_changes is False
    assert all(not item.enabled for item in state.items)
    assert (game_dir / "localization" / "strings.txt").read_bytes() == b"MENU_PLAY=Play\n"
    assert (game_dir / "localization" / "fonts.cfg").read_bytes() == b"font_family=Default\nrtl=false\n"
    assert not (game_dir / "ui" / "hud_theme.cfg").exists()

    # Remove translation item cleanly
    state = engine.remove_item(game_id, tr_item.id)
    assert len(state.items) == 1
    assert state.items[0].id == mod_item.id


def test_mods_engine_hard_blocks_protected_games_and_running_games(tmp_path: Path) -> None:
    db, library, catalog, sp_game_id, sp_dir = _setup_singleplayer_game(tmp_path)
    data_root = tmp_path / "data"

    # Add Fortnite as an Epic game AND even override protection_mode='full' -> MUST STILL STAY LOCKED!
    fortnite_dir = tmp_path / "Fortnite"
    fortnite_dir.mkdir()
    library.reconcile(
        GameSource.EPIC,
        DiscoveryBatch(
            (
                DetectedGame(
                    source=GameSource.EPIC,
                    source_id="Fortnite",
                    name="Fortnite",
                    install_dir=fortnite_dir,
                    cover_path=None,
                    launch_target=None,
                    targets=(),
                ),
            )
        ),
    )
    fn_game = next(g for g in library.list_games() if g.name == "Fortnite")
    library.set_protection(fn_game.id, "full", exit_after_launch=False)

    tr_zip = build_sample_translation_zip(tmp_path / "sample-tr.zip")
    scanner = _EmptyScanner()
    running_flag = [False]
    engine = ModsEngine(
        db,
        data_root,
        library,
        catalog,
        is_any_game_running=lambda: running_flag[0],
        process_scanner=scanner,
    )

    # Protected game is locked in state AND rejects import/restore
    fn_state = engine.get_state(fn_game.id)
    assert fn_state.protected is True
    with pytest.raises(ProtectedGameModError):
        engine.import_zip(fn_game.id, tr_zip)
    with pytest.raises(ProtectedGameModError):
        engine.restore_original(fn_game.id)

    # Running game via callback blocks single-player mod changes
    running_flag[0] = True
    with pytest.raises(GameRunningModError):
        engine.import_zip(sp_game_id, tr_zip)
    running_flag[0] = False

    # Running game detected via live Toolhelp process scanner blocks single-player mod changes
    scanner.procs = ((4242, "Mafia2.exe"),)
    with pytest.raises(GameRunningModError):
        engine.import_zip(sp_game_id, tr_zip)
    scanner.procs = ()

    # Symlink/junction inside game folder is rejected
    if os.name == "nt":
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("keep", encoding="utf-8")
        junction = sp_dir / "ui"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            check=False,
        )
        mod_zip = build_sample_mod_zip(tmp_path / "mod_sym.zip", conflict_with_translation=False)
        with pytest.raises(ModFilesystemError):
            engine.import_zip(sp_game_id, mod_zip)
        assert not (outside / "hud_theme.cfg").exists()


def test_mods_engine_crash_safe_journal_recovery(tmp_path: Path) -> None:
    db, library, catalog, game_id, game_dir = _setup_singleplayer_game(tmp_path)
    data_root = tmp_path / "data"
    engine = ModsEngine(db, data_root, library, catalog, process_scanner=_EmptyScanner())

    tr_zip = build_sample_translation_zip(tmp_path / "sample-tr.zip")
    engine.import_zip(game_id, tr_zip, enable=True)

    # Simulate an interrupted operation mid-restore: items disabled, journal stuck 'in_progress',
    # and modified file still left on disk!
    repo = ModsRepository(db)
    repo.disable_all(game_id)
    repo.begin_journal("crash-1", game_id, "restore_original", {"desired_paths": []})
    assert b"SegoeUIArabic" in (game_dir / "localization" / "fonts.cfg").read_bytes()

    recovered = engine.recover_incomplete()
    assert recovered == 1
    assert repo.list_incomplete_journals() == ()
    assert (game_dir / "localization" / "strings.txt").read_bytes() == b"MENU_PLAY=Play\n"
    assert (game_dir / "localization" / "fonts.cfg").read_bytes() == b"font_family=Default\nrtl=false\n"


def test_mods_ui_sidebar_search_rtl_and_protected_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["mods ui test"])
    db, library, catalog, sp_game_id, _ = _setup_singleplayer_game(tmp_path)
    data_root = tmp_path / "data"
    fortnite_dir = tmp_path / "Fortnite"
    fortnite_dir.mkdir()
    library.reconcile(
        GameSource.EPIC,
        DiscoveryBatch(
            (
                DetectedGame(
                    source=GameSource.EPIC,
                    source_id="Fortnite",
                    name="Fortnite",
                    install_dir=fortnite_dir,
                    cover_path=None,
                    launch_target=None,
                    targets=(),
                ),
            )
        ),
    )
    fn_game = next(g for g in library.list_games() if g.name == "Fortnite")
    engine = ModsEngine(db, data_root, library, catalog, process_scanner=_EmptyScanner())

    window = GameHubWindow(app)
    try:
        games = library.list_games()
        window.mods_view.set_games([(g, engine.is_game_protected(g)[0]) for g in games])
        window.show_mods()
        assert window._pages.currentWidget() is window.mods_view
        assert window.game_page._tabs.count() == 3

        # Protected game shows friendly lock card and hides normal action controls
        window.mods_view.panel.present_state(engine.get_state(fn_game.id))
        assert not window.mods_view.panel._lock_card.isHidden()
        assert window.mods_view.panel._normal_box.isHidden()

        # Single-player game shows normal controls and Arabic RTL labels cleanly
        window.mods_view.panel.present_state(engine.get_state(sp_game_id))
        assert window.mods_view.panel._lock_card.isHidden()
        assert not window.mods_view.panel._normal_box.isHidden()

        apply_language(app, "ar")
        window.retranslate_ui()
        assert app.layoutDirection() == Qt.LayoutDirection.RightToLeft
        assert window._nav_mods.text() == "التعريبات والمودات"
        assert window.mods_view.panel._restore_btn.text() == "استرجاع اللعبة الأصلية"
        assert "المودات والتعريبات مقفولة" in window.mods_view.panel._lock_message.text()

        # Search filters game list
        window.mods_view._search.setText("Fort")
        assert window.mods_view._games_layout.count() == 2  # 1 button + stretch
    finally:
        apply_language(app, "en")
        window.close()
