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
from gamehub.ui.covers import load_cover_pixmap


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
    label.setObjectName("sectionHeading")
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _card_frame(parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("panelCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    return frame, layout


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
        default_exit_after_play: bool = False,
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
        body.setObjectName("canvas")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 10, 8)
        body_layout.setSpacing(12)

        # Header card with real game cover art
        header_card = QFrame(body)
        header_card.setObjectName("heroCard")
        header_row = QHBoxLayout(header_card)
        header_row.setContentsMargins(14, 12, 14, 12)
        header_row.setSpacing(14)

        cover = QLabel(header_card)
        cover.setFixedSize(112, 64)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setPixmap(load_cover_pixmap(data.cover_path, data.game_name, 112, 64, radius=8))
        header_row.addWidget(cover)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel(header_card)
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setText(data.game_name)

        self._summary = QLabel(self._build_summary(data), header_card)
        self._summary.setObjectName("mutedText")
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(self._summary)
        header_row.addLayout(title_col, stretch=1)
        body_layout.addWidget(header_card)

        # Voice note section
        voice_card, voice_layout = _card_frame(body)
        voice_layout.addWidget(_section_heading(self.tr("Voice note"), voice_card))
        self._voice_status = QLabel(self._default_voice_status(), voice_card)
        self._voice_status.setObjectName("mutedText")
        self._voice_status.setTextFormat(Qt.TextFormat.PlainText)
        self._voice_status.setWordWrap(True)
        voice_layout.addWidget(self._voice_status)

        self._play_voice = QPushButton(self.tr("Play voice note"), voice_card)
        self._play_voice.setAccessibleName(self.tr("Play voice note"))
        self._play_voice.clicked.connect(self.playVoiceRequested)
        self._stop_voice = QPushButton(self.tr("Stop"), voice_card)
        self._stop_voice.setAccessibleName(self.tr("Stop voice note"))
        self._stop_voice.clicked.connect(self.stopVoiceRequested)
        self._autoplay = QCheckBox(self.tr("Autoplay voice notes"), voice_card)
        self._autoplay.setChecked(autoplay_enabled)
        self._autoplay.toggled.connect(self.autoplayToggled)

        voice_controls = QHBoxLayout()
        voice_controls.setSpacing(8)
        voice_controls.addWidget(self._play_voice)
        voice_controls.addWidget(self._stop_voice)
        voice_controls.addWidget(self._autoplay)
        voice_controls.addStretch()
        voice_layout.addLayout(voice_controls)
        body_layout.addWidget(voice_card)

        # Text note section
        text_card, text_layout = _card_frame(body)
        text_heading = self.tr("Text note")
        if data.text_note is not None:
            text_heading = self.tr("Text note · {date}").format(
                date=_format_timestamp(data.text_note.created_at)
            )
        text_layout.addWidget(_section_heading(text_heading, text_card))
        if data.text_note is not None:
            self._text_note: QWidget = QPlainTextEdit(text_card)
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
            self._text_note = QLabel(self.tr("No text note saved yet."), text_card)
            self._text_note.setObjectName("mutedText")
            self._text_note.setTextFormat(Qt.TextFormat.PlainText)
            self._text_note.setWordWrap(True)
        text_layout.addWidget(self._text_note)
        body_layout.addWidget(text_card)

        # Last moments carousel (arrows flanking preview + pagination dots, zero technical labels)
        moments_card, moments_layout = _card_frame(body)
        moments_header = QHBoxLayout()
        moments_header.addWidget(_section_heading(self.tr("Last moments"), moments_card))
        moments_header.addStretch()
        self._position = QLabel(moments_card)
        self._position.setObjectName("mutedText")
        self._position.setTextFormat(Qt.TextFormat.PlainText)
        moments_header.addWidget(self._position)
        moments_layout.addLayout(moments_header)

        self._previous = QPushButton("‹", moments_card)
        self._previous.setAccessibleName(self.tr("Previous screenshot"))
        self._previous.setFixedWidth(36)
        self._previous.clicked.connect(self._go_previous)

        self._preview = QLabel(moments_card)
        self._preview.setAccessibleName(self.tr("Last moment screenshot preview"))
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setWordWrap(True)
        self._preview.setFrameShape(QFrame.Shape.StyledPanel)
        self._preview.setMinimumSize(280, 185)
        self._preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self._next = QPushButton("›", moments_card)
        self._next.setAccessibleName(self.tr("Next screenshot"))
        self._next.setFixedWidth(36)
        self._next.clicked.connect(self._go_next)

        carousel_stage = QHBoxLayout()
        carousel_stage.setSpacing(8)
        carousel_stage.addWidget(self._previous)
        carousel_stage.addWidget(self._preview, stretch=1)
        carousel_stage.addWidget(self._next)
        moments_layout.addLayout(carousel_stage)

        self._dots_row = QHBoxLayout()
        self._dots_row.setSpacing(6)
        self._dots_row.addStretch()
        self._dots: list[QLabel] = []
        for _ in self._paths:
            dot = QLabel("●", moments_card)
            dot.setObjectName("carouselDot")
            self._dots.append(dot)
            self._dots_row.addWidget(dot)
        self._dots_row.addStretch()
        moments_layout.addLayout(self._dots_row)
        body_layout.addWidget(moments_card)

        # Controls preview
        controls_card, controls_layout = _card_frame(body)
        controls_layout.addWidget(_section_heading(self.tr("Controls"), controls_card))
        self._control_preview: QLabel | None = None
        if self._control_images:
            self._control_preview = QLabel(controls_card)
            self._control_preview.setAccessibleName(self.tr("Pinned controls preview"))
            self._control_preview.setTextFormat(Qt.TextFormat.PlainText)
            self._control_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._control_preview.setWordWrap(True)
            self._control_preview.setFrameShape(QFrame.Shape.StyledPanel)
            self._control_preview.setMinimumSize(280, 140)
            self._control_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            controls_layout.addWidget(self._control_preview)
        controls_text = (
            "\n".join(data.controls)
            if data.controls
            else (
                self.tr("Pinned controls images: {count}").format(count=len(self._control_images))
                if self._control_images
                else self.tr("No controls pinned yet.")
            )
        )
        self._controls = QLabel(controls_text, controls_card)
        self._controls.setTextFormat(Qt.TextFormat.PlainText)
        self._controls.setWordWrap(True)
        controls_layout.addWidget(self._controls)
        body_layout.addWidget(controls_card)

        self._exit_after_play: QCheckBox | None = None
        if allow_launch:
            self._exit_after_play = QCheckBox(
                self.tr("Exit GameRewind after this game closes"), body
            )
            self._exit_after_play.setChecked(default_exit_after_play)
            body_layout.addWidget(self._exit_after_play)
            hint = QLabel(
                self.tr(
                    "Review your notes before launching. For exclusive fullscreen games, "
                    "use Play here or press Alt+Tab and Ctrl+Alt+L."
                ),
                body,
            )
            hint.setObjectName("mutedText")
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
        self._error.setObjectName("errorBanner")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        actions = QDialogButtonBox(self)
        self._launch: QPushButton | None = None
        if allow_launch:
            self._launch = actions.addButton(
                self.tr("Launch"), QDialogButtonBox.ButtonRole.AcceptRole
            )
            self._launch.setObjectName("primaryButton")
            self._launch.setAutoDefault(False)
            self._launch.clicked.connect(self.launchRequested)
        self._close = actions.addButton(self.tr("Close"), QDialogButtonBox.ButtonRole.RejectRole)
        self._close.setAutoDefault(False)
        actions.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)
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

    def exit_after_play(self) -> bool:
        return bool(self._exit_after_play is not None and self._exit_after_play.isChecked())

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
        width, height = 620, 700
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
            label = self.tr("Replay voice note")
            accessible = self.tr("Replay voice note")
        else:
            label = self.tr("Play voice note")
            accessible = self.tr("Play voice note")
        self._play_voice.setText(label)
        self._play_voice.setAccessibleName(accessible)
        self._play_voice.setEnabled(self._voice_available)
        self._stop_voice.setEnabled(self._voice_available and self._playing)

    def _update_launch_button(self) -> None:
        if self._launch is None:
            return
        self._launch.setText(self.tr("Launching…") if self._launching else self.tr("Launch"))
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
        for idx, dot in enumerate(self._dots):
            active = idx == self._index
            dot.setText("●" if active else "○")
            dot.setProperty("active", active)
            dot.style().unpolish(dot)
            dot.style().polish(dot)
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
