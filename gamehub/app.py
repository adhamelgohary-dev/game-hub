"""Start the Game Hub desktop application and its notification-area icon."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from gamehub.single_instance import SingleInstance


class GameHubWindow(QMainWindow):
    """The library window stays available through the tray after closing."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.setWindowTitle("Game Hub")
        self.resize(720, 480)

        library = QWidget(self)
        layout = QVBoxLayout(library)
        heading = QLabel("Library", library)
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        empty_state = QLabel("No games in your library.", library)
        empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(empty_state, stretch=1)
        self.setCentralWidget(library)

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
    try:
        if not instance.claim_or_activate():
            return 0

        if QSystemTrayIcon.isSystemTrayAvailable():
            window.tray.show()
        window.show()
        if smoke_test:
            QTimer.singleShot(0, app.quit)
        return app.exec()
    finally:
        window.tray.hide()
        instance.close()


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
    except (OSError, RuntimeError) as error:
        QMessageBox.critical(None, "Game Hub", f"Game Hub could not start.\n\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
