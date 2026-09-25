import time
from dataclasses import dataclass

from app.ai import AI, Timed
from app.audio import duration_seconds

MIME_EXT = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/amr": "amr"}


@dataclass
class Result:
    transcript: Timed
    summary: Timed | None
    audio_seconds: float | None
    total_seconds: float


async def process(
    ai: AI, audio: bytes, mime_type: str, min_seconds: float, started_at: float | None = None
) -> Result:
    """started_at lets the caller include media download time in the total."""
    t0 = started_at if started_at is not None else time.perf_counter()
    base_mime = mime_type.split(";")[0].strip()
    filename = f"voice.{MIME_EXT.get(base_mime, 'ogg')}"
    dur = duration_seconds(audio)

    transcript = await ai.transcribe(audio, filename, base_mime)
    summary = None
    # If duration is unknown, fall back to a rough length heuristic (~2.5 words/sec).
    long_enough = dur > min_seconds if dur is not None else len(transcript.text.split()) > min_seconds * 2.5
    if transcript.text and long_enough:
        summary = await ai.summarise(transcript.text)
    return Result(transcript, summary, dur, time.perf_counter() - t0)


def format_reply(r: Result) -> str:
    lines = [r.transcript.text or "(no speech detected)"]
    if r.summary and r.summary.text:
        lines += ["", f"*Summary:* {r.summary.text}"]
    meta = [f"STT {r.transcript.model} {r.transcript.seconds:.2f}s"]
    if r.summary:
        meta.append(f"Sum {r.summary.model} {r.summary.seconds:.2f}s")
    meta.append(f"total {r.total_seconds:.2f}s")
    if r.audio_seconds is not None:
        meta.append(f"audio {r.audio_seconds:.0f}s")
    lines += ["", "_" + " | ".join(meta) + "_"]
    return "\n".join(lines)
