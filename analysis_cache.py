"""Complete machine-generated results, independent of editable workspace records."""
from collections import OrderedDict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from meetflow import MODEL

_root = Path(__file__).parent
_revision = hashlib.sha256(b"".join((_root / name).read_bytes() for name in
    ("meetflow.py", "grounding.py", "review_actions.py"))).hexdigest()
_memory = OrderedDict()
_lock = threading.Lock()


def key_for(text):
    return hashlib.sha256((MODEL+"\0"+_revision+"\0"+text).encode()).hexdigest()


def memory_value(key):
    with _lock:
        value = _memory.get(key)
        if value is not None:
            _memory.move_to_end(key)
        return value


def load(key, path):
    value = memory_value(key)
    if value is None and path.is_file():
        with closing(sqlite3.connect(path)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='analysis_cache'").fetchone():
                row = db.execute("SELECT result FROM analysis_cache WHERE fingerprint=?", (key,)).fetchone()
                value = row[0] if row else None
    return json.loads(value) if value is not None else None


def remember(key, result, path):
    value = json.dumps(result,ensure_ascii=False)
    with _lock:
        _memory[key] = value
        _memory.move_to_end(key)
        if len(_memory)>32:
            _memory.popitem(last=False)
    if path.is_file():
        with closing(sqlite3.connect(path)) as db, db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='analysis_cache'").fetchone():
                db.execute("UPDATE analysis_cache SET result=? WHERE fingerprint=?", (value,key))


def save_with_meeting(db, text):
    key = key_for(text)
    value = memory_value(key)
    if value is not None:
        db.execute("INSERT OR REPLACE INTO analysis_cache VALUES(?,?)", (key,value))

