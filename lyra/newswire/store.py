"""The newswire's store: one SQLite file with a full-text index (FTS5), so searching millions of
headlines with filters stays fast on the NAS.

Each row is a headline, a short summary where the source gives one, and the link to the
publisher. Full article text is never fetched or stored (republishing it is a copyright problem).
Tags are stored as ",a,b," strings so a filter is one indexed LIKE '%,x,%'.
"""
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from lyra.market.config import DATA_DIR

DB_PATH = Path(DATA_DIR) / "newswire.db"
KEEP_DAYS = 400   # older rows are pruned so the file can't fill the disk

SCHEMA = """
CREATE TABLE IF NOT EXISTS wire (
  id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, summary TEXT DEFAULT '',
  source TEXT DEFAULT '', country TEXT DEFAULT '', language TEXT DEFAULT '', kind TEXT DEFAULT 'news',
  topics TEXT DEFAULT ',', tickers TEXT DEFAULT ',', people TEXT DEFAULT ',', via TEXT DEFAULT '',
  published REAL NOT NULL, fetched REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS wire_published ON wire(published DESC);
CREATE INDEX IF NOT EXISTS wire_kind ON wire(kind, published DESC);
CREATE INDEX IF NOT EXISTS wire_country ON wire(country, published DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS wire_fts USING fts5(title, summary, content='wire', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS wire_ai AFTER INSERT ON wire BEGIN
  INSERT INTO wire_fts(rowid, title, summary) VALUES (new.rowid, new.title, new.summary); END;
CREATE TRIGGER IF NOT EXISTS wire_ad AFTER DELETE ON wire BEGIN
  INSERT INTO wire_fts(wire_fts, rowid, title, summary) VALUES ('delete', old.rowid, old.title, old.summary); END;
CREATE TABLE IF NOT EXISTS wire_runs (source TEXT PRIMARY KEY, last_ok REAL, last_error TEXT, added INTEGER DEFAULT 0);
"""

COLUMNS = ("id", "url", "title", "summary", "source", "country", "language", "kind", "topics", "tickers",
           "people", "via", "published", "fetched")
PUBLIC = ("id", "url", "title", "summary", "source", "country", "language", "kind", "topics", "tickers", "people",
          "published")


def _tags(values: Iterable[str]) -> str:
    vals = sorted({v.strip() for v in values if v and v.strip() and "," not in v})
    return "," + ",".join(vals) + "," if vals else ","


def _untag(s: str) -> List[str]:
    return [v for v in (s or "").split(",") if v]


def fts_query(text: str) -> str:
    """User text as a safe FTS5 query: every word must appear (prefix match on the last one).
    Quotes and operators are stripped, so a search can never be a syntax error."""
    words = [w for w in "".join(c if c.isalnum() or c in " -'" else " " for c in text).split() if len(w) > 1][:12]
    if not words:
        return ""
    return " ".join(f'"{w}"' for w in words[:-1]) + (" " if len(words) > 1 else "") + f'"{words[-1]}"*'


class WireStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)

    def add(self, items: List[Dict]) -> int:
        """Insert new items; ones already stored (same URL) are skipped. Returns how many were new."""
        now = time.time()
        rows = []
        # Journals often date papers ahead of release; nothing is stored as newer than now.
        for it in items:
            rows.append((it["id"], it["url"], it["title"][:400], (it.get("summary") or "")[:600], it.get("source", "")[:120],
                         (it.get("country") or "")[:2].upper(), (it.get("language") or "")[:12].lower(), it.get("kind", "news"),
                         _tags(it.get("topics", [])), _tags(it.get("tickers", [])), _tags(it.get("people", [])),
                         it.get("via", "")[:40], min(float(it.get("published") or now), now), now))
        with self._lock:
            # rowcount counts the wire rows only (not the search-index rows the trigger adds).
            cur = self._conn.executemany(f"INSERT OR IGNORE INTO wire ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})", rows)
            self._conn.commit()
            return max(cur.rowcount, 0)

    def run(self, source: str, added: int = 0, error: str = ""):
        with self._lock:
            if error:
                self._conn.execute("INSERT INTO wire_runs(source,last_error) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET last_error=excluded.last_error",
                                   (source, error[:200]))
            else:
                self._conn.execute("""INSERT INTO wire_runs(source,last_ok,last_error,added) VALUES(?,?,'',?)
                                      ON CONFLICT(source) DO UPDATE SET last_ok=excluded.last_ok,last_error='',added=wire_runs.added+excluded.added""",
                                   (source, time.time(), added))
            self._conn.commit()

    def _where(self, f: Dict):
        sql, params = ["1=1"], []
        if f.get("q"):
            q = fts_query(f["q"])
            if q:
                sql.append("wire.rowid IN (SELECT rowid FROM wire_fts WHERE wire_fts MATCH ?)")
                params.append(q)
        for col in ("kind", "country", "language"):
            if f.get(col):
                vals = [v for v in str(f[col]).split(",") if v][:20]
                sql.append(f"wire.{col} IN ({','.join('?' * len(vals))})")
                params += [v.upper() if col == "country" else v.lower() for v in vals]
        for col in ("topics", "tickers", "people"):
            if f.get(col):
                sql.append(f"wire.{col} LIKE ?")
                v = f[col].upper() if col == "tickers" else f[col]
                params.append(f"%,{v},%")
        if f.get("source"):
            sql.append("wire.source LIKE ?")
            params.append(f"%{f['source']}%")
        if f.get("since"):
            sql.append("wire.published >= ?")
            params.append(float(f["since"]))
        if f.get("until"):
            sql.append("wire.published <= ?")
            params.append(float(f["until"]))
        return " AND ".join(sql), params

    def search(self, f: Dict, limit: int = 50, offset: int = 0) -> Dict:
        where, params = self._where(f)
        with self._lock:
            rows = self._conn.execute(f"SELECT {','.join(PUBLIC)} FROM wire WHERE {where} ORDER BY published DESC LIMIT ? OFFSET ?",
                                      (*params, limit, offset)).fetchall()
            total = self._conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM wire WHERE {where} LIMIT 100000)", params).fetchone()[0]
        out = []
        for r in rows:
            d = dict(r)
            for k in ("topics", "tickers", "people"):
                d[k] = _untag(d[k])
            out.append(d)
        return {"total": total, "total_capped": total >= 100000, "results": out}

    def facets(self, f: Dict, top: int = 30) -> Dict:
        """Counts for the filter panel, over the last 30 days of whatever the other filters match."""
        f = {**f, "since": f.get("since") or time.time() - 30 * 86400}
        where, params = self._where(f)
        out: Dict = {}
        with self._lock:
            for col in ("kind", "country", "language"):
                out[col] = [{"value": r[0], "count": r[1]} for r in self._conn.execute(
                    f"SELECT {col}, COUNT(*) c FROM wire WHERE {where} AND {col}!='' GROUP BY {col} ORDER BY c DESC LIMIT ?", (*params, top))]
            for col in ("topics", "tickers"):
                counts: Dict[str, int] = {}
                for (tags,) in self._conn.execute(f"SELECT {col} FROM wire WHERE {where} AND {col}!=',' ORDER BY published DESC LIMIT 20000", params):
                    for t in _untag(tags):
                        counts[t] = counts.get(t, 0) + 1
                out[col] = [{"value": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])[:top]]
        return out

    def stats(self) -> Dict:
        now = time.time()
        with self._lock:
            c = self._conn
            total = c.execute("SELECT COUNT(*) FROM wire").fetchone()[0]
            day = c.execute("SELECT COUNT(*) FROM wire WHERE fetched >= ?", (now - 86400,)).fetchone()[0]
            kinds = dict(c.execute("SELECT kind, COUNT(*) FROM wire GROUP BY kind").fetchall())
            countries = c.execute("SELECT COUNT(DISTINCT country) FROM wire WHERE country!=''").fetchone()[0]
            languages = c.execute("SELECT COUNT(DISTINCT language) FROM wire WHERE language!=''").fetchone()[0]
            sources = c.execute("SELECT COUNT(DISTINCT source) FROM wire").fetchone()[0]
            runs = [dict(r) for r in c.execute("SELECT source, last_ok, last_error, added FROM wire_runs ORDER BY source")]
        return {"articles": total, "added_last_24h": day, "by_kind": kinds, "countries": countries,
                "languages": languages, "publishers": sources, "feeds": runs}

    def prune(self, keep_days: int = KEEP_DAYS) -> int:
        with self._lock:
            n = self._conn.execute("DELETE FROM wire WHERE published < ?", (time.time() - keep_days * 86400,)).rowcount
            self._conn.commit()
        return n


_store: Optional[WireStore] = None


def get_wire() -> WireStore:
    global _store
    if _store is None:
        _store = WireStore()
    return _store
