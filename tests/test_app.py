import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from gamehub.app import GameHubWindow
from gamehub.single_instance import SingleInstance


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
