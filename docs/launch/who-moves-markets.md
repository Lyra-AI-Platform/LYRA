# Launch: Who moves markets, Said & traded, Watch Pro, the API, sponsor slots

Ready to paste. Links:
- https://lyraauth.com/watch/#movers (free: top 5 of Who moves markets)
- https://lyraauth.com/watch/account/ (Watch Pro $7/month · API keys with 100 free credits)
- https://lyraauth.com/advertise/ (self-serve sponsor slots, $49/week)

Rules for every post: the impact numbers show what happened on news days, not what caused it, so never write
"X moves stocks" as cause and effect. Don't present any real person as endorsing Lyra. Not financial advice.

---

## X / Bluesky / Threads (thread)

1/ Everyone says certain CEOs and politicians "move markets". We measured it.
Lyra Watch now checks, for every public figure, how often a company's stock made a big move on the days they were in the news about it, against its ordinary days.
https://lyraauth.com/watch/#movers

2/ "Big move" = a daily close at least 2× the stock's usual daily swing. Most stocks do that on ~5% of days. Some people's news days hit 4× that rate. Others: zero. Real closing prices, and the record grows every day.

3/ New: Said & traded. Every disclosed insider and congressional trade, next to the days that person was in the news about the same company in the 30 days before and after. Facts side by side.

4/ Free: the top 5, every person's verdict, the live feed an hour behind.
Watch Pro ($7/mo): the real-time stream, the full record day by day, said & traded.
https://lyraauth.com/watch/account/

5/ Building an AI agent? It's a pay-per-request JSON API. First key gets 100 free credits; out of credits, it answers HTTP 402 with the prices so the agent can ask its owner to top up.

---

## Hacker News (Show HN)

Title: Show HN: Who moves markets – measuring stock moves on the days people make news

Text:
I built Lyra Watch, which reads news coverage of ~40 politicians, investors and executives (plus everyone else the
headlines name) and tags the listed companies in each headline. New this week: for each person it takes the trading
days they were in the news about a company and checks the stock's close-to-close move against its own 60-day
volatility. A "big move" is 2σ. It then compares that share with the stock's share on all days ("lift").

Caveats, shown on the page too: news and price moves come together in both directions (a crash is itself news),
so this is what happened, not what caused it. The sample is small at first; it keeps a history so the record grows
daily, and a verdict needs at least 5 days.

Also: "said & traded" puts disclosed SEC Form 4 / House trades next to the person's news days about the same
ticker. And there's a pay-per-request API for agents that answers 402 with machine-readable prices when the wallet
is empty, which was fun to design.

https://lyraauth.com/watch/

---

## Reddit

r/SideProject (and r/webdev "Showoff Saturday"): use the HN text, title "I measured whether famous people's news days actually move stocks".

r/dataisbeautiful only with a chart (screenshot of the Who moves markets table), flair [OC], data: Yahoo daily closes + Google News/GDELT headlines; tool: Python.

Avoid r/stocks and r/wallstreetbets self-promotion rules: post only if a mod-approved weekly thread allows links.

---

## LinkedIn

Do famous CEOs and politicians really move their companies' stocks? I stopped guessing and measured it.

Lyra Watch now checks every trading day a public figure was in the news about a listed company, and asks whether the
stock made a big move that day (two of its usual daily swings), compared with its ordinary days. Real closing
prices, a record that grows daily, and the caveat in plain sight: it shows what happened, not what caused it.

Also new: Said & traded, which shows every disclosed insider and congressional trade next to the days the trader was
in the news about the same company.

Free to browse: https://lyraauth.com/watch/
Real-time and the full record with Watch Pro, plus a pay-as-you-go API for AI agents.

---

## Product Hunt

Name: Lyra Watch
Tagline: See who really moves the market, measured from real prices
Description: Lyra Watch tracks politicians, investors and executives in the news, and measures how often a stock made a
big move on the days they made news about it. Said & traded puts disclosed trades next to what was being said.
Free directory and live preview; Watch Pro for real time; a pay-per-request API for AI agents.
First comment: the HN text above, shortened.

---

## Free directories to submit to

Each takes a few minutes with the texts above: Product Hunt, Hacker News (Show HN), BetaList, Indie Hackers
(product page + a post), AlternativeTo (as an alternative to Quiver Quantitative / Capitol Trades), SaaSHub,
There's An AI For That and Futurepedia (as an AI data API), Postman API Network and RapidAPI Hub (list the
API with the same credit prices), and the public MCP/agent tool lists if you later wrap the API as an MCP server.

---

## Selling sponsor slots

Email or DM newsletters, fintech tools and research products that serve retail investors:

Subject: Sponsor slot on Lyra Watch

Hi, I run Lyra Watch (lyraauth.com/watch), a live tracker of the politicians, investors and executives moving the
news, with a measured "who moves markets" board. Readers are people who follow markets and policy. There's one
sponsor slot on the directory and the live feed: a headline, a line of text and your link, $49 a week, booked
here: lyraauth.com/advertise. You see impressions and clicks; no tracking cookies.
