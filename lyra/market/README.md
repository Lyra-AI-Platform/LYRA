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
3. **News** — Yahoo Finance and Google News feeds per ticker, plus CNBC/MarketWatch
   market feeds. Only articles whose headline or summary names the ticker or the
   company are counted. Headline, a short summary and a link to the publisher are
   kept; full article text is never fetched or shown (copyright). Each counted
   article gets a word-list sentiment score.
4. **Insider, fund and politician trades** — pure price maths can't see these, so it follows:
   - **Company insiders** (SEC Form 4): open-market buys and sells, weighted by
     role (a CEO's purchase counts more than a director's sale; sales are
     discounted because most are scheduled).
   - **Famous funds** (SEC 13F): Buffett, Ackman, Burry, Dalio, Wood, Druckenmiller,
     Tepper, Renaissance — whether they hold the stock and whether they added or trimmed.
   - **Politicians** (House/Senate disclosures).
   - **Your own list** of notable trades in `data/market/notable_trades.json`
     (e.g. a tech leader's reported buy).
   - **Buying while news is quiet** — insiders or politicians buying while news
     coverage is low.
5. **The network ("neurolink")** — other Lyra nodes, or signal files other
   projects publish on GitHub, listed in `data/market/peers.json`. Their
   consensus is a feature; disagreement lowers confidence.

## Risk guard — fixing the way AI day traders actually blow up

Most AI trading bots don't fail because their predictions are bad. They fail
because nothing stops them from acting on a bad prediction at full size, again
and again. Every `BUY`/`SELL` passes through `risk_guard.py` before it is
returned, and the guard can only shrink a trade or turn it into `HOLD`, never
enlarge it. Exits (`SELL`) are never blocked.

| Failure mode | What the guard does |
|---|---|
| No stop, one gap wipes out weeks of gains | Every BUY comes with a volatility-based stop-loss (2x typical daily move) and a 2:1 take-profit; size is capped so hitting the stop loses at most 1% of equity |
| A bad day turns into a blown account | Daily loss limit: no new buys after -2% on the day |
| Slow bleed becomes a disaster | Drawdown circuit breaker: sizes halve at 5% below peak, buying halts at 10% |
| Revenge trading after losses | 3 losing trades in a row → 24h cool-off on new buys |
| Overtrading / flip-flopping | Max 10 trades a day; no re-buying a ticker within 30 min of trading it |
| Fees and spread eat tiny edges | Buys whose expected move doesn't clear 2x round-trip costs become HOLD |
| Acting on stale or missing data | No buying if the latest price is more than 4 days old or missing |
| Whole account riding on one move | Total exposure capped at 60% of equity |

For the guard to know the account's state, the trader reports it:
```http
POST /api/market/account   {"equity": 10250, "invested": 3100}
POST /api/market/fills     {"ticker": "NVDA", "side": "buy", "shares": 3, "price": 135.2}
GET  /api/market/risk      -> daily P&L, drawdown, losing streak, trades today
```
`/api/market/decision` also records `portfolio_value` as an equity snapshot.
Every decision carries `risk.checks` explaining what passed, what was cut and
what was blocked; vetoed decisions keep `original_action`. All limits can be
changed with `LYRA_RISK_PER_TRADE`, `LYRA_DAILY_LOSS_LIMIT`, `LYRA_MAX_DRAWDOWN`,
`LYRA_MAX_EXPOSURE`, `LYRA_LOSS_STREAK`, `LYRA_COOLDOWN_HOURS`,
`LYRA_MAX_TRADES_PER_DAY`, `LYRA_MIN_REENTRY_MINUTES`, `LYRA_ROUND_TRIP_COST`
and `LYRA_MAX_DATA_AGE_DAYS`.

The learner still grades the model's own call, not the guard's veto, so a
blocked trade doesn't teach the model the wrong lesson.

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
returns the lean (BUY/SELL/HOLD), the causes and a `brief` text block to drop
into the model's context. Portfolio sizing (`portfolio_fraction`, `amount`,
`shares`, stops) is only returned when `LYRA_MARKET_PERSONAL_SIZING=1`, which is
for the operator's own private use: sizing tailored to one person's holdings is
regulated personal advice, so it is off on the public site.

| Endpoint | Purpose |
|---|---|
| `GET /api/market/vix` | current VIX |
| `GET /api/market/index/{ticker}` | full Tremor reading |
| `POST /api/market/decision` | AI trade decision with sizing |
| `POST /api/market/scan` | rank up to 25 tickers |
| `GET /api/market/news?ticker=&q=&refresh=` | stored articles |
| `GET /api/market/news/{id}` | one headline with summary and publisher link |
| `GET /api/market/signal/{ticker}` | lightweight signal for peer nodes |
| `GET /api/market/signals.json?tickers=NVDA,AAPL` | publishable signal file |
| `POST /api/market/account` | report equity / amount invested |
| `POST /api/market/fills` | report an executed trade |
| `GET /api/market/risk` | account state as the risk guard sees it |
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
| `LYRA_HOUSE_TRADES_URL` / `LYRA_SENATE_TRADES_URL` | stock-watcher S3 files | **both return 403 as of Oct 2026** — point at a live source |
| `LYRA_MARKET_PERSONAL_SIZING` | off | `1` returns portfolio-specific sizing (private use only) |
| `LYRA_MARKET_EXPERIMENTAL_UNTIL` | 200 | graded readings before the "experimental" label is dropped |

Every reading carries `sources` (status `ok` / `partial` / `stale` / `failed`
per source). If price, news or insider data fails, the reading is marked
`partial`, the page says which source failed, and it is not added to the track
record. At most one reading per ticker per day is saved for grading.

Sizing is deliberately conservative: never more than `MAX_POSITION`, scaled by
confidence, and shrunk further when the VIX is above 20. Low-confidence
readings always come back as `HOLD`.

## Limits

- Free public data only: Yahoo Finance prices (unofficial API, personal-use
  terms — a public or paid site needs a licensed feed), SEC EDGAR, RSS feeds.
- Funds are matched to the company by the first two words of the issuer name,
  not by CUSIP, so similar names can mismatch.
- The probabilities have not been backtested; treat them as unproven.
- Insider and politician filings arrive days to weeks after the trade.
- The models start from hand-set priors and need dozens of graded readings
  before the learned weights mean much. Confidence reflects that.
