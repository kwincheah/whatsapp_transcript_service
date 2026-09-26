import io

import pytest
from docx import Document

from app import pipeline
from app.documents import DocumentError, extract_text, kind_of
from tests.conftest import FakeAI


def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF with one line of Helvetica text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content_id = len(objs)
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def make_docx() -> bytes:
    d = Document()
    d.add_paragraph("Contract between A and B")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Fee", "RM 5,000"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_kind_detection():
    assert kind_of("application/pdf", "x") == "PDF"
    assert kind_of("", "Report.PDF") == "PDF"
    assert kind_of("application/octet-stream", "notes.md") == "Text"
    assert kind_of("application/zip", "a.zip") is None


def test_extract_pdf_docx_text():
    ex = extract_text(make_pdf(["Hello page one of the report", "Second page with more words"]), "application/pdf", "a.pdf", 10_000)
    assert ex.kind == "PDF" and ex.pages == 2
    assert "Hello page one of the report" in ex.text and "Second page with more words" in ex.text
    ex = extract_text(make_docx(), "", "c.docx", 10_000)
    assert "Contract between A and B" in ex.text and "Fee | RM 5,000" in ex.text
    assert extract_text("héllo".encode(), "text/plain", "a.txt", 100).text == "héllo"
    with pytest.raises(DocumentError):
        extract_text(b"garbage", "application/pdf", "bad.pdf", 100)
    with pytest.raises(DocumentError):
        extract_text(b"x", "application/zip", "a.zip", 100)


async def test_document_reply_with_question(ctx_factory):
    ctx, sent = ctx_factory()
    await pipeline.handle_document(ctx, make_pdf(["Revenue grew 10% in the third quarter of 2026"]), "application/pdf", "q3.pdf", "Did revenue grow?")
    call = ctx.ai.doc_calls[0]
    assert call["question"] == "Did revenue grow?" and call["truncated"] is False
    out = sent[-1]
    assert out.startswith("📄 *Quarterly Report*\nq3.pdf · PDF · 1 page")
    assert "❓ *Did revenue grow?*\nYes, 10%." in out
    assert "💡 *Summary*\nRevenue grew." in out and "• Revenue +10%" in out
    assert "Analysis deepseek-v4-flash 1.20s" in out and "12.0k tokens in" in out and "$0.0040" in out
    assert ctx.store.search("60111", "revenue")[0].kind == "document"


async def test_long_document_truncated_with_ack(ctx_factory):
    ctx, sent = ctx_factory(doc_max_input_chars=30_000)
    text = ("lorem ipsum dolor " * 5000).encode()
    await pipeline.handle_document(ctx, text, "text/plain", "big.txt", None)
    assert ctx.ai.doc_calls[0]["truncated"] is True
    assert len(ctx.ai.doc_calls[0]["text"]) == 30_000
    assert sent[0].startswith("📄 Reading *big.txt*")
    assert "⚠️ Long document: analysed the first ~33%." in sent[-1]


async def test_empty_and_unsupported_documents(ctx_factory):
    ctx, sent = ctx_factory(ocr_enabled=False)
    await pipeline.handle_document(ctx, make_pdf([""]), "application/pdf", "scan.pdf", None)
    assert "couldn't find any text" in sent[-1] and ctx.ai.doc_calls == []
    await pipeline.handle_document(ctx, b"PK..", "application/zip", "a.zip", None)
    assert "I can read PDF" in sent[-1]


# ---------- OCR ----------

def test_scanned_page_detection_and_merge():
    ex = extract_text(make_pdf(["Real text on page one of the report", "", "x"]), "application/pdf", "m.pdf", 10_000)
    assert ex.scanned_pages == [1, 2]
    merged = ex.with_ocr({1: "scanned words"})
    assert merged.text.split("\n\n") == ["Real text on page one of the report", "scanned words", "x"]


def test_render_pages_produces_jpegs():
    from app.documents import render_pages

    imgs = render_pages(make_pdf(["a", "b"]), [1], max_side=800)
    assert len(imgs) == 1 and imgs[0][:2] == b"\xff\xd8"
    from PIL import Image
    assert max(Image.open(io.BytesIO(imgs[0])).size) == 800


async def test_fully_scanned_pdf_is_ocrd(ctx_factory):
    ctx, sent = ctx_factory()
    await pipeline.handle_document(ctx, make_pdf(["", ""]), "application/pdf", "scan.pdf", None)
    assert sent[0] == "🔍 *scan.pdf* has scanned pages. Reading 2 with OCR…"
    assert ctx.ai.ocr_calls == [2]
    assert "OCR text of scanned page 0\n\nOCR text of scanned page 1" in ctx.ai.doc_calls[0]["text"]
    out = sent[-1]
    assert "🔍 OCR: 2 of 2 scanned pages" in out
    assert "OCR gpt-5.6-luna 2.00s" in out and "$0.0070" in out  # OCR 0.003 + analysis 0.004


async def test_mixed_pdf_only_ocrs_empty_pages_and_respects_limit(ctx_factory):
    ctx, sent = ctx_factory(ocr_max_pages=1)
    await pipeline.handle_document(ctx, make_pdf(["Typed page with plenty of real text", "", ""]), "application/pdf", "mix.pdf", None)
    assert ctx.ai.ocr_calls == [1]
    text = ctx.ai.doc_calls[0]["text"]
    assert text.startswith("Typed page with plenty of real text\n\nOCR text of scanned page 0")
    assert "🔍 OCR: 1 of 2 scanned pages (limit 1)" in sent[-1]


async def test_ocr_failures_reported(ctx_factory):
    ai = FakeAI()
    ai.ocr_fail_pages = (0, 1)
    ctx, sent = ctx_factory(ai=ai)
    await pipeline.handle_document(ctx, make_pdf(["", ""]), "application/pdf", "bad-scan.pdf", None)
    assert "couldn't read any text from it, even with OCR" in sent[-1]
    assert ai.doc_calls == []

    ai = FakeAI()
    ai.ocr_fail_pages = (1,)
    ctx, sent = ctx_factory(ai=ai)
    await pipeline.handle_document(ctx, make_pdf(["", ""]), "application/pdf", "half.pdf", None)
    assert "🔍 OCR: 1 of 2 scanned pages, 1 failed" in sent[-1]


async def test_ocr_disabled(ctx_factory):
    ctx, sent = ctx_factory(ocr_enabled=False)
    await pipeline.handle_document(ctx, make_pdf([""]), "application/pdf", "scan.pdf", None)
    assert "OCR is turned off" in sent[-1]
    assert not hasattr(ctx.ai, "ocr_calls")


async def test_ocr_api_call(monkeypatch):
    from app.ai import AI
    from tests.conftest import make_settings

    ai = AI(make_settings())
    calls = []

    class R:
        choices = [type("C", (), {"message": type("M", (), {"content": " page text "})()})()]
        usage = type("U", (), {"prompt_tokens": 1000, "completion_tokens": 500})()

    async def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return R()

    monkeypatch.setattr(ai.openai.chat.completions, "create", fake_create)
    texts, t = await ai.ocr_pages([b"\xff\xd8a", b"\xff\xd8b"])
    assert sorted(texts, key=str) == [None, "page text"]  # one page OK, one failed
    kw = calls[0]
    assert kw["model"] == "gpt-5.6-luna" and kw["reasoning_effort"] == "none"
    assert kw["max_completion_tokens"] == 2000
    img = kw["messages"][0]["content"][1]["image_url"]
    assert img["url"].startswith("data:image/jpeg;base64,") and img["detail"] == "high"
    assert t.cost == pytest.approx((1000 * 0.20 + 500 * 1.20) / 1e6)
