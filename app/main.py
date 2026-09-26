import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response

from app.ai import AI
from app.config import get_settings
from app.pipeline import format_reply, process
from app.whatsapp import WhatsApp, valid_signature

log = logging.getLogger("transcriber")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Meta retries webhooks it thinks failed; remember recent message ids to avoid double replies.
_seen: OrderedDict[str, None] = OrderedDict()
_SEEN_MAX = 1000


def _first_time(message_id: str) -> bool:
    if message_id in _seen:
        return False
    _seen[message_id] = None
    if len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Lengths only (never values) to catch truncated env vars.
    log.info(
        "config: phone_number_id=%s token_len=%d app_secret_len=%d allowed=%s",
        settings.whatsapp_phone_number_id,
        len(settings.whatsapp_token),
        len(settings.whatsapp_app_secret),
        sorted(settings.allowed_sender_set) or "anyone",
    )
    async with httpx.AsyncClient(timeout=60) as client:
        app.state.settings = settings
        app.state.wa = WhatsApp(settings, client)
        app.state.ai = AI(settings)
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhook")
async def verify(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    if mode == "subscribe" and token == get_settings().whatsapp_verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403)


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    settings = request.app.state.settings
    body = await request.body()
    if settings.whatsapp_app_secret and not valid_signature(
        settings.whatsapp_app_secret, body, request.headers.get("x-hub-signature-256")
    ):
        raise HTTPException(401, "bad signature")

    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # The bot number that received the message; reply from the same one.
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            for msg in value.get("messages", []):
                if _first_time(msg.get("id", "")):
                    background.add_task(handle_message, request.app, msg, phone_number_id)
    # Always 200 quickly so Meta doesn't retry; work happens in the background.
    return {"ok": True}


async def handle_message(app: FastAPI, msg: dict, phone_number_id: str | None = None) -> None:
    settings, wa, ai = app.state.settings, app.state.wa, app.state.ai
    sender, msg_id = msg.get("from", ""), msg.get("id")
    allowed = settings.allowed_sender_set
    if allowed and sender not in allowed:
        log.info("ignoring message from non-allowed sender %s", sender)
        return

    if msg.get("type") != "audio":
        try:
            await wa.send_text(
                sender, "Forward me a voice message and I'll transcribe it.", msg_id, phone_number_id
            )
        except Exception:
            log.error("failed to send hint reply for %s", msg_id)
        return

    started = time.perf_counter()
    try:
        audio, mime = await wa.download_media(msg["audio"]["id"])
        result = await process(ai, audio, mime, settings.summary_min_seconds, started_at=started)
        reply = format_reply(result)
        log.info(
            "done audio=%s stt=%.2fs summary=%s total=%.2fs",
            f"{result.audio_seconds:.1f}s" if result.audio_seconds is not None else "unknown",
            result.transcript.seconds,
            "failed" if result.summary_failed else f"{result.summary.seconds:.2f}s" if result.summary else "skipped",
            result.total_seconds,
        )
    except Exception:
        log.exception("failed to process %s", msg_id)
        reply = "Sorry, I couldn't transcribe that voice message."
    try:
        await wa.send_text(sender, reply, msg_id, phone_number_id)
    except Exception:
        log.error("failed to send reply for %s", msg_id)
