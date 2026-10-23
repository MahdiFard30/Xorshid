"""Append-only revision history; current-value tables are never the archive."""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time


def safe(value):
    if isinstance(value,float) and not math.isfinite(value):return {'invalid_float':repr(value)}
    if isinstance(value,dict):return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [safe(v) for v in value]
    return value


class Archive:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.touch(mode=0o600,exist_ok=True)
        with sqlite3.connect(self.path,timeout=10) as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS revisions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,identity TEXT,
                recorded_utc REAL,sha256 TEXT,labels TEXT,payload TEXT);
                CREATE INDEX IF NOT EXISTS revision_identity ON revisions(kind,identity,id);''')

    def save(self,kind,identity,value,labels=None,seed=False):
        raw=json.dumps(safe(value),sort_keys=True,ensure_ascii=False,allow_nan=False)
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with sqlite3.connect(self.path,timeout=10) as con:
            con.execute('BEGIN IMMEDIATE')
            last=con.execute('SELECT sha256 FROM revisions WHERE kind=? AND identity=? ORDER BY id DESC LIMIT 1',
                             (kind,str(identity))).fetchone()
            if seed and last:return False
            if last and last[0]==digest:return False
            con.execute('INSERT INTO revisions(kind,identity,recorded_utc,sha256,labels,payload) VALUES(?,?,?,?,?,?)',
                        (kind,str(identity),time.time(),digest,json.dumps(safe(labels or {}),sort_keys=True),raw))
        return True

    def backup(self,target):
        target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as source,sqlite3.connect(target) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Archive backup verification failed')
        return target
