"""Security guardrails — اسکنر secret/PII، فایل حساس، دستور خطرناک، audit log."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

SECRET_RES = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{10,}"),
    re.compile(r"xox[bap]-[A-Za-z0-9-]+"),
    re.compile(r"ghp_[A-Za-z0-9]{10,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"]?[\w\-]{6,}"),
]
PII_RES = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    re.compile(r"\b09\d{9}\b"),  # موبایل ایران
    re.compile(r"\b\d{10}\b"),  # کد ملی (تقریبی)
]
SENSITIVE_FILES = (".env", "id_rsa", "id_ed25519", ".pem", "credentials",
                   "secrets", ".git-credentials", "token.json")
DANGEROUS_CMD = ("rm -rf /", "mkfs", "dd if=", ":(){:|:&};", "> /dev/sd",
                 "shutdown", "reboot", "chmod -R 777 /")


def scan_secrets(text: str) -> List[str]:
    return [f"secret:{rx.pattern[:30]}" for rx in SECRET_RES if rx.search(text)]


def scan_pii(text: str) -> List[str]:
    out = []
    for rx in PII_RES:
        if rx.search(text):
            out.append(f"pii:{rx.pattern[:30]}")
    return out


def redact(text: str) -> str:
    for rx in SECRET_RES:
        text = rx.sub("[REDACTED-SECRET]", text)
    return text


def is_sensitive_file(path: str) -> bool:
    low = path.lower()
    return any(s in low for s in SENSITIVE_FILES)


def is_dangerous_command(cmd: str) -> Tuple[bool, str]:
    for d in DANGEROUS_CMD:
        if d in cmd:
            return True, d
    return False, ""


class AuditLogger:
    def __init__(self, db: str = "~/.ultimate-jarvis/audit.db") -> None:
        self.path = Path(db).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.path))
        c.execute("""CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT,
            action TEXT, detail TEXT, allowed INTEGER)""")
        c.commit()
        c.close()

    def log(self, actor: str, action: str, detail: str = "", allowed: bool = True) -> None:
        c = sqlite3.connect(str(self.path))
        c.execute("INSERT INTO audit(ts,actor,action,detail,allowed) VALUES(?,?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), actor, action, detail[:1000], int(allowed)))
        c.commit()
        c.close()

    def recent(self, limit: int = 20):
        c = sqlite3.connect(str(self.path))
        rows = c.execute("SELECT ts,actor,action,allowed FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        c.close()
        return rows
