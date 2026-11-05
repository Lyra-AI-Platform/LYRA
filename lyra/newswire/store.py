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
from lyra.newswire import clusters as CL

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
CREATE TABLE IF NOT EXISTS cluster (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL, source TEXT DEFAULT '', first_seen REAL NOT NULL,
  last_seen REAL NOT NULL, stories INTEGER DEFAULT 1, outlets INTEGER DEFAULT 1, breaking_at REAL,
  topics TEXT DEFAULT ',', tickers TEXT DEFAULT ',', people TEXT DEFAULT ','
);
CREATE INDEX IF NOT EXISTS cluster_last ON cluster(last_seen DESC);
CREATE TABLE IF NOT EXISTS cluster_outlet (cluster TEXT NOT NULL, outlet TEXT NOT NULL, first_at REAL NOT NULL,
  PRIMARY KEY (cluster, outlet)) WITHOUT ROWID;
-- Stories per company per hour: Tremor, the leaderboard and the timeline read these, not the articles.
CREATE TABLE IF NOT EXISTS ticker_hour (ticker TEXT NOT NULL, hour INTEGER NOT NULL, stories INTEGER DEFAULT 0,
  PRIMARY KEY (ticker, hour)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ticker_outlet (ticker TEXT NOT NULL, hour INTEGER NOT NULL, outlet TEXT NOT NULL,
  PRIMARY KEY (ticker, hour, outlet)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ticker_hour_hour ON ticker_hour(hour);
"""
BREAKING_SHOWN = 6 * 3600   # how long a cluster keeps its Breaking badge

def safe_url(url: str) -> str:
    """Only http(s) links reach a page. A javascript: or data: link in a feed could run in a
    reader's session; anything but a plain web address comes back as ""."""
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


COLUMNS = ("id", "url", "title", "summary", "source", "country", "language", "kind", "topics", "tickers",
           "people", "via", "published", "fetched")
PUBLIC = ("id", "url", "title", "summary", "source", "country", "language", "kind", "topics", "tickers", "people",
          "published")


def _tags(values: Iterable[str]) -> str:
    vals = sorted({v.strip() for v in values if v and v.strip() and "," not in v})
    return "," + ",".join(vals) + "," if vals else ","


def _untag(s: str) -> List[str]:
    return [v for v in (s or "").split(",") if v]


STOPWORDS = set("""the and for with what whats how why who when where which that this these those from into about over
under than then them they their there here have has had was were are is be been being will would could should can may
might must not but any all our your you his her its out off one two new latest recent happening going does did doing
tell show give explain please much many more most some such also just only very really like want need make made
""".split())


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
        self._index = CL.ClusterIndex()
        self._upgrade()
        self._load_index()

    def _upgrade(self):
        """One-off data fixes, each run once (PRAGMA user_version counts them)."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            # GDELT languages used to fall back to the name's first two letters. Where that
            # could only be one language it's corrected; otherwise it's cleared, not guessed.
            for wrong, right in (("cr", "hr"), ("se", "sr"), ("bo", "bs"), ("ma", ""), ("an", "")):
                self._conn.execute("UPDATE wire SET language=? WHERE language=? AND via='GDELT'", (right, wrong))
            self._conn.execute("PRAGMA user_version=1")
            self._conn.commit()
        if version < 2:
            if "cluster" not in {r[1] for r in self._conn.execute("PRAGMA table_info(wire)")}:
                self._conn.execute("ALTER TABLE wire ADD COLUMN cluster TEXT DEFAULT ''")
            self._conn.execute("CREATE INDEX IF NOT EXISTS wire_cluster ON wire(cluster)")
            self._conn.execute("PRAGMA user_version=2")
            self._conn.commit()

    def _load_index(self):
        since = time.time() - CL.WINDOW
        for cid, title, last in self._conn.execute("SELECT id, title, last_seen FROM cluster WHERE last_seen >= ?", (since,)):
            self._index.remember(cid, CL.words(title), last)

    def backfill(self, days: int = 30, batch: int = 5000, retag=None) -> int:
        """Bring articles stored before the pipeline into it, newest two days clustered and 30 days
        counted. Safe to stop and rerun: it only takes articles with no cluster yet. Runs in the
        collector's thread between cycles, a batch at a time, so the site stays responsive.
        retag re-reads each article first, so old mistakes (Google News links counted as
        Alphabet, fake tickers) don't reach the new counts."""
        since = time.time() - days * 86400
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,url,title,summary,language,source,topics,tickers,people,published FROM wire "
                "WHERE cluster='' AND published >= ? ORDER BY published LIMIT ?", (since, batch)).fetchall()
            for r in rows:
                it = dict(r)
                if retag:
                    fixed = retag({**it, "topics": _untag(it["topics"])})
                    it.update(topics=_tags(fixed["topics"]), tickers=_tags(fixed["tickers"]), people=_tags(fixed["people"]))
                    self._conn.execute("UPDATE wire SET topics=?, tickers=?, people=? WHERE id=?",
                                       (it["topics"], it["tickers"], it["people"], it["id"]))
                self._place(it)
            self._conn.commit()
        return len(rows)

    def _place(self, it: Dict) -> None:
        """Put one stored article into its cluster and the per-company counts. Lock held by caller."""
        c, when = self._conn, it["published"]
        topics, tickers, people = _untag(it["topics"]), _untag(it["tickers"]), _untag(it["people"])
        title_words = CL.words(it["title"])
        cid = self._index.find(title_words, when) or it["id"]
        src = CL.outlet(it.get("source", ""))
        row = c.execute("SELECT topics,tickers,people,first_seen,last_seen FROM cluster WHERE id=?", (cid,)).fetchone()
        if row is None:
            c.execute("INSERT OR IGNORE INTO cluster(id,title,url,source,first_seen,last_seen,topics,tickers,people) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (cid, it["title"], it["url"], it.get("source", ""), when, when, it["topics"], it["tickers"], it["people"]))
        else:
            c.execute("UPDATE cluster SET stories=stories+1, first_seen=MIN(first_seen,?), last_seen=MAX(last_seen,?), "
                      "topics=?, tickers=?, people=? WHERE id=?",
                      (when, when, _tags(_untag(row[0]) + topics), _tags(_untag(row[1]) + tickers),
                       _tags(_untag(row[2]) + people), cid))
        if src:
            c.execute("INSERT OR IGNORE INTO cluster_outlet(cluster,outlet,first_at) VALUES(?,?,?)", (cid, src, when))
            c.execute("UPDATE cluster_outlet SET first_at=MIN(first_at,?) WHERE cluster=? AND outlet=?", (when, cid, src))
            times = [t for (t,) in c.execute("SELECT first_at FROM cluster_outlet WHERE cluster=?", (cid,))]
            c.execute("UPDATE cluster SET outlets=?, breaking_at=COALESCE(breaking_at,?) WHERE id=?",
                      (max(len(times), 1), CL.breaking_time(times), cid))
        c.execute("UPDATE wire SET cluster=? WHERE id=?", (cid, it["id"]))
        self._index.remember(cid, title_words, when)
        hour = int(when // 3600)
        for t in tickers:
            c.execute("INSERT INTO ticker_hour(ticker,hour,stories) VALUES(?,?,1) "
                      "ON CONFLICT(ticker,hour) DO UPDATE SET stories=stories+1", (t, hour))
            if src:
                c.execute("INSERT OR IGNORE INTO ticker_outlet(ticker,hour,outlet) VALUES(?,?,?)", (t, hour, src))

    def add(self, items: List[Dict]) -> int:
        """Insert new items; ones already stored (same URL) are skipped. Returns how many were new."""
        now = time.time()
        rows = []
        # Journals often date papers ahead of release; nothing is stored as newer than now.
        for it in items:
            if not safe_url(it.get("url", "")):
                continue
            rows.append((it["id"], it["url"].strip(), it["title"][:400], (it.get("summary") or "")[:600], it.get("source", "")[:120],
                         (it.get("country") or "")[:2].upper(), (it.get("language") or "")[:12].lower(), it.get("kind", "news"),
                         _tags(it.get("topics", [])), _tags(it.get("tickers", [])), _tags(it.get("people", [])),
                         it.get("via", "")[:40], min(float(it.get("published") or now), now), now))
        with self._lock:
            ids = [r[0] for r in rows]
            known = set()
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                known |= {x for (x,) in self._conn.execute(
                    f"SELECT id FROM wire WHERE id IN ({','.join('?' * len(part))})", part)}
            fresh = {}
            for r in rows:
                if r[0] not in known:
                    fresh.setdefault(r[0], r)   # a feed can repeat an article within one batch
            self._conn.executemany(f"INSERT OR IGNORE INTO wire ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                                   list(fresh.values()))
            # Every article joins the pipeline here, so all products read the same tags and clusters.
            for r in sorted(fresh.values(), key=lambda x: x[12]):
                self._place({"id": r[0], "url": r[1], "title": r[2], "source": r[4], "topics": r[8], "tickers": r[9],
                             "people": r[10], "published": r[12]})
            self._index.forget_before(now - CL.WINDOW)
            self._conn.commit()
            return len(fresh)

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
            if not safe_url(d["url"]):   # stored before links were checked
                continue
            for k in ("topics", "tickers", "people"):
                d[k] = _untag(d[k])
            out.append(d)
        return {"total": total, "total_capped": total >= 100000, "results": out}

    def relevant(self, text: str, f: Dict, limit: int = 10) -> List[Dict]:
        """Best matches for a natural-language question: its meaningful words, any of them, ranked
        by relevance (BM25) and then by date. Used to ground AI answers in real sources."""
        words = [w for w in "".join(c if c.isalnum() or c in " -" else " " for c in text.lower()).split()
                 if len(w) > 2 and w not in STOPWORDS][:16]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        where, params = self._where({k: v for k, v in f.items() if k != "q"})
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT {','.join('wire.' + c for c in PUBLIC)} FROM wire_fts JOIN wire ON wire.rowid = wire_fts.rowid
                    WHERE wire_fts MATCH ? AND {where} ORDER BY bm25(wire_fts), wire.published DESC LIMIT ?""",
                (match, *params, limit * 2)).fetchall()
        out, seen = [], set()
        for r in rows:
            d = dict(r)
            key = " ".join(d["title"].lower().split())[:120]
            if key in seen or not safe_url(d["url"]):      # syndicated under several URLs, or an unsafe link
                continue
            seen.add(key)
            for k in ("topics", "tickers", "people"):
                d[k] = _untag(d[k])
            out.append(d)
        return out[:limit]

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
        cutoff = time.time() - keep_days * 86400
        with self._lock:
            n = self._conn.execute("DELETE FROM wire WHERE published < ?", (cutoff,)).rowcount
            self._conn.execute("DELETE FROM cluster_outlet WHERE cluster IN (SELECT id FROM cluster WHERE last_seen < ?)", (cutoff,))
            self._conn.execute("DELETE FROM cluster WHERE last_seen < ?", (cutoff,))
            self._conn.execute("DELETE FROM ticker_hour WHERE hour < ?", (int(cutoff // 3600),))
            self._conn.execute("DELETE FROM ticker_outlet WHERE hour < ?", (int(cutoff // 3600),))
            self._conn.commit()
        return n

    # ── What the products read ──────────────────────────────────────────────

    def clusters(self, f: Optional[Dict] = None, limit: int = 50, by_importance: bool = False, now: Optional[float] = None) -> List[Dict]:
        """Grouped stories, newest or most important first.
        f: since, until, topics, tickers, people (one value each), channel (a Live tab)."""
        f, now = f or {}, now or time.time()
        sql, params = ["last_seen >= ?"], [f.get("since") or now - 86400]
        if f.get("until"):
            sql.append("first_seen <= ?")
            params.append(f["until"])
        channel = f.get("channel") or ""
        for col, val in (("topics", f.get("topics") or (channel if channel not in ("", "everything", "people", "markets") else "")),
                         ("tickers", f.get("tickers")), ("people", f.get("people"))):
            if val:
                sql.append(f"{col} LIKE ?")
                params.append(f"%,{val},%")
        if channel == "people":
            sql.append("people != ','")
        elif channel == "markets":
            sql.append("(tickers != ',' OR topics LIKE '%,markets,%')")
        # Importance needs every candidate scored; the newest few hundred are always enough.
        fetch = max(limit, 400) if by_importance else limit
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM cluster WHERE {' AND '.join(sql)} ORDER BY last_seen DESC LIMIT ?",
                                      (*params, fetch)).fetchall()
        out = [self._cluster(r, now) for r in rows]
        out = [c for c in out if safe_url(c["url"])]
        if by_importance:
            out.sort(key=lambda c: (c["importance"], c["last_seen"]), reverse=True)
        return out[:limit]

    @staticmethod
    def _cluster(r, now: float) -> Dict:
        d = dict(r)
        for k in ("topics", "tickers", "people"):
            d[k] = _untag(d[k])
        hours = max((d["last_seen"] - d["first_seen"]) / 3600, 0.25)
        breaking = bool(d["breaking_at"] and now - d["breaking_at"] < BREAKING_SHOWN)
        d.update(breaking=breaking, channels=CL.channels_for(d["topics"], d["people"], d["tickers"]),
                 importance=CL.importance(d["outlets"], d["stories"] / hours, len(d["people"]), len(d["tickers"]), breaking))
        return d

    def stories_since(self, ticker: str, since: float) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(SUM(stories),0) FROM ticker_hour WHERE ticker=? AND hour>=?",
                                     (ticker, int(since // 3600))).fetchone()
        return row[0]

    def hourly(self, ticker: str, since: float) -> Dict[int, int]:
        """{hour number: stories} for one company."""
        with self._lock:
            return dict(self._conn.execute("SELECT hour, stories FROM ticker_hour WHERE ticker=? AND hour>=? ORDER BY hour",
                                           (ticker, int(since // 3600))).fetchall())

    def activity(self, now: Optional[float] = None) -> Dict[str, Dict]:
        """For every company in the news this week: stories this hour, in 24 h and over 7 days, and
        how many separate outlets in 24 h. The leaderboard's raw material."""
        now = now or time.time()
        this_hour, day, week = int(now // 3600), int((now - 86400) // 3600), int((now - 7 * 86400) // 3600)
        out: Dict[str, Dict] = {}
        with self._lock:
            for t, hour, n in self._conn.execute("SELECT ticker,hour,stories FROM ticker_hour WHERE hour>=?", (week,)):
                a = out.setdefault(t, {"last_hour": 0, "day": 0, "week": 0, "outlets": 0})
                a["week"] += n
                if hour >= day:
                    a["day"] += n
                if hour >= this_hour - 1:
                    a["last_hour"] += n
            for t, n in self._conn.execute("SELECT ticker, COUNT(DISTINCT outlet) FROM ticker_outlet WHERE hour>=? GROUP BY ticker", (day,)):
                if t in out:
                    out[t]["outlets"] = n
        return out

    def spikes(self, ticker: str, since: float, top: int = 6) -> List[Dict]:
        """The busiest hours for a company, each with its most widely carried headline."""
        rows = sorted(self.hourly(ticker, since).items(), key=lambda x: -x[1])[:top]
        out = []
        for hour, stories in sorted(rows):
            found = self.clusters({"tickers": ticker, "since": hour * 3600, "until": (hour + 1) * 3600}, limit=1, by_importance=True,
                                  now=(hour + 1) * 3600)
            if found:
                out.append({"ts": hour * 3600, "stories": stories, "title": found[0]["title"], "url": found[0]["url"]})
        return out


_store: Optional[WireStore] = None


def get_wire() -> WireStore:
    global _store
    if _store is None:
        _store = WireStore()
    return _store
