"""Collect a text or voice note for an ended game session."""

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NoteDialog(QDialog):
    textRequested = Signal(str)
    recordRequested = Signal()
    promptDisabled = Signal()

    def __init__(self, game_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Record a note?"))
        self.resize(440, 310)
        self._recording = False
        self._voice_retry = False
        self._busy = False
        self._preference_applied = False

        game = QLabel(self)
        game.setTextFormat(Qt.TextFormat.PlainText)
        game.setWordWrap(True)
        game.setText(game_name)
        game_font = game.font()
        game_font.setBold(True)
        game.setFont(game_font)

        self._record = QPushButton(self)
        self._update_record_label()
        self._record.clicked.connect(self.recordRequested)
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._show_elapsed)
        self._status = QLabel(self)
        self._status.hide()

        record_row = QHBoxLayout()
        record_row.addWidget(self._record)
        record_row.addWidget(self._status)
        record_row.addStretch()

        text_label = QLabel(self.tr("&Text note"), self)
        self._text = QPlainTextEdit(self)
        self._text.setAccessibleName(self.tr("Text note"))
        self._text.setTabChangesFocus(True)
        self._text.textChanged.connect(self._update_actions)
        text_label.setBuddy(self._text)

        self._error = QLabel(self)
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        self._disable_prompt = QCheckBox(self.tr("Don't ask after games"), self)
        self.finished.connect(self._apply_prompt_preference)
        actions = QDialogButtonBox(self)
        self._save = actions.addButton(self.tr("&Save text"), QDialogButtonBox.ButtonRole.AcceptRole)
        self._save.clicked.connect(self._submit_text)
        dismiss = actions.addButton(self.tr("&Dismiss"), QDialogButtonBox.ButtonRole.RejectRole)
        actions.rejected.connect(self.reject)
        self._save.setAutoDefault(False)
        dismiss.setAutoDefault(False)

        layout = QVBoxLayout(self)
        layout.addWidget(game)
        layout.addLayout(record_row)
        layout.addWidget(text_label)
        layout.addWidget(self._text, stretch=1)
        layout.addWidget(self._error)
        layout.addWidget(self._disable_prompt)
        layout.addWidget(actions)

        QWidget.setTabOrder(self._record, self._text)
        QWidget.setTabOrder(self._text, self._disable_prompt)
        QWidget.setTabOrder(self._disable_prompt, self._save)
        QWidget.setTabOrder(self._save, dismiss)
        self._text.setFocus()
        self._update_actions()

    def set_recording(self, recording: bool) -> None:
        if self._recording == recording:
            return
        self._recording = recording
        if recording:
            self._elapsed.start()
            self._show_elapsed()
            self._timer.start()
        else:
            self._timer.stop()
        self._update_record_label()
        self._update_status()
        self._update_actions()

    def set_voice_retry(self, available: bool) -> None:
        """Let the controller retry an existing clip with the voice button."""
        self._voice_retry = available
        self._update_record_label()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._text.setReadOnly(busy)
        self._update_status()
        self._update_actions()

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def clear_error(self) -> None:
        self.show_error("")

    def _update_record_label(self) -> None:
        description = ""
        if self._recording:
            label = self.tr("&Stop recording")
        elif self._voice_retry:
            label = self.tr("&Retry voice save")
        else:
            label = self.tr("&Record voice")
            description = self.tr("Records up to 60 seconds.")
        self._record.setText(label)
        self._record.setAccessibleDescription(description)

    def _update_status(self) -> None:
        if self._busy and not self._recording:
            self._status.setText(self.tr("Working…"))
        self._status.setVisible(self._busy or self._recording)

    def _update_actions(self) -> None:
        self._record.setEnabled(not self._busy)
        self._save.setEnabled(not self._busy and not self._recording and bool(self._text.toPlainText().strip()))

    def _show_elapsed(self) -> None:
        minutes, seconds = divmod(self._elapsed.elapsed() // 1000, 60)
        self._status.setText(
            self.tr("Recording · {minutes}:{seconds:02d}").format(minutes=minutes, seconds=seconds)
        )

    def _submit_text(self) -> None:
        self.textRequested.emit(self._text.toPlainText())

    def _apply_prompt_preference(self) -> None:
        self._timer.stop()
        if self._disable_prompt.isChecked() and not self._preference_applied:
            self._preference_applied = True
            self.promptDisabled.emit()
