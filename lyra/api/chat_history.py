"""Chat history that survives restarts: the plain dicts chat.py already uses, written through
to SQLite. Reading stays in memory, so streaming a reply never waits on the disk."""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_owner (conv_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chat_message (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS chat_message_conv ON chat_message(conv_id, id);
"""


class ChatDB:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)

    def add(self, conv_id: str, message: Dict) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO chat_message(conv_id,body,created) VALUES(?,?,?)",
                               (conv_id, json.dumps(message), time.time()))
            self._conn.commit()

    def forget(self, conv_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM chat_message WHERE conv_id=?", (conv_id,))
            self._conn.execute("DELETE FROM chat_owner WHERE conv_id=?", (conv_id,))
            self._conn.commit()

    def set_owner(self, conv_id: str, user_id: int) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO chat_owner(conv_id,user_id) VALUES(?,?)", (conv_id, user_id))
            self._conn.commit()

    def owners(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._conn.execute("SELECT conv_id,user_id FROM chat_owner").fetchall())

    def messages(self) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        with self._lock:
            for conv, body in self._conn.execute("SELECT conv_id,body FROM chat_message ORDER BY id"):
                out.setdefault(conv, []).append(json.loads(body))
        return out


class _Log(list):
    """One conversation. append() also saves the message."""

    def __init__(self, conv_id: str, db: ChatDB, items: Iterable = ()):
        super().__init__(items)
        self.conv_id, self.db = conv_id, db

    def append(self, message) -> None:
        super().append(message)
        self.db.add(self.conv_id, message)


class Conversations(dict):
    """{conversation id: messages}, as chat.py expects."""

    def __init__(self, db: ChatDB):
        super().__init__()
        self.db = db
        for conv, msgs in db.messages().items():
            super().__setitem__(conv, _Log(conv, db, msgs))

    def __setitem__(self, conv_id, messages) -> None:
        log = _Log(conv_id, self.db)
        super().__setitem__(conv_id, log)
        for m in messages:
            log.append(m)

    def pop(self, conv_id, default=None):
        self.db.forget(conv_id)
        return super().pop(conv_id, default)


class Owners(dict):
    """{conversation id: user id}."""

    def __init__(self, db: ChatDB):
        super().__init__(db.owners())
        self.db = db

    def __setitem__(self, conv_id, user_id) -> None:
        super().__setitem__(conv_id, user_id)
        self.db.set_owner(conv_id, user_id)

    def setdefault(self, conv_id, user_id: Optional[int] = None):
        if conv_id not in self:
            self[conv_id] = user_id
        return self[conv_id]
