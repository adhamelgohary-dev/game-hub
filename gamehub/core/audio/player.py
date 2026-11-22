"""Play an application-generated local voice note through Qt Multimedia."""

from PySide6.QtCore import QBuffer, QIODevice, QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

MAX_CLIP_BYTES = 8 * 1024 * 1024


class VoicePlayer(QObject):
    playingChanged = Signal(bool)
    failed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(self._changed)
        self._player.errorOccurred.connect(self._error)
        self._buffer: QBuffer | None = None

    def is_available(self) -> bool:
        return self._player.isAvailable()

    def play(self, clip: bytes) -> bool:
        self.stop()
        if (
            not self._player.isAvailable()
            or not 27 <= len(clip) <= MAX_CLIP_BYTES
            or not clip.startswith(b"OggS\x00")
        ):
            self.failed.emit()
            return False
        buffer = QBuffer(self)
        buffer.setData(clip)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            buffer.deleteLater()
            self.failed.emit()
            return False
        self._buffer = buffer
        self._player.setSourceDevice(buffer, QUrl.fromLocalFile("GameHub-voice.ogg"))
        self._player.play()
        return True

    def stop(self) -> None:
        if self._buffer is None:
            return
        self._player.stop()
        self._player.setSource(QUrl())
        self._buffer.close()
        self._buffer.deleteLater()
        self._buffer = None

    def _changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.playingChanged.emit(state == QMediaPlayer.PlaybackState.PlayingState)

    def _error(self, code, _message: str) -> None:
        if code != QMediaPlayer.Error.NoError:
            self.failed.emit()
