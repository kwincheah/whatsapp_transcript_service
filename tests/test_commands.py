from app.commands import handle_command
from app.store import Store
from tests.conftest import make_settings


def test_help_and_unknown():
    s = make_settings()
    assert "/search" in handle_command("/help", "1", s, Store(":memory:"))
    assert "Unknown command" in handle_command("/nope", "1", s, Store(":memory:"))
    assert "History is turned off" in handle_command("/stats", "1", s, None)


def test_lang_and_vocab():
    s, st = make_settings(stt_vocab="Railway"), Store(":memory:")
    assert "off" in handle_command("/lang", "1", s, st)
    assert "English" in handle_command("/lang English", "1", s, st)
    assert st.prefs("1")[0] == "English"
    handle_command("/lang off", "1", s, st)
    assert st.prefs("1")[0] == ""
    handle_command("/vocab add Kwin, DeepSeek", "1", s, st)
    handle_command("/vocab add Kwin", "1", s, st)
    assert st.prefs("1")[1] == ["Kwin", "DeepSeek"]
    assert "Railway, Kwin, DeepSeek" in handle_command("/vocab list", "1", s, st)
    handle_command("/vocab clear", "1", s, st)
    assert st.prefs("1")[1] == []


def test_search_and_stats():
    s, st = make_settings(), Store(":memory:")
    st.add(wamid="a", sender="1", kind="voice", title=None, audio_seconds=90, content="meeting moved to 3pm",
           summary="Meeting moved.", latency=2.0, cost=0.01)
    st.add(wamid="b", sender="1", kind="document", title="q3.pdf", audio_seconds=None, content="revenue report",
           summary="Revenue grew.", latency=4.0, cost=0.02)
    st.add(wamid="c", sender="2", kind="voice", title=None, audio_seconds=10, content="meeting elsewhere",
           summary=None, latency=1.0, cost=0.5)
    out = handle_command("/search meeting", "1", s, st)
    assert "*meeting* moved" in out and "elsewhere" not in out  # other users' history is private
    assert "No results" in handle_command("/search zzz", "1", s, st)
    assert "No results" in handle_command('/search "(* NEAR', "1", s, st)  # FTS syntax can't break it
    stats = handle_command("/stats", "1", s, st)
    assert "1 audio (1m 30s, avg 2.0s)" in stats and "1 document, avg 4.0s" in stats and "$0.0300" in stats
