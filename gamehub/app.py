"""Start the Game Hub desktop application and its notification-area icon."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QCloseEvent, QImageReader
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QSystemTrayIcon,
)

from gamehub.core.audio.recorder import AudioRecorder
from gamehub.core.capture.scheduler import CaptureScheduler
from gamehub.core.capture.service import CaptureService
from gamehub.core.capture.windows import WgcCapture, WindowProbe
from gamehub.core.events import EventBus
from gamehub.core.hotkeys.windows import (
    MOD_ALT,
    MOD_CONTROL,
    RECORD_NOTE_ID,
    GlobalHotkeys,
)
from gamehub.core.library.epic import EpicDetector
from gamehub.core.library.models import LibraryChanged
from gamehub.core.library.service import LibraryService
from gamehub.core.library.steam import SteamDetector
from gamehub.core.library.xbox import XboxDetector
from gamehub.core.sessions.models import GameStarted, GameStopped, SessionIdentity
from gamehub.core.sessions.processes import ProcessProbe
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.sessions.watcher import SessionWatcher
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository
from gamehub.modules.memory.notes_controller import NotesController
from gamehub.single_instance import SingleInstance
from gamehub.ui.last_moments import LastMomentsDialog
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
        self.tray.activated.connect(self._tray_activated)
        self._tracked_games: set[str] = set()
        self._recording = False

        self.tray_menu = QMenu(self)
        self.tray_menu.addAction("Open Game Hub", self.reveal)
        self.tray_menu.addAction("Quit", app.quit)
        self._tray_status = self.tray_menu.addAction("")
        self._tray_status.setEnabled(False)
        self.tray.setContextMenu(self.tray_menu)
        self._show_tracking_status()

    def game_started(self, event: GameStarted) -> None:
        self._tracked_games.add(event.game_id)
        self._show_tracking_status()

    def game_stopped(self, event: GameStopped) -> None:
        self._tracked_games.discard(event.game_id)
        self._show_tracking_status()

    def set_recording(self, recording: bool) -> None:
        self._recording = recording
        self._show_tracking_status()

    def notify(self, message: str) -> None:
        if self.tray.isVisible():
            self.tray.showMessage("Game Hub", message)
        else:
            self.library.show_error(message)

    def _show_tracking_status(self) -> None:
        count = len(self._tracked_games)
        if self._recording:
            text = self.tr("Recording voice note")
        elif count == 0:
            text = self.tr("Watching for games")
        elif count == 1:
            text = self.tr("Tracking 1 game")
        else:
            text = self.tr("Tracking {count} games").format(count=count)
        self._tray_status.setText(text)
        self.tray.setToolTip(f"Game Hub · {text}")

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
    watcher = None
    capture_scheduler = None
    notes_controller = None
    hotkeys = None
    try:
        if not instance.claim_or_activate():
            return 0

        log_handler = _add_file_log(data_root)
        database = Database(data_root / "gamehub.db")
        detectors = () if smoke_test else (SteamDetector(), EpicDetector(), XboxDetector())
        events = EventBus(window)
        library = LibraryRepository(database)
        screenshots = _open_screenshot_store(database, data_root)
        service = LibraryService(library, detectors, events.publish)
        window.library.present_games(service.current().games)
        controller = LibraryController(window.library, service)
        window.library.lastMomentsRequested.connect(
            lambda game_id: _open_last_moments(window, library, screenshots, game_id)
        )
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        app.setQuitOnLastWindowClosed(not tray_available)
        if tray_available:
            window.tray.show()
        window.show()
        if smoke_test:
            _check_capture_runtime()
            _check_audio_runtime()
            QTimer.singleShot(0, app.quit)
        else:
            events.subscribe(GameStarted, window.game_started)
            events.subscribe(GameStopped, window.game_stopped)
            events.subscribe(GameStarted, controller.session_updated)
            events.subscribe(GameStopped, controller.session_updated)
            sessions = SessionRepository(database)
            tracker = SessionTracker(sessions, events.publish)
            watcher = SessionWatcher(sessions, ProcessProbe(), tracker)
            events.subscribe(LibraryChanged, watcher.library_changed)
            watcher.start()
            windows = _open_window_probe()
            notes_controller, hotkeys = _start_notes(app, window, database, data_root, library, windows, tracker)
            if notes_controller is not None:
                events.subscribe(GameStopped, notes_controller.game_stopped)
            if screenshots is not None and windows is not None:
                try:
                    capture_service = CaptureService(windows, tracker, WgcCapture(), screenshots)
                    capture_scheduler = CaptureScheduler(capture_service, window)
                    capture_scheduler.start()
                except (OSError, RuntimeError):
                    logging.getLogger("gamehub").warning("capture_startup_unavailable")
            QTimer.singleShot(0, controller.refresh)
        return app.exec()
    finally:
        if hotkeys is not None:
            hotkeys.close()
        if notes_controller is not None:
            notes_controller.close()
        window.tray.hide()
        if capture_scheduler is not None:
            capture_scheduler.close()
        if watcher is not None:
            watcher.close()
        if controller is not None:
            controller.close()
        if log_handler is not None:
            logging.getLogger("gamehub").removeHandler(log_handler)
            log_handler.close()
        instance.close()


def _open_window_probe() -> WindowProbe | None:
    try:
        return WindowProbe()
    except OSError:
        logging.getLogger("gamehub").warning("foreground_probe_unavailable")
        return None


def _start_notes(
    app: QApplication,
    window: GameHubWindow,
    database: Database,
    data_root: Path,
    library: LibraryRepository,
    windows: WindowProbe | None,
    tracker: SessionTracker,
) -> tuple[NotesController | None, GlobalHotkeys | None]:
    def foreground_session() -> SessionIdentity | None:
        foreground = windows.foreground() if windows is not None else None
        return tracker.active_for(foreground.process) if foreground is not None else None

    try:
        repository = NoteRepository(database, data_root)
        controller = NotesController(
            window, repository, library, AudioRecorder(),
            foreground_session, window.set_recording, window.notify,
        )
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("note_store_unavailable")
        return None, None

    try:
        repository.recover_files()
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("note_recovery_incomplete")
    if windows is None:
        return controller, None
    try:
        hotkeys = GlobalHotkeys(app)
    except OSError:
        logging.getLogger("gamehub").warning("note_hotkeys_unavailable")
        return controller, None
    if not hotkeys.bind(RECORD_NOTE_ID, MOD_CONTROL | MOD_ALT, ord("N"), controller.toggle_hotkey):
        window.notify(window.tr("Ctrl+Alt+N is unavailable. You can record from the game-close prompt."))
    return controller, hotkeys


def _check_capture_runtime() -> None:
    from inspect import signature

    from windows_capture import WindowsCapture

    if "window_hwnd" not in signature(WindowsCapture).parameters:
        raise RuntimeError("The exact-window capture adapter is unavailable.")
    if b"webp" not in QImageReader.supportedImageFormats():
        raise RuntimeError("The Qt WebP reader is unavailable.")


def _check_audio_runtime() -> None:
    from sounddevice import get_portaudio_version
    from soundfile import check_format

    if not get_portaudio_version() or not check_format("OGG", "VORBIS"):
        raise RuntimeError("The local audio recorder is unavailable.")


def _open_screenshot_store(database: Database, data_root: Path) -> ScreenshotRepository | None:
    try:
        screenshots = ScreenshotRepository(database, data_root)
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("capture_store_unavailable")
        return None
    try:
        screenshots.recover_files()
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("capture_recovery_incomplete")
    return screenshots


def _open_last_moments(
    window: GameHubWindow,
    library: LibraryRepository,
    screenshots: ScreenshotRepository | None,
    game_id: str,
) -> None:
    if screenshots is None:
        window.library.show_error("Game Hub could not open your screenshot folder.")
        return
    try:
        game = library.get_game(game_id)
        if game is None:
            return
        images = screenshots.last_moments(game_id)
    except (OSError, StorageError):
        window.library.show_error("Game Hub could not load the screenshots for this game.")
        return
    LastMomentsDialog(game.name, images, window, load_image=screenshots.read_image).exec()


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
