import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response

from app.ai import AI
from app.commands import handle_command
from app.config import MB, get_settings
from app.documents import kind_of
from app.pipeline import Ctx, handle_audio, handle_document
from app.store import Store
from app.whatsapp import MediaTooLarge, WhatsApp, valid_signature

log = logging.getLogger("transcriber")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HINT = "Send or forward me a voice note, audio/video file, or a PDF, Word or text file. Send /help for more."
UNSUPPORTED = {
    "image": "📷 Images aren't supported yet. Send a PDF, Word or text file, or a voice note.",
    "sticker": HINT,
    "location": HINT,
    "contacts": HINT,
}

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
    store = None
    if settings.db_path:
        try:
            store = Store(settings.db_path)
            log.info("history: %s", settings.db_path)
        except Exception:
            log.exception("history disabled: can't open %s", settings.db_path)
    async with httpx.AsyncClient(timeout=120) as client:
        app.state.settings = settings
        app.state.wa = WhatsApp(settings, client)
        app.state.ai = AI(settings)
        app.state.store = store
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
    settings, wa, ai, store = app.state.settings, app.state.wa, app.state.ai, app.state.store
    sender, msg_id, mtype = msg.get("from", ""), msg.get("id", ""), msg.get("type")
    allowed = settings.allowed_sender_set
    if allowed and sender not in allowed:
        log.info("ignoring message from non-allowed sender %s", sender)
        return

    async def send(text: str) -> None:
        await wa.send_text(sender, text, msg_id, phone_number_id)

    try:
        await _dispatch(app, msg, sender, msg_id, mtype, send)
    except MediaTooLarge as e:
        await _safe_send(send, f"That file is too large ({e.size // MB} MB). The limit is {e.limit // MB} MB.")
    except Exception:
        log.exception("failed to process %s (%s)", msg_id, mtype)
        await _safe_send(send, "Sorry, something went wrong processing that. Please try again.")


async def _safe_send(send, text: str) -> None:
    try:
        await send(text)
    except Exception:
        log.error("failed to send reply")


async def _dispatch(app: FastAPI, msg: dict, sender: str, msg_id: str, mtype: str | None, send) -> None:
    settings, wa, ai, store = app.state.settings, app.state.wa, app.state.ai, app.state.store

    if mtype == "text":
        body = msg.get("text", {}).get("body", "").strip()
        await send(handle_command(body, sender, settings, store) if body.startswith("/") else HINT)
        return
    if mtype in UNSUPPORTED or mtype not in ("audio", "video", "document"):
        await send(UNSUPPORTED.get(mtype, HINT))
        return

    started = time.perf_counter()
    lang, user_vocab = store.prefs(sender) if store else (None, [])
    ctx = Ctx(
        settings=settings,
        ai=ai,
        store=store,
        sender=sender,
        wamid=msg_id,
        send=send,
        started=started,
        # None = no personal choice (use the default); "" = explicitly off.
        lang=(settings.translate_to if lang is None else lang) or None,
        vocab=settings.stt_vocab_list + user_vocab,
    )
    media = msg[mtype]

    if mtype in ("audio", "video"):
        data, mime = await wa.download_media(media["id"], settings.stt_max_bytes)
        kind = "voice" if media.get("voice") else mtype
        await handle_audio(ctx, data, media.get("mime_type") or mime, kind)
        return

    # Documents: audio/video files are transcribed; text documents are analysed.
    filename = media.get("filename") or "document"
    mime = (media.get("mime_type") or "").split(";")[0].strip()
    caption = (media.get("caption") or "").strip() or None
    if mime.startswith(("audio/", "video/")):
        data, dl_mime = await wa.download_media(media["id"], settings.stt_max_bytes)
        await handle_audio(ctx, data, mime or dl_mime, "audio_file", filename=filename)
        return
    if kind_of(mime, filename) is None:
        await send(f"📄 I can't read *{filename}* yet. I support PDF, Word (.docx) and text files (txt, md, csv, json…).")
        return
    data, mime2 = await wa.download_media(media["id"], settings.doc_max_bytes)
    await handle_document(ctx, data, mime or mime2, filename, caption)
