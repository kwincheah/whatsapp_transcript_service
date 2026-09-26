import logging
import time
from datetime import datetime, timezone

from app.ai import AI
from app.config import Settings
from app.pipeline import fmt_cost, fmt_duration
from app.store import Store

log = logging.getLogger("transcriber")

HELP = """🤖 *Voice & document assistant*

*Send or forward me*
🎙️ Voice notes, audio files, videos → transcript
   + summary if over {min_s:g}s, + key points if over {kp_s:g}s
📄 PDF, Word (.docx) or text files → summary + key points
   Add a caption to ask a question about the file.

*Commands*
/lang English — also translate (/lang off to stop)
/vocab add Name1, Name2 — words to spell correctly
/vocab list · /vocab clear
/search question — search the web
/find keyword — find past transcripts & documents
/stats — usage, latency and cost
/help — this message"""

NO_STORE = "History is turned off on this bot, so this command isn't available."


def _stats_line(label: str, r: dict) -> str:
    if not r["n"]:
        return f"*{label}:* nothing yet"
    parts = []
    if r["voice_n"]:
        lat = f", avg {r['voice_lat']:.1f}s" if r["voice_lat"] else ""
        parts.append(f"{r['voice_n']} audio ({fmt_duration(r['audio_s'])}{lat})")
    if r["doc_n"]:
        lat = f", avg {r['doc_lat']:.1f}s" if r["doc_lat"] else ""
        parts.append(f"{r['doc_n']} document{'s' if r['doc_n'] != 1 else ''}{lat}")
    if r["web_n"]:
        parts.append(f"{r['web_n']} web search{'es' if r['web_n'] != 1 else ''}")
    return f"*{label}:* " + " · ".join(parts) + f" · {fmt_cost(r['cost'])}"


async def web_search(question: str, sender: str, wamid: str, settings: Settings, store: Store | None, ai: AI) -> str:
    if not settings.web_search_enabled:
        return "🔎 Web search is turned off on this bot."
    if not question:
        return "🔎 Usage: /search your question\ne.g. /search latest OPR rate Malaysia"
    t0 = time.perf_counter()
    lang = None
    if store:
        user_lang, _ = store.prefs(sender)
        lang = (settings.translate_to if user_lang is None else user_lang) or None
    try:
        a = await ai.web_search(question, lang)
    except Exception:
        log.exception("web search failed")
        return "🔎 Sorry, the web search failed. Please try again."
    total = time.perf_counter() - t0
    lines = [f"🔎 *{question}*", a.text or "(no answer found)"]
    if a.sources:
        lines += ["", "*Sources*"] + [f"{i}. {title}\n{url}" for i, (title, url) in enumerate(a.sources, 1)]
    meta = [f"Web search {a.model} {a.seconds:.2f}s"]
    if a.searches != 1:
        meta.append(f"{a.searches} searches")
    meta.append(fmt_cost(a.cost))
    lines += ["", "_⏱ " + " · ".join(meta) + "_"]
    log.info("done kind=web searches=%d total=%.2fs cost=%s", a.searches, total, fmt_cost(a.cost))
    if store:
        try:
            store.add(wamid=wamid, sender=sender, kind="web", title=question, audio_seconds=None, content=a.text,
                      summary=None, latency=total, cost=a.cost)
        except Exception:
            log.exception("failed to save history")
    return "\n".join(lines)


async def handle_command(
    text: str, sender: str, settings: Settings, store: Store | None, ai: AI | None = None, wamid: str = ""
) -> str:
    cmd, _, arg = text.strip().partition(" ")
    cmd, arg = cmd.lower(), arg.strip()

    if cmd in ("/help", "/start"):
        return HELP.format(min_s=settings.summary_min_seconds, kp_s=settings.key_points_min_seconds)

    if cmd == "/search":
        return await web_search(arg, sender, wamid, settings, store, ai)

    if store is None:
        return NO_STORE

    lang, vocab = store.prefs(sender)

    if cmd == "/lang":
        if not arg:
            current = settings.translate_to if lang is None else lang
            return f"🌐 Translation: *{current or 'off'}*\nUse /lang English (any language) or /lang off."
        if arg.lower() in ("off", "none", "no"):
            store.set_lang(sender, "")
            return "🌐 Translation turned *off*."
        store.set_lang(sender, arg[:40])
        return f"🌐 I'll translate voice notes into *{arg[:40]}* (and write document summaries in it)."

    if cmd == "/vocab":
        sub, _, rest = arg.partition(" ")
        sub = sub.lower()
        if sub == "add" and rest.strip():
            new = [w.strip() for w in rest.split(",") if w.strip()]
            merged = list(dict.fromkeys(vocab + new))[:100]
            store.set_vocab(sender, merged)
            return f"🔤 Added {len(new)} word(s). Vocabulary: {', '.join(merged)}"
        if sub == "clear":
            store.set_vocab(sender, [])
            return "🔤 Vocabulary cleared."
        words = settings.stt_vocab_list + vocab
        return (
            "🔤 Vocabulary: " + (", ".join(words) if words else "(empty)") +
            "\nUse /vocab add Name1, Name2 or /vocab clear."
        )

    if cmd == "/find":
        if not arg:
            return "🗂️ Usage: /find keyword"
        hits = store.search(sender, arg)
        if not hits:
            return f"🗂️ Nothing in your history matches “{arg}”."
        lines = [f"🗂️ *Your history: “{arg}”*"]
        for h in hits:
            when = datetime.fromtimestamp(h.ts, timezone.utc).strftime("%d %b %Y")
            icon = {"document": "📄", "web": "🔎"}.get(h.kind, "🎙️")
            title = f" *{h.title}*" if h.title else ""
            lines.append(f"\n{icon}{title} · {when}\n{h.snippet}")
        return "\n".join(lines)

    if cmd == "/stats":
        now = time.time()
        month = store.stats(sender, now - 30 * 86400)
        total = store.stats(sender, 0)
        current = settings.translate_to if lang is None else lang
        return "\n".join([
            "📊 *Stats*",
            _stats_line("Last 30 days", month),
            _stats_line("All time", total),
            f"Translation: {current or 'off'} · Vocabulary: {len(settings.stt_vocab_list + vocab)} words",
            "_Costs are estimates._",
        ])

    return "Unknown command. Send /help to see what I can do."
