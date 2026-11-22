"""Bind voice and text notes to the session that initiated them."""

import logging
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from gamehub.core.audio.recorder import AudioRecorder, RecordingError
from gamehub.core.sessions.models import GameStopped, SessionIdentity
from gamehub.core.storage.db import StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.memory import MemoryChanged
from gamehub.core.storage.notes import MAX_TEXT_LENGTH, NoteRepository
from gamehub.modules.memory.note_dialog import NoteDialog

LOGGER = logging.getLogger(__name__)
MAX_RECORD_MS = 60_000


@dataclass(slots=True)
class _VoiceNote:
    game_id: str
    session_id: str
    source: str
    dialog: NoteDialog | None
    phase: str = "starting"
    stop_pending: bool = False
    cancellation: Event = field(default_factory=Event)
    clip: bytes | None = None


class NotesController(QObject):
    _done = Signal(object, object)

    def __init__(
        self,
        parent: QWidget,
        notes: NoteRepository,
        library: LibraryRepository,
        recorder: AudioRecorder,
        foreground_session: Callable[[], SessionIdentity | None],
        indicate_recording: Callable[[bool], None],
        notify: Callable[[str], None],
        *,
        publish: Callable[[MemoryChanged], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = parent
        self._notes = notes
        self._library = library
        self._recorder = recorder
        self._foreground_session = foreground_session
        self._indicate_recording = indicate_recording
        self._notify = notify
        self._publish = publish
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game-notes")
        self._done.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._stop_voice)
        self._queue: deque[GameStopped] = deque()
        self._dialog: NoteDialog | None = None
        self._voice: _VoiceNote | None = None
        self._prompts_enabled = notes.prompt_enabled()

    def set_prompts_enabled(self, enabled: bool) -> None:
        self._prompts_enabled = enabled
        if not enabled:
            self._queue.clear()

    def game_stopped(self, event: GameStopped) -> None:
        voice = self._voice
        if (
            voice is not None
            and voice.source == "hotkey"
            and voice.session_id == event.session_id
            and voice.phase in {"starting", "recording"}
        ):
            self._stop_voice()
        if self._prompts_enabled and event.status == "completed" and event.reason == "process_exit":
            self._queue.append(event)
            self._show_next()

    def toggle_hotkey(self) -> None:
        if self._voice is not None:
            self._stop_voice()
            return
        session = self._foreground_session()
        if session is not None:
            self._start_voice(session.game_id, session.session_id, "hotkey", expected=session)

    def _show_next(self) -> None:
        if self._dialog is not None:
            return
        while self._queue:
            event = self._queue.popleft()
            try:
                game = self._library.get_game(event.game_id)
            except StorageError:
                LOGGER.warning("note_prompt_library_unavailable")
                continue
            if game is None:
                continue
            dialog = NoteDialog(game.name, self._window)
            self._dialog = dialog
            dialog.textRequested.connect(
                lambda text, d=dialog, gid=event.game_id, sid=event.session_id: self._save_text(
                    d, gid, sid, text
                )
            )
            dialog.recordRequested.connect(
                lambda d=dialog, gid=event.game_id, sid=event.session_id: self._toggle_from_prompt(
                    d, gid, sid
                )
            )
            dialog.promptDisabled.connect(self._disable_prompts)
            dialog.finished.connect(lambda _, d=dialog: self._prompt_closed(d))
            dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            dialog.show()
            return

    def _disable_prompts(self) -> None:
        self._prompts_enabled = False
        self._queue.clear()

        def saved(future):
            try:
                future.result()
            except StorageError:
                self._notify(self.tr("Game Hub could not save the note prompt preference."))

        self._submit(lambda: self._notes.set_prompt_enabled(False), saved)

    def _prompt_closed(self, dialog: NoteDialog) -> None:
        if self._dialog is not dialog:
            return
        self._dialog = None
        voice = self._voice
        if voice is not None and voice.dialog is dialog:
            if voice.phase == "starting":
                voice.cancellation.set()
            elif voice.phase == "recording":
                self._discard_voice(voice)
            elif voice.phase == "retry":
                self._voice = None
        dialog.deleteLater()
        QTimer.singleShot(0, self, self._show_next)

    def _save_text(self, dialog: NoteDialog, game_id: str, session_id: str, text: str) -> None:
        dialog.clear_error()
        dialog.set_busy(True)

        def saved(future):
            try:
                note_id = future.result()
            except StorageError:
                self._show_error(dialog, self.tr("Game Hub could not save this text note."))
                if self._dialog is dialog:
                    dialog.set_busy(False)
            except ValueError:
                self._show_error(
                    dialog,
                    self.tr("Enter a nonblank note of up to {limit} characters.").format(limit=MAX_TEXT_LENGTH),
                )
                if self._dialog is dialog:
                    dialog.set_busy(False)
            else:
                if self._publish is not None:
                    self._publish(MemoryChanged(game_id, session_id, "text_note", note_id))
                if self._dialog is dialog:
                    dialog.accept()

        self._submit(lambda: self._notes.save_text(session_id, text), saved)

    def _toggle_from_prompt(self, dialog: NoteDialog, game_id: str, session_id: str) -> None:
        if self._voice is None:
            self._start_voice(game_id, session_id, "popup", dialog)
        elif self._voice.dialog is dialog:
            self._stop_voice()
        else:
            dialog.show_error(self.tr("Another voice note is recording or being saved."))

    def _start_voice(
        self,
        game_id: str,
        session_id: str,
        source: str,
        dialog: NoteDialog | None = None,
        *,
        expected: SessionIdentity | None = None,
    ) -> None:
        voice = _VoiceNote(game_id, session_id, source, dialog)
        self._voice = voice
        if dialog is not None:
            dialog.clear_error()
            dialog.set_busy(True)

        def start():
            if voice.cancellation.is_set() or (
                expected is not None and self._foreground_session() != expected
            ):
                return False
            self._recorder.start()
            if voice.cancellation.is_set():
                self._recorder.abort()
                return False
            return True

        self._submit(start, lambda future: self._voice_started(voice, future))

    def _voice_started(self, voice: _VoiceNote, future: Future) -> None:
        dialog = voice.dialog
        try:
            started = future.result()
        except RecordingError:
            if not voice.cancellation.is_set():
                self._show_error(
                    dialog, self.tr("Microphone unavailable. Check Windows microphone access or save a text note.")
                )
            started = False
        if not started:
            self._voice = None
            if dialog is not None and self._dialog is dialog:
                dialog.set_busy(False)
            return
        if voice.cancellation.is_set():
            self._discard_voice(voice)
            return
        voice.phase = "recording"
        self._indicate_recording(True)
        self._timer.start(MAX_RECORD_MS)
        if dialog is not None and self._dialog is dialog:
            dialog.set_recording(True)
            dialog.set_busy(False)
        elif voice.source == "hotkey":
            self._notify(self.tr("Recording voice note. Press Ctrl+Alt+N to stop."))
        if voice.stop_pending:
            self._stop_voice()

    def _discard_voice(self, voice: _VoiceNote) -> None:
        self._timer.stop()
        voice.phase = "stopping"

        def discarded(_future):
            self._indicate_recording(False)
            self._finish_voice(voice)

        self._submit(self._recorder.abort, discarded)

    def _stop_voice(self) -> None:
        voice = self._voice
        if voice is None:
            return
        if voice.phase == "starting":
            voice.stop_pending = True
            return
        if voice.phase == "retry":
            self._save_clip(voice)
            return
        if voice.phase != "recording":
            return
        self._timer.stop()
        voice.phase = "stopping"
        if voice.dialog is not None and self._dialog is voice.dialog:
            voice.dialog.set_recording(False)
            voice.dialog.set_busy(True)
        self._submit(self._recorder.stop, lambda future: self._voice_encoded(voice, future))

    def _voice_encoded(self, voice: _VoiceNote, future: Future) -> None:
        self._indicate_recording(False)
        try:
            voice.clip = future.result()
        except RecordingError:
            self._finish_voice(voice)
            self._show_error(
                voice.dialog, self.tr("No voice note could be recorded. Try recording again or save a text note.")
            )
        else:
            self._save_clip(voice)

    def _save_clip(self, voice: _VoiceNote) -> None:
        clip = voice.clip
        if clip is None:
            return
        voice.phase = "saving"
        dialog = voice.dialog
        if dialog is not None and self._dialog is dialog:
            dialog.set_voice_retry(False)
            dialog.set_busy(True)
        self._submit(
            lambda: self._notes.save_voice(voice.session_id, clip, voice.source),
            lambda future: self._voice_saved(voice, future),
        )

    def _finish_voice(self, voice: _VoiceNote) -> None:
        self._voice = None
        dialog = voice.dialog
        if dialog is not None and self._dialog is dialog:
            dialog.set_voice_retry(False)
            dialog.set_recording(False)
            dialog.set_busy(False)

    def _voice_saved(self, voice: _VoiceNote, future: Future) -> None:
        dialog = voice.dialog
        try:
            note_id = future.result()
        except StorageError:
            self._retry_voice(voice)
        except ValueError:
            self._finish_voice(voice)
            self._show_error(dialog, self.tr("Game Hub could not save this voice note."))
        else:
            self._finish_voice(voice)
            if self._publish is not None:
                self._publish(MemoryChanged(voice.game_id, voice.session_id, "voice_note", note_id))
            if dialog is not None and self._dialog is dialog:
                dialog.accept()
            elif dialog is None:
                self._notify(self.tr("Voice note saved."))

    def _retry_voice(self, voice: _VoiceNote) -> None:
        voice.phase = "retry"
        dialog = voice.dialog
        if dialog is None:
            self._notify(self.tr("Game Hub could not save the voice note. Press Ctrl+Alt+N to retry."))
        elif self._dialog is dialog:
            dialog.set_busy(False)
            dialog.set_voice_retry(True)
            dialog.show_error(self.tr("Game Hub could not save this voice note. You can retry or dismiss it."))
        else:
            self._finish_voice(voice)

    def _show_error(self, dialog: NoteDialog | None, message: str) -> None:
        if dialog is not None and self._dialog is dialog:
            dialog.show_error(message)
        else:
            self._notify(message)

    def _submit(self, work: Callable, done: Callable[[Future], None]) -> None:
        self._worker.submit(work).add_done_callback(lambda future: self._done.emit(done, future))

    @Slot(object, object)
    def _complete(self, done: Callable[[Future], None], future: Future) -> None:
        done(future)

    def close(self) -> None:
        self._timer.stop()
        if self._voice is not None:
            self._voice.cancellation.set()
        self._worker.submit(self._recorder.abort)
        self._worker.shutdown()
