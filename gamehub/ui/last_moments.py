"""Browse retained screenshots for the selected game."""

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class LastMomentsDialog(QDialog):
    def __init__(
        self,
        title: str,
        images: Sequence[Path],
        parent: QWidget | None = None,
        *,
        load_image: Callable[[Path], bytes | None],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Last moments · {game}").format(game=title))
        self._paths = tuple(images)
        self._load_image = load_image
        self._index = 0
        self._picture = QPixmap()

        self._preview = QLabel(self)
        self._preview.setAccessibleName(self.tr("Screenshot preview"))
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setWordWrap(True)
        self._preview.setMinimumSize(280, 160)
        self._preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self._previous = QPushButton(self.tr("&Previous"), self)
        self._previous.clicked.connect(self._go_previous)
        self._next = QPushButton(self.tr("&Next"), self)
        self._next.clicked.connect(self._go_next)
        self._position = QLabel(self)
        self._position.setAlignment(Qt.AlignmentFlag.AlignCenter)

        navigation = QHBoxLayout()
        navigation.addWidget(self._previous)
        navigation.addWidget(self._position, stretch=1)
        navigation.addWidget(self._next)

        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        actions.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self._preview, stretch=1)
        layout.addLayout(navigation)
        layout.addWidget(actions)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self._step_left)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self._step_right)
        self.resize(720, 480)
        self._show_current()
        if self._next.isEnabled():
            self._next.setFocus()
        else:
            actions.button(QDialogButtonBox.StandardButton.Close).setFocus()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_picture()

    def _go_previous(self) -> None:
        self._move(-1)

    def _go_next(self) -> None:
        self._move(1)

    def _step_left(self) -> None:
        self._move(1 if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else -1)

    def _step_right(self) -> None:
        self._move(-1 if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else 1)

    def _move(self, step: int) -> None:
        next_index = self._index + step
        if 0 <= next_index < len(self._paths):
            self._index = next_index
            self._show_current()

    def _show_current(self) -> None:
        total = len(self._paths)
        self._previous.setEnabled(self._index > 0)
        self._next.setEnabled(self._index < total - 1)
        if not total:
            self._preview.setText(self.tr("No screenshots have been saved for this game."))
            return

        self._position.setText(
            self.tr("Screenshot {current} of {total}").format(current=self._index + 1, total=total)
        )
        self._picture = _decode_preview(self._load_image(self._paths[self._index]))
        if self._picture.isNull():
            self._preview.setText(self.tr("This screenshot is unavailable."))
        else:
            self._fit_picture()

    def _fit_picture(self) -> None:
        if not self._picture.isNull():
            self._preview.setPixmap(self._picture.scaled(
                self._preview.contentsRect().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))


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
