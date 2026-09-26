import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.ai import AI, Analysis, Timed, estimate_tokens
from app.audio import duration_seconds
from app.config import Settings
from app.documents import DocumentError, extract_text, render_pages
from app.store import Store

log = logging.getLogger("transcriber")

# Formats OpenAI transcription accepts: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm.
MIME_EXT = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/mpeg": "mpeg",
}
# A reply longer than this gets an interim "reading..." message first.
DOC_ACK_TOKENS = 8000


@dataclass
class Ctx:
    settings: Settings
    ai: AI
    store: Store | None
    sender: str
    wamid: str
    send: Callable[[str], Awaitable[None]]
    started: float
    lang: str | None  # translate into this language (None = off)
    vocab: list[str]


def fmt_cost(c: float) -> str:
    if c <= 0:
        return "$0"
    return f"${c:.4f}" if c >= 0.0001 else "<$0.0001"


def fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def fmt_duration(s: float) -> str:
    s = round(s)
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def meta_line(parts: list[str]) -> str:
    return "_⏱ " + " · ".join(parts) + "_"


def long_enough(duration: float | None, text: str, threshold: float) -> bool:
    if duration is not None:
        return duration > threshold
    # Unknown duration: estimate from speech rate (~2.5 words/sec).
    return len(text.split()) > threshold * 2.5


def _record(ctx: Ctx, **kw) -> None:
    if not ctx.store:
        return
    try:
        ctx.store.add(wamid=ctx.wamid, sender=ctx.sender, **kw)
    except Exception:
        log.exception("failed to save history")


async def handle_audio(ctx: Ctx, data: bytes, mime: str, kind: str, filename: str | None = None) -> None:
    """Voice notes, audio files and videos: transcript first, then summary/key points/translation."""
    s = ctx.settings
    base_mime = mime.split(";")[0].strip()
    ext = MIME_EXT.get(base_mime)
    if filename and not ext:
        ext = os.path.splitext(filename)[1].lstrip(".").lower() or None
    name = f"audio.{ext or 'ogg'}"
    dur = duration_seconds(data)

    tr = await ctx.ai.transcribe(data, name, base_mime, ctx.vocab, dur)
    text = tr.text
    summarise = bool(text) and long_enough(dur, text, s.summary_min_seconds)
    key_points = bool(text) and long_enough(dur, text, s.key_points_min_seconds)
    translate = ctx.lang if text else None

    header = "📝 *Transcript*" + (f" · {filename}" if filename else "")
    meta1 = [f"STT {tr.model} {tr.seconds:.2f}s"]
    if dur is not None:
        meta1.append(f"Audio {fmt_duration(dur)}")

    def done(summary: str | None, cost: float) -> None:
        total = time.perf_counter() - ctx.started
        log.info(
            "done kind=%s audio=%s stt=%.2fs total=%.2fs cost=%s",
            kind, f"{dur:.1f}s" if dur is not None else "unknown", tr.seconds, total, fmt_cost(cost),
        )
        _record(ctx, kind=kind, title=filename, audio_seconds=dur, content=text, summary=summary,
                latency=total, cost=cost)

    if not (summarise or translate):
        meta1 += [f"Total {time.perf_counter() - ctx.started:.2f}s", fmt_cost(tr.cost)]
        await ctx.send(f"{header}\n{text or '(no speech detected)'}\n\n{meta_line(meta1)}")
        done(None, tr.cost)
        return

    # Stage 1: the transcript goes out now; analysis follows in a second message.
    await ctx.send(f"{header}\n{text}\n\n{meta_line(meta1)}")

    a: Analysis | None = None
    try:
        a = await ctx.ai.analyse_voice(text, summarise, key_points, translate)
    except Exception:
        log.exception("analysis failed")

    sections = []
    if a is None or not a.ok:
        if summarise:
            sections.append("💡 *Summary*\n(unavailable)")
    else:
        if a.summary:
            sections.append(f"💡 *Summary*\n{a.summary}")
        if a.key_points:
            sections.append("📌 *Key points*\n" + "\n".join(f"• {p}" for p in a.key_points))
        if a.translation:
            sections.append(f"🌐 *Translation ({translate})*\n{a.translation}")

    cost = tr.cost + (a.cost if a else 0)
    if sections:
        label = "Summary" if summarise else "Translation"
        meta2 = []
        if a:
            meta2.append(f"{label} {a.model} {a.seconds:.2f}s")
        meta2 += [f"Total {time.perf_counter() - ctx.started:.2f}s", fmt_cost(cost)]
        await ctx.send("\n\n".join(sections) + "\n\n" + meta_line(meta2))
    done(a.summary if a else None, cost)


async def handle_document(ctx: Ctx, data: bytes, mime: str, filename: str, question: str | None) -> None:
    s = ctx.settings
    t0 = time.perf_counter()
    try:
        ext = await asyncio.to_thread(extract_text, data, mime, filename, s.doc_max_input_chars)
    except DocumentError as e:
        await ctx.send(f"📄 {e}")
        return
    extract_secs = time.perf_counter() - t0

    # Scanned pages (images of text) go through OCR; pages with real text are left as they are.
    ocr: Timed | None = None
    ocr_note = None
    scanned = ext.scanned_pages if s.ocr_enabled else []
    if scanned:
        todo = scanned[: s.ocr_max_pages]
        await ctx.send(f"🔍 *{filename}* has scanned pages. Reading {len(todo)} with OCR…")
        try:
            images = await asyncio.to_thread(render_pages, data, todo, s.ocr_image_max_side)
            texts, ocr = await ctx.ai.ocr_pages(images)
        except Exception:
            log.exception("OCR rendering failed")
            texts = [None] * len(todo)
        got = {i: t for i, t in zip(todo, texts) if t}
        ext = ext.with_ocr(got)
        ocr_note = f"🔍 OCR: {len(got)} of {len(scanned)} scanned page{'s' if len(scanned) != 1 else ''}"
        if len(scanned) > len(todo):
            ocr_note += f" (limit {s.ocr_max_pages})"
        failed = sum(t is None for t in texts)
        if failed:
            ocr_note += f", {failed} failed"
    ocr_cost = ocr.cost if ocr else 0.0

    text = ext.text.strip()
    if not text:
        hint = (
            "I couldn't read any text from it, even with OCR." if scanned
            else "If it's a scanned PDF, OCR is turned off on this bot (OCR_ENABLED)."
            if ext.kind == "PDF" and not s.ocr_enabled else "It looks empty."
        )
        await ctx.send(f"📄 I couldn't find any text in *{filename}*. {hint}")
        return
    truncated = len(text) > s.doc_max_input_chars
    used = text[: s.doc_max_input_chars]
    pages = f"{ext.pages} page{'s' if ext.pages != 1 else ''}" if ext.pages else None

    if estimate_tokens(used) > DOC_ACK_TOKENS:
        await ctx.send(f"📄 Reading *{filename}*" + (f" ({pages})" if pages else "") + "…")

    a = await ctx.ai.analyse_document(used, filename, ctx.lang, question, truncated)
    if not a.ok:
        await ctx.send(f"📄 Sorry, I couldn't analyse *{filename}*. Please try again.")
        _record(ctx, kind="document", title=filename, audio_seconds=None, content=used, summary=None,
                latency=time.perf_counter() - ctx.started, cost=a.cost + ocr_cost)
        return

    info = [ext.kind] + ([pages] if pages else [])
    lines = [f"📄 *{a.title or filename}*", f"{filename} · {' · '.join(info)}"]
    if ocr_note:
        lines.append(ocr_note)
    if truncated:
        pct = max(1, round(100 * len(used) / len(text)))
        lines.append(f"⚠️ Long document: analysed the first ~{pct}%.")
    blocks = ["\n".join(lines)]
    if question and a.answer:
        blocks.append(f"❓ *{question}*\n{a.answer}")
    if a.summary:
        blocks.append(f"💡 *Summary*\n{a.summary}")
    if a.key_points:
        blocks.append("📌 *Key points*\n" + "\n".join(f"• {p}" for p in a.key_points))

    total = time.perf_counter() - ctx.started
    cost = a.cost + ocr_cost
    meta = [f"Extract {extract_secs:.2f}s"]
    if ocr:
        meta.append(f"OCR {ocr.model} {ocr.seconds:.2f}s")
    meta += [
        f"Analysis {a.model} {a.seconds:.2f}s",
        f"Total {total:.2f}s",
        f"{fmt_tokens(a.input_tokens)} tokens in",
        fmt_cost(cost),
    ]
    blocks.append(meta_line(meta))
    await ctx.send("\n\n".join(blocks))
    log.info("done kind=document chars=%d ocr_pages=%d truncated=%s total=%.2fs cost=%s", len(used), len(scanned),
             truncated, total, fmt_cost(cost))
    _record(ctx, kind="document", title=filename, audio_seconds=None, content=used, summary=a.summary,
            latency=total, cost=cost)
