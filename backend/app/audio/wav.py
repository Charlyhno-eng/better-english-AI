import io
import wave

from app.audio.contracts import AudioData
from app.core.errors import InvalidAudioError

WAV_MEDIA_TYPES = {"audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"}


def read_pcm(audio: AudioData, max_duration_seconds: float) -> bytes:
    """Read bounded mono 16 kHz PCM16 WAV without writing user audio to disk."""
    if audio.media_type.split(";", 1)[0].strip().lower() not in WAV_MEDIA_TYPES:
        raise InvalidAudioError("Audio must be a PCM16 mono 16 kHz WAV recording.")
    try:
        with wave.open(io.BytesIO(audio.content), "rb") as source:
            if (
                source.getframerate() != 16_000
                or source.getnchannels() != 1
                or source.getsampwidth() != 2
                or source.getcomptype() != "NONE"
            ):
                raise InvalidAudioError("Audio must be a PCM16 mono 16 kHz WAV recording.")
            frames = source.getnframes()
            if frames == 0:
                raise InvalidAudioError("The recording is empty.")
            if frames / 16_000 > max_duration_seconds:
                raise InvalidAudioError("The recording exceeds the duration limit.")
            pcm = source.readframes(frames)
            if len(pcm) != frames * 2:
                raise InvalidAudioError("The WAV recording is truncated.")
            return pcm
    except (wave.Error, EOFError) as exc:
        raise InvalidAudioError("The WAV recording is invalid.") from exc
