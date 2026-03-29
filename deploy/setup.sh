#!/bin/bash
# ============================================================
# lyraauth.com — Full VPS Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 VPS as root
# Usage: bash setup.sh
# ============================================================

set -e  # Exit on any error

DOMAIN="lyraauth.com"
APP_DIR="/opt/lyra"
APP_USER="lyra"
REPO_URL="https://github.com/lyra-ai-platform/lyra.git"
BRANCH="claude/advanced-ai-learning-9uJH5"
PORT="7860"

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
  python3.11 python3.11-venv python3-pip \
  git nginx certbot python3-certbot-nginx \
  build-essential curl wget unzip

# ── 3. Create app user ────────────────────────────
echo "[3/9] Creating app user..."
id -u $APP_USER &>/dev/null || useradd -r -m -d $APP_DIR -s /bin/bash $APP_USER

# ── 4. Clone / update repo ────────────────────────
echo "[4/9] Deploying Lyra code..."
if [ -d "$APP_DIR/.git" ]; then
  echo "  → Updating existing repo..."
  sudo -u $APP_USER git -C $APP_DIR fetch origin
  sudo -u $APP_USER git -C $APP_DIR checkout $BRANCH
  sudo -u $APP_USER git -C $APP_DIR pull origin $BRANCH
else
  echo "  → Cloning repo..."
  git clone --branch $BRANCH $REPO_URL $APP_DIR
  chown -R $APP_USER:$APP_USER $APP_DIR
fi

# ── 5. Python environment ─────────────────────────
echo "[5/9] Setting up Python environment..."
sudo -u $APP_USER python3.11 -m venv $APP_DIR/.venv
sudo -u $APP_USER $APP_DIR/.venv/bin/pip install --quiet --upgrade pip
sudo -u $APP_USER $APP_DIR/.venv/bin/pip install --quiet -r $APP_DIR/requirements.txt
sudo -u $APP_USER $APP_DIR/.venv/bin/python -m spacy download en_core_web_sm

# Create required data directories
sudo -u $APP_USER mkdir -p $APP_DIR/data/auth/training_data \
                           $APP_DIR/data/memory \
                           $APP_DIR/data/models \
                           $APP_DIR/data/logs

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

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header Referrer-Policy "no-referrer-when-downgrade";
}
NGINX_CONF

# Set correct permissions on website folder
chmod -R 755 $APP_DIR/website 2>/dev/null || true
chown -R $APP_USER:www-data $APP_DIR/website 2>/dev/null || true

# Enable site
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ── 7. HTTPS certificate ──────────────────────────
echo "[7/9] Getting HTTPS certificate (free via Let's Encrypt)..."
echo "  → Make sure DNS is pointing to this server before this step!"
certbot --nginx \
  -d $DOMAIN \
  -d www.$DOMAIN \
  --non-interactive \
  --agree-tos \
  --email legal@lyraauth.com \
  --redirect || echo "  ⚠ Certbot failed — run manually: certbot --nginx -d $DOMAIN -d www.$DOMAIN"

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
echo "  Logs:      tail -f $APP_DIR/data/logs/lyra.log"
echo "  Status:    systemctl status lyra"
echo ""
echo "  Next steps:"
echo "  1. Visit https://lyraauth.com — your site should be live"
echo "  2. Register your first site key: POST https://lyraauth.com/api/auth/register"
echo "  3. Set up owner auth: POST https://lyraauth.com/api/owner/setup"
echo ""
