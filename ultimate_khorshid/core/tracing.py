"""Observability سبک با SQLite — trace/span برای هر اجرا (LLM calls، tool calls، latency).

بدون وابستگی. برای Langfuse/OTel مسیر ارتقا در README مستند شده.
استفاده: tracer.start_trace(...) + tracer.span(...) یا contextvar خودکار در runtime.
"""

from __future__ import annotations

import contextvars
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def default_db() -> Path:
    p = Path(os.path.expanduser("~/.ultimate-jarvis/traces.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class Span:
    def __init__(self, tracer: "Tracer", trace_id: str, name: str,
                 kind: str = "tool", attrs: Optional[Dict[str, Any]] = None) -> None:
        self._t = tracer
        self.trace_id = trace_id
        self.name = name
        self.kind = kind
        self.attrs = dict(attrs or {})
        self.t0 = time.time()
        self.status = "ok"
        self.error = ""

    def set(self, **attrs: Any) -> "Span":
        self.attrs.update(attrs)
        return self

    def fail(self, err: str) -> "Span":
        self.status = "error"
        self.error = str(err)[:500]
        return self

    def __enter__(self) -> "Span":
        return self

    def __exit__(self, *exc: Any) -> None:
        if exc[0] is not None:
            self.fail(repr(exc[1])[:500])
        self._t._end_span(self)


class Tracer:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.path = Path(os.path.expanduser(db_path)) if db_path else default_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path))
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init(self) -> None:
        c = self._conn()
        c.execute("""CREATE TABLE IF NOT EXISTS traces(
            id TEXT PRIMARY KEY, name TEXT, ts TEXT DEFAULT (datetime('now','localtime')),
            attrs TEXT DEFAULT '{}', status TEXT DEFAULT 'ok')""")
        c.execute("""CREATE TABLE IF NOT EXISTS spans(
            id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, name TEXT, kind TEXT,
            ms REAL, attrs TEXT DEFAULT '{}', status TEXT DEFAULT 'ok', error TEXT DEFAULT '')""")
        c.execute("""CREATE TABLE IF NOT EXISTS usage(
            id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, engine TEXT, model TEXT,
            tok_in INTEGER DEFAULT 0, tok_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0,
            ts TEXT DEFAULT (datetime('now','localtime')))""")
        c.commit()
        c.close()

    # -- write --
    def start_trace(self, name: str, attrs: Optional[Dict[str, Any]] = None) -> str:
        tid = uuid.uuid4().hex[:12]
        c = self._conn()
        c.execute("INSERT INTO traces(id, name, attrs) VALUES(?,?,?)",
                  (tid, name, json.dumps(attrs or {}, ensure_ascii=False)))
        c.commit()
        c.close()
        return tid

    def end_trace(self, trace_id: str, status: str = "ok") -> None:
        try:
            c = self._conn()
            c.execute("UPDATE traces SET status=? WHERE id=?", (status, trace_id))
            c.commit()
            c.close()
        except Exception:
            pass

    def span(self, trace_id: str, name: str, kind: str = "tool",
             attrs: Optional[Dict[str, Any]] = None) -> Span:
        return Span(self, trace_id, name, kind, attrs)

    def _end_span(self, s: Span) -> None:
        try:
            c = self._conn()
            c.execute("INSERT INTO spans(trace_id, name, kind, ms, attrs, status, error)"
                      " VALUES(?,?,?,?,?,?,?)",
                      (s.trace_id, s.name, s.kind, (time.time() - s.t0) * 1000,
                       json.dumps(s.attrs, ensure_ascii=False)[:4000], s.status, s.error))
            c.commit()
            c.close()
        except Exception:
            pass

    def log_usage(self, trace_id: str, engine: str, model: str,
                  tok_in: int = 0, tok_out: int = 0, cost_usd: float = 0.0) -> None:
        try:
            c = self._conn()
            c.execute("INSERT INTO usage(trace_id, engine, model, tok_in, tok_out, cost_usd)"
                      " VALUES(?,?,?,?,?,?)",
                      (trace_id, engine, model, int(tok_in), int(tok_out), float(cost_usd)))
            c.commit()
            c.close()
        except Exception:
            pass

    # -- read --
    def recent_traces(self, limit: int = 15) -> List[Dict[str, Any]]:
        c = self._conn()
        rows = c.execute(
            "SELECT id, name, ts, status FROM traces ORDER BY rowid DESC LIMIT ?",
            (limit,)).fetchall()
        c.close()
        return [{"id": r[0], "name": r[1], "ts": r[2], "status": r[3]} for r in rows]

    def trace_detail(self, trace_id: str) -> Dict[str, Any]:
        c = self._conn()
        t = c.execute("SELECT id, name, ts, attrs, status FROM traces WHERE id=?",
                      (trace_id,)).fetchone()
        spans = c.execute("SELECT name, kind, ms, attrs, status, error FROM spans"
                          " WHERE trace_id=? ORDER BY id", (trace_id,)).fetchall()
        use = c.execute("SELECT engine, model, tok_in, tok_out, cost_usd FROM usage"
                        " WHERE trace_id=?", (trace_id,)).fetchall()
        c.close()
        if not t:
            return {}
        return {"id": t[0], "name": t[1], "ts": t[2],
                "attrs": json.loads(t[3] or "{}"), "status": t[4],
                "spans": [{"name": s[0], "kind": s[1], "ms": round(s[2], 1),
                           "attrs": json.loads(s[3] or "{}"), "status": s[4],
                           "error": s[5]} for s in spans],
                "usage": [{"engine": u[0], "model": u[1], "in": u[2],
                           "out": u[3], "cost": u[4]} for u in use]}

    def cost_summary(self) -> Dict[str, Any]:
        c = self._conn()
        tot = c.execute("SELECT COALESCE(SUM(tok_in),0), COALESCE(SUM(tok_out),0),"
                        " COALESCE(SUM(cost_usd),0), COUNT(*) FROM usage").fetchone()
        by = c.execute("SELECT engine || '/' || model, COALESCE(SUM(cost_usd),0),"
                       " COUNT(*) FROM usage GROUP BY 1 ORDER BY 2 DESC").fetchall()
        c.close()
        return {"tok_in": tot[0], "tok_out": tot[1], "cost_usd": round(tot[2], 6),
                "calls": tot[3],
                "by_model": [{"model": b[0], "cost_usd": round(b[1], 6),
                              "calls": b[2]} for b in by]}

    def clear(self, keep_last: int = 0) -> int:
        c = self._conn()
        if keep_last > 0:
            ids = [r[0] for r in c.execute(
                "SELECT id FROM traces ORDER BY rowid DESC LIMIT ?", (keep_last,))]
            q = f"DELETE FROM traces WHERE id NOT IN ({','.join('?' * len(ids))})" if ids else "DELETE FROM traces"
            cur = c.execute(q, ids) if ids else c.execute(q)
            c.execute("DELETE FROM spans WHERE trace_id NOT IN (SELECT id FROM traces)")
            c.execute("DELETE FROM usage WHERE trace_id NOT IN (SELECT id FROM traces)")
        else:
            cur = c.execute("DELETE FROM traces")
            c.execute("DELETE FROM spans")
            c.execute("DELETE FROM usage")
        n = cur.rowcount
        c.commit()
        c.close()
        return n


_current: contextvars.ContextVar[Optional[Tracer]] = contextvars.ContextVar(
    "khorshid_tracer", default=None)
_current_trace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "khorshid_trace_id", default="")


def current_tracer() -> Optional[Tracer]:
    return _current.get()


def current_trace_id() -> str:
    return _current_trace.get()


@contextmanager
def use_tracer(tracer: Tracer, trace_id: str = "") -> Iterator[Tracer]:
    t1, t2 = _current.set(tracer), _current_trace.set(trace_id)
    try:
        yield tracer
    finally:
        _current.reset(t1)
        _current_trace.reset(t2)


def traced_span(name: str, kind: str = "tool",
                attrs: Optional[Dict[str, Any]] = None):
    """اسپن اختیاری: اگر tracer فعال بود ثبت می‌کند، وگرنه no-op."""
    tr, tid = _current.get(), _current_trace.get()

    @contextmanager
    def _noop() -> Iterator[None]:
        yield None

    if tr is None or not tid:
        return _noop()
    return tr.span(tid, name, kind, attrs)
