import ast
import re
import string
from pathlib import Path

import pytest
from PySide6.QtCore import QDir, QLocale, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gamehub.app import GameHubWindow
from gamehub.core.i18n import apply_language
from gamehub.core.i18n.catalog import AR_CATALOG
from gamehub.core.library.models import GameSource, GameSummary
from gamehub.core.settings import SettingsSnapshot
from gamehub.core.storage.memory import TimelinePage
from gamehub.ui.settings_view import SettingsView


def _placeholders(template: str) -> set[str]:
    formatter = string.Formatter()
    return {
        field_name
        for _, field_name, _, _ in formatter.parse(template)
        if field_name is not None
    }


def test_arabic_catalog_has_full_key_and_placeholder_parity() -> None:
    keys: set[str] = set()
    for path in sorted(Path("gamehub").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)

    missing = sorted(keys - set(AR_CATALOG))
    assert missing == [], f"Missing Arabic translations: {missing}"
    for key in sorted(keys):
        translated = AR_CATALOG[key]
        assert translated.strip(), f"Empty Arabic translation for {key!r}"
        assert _placeholders(translated) == _placeholders(key), (
            f"Placeholder mismatch for {key!r}: {translated!r}"
        )

    # Verify QFileDialog filters contain clean ASCII globs without BiDi control characters.
    for key, sample in (
        ("Windows executables (*.exe)", "game.exe"),
        ("Images (*.png *.jpg *.jpeg *.webp *.bmp)", "keys.png"),
        ("Images (*.png *.jpg *.jpeg *.webp *.bmp)", "keys.bmp"),
    ):
        match = re.search(r"\(([^)]+)\)", AR_CATALOG[key])
        assert match is not None
        globs = match.group(1).split()
        assert QDir.match(globs, sample), f"Arabic filter failed to match {sample}: {globs}"


def test_language_switch_updates_layout_direction_and_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["i18n test"])
    window = GameHubWindow(app)
    try:
        game = GameSummary(
            id="game-1",
            name="Hollow Quest",
            source=GameSource.STEAM,
            install_dir=tmp_path,
            cover_path=None,
            last_played=None,
            total_playtime=90,
            installed=True,
            launch_target=None,
            tracking=True,
        )
        window.library.present_games([game])
        window.game_page.show_game(game, (), TimelinePage(()))
        window.settings_view.load_settings(SettingsSnapshot(language="ar"), tmp_path)

        apply_language(app, "ar")
        window.retranslate_ui()
        assert app.layoutDirection() == Qt.LayoutDirection.RightToLeft
        assert QLocale().language() == QLocale.Language.Arabic
        assert window.library._title.text() == "المكتبة"
        assert window.settings_view._title.text() == "الإعدادات"
        assert window._quit_action.text() == "خروج"
        assert "إجمالي وقت اللعب" in window.game_page._summary.text()
        assert window.library._table.item(0, 2).text() == str(tmp_path)
        assert window.settings_view._data_path_label.text() == str(tmp_path)
        assert (
            window.settings_view._data_path_label.layoutDirection()
            == Qt.LayoutDirection.LeftToRight
        )

        # Switching back to English restores LTR, English locale, and English labels.
        apply_language(app, "en")
        window.retranslate_ui()
        assert app.layoutDirection() == Qt.LayoutDirection.LeftToRight
        assert QLocale().language() == QLocale.Language.English
        assert window.library._title.text() == "Library"
        assert window.settings_view._title.text() == "Settings"
        assert window._quit_action.text() == "Quit"
        assert "Total playtime" in window.game_page._summary.text()
    finally:
        apply_language(app, "en")
        window.close()
        window.deleteLater()
        app.processEvents()


def test_settings_view_emits_patch_and_displays_adjacent_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["settings view test"])
    view = SettingsView()
    view.show()
    submitted: list[dict] = []
    view.saveRequested.connect(submitted.append)
    try:
        view.load_settings(SettingsSnapshot(), tmp_path)
        view._interval.setValue(45)
        view._buffer.setValue(12)
        view._autoplay.setChecked(False)
        view._hk_record.setText("Ctrl+Alt+R")
        view._save.click()

        assert len(submitted) == 1
        assert submitted[0]["capture.interval_sec"] == 45
        assert submitted[0]["capture.buffer_size"] == 12
        assert submitted[0]["memory.autoplay_voice"] is False
        assert submitted[0]["hotkey.record_note"] == "Ctrl+Alt+R"

        view.show_field_errors({"hotkey.record_note": "shortcut_conflict"})
        assert view._error_labels["hotkey.record_note"].isVisible()
        assert "previous shortcut" in view._error_labels["hotkey.record_note"].text().lower()

        backed = []
        view.backRequested.connect(lambda: backed.append(True))
        QTest.keyClick(view, Qt.Key.Key_Escape)
        assert backed == [True]
    finally:
        view.close()
        view.deleteLater()
        app.processEvents()
