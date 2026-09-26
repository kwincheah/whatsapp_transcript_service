"""SQLite history for /stats, /search and per-user preferences."""

import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass

log = logging.getLogger("transcriber")

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    wamid TEXT,
    sender TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,          -- voice | video | audio_file | document
    title TEXT,
    audio_seconds REAL,
    content TEXT,
    summary TEXT,
    latency REAL,
    cost REAL
);
CREATE INDEX IF NOT EXISTS items_sender_ts ON items(sender, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(title, content, summary, content='items', content_rowid='id');
CREATE TABLE IF NOT EXISTS prefs (
    sender TEXT PRIMARY KEY,
    lang TEXT,
    vocab TEXT
);
"""


@dataclass
class Hit:
    ts: float
    kind: str
    title: str | None
    snippet: str


def _fts_query(q: str) -> str:
    # Quote each word so user input can't break FTS5 syntax; words are ANDed.
    words = re.findall(r"\w+", q, re.UNICODE)
    return " ".join(f'"{w}"' for w in words)


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add(
        self, *, wamid, sender, kind, title, audio_seconds, content, summary, latency, cost
    ) -> None:
        cur = self.db.execute(
            "INSERT INTO items (wamid, sender, ts, kind, title, audio_seconds, content, summary, latency, cost)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (wamid, sender, time.time(), kind, title, audio_seconds, content, summary, latency, cost),
        )
        self.db.execute(
            "INSERT INTO items_fts (rowid, title, content, summary) VALUES (?,?,?,?)",
            (cur.lastrowid, title or "", content or "", summary or ""),
        )
        self.db.commit()

    def search(self, sender: str, query: str, limit: int = 5) -> list[Hit]:
        q = _fts_query(query)
        if not q:
            return []
        rows = self.db.execute(
            "SELECT i.ts, i.kind, i.title, snippet(items_fts, -1, '*', '*', '…', 12) AS snip"
            " FROM items_fts JOIN items i ON i.id = items_fts.rowid"
            " WHERE items_fts MATCH ? AND i.sender = ? ORDER BY i.ts DESC LIMIT ?",
            (q, sender, limit),
        ).fetchall()
        return [Hit(r["ts"], r["kind"], r["title"], " ".join(r["snip"].split())) for r in rows]

    def stats(self, sender: str, since: float) -> dict:
        r = self.db.execute(
            "SELECT COUNT(*) n,"
            " SUM(kind != 'document') voice_n, SUM(kind = 'document') doc_n,"
            " COALESCE(SUM(audio_seconds), 0) audio_s, COALESCE(SUM(cost), 0) cost,"
            " AVG(CASE WHEN kind != 'document' THEN latency END) voice_lat,"
            " AVG(CASE WHEN kind = 'document' THEN latency END) doc_lat"
            " FROM items WHERE sender = ? AND ts >= ?",
            (sender, since),
        ).fetchone()
        return dict(r)

    def prefs(self, sender: str) -> tuple[str | None, list[str]]:
        r = self.db.execute("SELECT lang, vocab FROM prefs WHERE sender = ?", (sender,)).fetchone()
        if not r:
            return None, []
        vocab = [w for w in (r["vocab"] or "").split("\n") if w]
        return r["lang"], vocab

    def set_lang(self, sender: str, lang: str | None) -> None:
        self.db.execute(
            "INSERT INTO prefs (sender, lang) VALUES (?, ?) ON CONFLICT(sender) DO UPDATE SET lang = excluded.lang",
            (sender, lang),
        )
        self.db.commit()

    def set_vocab(self, sender: str, words: list[str]) -> None:
        self.db.execute(
            "INSERT INTO prefs (sender, vocab) VALUES (?, ?) ON CONFLICT(sender) DO UPDATE SET vocab = excluded.vocab",
            (sender, "\n".join(words)),
        )
        self.db.commit()
