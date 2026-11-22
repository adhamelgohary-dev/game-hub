from io import BytesIO
from unittest.mock import Mock

import cffi
import pytest
import sounddevice
import soundfile

from gamehub.core.audio import recorder as audio
from gamehub.core.audio.recorder import AudioRecorder, RecordingError

SAMPLE_RATE = 8_000
SYNTHETIC_PCM = b"\x00\x10\x00\xf0"


@pytest.fixture
def input_stream(monkeypatch: pytest.MonkeyPatch):
    device = Mock(return_value={"index": 7, "default_samplerate": SAMPLE_RATE})
    stream = Mock()
    factory = Mock(return_value=stream)
    monkeypatch.setattr(sounddevice, "query_devices", device)
    monkeypatch.setattr(sounddevice, "RawInputStream", factory)
    return device, factory, stream


def _deliver(factory: Mock, payload: bytes) -> None:
    ffi = cffi.FFI()
    storage = ffi.new("char[]", payload)
    factory.call_args.kwargs["callback"](ffi.buffer(storage, len(payload)), len(payload) // 2, None, None)


def _read(clip: bytes):
    assert clip.startswith(b"OggS")
    with soundfile.SoundFile(BytesIO(clip)) as file:
        assert (file.format, file.subtype, file.samplerate, file.channels) == ("OGG", "VORBIS", SAMPLE_RATE, 1)
        return file.read(dtype="float32")


def test_recorder_opens_default_input_only_and_encodes_early_stop(input_stream) -> None:
    device, factory, stream = input_stream
    recorder = AudioRecorder()

    recorder.start()
    _deliver(factory, SYNTHETIC_PCM * 800)
    clip = recorder.stop()

    device.assert_called_once_with(kind="input")
    options = factory.call_args.kwargs
    assert (options["device"], options["channels"], options["samplerate"], options["dtype"]) == (7, 1, SAMPLE_RATE, "int16")
    assert set(options) == {"device", "channels", "samplerate", "dtype", "callback"}
    stream.start.assert_called_once()
    stream.close.assert_called_once_with(ignore_errors=False)
    values = _read(clip)
    assert len(values) == 1_600
    assert abs(values).max() > 0.01
    assert not recorder.reached_limit


def test_callback_stops_at_sample_limit_and_drops_excess_pcm(input_stream) -> None:
    _, factory, _ = input_stream
    recorder = AudioRecorder(limit_sec=1)
    recorder.start()

    with pytest.raises(sounddevice.CallbackStop):
        _deliver(factory, SYNTHETIC_PCM * 4_100)

    assert recorder.reached_limit
    assert len(_read(recorder.stop())) == SAMPLE_RATE


def test_wall_clock_limit_applies_when_device_callback_falls_behind(
    input_stream, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory, _ = input_stream
    clock = Mock(return_value=12.0)
    monkeypatch.setattr(audio, "monotonic", clock)
    recorder = AudioRecorder(limit_sec=1)
    recorder.start()
    _deliver(factory, SYNTHETIC_PCM * 100)
    clock.return_value = 13.0

    assert recorder.reached_limit
    with pytest.raises(sounddevice.CallbackStop):
        _deliver(factory, SYNTHETIC_PCM * 100)

    assert len(_read(recorder.stop())) == 200


def test_microphone_denial_is_safe_and_retryable(input_stream) -> None:
    _, factory, stream = input_stream
    recorder = AudioRecorder()
    stream.start.side_effect = sounddevice.PortAudioError("private device information")

    with pytest.raises(RecordingError, match="Microphone unavailable") as failure:
        recorder.start()

    assert "private device information" not in str(failure.value)
    assert failure.value.__cause__ is None
    stream.close.assert_called_once()

    stream.start.side_effect = None
    recorder.start()
    _deliver(factory, SYNTHETIC_PCM * 100)
    assert len(_read(recorder.stop())) == 200


def test_no_default_microphone_does_not_open_a_stream(input_stream) -> None:
    device, factory, _ = input_stream
    device.side_effect = sounddevice.PortAudioError("private device information")

    with pytest.raises(RecordingError, match="Microphone unavailable"):
        AudioRecorder().start()

    factory.assert_not_called()


def test_empty_or_failed_recording_releases_stream(input_stream) -> None:
    _, factory, stream = input_stream
    recorder = AudioRecorder()
    recorder.start()
    with pytest.raises(RecordingError, match="No microphone audio"):
        recorder.stop()

    recorder.start()
    _deliver(factory, SYNTHETIC_PCM * 100)
    stream.close.side_effect = sounddevice.PortAudioError("private device information")
    with pytest.raises(RecordingError, match="could not finish the voice note"):
        recorder.stop()
    with pytest.raises(RecordingError, match="No voice note is recording"):
        recorder.stop()


def test_abort_is_idempotent_and_does_not_carry_audio_to_the_next_note(input_stream) -> None:
    _, factory, stream = input_stream
    recorder = AudioRecorder()
    recorder.start()
    _deliver(factory, SYNTHETIC_PCM * 100)
    with pytest.raises(RecordingError, match="already recording"):
        recorder.start()

    recorder.abort()
    recorder.abort()
    stream.close.assert_called_once()

    recorder.start()
    _deliver(factory, SYNTHETIC_PCM * 200)
    assert len(_read(recorder.stop())) == 400
