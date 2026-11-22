from io import BytesIO

import numpy
import pytest
import soundfile
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from gamehub.core.audio.player import MAX_CLIP_BYTES, VoicePlayer


def _voice_clip() -> bytes:
    samples = 0.05 * numpy.sin(2 * numpy.pi * 440 * numpy.arange(4000) / 16000)
    with BytesIO() as output:
        soundfile.write(output, samples, 16000, format="OGG", subtype="VORBIS")
        return output.getvalue()


@pytest.fixture(scope="module")
def core_app(monkeypatch_module=None):
    return QCoreApplication.instance() or QCoreApplication(["voice player test"])


def test_voice_player_rejects_invalid_or_oversized_clips(core_app) -> None:
    player = VoicePlayer()
    failures = []
    player.failed.connect(lambda: failures.append(True))
    try:
        assert player.play(b"") is False
        assert player.play(b"RIFF1234WEBP" * 4) is False
        assert player.play(b"OggS\x00" + b"0" * 10) is False
        assert player.play(b"OggS\x00" + b"0" * MAX_CLIP_BYTES) is False
        assert len(failures) == 4
    finally:
        player.stop()


def test_voice_player_loads_bounded_ogg_buffer(core_app) -> None:
    player = VoicePlayer()
    states = []
    errors = []
    player.playingChanged.connect(states.append)
    player.failed.connect(lambda: errors.append(True))
    try:
        assert player.is_available() is True
        assert player.play(_voice_clip()) is True
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        assert errors == []
        assert True in states
    finally:
        player.stop()
