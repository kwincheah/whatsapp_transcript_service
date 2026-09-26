# WhatsApp Voice Transcriber

Forward a WhatsApp voice note to the bot. It replies with:

- the transcript (**gpt-4o-mini-transcribe**)
- a one-line summary if the audio is longer than 8 s (**deepseek-v4-flash**)
- the latency and model used for each step

Example reply (audio over 8 s):

```
📝 *Transcript*
Hey, just wanted to let you know the meeting moved to 3pm tomorrow, and can you bring the Q3 deck...

💡 *Summary*
Meeting moved to 3pm tomorrow; bring Q3 deck.

_⏱ STT gpt-4o-mini-transcribe 1.42s · Summary deepseek-v4-flash 0.61s · Total 2.31s · Audio 14s_
```

For audio of 8 s or less, the Summary section and its timing are left out. If the summary call fails, the transcript is still sent, with `(unavailable)` in the Summary section.

`Total` is end to end: download from WhatsApp, then transcription, then the summary.

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

### 1. Meta app
1. At [developers.facebook.com](https://developers.facebook.com), go to **Create App** and add the **WhatsApp** product.
2. On **WhatsApp → API Setup**:
   - Meta provides a free **test number**. That's enough for personal use.
   - Under **To**, add and verify **your personal number**.
   - Copy the **Phone number ID** and **WhatsApp Business Account ID** (WABA ID).
3. Copy **App settings → Basic → App secret**.
4. Create a permanent token, since test tokens expire after 24 h:
   - Open **business.facebook.com → Settings → System users** and add an Admin user.
   - **Assign assets**: your app and your WhatsApp account.
   - **Generate token** with expiry *Never* and the permissions `whatsapp_business_messaging` and `whatsapp_business_management`.

Never register your personal number as the bot number, because it would stop working in the WhatsApp app.

### 2. Deploy (Railway)
1. **New Project → Deploy from GitHub repo** and pick this repo. Railway builds it from the `Dockerfile`.
2. Open the service box, go to **Variables**, and add the values from `.env.example`.
   - The web editor has truncated long values, so set long ones with the CLI and verify them:
     ```bash
     railway variables --set "WHATSAPP_TOKEN=EAA..."
     railway variables --kv | grep WHATSAPP
     ```
   - The startup log line `config: phone_number_id=... token_len=... app_secret_len=...` shows what the app actually received.
3. Go to the service's **Settings → Networking → Generate Domain**. This is the service's own Settings, not the project's.
4. Check that `https://<domain>/health` returns `{"ok":true}`.

To run it locally instead: `cp .env.example .env`, fill it in, run `pip install -r requirements.txt && uvicorn app.main:app --port 8000`, and expose the port with `ngrok http 8000`.

### 3. Webhook
1. Test the verify token in a browser. The page should show `hello`:
   `https://<domain>/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=hello`
2. In Meta, go to **WhatsApp → Configuration → Webhook**:
   - Callback URL: `https://<domain>/webhook`
   - Verify token: your `WHATSAPP_VERIFY_TOKEN`
   - Click **Verify and save**, then **subscribe to `messages`**.
3. Connect the app to the WhatsApp account (required for real messages to arrive):
   ```bash
   curl -X POST "https://graph.facebook.com/v23.0/<WABA_ID>/subscribed_apps" \
     -H "Authorization: Bearer <WHATSAPP_TOKEN>"
   ```
   Confirm it with `GET <WABA_ID>/phone_numbers`: the test number should show your webhook URL.
4. Send "hi" to the bot's number. It replies *"Forward me a voice message…"*. Now forward a voice note.

### Troubleshooting (Railway logs)

| Log | Fix |
|---|---|
| No `POST /webhook` when you message the bot | `messages` not subscribed, `subscribed_apps` call missing, wrong WABA ID, or the app is still in Development mode (switch it to Live) |
| `POST /webhook 401` | `WHATSAPP_APP_SECRET` wrong or truncated; it's 32 chars |
| `ignoring message from non-allowed sender N` | Put exactly `N` into `ALLOWED_SENDERS`. `16315551181` is Meta's dashboard "Test" sender, not you |
| `Graph API 401 ...` | Token expired or truncated, or `WHATSAPP_PHONE_NUMBER_ID` wrong or truncated |
| `Graph API 400 ... 131030` | Your number isn't on the API Setup **To** list |
| OpenAI / DeepSeek errors | Check the API key or credit; if the model isn't found, try `SUMMARY_MODEL=deepseek-flash` |

WhatsApp only lets the bot send free-form replies within 24 h of your last message to it. Forwarding a voice note opens that window.

## Config

| Variable | Default | |
|---|---|---|
| `STT_MODEL` | `gpt-4o-mini-transcribe` | OpenAI transcription model |
| `SUMMARY_MODEL` | `deepseek-v4-flash` | DeepSeek chat model |
| `SUMMARY_MIN_SECONDS` | `8` | Summarise only when the audio is longer than this |
| `SUMMARY_MAX_TOKENS` | `400` | Token budget for the summary call (includes any model reasoning; the prompt keeps the summary to one line) |
| `ALLOWED_SENDERS` | *(anyone)* | Comma-separated numbers allowed to use the bot |

## Dev

```bash
pip install -r requirements-dev.txt
pytest
```
