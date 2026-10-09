"""جست‌وجوی معنایی سبک (TF-IDF + کسینوس) — هیبرید با FTS5/LIKE.

بدون هیچ مدلی/وابستگی: بازنویسی سؤال (paraphrase) را بهتر از keyword خالص می‌گیرد.
مسیر ارتقا: اگر روزی sqlite-vec/chromadb خواستی، همین اینترفیس را نگه دار.

API:
    hybrid_search(db_path, query, limit) -> [(id, text, source, score, created)]
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

_TOKEN = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    toks = []
    for w in _TOKEN.findall((text or "").lower()):
        w = w.strip("ـ‌")
        if len(w) > 1:
            toks.append(w)
    # n-gram کاراکتری برای تحمل اشتباه تایپی/صرف فارسی
    grams = []
    for w in toks:
        if len(w) >= 4:
            grams.extend(w[i:i + 4] for i in range(len(w) - 3))
    return toks + grams


class TfIdfIndex:
    def __init__(self) -> None:
        self.docs: Dict[int, Counter] = {}
        self.df: Counter = Counter()
        self.n = 0

    def add(self, doc_id: int, text: str) -> None:
        tf = Counter(tokenize(text))
        self.docs[doc_id] = tf
        for t in tf:
            self.df[t] += 1
        self.n += 1

    def _idf(self, term: str) -> float:
        return math.log(1 + self.n / (1 + self.df.get(term, 0)))

    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        qtf = Counter(tokenize(query))
        if not qtf or not self.docs:
            return []
        qw = {t: (1 + math.log(c)) * self._idf(t) for t, c in qtf.items()}
        qnorm = math.sqrt(sum(v * v for v in qw.values())) or 1.0
        scored = []
        for doc_id, tf in self.docs.items():
            dot = 0.0
            dnorm2 = 0.0
            for t, c in tf.items():
                w = (1 + math.log(c)) * self._idf(t)
                dnorm2 += w * w
                if t in qw:
                    dot += w * qw[t]
            if dot > 0:
                scored.append((doc_id, dot / (math.sqrt(dnorm2) * qnorm)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


_index_cache: Dict[str, Tuple[int, TfIdfIndex]] = {}


def _load_rows(db_path: str) -> List[Tuple[int, str, str, str]]:
    p = Path(os.path.expanduser(db_path))
    if not p.exists():
        return []
    c = sqlite3.connect(str(p))
    try:
        return c.execute("SELECT id, text, source, created FROM memories").fetchall()
    except Exception:
        return []
    finally:
        c.close()


def get_index(db_path: str) -> TfIdfIndex:
    rows = _load_rows(db_path)
    key = os.path.expanduser(db_path)
    cached = _index_cache.get(key)
    if cached and cached[0] == len(rows):
        return cached[1]
    idx = TfIdfIndex()
    for i, text, _s, _c in rows:
        idx.add(i, text)
    _index_cache[key] = (len(rows), idx)
    return idx


def hybrid_search(db_path: str, query: str, limit: int = 5) -> List[Dict[str, object]]:
    """ترکیب TF-IDF + LIKE با Reciprocal Rank Fusion."""
    rows = {r[0]: r for r in _load_rows(db_path)}
    if not rows:
        return []
    tfidf_rank = [doc for doc, _ in get_index(db_path).search(query, limit * 3)]
    words = [w for w in query.split() if len(w) > 1][:6]
    like_rank: List[int] = []
    if words:
        for i, text, _s, _c in rows.values():
            if any(w in text for w in words):
                like_rank.append(i)
    rrf: Dict[int, float] = {}
    for rank, doc in enumerate(tfidf_rank):
        rrf[doc] = rrf.get(doc, 0.0) + 1.0 / (60 + rank)
    for rank, doc in enumerate(like_rank[: limit * 3]):
        rrf[doc] = rrf.get(doc, 0.0) + 1.0 / (60 + rank)
    out = []
    for doc in sorted(rrf, key=lambda d: rrf[d], reverse=True)[:limit]:
        i, text, source, created = rows[doc]
        out.append({"id": i, "text": text, "source": source,
                    "score": round(rrf[doc], 4), "created": created})
    return out
