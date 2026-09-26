import io
import os
from dataclasses import dataclass

TEXT_MIMES = {"application/json", "application/xml", "application/csv", "application/x-yaml"}
TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".yaml", ".yml", ".html", ".htm", ".srt", ".vtt"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentError(Exception):
    """User-facing reason a document couldn't be read."""


@dataclass
class Extracted:
    text: str
    kind: str  # "PDF", "Word", "Text"
    pages: int | None = None


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
        return Extracted("\n\n".join(parts), "PDF", len(reader.pages))
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
