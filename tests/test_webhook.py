import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings


@pytest.fixture
def client(monkeypatch):
    for k, v in {
        "WHATSAPP_TOKEN": "t",
        "WHATSAPP_PHONE_NUMBER_ID": "1",
        "WHATSAPP_VERIFY_TOKEN": "verify",
        "OPENAI_API_KEY": "o",
        "DEEPSEEK_API_KEY": "d",
        "ALLOWED_SENDERS": "+60111",
        "DB_PATH": ":memory:",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    main._seen.clear()
    with TestClient(main.app) as c:
        yield c
    get_settings.cache_clear()


def test_verify(client):
    q = {"hub.mode": "subscribe", "hub.verify_token": "verify", "hub.challenge": "42"}
    assert client.get("/webhook", params=q).text == "42"
    q["hub.verify_token"] = "nope"
    assert client.get("/webhook", params=q).status_code == 403


def test_voice_message_is_processed_once(client, monkeypatch):
    calls = []

    async def fake_handle(app, msg, phone_number_id=None):
        calls.append((msg["id"], phone_number_id))

    monkeypatch.setattr(main, "handle_message", fake_handle)
    payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "1329315093600329"}, "messages": [
        {"id": "wamid.1", "from": "60111", "type": "audio", "audio": {"id": "m1"}}
    ]}}]}]}
    assert client.post("/webhook", json=payload).status_code == 200
    assert client.post("/webhook", json=payload).status_code == 200  # Meta retry
    assert calls == [("wamid.1", "1329315093600329")]


async def test_non_allowed_sender_ignored(client):
    sent = []

    class WA:
        async def send_text(self, *a):
            sent.append(a)

    main.app.state.wa = WA()
    await main.handle_message(main.app, {"id": "x", "from": "999", "type": "text"})
    assert sent == []
    await main.handle_message(main.app, {"id": "y", "from": "60111", "type": "text"})
    assert len(sent) == 1


async def test_send_failure_is_logged_not_raised(client):
    class WA:
        async def send_text(self, *a):
            raise RuntimeError("401")

    main.app.state.wa = WA()
    await main.handle_message(main.app, {"id": "z", "from": "60111", "type": "text"})


class RecordingWA:
    def __init__(self, media=(b"data", "application/pdf"), size_error=None):
        self.sent, self.downloads, self.media, self.size_error = [], [], media, size_error

    async def send_text(self, to, body, reply_to=None, phone_number_id=None):
        self.sent.append(body)

    async def download_media(self, media_id, max_bytes=None):
        self.downloads.append((media_id, max_bytes))
        if self.size_error:
            raise self.size_error
        return self.media


async def test_routing(client, monkeypatch):
    calls = []

    async def fake_audio(ctx, data, mime, kind, filename=None):
        calls.append(("audio", kind, mime, filename, ctx.lang, ctx.vocab))

    async def fake_doc(ctx, data, mime, filename, question):
        calls.append(("doc", filename, question))

    monkeypatch.setattr(main, "handle_audio", fake_audio)
    monkeypatch.setattr(main, "handle_document", fake_doc)
    wa = RecordingWA()
    main.app.state.wa = wa
    main.app.state.store.set_lang("60111", "English")
    main.app.state.store.set_vocab("60111", ["Kwin"])

    def m(**kw):
        return {"id": "w", "from": "60111", **kw}

    await main.handle_message(main.app, m(type="audio", audio={"id": "a1", "voice": True, "mime_type": "audio/ogg"}))
    await main.handle_message(main.app, m(type="video", video={"id": "v1", "mime_type": "video/mp4"}))
    await main.handle_message(main.app, m(type="document", document={
        "id": "d1", "filename": "call.m4a", "mime_type": "audio/mp4"}))
    await main.handle_message(main.app, m(type="document", document={
        "id": "d2", "filename": "q3.pdf", "mime_type": "application/pdf", "caption": "Did revenue grow?"}))
    assert calls == [
        ("audio", "voice", "audio/ogg", None, "English", ["Kwin"]),
        ("audio", "video", "video/mp4", None, "English", ["Kwin"]),
        ("audio", "audio_file", "audio/mp4", "call.m4a", "English", ["Kwin"]),
        ("doc", "q3.pdf", "Did revenue grow?"),
    ]
    mb = 1024 * 1024
    assert wa.downloads == [("a1", 25 * mb), ("v1", 25 * mb), ("d1", 25 * mb), ("d2", 20 * mb)]

    # Unsupported file: rejected before downloading
    await main.handle_message(main.app, m(type="document", document={
        "id": "d3", "filename": "a.zip", "mime_type": "application/zip"}))
    assert "can't read *a.zip*" in wa.sent[-1] and len(wa.downloads) == 4
    await main.handle_message(main.app, m(type="image", image={"id": "i"}))
    assert "Images aren't supported" in wa.sent[-1]
    await main.handle_message(main.app, m(type="text", text={"body": "/lang"}))
    assert "English" in wa.sent[-1]
    await main.handle_message(main.app, m(type="text", text={"body": "hello"}))
    assert "/help" in wa.sent[-1]


async def test_too_large_file(client):
    from app.whatsapp import MediaTooLarge

    wa = RecordingWA(size_error=MediaTooLarge(30 * 1024 * 1024, 25 * 1024 * 1024))
    main.app.state.wa = wa
    await main.handle_message(main.app, {"id": "w", "from": "60111", "type": "audio", "audio": {"id": "a"}})
    assert wa.sent == ["That file is too large (30 MB). The limit is 25 MB."]
