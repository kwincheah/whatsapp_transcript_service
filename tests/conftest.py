import pytest

from app.ai import Analysis, Timed
from app.config import Settings
from app.pipeline import Ctx
from app.store import Store


def make_settings(**kw) -> Settings:
    base = dict(
        whatsapp_token="t", whatsapp_phone_number_id="1", whatsapp_verify_token="v",
        openai_api_key="o", deepseek_api_key="d", db_path=":memory:", _env_file=None,
    )
    base.update(kw)
    return Settings(**base)


class FakeAI:
    """Records calls; returns canned results."""

    def __init__(self, text="hello there this is a test", analysis=None, doc=None, fail=False):
        self.text, self.analysis, self.doc, self.fail = text, analysis, doc, fail
        self.voice_calls, self.doc_calls, self.vocab = [], [], None

    async def transcribe(self, audio, filename, mime_type, vocab, duration):
        self.vocab = vocab
        return Timed(self.text, "gpt-4o-mini-transcribe", 0.5, 0.001)

    async def analyse_voice(self, transcript, summarise, key_points, translate_to):
        self.voice_calls.append(dict(summarise=summarise, key_points=key_points, translate_to=translate_to))
        if self.fail:
            raise RuntimeError("deepseek down")
        if self.analysis:
            return self.analysis
        return Analysis(
            "deepseek-v4-flash", 0.3, 0.0002, 100,
            summary="Short summary." if summarise else "",
            key_points=["Point A", "Point B"] if key_points else [],
            translation="Translated text." if translate_to else None,
        )

    async def analyse_document(self, text, filename, lang, question, truncated):
        self.doc_calls.append(dict(text=text, filename=filename, lang=lang, question=question, truncated=truncated))
        return self.doc or Analysis(
            "deepseek-v4-flash", 1.2, 0.004, 12_000, title="Quarterly Report",
            summary="Revenue grew.", key_points=["Revenue +10%", "Due 1 Oct"],
            answer="Yes, 10%." if question else None,
        )


@pytest.fixture
def ctx_factory():
    def make(ai=None, lang=None, vocab=None, store=True, **settings_kw):
        sent = []

        async def send(text):
            sent.append(text)

        ctx = Ctx(
            settings=make_settings(**settings_kw), ai=ai or FakeAI(), store=Store(":memory:") if store else None,
            sender="60111", wamid="wamid.1", send=send, started=0.0, lang=lang, vocab=vocab or [],
        )
        return ctx, sent

    return make
