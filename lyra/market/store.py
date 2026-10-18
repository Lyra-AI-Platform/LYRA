"""SQLite storage for the market expert: HTTP cache, news articles,
predictions, learned weights and the mistake log."""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from lyra.market.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY, body TEXT, fetched_at REAL
);
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY, ticker TEXT, title TEXT, source TEXT, url TEXT,
    published REAL, summary TEXT, full_text TEXT, sentiment REAL, fetched_at REAL
);
CREATE INDEX IF NOT EXISTS idx_articles_ticker ON articles(ticker, published);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, created_at REAL, price REAL,
    horizon_days INTEGER, features TEXT, p_boom REAL, p_bust REAL, action TEXT,
    evaluated INTEGER DEFAULT 0, outcome_return REAL, outcome TEXT, evaluated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_predictions_open ON predictions(evaluated, created_at);
CREATE TABLE IF NOT EXISTS weights (
    model TEXT PRIMARY KEY, data TEXT, updated_at REAL
);
CREATE TABLE IF NOT EXISTS equity (
    ts REAL, equity REAL, invested REAL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, ticker TEXT, side TEXT, shares REAL,
    price REAL, realized_pnl REAL
);
CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_id INTEGER, ticker TEXT,
    predicted TEXT, actual TEXT, outcome_return REAL, blamed_factors TEXT, created_at REAL
);
"""


class MarketStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql: str, params=()) -> List[Dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # HTTP cache
    def cache_get(self, url: str, max_age: float) -> Optional[str]:
        rows = self._all("SELECT body, fetched_at FROM http_cache WHERE url=?", (url,))
        if rows and time.time() - rows[0]["fetched_at"] < max_age:
            return rows[0]["body"]
        return None

    def cache_put(self, url: str, body: str):
        self._exec("INSERT OR REPLACE INTO http_cache VALUES (?,?,?)", (url, body, time.time()))

    # Articles
    def save_article(self, a: Dict):
        self._exec(
            """INSERT INTO articles VALUES (:id,:ticker,:title,:source,:url,:published,:summary,
               :full_text,:sentiment,:fetched_at)
               ON CONFLICT(id) DO UPDATE SET
                 full_text=COALESCE(NULLIF(excluded.full_text,''), articles.full_text),
                 sentiment=excluded.sentiment""",
            {"full_text": "", "fetched_at": time.time(), **a},
        )

    def get_article(self, article_id: str) -> Optional[Dict]:
        rows = self._all("SELECT * FROM articles WHERE id=?", (article_id,))
        return rows[0] if rows else None

    def list_articles(self, ticker: str = "", query: str = "", since: float = 0, limit: int = 50) -> List[Dict]:
        sql = "SELECT id,ticker,title,source,url,published,summary,sentiment, length(full_text) AS text_length FROM articles WHERE published>=?"
        params: list = [since]
        if ticker:
            sql += " AND ticker=?"
            params.append(ticker.upper())
        if query:
            sql += " AND (title LIKE ? OR summary LIKE ? OR full_text LIKE ?)"
            params += [f"%{query}%"] * 3
        sql += " ORDER BY published DESC LIMIT ?"
        params.append(limit)
        return self._all(sql, params)

    # Predictions
    def save_prediction(self, p: Dict) -> int:
        cur = self._exec(
            """INSERT INTO predictions (ticker,created_at,price,horizon_days,features,p_boom,p_bust,action)
               VALUES (?,?,?,?,?,?,?,?)""",
            (p["ticker"], p.get("created_at", time.time()), p["price"], p["horizon_days"],
             json.dumps(p["features"]), p["p_boom"], p["p_bust"], p["action"]),
        )
        return cur.lastrowid

    def due_predictions(self, now: Optional[float] = None) -> List[Dict]:
        now = now or time.time()
        rows = self._all("SELECT * FROM predictions WHERE evaluated=0 AND created_at + horizon_days*86400 <= ?", (now,))
        for r in rows:
            r["features"] = json.loads(r["features"])
        return rows

    def mark_evaluated(self, pid: int, ret: float, outcome: str):
        self._exec("UPDATE predictions SET evaluated=1, outcome_return=?, outcome=?, evaluated_at=? WHERE id=?",
                   (ret, outcome, time.time(), pid))

    def prediction_stats(self) -> Dict:
        rows = self._all("""SELECT COUNT(*) AS total, SUM(evaluated) AS evaluated,
                            SUM(CASE WHEN evaluated=1 AND (
                                  (action='BUY' AND outcome='boom') OR (action='SELL' AND outcome='bust') OR
                                  (action='HOLD' AND outcome='flat')) THEN 1 ELSE 0 END) AS correct
                            FROM predictions""")[0]
        return {k: (v or 0) for k, v in rows.items()}

    def history(self, ticker: str, limit: int = 20) -> List[Dict]:
        return self._all("""SELECT id,created_at,price,p_boom,p_bust,action,evaluated,outcome_return,outcome
                            FROM predictions WHERE ticker=? ORDER BY created_at DESC LIMIT ?""", (ticker.upper(), limit))

    # Weights
    def load_weights(self, model: str) -> Optional[Dict]:
        rows = self._all("SELECT data FROM weights WHERE model=?", (model,))
        return json.loads(rows[0]["data"]) if rows else None

    def save_weights(self, model: str, data: Dict):
        self._exec("INSERT OR REPLACE INTO weights VALUES (?,?,?)", (model, json.dumps(data), time.time()))

    # Account (fed by the AI trader so the risk guard knows where it stands)
    def record_equity(self, equity: float, invested: Optional[float] = None, ts: Optional[float] = None):
        self._exec("INSERT INTO equity VALUES (?,?,?)", (ts or time.time(), equity, invested))

    def equity_rows(self, since: float = 0) -> List[Dict]:
        return self._all("SELECT * FROM equity WHERE ts>=? ORDER BY ts", (since,))

    def position(self, ticker: str) -> Dict:
        """Shares held and average cost, replayed from fills."""
        shares = cost = 0.0
        for f in self._all("SELECT side, shares, price FROM fills WHERE ticker=? ORDER BY ts, id", (ticker.upper(),)):
            if f["side"] == "buy":
                cost += f["shares"] * f["price"]
                shares += f["shares"]
            elif shares > 0:
                sold = min(f["shares"], shares)
                cost -= cost / shares * sold
                shares -= sold
        return {"shares": shares, "avg_cost": cost / shares if shares else 0.0}

    def record_fill(self, ticker: str, side: str, shares: float, price: float, ts: Optional[float] = None) -> Dict:
        ticker = ticker.upper()
        pnl = None
        if side == "sell":
            pos = self.position(ticker)
            pnl = round((price - pos["avg_cost"]) * min(shares, pos["shares"]), 2) if pos["shares"] else 0.0
        cur = self._exec("INSERT INTO fills (ts,ticker,side,shares,price,realized_pnl) VALUES (?,?,?,?,?,?)",
                         (ts or time.time(), ticker, side, shares, price, pnl))
        return {"id": cur.lastrowid, "ticker": ticker, "side": side, "realized_pnl": pnl}

    def fills(self, since: float = 0, ticker: str = "") -> List[Dict]:
        sql, params = "SELECT * FROM fills WHERE ts>=?", [since]
        if ticker:
            sql += " AND ticker=?"
            params.append(ticker.upper())
        return self._all(sql + " ORDER BY ts, id", params)

    # Mistakes
    def log_mistake(self, m: Dict):
        self._exec("""INSERT INTO mistakes (prediction_id,ticker,predicted,actual,outcome_return,blamed_factors,created_at)
                      VALUES (?,?,?,?,?,?,?)""",
                   (m["prediction_id"], m["ticker"], m["predicted"], m["actual"], m["outcome_return"],
                    json.dumps(m["blamed_factors"]), time.time()))

    def mistakes(self, limit: int = 50) -> List[Dict]:
        rows = self._all("SELECT * FROM mistakes ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            r["blamed_factors"] = json.loads(r["blamed_factors"])
        return rows


_store: Optional[MarketStore] = None


def get_store() -> MarketStore:
    global _store
    if _store is None:
        _store = MarketStore()
    return _store
