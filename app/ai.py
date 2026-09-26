import json
import logging
import re
import time
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import Settings

log = logging.getLogger("transcriber")


@dataclass
class Timed:
    text: str
    model: str
    seconds: float
    cost: float = 0.0


@dataclass
class Analysis:
    model: str
    seconds: float
    cost: float
    input_tokens: int
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    translation: str | None = None
    answer: str | None = None
    title: str | None = None
    ok: bool = True


def estimate_tokens(text: str) -> int:
    # Conservative for mixed-language text (English ~4 chars/token, CJK ~1-2).
    return len(text) // 3 + 1


def _parse_json(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _str_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _opt_str(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


class AI:
    def __init__(self, settings: Settings):
        self.s = settings
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.deepseek = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)

    async def transcribe(
        self, audio: bytes, filename: str, mime_type: str, vocab: list[str], duration: float | None
    ) -> Timed:
        t0 = time.perf_counter()
        kwargs = {}
        if vocab:
            kwargs["prompt"] = "Vocabulary that may appear: " + ", ".join(vocab) + "."
        resp = await self.openai.audio.transcriptions.create(
            model=self.s.stt_model,
            file=(filename, audio, mime_type),
            response_format="text",
            **kwargs,
        )
        text = resp if isinstance(resp, str) else resp.text
        cost = (duration or 0) / 60 * self.s.price_stt_per_min
        return Timed(text.strip(), self.s.stt_model, time.perf_counter() - t0, cost)

    async def _json_chat(self, system: str, user: str, max_tokens: int) -> tuple[dict | None, Analysis]:
        t0 = time.perf_counter()
        resp = await self.deepseek.chat.completions.create(
            model=self.s.summary_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled" if self.s.summary_thinking else "disabled"}},
        )
        choice = resp.choices[0]
        raw = (choice.message.content or "").strip()
        u = resp.usage
        prompt_tokens = getattr(u, "prompt_tokens", 0) or 0
        hit = getattr(u, "prompt_cache_hit_tokens", 0) or 0
        out = getattr(u, "completion_tokens", 0) or 0
        cost = (
            (prompt_tokens - hit) * self.s.price_llm_input_per_m
            + hit * self.s.price_llm_cached_input_per_m
            + out * self.s.price_llm_output_per_m
        ) / 1_000_000
        meta = Analysis(self.s.summary_model, time.perf_counter() - t0, cost, prompt_tokens)
        data = _parse_json(raw)
        if data is None:
            log.warning(
                "unparseable analysis from %s (finish_reason=%s, %d chars)", resp.model, choice.finish_reason, len(raw)
            )
        return data, meta

    def voice_budget(self, transcript: str, summarise: bool, key_points: bool, translate_to: str | None) -> int:
        budget = 50  # JSON keys/overhead
        if summarise:
            budget += self.s.voice_summary_max_tokens
        if key_points:
            budget += self.s.voice_key_points_max_tokens
        if translate_to:
            # A translation is about as long as the source; allow 1.5x for scripts that tokenise worse.
            budget += min(self.s.translation_max_tokens, int(estimate_tokens(transcript) * 1.5) + 100)
        return budget

    async def analyse_voice(
        self, transcript: str, summarise: bool, key_points: bool, translate_to: str | None
    ) -> Analysis:
        lang = f"in {translate_to}" if translate_to else "in the transcript's language"
        fields = []
        if summarise:
            fields.append(f'"summary": one short sentence (max ~20 words) {lang}')
        if key_points:
            fields.append(f'"key_points": array of 3-5 short strings {lang}, action items and dates first')
        if translate_to:
            fields.append(
                f'"translation": faithful full translation into {translate_to}, '
                f"or null if the transcript is already mostly in {translate_to}"
            )
        system = (
            "You process a WhatsApp voice-message transcript. Reply with a JSON object with exactly these keys:\n- "
            + "\n- ".join(fields)
            + "\nBe concise. No extra keys, no commentary."
        )
        max_tokens = self.voice_budget(transcript, summarise, key_points, translate_to)
        data, a = await self._json_chat(system, transcript, max_tokens)
        if data is None:
            a.ok = False
            return a
        a.summary = _opt_str(data.get("summary")) or ""
        a.key_points = _str_list(data.get("key_points"))
        a.translation = _opt_str(data.get("translation"))
        # Translation-only calls legitimately return null when no translation is needed.
        a.ok = bool(a.summary or a.key_points or a.translation) or not (summarise or key_points)
        return a

    async def analyse_document(
        self, text: str, filename: str, lang: str | None, question: str | None, truncated: bool
    ) -> Analysis:
        in_lang = f"in {lang}" if lang else "in the document's language"
        fields = [
            '"title": short descriptive title (max 8 words)',
            f'"summary": 2-4 sentences {in_lang} covering purpose and main conclusions',
            f'"key_points": array of 3-7 short strings {in_lang}; include key numbers, dates, obligations, deadlines',
        ]
        if question:
            fields.append(f'"answer": direct answer to the user\'s question {in_lang}, based only on the document')
        system = (
            "You analyse a document the user forwarded on WhatsApp. Reply with a JSON object with exactly these keys:\n- "
            + "\n- ".join(fields)
            + "\nBe concise and factual. No extra keys, no commentary."
        )
        header = f"File: {filename}\n"
        if truncated:
            header += "(Only the first part of the document is included.)\n"
        if question:
            header += f"User's question: {question}\n"
        data, a = await self._json_chat(system, f"{header}\n---\n{text}", self.s.doc_max_output_tokens)
        if data is None:
            a.ok = False
            return a
        a.title = _opt_str(data.get("title"))
        a.summary = _opt_str(data.get("summary")) or ""
        a.key_points = _str_list(data.get("key_points"))
        a.answer = _opt_str(data.get("answer"))
        a.ok = bool(a.summary or a.key_points)
        return a
