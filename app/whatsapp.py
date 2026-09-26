import hashlib
import hmac
import logging

import httpx

from app.config import Settings

WA_TEXT_LIMIT = 4096

log = logging.getLogger("transcriber")


def _check(r: httpx.Response) -> None:
    # Meta's error body says what's wrong (bad token, wrong ID, recipient not allowed...).
    if r.is_error:
        log.error("Graph API %s %s: %s", r.status_code, r.request.url.path, r.text[:500])
    r.raise_for_status()


class WhatsApp:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.s = settings
        self.http = client
        self.base = f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        self.auth = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        meta = await self.http.get(f"{self.base}/{media_id}", headers=self.auth)
        _check(meta)
        info = meta.json()
        media = await self.http.get(info["url"], headers=self.auth)
        _check(media)
        return media.content, info.get("mime_type", "audio/ogg")

    async def send_text(
        self, to: str, body: str, reply_to: str | None = None, phone_number_id: str | None = None
    ) -> None:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body[:WA_TEXT_LIMIT]},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        r = await self.http.post(
            f"{self.base}/{phone_number_id or self.s.whatsapp_phone_number_id}/messages",
            headers=self.auth,
            json=payload,
        )
        _check(r)


def valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
