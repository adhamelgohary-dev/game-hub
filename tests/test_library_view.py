import os
from pathlib import Path

import pytest
from PIL import Image
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


def test_library_displays_cover_cards_empty_state_and_filters(
    library: LibraryView, tmp_path: Path
) -> None:
    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (460, 215), (30, 120, 200)).save(cover, format="JPEG")
    full_game = GameSummary(
        id="steam-example",
        name="A <Game>",
        source=GameSource.STEAM,
        install_dir=tmp_path,
        cover_path=cover,
        last_played=None,
        total_playtime=3661,
        installed=True,
        launch_target=None,
        tracking=True,
        protection_mode="full",
    )
    strict_game = GameSummary(
        id="strict-example",
        name="Tactical Arena",
        source=GameSource.EPIC,
        install_dir=tmp_path,
        cover_path=None,
        last_played=1_000_000,
        total_playtime=120,
        installed=True,
        launch_target=None,
        tracking=True,
        protection_mode="strict",
    )
    assert library._empty.isVisible()
    library.present_games([full_game, strict_game])
    assert library._scroll.isVisible()
    assert len(library.cards()) == 2
    assert "&lt;Game&gt;" in library.cards()[0].toolTip()
    assert not library.cards()[0]._cover.pixmap().isNull()
    assert not library.cards()[1]._cover.pixmap().isNull()
    assert library.cards()[0]._details_btn.text() == "Details"
    assert library.cards()[0]._play_btn.text() == "Play"

    # Filter chips filter between All, Full, and Strict
    library._chip_strict.click()
    assert [card.game_id for card in library.cards()] == ["strict-example"]
    library._chip_full.click()
    assert [card.game_id for card in library.cards()] == ["steam-example"]
    library._chip_all.click()
    assert len(library.cards()) == 2

    # Search filters by name case-insensitively
    library._search.setText("tactical")
    assert [card.game_id for card in library.cards()] == ["strict-example"]
    library._search.setText("nonexistent")
    assert library.cards() == ()
    assert library._empty.isVisible()
    library._search.clear()
    assert len(library.cards()) == 2

    library.present_games([])
    assert library._empty.isVisible()


def test_library_card_signals_click_and_keyboard(
    library: LibraryView, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    picked = iter(["", path])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (next(picked), ""))
    library.refreshRequested.connect(lambda: events.append("refresh"))
    library.addRequested.connect(lambda selection: events.append(("add", selection)))
    library.playRequested.connect(lambda game_id: events.append(("play", game_id)))
    library.gameOpened.connect(lambda game_id: events.append(("open", game_id)))

    QTest.keyClick(library._refresh, Qt.Key.Key_Space)
    library._add.click()
    assert events == ["refresh"]
    library._add.click()
    library.present_games([game])
    assert library.selected_game() is None
    assert len(library.cards()) == 1
    card = library.cards()[0]

    # Clicking Play and Details buttons emits signals and selects the card
    card._play_btn.click()
    assert library.selected_game() == game.id
    card._details_btn.click()
    # Whole card is clickable and keyboard-activatable
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    QTest.keyClick(card, Qt.Key.Key_Return)
    assert events == [
        "refresh",
        ("add", path),
        ("play", game.id),
        ("open", game.id),
        ("open", game.id),
        ("open", game.id),
    ]


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
