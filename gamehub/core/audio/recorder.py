"""Record one bounded, local voice note from the default audio input."""

import logging
from io import BytesIO
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sounddevice import RawInputStream

_MAX_SECONDS = 60
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000
_BYTES_PER_SAMPLE = 2
_MICROPHONE_UNAVAILABLE = "Microphone unavailable. Check Windows microphone access or save a text note."
LOGGER = logging.getLogger(__name__)


class RecordingError(RuntimeError):
    """A recoverable recording failure with a message safe to show to the user."""


class AudioRecorder:
    """Own one microphone stream. Call start, stop, and abort on the same worker."""

    def __init__(self, limit_sec: int = _MAX_SECONDS) -> None:
        if type(limit_sec) is not int:
            raise TypeError("The recording limit must be a whole number of seconds.")
        if not 1 <= limit_sec <= _MAX_SECONDS:
            raise ValueError("The recording limit must be between 1 and 60 seconds.")
        self._limit_sec = limit_sec
        self._stream: RawInputStream | None = None
        self._pcm = bytearray()
        self._sample_rate = 0
        self._samples = 0
        self._deadline = 0.0

    @property
    def reached_limit(self) -> bool:
        return self._stream is not None and (
            self._samples == len(self._pcm) // _BYTES_PER_SAMPLE or monotonic() >= self._deadline
        )

    def start(self) -> None:
        if self._stream is not None:
            raise RecordingError("A voice note is already recording.")

        try:
            import sounddevice
        except Exception:  # noqa: BLE001 - PortAudio can fail while the module is loading.
            raise RecordingError(_MICROPHONE_UNAVAILABLE) from None

        def receive(indata, frames, _time, _status) -> None:
            if not self._receive(indata, frames):
                raise sounddevice.CallbackStop

        try:
            device = sounddevice.query_devices(kind="input")
            sample_rate = int(device["default_samplerate"])
            if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
                raise ValueError("Unsupported microphone sample rate")
            self._sample_rate = sample_rate
            self._pcm = bytearray(sample_rate * self._limit_sec * _BYTES_PER_SAMPLE)
            self._stream = sounddevice.RawInputStream(
                device=device["index"], samplerate=sample_rate, channels=1, dtype="int16", callback=receive,
            )
            self._deadline = monotonic() + self._limit_sec
            self._stream.start()
        except (KeyError, OSError, OverflowError, RuntimeError, TypeError, ValueError, sounddevice.PortAudioError):
            self.abort()
            raise RecordingError(_MICROPHONE_UNAVAILABLE) from None

    def stop(self) -> bytes:
        stream = self._stream
        if stream is None:
            raise RecordingError("No voice note is recording.")
        import sounddevice

        try:
            # Closing an input stream aborts pending buffers and joins its callback.
            stream.close(ignore_errors=False)
            if not self._samples:
                raise RecordingError("No microphone audio was captured. Try recording again or save a text note.")
            return self._encode()
        except RecordingError:
            raise
        except (ImportError, OSError, RuntimeError, ValueError, sounddevice.PortAudioError):
            raise RecordingError("GameRewind could not finish the voice note. You can try again or save a text note.") from None
        finally:
            self._reset()

    def abort(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
        except Exception:  # noqa: BLE001 - discard audio and reset even if the driver errors.
            LOGGER.warning("audio_recorder_cleanup_failed")
        finally:
            self._reset()

    def _receive(self, indata, frames: int) -> bool:
        if monotonic() >= self._deadline:
            return False
        buffer = memoryview(indata)
        capacity = len(self._pcm) // _BYTES_PER_SAMPLE
        samples = min(frames, buffer.nbytes // _BYTES_PER_SAMPLE, capacity - self._samples)
        if samples > 0:
            offset = self._samples * _BYTES_PER_SAMPLE
            num_bytes = samples * _BYTES_PER_SAMPLE
            self._pcm[offset:offset + num_bytes] = buffer[:num_bytes]
            self._samples += samples
        return self._samples < capacity

    def _encode(self) -> bytes:
        import numpy
        import soundfile

        values = numpy.frombuffer(self._pcm, dtype=numpy.int16, count=self._samples)
        with BytesIO() as output:
            soundfile.write(output, values, self._sample_rate, format="OGG", subtype="VORBIS")
            return output.getvalue()

    def _reset(self) -> None:
        self._stream = None
        self._pcm = bytearray()
        self._sample_rate = 0
        self._samples = 0
        self._deadline = 0.0
