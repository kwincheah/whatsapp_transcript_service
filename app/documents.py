import io
import os
from dataclasses import dataclass

TEXT_MIMES = {"application/json", "application/xml", "application/csv", "application/x-yaml"}
TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".yaml", ".yml", ".html", ".htm", ".srt", ".vtt"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentError(Exception):
    """User-facing reason a document couldn't be read."""


# A PDF page with less text than this is treated as scanned (an image of text).
SCANNED_PAGE_CHARS = 25


@dataclass
class Extracted:
    text: str
    kind: str  # "PDF", "Word", "Text"
    pages: int | None = None
    page_texts: list[str] | None = None  # PDF only: text of each page that was read

    @property
    def scanned_pages(self) -> list[int]:
        """0-based indices of PDF pages with (almost) no extractable text."""
        if not self.page_texts:
            return []
        return [i for i, t in enumerate(self.page_texts) if len(t.strip()) < SCANNED_PAGE_CHARS]

    def with_ocr(self, ocr: dict[int, str]) -> "Extracted":
        """Merge OCR text into the page order."""
        pages = [ocr.get(i, t) for i, t in enumerate(self.page_texts or [])]
        return Extracted("\n\n".join(pages), self.kind, self.pages, pages)


def kind_of(mime: str, filename: str) -> str | None:
    ext = os.path.splitext(filename.lower())[1]
    if mime == "application/pdf" or ext == ".pdf":
        return "PDF"
    if mime == DOCX_MIME or ext == ".docx":
        return "Word"
    if mime.startswith("text/") or mime in TEXT_MIMES or ext in TEXT_EXTS:
        return "Text"
    return None


def extract_text(data: bytes, mime: str, filename: str, max_chars: int) -> Extracted:
    """Extract plain text; stops reading once comfortably past max_chars."""
    kind = kind_of(mime, filename)
    if kind == "PDF":
        return _pdf(data, max_chars)
    if kind == "Word":
        return _docx(data)
    if kind == "Text":
        return Extracted(data.decode("utf-8", errors="replace"), "Text")
    raise DocumentError(
        "I can read PDF, Word (.docx) and text files (txt, md, csv, json…). "
        "Other file types aren't supported yet."
    )


def _pdf(data: bytes, max_chars: int) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("That PDF is password-protected.")
        parts, total = [], 0
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total > max_chars * 1.1:
                break
        return Extracted("\n\n".join(parts), "PDF", len(reader.pages), parts)
    except DocumentError:
        raise
    except (PdfReadError, ValueError, KeyError) as e:
        raise DocumentError("I couldn't open that PDF (it may be damaged).") from e


def _docx(data: bytes) -> Extracted:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:
        raise DocumentError("I couldn't open that Word document.") from e
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return Extracted("\n".join(parts), "Word")


def render_pages(data: bytes, indices: list[int], max_side: int = 1600) -> list[bytes]:
    """Render PDF pages to JPEG for OCR. max_side keeps small print legible without huge images."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        out = []
        for i in indices:
            page = pdf[i]
            w, h = page.get_size()  # points (1/72 inch)
            scale = min(max_side / max(w, h), 300 / 72)  # cap at 300 dpi
            image = page.render(scale=scale).to_pil().convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=85)
            out.append(buf.getvalue())
            page.close()
        return out
    finally:
        pdf.close()
