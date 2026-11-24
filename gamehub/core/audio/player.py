"""Play an application-generated local voice note through Qt Multimedia (lazily loaded)."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QObject, QUrl, Signal

MAX_CLIP_BYTES = 8 * 1024 * 1024


class VoicePlayer(QObject):
    playingChanged = Signal(bool)
    failed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio = None
        self._player = None
        self._playing_state = None
        self._no_error = None
        self._buffer: QBuffer | None = None

    def _ensure_backend(self) -> bool:
        if self._player is not None:
            return True
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._playing_state = QMediaPlayer.PlaybackState.PlayingState
        self._no_error = QMediaPlayer.Error.NoError
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(self._changed)
        self._player.errorOccurred.connect(self._error)
        return True

    def is_available(self) -> bool:
        self._ensure_backend()
        return bool(self._player is not None and self._player.isAvailable())

    def play(self, clip: bytes) -> bool:
        self.stop()
        if not 27 <= len(clip) <= MAX_CLIP_BYTES or not clip.startswith(b"OggS\x00"):
            self.failed.emit()
            return False
        self._ensure_backend()
        if self._player is None or not self._player.isAvailable():
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
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        self._buffer.close()
        self._buffer.deleteLater()
        self._buffer = None

    def _changed(self, state) -> None:
        self.playingChanged.emit(state == self._playing_state)

    def _error(self, code, _message: str) -> None:
        if code != self._no_error:
            self.failed.emit()
