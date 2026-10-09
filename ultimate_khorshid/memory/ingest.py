"""Ingest — خواندن فایل/پوشه و ذخیره در حافظه."""

from __future__ import annotations

import os
from pathlib import Path
from ultimate_khorshid.memory.chunking import chunk_text
from ultimate_khorshid.memory.store import get_memory

TEXT_EXTS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml",
             ".html", ".csv", ".log", ".rst", ".java", ".go", ".rs", ".c", ".cpp"}


def ingest_file(path: str, db_path: str = "~/.ultimate-jarvis/memory.db") -> int:
    fp = Path(os.path.expanduser(path))
    if not fp.exists() or fp.stat().st_size > 2_000_000:
        return 0
    text = fp.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk_text(text, source=str(fp))
    mem = get_memory(db_path)
    for ch in chunks:
        mem.add(f"[{fp.name} #{ch.index}] {ch.text}", source=f"doc:{fp.name}")
    return len(chunks)


def ingest_directory(path: str, db_path: str = "~/.ultimate-jarvis/memory.db",
                     exts: set | None = None) -> int:
    base = Path(os.path.expanduser(path))
    exts = exts or TEXT_EXTS
    total = 0
    for fp in base.rglob("*"):
        if fp.is_file() and fp.suffix.lower() in exts and fp.stat().st_size < 1_000_000:
            if any(part in {".git", "node_modules", "__pycache__", ".venv"} for part in fp.parts):
                continue
            total += ingest_file(str(fp), db_path)
    return total
