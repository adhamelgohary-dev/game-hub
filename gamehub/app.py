"""Start the Game Hub desktop application and its notification-area icon."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QSystemTrayIcon,
)

from gamehub.core.library.epic import EpicDetector
from gamehub.core.library.service import LibraryService
from gamehub.core.library.steam import SteamDetector
from gamehub.core.library.xbox import XboxDetector
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.single_instance import SingleInstance
from gamehub.ui.library_controller import LibraryController
from gamehub.ui.library_view import LibraryView


class GameHubWindow(QMainWindow):
    """The library window stays available through the tray after closing."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.setWindowTitle("Game Hub")
        self.resize(720, 480)

        self.library = LibraryView(self)
        self.setCentralWidget(self.library)

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Game Hub")
        self.tray.activated.connect(self._tray_activated)

        self.tray_menu = QMenu(self)
        self.tray_menu.addAction("Open Game Hub", self.reveal)
        self.tray_menu.addAction("Quit", app.quit)
        self.tray.setContextMenu(self.tray_menu)

    def reveal(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            super().closeEvent(event)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.reveal()


def _run(app: QApplication, data_root: Path, *, smoke_test: bool) -> int:
    window = GameHubWindow(app)
    instance = SingleInstance(data_root, window.reveal)
    controller = None
    log_handler = None
    try:
        if not instance.claim_or_activate():
            return 0

        log_handler = _add_file_log(data_root)
        database = Database(data_root / "gamehub.db")
        detectors = () if smoke_test else (SteamDetector(), EpicDetector(), XboxDetector())
        service = LibraryService(LibraryRepository(database), detectors)
        window.library.present_games(service.current().games)
        controller = LibraryController(window.library, service)
        if QSystemTrayIcon.isSystemTrayAvailable():
            window.tray.show()
        window.show()
        if smoke_test:
            QTimer.singleShot(0, app.quit)
        else:
            QTimer.singleShot(0, controller.refresh)
        return app.exec()
    finally:
        window.tray.hide()
        if controller is not None:
            controller.close()
        if log_handler is not None:
            logging.getLogger("gamehub").removeHandler(log_handler)
            log_handler.close()
        instance.close()


def _add_file_log(data_root: Path) -> logging.Handler | None:
    folder = data_root / "logs"
    try:
        folder.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            folder / "gamehub.log", maxBytes=256 * 1024, backupCount=2, encoding="utf-8"
        )
    except OSError:
        return None
    logger = logging.getLogger("gamehub")
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    return handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open Game Hub.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Build the window and tray, enter the event loop, and exit.",
    )
    args = parser.parse_args(argv)
    app = QApplication(["Game Hub"])
    app.setApplicationName("Game Hub")

    if args.smoke_test:
        with TemporaryDirectory(prefix="gamehub-smoke-") as temp_dir:
            return _run(app, Path(temp_dir), smoke_test=True)

    local_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    try:
        return _run(app, Path(local_data) / "GameHub", smoke_test=False)
    except (OSError, RuntimeError, StorageError):
        QMessageBox.critical(
            None, "Game Hub", "Game Hub could not start. Check that your local data folder is available."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
