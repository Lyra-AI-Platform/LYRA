# Putting lyraauth.com behind Cloudflare

Cloudflare sits in front of the server: visitors connect to Cloudflare, and a
**Cloudflare Tunnel** carries traffic to the VPS over an outbound connection.
The VPS then has no open web ports, so it can't be hit directly, and every request
passes Cloudflare's bot and abuse filtering first.

## 1. Add the domain to Cloudflare (once)

1. Cloudflare dashboard → **Add a domain** → `lyraauth.com` → Free plan.
2. At your domain registrar, change the nameservers to the two Cloudflare gives you.
   Wait until Cloudflare shows the domain as **Active**.
3. Delete any old `A` records for `lyraauth.com` / `www` that point at the VPS IP
   (the tunnel creates its own records in step 2).

## 2. Create the tunnel

1. Dashboard → **Networking → Tunnels** (Zero Trust → Networks → Tunnels on older dashboards) → **Create a tunnel** → type **Cloudflared** → name it `lyra`.
2. Copy the token shown in the install command (the long `eyJ...` string).
3. Add **Published application routes**:
   | Hostname | Service |
   |---|---|
   | `lyraauth.com` | `HTTP` → `localhost:80` |
   | `www.lyraauth.com` | `HTTP` → `localhost:80` |

## 3. Run the setup on the VPS

```bash
git clone --branch claude/vix-expert-stock-predictor-u7j0br https://github.com/lyra-ai-platform/lyra.git /tmp/lyra
CLOUDFLARE_TUNNEL_TOKEN=eyJ...your-token... bash /tmp/lyra/deploy/setup.sh
```

This installs the app, generates its secrets in `/opt/lyra/.env`, installs `cloudflared`
as a service, and firewalls ports 80/443 so only Cloudflare can reach the site.
Later updates: `bash /opt/lyra/deploy/update.sh`.

## 4. Anti-scraping settings (dashboard, ~5 minutes)

| Where | Setting |
|---|---|
| SSL/TLS → Overview | **Full** |
| SSL/TLS → Edge Certificates | **Always Use HTTPS** on |
| Security → Settings → Bot traffic | **Bot fight mode** on, **Block AI bots** on |
| AI Crawl Control | **Block** all AI crawlers |
| Scrape Shield | **Email address obfuscation** and **Hotlink protection** on |
| Security → WAF → Rate limiting rules | Add the rule below |
| Caching → Cache Rules | Bypass cache when URI path starts with `/api/` or equals `/market` |

Rate limiting rule (Free plan allows one):
- **If** URI path starts with `/api/market` **or** URI path equals `/api/users/login`
- **Rate**: 60 requests per 10 seconds, counted per IP
- **Then**: Block for 10 seconds

## What actually stops people copying the data

| Layer | Protection |
|---|---|
| App | All market data requires a signed-in account; anonymous requests get 401 |
| App | Per-account hourly limits (40 analyses, 400 reads) and small page sizes, so bulk export is slow and obvious |
| App | Peer/export endpoints are disabled unless the caller has the secret `LYRA_PEER_KEY` |
| App | Login tokens are signed with a random secret generated on the server (the old code used a public default) |
| Page | Text selection, right-click, copy, print and save shortcuts are blocked on data panels; every view is watermarked with the viewer's email and time, so leaked screenshots can be traced |
| Responses | `no-store` and `noindex` headers: nothing is cached by Cloudflare or indexed by search engines |
| Cloudflare | Bot Fight Mode, AI-crawler blocking, rate limiting, and no direct access to the server |

Honest limit: anything a signed-in person can see, they can screenshot or retype.
These layers make bulk or automated copying impractical and make leaks traceable.
They can't make on-screen data impossible to copy.
