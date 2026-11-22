"""Display prior session context, notes, screenshots, and launch controls."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QDateTime,
    QEvent,
    QIODevice,
    QLocale,
    QObject,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QGuiApplication,
    QImageReader,
    QKeyEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gamehub.core.storage.memory import LastTimeData


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


def _decode_preview(encoded: bytes | None) -> QPixmap:
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


def _section_heading(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class LastTimeCard(QDialog):
    playVoiceRequested = Signal()
    stopVoiceRequested = Signal()
    autoplayToggled = Signal(bool)
    launchRequested = Signal()

    def __init__(
        self,
        data: LastTimeData,
        *,
        autoplay_enabled: bool,
        allow_launch: bool,
        already_running: bool = False,
        load_image: Callable[[Path], bytes | None],
        load_control_image: Callable[[Path], bytes | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Last time · {game}").format(game=data.game_name))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._apply_initial_size()

        self._data = data
        self._load_image = load_image
        self._load_control_image = load_control_image or (lambda _path: None)
        self._paths = data.screenshots
        self._control_images = data.control_images
        self._index = 0
        self._picture = QPixmap()
        self._control_picture = QPixmap()
        self._playing = False
        self._played_once = False
        self._voice_error: str | None = None
        self._launching = False
        self._voice_available = bool(data.voice_note and data.voice_note.available)
        self._already_running = already_running
        self._can_launch = bool(
            allow_launch and not already_running and data.installed and data.launch_target is not None
        )

        body = QWidget(self)
        body_layout = QVBoxLayout(body)

        title = QLabel(body)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setText(data.game_name)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        title.setFont(title_font)

        self._summary = QLabel(self._build_summary(data), body)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)

        body_layout.addWidget(title)
        body_layout.addWidget(self._summary)

        # Voice note section
        body_layout.addWidget(_section_heading(self.tr("Voice note"), body))
        self._voice_status = QLabel(self._default_voice_status(), body)
        self._voice_status.setTextFormat(Qt.TextFormat.PlainText)
        self._voice_status.setWordWrap(True)
        body_layout.addWidget(self._voice_status)

        self._play_voice = QPushButton(self.tr("&Play voice note"), body)
        self._play_voice.setAccessibleName(self.tr("Play voice note"))
        self._play_voice.clicked.connect(self.playVoiceRequested)
        self._stop_voice = QPushButton(self.tr("&Stop"), body)
        self._stop_voice.setAccessibleName(self.tr("Stop voice note"))
        self._stop_voice.clicked.connect(self.stopVoiceRequested)
        self._autoplay = QCheckBox(self.tr("Autoplay voice notes"), body)
        self._autoplay.setChecked(autoplay_enabled)
        self._autoplay.toggled.connect(self.autoplayToggled)

        voice_controls = QHBoxLayout()
        voice_controls.addWidget(self._play_voice)
        voice_controls.addWidget(self._stop_voice)
        voice_controls.addWidget(self._autoplay)
        voice_controls.addStretch()
        body_layout.addLayout(voice_controls)

        # Text note section
        text_heading = self.tr("Text note")
        if data.text_note is not None:
            text_heading = self.tr("Text note · {date}").format(
                date=_format_timestamp(data.text_note.created_at)
            )
        body_layout.addWidget(_section_heading(text_heading, body))
        if data.text_note is not None:
            self._text_note: QWidget = QPlainTextEdit(body)
            self._text_note.setReadOnly(True)
            self._text_note.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            self._text_note.setPlainText(data.text_note.text)
            self._text_note.setTabChangesFocus(True)
            self._text_note.setAccessibleName(self.tr("Last text note"))
            self._text_note.setMinimumHeight(64)
            self._text_note.setMaximumHeight(120)
        else:
            self._text_note = QLabel(self.tr("No text note saved yet."), body)
            self._text_note.setTextFormat(Qt.TextFormat.PlainText)
            self._text_note.setWordWrap(True)
        body_layout.addWidget(self._text_note)

        # Last moments carousel
        body_layout.addWidget(_section_heading(self.tr("Last moments"), body))
        self._preview = QLabel(body)
        self._preview.setAccessibleName(self.tr("Last moment screenshot preview"))
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setWordWrap(True)
        self._preview.setFrameShape(QFrame.Shape.StyledPanel)
        self._preview.setMinimumSize(320, 180)
        self._preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        body_layout.addWidget(self._preview)

        self._previous = QPushButton(self.tr("&Previous"), body)
        self._previous.setAccessibleName(self.tr("Previous screenshot"))
        self._previous.clicked.connect(self._go_previous)
        self._next = QPushButton(self.tr("&Next"), body)
        self._next.setAccessibleName(self.tr("Next screenshot"))
        self._next.clicked.connect(self._go_next)
        self._position = QLabel(body)
        self._position.setTextFormat(Qt.TextFormat.PlainText)
        self._position.setAlignment(Qt.AlignmentFlag.AlignCenter)

        carousel = QHBoxLayout()
        carousel.addWidget(self._previous)
        carousel.addWidget(self._position, stretch=1)
        carousel.addWidget(self._next)
        body_layout.addLayout(carousel)

        # Controls preview
        body_layout.addWidget(_section_heading(self.tr("Controls"), body))
        self._control_preview: QLabel | None = None
        if self._control_images:
            self._control_preview = QLabel(body)
            self._control_preview.setAccessibleName(self.tr("Pinned controls preview"))
            self._control_preview.setTextFormat(Qt.TextFormat.PlainText)
            self._control_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._control_preview.setWordWrap(True)
            self._control_preview.setFrameShape(QFrame.Shape.StyledPanel)
            self._control_preview.setMinimumSize(280, 140)
            self._control_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            body_layout.addWidget(self._control_preview)
        controls_text = (
            "\n".join(data.controls)
            if data.controls
            else (
                self.tr("Pinned controls images: {count}").format(count=len(self._control_images))
                if self._control_images
                else self.tr("No controls pinned yet.")
            )
        )
        self._controls = QLabel(controls_text, body)
        self._controls.setTextFormat(Qt.TextFormat.PlainText)
        self._controls.setWordWrap(True)
        body_layout.addWidget(self._controls)

        if allow_launch:
            hint = QLabel(
                self.tr(
                    "Review your notes before launching. For exclusive fullscreen games, "
                    "use Play here or press Alt+Tab and Ctrl+Alt+L."
                ),
                body,
            )
            hint.setTextFormat(Qt.TextFormat.PlainText)
            hint.setWordWrap(True)
            body_layout.addWidget(hint)

        body_layout.addStretch()

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        scroll.installEventFilter(self)
        self._previous.installEventFilter(self)
        self._next.installEventFilter(self)
        self._scroll = scroll

        self._error = QLabel(self)
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        actions = QDialogButtonBox(self)
        self._launch: QPushButton | None = None
        if allow_launch:
            self._launch = actions.addButton(
                self.tr("&Launch"), QDialogButtonBox.ButtonRole.AcceptRole
            )
            self._launch.setAutoDefault(False)
            self._launch.clicked.connect(self.launchRequested)
        self._close = actions.addButton(self.tr("&Close"), QDialogButtonBox.ButtonRole.RejectRole)
        self._close.setAutoDefault(False)
        actions.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self._error)
        layout.addWidget(actions)

        if allow_launch and self._already_running:
            self.show_error(self.tr("This game is already running."))
        elif allow_launch and not self._can_launch:
            self.show_error(
                self.tr(
                    "No launch target is available for this game. Check that it is installed "
                    "or add its executable."
                )
            )
        self._update_voice_controls()
        self._update_launch_button()
        self._show_current_shot()
        self._show_control_preview()
        if self._launch is not None and self._launch.isEnabled():
            self._launch.setFocus()
        elif self._play_voice.isEnabled():
            self._play_voice.setFocus()
        else:
            self._close.setFocus()

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        if playing:
            self._played_once = True
            self._voice_error = None
            self._voice_status.setText(self.tr("Playing voice note…"))
        elif self._voice_error is not None:
            self._voice_status.setText(self._voice_error)
        else:
            self._voice_status.setText(self._default_voice_status())
        self._update_voice_controls()

    def show_voice_error(self, message: str) -> None:
        self._playing = False
        self._voice_error = message
        self._voice_status.setText(message)
        self._update_voice_controls()

    def clear_voice_error(self) -> None:
        self._voice_error = None
        if not self._playing:
            self._voice_status.setText(self._default_voice_status())

    def set_launching(self, launching: bool) -> None:
        self._launching = launching
        self._update_launch_button()

    def is_launching(self) -> bool:
        return self._launching

    def set_autoplay_checked(self, enabled: bool) -> None:
        previous = self._autoplay.blockSignals(True)
        try:
            self._autoplay.setChecked(enabled)
        finally:
            self._autoplay.blockSignals(previous)

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def clear_error(self) -> None:
        self.show_error("")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched in {self._scroll, self._previous, self._next}
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and self._handle_carousel_key(event)
        ):
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._handle_carousel_key(event):
            return
        super().keyPressEvent(event)

    def _handle_carousel_key(self, event: QKeyEvent) -> bool:
        if isinstance(self.focusWidget(), QPlainTextEdit):
            return False
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        if event.key() == Qt.Key.Key_Left:
            self._move(1 if rtl else -1)
            event.accept()
            return True
        if event.key() == Qt.Key.Key_Right:
            self._move(-1 if rtl else 1)
            event.accept()
            return True
        return False

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_picture()

    def _apply_initial_size(self) -> None:
        width, height = 540, 620
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if available.width() > 0 and available.height() > 0:
                width = min(width, max(320, available.width() - 40))
                height = min(height, max(320, available.height() - 40))
        self.resize(width, height)

    def _build_summary(self, data: LastTimeData) -> str:
        total = _format_duration(self, data.total_playtime)
        if data.last_session is None:
            return self.tr("No previous ended sessions yet · Total playtime {total}").format(total=total)
        played_at = _format_timestamp(data.last_session.started_at)
        duration = _format_duration(self, data.last_session.duration_sec)
        if data.last_session.status == "interrupted":
            return self.tr(
                "Last played {date} ({duration}, interrupted) · Total playtime {total}"
            ).format(date=played_at, duration=duration, total=total)
        return self.tr("Last played {date} ({duration}) · Total playtime {total}").format(
            date=played_at, duration=duration, total=total
        )

    def _default_voice_status(self) -> str:
        note = self._data.voice_note
        if note is None:
            return self.tr("No voice note saved yet.")
        saved = _format_timestamp(note.created_at)
        if not note.available:
            return self.tr("Saved {date} · This voice note is unavailable.").format(date=saved)
        return self.tr("Saved {date}").format(date=saved)

    def _update_voice_controls(self) -> None:
        if self._played_once:
            label = self.tr("&Replay voice note")
            accessible = self.tr("Replay voice note")
        else:
            label = self.tr("&Play voice note")
            accessible = self.tr("Play voice note")
        self._play_voice.setText(label)
        self._play_voice.setAccessibleName(accessible)
        self._play_voice.setEnabled(self._voice_available)
        self._stop_voice.setEnabled(self._voice_available and self._playing)

    def _update_launch_button(self) -> None:
        if self._launch is None:
            return
        self._launch.setText(self.tr("Launching…") if self._launching else self.tr("&Launch"))
        self._launch.setEnabled(self._can_launch and not self._launching)

    def _go_previous(self) -> None:
        self._move(-1)

    def _go_next(self) -> None:
        self._move(1)

    def _move(self, step: int) -> None:
        target = self._index + step
        if 0 <= target < len(self._paths):
            self._index = target
            self._show_current_shot()

    def _show_current_shot(self) -> None:
        total = len(self._paths)
        self._previous.setEnabled(self._index > 0)
        self._next.setEnabled(self._index < total - 1)
        if not total:
            self._position.setText("")
            self._preview.setPixmap(QPixmap())
            self._preview.setText(self.tr("No screenshots saved from the last session."))
            return

        self._position.setText(
            self.tr("Screenshot {current} of {total}").format(current=self._index + 1, total=total)
        )
        self._picture = _decode_preview(self._load_image(self._paths[self._index]))
        if self._picture.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText(self.tr("This screenshot is unavailable."))
        else:
            self._fit_picture()

    def _fit_picture(self) -> None:
        if not self._picture.isNull():
            self._preview.setPixmap(
                self._picture.scaled(
                    self._preview.contentsRect().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        if self._control_preview is not None and not self._control_picture.isNull():
            self._control_preview.setPixmap(
                self._control_picture.scaled(
                    self._control_preview.contentsRect().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _show_control_preview(self) -> None:
        if self._control_preview is None or not self._control_images:
            return
        self._control_picture = _decode_preview(self._load_control_image(self._control_images[-1]))
        if self._control_picture.isNull():
            self._control_preview.setPixmap(QPixmap())
            self._control_preview.setText(self.tr("This controls image is unavailable."))
        else:
            self._fit_picture()
