import logging
import time
from dataclasses import dataclass

from app.ai import AI, Timed
from app.audio import duration_seconds

log = logging.getLogger("transcriber")

MIME_EXT = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/amr": "amr"}


@dataclass
class Result:
    transcript: Timed
    summary: Timed | None  # None when the audio is short enough to skip summarising
    summary_failed: bool
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
    summary, failed = None, False
    # If duration is unknown, fall back to a rough length heuristic (~2.5 words/sec).
    long_enough = dur > min_seconds if dur is not None else len(transcript.text.split()) > min_seconds * 2.5
    if transcript.text and long_enough:
        try:
            summary = await ai.summarise(transcript.text)
            failed = not summary.text
        except Exception:
            # Never lose the transcript because the summary step failed.
            log.exception("summary failed")
            failed = True
    return Result(transcript, summary, failed, dur, time.perf_counter() - t0)


def format_reply(r: Result) -> str:
    lines = ["📝 *Transcript*", r.transcript.text or "(no speech detected)"]
    if r.summary and r.summary.text:
        lines += ["", "💡 *Summary*", r.summary.text]
    elif r.summary_failed:
        lines += ["", "💡 *Summary*", "(unavailable)"]
    meta = [f"STT {r.transcript.model} {r.transcript.seconds:.2f}s"]
    if r.summary:
        meta.append(f"Summary {r.summary.model} {r.summary.seconds:.2f}s")
    meta.append(f"Total {r.total_seconds:.2f}s")
    if r.audio_seconds is not None:
        meta.append(f"Audio {r.audio_seconds:.0f}s")
    lines += ["", "_⏱ " + " · ".join(meta) + "_"]
    return "\n".join(lines)
