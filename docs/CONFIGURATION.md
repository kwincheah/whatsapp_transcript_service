# Configuration

Every environment variable, with defaults, and the cost model.

[← Back to README](../README.md)

---

All settings are environment variables: Railway **Variables**, or a local `.env` file (see [`.env.example`](../.env.example)). Enter **values only**, with no quotes or trailing comments.

## Required

| Variable | Where to find it | Looks like |
|---|---|---|
| `WHATSAPP_TOKEN` | System User token ([setup step 5](SETUP.md#5-make-it-permanent)) | `EAA…` (~200 chars) |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp → API Setup → *Phone number ID* | `1329315093600329` |
| `WHATSAPP_VERIFY_TOKEN` | **You make it up**; enter the same value in Meta | `kc-wa-bot-7x92f` |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/api-keys) | `sk-proj-…` |
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | `sk-…` |

## Recommended

| Variable | Default | Description |
|---|---|---|
| `WHATSAPP_APP_SECRET` | *(empty: check off)* | App secret (32 chars); rejects forged webhook calls |
| `ALLOWED_SENDERS` | *(empty: anyone)* | Comma-separated numbers with country code, no `+` |

## Behaviour

| Variable | Default | Description |
|---|---|---|
| `SUMMARY_MIN_SECONDS` | `8` | Summarise audio **longer** than this |
| `KEY_POINTS_MIN_SECONDS` | `60` | Add key points for audio longer than this |
| `TRANSLATE_TO` | *(empty: off)* | Default translation language, e.g. `English`; users override it with `/lang` |
| `STT_VOCAB` | *(empty)* | Comma-separated words for every user, added to each user's `/vocab` |
| `DB_PATH` | `data/bot.db` | SQLite history for `/find` and `/stats`; set it empty to disable |

## Models

| Variable | Default | Description |
|---|---|---|
| `STT_MODEL` | `gpt-4o-mini-transcribe` | `gpt-4o-transcribe` is more accurate but slower and pricier |
| `SUMMARY_MODEL` | `deepseek-v4-flash` | At the time of writing, DeepSeek routes this to V4.1 Flash; `deepseek-flash` names it directly |
| `SUMMARY_THINKING` | `false` | DeepSeek reasoning. If you enable it, raise the token budgets a lot |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | For a proxy or a compatible provider |
| `WHATSAPP_API_VERSION` | `v23.0` | Meta Graph API version |

## OCR

| Variable | Default | Description |
|---|---|---|
| `OCR_ENABLED` | `true` | OCR scanned PDF pages |
| `OCR_MODEL` | `gpt-5.6-luna` | Any OpenAI vision model; uses `OPENAI_API_KEY` |
| `OCR_MAX_PAGES` | `20` | Maximum scanned pages OCR'd per document |
| `OCR_CONCURRENCY` | `5` | Pages processed in parallel |
| `OCR_MAX_TOKENS_PER_PAGE` | `2000` | Output cap per page |
| `OCR_IMAGE_MAX_SIDE` | `1600` | Rendered page size in px; raise it for tiny print |

## Web search

| Variable | Default | Description |
|---|---|---|
| `WEB_SEARCH_ENABLED` | `true` | Enables `/search` |
| `WEB_SEARCH_MODEL` | `gpt-5.6-luna` | OpenAI model used with the `web_search` tool |
| `WEB_SEARCH_REASONING` | `low` | Reasoning effort. The tool needs some reasoning; `low` is fast |
| `WEB_SEARCH_CONTEXT_SIZE` | `low` | How much page content each search pulls in (`low`, `medium` or `high`). Higher is more thorough, slower and pricier |
| `WEB_SEARCH_MAX_OUTPUT_TOKENS` | `1500` | Output cap, including reasoning |
| `WEB_SEARCH_COUNTRY` | *(empty)* | ISO country code, e.g. `MY`, to prefer local results |

## Limits & budgets

See [Token budgets](ARCHITECTURE.md#-token-budgets) for how these combine.

| Variable | Default |
|---|---|
| `VOICE_SUMMARY_MAX_TOKENS` | `150` |
| `VOICE_KEY_POINTS_MAX_TOKENS` | `350` |
| `TRANSLATION_MAX_TOKENS` | `4000` |
| `DOC_MAX_OUTPUT_TOKENS` | `1500` |
| `DOC_MAX_INPUT_CHARS` | `150000` |
| `DOC_MAX_BYTES` | `20971520` (20 MB) |
| `STT_MAX_BYTES` | `26214400` (25 MB) |

## Cost estimates (USD)

| Variable | Default | Basis |
|---|---|---|
| `PRICE_STT_PER_MIN` | `0.003` | gpt-4o-mini-transcribe, per audio minute |
| `PRICE_LLM_INPUT_PER_M` | `0.30` | DeepSeek Flash input (cache miss), per 1M tokens, peak rate |
| `PRICE_LLM_CACHED_INPUT_PER_M` | `0.006` | DeepSeek Flash input (cache hit), peak rate |
| `PRICE_LLM_OUTPUT_PER_M` | `1.20` | DeepSeek Flash output, peak rate |
| `PRICE_OCR_INPUT_PER_M` | `0.20` | gpt-5.6-luna input, per 1M tokens |
| `PRICE_OCR_OUTPUT_PER_M` | `1.20` | gpt-5.6-luna output, per 1M tokens |
| `PRICE_WEB_SEARCH_PER_CALL` | `0.01` | OpenAI web_search tool, per search ($10 per 1,000) |
| `PRICE_WEB_INPUT_PER_M` / `PRICE_WEB_OUTPUT_PER_M` | `0.20` / `1.20` | Tokens for the web search model |

These defaults are peak-hour rates, so estimates err on the high side, since DeepSeek halves prices off-peak. Update them from the providers' pricing pages.

> [!IMPORTANT]
> **Upgrading from an older version:** `SUMMARY_MAX_TOKENS` is no longer used. Delete it from Railway to avoid confusion; the per-task budgets above replace it.

## 💰 Costs

| Component | Rough cost |
|---|---|
| WhatsApp Cloud API | Replies inside the 24 h customer-service window are free under Meta's current pricing |
| OpenAI `gpt-4o-mini-transcribe` | ~$0.003 per audio minute |
| OpenAI web search (`/search`) | $0.01 per search + tokens: roughly **$0.01–0.02 per question** |
| OpenAI `gpt-5.6-luna` (OCR) | ~$0.20 per 1M input / $1.20 per 1M output tokens: roughly **$0.001–0.002 per scanned page** |
| DeepSeek Flash | ~$0.15–0.30 per 1M input tokens and ~$0.60–1.20 per 1M output tokens (off-peak / peak) |
| Railway | Trial credit, then the Hobby plan |

In practice, a 1-minute voice note costs about **$0.004** and a 20-page PDF about **$0.005**. Send `/stats` to see your real totals.
