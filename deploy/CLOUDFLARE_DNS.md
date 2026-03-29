# Cloudflare DNS Setup for lyraauth.com

## Step 1 — Add your VPS to Cloudflare DNS

In Cloudflare dashboard → lyraauth.com → DNS → Records:

| Type | Name         | Content         | Proxy status | TTL  |
|------|--------------|-----------------|--------------|------|
| A    | `@`          | `YOUR_VPS_IP`   | Proxied ☁️   | Auto |
| A    | `www`        | `YOUR_VPS_IP`   | Proxied ☁️   | Auto |

Replace `YOUR_VPS_IP` with the IP address of your VPS.

**Leave Proxy Status ON (orange cloud ☁️)** — this hides your real server IP,
gives you free DDoS protection, and makes the site faster.

---

## Step 2 — SSL/TLS Settings

Cloudflare dashboard → lyraauth.com → SSL/TLS → Overview:

Set encryption mode to: **Full (strict)**

This ensures traffic is encrypted all the way from user → Cloudflare → your VPS.

---

## Step 3 — Page Rules (optional but recommended)

Cloudflare → Rules → Page Rules → Create:

| URL pattern              | Setting              | Value  |
|--------------------------|----------------------|--------|
| `http://lyraauth.com/*`  | Always Use HTTPS     | —      |
| `lyraauth.com/widget.js` | Cache Level          | Cache Everything |
| `lyraauth.com/css/*`     | Cache Level          | Cache Everything |

---

## Step 4 — Privacy Settings

Your WHOIS is already private — Cloudflare Registrar automatically redacts
all owner information from public WHOIS records. Nothing to configure.

To verify: whois lyraauth.com — it will show Cloudflare's info, not yours.

---

## Email (optional)

To receive emails at legal@lyraauth.com, add these records:

| Type | Name | Content |
|------|------|---------|
| MX   | `@`  | `route1.mx.cloudflare.net` (priority 85) |

Then enable Cloudflare Email Routing (free) → forward to your real email.

---

## Done

Once DNS propagates (usually 1-5 minutes with Cloudflare), visit:
- https://lyraauth.com — your website
- https://lyraauth.com/api/health — Lyra API health check
- https://lyraauth.com/widget.js — embeddable widget
