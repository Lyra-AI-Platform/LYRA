# Lyra Market Expert — the Tremor Index (TRX)

A niche, probabilistic helper that tells an AI (or you) whether a stock looks
more likely to **boom** or **bust**, why, and how much to buy or sell.
It is not an oracle and it is not financial advice. It is built to be honest
about uncertainty and to get better by grading its own past calls.

Each stock gets its own reading, labelled `TRX-<TICKER>` (e.g. `TRX-NVDA`).

| Field | Meaning |
|---|---|
| `p_boom` | chance of rising ≥ 5% within 30 days |
| `p_bust` | chance of falling ≥ 5% within 30 days |
| `score` | 0–100; 50 is neutral, above leans boom, below leans bust |
| `tremor` | chance of a big move either way |
| `causes` | the factors that drove the reading, in plain English |
| `decision` | `BUY` / `SELL` / `HOLD`, confidence, and position size |

## What it looks at

1. **Market fear** — the CBOE VIX level, 5-day change and regime (calm → panic).
2. **The stock itself** — momentum, trend vs. 50-day average, drawdown, its own
   volatility compared with the VIX, unusual volume.
3. **All the news in one place** — Yahoo Finance and Google News feeds per ticker,
   plus CNBC/MarketWatch market feeds. Full article text is fetched where the
   site allows it and stored locally, so you can read everything at
   `/market` without opening another site. Each article gets a sentiment score.
4. **Smart money** — pure maths misses trades made on better information, so it follows:
   - **Company insiders** (SEC Form 4): open-market buys and sells, weighted by
     role (a CEO's purchase counts more than a director's sale; sales are
     discounted because most are scheduled).
   - **Famous funds** (SEC 13F): Buffett, Ackman, Burry, Dalio, Wood, Druckenmiller,
     Tepper, Renaissance — whether they hold the stock and whether they added or trimmed.
   - **Politicians** (House/Senate disclosures).
   - **Your own list** of notable trades in `data/market/notable_trades.json`
     (e.g. a tech leader's reported buy).
   - **Quiet accumulation** — insiders/politicians buying while the news is
     silent, the closest public proxy for someone knowing something early.
5. **The network ("neurolink")** — other Lyra nodes, or signal files other
   projects publish on GitHub, listed in `data/market/peers.json`. Their
   consensus is a feature; disagreement lowers confidence.

## How it learns from mistakes

Every reading is saved. After 30 days the learner checks what the price did,
labels it boom / bust / flat, and updates two small logistic models (boom and
bust) toward the truth. Wrong calls go into a mistake log with the factors that
misled it, so you can see why it was wrong. Weights are regularised toward
sensible defaults so a few unlucky outcomes can't wreck the model. This runs
every 6 hours in the background, or on demand.

## Using it

**Web UI:** start Lyra and open `http://localhost:8080/market`.

**For an AI agent:**
```http
POST /api/market/decision
{"ticker": "NVDA", "portfolio_value": 10000, "shares_held": 0}
```
returns the action, size (`portfolio_fraction`, `amount`, `shares`), the causes,
and a `brief` text block to drop into the model's context.

| Endpoint | Purpose |
|---|---|
| `GET /api/market/vix` | current VIX |
| `GET /api/market/index/{ticker}` | full Tremor reading |
| `POST /api/market/decision` | AI trade decision with sizing |
| `POST /api/market/scan` | rank up to 25 tickers |
| `GET /api/market/news?ticker=&q=&refresh=` | stored articles |
| `GET /api/market/news/{id}` | one article with full text |
| `GET /api/market/signal/{ticker}` | lightweight signal for peer nodes |
| `GET /api/market/signals.json?tickers=NVDA,AAPL` | publishable signal file |
| `GET /api/market/learning` | hit rate, mistake log, current weights |
| `POST /api/market/learning/evaluate` | grade matured readings now |

**Command line:**
```bash
python -m lyra.market read NVDA --portfolio 10000
python -m lyra.market scan NVDA AAPL TSLA AMD
python -m lyra.market news NVDA
python -m lyra.market learn
python -m lyra.market export NVDA AAPL --out signals.json   # commit to GitHub for peers
```

## Configuration

| Env var | Default | |
|---|---|---|
| `LYRA_SEC_USER_AGENT` | `Lyra Market Expert lyra@example.com` | **Set this to your name + email** — the SEC requires it |
| `LYRA_MARKET_HORIZON_DAYS` | 30 | grading horizon |
| `LYRA_MARKET_BOOM` / `LYRA_MARKET_BUST` | 0.05 | move that counts as boom/bust |
| `LYRA_MARKET_MAX_POSITION` | 0.05 | max fraction of portfolio in one stock |
| `LYRA_HOUSE_TRADES_URL` / `LYRA_SENATE_TRADES_URL` | stock-watcher S3 files | swap if those feeds move |

Sizing is deliberately conservative: never more than `MAX_POSITION`, scaled by
confidence, and shrunk further when the VIX is above 20. Low-confidence
readings always come back as `HOLD`.

## Limits

- Free public data only: Yahoo/Stooq prices, SEC EDGAR, RSS feeds. Some sites
  block full-text fetching; those articles show their summary.
- Insider and politician filings arrive days to weeks after the trade.
- The models start from hand-set priors and need dozens of graded readings
  before the learned weights mean much. Confidence reflects that.
