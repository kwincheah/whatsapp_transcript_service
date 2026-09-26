import hashlib
import hmac

import pytest

from app import pipeline
from app.ai import Timed
from app.whatsapp import valid_signature


class FakeAI:
    def __init__(self, text="hello there this is a test"):
        self.text = text
        self.summarised = False

    async def transcribe(self, audio, filename, mime_type):
        assert filename == "voice.ogg" and mime_type == "audio/ogg"
        return Timed(self.text, "gpt-4o-mini-transcribe", 0.5)

    async def summarise(self, transcript):
        self.summarised = True
        return Timed("Short summary.", "deepseek-v4-flash", 0.3)


@pytest.mark.parametrize("dur,expect_summary", [(5.0, False), (8.0, False), (12.0, True)])
async def test_summary_only_when_longer_than_threshold(monkeypatch, dur, expect_summary):
    monkeypatch.setattr(pipeline, "duration_seconds", lambda _: dur)
    ai = FakeAI()
    r = await pipeline.process(ai, b"x", "audio/ogg; codecs=opus", 8.0)
    assert ai.summarised is expect_summary
    out = pipeline.format_reply(r)
    assert out.startswith("📝 *Transcript*\nhello there this is a test")
    assert "gpt-4o-mini-transcribe 0.50s" in out
    assert ("deepseek-v4-flash 0.30s" in out) is expect_summary
    assert ("💡 *Summary*\nShort summary." in out) is expect_summary
    assert f"Audio {dur:.0f}s" in out


async def test_unknown_duration_falls_back_to_word_count(monkeypatch):
    monkeypatch.setattr(pipeline, "duration_seconds", lambda _: None)
    short = FakeAI("just a few words")
    await pipeline.process(short, b"x", "audio/ogg", 8.0)
    assert not short.summarised
    long = FakeAI(" ".join(["word"] * 40))
    await pipeline.process(long, b"x", "audio/ogg", 8.0)
    assert long.summarised


def test_signature():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert valid_signature("secret", body, sig)
    assert not valid_signature("secret", body, "sha256=deadbeef")
    assert not valid_signature("secret", body, None)


@pytest.mark.parametrize("mode", ["raise", "empty"])
async def test_summary_failure_keeps_transcript(monkeypatch, mode):
    monkeypatch.setattr(pipeline, "duration_seconds", lambda _: 20.0)

    class BrokenAI(FakeAI):
        async def summarise(self, transcript):
            if mode == "raise":
                raise RuntimeError("deepseek down")
            return Timed("", "deepseek-v4-flash", 0.3)

    r = await pipeline.process(BrokenAI(), b"x", "audio/ogg", 8.0)
    out = pipeline.format_reply(r)
    assert "hello there this is a test" in out
    assert "💡 *Summary*\n(unavailable)" in out


async def test_summarise_disables_thinking_by_default(monkeypatch):
    from app.ai import AI
    from app.config import Settings

    s = Settings(
        whatsapp_token="t", whatsapp_phone_number_id="1", whatsapp_verify_token="v",
        openai_api_key="o", deepseek_api_key="d", _env_file=None,
    )
    ai = AI(s)
    seen = {}

    class Resp:
        model = "deepseek-flash"
        choices = [type("C", (), {"finish_reason": "stop", "message": type("M", (), {"content": " Sum. "})()})()]

    async def fake_create(**kw):
        seen.update(kw)
        return Resp()

    monkeypatch.setattr(ai.deepseek.chat.completions, "create", fake_create)
    out = await ai.summarise("some transcript")
    assert out.text == "Sum."
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
