"""Scheduler — زمان‌بندی تسک‌های دوره‌ای (interval/once/daily) با SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List


@dataclass(slots=True)
class Task:
    id: int
    name: str
    prompt: str
    agent: str
    every_seconds: int
    next_run: float
    enabled: bool = True


class TaskStore:
    def __init__(self, db: str = "~/.ultimate-jarvis/scheduler.db") -> None:
        self.path = Path(db).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.path))
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, prompt TEXT,
            agent TEXT DEFAULT 'computer', every_seconds INTEGER DEFAULT 3600,
            next_run REAL DEFAULT 0, enabled INTEGER DEFAULT 1)""")
        c.execute("""CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER,
            ts TEXT, ok INTEGER, output TEXT)""")
        c.commit()
        c.close()

    def add(self, name: str, prompt: str, agent: str = "computer", every_seconds: int = 3600) -> int:
        c = sqlite3.connect(str(self.path))
        cur = c.execute("INSERT INTO tasks(name,prompt,agent,every_seconds,next_run) VALUES(?,?,?,?,?)",
                        (name, prompt, agent, every_seconds, time.time() + 5))
        c.commit()
        nid = cur.lastrowid or 0
        c.close()
        return nid

    def list(self) -> List[Task]:
        c = sqlite3.connect(str(self.path))
        rows = c.execute("SELECT id,name,prompt,agent,every_seconds,next_run,enabled FROM tasks").fetchall()
        c.close()
        return [Task(*r[:6], enabled=bool(r[6])) for r in rows]

    def due(self) -> List[Task]:
        return [t for t in self.list() if t.enabled and t.next_run <= time.time()]

    def mark_run(self, t: Task, ok: bool, output: str) -> None:
        c = sqlite3.connect(str(self.path))
        c.execute("UPDATE tasks SET next_run=? WHERE id=?", (time.time() + t.every_seconds, t.id))
        c.execute("INSERT INTO runs(task_id,ts,ok,output) VALUES(?,?,?,?)",
                  (t.id, datetime.now().isoformat(timespec="seconds"), int(ok), output[:3000]))
        c.commit()
        c.close()

    def remove(self, tid: int) -> None:
        c = sqlite3.connect(str(self.path))
        c.execute("DELETE FROM tasks WHERE id=?", (tid,))
        c.commit()
        c.close()

    def toggle(self, tid: int, enabled: bool) -> None:
        c = sqlite3.connect(str(self.path))
        c.execute("UPDATE tasks SET enabled=? WHERE id=?", (int(enabled), tid))
        c.commit()
        c.close()


RunnerFn = Callable[[str, str], str]  # (prompt, agent) -> output


class TaskScheduler:
    """حلقه پس‌زمینه که تسک‌های رسیده را با runner اجرا می‌کند."""

    def __init__(self, store: TaskStore, runner: RunnerFn, poll_seconds: int = 10) -> None:
        self.store = store
        self.runner = runner
        self.poll = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="khorshid-sched")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for t in self.store.due():
                    try:
                        out = self.runner(t.prompt, t.agent)
                        self.store.mark_run(t, True, out)
                    except Exception:
                        self.store.mark_run(t, False, traceback.format_exc()[-2000:])
            except Exception:
                pass
            self._stop.wait(self.poll)
