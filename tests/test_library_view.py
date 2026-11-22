import os
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from gamehub.core.library.models import GameSource, GameSummary
from gamehub.ui.library_view import LibraryView


@pytest.fixture
def library(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication(["Game Hub test"])
    view = LibraryView()
    view.show()
    yield view
    view.close()
    app.processEvents()


def test_library_displays_read_only_rows_and_empty_state(library: LibraryView, tmp_path: Path) -> None:
    game = GameSummary(
        id="steam-example",
        name="A <Game>",
        source=GameSource.STEAM,
        install_dir=tmp_path,
        cover_path=None,
        last_played=None,
        total_playtime=3661,
        installed=True,
        launch_target=None,
        tracking=False,
    )
    assert library._empty.isVisible()
    library.present_games([game])
    table = library._table
    assert table.isVisible()
    assert table.rowCount() == 1
    assert [table.item(0, column).text() for column in range(table.columnCount())] == [
        "A <Game>", "Steam · Assign executable", str(tmp_path), "Never", "1 h 1 min",
    ]
    assert not table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable
    assert "&lt;Game&gt;" in table.item(0, 0).toolTip()
    library.present_games([replace(game, tracking=True)])
    assert table.item(0, 1).text() == "Steam"
    library.present_games([])
    assert library._empty.isVisible()


def test_library_signals_and_selection(library: LibraryView, monkeypatch: pytest.MonkeyPatch) -> None:
    path = "C:/Games/Example.exe"
    game = GameSummary(
        id="epic-example",
        name="Another game",
        source=GameSource.EPIC,
        install_dir=None,
        cover_path=None,
        last_played=1_000_000,
        total_playtime=0,
        installed=True,
        launch_target=None,
        tracking=False,
    )
    events = []
    picked = iter(["", path, path])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (next(picked), ""))
    library.refreshRequested.connect(lambda: events.append("refresh"))
    library.addRequested.connect(lambda selection: events.append(("add", selection)))
    library.assignRequested.connect(lambda game_id, selection: events.append((game_id, selection)))
    library.lastMomentsRequested.connect(lambda game_id: events.append(("moments", game_id)))

    QTest.keyClick(library._refresh, Qt.Key.Key_Space)
    library._add.click()
    assert events == ["refresh"]
    library._add.click()
    library.present_games([game])
    assert not library._assign.isEnabled()
    assert not library._last_moments.isEnabled()
    assert library._table.item(0, 3).text() != "Never"
    library._table.selectRow(0)
    library.present_games([game])
    library._assign.click()
    QTest.keyClick(library._last_moments, Qt.Key.Key_Space)
    assert events == ["refresh", ("add", path), (game.id, path), ("moments", game.id)]


def test_library_busy_and_error_feedback(library: LibraryView) -> None:
    library.set_busy(True)
    assert not library._refresh.isEnabled()
    assert not library._add.isEnabled()
    assert library._progress.isVisible()
    library.show_error("This executable is unavailable.")
    library.set_busy(False)
    assert library._refresh.isEnabled()
    assert not library._progress.isVisible()
    assert library._error.isVisible()
    assert library._error.text() == "This executable is unavailable."
    library.clear_error()
    assert not library._error.isVisible()
