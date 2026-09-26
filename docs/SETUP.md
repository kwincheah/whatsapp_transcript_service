# Setup guide

Step-by-step: Meta / WhatsApp Cloud API → Railway → webhook → test → permanent token. Plus local development.

[← Back to README](../README.md)

---

## 1. Meta / WhatsApp

1. Go to **[developers.facebook.com](https://developers.facebook.com) → My Apps → Create App** and add the **WhatsApp** product.
2. Open **WhatsApp → API Setup**:
   - Meta gives you a free **test number** (e.g. `+1 555 …`). **That's all you need for personal use.**
   - Under **To → Manage phone number list**, add **your personal number** and confirm it with the code WhatsApp sends.
   - Note down the **Phone number ID** and the **WhatsApp Business Account ID (WABA ID)**. These are long numeric IDs, *not* phone numbers.
3. Go to **App settings → Basic** and copy the **App secret** (32 characters).
4. **Optional, recommended:** set **App Mode** to **Live**. This needs a Privacy Policy URL and a category.

> [!WARNING]
> Don't register your **personal** number with **"Add phone number"**. Registering it on the Cloud API removes it from the WhatsApp app.

## 2. Deploy on Railway

1. Go to **[railway.com](https://railway.com) → New Project → Deploy from GitHub repo** and pick this repository. Railway builds from the `Dockerfile`, and the first deploy fails until the variables are set.
2. **Set the variables** with the **Railway CLI**, because the web editor has been seen truncating long values:
   ```bash
   npm i -g @railway/cli && railway login && railway link
   railway variables --set "WHATSAPP_TOKEN=EAA..."   # repeat for each variable
   railway variables --kv                             # verify
   ```
3. **Create a public URL.** Click the **service box**, then open **Settings → Networking → Generate Domain**. Use the *service's* Settings, not the project's.
4. **Add a volume for history.** Right-click the service → **Attach volume** (or ⌘K → *volume*), with mount path **`/app/data`**. Without it, `/find` and `/stats` history resets on every deploy.
5. Check that `https://<your-domain>/health` returns `{"ok":true}`, and check the startup log:
   ```text
   config: phone_number_id=1329315093600329 token_len=212 app_secret_len=32 allowed=['60123456789']
   history: data/bot.db
   ```

## 3. Connect the webhook

1. **Test the verify token** in a browser. The page should show `hello`:
   ```text
   https://<your-domain>/webhook?hub.mode=subscribe&hub.verify_token=<YOUR_TOKEN>&hub.challenge=hello
   ```
2. In Meta, open **WhatsApp → Configuration → Webhook → Edit**:

   | Field | Value |
   |---|---|
   | Callback URL | `https://<your-domain>/webhook` |
   | Verify token | Same as `WHATSAPP_VERIFY_TOKEN` (no quotes) |

   Click **Verify and save**, then **subscribe to `messages`**.
3. **Connect the app to your WhatsApp Business Account.** Real messages won't arrive without this:
   ```bash
   curl -X POST "https://graph.facebook.com/v23.0/<WABA_ID>/subscribed_apps" \
     -H "Authorization: Bearer <WHATSAPP_TOKEN>"
   # → {"success": true}
   ```

## 4. Test it

| Send | Expected |
|---|---|
| `/help` | The command list |
| Voice note **≤ 8 s** | One message: 📝 Transcript + ⏱ |
| Voice note **> 8 s** | 📝 Transcript, then 💡 Summary |
| Voice note **> 60 s** | 📝 Transcript, then 💡 Summary + 📌 Key points |
| A PDF with a caption question | 📄 Title, ❓ Answer, 💡 Summary, 📌 Key points |
| `/stats` | Your usage so far |

## 5. Make it permanent

The API Setup token **expires after 24 hours**. Replace it with a **System User** token:

1. **[business.facebook.com](https://business.facebook.com) → Settings → Users → System users → Add**, with role *Admin*.
2. **Assign assets**: your **app** and your **WhatsApp account**, both with *Full control*.
3. **Generate token** with expiration **Never** and the permissions `whatsapp_business_messaging` and `whatsapp_business_management`.
4. `railway variables --set "WHATSAPP_TOKEN=EAA..."`

## 💻 Running locally

```bash
git clone https://github.com/kwincheah/whatsapp_transcript_service.git
cd whatsapp_transcript_service

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env        # fill it in
uvicorn app.main:app --reload --port 8000
ngrok http 8000             # use https://<id>.ngrok-free.app/webhook as the Callback URL
```

Tests use fakes, so no API keys or network are needed:

```bash
pytest
```

With Docker:

```bash
docker build -t wa-transcriber .
docker run --env-file .env -p 8000:8000 -v "$PWD/data:/app/data" wa-transcriber
```
