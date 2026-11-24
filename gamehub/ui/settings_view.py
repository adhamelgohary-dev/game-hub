"""Editable application settings organized into 5 plain-language groups with EN/AR explanations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gamehub import __version__
from gamehub.core.settings import (
    MAX_BUFFER_SIZE,
    MAX_CAPTURE_INTERVAL_SEC,
    MIN_BUFFER_SIZE,
    MIN_CAPTURE_INTERVAL_SEC,
    SettingsSnapshot,
)


def _make_hint(parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName("mutedText")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class SettingsView(QWidget):
    backRequested = Signal()
    saveRequested = Signal(dict)
    resetDefaultsRequested = Signal()
    openFolderRequested = Signal()
    moveFolderRequested = Signal(str)
    testProtectionRequested = Signal()
    protectedGameModeChanged = Signal(str, str)
    addScanFolderRequested = Signal(str)
    rescanFolderRequested = Signal(str)
    removeScanFolderRequested = Signal(str)
    fetchCoversRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data_root = Path()
        self._busy = False
        self._restart_required = False
        self._error_labels: dict[str, QLabel] = {}
        self._error_codes: dict[str, str] = {}
        self._status_code: str | None = None
        self._scan_folders: list[Path] = []
        self._last_test_result: tuple[bool, int] | None = None
        self._last_fetch_count: int | None = None

        self._back = QPushButton(self)
        self._back.clicked.connect(self.backRequested)
        self._title = QLabel(self)
        self._title.setObjectName("pageTitle")

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(self._back)
        header.addWidget(self._title)
        header.addStretch()

        body = QWidget(self)
        body.setObjectName("canvas")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 8, 12)
        body_layout.setSpacing(14)

        # 1. General (Language & Theme)
        self._lang_group = QGroupBox(body)
        lang_form = QFormLayout(self._lang_group)
        lang_form.setVerticalSpacing(6)

        self._lang_label = QLabel(self._lang_group)
        self._lang_label.setWordWrap(True)
        self._language = QComboBox(self._lang_group)
        self._language.addItem("English", "en")
        self._language.addItem("العربية", "ar")
        self._lang_label.setBuddy(self._language)
        self._lang_hint = _make_hint(self._lang_group)
        lang_form.addRow(self._lang_label, self._language)
        lang_form.addRow(self._lang_hint)
        lang_form.addRow(self._make_error("ui.language", self._lang_group))

        self._theme_label = QLabel(self._lang_group)
        self._theme_label.setWordWrap(True)
        self._theme = QComboBox(self._lang_group)
        self._theme.addItem("", "dark")
        self._theme.addItem("", "light")
        self._theme.addItem("", "system")
        self._theme_label.setBuddy(self._theme)
        self._theme_hint = _make_hint(self._lang_group)
        lang_form.addRow(self._theme_label, self._theme)
        lang_form.addRow(self._theme_hint)
        lang_form.addRow(self._make_error("ui.theme", self._lang_group))
        body_layout.addWidget(self._lang_group)

        # 2. Capture and notes (Screenshots, Notes, Global shortcuts)
        self._capture_group = QGroupBox(body)
        capture_layout = QVBoxLayout(self._capture_group)
        capture_layout.setSpacing(10)

        capture_form = QFormLayout()
        capture_form.setVerticalSpacing(6)
        self._interval_label = QLabel(self._capture_group)
        self._interval_label.setWordWrap(True)
        self._interval = QSpinBox(self._capture_group)
        self._interval.setRange(MIN_CAPTURE_INTERVAL_SEC, MAX_CAPTURE_INTERVAL_SEC)
        self._interval_label.setBuddy(self._interval)
        self._interval_hint = _make_hint(self._capture_group)
        capture_form.addRow(self._interval_label, self._interval)
        capture_form.addRow(self._interval_hint)
        capture_form.addRow(self._make_error("capture.interval_sec", self._capture_group))

        self._buffer_label = QLabel(self._capture_group)
        self._buffer_label.setWordWrap(True)
        self._buffer = QSpinBox(self._capture_group)
        self._buffer.setRange(MIN_BUFFER_SIZE, MAX_BUFFER_SIZE)
        self._buffer_label.setBuddy(self._buffer)
        self._buffer_hint = _make_hint(self._capture_group)
        capture_form.addRow(self._buffer_label, self._buffer)
        capture_form.addRow(self._buffer_hint)
        capture_form.addRow(self._make_error("capture.buffer_size", self._capture_group))
        capture_layout.addLayout(capture_form)

        self._autoplay = QCheckBox(self._capture_group)
        self._autoplay_hint = _make_hint(self._capture_group)
        self._prompt_on_end = QCheckBox(self._capture_group)
        self._prompt_on_end_hint = _make_hint(self._capture_group)
        capture_layout.addWidget(self._autoplay)
        capture_layout.addWidget(self._autoplay_hint)
        capture_layout.addWidget(self._prompt_on_end)
        capture_layout.addWidget(self._prompt_on_end_hint)

        self._hotkeys_heading = QLabel(self._capture_group)
        self._hotkeys_heading.setObjectName("sectionHeading")
        self._hotkeys_hint = _make_hint(self._capture_group)
        capture_layout.addWidget(self._hotkeys_heading)
        capture_layout.addWidget(self._hotkeys_hint)

        hotkeys_form = QFormLayout()
        hotkeys_form.setVerticalSpacing(6)
        self._hk_record_label = QLabel(self._capture_group)
        self._hk_record_label.setWordWrap(True)
        self._hk_record = QLineEdit(self._capture_group)
        self._hk_record.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._hk_record_label.setBuddy(self._hk_record)
        self._hk_record_hint = _make_hint(self._capture_group)
        hotkeys_form.addRow(self._hk_record_label, self._hk_record)
        hotkeys_form.addRow(self._hk_record_hint)
        hotkeys_form.addRow(self._make_error("hotkey.record_note", self._capture_group))

        self._hk_last_label = QLabel(self._capture_group)
        self._hk_last_label.setWordWrap(True)
        self._hk_last = QLineEdit(self._capture_group)
        self._hk_last.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._hk_last_label.setBuddy(self._hk_last)
        self._hk_last_hint = _make_hint(self._capture_group)
        hotkeys_form.addRow(self._hk_last_label, self._hk_last)
        hotkeys_form.addRow(self._hk_last_hint)
        hotkeys_form.addRow(self._make_error("hotkey.last_time", self._capture_group))

        self._hk_pin_label = QLabel(self._capture_group)
        self._hk_pin_label.setWordWrap(True)
        self._hk_pin = QLineEdit(self._capture_group)
        self._hk_pin.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._hk_pin_label.setBuddy(self._hk_pin)
        self._hk_pin_hint = _make_hint(self._capture_group)
        hotkeys_form.addRow(self._hk_pin_label, self._hk_pin)
        hotkeys_form.addRow(self._hk_pin_hint)
        hotkeys_form.addRow(self._make_error("hotkey.pin_controls", self._capture_group))
        capture_layout.addLayout(hotkeys_form)
        body_layout.addWidget(self._capture_group)

        # 3. Protected games (Zero-Presence Anti-Cheat)
        self._protection_group = QGroupBox(body)
        protection_layout = QVBoxLayout(self._protection_group)
        protection_layout.setSpacing(10)

        protection_form = QFormLayout()
        protection_form.setVerticalSpacing(6)
        self._external_behavior_label = QLabel(self._protection_group)
        self._external_behavior_label.setWordWrap(True)
        self._external_behavior = QComboBox(self._protection_group)
        self._external_behavior.addItem("", "exit_app")
        self._external_behavior.addItem("", "strict_mode")
        self._external_behavior.addItem("", "ask_me")
        self._external_behavior_label.setBuddy(self._external_behavior)
        self._external_behavior_hint = _make_hint(self._protection_group)
        protection_form.addRow(self._external_behavior_label, self._external_behavior)
        protection_form.addRow(self._external_behavior_hint)
        protection_form.addRow(
            self._make_error("protection.external_behavior", self._protection_group)
        )
        protection_layout.addLayout(protection_form)

        self._launchers_heading = QLabel(self._protection_group)
        self._launchers_heading.setObjectName("sectionHeading")
        self._launchers_heading.setWordWrap(True)
        self._launchers_hint = _make_hint(self._protection_group)
        protection_layout.addWidget(self._launchers_heading)
        protection_layout.addWidget(self._launchers_hint)

        self._strict_riot = QCheckBox(self._protection_group)
        self._strict_riot.setChecked(True)
        self._strict_riot.setEnabled(False)
        protection_layout.addWidget(self._strict_riot)

        self._launcher_checks: dict[str, QCheckBox] = {}
        for key in ("epic", "ea", "battlenet", "ubisoft", "steam"):
            box = QCheckBox(self._protection_group)
            self._launcher_checks[key] = box
            protection_layout.addWidget(box)

        self._detected_protected_heading = QLabel(self._protection_group)
        self._detected_protected_heading.setObjectName("sectionHeading")
        self._detected_protected_heading.setWordWrap(True)
        protection_layout.addWidget(self._detected_protected_heading)

        self._protected_games_container = QWidget(self._protection_group)
        self._protected_games_layout = QVBoxLayout(self._protected_games_container)
        self._protected_games_layout.setContentsMargins(0, 0, 0, 0)
        self._protected_games_layout.setSpacing(6)
        self._protected_games_rows: list[tuple[str, str, str, str]] = []
        protection_layout.addWidget(self._protected_games_container)

        test_row = QHBoxLayout()
        self._test_protection_btn = QPushButton(self._protection_group)
        self._test_protection_btn.clicked.connect(self.testProtectionRequested)
        self._test_protection_result = QLabel(self._protection_group)
        self._test_protection_result.setObjectName("mutedText")
        self._test_protection_result.setTextFormat(Qt.TextFormat.PlainText)
        self._test_protection_result.setWordWrap(True)
        test_row.addWidget(self._test_protection_btn)
        test_row.addWidget(self._test_protection_result, stretch=1)
        self._test_protection_hint = _make_hint(self._protection_group)
        protection_layout.addLayout(test_row)
        protection_layout.addWidget(self._test_protection_hint)
        body_layout.addWidget(self._protection_group)

        # 4. Library and folders (Scan folders, optional SteamGridDB, Data folder)
        self._data_group = QGroupBox(body)
        data_layout = QVBoxLayout(self._data_group)
        data_layout.setSpacing(10)

        self._scan_folders_heading = QLabel(self._data_group)
        self._scan_folders_heading.setObjectName("sectionHeading")
        self._scan_folders_hint = _make_hint(self._data_group)
        data_layout.addWidget(self._scan_folders_heading)
        data_layout.addWidget(self._scan_folders_hint)

        self._scan_folders_container = QWidget(self._data_group)
        self._scan_folders_layout = QVBoxLayout(self._scan_folders_container)
        self._scan_folders_layout.setContentsMargins(0, 0, 0, 0)
        self._scan_folders_layout.setSpacing(6)
        data_layout.addWidget(self._scan_folders_container)

        scan_btn_row = QHBoxLayout()
        self._add_scan_folder_btn = QPushButton(self._data_group)
        self._add_scan_folder_btn.clicked.connect(self._pick_scan_folder)
        scan_btn_row.addWidget(self._add_scan_folder_btn)
        scan_btn_row.addStretch()
        data_layout.addLayout(scan_btn_row)

        # Optional SteamGridDB (off by default)
        self._sgdb_heading = QLabel(self._data_group)
        self._sgdb_heading.setObjectName("sectionHeading")
        data_layout.addWidget(self._sgdb_heading)

        self._sgdb_enabled = QCheckBox(self._data_group)
        self._sgdb_enabled.toggled.connect(self._sync_sgdb_controls)
        self._sgdb_hint = _make_hint(self._data_group)
        data_layout.addWidget(self._sgdb_enabled)
        data_layout.addWidget(self._sgdb_hint)

        sgdb_form = QFormLayout()
        sgdb_form.setVerticalSpacing(6)
        self._sgdb_key_label = QLabel(self._data_group)
        self._sgdb_key_label.setWordWrap(True)
        self._sgdb_api_key = QLineEdit(self._data_group)
        self._sgdb_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._sgdb_api_key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._sgdb_api_key.textChanged.connect(self._sync_sgdb_controls)
        self._sgdb_key_label.setBuddy(self._sgdb_api_key)
        self._sgdb_key_hint = _make_hint(self._data_group)
        sgdb_form.addRow(self._sgdb_key_label, self._sgdb_api_key)
        sgdb_form.addRow(self._sgdb_key_hint)
        sgdb_form.addRow(self._make_error("covers.steamgriddb_api_key", self._data_group))
        data_layout.addLayout(sgdb_form)

        fetch_row = QHBoxLayout()
        self._fetch_covers_btn = QPushButton(self._data_group)
        self._fetch_covers_btn.clicked.connect(self.fetchCoversRequested)
        self._fetch_covers_status = _make_hint(self._data_group)
        fetch_row.addWidget(self._fetch_covers_btn)
        fetch_row.addWidget(self._fetch_covers_status, stretch=1)
        data_layout.addLayout(fetch_row)

        # Data folder
        self._data_folder_heading = QLabel(self._data_group)
        self._data_folder_heading.setObjectName("sectionHeading")
        self._data_folder_hint = _make_hint(self._data_group)
        data_layout.addWidget(self._data_folder_heading)
        data_layout.addWidget(self._data_folder_hint)

        self._data_path_label = QLabel(self._data_group)
        self._data_path_label.setTextFormat(Qt.TextFormat.PlainText)
        self._data_path_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._data_path_label.setWordWrap(True)
        self._data_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        data_buttons = QHBoxLayout()
        self._open_folder = QPushButton(self._data_group)
        self._open_folder.clicked.connect(self.openFolderRequested)
        self._move_folder = QPushButton(self._data_group)
        self._move_folder.clicked.connect(self._pick_destination)
        data_buttons.addWidget(self._open_folder)
        data_buttons.addWidget(self._move_folder)
        data_buttons.addStretch()
        data_layout.addWidget(self._data_path_label)
        data_layout.addLayout(data_buttons)
        data_layout.addWidget(self._make_error("data_location", self._data_group))
        body_layout.addWidget(self._data_group)

        # 5. About and privacy (Guarantees + Version + Reset to defaults)
        self._about_group = QGroupBox(body)
        about_layout = QVBoxLayout(self._about_group)
        about_layout.setSpacing(8)
        self._about_zero_bg = QLabel(self._about_group)
        self._about_zero_bg.setTextFormat(Qt.TextFormat.PlainText)
        self._about_zero_bg.setWordWrap(True)
        self._about_anticheat = QLabel(self._about_group)
        self._about_anticheat.setTextFormat(Qt.TextFormat.PlainText)
        self._about_anticheat.setWordWrap(True)
        self._about_version = QLabel(self._about_group)
        self._about_version.setObjectName("mutedText")
        self._about_version.setTextFormat(Qt.TextFormat.PlainText)
        self._about_version.setWordWrap(True)
        reset_row = QHBoxLayout()
        self._reset_defaults_btn = QPushButton(self._about_group)
        self._reset_defaults_btn.clicked.connect(self._confirm_reset_defaults)
        reset_row.addWidget(self._reset_defaults_btn)
        reset_row.addStretch()
        self._reset_defaults_hint = _make_hint(self._about_group)
        about_layout.addWidget(self._about_zero_bg)
        about_layout.addWidget(self._about_anticheat)
        about_layout.addWidget(self._about_version)
        about_layout.addLayout(reset_row)
        about_layout.addWidget(self._reset_defaults_hint)
        body_layout.addWidget(self._about_group)

        body_layout.addStretch()

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)

        self._status = QLabel(self)
        self._status.setObjectName("mutedText")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        self._status.hide()

        self._save = QPushButton(self)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._submit)
        footer = QHBoxLayout()
        footer.addWidget(self._status, stretch=1)
        footer.addWidget(self._save)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(scroll, stretch=1)
        root.addLayout(footer)
        self._sync_sgdb_controls()
        self.retranslate_ui()

    def load_settings(self, snapshot: SettingsSnapshot, data_root: Path) -> None:
        self._data_root = data_root
        idx = self._language.findData(snapshot.language)
        if idx >= 0:
            self._language.setCurrentIndex(idx)
        theme_idx = self._theme.findData(snapshot.theme)
        if theme_idx >= 0:
            self._theme.setCurrentIndex(theme_idx)
        ext_idx = self._external_behavior.findData(snapshot.external_protected_behavior)
        if ext_idx >= 0:
            self._external_behavior.setCurrentIndex(ext_idx)
        self._launcher_checks["epic"].setChecked(snapshot.strict_launcher_epic)
        self._launcher_checks["ea"].setChecked(snapshot.strict_launcher_ea)
        self._launcher_checks["battlenet"].setChecked(snapshot.strict_launcher_battlenet)
        self._launcher_checks["ubisoft"].setChecked(snapshot.strict_launcher_ubisoft)
        self._launcher_checks["steam"].setChecked(snapshot.strict_launcher_steam)
        self._interval.setValue(snapshot.capture_interval_sec)
        self._buffer.setValue(snapshot.capture_buffer_size)
        self._autoplay.setChecked(snapshot.autoplay_voice)
        self._prompt_on_end.setChecked(snapshot.prompt_on_end)
        self._hk_record.setText(snapshot.hotkey_record_note)
        self._hk_last.setText(snapshot.hotkey_last_time)
        self._hk_pin.setText(snapshot.hotkey_pin_controls)
        self._sgdb_enabled.setChecked(snapshot.steamgriddb_enabled)
        self._sgdb_api_key.setText(snapshot.steamgriddb_api_key)
        self._data_path_label.setText(str(data_root))
        self._sync_sgdb_controls()

    def set_scan_folders(self, folders: Sequence[Path]) -> None:
        self._scan_folders = list(folders)
        self._rebuild_scan_folders_list()

    def set_fetch_covers_running(self, running: bool) -> None:
        self._fetch_covers_btn.setEnabled(not running and self._can_fetch_covers())
        if running:
            self._fetch_covers_status.setText(self.tr("Fetching missing covers…"))

    def set_fetch_covers_result(self, updated_count: int) -> None:
        self._last_fetch_count = updated_count
        self._fetch_covers_btn.setEnabled(self._can_fetch_covers())
        if updated_count > 0:
            self._fetch_covers_status.setText(
                self.tr("Updated {count} missing covers.").format(count=updated_count)
            )
        else:
            self._fetch_covers_status.setText(self.tr("No new covers were found."))

    def _can_fetch_covers(self) -> bool:
        return (
            not self._busy
            and not self._restart_required
            and self._sgdb_enabled.isChecked()
            and bool(self._sgdb_api_key.text().strip())
        )

    def _sync_sgdb_controls(self) -> None:
        enabled = self._sgdb_enabled.isChecked()
        self._sgdb_api_key.setEnabled(enabled)
        self._fetch_covers_btn.setEnabled(self._can_fetch_covers())

    def set_protected_games(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Populate detected protected games: (game_id, name, anti_cheat, mode)."""
        self._protected_games_rows = list(rows)
        self._rebuild_protected_games_list()

    def set_test_protection_running(self, running: bool) -> None:
        self._test_protection_btn.setEnabled(not running)
        if running:
            self._test_protection_result.setText(self.tr("Running protection check…"))

    def set_test_protection_result(self, ok: bool, elapsed_ms: int) -> None:
        self._last_test_result = (ok, elapsed_ms)
        self._test_protection_btn.setEnabled(True)
        if ok:
            self._test_protection_result.setText(
                self.tr("Protection OK — Game Hub closed in {ms} ms").format(ms=elapsed_ms)
            )
        else:
            self._test_protection_result.setText(
                self.tr("Protection test failed. Check that Windows process scanning is available.")
            )

    def _rebuild_scan_folders_list(self) -> None:
        while self._scan_folders_layout.count():
            item = self._scan_folders_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._scan_folders:
            empty = _make_hint(self._scan_folders_container)
            empty.setText(self.tr("No custom game folders added yet."))
            self._scan_folders_layout.addWidget(empty)
            return

        for folder in self._scan_folders:
            row = QFrame(self._scan_folders_container)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(8)
            path_lbl = QLabel(str(folder), row)
            path_lbl.setTextFormat(Qt.TextFormat.PlainText)
            path_lbl.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            path_lbl.setWordWrap(True)
            rescan_btn = QPushButton(self.tr("Rescan"), row)
            rescan_btn.clicked.connect(lambda _checked=False, f=str(folder): self.rescanFolderRequested.emit(f))
            remove_btn = QPushButton(self.tr("Remove"), row)
            remove_btn.clicked.connect(lambda _checked=False, f=str(folder): self.removeScanFolderRequested.emit(f))
            row_layout.addWidget(path_lbl, stretch=1)
            row_layout.addWidget(rescan_btn)
            row_layout.addWidget(remove_btn)
            self._scan_folders_layout.addWidget(row)

    def _rebuild_protected_games_list(self) -> None:
        while self._protected_games_layout.count():
            item = self._protected_games_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._protected_games_rows:
            empty = QLabel(
                self.tr("No protected games detected on this PC yet."),
                self._protected_games_container,
            )
            empty.setObjectName("mutedText")
            empty.setWordWrap(True)
            self._protected_games_layout.addWidget(empty)
            return

        for game_id, name, anti_cheat, mode in self._protected_games_rows:
            row_widget = QFrame(self._protected_games_container)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(10)

            info = QLabel(f"{name} ({anti_cheat})", row_widget)
            info.setTextFormat(Qt.TextFormat.PlainText)
            info.setWordWrap(True)
            combo = QComboBox(row_widget)
            combo.addItem(self.tr("Strict-exit (Default)"), "auto")
            combo.addItem(self.tr("Off for this game"), "full")
            combo.setCurrentIndex(1 if mode == "full" else 0)

            def _on_changed(
                index: int,
                gid: str = game_id,
                gname: str = name,
                box: QComboBox = combo,
            ) -> None:
                chosen = str(box.itemData(index) or "auto")
                if chosen == "full":
                    answer = QMessageBox.warning(
                        self,
                        self.tr("Turn off anti-cheat protection?"),
                        self.tr(
                            "This game uses anti-cheat software. Keeping protection on (Strict-exit) "
                            "ensures Game Hub closes before the game starts for zero ban risk. "
                            "Turn off protection for {game} anyway?"
                        ).format(game=gname),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        box.blockSignals(True)
                        box.setCurrentIndex(0)
                        box.blockSignals(False)
                        return
                self.protectedGameModeChanged.emit(gid, chosen)

            combo.currentIndexChanged.connect(_on_changed)
            row_layout.addWidget(info, stretch=1)
            row_layout.addWidget(combo)
            self._protected_games_layout.addWidget(row_widget)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = not busy and not self._restart_required
        self._save.setEnabled(enabled)
        self._move_folder.setEnabled(enabled)
        self._reset_defaults_btn.setEnabled(enabled)
        self._add_scan_folder_btn.setEnabled(enabled)
        self._open_folder.setEnabled(not busy)
        self._sync_sgdb_controls()

    def set_restart_required(self) -> None:
        self._restart_required = True
        self._busy = False
        self._save.setEnabled(False)
        self._move_folder.setEnabled(False)
        self._reset_defaults_btn.setEnabled(False)
        self._add_scan_folder_btn.setEnabled(False)
        self._open_folder.setEnabled(True)
        self._sync_sgdb_controls()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and not self._busy:
            self.backRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def show_field_errors(self, errors: dict[str, str]) -> None:
        self._error_codes = dict(errors)
        self._status_code = None
        for key, label in self._error_labels.items():
            code = errors.get(key)
            if code:
                label.setText(self._message_for_code(code))
                label.show()
            else:
                label.clear()
                label.hide()
        if "_storage" in errors:
            self._status_code = errors["_storage"]
            self._status.setText(self._message_for_code(errors["_storage"]))
            self._status.show()
        else:
            self._status.clear()
            self._status.hide()

    def show_status(self, code: str) -> None:
        self._error_codes.clear()
        for label in self._error_labels.values():
            label.clear()
            label.hide()
        self._status_code = code
        self._status.setText(self._message_for_code(code))
        self._status.show()

    def retranslate_ui(self) -> None:
        self._back.setText(self.tr("Back to Library"))
        self._title.setText(self.tr("Settings"))

        # 1. General
        self._lang_group.setTitle(self.tr("General"))
        self._lang_label.setText(self.tr("Display language"))
        self._lang_hint.setText(
            self.tr("Choose English or Arabic. Right-to-left layout switches immediately.")
        )
        self._theme_label.setText(self.tr("Theme"))
        self._theme_hint.setText(
            self.tr("Pick Dark, Light, or automatically match your Windows theme.")
        )
        self._theme.setItemText(0, self.tr("Dark"))
        self._theme.setItemText(1, self.tr("Light"))
        self._theme.setItemText(2, self.tr("System"))

        # 2. Capture and notes
        self._capture_group.setTitle(self.tr("Capture and notes"))
        self._interval_label.setText(self.tr("Capture interval (seconds)"))
        self._interval_hint.setText(
            self.tr("How often Game Hub saves a quiet screenshot while you play a single-player game.")
        )
        self._buffer_label.setText(self.tr("Screenshot ring size"))
        self._buffer_hint.setText(
            self.tr("How many recent screenshots to keep per game before replacing the oldest one.")
        )
        self._autoplay.setText(self.tr("Autoplay voice notes"))
        self._autoplay_hint.setText(
            self.tr("Play your latest voice reminder automatically when the Last time card opens.")
        )
        self._prompt_on_end.setText(self.tr("Ask for a note when a game closes"))
        self._prompt_on_end_hint.setText(
            self.tr("Offer a quick voice or text note right after you finish a game session.")
        )
        self._hotkeys_heading.setText(self.tr("Global shortcuts"))
        self._hotkeys_hint.setText(
            self.tr("Use Ctrl, Alt, or Shift with a letter, digit, or F1–F12. Leave blank to disable.")
        )
        self._hk_record_label.setText(self.tr("Record voice note"))
        self._hk_record_hint.setText(
            self.tr("Press during gameplay to start or stop recording a voice reminder.")
        )
        self._hk_record.setPlaceholderText("Ctrl+Alt+N")
        self._hk_last_label.setText(self.tr("Reopen Last time card"))
        self._hk_last_hint.setText(
            self.tr("Bring back your last screenshots, voice note, and controls at any time.")
        )
        self._hk_last.setPlaceholderText("Ctrl+Alt+L")
        self._hk_pin_label.setText(self.tr("Pin controls screenshot"))
        self._hk_pin_hint.setText(
            self.tr("Capture the current controls screen and pin it to the game's page.")
        )
        self._hk_pin.setPlaceholderText("Ctrl+Alt+C")

        # 3. Protected games
        self._protection_group.setTitle(self.tr("Protected games"))
        self._external_behavior_label.setText(
            self.tr("When a protected game starts while Game Hub is open")
        )
        self._external_behavior_hint.setText(
            self.tr(
                "Recommended: Exit Game Hub automatically so zero presence stays next to anti-cheat games."
            )
        )
        self._external_behavior.setItemText(0, self.tr("Exit Game Hub automatically"))
        self._external_behavior.setItemText(1, self.tr("Switch to Strict mode"))
        self._external_behavior.setItemText(2, self.tr("Ask me (Windows notification)"))
        self._launchers_heading.setText(
            self.tr("Close Game Hub whenever this launcher is open")
        )
        self._launchers_hint.setText(
            self.tr(
                "Leave off for launchers where you play single-player story games; protected games still close Game Hub automatically."
            )
        )
        self._strict_riot.setText(self.tr("Riot Client (always on for Vanguard safety)"))
        self._launcher_checks["epic"].setText(
            self.tr("Epic Games Launcher (off by default so story games work)")
        )
        self._launcher_checks["ea"].setText(self.tr("EA app"))
        self._launcher_checks["battlenet"].setText(self.tr("Battle.net"))
        self._launcher_checks["ubisoft"].setText(self.tr("Ubisoft Connect"))
        self._launcher_checks["steam"].setText(self.tr("Steam"))
        self._detected_protected_heading.setText(
            self.tr("Detected protected games on this PC")
        )
        self._test_protection_btn.setText(self.tr("Test protection"))
        self._test_protection_hint.setText(
            self.tr("Runs a safe dummy check to verify Game Hub detects protected games in under a second.")
        )
        self._rebuild_protected_games_list()
        if self._last_test_result is not None:
            self.set_test_protection_result(*self._last_test_result)

        # 4. Library and folders
        self._data_group.setTitle(self.tr("Library and folders"))
        self._scan_folders_heading.setText(self.tr("Scan folders"))
        self._scan_folders_hint.setText(
            self.tr("Scan any local folder for standalone games. Uninstallers and helper tools are skipped automatically.")
        )
        self._add_scan_folder_btn.setText(self.tr("Add scan folder…"))
        self._rebuild_scan_folders_list()

        self._sgdb_heading.setText(self.tr("Optional cover art (SteamGridDB)"))
        self._sgdb_enabled.setText(
            self.tr("Fetch missing covers from SteamGridDB (optional, off by default)")
        )
        self._sgdb_hint.setText(
            self.tr(
                "This is the only optional internet feature in Game Hub. It sends only game titles using your own API key."
            )
        )
        self._sgdb_key_label.setText(self.tr("SteamGridDB API key"))
        self._sgdb_key_hint.setText(
            self.tr("Stored locally on your PC and never written to logs.")
        )
        self._fetch_covers_btn.setText(self.tr("Fetch missing covers now"))
        if self._last_fetch_count is not None:
            self.set_fetch_covers_result(self._last_fetch_count)

        self._data_folder_heading.setText(self.tr("Data folder"))
        self._data_folder_hint.setText(
            self.tr("Where Game Hub stores your notes, screenshots, custom covers, and local database.")
        )
        self._data_path_label.setAccessibleName(self.tr("Current data folder"))
        self._open_folder.setText(self.tr("Open folder"))
        self._move_folder.setText(self.tr("Move data folder…"))

        # 5. About and privacy
        self._about_group.setTitle(self.tr("About and privacy"))
        self._about_zero_bg.setText(
            self.tr(
                "Zero background: no system tray, no start with Windows, and no background "
                "services. Closing the main window exits Game Hub completely."
            )
        )
        self._about_anticheat.setText(
            self.tr(
                "Offline and anti-cheat safe: all notes and screenshots stay on your PC. "
                "Game Hub never injects, hooks, or reads game memory, and closes automatically "
                "before protected multiplayer games start."
            )
        )
        self._about_version.setText(
            self.tr("Game Hub v{version} · MIT License").format(version=__version__)
        )
        self._reset_defaults_btn.setText(self.tr("Reset to defaults"))
        self._reset_defaults_hint.setText(
            self.tr(
                "Restores settings, shortcuts, launcher toggles, and per-game protection to safe defaults. Your notes and screenshots are kept."
            )
        )
        self._save.setText(self.tr("Save settings"))
        if self._data_root != Path():
            self._data_path_label.setText(str(self._data_root))
        if self._error_codes:
            self.show_field_errors(dict(self._error_codes))
        elif self._status_code:
            self.show_status(self._status_code)

    def _make_error(self, key: str, parent: QWidget) -> QLabel:
        label = QLabel(parent)
        label.setObjectName("errorBanner")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.hide()
        self._error_labels[key] = label
        return label

    def _submit(self) -> None:
        patch = {
            "ui.language": self._language.currentData(),
            "ui.theme": self._theme.currentData(),
            "protection.external_behavior": self._external_behavior.currentData(),
            "protection.strict_launcher.epic": self._launcher_checks["epic"].isChecked(),
            "protection.strict_launcher.ea": self._launcher_checks["ea"].isChecked(),
            "protection.strict_launcher.battlenet": self._launcher_checks["battlenet"].isChecked(),
            "protection.strict_launcher.ubisoft": self._launcher_checks["ubisoft"].isChecked(),
            "protection.strict_launcher.steam": self._launcher_checks["steam"].isChecked(),
            "capture.interval_sec": self._interval.value(),
            "capture.buffer_size": self._buffer.value(),
            "memory.autoplay_voice": self._autoplay.isChecked(),
            "memory.prompt_on_end": self._prompt_on_end.isChecked(),
            "hotkey.record_note": self._hk_record.text().strip(),
            "hotkey.last_time": self._hk_last.text().strip(),
            "hotkey.pin_controls": self._hk_pin.text().strip(),
            "covers.steamgriddb_enabled": self._sgdb_enabled.isChecked(),
            "covers.steamgriddb_api_key": self._sgdb_api_key.text().strip(),
        }
        self.saveRequested.emit(patch)

    def _confirm_reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Reset settings to defaults?"),
            self.tr(
                "This restores all settings, shortcuts, launcher toggles, and per-game anti-cheat protection back to their safe defaults. Your saved notes and screenshots will not be deleted."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.resetDefaultsRequested.emit()

    def _pick_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose a new empty data folder"))
        if folder:
            self.moveFolderRequested.emit(folder)

    def _pick_scan_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose a folder to scan"))
        if folder:
            self.addScanFolderRequested.emit(folder)

    def _message_for_code(self, code: str) -> str:
        messages = {
            "settings_saved": self.tr("Settings saved."),
            "settings_reset": self.tr("Settings restored to defaults."),
            "location_moved_restart": self.tr(
                "Data folder verified and updated. Restart Game Hub to use the new location."
            ),
            "invalid_language": self.tr("Select English or Arabic."),
            "invalid_theme": self.tr("Select Dark, Light, or System."),
            "invalid_external_behavior": self.tr("Select a supported protected-game action."),
            "invalid_capture_interval": self.tr("Choose an interval between 5 and 300 seconds."),
            "invalid_buffer_size": self.tr("Choose a screenshot ring size between 1 and 50."),
            "invalid_api_key": self.tr("Enter a valid ASCII API key (up to 128 characters)."),
            "invalid_shortcut": self.tr(
                "Enter a shortcut such as Ctrl+Alt+N, or leave blank to disable."
            ),
            "duplicate_shortcut": self.tr("Each enabled shortcut must be unique."),
            "shortcut_conflict": self.tr(
                "Windows rejected this shortcut because another app uses it. The previous shortcut remains active."
            ),
            "hotkeys_unavailable": self.tr("Global shortcuts are currently unavailable."),
            "storage_unavailable": self.tr("Game Hub could not save your settings."),
            "location_invalid": self.tr("Choose a local folder on a fixed drive without symlinks."),
            "location_same": self.tr("This folder is already your active data folder."),
            "location_nested": self.tr("Choose a folder outside the current data folder."),
            "location_not_directory": self.tr("The selected path is not a folder."),
            "location_not_empty": self.tr("Choose an empty folder for the moved data store."),
            "location_unwritable": self.tr("Game Hub cannot write to the selected folder."),
            "location_move_failed": self.tr(
                "Game Hub could not move the data folder. Your previous folder remains active."
            ),
            "open_folder_failed": self.tr("Game Hub could not open the data folder."),
        }
        return messages.get(code, self.tr("Game Hub could not apply this setting."))
