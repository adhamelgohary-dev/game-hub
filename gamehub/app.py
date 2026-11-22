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
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
)

from gamehub.core.audio.player import VoicePlayer
from gamehub.core.audio.recorder import AudioRecorder
from gamehub.core.capture.scheduler import CaptureScheduler
from gamehub.core.capture.service import CaptureService
from gamehub.core.capture.windows import WgcCapture, WindowProbe
from gamehub.core.events import EventBus
from gamehub.core.hotkeys.windows import (
    LAST_TIME_ID,
    MOD_ALT,
    MOD_CONTROL,
    PIN_CONTROLS_ID,
    RECORD_NOTE_ID,
    GlobalHotkeys,
)
from gamehub.core.library.epic import EpicDetector
from gamehub.core.library.launcher import LaunchCoordinator, WindowsLauncher
from gamehub.core.library.models import LibraryChanged
from gamehub.core.library.service import LibraryService
from gamehub.core.library.steam import SteamDetector
from gamehub.core.library.xbox import XboxDetector
from gamehub.core.sessions.models import GameStarted, GameStopped, SessionIdentity
from gamehub.core.sessions.processes import ProcessProbe
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.sessions.watcher import SessionWatcher
from gamehub.core.storage.controls import ControlsRepository
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.memory import MemoryChanged, MemoryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository
from gamehub.modules.memory.controls_controller import ControlsController
from gamehub.modules.memory.last_time_controller import LastTimeController
from gamehub.modules.memory.notes_controller import NotesController
from gamehub.single_instance import SingleInstance
from gamehub.ui.game_page import GamePage
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
        self.game_page = GamePage(self)
        self._pages = QStackedWidget(self)
        self._pages.addWidget(self.library)
        self._pages.addWidget(self.game_page)
        self.setCentralWidget(self._pages)

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
        elif self._pages.currentWidget() is self.game_page:
            self.game_page.show_error(message)
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

    def show_library(self) -> None:
        self._pages.setCurrentWidget(self.library)

    def show_game_page(self) -> None:
        self._pages.setCurrentWidget(self.game_page)

    def is_game_page_open(self, game_id: str) -> bool:
        return self._pages.currentWidget() is self.game_page and self.game_page.game_id == game_id

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
    last_time_controller = None
    controls_controller = None
    voice_player = None
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
        controls = _open_controls_store(database, data_root)
        memory = _open_memory_store(database, data_root)
        service = LibraryService(library, detectors, events.publish)
        window.library.present_games(service.current().games)
        controller = LibraryController(window.library, service)
        window.library.lastMomentsRequested.connect(
            lambda game_id: _open_last_moments(window, library, screenshots, game_id)
        )
        window.game_page.set_loaders(
            load_control_image=controls.read_image if controls is not None else (lambda _p: None),
            load_screenshot=screenshots.read_image if screenshots is not None else (lambda _p: None),
        )
        window.game_page.backRequested.connect(window.show_library)
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
            launcher = LaunchCoordinator(WindowsLauncher(), events.publish)
            tracker = SessionTracker(sessions, events.publish, launcher.claim)
            watcher = SessionWatcher(sessions, ProcessProbe(), tracker)
            events.subscribe(LibraryChanged, watcher.library_changed)
            windows = _open_window_probe()

            def foreground_session() -> SessionIdentity | None:
                foreground = windows.foreground() if windows is not None else None
                return tracker.active_for(foreground.process) if foreground is not None else None

            if screenshots is not None and windows is not None:
                try:
                    capture_service = CaptureService(windows, tracker, WgcCapture(), screenshots)
                    capture_scheduler = CaptureScheduler(capture_service, window)
                except (OSError, RuntimeError):
                    logging.getLogger("gamehub").warning("capture_startup_unavailable")

            notes_controller = _start_notes(
                window, database, data_root, library, foreground_session, events.publish
            )
            if notes_controller is not None:
                events.subscribe(GameStopped, notes_controller.game_stopped)

            voice_player = _open_voice_player(window)
            last_time_controller = _start_last_time(
                window, memory, screenshots, controls, voice_player, launcher, foreground_session
            )
            if last_time_controller is not None:
                events.subscribe(GameStarted, last_time_controller.game_started)
                events.subscribe(GameStopped, last_time_controller.game_stopped)
                window.library.playRequested.connect(last_time_controller.open_play_preview)
                window.game_page.playRequested.connect(last_time_controller.open_play_preview)
            else:
                window.library.playRequested.connect(
                    lambda _game_id: window.library.show_error(
                        window.tr("Game Hub could not open the Last time card.")
                    )
                )
                window.game_page.playRequested.connect(
                    lambda _game_id: window.game_page.show_error(
                        window.tr("Game Hub could not open the Last time card.")
                    )
                )

            if controls is not None:
                controls_controller = ControlsController(
                    window,
                    controls,
                    capture_scheduler.pin_foreground if capture_scheduler is not None else None,
                    events.publish,
                    window.notify,
                )
                window.game_page.uploadControlImageRequested.connect(controls_controller.import_image)
                window.game_page.saveControlTextRequested.connect(controls_controller.save_text)

                def _controls_error(game_id: str, msg: str) -> None:
                    if window.is_game_page_open(game_id):
                        window.game_page.set_saving_control_text(False)
                        window.game_page.show_error(msg)

                controls_controller.errorOccurred.connect(_controls_error)
            else:
                def _controls_unavailable(*_args) -> None:
                    window.game_page.set_saving_control_text(False)
                    window.game_page.show_error(
                        window.tr("Game Hub could not access your controls storage.")
                    )

                window.game_page.uploadControlImageRequested.connect(_controls_unavailable)
                window.game_page.saveControlTextRequested.connect(_controls_unavailable)

            _wire_game_page(window, library, controls, memory, voice_player, events)
            hotkeys = _start_hotkeys(
                app, window, windows, notes_controller, last_time_controller, controls_controller
            )
            watcher.start()
            if capture_scheduler is not None:
                capture_scheduler.start()
            QTimer.singleShot(0, controller.refresh)
        return app.exec()
    finally:
        if hotkeys is not None:
            hotkeys.close()
        if voice_player is not None:
            voice_player.stop()
        if controls_controller is not None:
            controls_controller.close()
        if last_time_controller is not None:
            last_time_controller.close()
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
    window: GameHubWindow,
    database: Database,
    data_root: Path,
    library: LibraryRepository,
    foreground_session,
    publish,
) -> NotesController | None:
    try:
        repository = NoteRepository(database, data_root)
        controller = NotesController(
            window, repository, library, AudioRecorder(),
            foreground_session, window.set_recording, window.notify,
            publish=publish,
        )
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("note_store_unavailable")
        return None

    try:
        repository.recover_files()
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("note_recovery_incomplete")
    return controller


def _open_voice_player(window: GameHubWindow) -> VoicePlayer | None:
    try:
        return VoicePlayer(window)
    except (OSError, RuntimeError):
        logging.getLogger("gamehub").warning("voice_player_unavailable")
        return None


def _open_controls_store(database: Database, data_root: Path) -> ControlsRepository | None:
    try:
        controls = ControlsRepository(database, data_root)
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("controls_store_unavailable")
        return None
    try:
        controls.recover_files()
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("controls_recovery_incomplete")
    return controls


def _open_memory_store(database: Database, data_root: Path) -> MemoryRepository | None:
    try:
        return MemoryRepository(database, data_root)
    except (OSError, StorageError):
        logging.getLogger("gamehub").warning("memory_store_unavailable")
        return None


def _start_last_time(
    window: GameHubWindow,
    memory: MemoryRepository | None,
    screenshots: ScreenshotRepository | None,
    controls: ControlsRepository | None,
    player: VoicePlayer | None,
    launcher: LaunchCoordinator,
    foreground_session,
) -> LastTimeController | None:
    if memory is None or player is None:
        return None

    load_image = screenshots.read_image if screenshots is not None else (lambda _path: None)
    load_control_image = controls.read_image if controls is not None else (lambda _path: None)
    return LastTimeController(
        window,
        memory,
        load_image,
        player,
        launcher,
        foreground_session,
        window.library.selected_game,
        window.reveal,
        window.notify,
        load_control_image=load_control_image,
    )


def _wire_game_page(
    window: GameHubWindow,
    library: LibraryRepository,
    controls: ControlsRepository | None,
    memory: MemoryRepository | None,
    player: VoicePlayer | None,
    events: EventBus,
) -> None:
    def open_game(game_id: str) -> None:
        if memory is None:
            window.library.show_error(window.tr("Game Hub could not load this game's history."))
            return
        try:
            game = library.get_game(game_id)
            if game is None:
                return
            control_items = controls.list_controls(game_id) if controls is not None else ()
            page = memory.timeline(game_id)
        except (OSError, StorageError):
            window.library.show_error(window.tr("Game Hub could not load this game's history."))
            return
        if player is not None:
            player.stop()
        window.game_page.show_game(game, control_items, page)
        window.show_game_page()

    def load_more(game_id: str, cursor) -> None:
        if memory is None or not window.is_game_page_open(game_id):
            return
        try:
            page = memory.timeline(game_id, cursor=cursor)
        except (OSError, StorageError):
            window.game_page.show_error(window.tr("Game Hub could not load earlier sessions."))
            return
        window.game_page.present_timeline(page, append=True)

    def refresh_timeline(game_id: str) -> None:
        if not window.is_game_page_open(game_id) or memory is None:
            return
        try:
            game = library.get_game(game_id)
            if game is None:
                return
            control_items = controls.list_controls(game_id) if controls is not None else ()
            page = memory.timeline(game_id)
        except (OSError, StorageError):
            return
        window.game_page.show_game(game, control_items, page)

    def handle_memory_changed(event: MemoryChanged) -> None:
        if not window.is_game_page_open(event.game_id):
            return
        if event.item_kind in {"control_image", "control_text"}:
            if controls is None:
                return
            try:
                control_items = controls.list_controls(event.game_id)
            except (OSError, StorageError):
                return
            window.game_page.present_controls(
                control_items, select_latest=event.item_kind == "control_image"
            )
            if event.item_kind == "control_text":
                window.game_page.clear_control_input()
        else:
            refresh_timeline(event.game_id)

    def play_voice(path: Path) -> None:
        if player is None or memory is None:
            window.game_page.reset_voice_state()
            window.game_page.show_error(window.tr("Voice playback is unavailable."))
            return
        clip = memory.read_voice(path)
        if clip is None:
            window.game_page.reset_voice_state()
            window.game_page.show_error(window.tr("This voice note is unavailable."))
            return
        if not player.play(clip):
            window.game_page.reset_voice_state()
            window.game_page.show_error(window.tr("Game Hub could not play this voice note."))

    window.library.gameOpened.connect(open_game)
    window.game_page.loadMoreTimelineRequested.connect(load_more)
    window.game_page.playVoiceNoteRequested.connect(play_voice)
    if player is not None:
        window.game_page.stopVoiceNoteRequested.connect(player.stop)
        player.playingChanged.connect(window.game_page.set_voice_playing)
        player.failed.connect(
            lambda: (
                window.game_page.reset_voice_state(),
                window.game_page.show_error(window.tr("Game Hub could not play this voice note."))
                if window.game_page.game_id is not None
                else None,
            )
        )
    events.subscribe(MemoryChanged, handle_memory_changed)
    events.subscribe(GameStarted, lambda event: refresh_timeline(event.game_id))
    events.subscribe(GameStopped, lambda event: refresh_timeline(event.game_id))


def _start_hotkeys(
    app: QApplication,
    window: GameHubWindow,
    windows: WindowProbe | None,
    notes_controller: NotesController | None,
    last_time_controller: LastTimeController | None,
    controls_controller: ControlsController | None,
) -> GlobalHotkeys | None:
    if (
        notes_controller is None
        and last_time_controller is None
        and controls_controller is None
    ):
        return None
    try:
        hotkeys = GlobalHotkeys(app)
    except OSError:
        logging.getLogger("gamehub").warning("hotkeys_unavailable")
        return None

    if (
        notes_controller is not None
        and windows is not None
        and not hotkeys.bind(RECORD_NOTE_ID, MOD_CONTROL | MOD_ALT, ord("N"), notes_controller.toggle_hotkey)
    ):
        window.notify(
            window.tr("Ctrl+Alt+N is unavailable. You can record from the game-close prompt.")
        )
    if (
        last_time_controller is not None
        and not hotkeys.bind(LAST_TIME_ID, MOD_CONTROL | MOD_ALT, ord("L"), last_time_controller.reopen_hotkey)
    ):
        window.notify(
            window.tr("Ctrl+Alt+L is unavailable. You can open Last time from Play in Library.")
        )
    if (
        controls_controller is not None
        and not hotkeys.bind(PIN_CONTROLS_ID, MOD_CONTROL | MOD_ALT, ord("C"), controls_controller.pin_hotkey)
    ):
        window.notify(
            window.tr("Ctrl+Alt+C is unavailable. You can upload controls images from the game page.")
        )
    return hotkeys


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
    player = VoicePlayer()
    try:
        if not player.is_available():
            raise RuntimeError("The Qt Multimedia audio backend is unavailable.")
    finally:
        player.stop()


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
