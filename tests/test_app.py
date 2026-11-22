import os
import subprocess
import sys
from pathlib import Path

import psutil
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QTableWidget

from gamehub import app as gamehub_app
from gamehub.app import GameHubWindow
from gamehub.core.library.service import LibraryService
from gamehub.core.sessions.models import GameStarted, GameStopped
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.single_instance import SingleInstance
from gamehub.ui.library_controller import LibraryController


@pytest.fixture(scope="module")
def app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Game Hub test"])


def test_window_has_no_tray_and_closes_cleanly(app: QApplication) -> None:
    window = GameHubWindow(app)
    window.show()
    try:
        assert window.isVisible()
        assert window.windowTitle() == "Game Hub"
        assert not hasattr(window, "tray")
        assert not hasattr(window, "tray_menu")
        assert window.statusBar().currentMessage() == "Watching for games"
        window.game_started(GameStarted("game", "session", 0))
        assert window.statusBar().currentMessage() == "Tracking 1 game"
        window.game_stopped(GameStopped("game", "session", 5000, 5, "completed", "process_exit"))
        assert window.statusBar().currentMessage() == "Watching for games"
        assert window.close() is True
        assert not window.isVisible()
    finally:
        window.close()


def test_closing_main_window_exits_process_with_no_residual_processes(tmp_path: Path) -> None:
    script = f"""
import os
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from gamehub import app as gamehub_app

os.environ["QT_QPA_PLATFORM"] = "offscreen"
qt_app = QApplication(["Game Hub"])
orig_window = gamehub_app.GameHubWindow

class AutoCloseWindow(orig_window):
    def show(self):
        super().show()
        QTimer.singleShot(250, self.close)

gamehub_app.GameHubWindow = AutoCloseWindow
code = gamehub_app._run(qt_app, Path({str(tmp_path)!r}), smoke_test=False)
raise SystemExit(code)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _, stderr = proc.communicate(timeout=20)
        assert proc.returncode == 0, stderr
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    assert not psutil.pid_exists(proc.pid)


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


def test_screenshot_root_failure_leaves_library_storage_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "gamehub.db")

    def unavailable(*_):
        raise StorageError("Unsafe screenshot location")

    monkeypatch.setattr(gamehub_app, "ScreenshotRepository", unavailable)
    assert gamehub_app._open_screenshot_store(database, tmp_path) is None
    assert LibraryRepository(database).list_games() == ()
