"""Per-game page with Play, pinned Controls, and chronological Session Timeline."""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QBuffer, QDateTime, QIODevice, QLocale, QSize, Qt, Signal
from PySide6.QtGui import QImageReader, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gamehub.core.library.models import GameSource, GameSummary
from gamehub.core.storage.controls import ControlItem
from gamehub.core.storage.memory import SessionCursor, TimelinePage, TimelineSession
from gamehub.ui.last_moments import LastMomentsDialog


def _format_timestamp(utc_ms: int) -> str:
    date = QDateTime.fromMSecsSinceEpoch(utc_ms).toLocalTime()
    return QLocale().toString(date, QLocale.FormatType.ShortFormat)


def _format_duration(widget: QWidget, seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return widget.tr("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
    if minutes or not secs:
        return widget.tr("{minutes} min").format(minutes=minutes)
    return widget.tr("{seconds} sec").format(seconds=secs)


def _decode_webp(encoded: bytes | None) -> QPixmap:
    if not encoded:
        return QPixmap()
    buffer = QBuffer()
    buffer.setData(encoded)
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        return QPixmap()
    reader = QImageReader(buffer, b"webp")
    size = reader.size()
    if size.isEmpty() or size.width() * size.height() > 64_000_000:
        return QPixmap()
    if size.width() > 2560 or size.height() > 1440:
        reader.setScaledSize(size.scaled(QSize(2560, 1440), Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())


class GamePage(QWidget):
    backRequested = Signal()
    playRequested = Signal(str)
    uploadControlImageRequested = Signal(str, str)
    saveControlTextRequested = Signal(str, str)
    loadMoreTimelineRequested = Signal(str, object)
    playVoiceNoteRequested = Signal(object)
    stopVoiceNoteRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        load_control_image: Callable[[Path], bytes | None] | None = None,
        load_screenshot: Callable[[Path], bytes | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._load_control_image = load_control_image or (lambda _path: None)
        self._load_screenshot = load_screenshot or (lambda _path: None)
        self._game: GameSummary | None = None
        self._control_images: tuple[ControlItem, ...] = ()
        self._control_index = 0
        self._control_pixmap = QPixmap()
        self._timeline_sessions: list[TimelineSession] = []
        self._next_cursor: SessionCursor | None = None
        self._playing_voice_id: str | None = None
        self._pending_voice_id: str | None = None
        self._voice_playing = False
        self._saving_control_text = False
        self._voice_buttons: dict[str, tuple[QPushButton, QPushButton]] = {}

        # Header
        self._back = QPushButton(self.tr("&Back to Library"), self)
        self._back.clicked.connect(self._go_back)
        self._play = QPushButton(self.tr("&Play…"), self)
        self._play.clicked.connect(self._request_play)

        self._title = QLabel(self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)
        title_font = self._title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self._title.setFont(title_font)

        self._summary = QLabel(self)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)

        header_actions = QHBoxLayout()
        header_actions.addWidget(self._back)
        header_actions.addStretch()
        header_actions.addWidget(self._play)

        self._error = QLabel(self)
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_controls_tab(), self.tr("Controls"))
        self._tabs.addTab(self._build_timeline_tab(), self.tr("Timeline"))
        self._tabs.currentChanged.connect(lambda _index: self._fit_control_pixmap())

        layout = QVBoxLayout(self)
        layout.addLayout(header_actions)
        layout.addWidget(self._title)
        layout.addWidget(self._summary)
        layout.addWidget(self._error)
        layout.addWidget(self._tabs, stretch=1)

    @property
    def game_id(self) -> str | None:
        return self._game.id if self._game is not None else None

    def set_loaders(
        self,
        *,
        load_control_image: Callable[[Path], bytes | None],
        load_screenshot: Callable[[Path], bytes | None],
    ) -> None:
        self._load_control_image = load_control_image
        self._load_screenshot = load_screenshot

    def show_game(
        self,
        game: GameSummary,
        controls: Sequence[ControlItem],
        timeline: TimelinePage,
    ) -> None:
        switched = self._game is None or self._game.id != game.id
        self._game = game
        self.clear_error()
        if switched:
            self._control_index = 0
            self._control_input.clear()
            self.set_saving_control_text(False)
            self.reset_voice_state()
        self._title.setText(game.name)
        sources = {
            GameSource.STEAM: self.tr("Steam"),
            GameSource.EPIC: self.tr("Epic Games"),
            GameSource.XBOX: self.tr("Xbox"),
            GameSource.MANUAL: self.tr("Manual"),
        }
        last_played = (
            _format_timestamp(game.last_played)
            if game.last_played is not None
            else self.tr("Never")
        )
        self._summary.setText(
            self.tr("{source} · Last played {date} · Total playtime {playtime}").format(
                source=sources[game.source],
                date=last_played,
                playtime=_format_duration(self, game.total_playtime),
            )
        )
        self.present_controls(controls)
        self.present_timeline(timeline, append=False)

    def present_controls(
        self, controls: Sequence[ControlItem], *, select_latest: bool = False
    ) -> None:
        self._control_images = tuple(item for item in controls if item.kind == "image")
        if select_latest and self._control_images:
            self._control_index = len(self._control_images) - 1
        else:
            self._control_index = min(self._control_index, max(0, len(self._control_images) - 1))
        self._show_current_control_image()

        texts = [item for item in controls if item.kind == "text" and item.text]
        self._clear_layout(self._controls_text_list)
        if not texts:
            empty = QLabel(self.tr("No controls or strategy notes saved yet."), self)
            empty.setTextFormat(Qt.TextFormat.PlainText)
            empty.setWordWrap(True)
            self._controls_text_list.addWidget(empty)
        else:
            for item in texts:
                entry = QLabel(
                    self.tr("Saved {date}\n{text}").format(
                        date=_format_timestamp(item.created_at), text=item.text
                    ),
                    self,
                )
                entry.setTextFormat(Qt.TextFormat.PlainText)
                entry.setWordWrap(True)
                entry.setFrameShape(QFrame.Shape.StyledPanel)
                entry.setMargin(6)
                entry.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                self._controls_text_list.addWidget(entry)

    def present_timeline(self, page: TimelinePage, *, append: bool) -> None:
        if not append:
            self._timeline_sessions = list(page.sessions)
        else:
            self._timeline_sessions.extend(page.sessions)
        self._next_cursor = page.next_cursor
        self._rebuild_timeline_widgets()

    def clear_control_input(self) -> None:
        self._control_input.clear()
        self.set_saving_control_text(False)

    def set_saving_control_text(self, saving: bool) -> None:
        self._saving_control_text = saving
        self._save_control_text.setEnabled(not saving)
        self._control_input.setReadOnly(saving)

    def reset_voice_state(self) -> None:
        self._pending_voice_id = None
        self._playing_voice_id = None
        self._voice_playing = False
        self._sync_voice_buttons()

    def set_voice_playing(self, playing: bool) -> None:
        if playing:
            if self._pending_voice_id is not None:
                self._playing_voice_id = self._pending_voice_id
                self._pending_voice_id = None
            self._voice_playing = True
        else:
            self._voice_playing = False
            if self._pending_voice_id is None:
                self._playing_voice_id = None
        self._sync_voice_buttons()

    def _sync_voice_buttons(self) -> None:
        for note_id, (play_btn, stop_btn) in self._voice_buttons.items():
            active = self._voice_playing and note_id == self._playing_voice_id
            stop_btn.setEnabled(active)
            play_btn.setText(self.tr("Replay") if active else self.tr("Play"))

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def clear_error(self) -> None:
        self.show_error("")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_control_pixmap()

    def _build_controls_tab(self) -> QWidget:
        content = QWidget(self)
        layout = QVBoxLayout(content)

        hint = QLabel(
            self.tr(
                "Press Ctrl+Alt+C while this game is focused to pin its controls screen, "
                "or upload a local image below."
            ),
            content,
        )
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._upload_image = QPushButton(self.tr("&Upload controls image…"), content)
        self._upload_image.clicked.connect(self._pick_control_image)
        upload_row = QHBoxLayout()
        upload_row.addWidget(self._upload_image)
        upload_row.addStretch()
        layout.addLayout(upload_row)

        self._control_preview = QLabel(content)
        self._control_preview.setAccessibleName(self.tr("Pinned controls image preview"))
        self._control_preview.setTextFormat(Qt.TextFormat.PlainText)
        self._control_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._control_preview.setWordWrap(True)
        self._control_preview.setFrameShape(QFrame.Shape.StyledPanel)
        self._control_preview.setMinimumSize(300, 180)
        self._control_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._control_preview)

        self._prev_control = QPushButton(self.tr("Pre&vious"), content)
        self._prev_control.setAccessibleName(self.tr("Previous controls image"))
        self._prev_control.clicked.connect(lambda: self._move_control(-1))
        self._next_control = QPushButton(self.tr("&Next"), content)
        self._next_control.setAccessibleName(self.tr("Next controls image"))
        self._next_control.clicked.connect(lambda: self._move_control(1))
        self._control_position = QLabel(content)
        self._control_position.setTextFormat(Qt.TextFormat.PlainText)
        self._control_position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav = QHBoxLayout()
        nav.addWidget(self._prev_control)
        nav.addWidget(self._control_position, stretch=1)
        nav.addWidget(self._next_control)
        layout.addLayout(nav)

        note_label = QLabel(self.tr("Controls and stra&tegy notes"), content)
        note_label.setWordWrap(True)
        self._control_input = QPlainTextEdit(content)
        self._control_input.setAccessibleName(self.tr("Controls and strategy note"))
        self._control_input.setTabChangesFocus(True)
        self._control_input.setPlaceholderText(
            self.tr("Key bindings, combat tips, or reminders for this game…")
        )
        self._control_input.setMinimumHeight(70)
        self._control_input.setMaximumHeight(120)
        note_label.setBuddy(self._control_input)

        self._save_control_text = QPushButton(self.tr("&Save controls note"), content)
        self._save_control_text.clicked.connect(self._submit_control_text)
        save_row = QHBoxLayout()
        save_row.addWidget(self._save_control_text)
        save_row.addStretch()

        self._controls_text_list = QVBoxLayout()
        layout.addWidget(note_label)
        layout.addWidget(self._control_input)
        layout.addLayout(save_row)
        layout.addLayout(self._controls_text_list)
        layout.addStretch()

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_timeline_tab(self) -> QWidget:
        content = QWidget(self)
        outer = QVBoxLayout(content)
        self._timeline_list = QVBoxLayout()
        outer.addLayout(self._timeline_list)

        self._load_more = QPushButton(self.tr("Load &more sessions"), content)
        self._load_more.clicked.connect(self._request_more_timeline)
        self._load_more.hide()
        outer.addWidget(self._load_more)
        outer.addStretch()

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _rebuild_timeline_widgets(self) -> None:
        self._voice_buttons.clear()
        self._clear_layout(self._timeline_list)
        if not self._timeline_sessions:
            empty = QLabel(self.tr("No sessions recorded for this game yet."), self)
            empty.setTextFormat(Qt.TextFormat.PlainText)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._timeline_list.addWidget(empty)
        else:
            for session in self._timeline_sessions:
                self._timeline_list.addWidget(self._build_session_card(session))
        self._sync_voice_buttons()
        self._load_more.setVisible(self._next_cursor is not None)

    def _build_session_card(self, session: TimelineSession) -> QFrame:
        card = QFrame(self)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(card)

        status_labels = {
            "completed": self.tr("Completed"),
            "interrupted": self.tr("Interrupted"),
            "open": self.tr("In progress"),
        }
        status = status_labels.get(session.status, session.status)
        session_date = _format_timestamp(session.started_at)
        header = QLabel(
            self.tr("{date} · {duration} · {status}").format(
                date=session_date,
                duration=_format_duration(self, session.duration_sec),
                status=status,
            ),
            card,
        )
        header.setTextFormat(Qt.TextFormat.PlainText)
        header.setWordWrap(True)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        if session.screenshots:
            shots_button = QPushButton(
                self.tr("View screenshots ({count})…").format(count=len(session.screenshots)),
                card,
            )
            shots_button.setAccessibleName(
                self.tr("View screenshots from {date}").format(date=session_date)
            )
            shots_button.clicked.connect(
                lambda _checked=False, paths=session.screenshots: self._open_session_shots(paths)
            )
            row = QHBoxLayout()
            row.addWidget(shots_button)
            row.addStretch()
            layout.addLayout(row)

        for voice in session.voice_notes:
            voice_row = QHBoxLayout()
            voice_date = _format_timestamp(voice.created_at)
            if not voice.available:
                label = QLabel(
                    self.tr("Voice note ({date}) · This voice note is unavailable.").format(
                        date=voice_date
                    ),
                    card,
                )
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                voice_row.addWidget(label)
            else:
                label = QLabel(
                    self.tr("Voice note ({date})").format(date=voice_date),
                    card,
                )
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                play_btn = QPushButton(self.tr("Play"), card)
                play_btn.setAccessibleName(
                    self.tr("Play voice note from {date}").format(date=voice_date)
                )
                stop_btn = QPushButton(self.tr("Stop"), card)
                stop_btn.setAccessibleName(
                    self.tr("Stop voice note from {date}").format(date=voice_date)
                )
                stop_btn.setEnabled(False)
                play_btn.clicked.connect(
                    lambda _checked=False, nid=voice.id, path=voice.path: self._play_voice(nid, path)
                )
                stop_btn.clicked.connect(self.stopVoiceNoteRequested)
                self._voice_buttons[voice.id] = (play_btn, stop_btn)
                voice_row.addWidget(label)
                voice_row.addWidget(play_btn)
                voice_row.addWidget(stop_btn)
            voice_row.addStretch()
            layout.addLayout(voice_row)

        for note in session.text_notes:
            text_label = QLabel(
                self.tr("Note ({date}): {text}").format(
                    date=_format_timestamp(note.created_at), text=note.text
                ),
                card,
            )
            text_label.setTextFormat(Qt.TextFormat.PlainText)
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            layout.addWidget(text_label)

        if not session.screenshots and not session.voice_notes and not session.text_notes:
            none_label = QLabel(self.tr("No screenshots or notes saved for this session."), card)
            none_label.setTextFormat(Qt.TextFormat.PlainText)
            none_label.setWordWrap(True)
            layout.addWidget(none_label)
        return card

    def _open_session_shots(self, paths: tuple[Path, ...]) -> None:
        title = self._game.name if self._game is not None else self.tr("Session")
        LastMomentsDialog(title, paths, self, load_image=self._load_screenshot).exec()

    def _play_voice(self, note_id: str, path: Path) -> None:
        self._pending_voice_id = note_id
        self.playVoiceNoteRequested.emit(path)

    def _move_control(self, step: int) -> None:
        target = self._control_index + step
        if 0 <= target < len(self._control_images):
            self._control_index = target
            self._show_current_control_image()

    def _show_current_control_image(self) -> None:
        total = len(self._control_images)
        self._prev_control.setEnabled(self._control_index > 0)
        self._next_control.setEnabled(self._control_index < total - 1)
        if not total:
            self._control_position.setText("")
            self._control_pixmap = QPixmap()
            self._control_preview.setPixmap(QPixmap())
            self._control_preview.setText(self.tr("No controls image pinned yet."))
            return

        item = self._control_images[self._control_index]
        self._control_position.setText(
            self.tr("Controls image {current} of {total}").format(
                current=self._control_index + 1, total=total
            )
        )
        encoded = self._load_control_image(item.path) if item.path is not None else None
        self._control_pixmap = _decode_webp(encoded)
        if self._control_pixmap.isNull():
            self._control_preview.setPixmap(QPixmap())
            self._control_preview.setText(self.tr("This controls image is unavailable."))
        else:
            self._fit_control_pixmap()

    def _fit_control_pixmap(self) -> None:
        if not self._control_pixmap.isNull():
            self._control_preview.setPixmap(
                self._control_pixmap.scaled(
                    self._control_preview.contentsRect().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _pick_control_image(self) -> None:
        if self._game is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Upload controls image"),
            "",
            self.tr("Images (*.png *.jpg *.jpeg *.webp *.bmp)"),
        )
        if path:
            self.clear_error()
            self.uploadControlImageRequested.emit(self._game.id, path)

    def _submit_control_text(self) -> None:
        if self._game is None or self._saving_control_text:
            return
        text = self._control_input.toPlainText()
        if not text.strip():
            self.show_error(self.tr("Enter a controls or strategy note before saving."))
            return
        self.clear_error()
        self.set_saving_control_text(True)
        self.saveControlTextRequested.emit(self._game.id, text)

    def _request_play(self) -> None:
        if self._game is not None:
            self.stopVoiceNoteRequested.emit()
            self.playRequested.emit(self._game.id)

    def _request_more_timeline(self) -> None:
        if self._game is not None and self._next_cursor is not None:
            self.loadMoreTimelineRequested.emit(self._game.id, self._next_cursor)

    def _go_back(self) -> None:
        self.stopVoiceNoteRequested.emit()
        self.reset_voice_state()
        self._game = None
        self.backRequested.emit()

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
