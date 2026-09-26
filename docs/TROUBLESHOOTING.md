# Troubleshooting

Symptoms and log lines, what causes them, and the fix.

[← Back to README](../README.md)

---

Open the **Railway logs** (service → *Deployments* → *View Logs*), send the bot a message, and look for:

| Symptom / log line | Cause | Fix |
|---|---|---|
| **No `POST /webhook`** when you message the bot | Meta isn't forwarding to you | Subscribe to `messages`, run the `subscribed_apps` call, use the **test number's** WABA ID, or switch the app to **Live** |
| `GET /webhook … 422` / `403` | Malformed test URL / verify token mismatch | Put a `&` before `hub.challenge` / use the same token in both places, with no quotes |
| `POST /webhook … 401` | App secret wrong or truncated | Copy it again; it must be exactly 32 characters |
| `ignoring message from non-allowed sender N` | Allow-list mismatch | Set `ALLOWED_SENDERS` to exactly `N`. `16315551181` is Meta's dashboard test sender |
| `Graph API 401 … Session has expired` | 24 h temporary token | [Make it permanent](SETUP.md#5-make-it-permanent) |
| `Graph API 400 … 131030` | Recipient not allowed | Add your number under **API Setup → To** |
| `unparseable analysis … finish_reason=length` | Output budget too small | Raise the matching `*_MAX_TOKENS`; keep `SUMMARY_THINKING=false` |
| `analysis failed` + `401` / `402` | DeepSeek key wrong / no balance | Fix the key or top up |
| `failed to process` + OpenAI error | OpenAI key or credit, or an unsupported audio format | Check the key; convert the audio to mp3 or m4a |
| "couldn't read any text from it, even with OCR" | Blank or unreadable scan | Try a clearer scan, or raise `OCR_IMAGE_MAX_SIDE` |
| `web search failed` in logs | Model has no web-search access, or a quota/key problem | Set `WEB_SEARCH_MODEL` to a model your account can use with `web_search`; if the error mentions reasoning, set `WEB_SEARCH_REASONING=medium` |
| `/search` finds nothing in my old notes | `/search` is **web** search | Use `/find` for your history |
| `OCR failed for a page` + `model_not_found` | `OCR_MODEL` isn't available to your OpenAI account | Set `OCR_MODEL` to a vision model you can use |
| `history disabled: can't open …` | `DB_PATH` isn't writable | Attach a volume at `/app/data`, or set `DB_PATH` empty |
| `/find` history disappears after a deploy | No volume | [Setup step 2.4](SETUP.md#2-deploy-on-railway) |

> [!TIP]
> WhatsApp only allows free-form replies within 24 h of your last message to the bot. Sending anything to it opens that window, so replies always work.
