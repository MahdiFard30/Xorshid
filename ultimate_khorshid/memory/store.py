"""MemoryStore — حافظه دائمی SQLite + FTS5 (zero-dependency، مثل OpenJarvis)."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List

from ultimate_khorshid.core.registry import MemoryRegistry


@dataclass(slots=True)
class MemoryHit:
    id: int
    text: str
    source: str
    score: float
    created: str


@MemoryRegistry.register("sqlite")
class SQLiteMemory:
    """بک‌اند پیش‌فرض: SQLite با جست‌وجوی full-text."""

    def __init__(self, db_path: str = "~/.ultimate-jarvis/memory.db") -> None:
        self.path = Path(os.path.expanduser(db_path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path))
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init(self) -> None:
        c = self._conn()
        c.execute("""CREATE TABLE IF NOT EXISTS memories(
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
            source TEXT DEFAULT 'user', created TEXT DEFAULT (datetime('now','localtime')))""")
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(text, content='memories', content_rowid='id')")
            c.execute("""CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories
                         BEGIN INSERT INTO mem_fts(rowid, text) VALUES (new.id, new.text); END""")
            c.execute("""CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories
                         BEGIN INSERT INTO mem_fts(mem_fts, rowid, text) VALUES('delete', old.id, old.text); END""")
        except sqlite3.OperationalError:
            pass  # بدون FTS5
        c.commit()
        c.close()

    # -- API --
    def add(self, text: str, source: str = "user") -> int:
        c = self._conn()
        cur = c.execute("INSERT INTO memories(text, source) VALUES(?,?)", (text, source))
        c.commit()
        nid = cur.lastrowid or 0
        c.close()
        return nid

    def search(self, query: str, limit: int = 5) -> List[MemoryHit]:
        c = self._conn()
        hits: List[MemoryHit] = []
        try:
            # مسیر ۱: FTS5
            try:
                rows = c.execute(
                    "SELECT m.id, m.text, m.source, rank, m.created FROM mem_fts f "
                    "JOIN memories m ON m.id=f.rowid WHERE mem_fts MATCH ? LIMIT ?",
                    (query, limit)).fetchall()
                for r in rows:
                    hits.append(MemoryHit(id=r[0], text=r[1], source=r[2], score=float(r[3]), created=r[4]))
            except sqlite3.OperationalError:
                pass
            # مسیر ۲: LIKE (فارسی‌دوست)
            if not hits:
                words = [w for w in query.split() if len(w) > 1][:6]
                if words:
                    like = " OR ".join(["text LIKE ?"] * len(words))
                    rows = c.execute(f"SELECT id, text, source, created FROM memories WHERE {like} LIMIT ?",
                                     tuple(f"%{w}%" for w in words) + (limit,)).fetchall()
                    for r in rows:
                        hits.append(MemoryHit(id=r[0], text=r[1], source=r[2], score=0.0, created=r[3]))
        finally:
            c.close()
        try:  # ترکیب معنایی (TF-IDF): بازنویسی‌ها را هم می‌گیرد
            from ultimate_khorshid.memory.semantic import hybrid_search
            have = {h.id for h in hits}
            for s in hybrid_search(str(self.path), query, limit):
                if s["id"] not in have:
                    hits.append(MemoryHit(id=s["id"], text=str(s["text"]),
                                        source=str(s["source"]), score=float(s["score"]),
                                        created=str(s["created"])))
                    have.add(s["id"])
        except Exception:
            pass
        return hits

    def list_recent(self, limit: int = 10) -> List[MemoryHit]:
        c = self._conn()
        rows = c.execute("SELECT id, text, source, created FROM memories ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        c.close()
        return [MemoryHit(id=r[0], text=r[1], source=r[2], score=0.0, created=r[3]) for r in rows]

    def delete(self, mid: int) -> bool:
        c = self._conn()
        cur = c.execute("DELETE FROM memories WHERE id=?", (mid,))
        c.commit()
        c.close()
        return cur.rowcount > 0

    def count(self) -> int:
        c = self._conn()
        n = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        c.close()
        return n


def get_memory(db_path: str = "~/.ultimate-jarvis/memory.db") -> SQLiteMemory:
    return MemoryRegistry.create("sqlite", db_path=db_path)
