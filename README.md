# WhatsApp Voice Transcriber

Forward a WhatsApp voice note to the bot. It replies with:

- the transcript (**gpt-4o-mini-transcribe**)
- a one-line summary if the audio is longer than 8 s (**deepseek-v4-flash**)
- the latency and model used for each step

Example reply:

```
Hey, just wanted to let you know the meeting moved to 3pm tomorrow, and can you bring the Q3 deck...

*Summary:* Meeting moved to 3pm tomorrow; bring Q3 deck.

_STT gpt-4o-mini-transcribe 1.42s | Sum deepseek-v4-flash 0.61s | total 2.31s | audio 14s_
```

`total` is end to end: download from WhatsApp, then transcription, then the summary.

## How it works

```
Your WhatsApp ──forward voice note──▶ Bot number (WhatsApp Cloud API)
                                          │ webhook POST
                                          ▼
                                   this service (FastAPI)
                                   1. download media
                                   2. OpenAI STT
                                   3. DeepSeek summary (if > 8 s)
                                          │
Your WhatsApp ◀──reply (quoted)───────────┘
```

The bot is a separate number on the **WhatsApp Cloud API** (Meta's official API). You chat with it from your normal personal WhatsApp, just like any other contact. Your personal account is not automated, so there is no ban risk.

## Setup

1. **Meta app**: at [developers.facebook.com](https://developers.facebook.com) create an app (type *Business*) and add the **WhatsApp** product.
   - You can start with the free test number. Add your personal number as a recipient under *API Setup*.
   - For a permanent bot, register a real number you don't use in the WhatsApp app. Also create a **System User** token with the `whatsapp_business_messaging` permission, because test tokens expire after 24 h.
2. **Config**: run `cp .env.example .env` and fill it in. Set `ALLOWED_SENDERS` to your own number so strangers can't spend your API credits.
3. **Run**:
   ```bash
   pip install -r requirements.txt
   uvicorn app.main:app --port 8000
   # or: docker build -t wa-transcriber . && docker run --env-file .env -p 8000:8000 wa-transcriber
   ```
   Meta needs a public HTTPS URL. For local testing, use `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`. For hosting, Fly.io, Railway, Render and Cloud Run all work.
4. **Webhook**: in the app go to *WhatsApp → Configuration → Webhook*.
   - Callback URL: `https://<your-host>/webhook`
   - Verify token: your `WHATSAPP_VERIFY_TOKEN`
   - Subscribe to the **messages** field.
5. Send the bot "hi" once from your phone. After that, forward any voice note to it.

> WhatsApp only lets a business number send free-form replies within 24 h of your last message to it. Forwarding a voice note opens that window, so replies always work.

## Config

| Variable | Default | |
|---|---|---|
| `STT_MODEL` | `gpt-4o-mini-transcribe` | OpenAI transcription model |
| `SUMMARY_MODEL` | `deepseek-v4-flash` | DeepSeek chat model |
| `SUMMARY_MIN_SECONDS` | `8` | Summarise only when the audio is longer than this |
| `SUMMARY_MAX_TOKENS` | `80` | Hard cap on summary length |
| `ALLOWED_SENDERS` | *(anyone)* | Comma-separated numbers allowed to use the bot |

## Dev

```bash
pip install -r requirements-dev.txt
pytest
```
