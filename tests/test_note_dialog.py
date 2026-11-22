import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from gamehub.modules.memory.note_dialog import NoteDialog


@pytest.fixture(scope="module")
def app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Game Hub test"])


def test_text_note_preserves_draft_until_controller_accepts(app: QApplication) -> None:
    dialog = NoteDialog("Example <Game>")
    requested = []
    dialog.textRequested.connect(requested.append)
    dialog.show()
    app.processEvents()

    try:
        assert dialog._text.hasFocus()
        assert not dialog._save.isEnabled()
        dialog._text.setPlainText(" \n ")
        assert not dialog._save.isEnabled()
        draft = "Find the next gate.\nKeep the key."
        dialog._text.setPlainText(draft)
        QTest.keyClick(dialog._save, Qt.Key.Key_Space)
        assert requested == [draft]
        assert dialog.isVisible()

        dialog.set_busy(True)
        assert not dialog._save.isEnabled()
        assert not dialog._record.isEnabled()
        assert dialog._text.isReadOnly()
        dialog.show_error("Microphone is unavailable. You can still save a text note.")
        dialog.set_busy(False)
        assert dialog._error.isVisible()
        assert dialog._text.toPlainText() == draft
        assert not dialog._text.isReadOnly()
        assert dialog._save.isEnabled()
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        dialog.close()


def test_record_and_dismiss_emit_without_saving_text(app: QApplication) -> None:
    dialog = NoteDialog("Example Game")
    events = []
    dialog.recordRequested.connect(lambda: events.append("record"))
    dialog.textRequested.connect(lambda _text: events.append("text"))
    dialog.promptDisabled.connect(lambda: events.append("disable"))
    dialog.show()
    app.processEvents()

    try:
        dialog._text.setPlainText("Keep this draft.")
        dialog._disable_prompt.setChecked(True)
        assert events == []
        QTest.keyClick(dialog._record, Qt.Key.Key_Space)
        dialog.set_recording(True)
        assert dialog._status.text() == "Recording · 0:00"
        assert dialog._status.isVisible()
        assert not dialog._save.isEnabled()

        QTest.keyClick(dialog._record, Qt.Key.Key_Space)
        dialog.set_recording(False)
        assert not dialog._status.isVisible()
        assert dialog._save.isEnabled()
        dialog.set_recording(True)
        dialog.set_busy(True)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not dialog._timer.isActive()
        dialog.reject()
        assert events == ["record", "record", "disable"]
    finally:
        dialog.close()


def test_voice_save_retry_keeps_text_fallback_and_reports_work(app: QApplication) -> None:
    dialog = NoteDialog("Example Game")
    requested = []
    dialog.recordRequested.connect(lambda: requested.append("retry"))
    dialog.show()
    app.processEvents()

    try:
        dialog._text.setPlainText("A fallback draft.")
        dialog.set_busy(True)
        assert dialog._status.isVisible()
        assert dialog._status.text() == "Working…"
        dialog.set_voice_retry(True)
        dialog.set_busy(False)
        assert not dialog._status.isVisible()
        assert dialog._record.text() == "&Retry voice save"
        assert dialog._save.isEnabled()
        QTest.keyClick(dialog._record, Qt.Key.Key_Space)
        assert requested == ["retry"]
        assert dialog._text.toPlainText() == "A fallback draft."
        dialog.set_voice_retry(False)
        assert dialog._record.text() == "&Record voice"
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        dialog.close()
