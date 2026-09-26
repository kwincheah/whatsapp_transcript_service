import hashlib
import hmac

import pytest

from app import pipeline
from app.ai import AI, Analysis
from app.whatsapp import split_message, valid_signature
from tests.conftest import FakeAI, make_settings


def _dur(monkeypatch, seconds):
    monkeypatch.setattr(pipeline, "duration_seconds", lambda _: seconds)


async def test_short_audio_single_message_no_analysis(monkeypatch, ctx_factory):
    _dur(monkeypatch, 5.0)
    ctx, sent = ctx_factory()
    await pipeline.handle_audio(ctx, b"x", "audio/ogg; codecs=opus", "voice")
    assert ctx.ai.voice_calls == []
    assert len(sent) == 1
    assert sent[0].startswith("📝 *Transcript*\nhello there this is a test")
    assert "STT gpt-4o-mini-transcribe 0.50s" in sent[0] and "Audio 5s" in sent[0] and "Total" in sent[0]
    assert "$0.0010" in sent[0]


async def test_long_audio_two_stage_reply(monkeypatch, ctx_factory):
    _dur(monkeypatch, 14.0)
    ctx, sent = ctx_factory()
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert ctx.ai.voice_calls == [dict(summarise=True, key_points=False, translate_to=None)]
    assert len(sent) == 2
    assert sent[0].startswith("📝 *Transcript*") and "Summary" not in sent[0] and "Total" not in sent[0]
    assert sent[1].startswith("💡 *Summary*\nShort summary.")
    assert "Summary deepseek-v4-flash 0.30s" in sent[1] and "Total" in sent[1]
    assert "$0.0012" in sent[1]  # STT + analysis


async def test_very_long_audio_gets_key_points(monkeypatch, ctx_factory):
    _dur(monkeypatch, 95.0)
    ctx, sent = ctx_factory()
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert ctx.ai.voice_calls[0]["key_points"] is True
    assert "📌 *Key points*\n• Point A\n• Point B" in sent[1]
    assert "Audio 1m 35s" in sent[0]


async def test_translation_for_short_audio(monkeypatch, ctx_factory):
    _dur(monkeypatch, 4.0)
    ctx, sent = ctx_factory(lang="English")
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert ctx.ai.voice_calls == [dict(summarise=False, key_points=False, translate_to="English")]
    assert len(sent) == 2
    assert sent[1].startswith("🌐 *Translation (English)*\nTranslated text.")
    assert "💡" not in sent[1] and "Translation deepseek-v4-flash" in sent[1]


async def test_no_translation_needed_sends_only_transcript(monkeypatch, ctx_factory):
    _dur(monkeypatch, 4.0)
    ai = FakeAI(analysis=Analysis("deepseek-v4-flash", 0.2, 0.0, 10, translation=None))
    ctx, sent = ctx_factory(ai=ai, lang="English")
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert len(sent) == 1


async def test_analysis_failure_keeps_transcript(monkeypatch, ctx_factory):
    _dur(monkeypatch, 20.0)
    ctx, sent = ctx_factory(ai=FakeAI(fail=True))
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert "hello there this is a test" in sent[0]
    assert sent[1].startswith("💡 *Summary*\n(unavailable)")


async def test_unknown_duration_uses_word_count(monkeypatch, ctx_factory):
    _dur(monkeypatch, None)
    ctx, _ = ctx_factory(ai=FakeAI("just a few words"))
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert ctx.ai.voice_calls == []
    ctx, _ = ctx_factory(ai=FakeAI(" ".join(["word"] * 40)))
    await pipeline.handle_audio(ctx, b"x", "audio/ogg", "voice")
    assert ctx.ai.voice_calls[0]["summarise"] is True


async def test_vocab_passed_and_history_saved(monkeypatch, ctx_factory):
    _dur(monkeypatch, 5.0)
    ctx, _ = ctx_factory(vocab=["Kwin", "Railway"])
    await pipeline.handle_audio(ctx, b"x", "video/mp4", "video")
    assert ctx.ai.vocab == ["Kwin", "Railway"]
    assert ctx.store.search("60111", "hello")[0].kind == "video"


def test_voice_budget_scales_with_task():
    ai = AI(make_settings())
    short = ai.voice_budget("hi " * 10, True, False, None)
    kp = ai.voice_budget("hi " * 10, True, True, None)
    tr_small = ai.voice_budget("hi " * 10, True, False, "English")
    tr_big = ai.voice_budget("word " * 5000, True, False, "English")
    assert short == 200 and kp == 550
    assert short < tr_small < tr_big
    assert tr_big == 200 + 4000  # capped by TRANSLATION_MAX_TOKENS


class _Resp:
    def __init__(self, content, finish="stop"):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"finish_reason": finish, "message": msg})()]
        self.model = "deepseek-flash"
        self.usage = type("U", (), {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 0, "completion_tokens": 100})()


async def test_deepseek_params_json_mode_no_thinking_and_cost(monkeypatch):
    ai = AI(make_settings())
    seen = {}

    async def fake_create(**kw):
        seen.update(kw)
        return _Resp('{"summary": "Sum.", "key_points": ["a"], "translation": null}')

    monkeypatch.setattr(ai.deepseek.chat.completions, "create", fake_create)
    a = await ai.analyse_voice("some transcript", True, True, None)
    assert (a.summary, a.key_points, a.ok) == ("Sum.", ["a"], True)
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["max_tokens"] == 550
    assert a.cost == pytest.approx((1000 * 0.30 + 100 * 1.20) / 1e6)


async def test_document_budget_and_bad_json(monkeypatch):
    ai = AI(make_settings())
    seen = {}

    async def fake_create(**kw):
        seen.update(kw)
        return _Resp("not json", finish="length")

    monkeypatch.setattr(ai.deepseek.chat.completions, "create", fake_create)
    a = await ai.analyse_document("text", "a.pdf", None, "What is X?", False)
    assert a.ok is False
    assert seen["max_tokens"] == 1500
    assert "User's question: What is X?" in seen["messages"][1]["content"]


def test_split_message():
    assert split_message("short") == ["short"]
    parts = split_message(("para " * 300 + "\n\n") * 5, limit=2000)
    assert len(parts) > 1 and all(len(p) <= 2020 for p in parts)
    assert parts[0].endswith(f"(1/{len(parts)})")


def test_signature():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert valid_signature("secret", body, sig)
    assert not valid_signature("secret", body, "sha256=deadbeef")
    assert not valid_signature("secret", body, None)


async def test_web_search_api_parsing(monkeypatch):
    from types import SimpleNamespace as NS

    ai = AI(make_settings(web_search_country="my"))
    seen = {}
    resp = NS(
        output=[
            NS(type="web_search_call"),
            NS(type="message", content=[NS(annotations=[
                NS(type="url_citation", url="https://bnm.gov.my/opr?utm_source=openai", title="BNM"),
                NS(type="url_citation", url="https://bnm.gov.my/opr", title="dup"),
                NS(type="file_citation"),
            ])]),
        ],
        output_text="**OPR** is 3.00% ([bnm.gov.my](https://bnm.gov.my/opr?utm_source=openai)).",
        usage=NS(input_tokens=10_000, output_tokens=300),
    )

    async def fake_create(**kw):
        seen.update(kw)
        return resp

    monkeypatch.setattr(ai.openai.responses, "create", fake_create)
    a = await ai.web_search("OPR?", "English")
    assert a.text == "*OPR* is 3.00%."
    assert a.sources == [("BNM", "https://bnm.gov.my/opr")]
    assert a.searches == 1
    assert a.cost == pytest.approx(0.01 + (10_000 * 0.20 + 300 * 1.20) / 1e6)
    assert seen["tools"] == [{"type": "web_search", "search_context_size": "low",
                              "user_location": {"type": "approximate", "country": "MY"}}]
    assert seen["reasoning"] == {"effort": "low"} and seen["max_output_tokens"] == 1500
    assert "Answer in English." in seen["instructions"]
