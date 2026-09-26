# Usage & examples

Everything the bot can receive, what it replies, and every command.

[← Back to README](../README.md)

---

## 💬 What replies look like

### 🎙️ Voice note, 14 s (over 8 s → summary)

```text
📝 Transcript
Eh bro, meeting tomorrow shift to 3pm ah, bring the Q3 deck and budget numbers.

⏱ STT gpt-4o-mini-transcribe 1.12s · Audio 14s
```
```text
💡 Summary
Meeting moved to 3pm tomorrow; bring Q3 deck and budget.

⏱ Summary deepseek-v4-flash 0.58s · Total 2.04s · $0.0008
```

### 🎙️ Voice note, 95 s, with `/lang English` (over 60 s → key points)

```text
📝 Transcript
Hari ni kita kena finalise vendor list sebelum Jumaat…

⏱ STT gpt-4o-mini-transcribe 2.40s · Audio 1m 35s
```
```text
💡 Summary
Finalise the vendor list before Friday and send quotes to finance.

📌 Key points
• Finalise vendor list by Friday
• Send the three quotes to finance
• Book the venue for 12 Oct

🌐 Translation (English)
Today we need to finalise the vendor list before Friday…

⏱ Summary deepseek-v4-flash 1.90s · Total 4.71s · $0.0061
```

### 🎙️ Voice note, 4 s (8 s or less → transcript only)

```text
📝 Transcript
On my way, see you in ten.

⏱ STT gpt-4o-mini-transcribe 0.81s · Audio 4s · Total 1.20s · $0.0002
```

### 📄 PDF with the caption *"Did revenue grow?"*

```text
📄 Q3 Financial Results Summary
Q3_report.pdf · PDF · 12 pages

❓ Did revenue grow?
Yes. Revenue grew 10% year on year to RM 4.2M.

💡 Summary
The report covers Q3 performance: revenue up 10%, margins stable, and a cost-reduction plan for Q4.

📌 Key points
• Revenue RM 4.2M (+10% YoY)
• Operating margin 18%, unchanged
• Q4 target: cut logistics costs by 5%
• Board review due 15 Oct

⏱ Extract 0.21s · Analysis deepseek-v4-flash 3.10s · Total 3.62s · 9.4k tokens in · $0.0034
```

### 🔍 Scanned PDF (e.g. a signed contract photographed page by page)

```text
🔍 contract_signed.pdf has scanned pages. Reading 6 with OCR…
```
```text
📄 Tenancy Agreement, Unit 12-3
contract_signed.pdf · PDF · 6 pages
🔍 OCR: 6 of 6 scanned pages

💡 Summary
Two-year tenancy from 1 Nov 2026 at RM 2,300/month, with a two-month deposit.

📌 Key points
• Rent RM 2,300, due on the 7th of each month
• Deposit RM 4,600 + utilities RM 500
• 2-month notice for early termination
• Signed 20 Sep 2026

⏱ Extract 0.08s · OCR gpt-5.6-luna 4.80s · Analysis deepseek-v4-flash 2.30s · Total 7.61s · 5.1k tokens in · $0.0093
```

### 🌍 Web search: `/search latest OPR rate Malaysia`

```text
🔎 latest OPR rate Malaysia
Bank Negara Malaysia kept the Overnight Policy Rate at *2.75%* at its September 2026 meeting, citing stable inflation and steady growth. The next MPC meeting is on 6 Nov 2026.

Sources
1. Monetary Policy Statement – Bank Negara Malaysia
https://www.bnm.gov.my/-/monetary-policy-statement-...
2. BNM holds OPR at 2.75% – The Edge Malaysia
https://theedgemalaysia.com/...

⏱ Web search gpt-5.6-luna 4.12s · $0.0131
```

> [!NOTE]
> - **Total** is end to end: download, extraction or transcription, then analysis. Costs are **estimates** from token usage and your configured prices.
> - Replies **quote** your original message, so it's clear which reply belongs to which file.
> - Documents with more than about 8k tokens of text get a quick *"📄 Reading…"* message first. Documents over `DOC_MAX_INPUT_CHARS` are truncated, and the reply says what share was analysed.
> - Replies over WhatsApp's 4,096-character limit are split into numbered parts, e.g. `(1/3)`.

**Supported inputs**

| Send | What happens |
|---|---|
| 🎙️ Voice note | Transcript (+ summary / key points / translation) |
| 🎬 Video | The audio track is transcribed the same way |
| 🎵 Audio file (as a document) | mp3, m4a, wav, ogg, flac, webm |
| 📄 PDF | Text is extracted and analysed; a caption becomes a question |
| 🔍 Scanned PDF | Pages without text are OCR'd (up to `OCR_MAX_PAGES`), then analysed |
| 📝 Word `.docx` | Paragraphs and tables are extracted and analysed |
| 🗒️ Text files | txt, md, csv, tsv, json, xml, yaml, html, srt, vtt |
| 📷 Image, zip… | A polite "not supported yet" message ([roadmap](../README.md#-roadmap)) |

## ⌨️ Commands

Send these as normal WhatsApp messages to the bot:

| Command | What it does |
|---|---|
| `/help` | Shows what the bot can do |
| `/lang English` | Translates voice notes into English (any language name works) and writes document summaries in it. `/lang off` stops it, and `/lang` shows the current setting |
| `/vocab add Kwin, Petronas, KLCC` | Adds words for the transcriber to spell correctly (up to 100 per user) |
| `/vocab list` · `/vocab clear` | Shows or clears your vocabulary |
| `/search latest OPR rate Malaysia` | **Web search:** a short, current answer (about 120 words) with up to 5 source links. It uses your `/lang` language if set |
| `/find vendor quote` | Searches **your history**: past transcripts, documents and web searches. All words must match |
| `/stats` | Shows counts, audio minutes, average latency and estimated cost for the last 30 days and all time |

`/find`, `/lang`, `/vocab` and `/stats` need `DB_PATH` enabled (the default); `/search` works without it. On Railway, add a **volume** so history survives redeploys ([setup step 2.4](SETUP.md#2-deploy-on-railway)).
