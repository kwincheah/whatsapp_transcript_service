import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import Settings

SUMMARY_PROMPT = (
    "Summarise this voice message transcript in one short sentence (max ~20 words), "
    "same language as the transcript. Output only the summary, no preamble."
)


@dataclass
class Timed:
    text: str
    model: str
    seconds: float


class AI:
    def __init__(self, settings: Settings):
        self.s = settings
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.deepseek = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)

    async def transcribe(self, audio: bytes, filename: str, mime_type: str) -> Timed:
        t0 = time.perf_counter()
        resp = await self.openai.audio.transcriptions.create(
            model=self.s.stt_model,
            file=(filename, audio, mime_type),
            response_format="text",
        )
        text = resp if isinstance(resp, str) else resp.text
        return Timed(text.strip(), self.s.stt_model, time.perf_counter() - t0)

    async def summarise(self, transcript: str) -> Timed:
        t0 = time.perf_counter()
        resp = await self.deepseek.chat.completions.create(
            model=self.s.summary_model,
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=self.s.summary_max_tokens,
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        return Timed(text, self.s.summary_model, time.perf_counter() - t0)
