"""Start the GameRewind desktop application with zero background footprint."""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImageReader
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gamehub import __version__
from gamehub.core.audio.player import VoicePlayer
from gamehub.core.audio.recorder import AudioRecorder
from gamehub.core.capture.scheduler import CaptureScheduler
from gamehub.core.capture.service import CaptureService
from gamehub.core.capture.windows import WgcCapture, WindowProbe
from gamehub.core.events import EventBus
from gamehub.core.hotkeys.windows import (
    LAST_TIME_ID,
    PIN_CONTROLS_ID,
    RECORD_NOTE_ID,
    GlobalHotkeys,
)
from gamehub.core.i18n import apply_language
from gamehub.core.library.battlenet import BattleNetDetector
from gamehub.core.library.ea import EaDetector
from gamehub.core.library.epic import EpicDetector
from gamehub.core.library.folder_scanner import FolderDetector, scan_folder_candidates
from gamehub.core.library.gog import GogDetector
from gamehub.core.library.itch import ItchDetector
from gamehub.core.library.launcher import LaunchCoordinator, WindowsLauncher
from gamehub.core.library.models import GameSource, LibraryChanged
from gamehub.core.library.riot import RiotDetector
from gamehub.core.library.service import LibraryService
from gamehub.core.library.steam import SteamDetector
from gamehub.core.library.steamgriddb import fetch_steamgriddb_cover
from gamehub.core.library.ubisoft import UbisoftDetector
from gamehub.core.library.xbox import XboxDetector
from gamehub.core.notifications.windows import WindowsNotifier
from gamehub.core.protection.catalog import (
    OVERRIDE_FILENAME,
    CatalogLoadError,
    ProtectedGameDetected,
    ProtectedGameExited,
    ProtectedGamesCatalog,
)
from gamehub.core.protection.guard import (
    ProcessScanner,
    ProtectionCheckError,
    ProtectionGuard,
    ServiceProbe,
    run_dummy_process_protection_test,
)
from gamehub.core.protection.lifecycle import LifecycleCoordinator
from gamehub.core.sessions.models import GameStarted, GameStopped, SessionIdentity
from gamehub.core.sessions.processes import ProcessProbe
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.sessions.watcher import SessionWatcher
from gamehub.core.settings import SettingsChanged, SettingsService, SettingsSnapshot
from gamehub.core.startup import remove_legacy_startup_entry
from gamehub.core.storage.controls import ControlsRepository
from gamehub.core.storage.covers import CoverStore
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.location import (
    StoreLocation,
    migrate_legacy_data_root,
    resolve_data_root,
)
from gamehub.core.storage.memory import MemoryChanged, MemoryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.pending_notes import PendingNoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository
from gamehub.modules.memory.controls_controller import ControlsController
from gamehub.modules.memory.last_time_controller import LastTimeController
from gamehub.modules.memory.notes_controller import NotesController
from gamehub.modules.mods.engine import ModsEngine
from gamehub.modules.mods.models import (
    GameRunningModError,
    ManifestValidationError,
    ModError,
    ProtectedGameModError,
)
from gamehub.single_instance import SingleInstance
from gamehub.ui.covers import clear_cover_cache, set_cover_cache_dir
from gamehub.ui.game_page import GamePage
from gamehub.ui.last_moments import LastMomentsDialog
from gamehub.ui.library_controller import LibraryController
from gamehub.ui.library_view import LibraryView
from gamehub.ui.mods_view import GameModsWidget, ModsView
from gamehub.ui.scan_folders_dialog import ScanFolderDialog
from gamehub.ui.settings_view import SettingsView
from gamehub.ui.theme import apply_theme, fade_in_widget, load_app_icon


class GameHubWindow(QMainWindow):
    """Main desktop window; closing it exits the GameRewind process completely."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self.setWindowTitle("GameRewind")
        self.resize(1120, 740)

        icon = load_app_icon(self)
        self.setWindowIcon(icon)
        app.setWindowIcon(icon)

        shell = QWidget(self)
        shell.setObjectName("canvas")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        # Persistent Fluent sidebar (brand + Library / Settings navigation)
        self._sidebar = QFrame(shell)
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(208)
        side_layout = QVBoxLayout(self._sidebar)
        side_layout.setContentsMargins(14, 18, 14, 18)
        side_layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_icon = QLabel(self._sidebar)
        brand_icon.setFixedSize(28, 28)
        brand_icon.setPixmap(icon.pixmap(28, 28))
        brand_title = QLabel("GameRewind", self._sidebar)
        brand_title.setObjectName("cardTitle")
        brand_row.addWidget(brand_icon)
        brand_row.addWidget(brand_title)
        brand_row.addStretch()
        side_layout.addLayout(brand_row)
        side_layout.addSpacing(14)

        self._nav_library = QPushButton(self.tr("Library"), self._sidebar)
        self._nav_library.setObjectName("navButton")
        self._nav_library.setCursor(Qt.CursorShape.PointingHandCursor)
        self._nav_library.clicked.connect(self.show_library)

        self._nav_mods = QPushButton(
            self.tr("Translations & Mods").replace("&", "&&"), self._sidebar
        )
        self._nav_mods.setObjectName("navButton")
        self._nav_mods.setCursor(Qt.CursorShape.PointingHandCursor)
        self._nav_mods.clicked.connect(self.show_mods)

        self._nav_settings = QPushButton(self.tr("Settings"), self._sidebar)
        self._nav_settings.setObjectName("navButton")
        self._nav_settings.setCursor(Qt.CursorShape.PointingHandCursor)

        side_layout.addWidget(self._nav_library)
        side_layout.addWidget(self._nav_mods)
        side_layout.addWidget(self._nav_settings)
        side_layout.addStretch()

        self.library = LibraryView(shell)
        self.game_page = GamePage(shell)
        self.mods_view = ModsView(shell)
        self.settings_view = SettingsView(shell)
        self._nav_settings.clicked.connect(self.library.settingsRequested)

        self._pages = QStackedWidget(shell)
        self._pages.addWidget(self.library)
        self._pages.addWidget(self.game_page)
        self._pages.addWidget(self.mods_view)
        self._pages.addWidget(self.settings_view)

        shell_layout.addWidget(self._sidebar)
        shell_layout.addWidget(self._pages, stretch=1)
        self.setCentralWidget(shell)

        self._tracked_games: set[str] = set()
        self._recording = False
        self._status_text = ""
        self._sync_nav_state("library")
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
        self.statusBar().showMessage(message, 8000)
        if self._pages.currentWidget() is self.game_page:
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
        self._status_text = text
        self.statusBar().showMessage(text)

    def _sync_nav_state(self, active: str) -> None:
        for name, button in (
            ("library", self._nav_library),
            ("mods", self._nav_mods),
            ("settings", self._nav_settings),
        ):
            button.setProperty("active", name == active)
            button.style().unpolish(button)
            button.style().polish(button)

    def show_library(self) -> None:
        changed = self._pages.currentWidget() is not self.library
        self._pages.setCurrentWidget(self.library)
        self._sync_nav_state("library")
        if changed:
            fade_in_widget(self.library)

    def show_mods(self) -> None:
        changed = self._pages.currentWidget() is not self.mods_view
        self._pages.setCurrentWidget(self.mods_view)
        self._sync_nav_state("mods")
        if changed:
            fade_in_widget(self.mods_view)

    def show_game_page(self) -> None:
        changed = self._pages.currentWidget() is not self.game_page
        self._pages.setCurrentWidget(self.game_page)
        self._sync_nav_state("library")
        if changed:
            fade_in_widget(self.game_page)

    def show_settings(self) -> None:
        changed = self._pages.currentWidget() is not self.settings_view
        self._pages.setCurrentWidget(self.settings_view)
        self._sync_nav_state("settings")
        if changed:
            fade_in_widget(self.settings_view)

    def is_game_page_open(self, game_id: str) -> bool:
        return self._pages.currentWidget() is self.game_page and self.game_page.game_id == game_id

    def retranslate_ui(self) -> None:
        self._nav_library.setText(self.tr("Library"))
        self._nav_mods.setText(self.tr("Translations & Mods").replace("&", "&&"))
        self._nav_settings.setText(self.tr("Settings"))
        self._show_tracking_status()
        self.library.retranslate_ui()
        self.game_page.retranslate_ui()
        self.mods_view.retranslate_ui()
        self.settings_view.retranslate_ui()

    def reveal(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.accept()
        self._app.closeAllWindows()
        self._app.quit()


class _GuardBridge(QObject):
    triggered = Signal(object)
    failed = Signal(str)


def _read_startup_guard_prefs(data_root: Path) -> tuple[str, frozenset[str]]:
    """Read language and optional strict-launcher prefs read-only without creating any files."""
    import json
    import sqlite3
    from contextlib import closing

    db_path = data_root / "gamehub.db"
    if not db_path.is_file():
        return "en", frozenset()
    language = "en"
    enabled: set[str] = set()
    try:
        uri = f"{db_path.absolute().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE key = 'ui.language' "
                "OR key LIKE 'protection.strict_launcher.%'"
            ).fetchall()
        for key, raw in rows:
            try:
                val = json.loads(raw)
            except ValueError:
                continue
            if key == "ui.language" and val in {"en", "ar"}:
                language = val
            elif key.startswith("protection.strict_launcher.") and val is True:
                enabled.add(key.rsplit(".", 1)[-1])
    except sqlite3.Error:
        pass
    return language, frozenset(enabled)


def _disabled_catalog_entries(
    catalog: ProtectedGamesCatalog, library: LibraryRepository
) -> frozenset[str]:
    """Return catalog entry IDs where the user explicitly turned protection Off ('full')."""
    disabled: set[str] = set()
    try:
        basenames_by_game = library.list_target_basenames()
        for game in library.list_games():
            if game.protection_mode != "full":
                continue
            exes = basenames_by_game.get(game.id, ())
            matched = catalog.match_game(game.source, game.source_id, exes)
            if matched is not None:
                disabled.add(matched.id)
    except StorageError:
        pass
    return frozenset(disabled)


def _run(
    app: QApplication,
    data_root: Path,
    *,
    smoke_test: bool,
    default_root: Path | None = None,
    legacy_root: Path | None = None,
    play_game_id: str | None = None,
    catalog_path: Path | None = None,
    process_scanner: ProcessScanner | None = None,
    service_probe: ServiceProbe | None = None,
    guard_interval_sec: float = 0.30,
    show_guard_dialog=None,
) -> int:
    effective_default = default_root if default_root is not None else data_root
    prefs_root = data_root
    if not smoke_test and not (prefs_root / "gamehub.db").is_file() and legacy_root is not None:
        legacy_resolved, legacy_err = resolve_data_root(legacy_root)
        if legacy_err is None and (legacy_resolved / "gamehub.db").is_file():
            prefs_root = legacy_resolved
    startup_lang, startup_strict_launchers = (
        ("en", frozenset()) if smoke_test else _read_startup_guard_prefs(prefs_root)
    )
    if startup_lang != "en":
        apply_language(app, startup_lang)

    def _notify_guard_block(kind: str, text: str) -> None:
        if show_guard_dialog is not None:
            show_guard_dialog(kind, text)
            return
        if kind == "fail_closed":
            QMessageBox.critical(None, "GameRewind", text)
        else:
            QMessageBox.information(None, "GameRewind", text)

    # Layer 2 (Cases 1 & 4 + Self-Check + Fail-Closed): runs BEFORE SingleInstance, BEFORE
    # data migration, and BEFORE creating any window or writing any data.
    try:
        catalog = ProtectedGamesCatalog.load(
            bundled_path=catalog_path,
            override_path=None if smoke_test else (prefs_root / OVERRIDE_FILENAME),
            strict_load=True,
        )
        protection_guard = ProtectionGuard(
            catalog,
            process_scanner=process_scanner,
            service_probe=service_probe,
            enabled_optional_launchers=startup_strict_launchers,
            interval_sec=guard_interval_sec,
        )
        startup_trigger = protection_guard.self_check()
    except (CatalogLoadError, ProtectionCheckError):
        _notify_guard_block(
            "fail_closed",
            app.translate(
                "GameHubWindow",
                "Protection could not start — GameRewind will close to keep you safe.",
            ),
        )
        return 2

    if startup_trigger is not None and not smoke_test:
        logging.getLogger("gamehub").info(
            "startup_refused_protected kind=%s name=%s",
            startup_trigger.kind,
            startup_trigger.display_name,
        )
        _notify_guard_block(
            "refused",
            app.translate(
                "GameHubWindow",
                "A protected game or its launcher is running — GameRewind won't run alongside it. Close it first.",
            ),
        )
        return 0

    if not smoke_test and legacy_root is not None:
        migrate_legacy_data_root(legacy_root, effective_default)
        resolved_after, location_error = resolve_data_root(effective_default)
        if location_error is not None:
            _notify_guard_block(
                "fail_closed",
                "GameRewind could not find its configured data folder. "
                "Restore the folder or remove store-location.json before starting again.",
            )
            return 1
        data_root = resolved_after

    window = GameHubWindow(app)
    instance = SingleInstance(effective_default, window.reveal)
    controller = None
    log_handler = None
    watcher = None
    capture_scheduler = None
    capture_service = None
    notes_controller = None
    last_time_controller = None
    controls_controller = None
    voice_player = None
    hotkeys = None
    move_worker = None
    guard_watchdog = None
    emergency_exit = [False]
    try:
        if not instance.claim_or_activate():
            return 0

        log_handler = _add_file_log(data_root)
        set_cover_cache_dir(data_root / "cache" / "covers")
        database = Database(data_root / "gamehub.db")
        events = EventBus(window)
        library = LibraryRepository(database)
        cover_store: CoverStore | None = None
        try:
            cover_store = CoverStore(database, data_root)
        except (OSError, StorageError):
            logging.getLogger("gamehub").warning("cover_storage_unavailable")
        detectors = (
            ()
            if smoke_test
            else (
                SteamDetector(),
                EpicDetector(),
                RiotDetector(),
                GogDetector(),
                EaDetector(),
                UbisoftDetector(),
                BattleNetDetector(),
                ItchDetector(),
                XboxDetector(),
                FolderDetector(library),
            )
        )
        screenshots = _open_screenshot_store(database, data_root)
        controls = _open_controls_store(database, data_root)
        memory = _open_memory_store(database, data_root)
        initial_settings = SettingsService(database).read()
        apply_language(app, initial_settings.language)
        apply_theme(app, initial_settings.theme)
        window.retranslate_ui()

        service = LibraryService(library, detectors, events.publish)
        window.library.present_games(service.current().games)
        controller = LibraryController(window.library, service)

        def _handle_scan_folder(folder_str: str, *, include_ignored: bool = False) -> None:
            folder = Path(folder_str)
            try:
                candidates = scan_folder_candidates(
                    folder,
                    existing_choices=library.list_scan_choices(folder),
                    known_exe_keys=library.list_known_exe_keys(exclude_source=GameSource.FOLDER),
                    include_ignored=include_ignored,
                )
            except (OSError, ValueError):
                window.library.show_error(
                    window.tr("Choose an accessible local folder to scan for games.")
                )
                return
            if not candidates:
                QMessageBox.information(
                    window,
                    window.tr("Scan folder"),
                    window.tr("No new game executables were found in that folder."),
                )
                return
            dialog = ScanFolderDialog(folder, candidates, parent=window)
            if dialog.exec() == ScanFolderDialog.DialogCode.Accepted:
                controller.apply_scan_folder(folder, dialog.choices())

        window.library.scanFolderRequested.connect(_handle_scan_folder)

        def _handle_change_cover(game_id: str, image_path: str) -> None:
            if cover_store is None:
                window.notify(window.tr("GameRewind could not save the selected cover image."))
                return
            try:
                cover_store.import_cover(game_id, Path(image_path))
            except (OSError, ValueError, StorageError):
                window.notify(window.tr("Choose a valid PNG, JPG, or WebP cover image."))
                return
            clear_cover_cache()
            window.library.present_games(service.current().games)
            if window.is_game_page_open(game_id):
                events.publish(LibraryChanged((game_id,)))

        def _handle_reset_cover(game_id: str) -> None:
            if cover_store is None:
                return
            try:
                cover_store.reset_cover(game_id)
            except (OSError, StorageError):
                window.notify(window.tr("GameRewind could not reset the cover image."))
                return
            clear_cover_cache()
            controller.refresh()
            if window.is_game_page_open(game_id):
                events.publish(LibraryChanged((game_id,)))

        window.library.changeCoverRequested.connect(_handle_change_cover)
        window.library.resetCoverRequested.connect(_handle_reset_cover)
        window.game_page.changeCoverRequested.connect(_handle_change_cover)
        window.game_page.resetCoverRequested.connect(_handle_reset_cover)
        window.library.lastMomentsRequested.connect(
            lambda game_id: _open_last_moments(window, library, screenshots, game_id)
        )
        window.game_page.lastMomentsRequested.connect(
            lambda game_id: _open_last_moments(window, library, screenshots, game_id)
        )
        window.game_page.assignExecutableRequested.connect(controller.assign_target)
        window.game_page.set_loaders(
            load_control_image=controls.read_image if controls is not None else (lambda _p: None),
            load_screenshot=screenshots.read_image if screenshots is not None else (lambda _p: None),
        )
        window.game_page.backRequested.connect(window.show_library)
        window.settings_view.backRequested.connect(window.show_library)
        app.setQuitOnLastWindowClosed(True)
        window.show()
        if smoke_test:
            _check_capture_runtime()
            _check_audio_runtime()
            QTimer.singleShot(0, app.quit)
        else:
            remove_legacy_startup_entry()
            pending_notes = PendingNoteRepository(database)
            notifier = WindowsNotifier()

            def _emergency_shutdown(*, fail_closed: bool = False) -> None:
                emergency_exit[0] = True
                if guard_watchdog is not None:
                    guard_watchdog.stop()
                if hotkeys is not None:
                    hotkeys.suspend()
                if capture_scheduler is not None:
                    capture_scheduler.pause()
                if voice_player is not None:
                    voice_player.stop()
                protection_guard.close()
                if fail_closed:
                    _notify_guard_block(
                        "fail_closed",
                        window.tr(
                            "Protection could not start — GameRewind will close to keep you safe."
                        ),
                    )
                window.close()
                app.quit()

            guard_bridge = _GuardBridge(window)
            guard_bridge.triggered.connect(
                lambda _trigger: _emergency_shutdown(fail_closed=False),
                Qt.ConnectionType.QueuedConnection,
            )
            guard_bridge.failed.connect(
                lambda _reason: _emergency_shutdown(fail_closed=True),
                Qt.ConnectionType.QueuedConnection,
            )

            def _sync_guard_policy(snapshot: SettingsSnapshot | None = None) -> None:
                snap = snapshot if snapshot is not None else SettingsService(database).read()
                protection_guard.update_policy(
                    enabled_optional_launchers=snap.enabled_optional_strict_launchers(),
                    disabled_entry_ids=_disabled_catalog_entries(catalog, library),
                )

            _sync_guard_policy(initial_settings)
            protection_guard.start(
                on_trigger=guard_bridge.triggered.emit,
                on_failure=guard_bridge.failed.emit,
            )
            guard_watchdog = QTimer(window)
            guard_watchdog.setInterval(1000)

            def _check_guard_heartbeat() -> None:
                if not protection_guard.is_healthy():
                    logging.getLogger("gamehub").error("protection_watchdog_unhealthy")
                    _emergency_shutdown(fail_closed=True)

            guard_watchdog.timeout.connect(_check_guard_heartbeat)
            guard_watchdog.start()

            lifecycle = LifecycleCoordinator(
                catalog,
                library,
                pending_notes,
                external_behavior=initial_settings.external_protected_behavior,
                suspend_hotkeys=lambda: hotkeys.suspend() if hotkeys is not None else None,
                resume_hotkeys=lambda: hotkeys.resume() if hotkeys is not None else None,
                pause_capture=lambda: capture_scheduler.pause()
                if capture_scheduler is not None
                else None,
                resume_capture=lambda: capture_scheduler.start()
                if capture_scheduler is not None
                else None,
                minimize_window=window.showMinimized,
                restore_window=window.reveal,
                exit_app=lambda: _emergency_shutdown(fail_closed=False),
                show_status=lambda name: window.statusBar().showMessage(
                    window.tr("Strict mode active for {game}").format(game=name)
                ),
                notify_passive=lambda name: notifier.notify_protected_game(
                    name,
                    title=window.tr("Protected game detected"),
                    body=window.tr(
                        "{game} is running. GameRewind switched to Strict mode; you can close GameRewind anytime."
                    ).format(game=name),
                ),
                prompts_enabled=lambda: notes_controller.prompts_enabled
                if notes_controller is not None
                else False,
            )
            window.library.set_strict_resolver(lambda game: lifecycle.is_strict_game(game.id))
            events.subscribe(GameStarted, window.game_started)
            events.subscribe(GameStopped, window.game_stopped)
            events.subscribe(GameStarted, lifecycle.on_game_started)
            events.subscribe(GameStopped, lifecycle.on_game_stopped)
            events.subscribe(ProtectedGameDetected, lifecycle.on_protected_detected)
            events.subscribe(
                ProtectedGameExited,
                lambda event: lifecycle.clear_external_protected(event.entry_id),
            )
            events.subscribe(GameStarted, controller.session_updated)
            events.subscribe(GameStopped, controller.session_updated)
            sessions = SessionRepository(database)
            launcher = LaunchCoordinator(WindowsLauncher(), events.publish)
            tracker = SessionTracker(sessions, events.publish, launcher.claim)
            watcher = SessionWatcher(
                sessions,
                ProcessProbe(),
                tracker,
                catalog=catalog,
                library=library,
                publish_protected=events.publish,
            )
            events.subscribe(LibraryChanged, watcher.library_changed)
            windows = _open_window_probe()

            def foreground_session() -> SessionIdentity | None:
                foreground = windows.foreground() if windows is not None else None
                return tracker.active_for(foreground.process) if foreground is not None else None

            if screenshots is not None and windows is not None:
                try:
                    capture_service = CaptureService(
                        windows,
                        tracker,
                        WgcCapture(),
                        screenshots,
                        buffer_size=initial_settings.capture_buffer_size,
                    )
                    capture_scheduler = CaptureScheduler(
                        capture_service, window, interval_sec=initial_settings.capture_interval_sec
                    )
                except (OSError, RuntimeError):
                    logging.getLogger("gamehub").warning("capture_startup_unavailable")

            notes_controller = _start_notes(
                window,
                database,
                data_root,
                library,
                foreground_session,
                events.publish,
                is_strict_active=lifecycle.is_strict_active,
                on_prompt_finished=lifecycle.on_note_prompt_finished,
                pending_notes=pending_notes,
            )
            if notes_controller is not None:
                events.subscribe(GameStopped, notes_controller.game_stopped)

            voice_player = _open_voice_player(window)
            last_time_controller = _start_last_time(
                window,
                memory,
                screenshots,
                controls,
                voice_player,
                launcher,
                foreground_session,
                is_strict_game=lifecycle.is_strict_game,
                on_launch_accepted=lambda gid, exit_after: lifecycle.on_play_launched(
                    gid, exit_after_play=exit_after
                ),
            )
            if last_time_controller is not None:
                events.subscribe(GameStarted, last_time_controller.game_started)
                events.subscribe(GameStopped, last_time_controller.game_stopped)
                window.library.playRequested.connect(last_time_controller.open_play_preview)
                window.game_page.playRequested.connect(last_time_controller.open_play_preview)
            else:
                window.library.playRequested.connect(
                    lambda _game_id: window.library.show_error(
                        window.tr("GameRewind could not open the Last time card.")
                    )
                )
                window.game_page.playRequested.connect(
                    lambda _game_id: window.game_page.show_error(
                        window.tr("GameRewind could not open the Last time card.")
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
                        window.tr("GameRewind could not access your controls storage.")
                    )

                window.game_page.uploadControlImageRequested.connect(_controls_unavailable)
                window.game_page.saveControlTextRequested.connect(_controls_unavailable)

            mods_engine = ModsEngine(
                database,
                data_root,
                library,
                catalog,
                is_any_game_running=lambda: bool(window._tracked_games),
                process_scanner=process_scanner,
            )
            mods_engine.recover_incomplete()
            refresh_mods_ui = _wire_mods(window, library, mods_engine, events)

            _wire_game_page(
                window,
                library,
                controls,
                memory,
                voice_player,
                events,
                catalog=catalog,
                on_game_opened=refresh_mods_ui,
                on_protection_changed=lambda: (
                    _sync_guard_policy(),
                    watcher.reload_protection(),
                    window.library.present_games(service.current().games),
                    refresh_mods_ui(),
                ),
            )
            hotkeys = _start_hotkeys(
                app,
                window,
                windows,
                initial_settings,
                notes_controller,
                last_time_controller,
                controls_controller,
            )
            store_location = StoreLocation(effective_default, data_root, database)
            move_worker = _wire_settings(
                app,
                window,
                database,
                store_location,
                hotkeys,
                windows,
                watcher,
                capture_service,
                capture_scheduler,
                notes_controller,
                last_time_controller,
                controls_controller,
                events,
                lifecycle=lifecycle,
                catalog=catalog,
                library=library,
                protection_guard=protection_guard,
                cover_store=cover_store,
                on_scan_folder=lambda folder_str, inc=False: (
                    _handle_scan_folder(folder_str, include_ignored=inc),
                    window.settings_view.set_scan_folders(library.list_scan_folders()),
                ),
                on_remove_scan_folder=lambda folder_str: (
                    controller.remove_scan_folder(Path(folder_str)),
                    window.settings_view.set_scan_folders(library.list_scan_folders()),
                ),
                on_covers_updated=lambda: (
                    clear_cover_cache(),
                    window.library.present_games(service.current().games),
                ),
                on_guard_policy_changed=lambda snap=None: (
                    _sync_guard_policy(snap),
                    watcher.reload_protection(),
                    window.library.present_games(service.current().games),
                ),
            )
            watcher.start()
            if capture_scheduler is not None:
                capture_scheduler.start()
            QTimer.singleShot(0, controller.refresh)
            if play_game_id and last_time_controller is not None:
                QTimer.singleShot(
                    0,
                    lambda gid=play_game_id: last_time_controller.open_play_preview(
                        gid, exit_after_play=True
                    ),
                )
            elif notes_controller is not None:
                QTimer.singleShot(0, notes_controller.offer_pending_notes)
        return app.exec()
    finally:
        if guard_watchdog is not None:
            guard_watchdog.stop()
        protection_guard.close()
        if hotkeys is not None:
            hotkeys.close()
        if move_worker is not None:
            move_worker.shutdown(wait=not emergency_exit[0], cancel_futures=emergency_exit[0])
        if voice_player is not None:
            voice_player.stop()
        if controls_controller is not None:
            controls_controller.close()
        if last_time_controller is not None:
            last_time_controller.close()
        if notes_controller is not None:
            notes_controller.close()
        if capture_scheduler is not None:
            capture_scheduler.close()
        if watcher is not None:
            watcher.close()
        if controller is not None:
            controller.close(wait=not emergency_exit[0])
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
    *,
    is_strict_active=None,
    on_prompt_finished=None,
    pending_notes: PendingNoteRepository | None = None,
) -> NotesController | None:
    try:
        repository = NoteRepository(database, data_root)
        controller = NotesController(
            window,
            repository,
            library,
            AudioRecorder(),
            foreground_session,
            window.set_recording,
            window.notify,
            publish=publish,
            is_strict_active=is_strict_active,
            on_prompt_finished=on_prompt_finished,
            pending_notes=pending_notes,
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
    *,
    is_strict_game=None,
    on_launch_accepted=None,
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
        is_strict_game=is_strict_game,
        on_launch_accepted=on_launch_accepted,
    )


def _wire_mods(
    window: GameHubWindow,
    library: LibraryRepository,
    mods_engine: ModsEngine,
    events: EventBus,
):
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, ProtectedGameModError):
            return window.tr(
                "Mods and translations are turned off for online games to protect your account."
            )
        if isinstance(exc, GameRunningModError):
            return window.tr("Close your running game before changing translations or mods.")
        if isinstance(exc, ManifestValidationError):
            return window.tr(
                "This .zip file is not a valid translation or mod pack. Only safe declarative packs are supported."
            )
        return window.tr("GameRewind could not update the translation or mod files.")

    def _refresh_game_panels(game_id: str | None = None, *, notice: str | None = None) -> None:
        try:
            games = library.list_games()
        except StorageError:
            return
        rows = [(g, mods_engine.is_game_protected(g)[0]) for g in games]
        window.mods_view.set_games(rows)
        selected_id = game_id or window.mods_view.selected_game_id
        if selected_id:
            try:
                state = mods_engine.get_state(selected_id)
            except (ModError, StorageError):
                pass
            else:
                if window.mods_view.selected_game_id == selected_id:
                    window.mods_view.panel.present_state(state)
                    if notice:
                        window.mods_view.panel.show_notice(notice)
                if window.game_page.game_id == selected_id:
                    window.game_page.mods_panel.present_state(state)
                    if notice:
                        window.game_page.mods_panel.show_notice(notice)
        else:
            window.mods_view.panel.clear_selection()

    def _run_action(panel: GameModsWidget, game_id: str, action, *, notice: str | None = None) -> None:
        panel.clear_messages()
        try:
            action()
        except (ModError, OSError, StorageError) as exc:
            panel.show_error(_friendly_error(exc))
            _refresh_game_panels(game_id)
            return
        _refresh_game_panels(game_id, notice=notice)

    def _bind_panel(panel: GameModsWidget) -> None:
        panel.importRequested.connect(
            lambda gid, zip_str, p=panel: _run_action(
                p,
                gid,
                lambda: mods_engine.import_zip(gid, Path(zip_str), enable=True),
                notice=window.tr("Imported and turned on ✓"),
            )
        )
        panel.toggleRequested.connect(
            lambda gid, iid, enabled, p=panel: _run_action(
                p,
                gid,
                lambda: mods_engine.set_enabled(gid, iid, enabled),
            )
        )
        panel.removeRequested.connect(
            lambda gid, iid, p=panel: _run_action(
                p,
                gid,
                lambda: mods_engine.remove_item(gid, iid),
                notice=window.tr("Removed cleanly ✓"),
            )
        )
        panel.restoreOriginalRequested.connect(
            lambda gid, p=panel: _run_action(
                p,
                gid,
                lambda: mods_engine.restore_original(gid),
                notice=window.tr("Original game files restored ✓"),
            )
        )
        panel.conflictWinnerRequested.connect(
            lambda gid, a_id, b_id, w_id, p=panel: _run_action(
                p,
                gid,
                lambda: mods_engine.choose_conflict_winner(gid, a_id, b_id, w_id),
            )
        )

    _bind_panel(window.mods_view.panel)
    _bind_panel(window.game_page.mods_panel)
    window.mods_view.gameSelected.connect(lambda gid: _refresh_game_panels(gid))
    window._nav_mods.clicked.connect(lambda: _refresh_game_panels())
    events.subscribe(LibraryChanged, lambda _event: _refresh_game_panels())
    _refresh_game_panels()
    return _refresh_game_panels


def _wire_game_page(
    window: GameHubWindow,
    library: LibraryRepository,
    controls: ControlsRepository | None,
    memory: MemoryRepository | None,
    player: VoicePlayer | None,
    events: EventBus,
    *,
    catalog: ProtectedGamesCatalog | None = None,
    on_game_opened=None,
    on_protection_changed=None,
) -> None:
    def _is_auto_strict(game) -> bool:
        if catalog is None:
            return False
        try:
            exes = library.list_target_basenames().get(game.id, ())
        except StorageError:
            exes = ()
        return catalog.effective_mode("auto", game.source, game.source_id, exes) == "strict"

    def open_game(game_id: str) -> None:
        if memory is None:
            window.library.show_error(window.tr("GameRewind could not load this game's history."))
            return
        try:
            game = library.get_game(game_id)
            if game is None:
                return
            control_items = controls.list_controls(game_id) if controls is not None else ()
            page = memory.timeline(game_id)
        except (OSError, StorageError):
            window.library.show_error(window.tr("GameRewind could not load this game's history."))
            return
        if player is not None:
            player.stop()
        window.game_page.show_game(game, control_items, page, auto_strict=_is_auto_strict(game))
        if on_game_opened is not None:
            on_game_opened(game_id)
        window.show_game_page()

    def save_protection(game_id: str, mode: str, exit_after_launch: bool) -> None:
        try:
            library.set_protection(game_id, mode, exit_after_launch=exit_after_launch)
        except (StorageError, ValueError):
            window.game_page.show_error(
                window.tr("GameRewind could not update this game's protection mode.")
            )
            return
        if on_protection_changed is not None:
            on_protection_changed()

    def load_more(game_id: str, cursor) -> None:
        if memory is None or not window.is_game_page_open(game_id):
            return
        try:
            page = memory.timeline(game_id, cursor=cursor)
        except (OSError, StorageError):
            window.game_page.show_error(window.tr("GameRewind could not load earlier sessions."))
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
        window.game_page.show_game(game, control_items, page, auto_strict=_is_auto_strict(game))

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
            window.game_page.show_error(window.tr("GameRewind could not play this voice note."))

    window.library.gameOpened.connect(open_game)
    window.game_page.protectionChanged.connect(save_protection)
    window.game_page.loadMoreTimelineRequested.connect(load_more)
    window.game_page.playVoiceNoteRequested.connect(play_voice)
    if player is not None:
        window.game_page.stopVoiceNoteRequested.connect(player.stop)
        player.playingChanged.connect(window.game_page.set_voice_playing)
        player.failed.connect(
            lambda: (
                window.game_page.reset_voice_state(),
                window.game_page.show_error(window.tr("GameRewind could not play this voice note."))
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
    initial: SettingsSnapshot,
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
        and not hotkeys.bind_shortcut(
            RECORD_NOTE_ID, initial.hotkey_record_note, notes_controller.toggle_hotkey
        )
    ):
        window.notify(
            window.tr("Ctrl+Alt+N is unavailable. You can record from the game-close prompt.")
        )
    if (
        last_time_controller is not None
        and not hotkeys.bind_shortcut(
            LAST_TIME_ID, initial.hotkey_last_time, last_time_controller.reopen_hotkey
        )
    ):
        window.notify(
            window.tr("Ctrl+Alt+L is unavailable. You can open Last time from Play in Library.")
        )
    if (
        controls_controller is not None
        and not hotkeys.bind_shortcut(
            PIN_CONTROLS_ID, initial.hotkey_pin_controls, controls_controller.pin_hotkey
        )
    ):
        window.notify(
            window.tr("Ctrl+Alt+C is unavailable. You can upload controls images from the game page.")
        )
    return hotkeys


class _MoveBridge(QObject):
    finished = Signal(bool, object)
    protectionTested = Signal(bool, int)
    coversFetched = Signal(int)


def _wire_settings(
    app: QApplication,
    window: GameHubWindow,
    database: Database,
    store_location: StoreLocation,
    hotkeys: GlobalHotkeys | None,
    windows: WindowProbe | None,
    watcher: SessionWatcher,
    capture_service: CaptureService | None,
    capture_scheduler: CaptureScheduler | None,
    notes_controller: NotesController | None,
    last_time_controller: LastTimeController | None,
    controls_controller: ControlsController | None,
    events: EventBus,
    *,
    lifecycle: LifecycleCoordinator | None = None,
    catalog: ProtectedGamesCatalog | None = None,
    library: LibraryRepository | None = None,
    protection_guard: ProtectionGuard | None = None,
    cover_store: CoverStore | None = None,
    on_scan_folder=None,
    on_remove_scan_folder=None,
    on_covers_updated=None,
    on_guard_policy_changed=None,
) -> ThreadPoolExecutor:
    action_map = {
        "hotkey.record_note": (
            RECORD_NOTE_ID,
            notes_controller.toggle_hotkey
            if notes_controller is not None and windows is not None
            else None,
        ),
        "hotkey.last_time": (
            LAST_TIME_ID,
            last_time_controller.reopen_hotkey if last_time_controller is not None else None,
        ),
        "hotkey.pin_controls": (
            PIN_CONTROLS_ID,
            controls_controller.pin_hotkey if controls_controller is not None else None,
        ),
    }
    id_to_key = {ident: key for key, (ident, _) in action_map.items()}

    def rebind_hotkeys(changes: dict[str, str]) -> tuple[bool, str | None, str | None]:
        if hotkeys is None:
            for key, shortcut in changes.items():
                if shortcut:
                    return False, key, "hotkeys_unavailable"
            return True, None, None
        batch = {}
        for key, shortcut in changes.items():
            ident, handler = action_map[key]
            if handler is None:
                if shortcut:
                    return False, key, "hotkeys_unavailable"
                continue
            batch[ident] = (shortcut, handler)
        ok, failed_id = hotkeys.rebind_batch(batch)
        if not ok:
            return False, id_to_key.get(failed_id or -1), "shortcut_conflict"
        return True, None, None

    settings_service = SettingsService(
        database,
        publish=events.publish,
        rebind_hotkeys=rebind_hotkeys,
    )
    move_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="store-move")
    move_bridge = _MoveBridge(window)

    def _load_protected_game_rows() -> list[tuple[str, str, str, str]]:
        if catalog is None or library is None:
            return []
        rows: list[tuple[str, str, str, str]] = []
        try:
            basenames = library.list_target_basenames()
            for game in library.list_games():
                if not game.installed:
                    continue
                matched = catalog.match_game(
                    game.source, game.source_id, basenames.get(game.id, ())
                )
                if matched is not None or game.protection_mode == "strict":
                    anti_cheat = matched.anti_cheat if matched is not None else "Strict"
                    rows.append((game.id, game.name, anti_cheat, game.protection_mode))
        except StorageError:
            return []
        return rows

    def open_settings() -> None:
        try:
            current = settings_service.read()
        except StorageError:
            window.library.show_error(window.tr("GameRewind could not read your settings."))
            return
        window.settings_view.load_settings(current, store_location.current())
        window.settings_view.set_protected_games(_load_protected_game_rows())
        if library is not None:
            window.settings_view.set_scan_folders(library.list_scan_folders())
        window.settings_view.show_field_errors({})
        window.show_settings()

    def reset_defaults() -> None:
        result = settings_service.reset_to_defaults()
        if library is not None:
            try:
                library.reset_protection_defaults()
            except StorageError:
                pass
        if result.ok:
            window.settings_view.load_settings(result.snapshot, store_location.current())
            window.settings_view.set_protected_games(_load_protected_game_rows())
            if on_guard_policy_changed is not None:
                on_guard_policy_changed(result.snapshot)
            window.settings_view.show_status("settings_reset")
        else:
            window.settings_view.show_field_errors(result.errors)

    def fetch_missing_covers() -> None:
        if library is None or cover_store is None:
            window.settings_view.set_fetch_covers_result(0)
            return
        snap = settings_service.read()
        enabled = window.settings_view._sgdb_enabled.isChecked()
        api_key = window.settings_view._sgdb_api_key.text().strip()
        if not enabled or not api_key:
            window.settings_view.set_fetch_covers_result(0)
            return
        if enabled != snap.steamgriddb_enabled or api_key != snap.steamgriddb_api_key:
            settings_service.update(
                {"covers.steamgriddb_enabled": enabled, "covers.steamgriddb_api_key": api_key}
            )
        window.settings_view.set_fetch_covers_running(True)

        def _worker() -> None:
            updated = 0
            try:
                games = library.list_games()
            except StorageError:
                move_bridge.coversFetched.emit(0)
                return
            for game in games:
                if game.cover_path is not None or game.custom_cover:
                    continue
                img = fetch_steamgriddb_cover(game.name, enabled=enabled, api_key=api_key)
                if img is None:
                    continue
                try:
                    cover_store.import_cover_bytes(game.id, img)
                    updated += 1
                except (OSError, ValueError, StorageError):
                    continue
            move_bridge.coversFetched.emit(updated)

        move_worker.submit(_worker)

    def _on_covers_fetched(count: int) -> None:
        window.settings_view.set_fetch_covers_result(count)
        if count > 0 and on_covers_updated is not None:
            on_covers_updated()

    move_bridge.coversFetched.connect(_on_covers_fetched, Qt.ConnectionType.QueuedConnection)

    def set_protected_game_mode(game_id: str, mode: str) -> None:
        if library is None:
            return
        try:
            library.set_protection(game_id, mode)
        except (StorageError, ValueError):
            window.settings_view.show_field_errors({"_storage": "storage_unavailable"})
            return
        if on_guard_policy_changed is not None:
            on_guard_policy_changed()
        window.settings_view.set_protected_games(_load_protected_game_rows())
        window.settings_view.show_status("settings_saved")

    def run_protection_test() -> None:
        if catalog is None:
            window.settings_view.set_test_protection_result(False, 0)
            return
        window.settings_view.set_test_protection_running(True)

        def _worker() -> None:
            res = run_dummy_process_protection_test(
                catalog,
                dummy_exe_name="FortniteLauncher.exe",
                live_guard=protection_guard,
            )
            move_bridge.protectionTested.emit(res.ok, res.elapsed_ms)

        move_worker.submit(_worker)

    move_bridge.protectionTested.connect(
        window.settings_view.set_test_protection_result,
        Qt.ConnectionType.QueuedConnection,
    )

    def save_settings(patch: dict) -> None:
        result = settings_service.update(patch)
        if result.ok:
            window.settings_view.load_settings(result.snapshot, store_location.current())
            window.settings_view.show_status("settings_saved")
        else:
            window.settings_view.show_field_errors(result.errors)

    def open_folder() -> None:
        url = QUrl.fromLocalFile(str(store_location.current()))
        if not QDesktopServices.openUrl(url):
            window.settings_view.show_field_errors({"data_location": "open_folder_failed"})

    def move_completed(ok: bool, diag: object) -> None:
        if ok:
            # Keep background writers stopped so no post-move writes land in the old store.
            watcher.close()
            if hotkeys is not None:
                hotkeys.close()
            window.settings_view.set_restart_required()
            window.settings_view.show_status("location_moved_restart")
        else:
            watcher.resume()
            if capture_scheduler is not None:
                capture_scheduler.start()
            window.settings_view.set_busy(False)
            window.settings_view.show_field_errors(
                {"data_location": str(diag) if diag else "location_move_failed"}
            )

    move_bridge.finished.connect(move_completed, Qt.ConnectionType.QueuedConnection)

    def move_folder(destination: str) -> None:
        window.settings_view.set_busy(True)
        if capture_scheduler is not None:
            capture_scheduler.pause()

        def run_move() -> None:
            watcher.pause()
            ok, diag = store_location.move(Path(destination))
            move_bridge.finished.emit(ok, diag)

        move_worker.submit(run_move)

    def apply_changed(event: SettingsChanged) -> None:
        snap = event.snapshot
        if "ui.language" in event.keys:
            apply_language(app, snap.language)
            window.retranslate_ui()
        if "ui.theme" in event.keys:
            apply_theme(app, snap.theme)
        if "capture.interval_sec" in event.keys and capture_scheduler is not None:
            capture_scheduler.set_interval_sec(snap.capture_interval_sec)
        if "capture.buffer_size" in event.keys and capture_service is not None:
            capture_service.set_buffer_size(snap.capture_buffer_size)
        if "memory.prompt_on_end" in event.keys and notes_controller is not None:
            notes_controller.set_prompts_enabled(snap.prompt_on_end)
        if "memory.autoplay_voice" in event.keys and last_time_controller is not None:
            last_time_controller.set_autoplay_enabled(snap.autoplay_voice)
        if "protection.external_behavior" in event.keys and lifecycle is not None:
            lifecycle.set_external_behavior(snap.external_protected_behavior)
        if (
            any(k.startswith("protection.strict_launcher.") for k in event.keys)
            and on_guard_policy_changed is not None
        ):
            on_guard_policy_changed(snap)

    window.library.settingsRequested.connect(open_settings)
    window.settings_view.saveRequested.connect(save_settings)
    window.settings_view.resetDefaultsRequested.connect(reset_defaults)
    window.settings_view.openFolderRequested.connect(open_folder)
    window.settings_view.moveFolderRequested.connect(move_folder)
    window.settings_view.testProtectionRequested.connect(run_protection_test)
    window.settings_view.protectedGameModeChanged.connect(set_protected_game_mode)
    window.settings_view.fetchCoversRequested.connect(fetch_missing_covers)
    if on_scan_folder is not None:
        window.settings_view.addScanFolderRequested.connect(
            lambda folder_str: on_scan_folder(folder_str, False)
        )
        window.settings_view.rescanFolderRequested.connect(
            lambda folder_str: on_scan_folder(folder_str, True)
        )
    if on_remove_scan_folder is not None:
        window.settings_view.removeScanFolderRequested.connect(on_remove_scan_folder)
    events.subscribe(SettingsChanged, apply_changed)
    return move_worker


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
        window.library.show_error(window.tr("GameRewind could not open your screenshot folder."))
        return
    try:
        game = library.get_game(game_id)
        if game is None:
            return
        images = screenshots.last_moments(game_id)
    except (OSError, StorageError):
        window.library.show_error(window.tr("GameRewind could not load the screenshots for this game."))
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
    parser = argparse.ArgumentParser(description="Open GameRewind.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Build the window, enter the event loop, and exit cleanly.",
    )
    parser.add_argument(
        "--play",
        dest="play_game_id",
        default=None,
        help="Open the Last time card for a game and exit GameRewind after the game finishes.",
    )
    args = parser.parse_args(argv)
    app = QApplication(["GameRewind"])
    app.setApplicationName("GameRewind")
    app.setApplicationVersion(__version__)

    if args.smoke_test:
        with TemporaryDirectory(prefix="gamehub-smoke-") as temp_dir:
            return _run(app, Path(temp_dir), smoke_test=True)

    local_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    default_root = Path(local_data) / "GameRewind"
    legacy_root = Path(local_data) / "GameHub"
    resolved_root, location_error = resolve_data_root(default_root)
    if location_error is not None:
        QMessageBox.critical(
            None,
            "GameRewind",
            "GameRewind could not find its configured data folder. "
            "Restore the folder or remove store-location.json before starting again.",
        )
        return 1
    try:
        return _run(
            app,
            resolved_root,
            smoke_test=False,
            default_root=default_root,
            legacy_root=legacy_root,
            play_game_id=args.play_game_id,
        )
    except (OSError, RuntimeError, StorageError):
        QMessageBox.critical(
            None, "GameRewind", "GameRewind could not start. Check that your local data folder is available."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
