"""Editable application settings with adjacent error feedback and data-folder controls."""

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


class SettingsView(QWidget):
    backRequested = Signal()
    saveRequested = Signal(dict)
    openFolderRequested = Signal()
    moveFolderRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data_root = Path()
        self._busy = False
        self._restart_required = False
        self._error_labels: dict[str, QLabel] = {}
        self._error_codes: dict[str, str] = {}
        self._status_code: str | None = None

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

        # Language & Appearance group
        self._lang_group = QGroupBox(body)
        lang_form = QFormLayout(self._lang_group)
        self._lang_label = QLabel(self._lang_group)
        self._lang_label.setWordWrap(True)
        self._language = QComboBox(self._lang_group)
        self._language.addItem("English", "en")
        self._language.addItem("العربية", "ar")
        self._lang_label.setBuddy(self._language)
        lang_form.addRow(self._lang_label, self._language)
        lang_form.addRow(self._make_error("ui.language", self._lang_group))

        self._theme_label = QLabel(self._lang_group)
        self._theme_label.setWordWrap(True)
        self._theme = QComboBox(self._lang_group)
        self._theme.addItem("", "dark")
        self._theme.addItem("", "light")
        self._theme.addItem("", "system")
        self._theme_label.setBuddy(self._theme)
        lang_form.addRow(self._theme_label, self._theme)
        lang_form.addRow(self._make_error("ui.theme", self._lang_group))
        body_layout.addWidget(self._lang_group)

        # Anti-cheat protection group
        self._protection_group = QGroupBox(body)
        protection_form = QFormLayout(self._protection_group)
        self._external_behavior_label = QLabel(self._protection_group)
        self._external_behavior_label.setWordWrap(True)
        self._external_behavior = QComboBox(self._protection_group)
        self._external_behavior.addItem("", "exit_app")
        self._external_behavior.addItem("", "strict_mode")
        self._external_behavior.addItem("", "ask_me")
        self._external_behavior_label.setBuddy(self._external_behavior)
        protection_form.addRow(self._external_behavior_label, self._external_behavior)
        protection_form.addRow(
            self._make_error("protection.external_behavior", self._protection_group)
        )
        body_layout.addWidget(self._protection_group)

        # Capture group
        self._capture_group = QGroupBox(body)
        capture_form = QFormLayout(self._capture_group)
        self._interval_label = QLabel(self._capture_group)
        self._interval_label.setWordWrap(True)
        self._interval = QSpinBox(self._capture_group)
        self._interval.setRange(MIN_CAPTURE_INTERVAL_SEC, MAX_CAPTURE_INTERVAL_SEC)
        self._interval_label.setBuddy(self._interval)
        capture_form.addRow(self._interval_label, self._interval)
        capture_form.addRow(self._make_error("capture.interval_sec", self._capture_group))

        self._buffer_label = QLabel(self._capture_group)
        self._buffer_label.setWordWrap(True)
        self._buffer = QSpinBox(self._capture_group)
        self._buffer.setRange(MIN_BUFFER_SIZE, MAX_BUFFER_SIZE)
        self._buffer_label.setBuddy(self._buffer)
        capture_form.addRow(self._buffer_label, self._buffer)
        capture_form.addRow(self._make_error("capture.buffer_size", self._capture_group))
        body_layout.addWidget(self._capture_group)

        # Notes & Last time group
        self._notes_group = QGroupBox(body)
        notes_layout = QVBoxLayout(self._notes_group)
        self._autoplay = QCheckBox(self._notes_group)
        self._prompt_on_end = QCheckBox(self._notes_group)
        notes_layout.addWidget(self._autoplay)
        notes_layout.addWidget(self._prompt_on_end)
        body_layout.addWidget(self._notes_group)

        # Hotkeys group
        self._hotkeys_group = QGroupBox(body)
        hotkeys_form = QFormLayout(self._hotkeys_group)
        self._hotkeys_hint = QLabel(self._hotkeys_group)
        self._hotkeys_hint.setWordWrap(True)
        hotkeys_form.addRow(self._hotkeys_hint)

        self._hk_record_label = QLabel(self._hotkeys_group)
        self._hk_record_label.setWordWrap(True)
        self._hk_record = QLineEdit(self._hotkeys_group)
        self._hk_record.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._hk_record_label.setBuddy(self._hk_record)
        hotkeys_form.addRow(self._hk_record_label, self._hk_record)
        hotkeys_form.addRow(self._make_error("hotkey.record_note", self._hotkeys_group))

        self._hk_last_label = QLabel(self._hotkeys_group)
        self._hk_last_label.setWordWrap(True)
        self._hk_last = QLineEdit(self._hotkeys_group)
        self._hk_last.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._hk_last_label.setBuddy(self._hk_last)
        hotkeys_form.addRow(self._hk_last_label, self._hk_last)
        hotkeys_form.addRow(self._make_error("hotkey.last_time", self._hotkeys_group))

        self._hk_pin_label = QLabel(self._hotkeys_group)
        self._hk_pin_label.setWordWrap(True)
        self._hk_pin = QLineEdit(self._hotkeys_group)
        self._hk_pin.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._hk_pin_label.setBuddy(self._hk_pin)
        hotkeys_form.addRow(self._hk_pin_label, self._hk_pin)
        hotkeys_form.addRow(self._make_error("hotkey.pin_controls", self._hotkeys_group))
        body_layout.addWidget(self._hotkeys_group)

        # Data folder group
        self._data_group = QGroupBox(body)
        data_layout = QVBoxLayout(self._data_group)
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

        # About & Privacy group (zero-background + offline + anti-cheat guarantees)
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
        about_layout.addWidget(self._about_zero_bg)
        about_layout.addWidget(self._about_anticheat)
        about_layout.addWidget(self._about_version)
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
        self._interval.setValue(snapshot.capture_interval_sec)
        self._buffer.setValue(snapshot.capture_buffer_size)
        self._autoplay.setChecked(snapshot.autoplay_voice)
        self._prompt_on_end.setChecked(snapshot.prompt_on_end)
        self._hk_record.setText(snapshot.hotkey_record_note)
        self._hk_last.setText(snapshot.hotkey_last_time)
        self._hk_pin.setText(snapshot.hotkey_pin_controls)
        self._data_path_label.setText(str(data_root))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = not busy and not self._restart_required
        self._save.setEnabled(enabled)
        self._move_folder.setEnabled(enabled)
        self._open_folder.setEnabled(not busy)

    def set_restart_required(self) -> None:
        self._restart_required = True
        self._busy = False
        self._save.setEnabled(False)
        self._move_folder.setEnabled(False)
        self._open_folder.setEnabled(True)

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
        self._lang_group.setTitle(self.tr("Language and appearance"))
        self._lang_label.setText(self.tr("Display language"))
        self._theme_label.setText(self.tr("Theme"))
        self._theme.setItemText(0, self.tr("Dark"))
        self._theme.setItemText(1, self.tr("Light"))
        self._theme.setItemText(2, self.tr("System"))
        self._protection_group.setTitle(self.tr("Anti-cheat protection"))
        self._external_behavior_label.setText(
            self.tr("When a protected game starts while Game Hub is open")
        )
        self._external_behavior.setItemText(0, self.tr("Exit Game Hub automatically"))
        self._external_behavior.setItemText(1, self.tr("Switch to Strict mode"))
        self._external_behavior.setItemText(2, self.tr("Ask me (Windows notification)"))
        self._capture_group.setTitle(self.tr("Screenshots"))
        self._interval_label.setText(self.tr("Capture interval (seconds)"))
        self._buffer_label.setText(self.tr("Screenshot ring size"))
        self._notes_group.setTitle(self.tr("Notes and Last time"))
        self._autoplay.setText(self.tr("Autoplay voice notes"))
        self._prompt_on_end.setText(self.tr("Ask for a note when a game closes"))
        self._hotkeys_group.setTitle(self.tr("Global shortcuts"))
        self._hotkeys_hint.setText(
            self.tr("Use Ctrl, Alt, or Shift with a letter, digit, or F1–F12. Leave blank to disable.")
        )
        self._hk_record_label.setText(self.tr("Record voice note"))
        self._hk_record.setPlaceholderText("Ctrl+Alt+N")
        self._hk_last_label.setText(self.tr("Reopen Last time card"))
        self._hk_last.setPlaceholderText("Ctrl+Alt+L")
        self._hk_pin_label.setText(self.tr("Pin controls screenshot"))
        self._hk_pin.setPlaceholderText("Ctrl+Alt+C")
        self._data_group.setTitle(self.tr("Data folder"))
        self._data_path_label.setAccessibleName(self.tr("Current data folder"))
        self._open_folder.setText(self.tr("Open folder"))
        self._move_folder.setText(self.tr("Move data folder…"))
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
                "Game Hub never injects, hooks, or reads game memory, and defaults protected "
                "multiplayer games to Strict mode."
            )
        )
        self._about_version.setText(
            self.tr("Game Hub v{version} · MIT License").format(version=__version__)
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
            "capture.interval_sec": self._interval.value(),
            "capture.buffer_size": self._buffer.value(),
            "memory.autoplay_voice": self._autoplay.isChecked(),
            "memory.prompt_on_end": self._prompt_on_end.isChecked(),
            "hotkey.record_note": self._hk_record.text().strip(),
            "hotkey.last_time": self._hk_last.text().strip(),
            "hotkey.pin_controls": self._hk_pin.text().strip(),
        }
        self.saveRequested.emit(patch)

    def _pick_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Choose a new empty data folder"))
        if folder:
            self.moveFolderRequested.emit(folder)

    def _message_for_code(self, code: str) -> str:
        messages = {
            "settings_saved": self.tr("Settings saved."),
            "location_moved_restart": self.tr(
                "Data folder verified and updated. Restart Game Hub to use the new location."
            ),
            "invalid_language": self.tr("Select English or Arabic."),
            "invalid_theme": self.tr("Select Dark, Light, or System."),
            "invalid_external_behavior": self.tr("Select a supported protected-game action."),
            "invalid_capture_interval": self.tr("Choose an interval between 5 and 300 seconds."),
            "invalid_buffer_size": self.tr("Choose a screenshot ring size between 1 and 50."),
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
