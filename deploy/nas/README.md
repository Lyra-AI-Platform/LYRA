# Running lyraauth.com on your NAS

Two containers: the site (`lyra`) and Cloudflare's connector (`tunnel`). The tunnel
dials out to Cloudflare, so:
- no router port forwarding
- your home IP address is never exposed
- every visitor passes Cloudflare's protection first

The Cloudflare side is already configured: the `lyraauth.com` tunnel routes
`lyraauth.com` and `www.lyraauth.com` to `http://lyra:7860`.

## What you need

- A NAS that runs Docker: Synology (Container Manager), QNAP (Container Station),
  Unraid, TrueNAS SCALE, or any Linux box with Docker Compose.
- An Intel/AMD (x86-64) or 64-bit ARM NAS.
- About 1 GB free RAM and 2 GB disk.
- Your tunnel token: Cloudflare dashboard → **Networking → Tunnels → lyraauth.com**
  → copy the long value starting `eyJ` from the install command.

## Option A: Synology (Container Manager), no command line

1. Download the code: https://github.com/lyra-ai-platform/lyra/archive/refs/heads/claude/vix-expert-stock-predictor-u7j0br.zip
2. In **File Station**, create the folder `docker/lyra`, upload the zip into it and
   extract it there. Right-click the zip → *Extract → Extract here*.
3. Open the extracted folder → `deploy/nas`. Make a copy of `.env.example`
   named `.env`, open it with **Text Editor**, paste your token after
   `TUNNEL_TOKEN=` and save.
4. Open **Container Manager → Project → Create**:
   - Project name: `lyra`
   - Path: the `deploy/nas` folder from step 3
   - Source: **Use existing docker-compose.yml**
   - Click through and **Done**. The first build takes a few minutes.
5. Both containers should show **Running**. Tell Claude, and it will switch the
   domain over to the tunnel.

QNAP Container Station has the same flow under **Applications → Create**:
point it at `deploy/nas/docker-compose.yml`.

## Option B: any NAS with SSH

```bash
git clone --branch claude/vix-expert-stock-predictor-u7j0br https://github.com/lyra-ai-platform/lyra.git
cd lyra/deploy/nas
cp .env.example .env && nano .env        # paste TUNNEL_TOKEN, save
docker compose up -d --build
docker compose ps                        # both should be "running"
```

## Checking it works

- `docker compose logs tunnel` should show `Registered tunnel connection` (4 times).
- In Cloudflare → Networking → Tunnels, `lyraauth.com` turns **Healthy**.

## Updating later

Synology: download the new zip, replace the folder (keep your `.env`), then
Container Manager → Project → lyra → **Build**.
SSH: `git pull && docker compose up -d --build`.

## Your data

Accounts, the login secret and market history live in the Docker volume
`lyra_lyra-data`, which survives restarts and updates. Back it up from Container
Manager, or run:
`docker run --rm -v lyra_lyra-data:/d -v "$PWD":/b alpine tar czf /b/lyra-backup.tgz -C /d .`

If the NAS is off or loses internet, the site goes down with it. Cloudflare shows
visitors an error page until it's back.
