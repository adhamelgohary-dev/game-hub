import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QTableWidget

from gamehub.app import GameHubWindow
from gamehub.core.library.service import LibraryService
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.single_instance import SingleInstance
from gamehub.ui.library_controller import LibraryController


@pytest.fixture(scope="module")
def app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Game Hub test"])


def test_window_has_tray_and_quit_action(app: QApplication) -> None:
    window = GameHubWindow(app)
    window.show()
    try:
        assert window.isVisible()
        assert window.windowTitle() == "Game Hub"
        assert isinstance(window.tray, QSystemTrayIcon)
        assert not window.tray.icon().isNull()
        assert [action.text() for action in window.tray_menu.actions()] == [
            "Open Game Hub",
            "Quit",
        ]
        if QSystemTrayIcon.isSystemTrayAvailable():
            window.tray.show()
            assert window.tray.isVisible()
            window.close()
            assert not window.isVisible()
            window.tray_menu.actions()[0].trigger()
            assert window.isVisible()
    finally:
        window.tray.hide()
        window.close()


def test_second_instance_activates_primary(app: QApplication, tmp_path: Path) -> None:
    activations = []
    events = QEventLoop(app)

    def activate_primary() -> None:
        activations.append("primary")
        events.quit()

    primary = SingleInstance(tmp_path, activate_primary)
    secondary = SingleInstance(tmp_path, lambda: activations.append("secondary"))
    try:
        assert primary.claim_or_activate()
        assert not secondary.claim_or_activate()
        QTimer.singleShot(1000, events, events.quit)
        events.exec()
        assert activations == ["primary"]
    finally:
        secondary.close()
        primary.close()


def test_entry_point_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gamehub.app", "--smoke-test"],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_library_manual_add_reaches_view_and_persists(app: QApplication, tmp_path: Path) -> None:
    exe = tmp_path / "Example Adventure.exe"
    exe.touch()
    window = GameHubWindow(app)
    database_path = tmp_path / "gamehub.db"
    repository = LibraryRepository(Database(database_path))
    controller = LibraryController(window.library, LibraryService(repository, ()))
    events = QEventLoop(app)
    table = window.library.findChild(QTableWidget)
    table.model().rowsInserted.connect(events.quit)
    deadline = QTimer(events)
    deadline.setSingleShot(True)
    deadline.timeout.connect(events.quit)
    try:
        deadline.start(3000)
        window.library.addRequested.emit(str(exe))
        events.exec()
        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "Example Adventure"
        reopened = LibraryRepository(Database(database_path))
        assert reopened.list_games()[0].name == "Example Adventure"
    finally:
        controller.close()
        window.close()
