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

    async def fake_handle(app, msg):
        calls.append(msg["id"])

    monkeypatch.setattr(main, "handle_message", fake_handle)
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid.1", "from": "60111", "type": "audio", "audio": {"id": "m1"}}
    ]}}]}]}
    assert client.post("/webhook", json=payload).status_code == 200
    assert client.post("/webhook", json=payload).status_code == 200  # Meta retry
    assert calls == ["wamid.1"]


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
