#!/bin/bash
# ============================================================
# lyraauth.com — Full VPS Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 VPS as root
# Usage: bash setup.sh
#
# Behind Cloudflare (recommended): create a tunnel in the Cloudflare
# dashboard (see deploy/cloudflare/README.md), then run
#   CLOUDFLARE_TUNNEL_TOKEN=<token> bash setup.sh
# The server then needs no open web ports and no certbot.
# ============================================================

set -e  # Exit on any error

DOMAIN="lyraauth.com"
APP_DIR="/opt/lyra"
APP_USER="lyra"
REPO_URL="https://github.com/lyra-ai-platform/lyra.git"
BRANCH="${LYRA_BRANCH:-claude/vix-expert-stock-predictor-u7j0br}"
PORT="7860"
CF_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"

echo "================================================"
echo "  Lyra AI Platform — Setup for $DOMAIN"
echo "================================================"

# ── 1. System update ──────────────────────────────
echo ""
echo "[1/9] Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

# ── 2. Install dependencies ───────────────────────
echo "[2/9] Installing system dependencies..."
apt-get install -y -qq \
  python3 python3-venv python3-pip \
  git nginx certbot python3-certbot-nginx \
  build-essential curl wget unzip

# Ensure nginx service is started after fresh install
systemctl enable nginx 2>/dev/null || true
systemctl start nginx 2>/dev/null || true

# ── 3. Create app user ────────────────────────────
echo "[3/9] Creating app user..."
id -u $APP_USER &>/dev/null || useradd -r -m -d $APP_DIR -s /bin/bash $APP_USER

# ── 4. Clone / update repo ────────────────────────
echo "[4/9] Deploying Lyra code..."
if [ -d "$APP_DIR/.git" ]; then
  echo "  → Updating existing repo..."
  git -C $APP_DIR fetch origin
  git -C $APP_DIR checkout $BRANCH
  git -C $APP_DIR reset --hard origin/$BRANCH
else
  echo "  → Cloning fresh..."
  rm -rf $APP_DIR
  git clone --branch $BRANCH $REPO_URL $APP_DIR
fi
chown -R $APP_USER:$APP_USER $APP_DIR

# ── 5. Python environment ─────────────────────────
echo "[5/9] Setting up Python environment..."
sudo -u $APP_USER python3 -m venv $APP_DIR/.venv
sudo -u $APP_USER $APP_DIR/.venv/bin/pip install --quiet --upgrade pip
sudo -u $APP_USER $APP_DIR/.venv/bin/pip install --quiet -r $APP_DIR/requirements.txt
sudo -u $APP_USER $APP_DIR/.venv/bin/python -m spacy download en_core_web_sm

# Create required data directories
sudo -u $APP_USER mkdir -p $APP_DIR/data/auth/training_data \
                           $APP_DIR/data/memory \
                           $APP_DIR/data/models \
                           $APP_DIR/data/logs

# Secrets live outside the repo, are generated once and survive updates.
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" << ENV_CONF
JWT_SECRET=$(openssl rand -hex 48)
LYRA_PEER_KEY=$(openssl rand -hex 24)
LYRA_SEC_USER_AGENT=Lyra Market Expert legal@$DOMAIN
ENV_CONF
fi
chown $APP_USER:$APP_USER "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ── 6. Nginx configuration ────────────────────────
echo "[6/9] Configuring nginx..."
cat > /etc/nginx/sites-available/$DOMAIN << 'NGINX_CONF'
server {
    listen 80;
    server_name lyraauth.com www.lyraauth.com;

    # Serve the static website files
    root /opt/lyra/website;
    index index.html;

    # Widget JS served from authenticator
    location /widget.js {
        alias /opt/lyra/lyra/authenticator/frontend/lyraauth.js;
        add_header Content-Type application/javascript;
        add_header Cache-Control "public, max-age=3600";
    }

    # API — proxy to FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
    }

    # Tremor Index page (served by the app; data behind login)
    location = /market {
        proxy_pass http://127.0.0.1:7860;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
        add_header Cache-Control "private, no-store" always;
    }

    # WebSocket support (chat)
    location /ws/ {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # Static pages
    location / {
        try_files $uri $uri/ $uri.html =404;
    }

    # Real visitor IPs when traffic arrives through the Cloudflare tunnel
    set_real_ip_from 127.0.0.1;
    real_ip_header CF-Connecting-IP;

    # Never serve dotfiles (.env, .git)
    location ~ /\.(?!well-known) { deny all; }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()";
}
NGINX_CONF

# Set correct permissions on website folder
chmod -R 755 $APP_DIR/website 2>/dev/null || true
chown -R $APP_USER:www-data $APP_DIR/website 2>/dev/null || true

# Enable site
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
rm -f /etc/nginx/sites-enabled/default
nginx -t && (systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || service nginx restart 2>/dev/null || true)

# ── 7. HTTPS: Cloudflare Tunnel, or certbot ───────
if [ -n "$CF_TOKEN" ]; then
  echo ""
  echo "[7/9] Connecting to Cloudflare Tunnel..."
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq && apt-get install -y -qq cloudflared
  cloudflared service uninstall 2>/dev/null || true
  cloudflared service install "$CF_TOKEN"
  # Cloudflare now carries all web traffic; only SSH stays open to the internet.
  apt-get install -y -qq ufw
  ufw allow OpenSSH
  ufw deny 80/tcp
  ufw deny 443/tcp
  ufw --force enable
else
  echo "[7/9] Getting HTTPS certificate (free via Let's Encrypt)..."
  echo "  → Make sure DNS is pointing to this server before this step!"
  certbot --nginx \
    -d $DOMAIN \
    -d www.$DOMAIN \
    --non-interactive \
    --agree-tos \
    --email legal@lyraauth.com \
    --redirect || echo "  ⚠ Certbot failed — run manually: certbot --nginx -d $DOMAIN -d www.$DOMAIN"
fi

# ── 8. Systemd service ────────────────────────────
echo "[8/9] Installing systemd service..."
cat > /etc/systemd/system/lyra.service << SERVICE_CONF
[Unit]
Description=Lyra AI Platform
Documentation=https://lyraauth.com/pages/docs.html
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m lyra.main
Restart=always
RestartSec=5
Environment=LYRA_HOST=127.0.0.1
Environment=LYRA_PORT=$PORT
Environment=PYTHONPATH=$APP_DIR
EnvironmentFile=$APP_DIR/.env
StandardOutput=append:$APP_DIR/data/logs/lyra.log
StandardError=append:$APP_DIR/data/logs/lyra-error.log

[Install]
WantedBy=multi-user.target
SERVICE_CONF

systemctl daemon-reload
systemctl enable lyra
systemctl start lyra

# ── 9. Done ───────────────────────────────────────
echo "[9/9] Setup complete!"
echo ""
echo "================================================"
echo "  ✓ lyraauth.com is LIVE"
echo "================================================"
echo ""
echo "  Website:   https://lyraauth.com"
echo "  API:       https://lyraauth.com/api/health"
echo "  Widget:    https://lyraauth.com/widget.js"
echo "  Tremor:    https://lyraauth.com/market   (sign in first)"
echo "  Logs:      tail -f $APP_DIR/data/logs/lyra.log"
echo "  Status:    systemctl status lyra"
echo ""
echo "  Next steps:"
echo "  1. Visit https://lyraauth.com — your site should be live"
echo "  2. Register your first site key: POST https://lyraauth.com/api/auth/register"
echo "  3. Set up owner auth: POST https://lyraauth.com/api/owner/setup"
echo ""
