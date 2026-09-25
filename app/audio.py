import io

from mutagen import File as MutagenFile


def duration_seconds(data: bytes) -> float | None:
    """Best-effort audio duration. WhatsApp voice notes are OGG/Opus."""
    try:
        audio = MutagenFile(io.BytesIO(data))
    except Exception:
        return None
    if audio is None or audio.info is None:
        return None
    return float(audio.info.length)
