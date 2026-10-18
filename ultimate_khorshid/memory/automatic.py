"""Persistent conversation and experience memory, without extra model calls.

Only user statements become facts. Tool outcomes are evidence, never executable
instructions; replay always goes through the normal agent and tool executor.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path

from ultimate_khorshid.memory.store import SQLiteMemory
from ultimate_khorshid.security.guardrails import redact

_database = contextvars.ContextVar("memory_database", default=None)
_calls = contextvars.ContextVar("memory_calls", default=None)
_enabled = contextvars.ContextVar("memory_enabled", default=True)
_background = contextvars.ContextVar("memory_background", default="")
_locks = [threading.RLock() for _ in range(64)]


def session_lock(path, session):
    key = str(Path(path).expanduser().resolve()) + ":" + session
    return _locks[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(_locks)]


def clean(text):
    text = redact(str(text))
    return re.sub(r"(?im)((?:password|token|api[_ -]?key|رمز(?: عبور)?|توکن|کلید API)\s*[:=：]\s*)\S+",
                  r"\1[REDACTED]", text)


def scoped_path(path, scope="local"):
    path = Path(path).expanduser()
    if scope == "local":
        return str(path)
    digest = hashlib.sha256(scope.encode()).hexdigest()[:24]
    return str(path.parent / (path.stem + "-" + digest + path.suffix))


@contextmanager
def memory_context(path, enabled=True, background=""):
    calls = []
    tokens = (_database.set(path), _calls.set(calls), _enabled.set(enabled), _background.set(background))
    try:
        yield calls
    finally:
        _database.reset(tokens[0])
        _calls.reset(tokens[1])
        _enabled.reset(tokens[2])
        _background.reset(tokens[3])


def record_tool(call, result):
    calls = _calls.get()
    if calls is not None and _enabled.get():
        calls.append({"name": call.name, "arguments": clean(call.arguments)[:1200],
                      "success": bool(result.success), "output": clean(result.content)[:1200]})


def words(text):
    text = str(text).lower().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    stop = {"من", "تو", "در", "از", "به", "را", "رو", "که", "این", "اون", "است", "هست", "کن", "لطفا",
            "برای", "چی", "چیه", "the", "a", "is", "to", "my", "please", "and", "of"}
    return {w for w in re.findall(r"\w+", text) if len(w) > 1 and w not in stop}


def extract_facts(text):
    """Conservative first-person facts; replacement uses stable keys."""
    if "?" in text or "؟" in text:
        return
    patterns = [
        ("name", r"(?:اسم من|نام من|اسمم|نامم)\s+(.+)", "نام کاربر: {}"),
        ("city", r"من\s+(?:در|توی|تو)\s+(.+?)\s+زندگی می\s*کنم", "محل زندگی کاربر: {}"),
        ("color", r"رنگ مورد\s*علاقه(?: من|‌ام|م)?\s+(.+)", "رنگ موردعلاقه کاربر: {}"),
        ("name", r"my name is\s+(.+)", "User name: {}"),
        ("city", r"i live in\s+(.+)", "User city: {}"),
        ("color", r"my favou?rite colou?r is\s+(.+)", "User favorite color: {}"),
    ]
    for sentence in re.split(r"[\n.!؟?]+", text):
        sentence = sentence.strip().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
        sentence = re.sub(r"^(?:نه[،,]?|اصلاح(?: می کنم)?[:：،]?|actually[, ]*)\s*", "", sentence, flags=re.I)
        if any(w in sentence for w in ("[REDACTED", "نیست", "نمی", "اگر", "مثلا", "مثلاً", '"', '«', "don't", "not ")):
            continue
        for key, pattern, template in patterns:
            m = re.fullmatch(pattern, sentence, re.I)
            if not m:
                continue
            value = re.sub(r"\s+(?:است|هست|هستم)$", "", m.group(1)).strip()
            if value and len(value) < 100:
                yield key, template.format(value)
            break


class AutomaticMemory:
    def __init__(self, path, retention=1000):
        self.store = SQLiteMemory(path)
        self.retention = max(10, int(retention))
        with self.connection() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS conversation_turns(
                id INTEGER PRIMARY KEY, session TEXT NOT NULL, query TEXT NOT NULL,
                reply TEXT NOT NULL, tools TEXT NOT NULL, outcome TEXT NOT NULL,
                created TEXT DEFAULT (datetime('now')) )""")
            c.execute("CREATE INDEX IF NOT EXISTS turns_session ON conversation_turns(session,id)")
            c.execute("""CREATE TABLE IF NOT EXISTS learned_facts(
                key TEXT PRIMARY KEY, text TEXT NOT NULL,
                updated TEXT DEFAULT (datetime('now')))""")

    @contextmanager
    def connection(self):
        c = self.store._conn()
        try:
            with c:
                yield c
        finally:
            c.close()

    def recent(self, session, limit=8):
        with self.connection() as c:
            rows = c.execute("SELECT query,reply FROM conversation_turns WHERE session=? ORDER BY id DESC LIMIT ?",
                             (session, max(0, min(int(limit), 20)))).fetchall()
        messages = []
        for query, reply in reversed(rows):
            messages.extend([{"role": "user", "content": query[:3000]},
                             {"role": "assistant", "content": reply[:3000]}])
        return messages

    def facts(self):
        with self.connection() as c:
            return [r[0] for r in c.execute("SELECT text FROM learned_facts ORDER BY updated DESC,key LIMIT 30")]

    def recall(self, query, limit=3):
        terms = words(query)
        if not terms:
            return []
        with self.connection() as c:
            rows = c.execute("SELECT id,query,reply,tools,outcome FROM conversation_turns ORDER BY id DESC LIMIT ?",
                             (self.retention,)).fetchall()
        ranked = []
        seen = set()
        for row in rows:
            old = words(row[1])
            score = len(terms & old) / max(1, len(terms | old))
            if score < .2 or row[1] in seen:
                continue
            seen.add(row[1])
            ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], item[1][0]), reverse=True)
        return [{"query": r[1][:700], "reply": r[2][:1000], "tools": [
                    {**tool, "arguments": tool["arguments"][:400], "output": tool["output"][:400]}
                    for tool in json.loads(r[3])[-6:]],
                 "outcome": r[4]} for _, r in ranked[:limit]]

    def remember(self, session, query, reply, calls, outcome, *, learn_facts=True):
        query, reply = clean(query), clean(reply)
        with self.connection() as c:
            c.execute("INSERT INTO conversation_turns(session,query,reply,tools,outcome) VALUES(?,?,?,?,?)",
                      (session, query, reply, json.dumps(calls, ensure_ascii=False), outcome))
            for key, text in (extract_facts(query) if learn_facts else ()):
                c.execute("""INSERT INTO learned_facts(key,text) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET text=excluded.text,updated=datetime('now')""", (key, text))
            c.execute("DELETE FROM conversation_turns WHERE id NOT IN (SELECT id FROM conversation_turns ORDER BY id DESC LIMIT ?)",
                      (self.retention,))

    def status(self):
        with self.connection() as c:
            return {"database": str(self.store.path),
                    "turns": c.execute("SELECT count(*) FROM conversation_turns").fetchone()[0],
                    "facts": c.execute("SELECT count(*) FROM learned_facts").fetchone()[0]}

    def clear(self, session=None, everything=False):
        with self.connection() as c:
            if everything:
                c.execute("DELETE FROM conversation_turns")
                c.execute("DELETE FROM learned_facts")
                c.execute("DELETE FROM memories")
            elif session is not None:
                c.execute("DELETE FROM conversation_turns WHERE session=?", (session,))

    def context(self, query):
        return json.dumps({"user_facts": self.facts(), "past_experiences": self.recall(query, 2)}, ensure_ascii=False)
