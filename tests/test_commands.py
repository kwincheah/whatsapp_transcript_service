from app.commands import handle_command
from app.store import Store
from tests.conftest import make_settings


async def test_help_and_unknown():
    s = make_settings()
    assert "/search" in await handle_command("/help", "1", s, Store(":memory:"))
    assert "Unknown command" in await handle_command("/nope", "1", s, Store(":memory:"))
    assert "History is turned off" in await handle_command("/stats", "1", s, None)


async def test_lang_and_vocab():
    s, st = make_settings(stt_vocab="Railway"), Store(":memory:")
    assert "off" in await handle_command("/lang", "1", s, st)
    assert "English" in await handle_command("/lang English", "1", s, st)
    assert st.prefs("1")[0] == "English"
    await handle_command("/lang off", "1", s, st)
    assert st.prefs("1")[0] == ""
    await handle_command("/vocab add Kwin, DeepSeek", "1", s, st)
    await handle_command("/vocab add Kwin", "1", s, st)
    assert st.prefs("1")[1] == ["Kwin", "DeepSeek"]
    assert "Railway, Kwin, DeepSeek" in await handle_command("/vocab list", "1", s, st)
    await handle_command("/vocab clear", "1", s, st)
    assert st.prefs("1")[1] == []


async def test_search_and_stats():
    s, st = make_settings(), Store(":memory:")
    st.add(wamid="a", sender="1", kind="voice", title=None, audio_seconds=90, content="meeting moved to 3pm",
           summary="Meeting moved.", latency=2.0, cost=0.01)
    st.add(wamid="b", sender="1", kind="document", title="q3.pdf", audio_seconds=None, content="revenue report",
           summary="Revenue grew.", latency=4.0, cost=0.02)
    st.add(wamid="c", sender="2", kind="voice", title=None, audio_seconds=10, content="meeting elsewhere",
           summary=None, latency=1.0, cost=0.5)
    out = await handle_command("/find meeting", "1", s, st)
    assert "*meeting* moved" in out and "elsewhere" not in out  # other users' history is private
    assert "Nothing in your history" in await handle_command("/find zzz", "1", s, st)
    assert "Nothing in your history" in await handle_command('/find "(* NEAR', "1", s, st)  # FTS syntax can't break it
    stats = await handle_command("/stats", "1", s, st)
    assert "1 audio (1m 30s, avg 2.0s)" in stats and "1 document, avg 4.0s" in stats and "$0.0300" in stats


# ---------- web search ----------

class FakeWebAI:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def web_search(self, question, lang):
        from app.ai import WebAnswer

        self.calls.append((question, lang))
        if self.fail:
            raise RuntimeError("down")
        return WebAnswer("The OPR is *3.00%*.", [("BNM statement", "https://bnm.gov.my/opr")],
                         "gpt-5.6-luna", 3.2, 0.0125, 1)


async def test_web_search_command_and_history():
    s, st, ai = make_settings(), Store(":memory:"), FakeWebAI()
    st.set_lang("1", "English")
    out = await handle_command("/search latest OPR Malaysia", "1", s, st, ai, "w1")
    assert ai.calls == [("latest OPR Malaysia", "English")]
    assert out.startswith("🔎 *latest OPR Malaysia*\nThe OPR is *3.00%*.")
    assert "*Sources*\n1. BNM statement\nhttps://bnm.gov.my/opr" in out
    assert "Web search gpt-5.6-luna 3.20s · $0.0125" in out
    assert "🔎" in await handle_command("/find OPR", "1", s, st)  # saved to history
    assert "1 web search" in await handle_command("/stats", "1", s, st)


async def test_web_search_usage_errors_and_off():
    s, ai = make_settings(), FakeWebAI()
    assert "Usage: /search" in await handle_command("/search", "1", s, None, ai)
    assert "failed" in await handle_command("/search x", "1", s, None, FakeWebAI(fail=True))
    assert "turned off" in await handle_command("/search x", "1", make_settings(web_search_enabled=False), None, ai)
    await handle_command("/search works without history", "1", s, None, ai)
    assert ai.calls[-1] == ("works without history", None)
