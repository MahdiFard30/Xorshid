"""Chunking — تکه‌تکه کردن متن برای ingestion (مثل OpenJarvis)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class Chunk:
    text: str
    index: int
    source: str = ""


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100, source: str = "") -> List[Chunk]:
    text = text.strip()
    if not text:
        return []
    chunks: List[Chunk] = []
    start, idx = 0, 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # تلاش برای برش در مرز جمله/خط
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", "؟ ", "? ", " "):
                pos = text.rfind(sep, start + chunk_size // 2, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(Chunk(text=piece, index=idx, source=source))
            idx += 1
        start = max(end - overlap, start + 1)
        if end >= len(text):
            break
    return chunks
