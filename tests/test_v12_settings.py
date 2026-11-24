"""Tests for M17: 5 plain-language grouped Settings, explanations, SteamGridDB controls, Scan folders UI, and Reset to defaults."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from gamehub.core.i18n import apply_language
from gamehub.core.library.models import DetectedGame, DiscoveryBatch, GameSource
from gamehub.core.settings import SettingsService, SettingsSnapshot
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.ui.settings_view import SettingsView


def test_settings_view_five_groups_plain_explanations_and_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication(["Game Hub test"])
    view = SettingsView()
    view.show()
    try:
        # 5 clear groups exist with plain EN titles
        assert view._lang_group.title() == "General"
        assert view._capture_group.title() == "Capture and notes"
        assert view._protection_group.title() == "Protected games"
        assert view._data_group.title() == "Library and folders"
        assert view._about_group.title() == "About and privacy"

        # Plain-language one-line hints populated under every setting
        for hint in (
            view._lang_hint,
            view._theme_hint,
            view._interval_hint,
            view._buffer_hint,
            view._autoplay_hint,
            view._prompt_on_end_hint,
            view._hk_record_hint,
            view._hk_last_hint,
            view._hk_pin_hint,
            view._external_behavior_hint,
            view._launchers_hint,
            view._test_protection_hint,
            view._scan_folders_hint,
            view._sgdb_hint,
            view._sgdb_key_hint,
            view._data_folder_hint,
            view._reset_defaults_hint,
        ):
            assert hint.text().strip()

        # SteamGridDB is OFF by default and disables API key input + Fetch button until enabled
        view.load_settings(SettingsSnapshot(), tmp_path)
        assert not view._sgdb_enabled.isChecked()
        assert not view._sgdb_api_key.isEnabled()
        assert not view._fetch_covers_btn.isEnabled()

        view._sgdb_enabled.setChecked(True)
        assert view._sgdb_api_key.isEnabled()
        assert not view._fetch_covers_btn.isEnabled()
        view._sgdb_api_key.setText("my-sgdb-key")
        assert view._fetch_covers_btn.isEnabled()

        saved: list[dict] = []
        view.saveRequested.connect(saved.append)
        view._save.click()
        assert saved[-1]["covers.steamgriddb_enabled"] is True
        assert saved[-1]["covers.steamgriddb_api_key"] == "my-sgdb-key"

        # Scan folders manager lists folders and emits rescan / remove
        folder_a = tmp_path / "GamesA"
        folder_a.mkdir()
        view.set_scan_folders([folder_a])
        assert view._scan_folders_layout.count() == 1

        # Reset to defaults asks confirmation and emits signal on Yes
        resets: list[bool] = []
        view.resetDefaultsRequested.connect(lambda: resets.append(True))
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_kw: QMessageBox.StandardButton.No
        )
        view._reset_defaults_btn.click()
        assert resets == []
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_a, **_kw: QMessageBox.StandardButton.Yes
        )
        view._reset_defaults_btn.click()
        assert resets == [True]

        # Switching to Arabic translates all 5 group headings cleanly
        apply_language(app, "ar")
        view.retranslate_ui()
        assert view._lang_group.title() == "عام"
        assert view._capture_group.title() == "اللقطات والملاحظات"
        assert view._protection_group.title() == "الألعاب المحمية"
        assert view._data_group.title() == "المكتبة والمجلدات"
        assert view._about_group.title() == "حول البرنامج والخصوصية"
    finally:
        apply_language(app, "en")
        view.close()
        app.processEvents()


def test_reset_to_defaults_restores_settings_and_protection_without_deleting_games(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "gamehub.db")
    settings = SettingsService(db)
    library = LibraryRepository(db)

    game = DetectedGame(GameSource.RIOT, "valorant.live", "VALORANT", tmp_path)
    library.reconcile(GameSource.RIOT, DiscoveryBatch((game,), "complete"))
    gid = library.list_games()[0].id
    library.set_protection(gid, "full", exit_after_launch=False)

    res = settings.update(
        {
            "ui.theme": "light",
            "capture.interval_sec": 60,
            "protection.strict_launcher.epic": True,
            "covers.steamgriddb_enabled": True,
            "covers.steamgriddb_api_key": "abc123",
        }
    )
    assert res.ok
    assert res.snapshot.strict_launcher_epic is True
    assert res.snapshot.steamgriddb_enabled is True

    reset_res = settings.reset_to_defaults()
    library.reset_protection_defaults()
    assert reset_res.ok
    assert reset_res.snapshot.theme == "dark"
    assert reset_res.snapshot.capture_interval_sec == 30
    assert reset_res.snapshot.strict_launcher_epic is False
    assert reset_res.snapshot.steamgriddb_enabled is False
    assert reset_res.snapshot.steamgriddb_api_key == ""
    reloaded = library.get_game(gid)
    assert reloaded is not None
    assert reloaded.protection_mode == "auto"


def test_arabic_user_guide_documents_v12_settings_in_egyptian_arabic() -> None:
    guide = Path("docs/USER-GUIDE-AR.md").read_text(encoding="utf-8")
    assert "شرح الإعدادات" in guide
    assert "SteamGridDB" in guide
    assert "اختبار الحماية" in guide
    assert "Reset to defaults" in guide
    assert "System Tray" not in guide or "لا System Tray" in guide
