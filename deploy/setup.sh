#!/bin/bash
# lyraauth.com — Full VPS Setup
# Run once on Ubuntu 22.04 as root
set -e
DOMAIN="lyraauth.com"
APP_DIR="/opt/lyra"
PORT="8080"
echo "=== Lyra AI Platform Setup ==="
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq python3.11 python3.11-venv python3-pip git nginx certbot python3-certbot-nginx build-essential
mkdir -p $APP_DIR
git clone https://github.com/Lyra-AI-Platform/LYRA $APP_DIR || (cd $APP_DIR && git pull)
cd $APP_DIR
python3.11 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet fastapi uvicorn[standard] python-multipart aiofiles httpx pydantic websockets rich networkx beautifulsoup4 spacy nltk
.venv/bin/python -m spacy download en_core_web_sm
mkdir -p data/auth/training_data data/memory data/models data/logs
cat > /etc/nginx/sites-available/$DOMAIN << 'NGINX'
server {
    listen 80;
    server_name lyraauth.com www.lyraauth.com;
    root /opt/lyra/website;
    index index.html;
    location /widget.js {
        alias /opt/lyra/lyra/authenticator/frontend/lyraauth.js;
        add_header Content-Type application/javascript;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
    location /ws/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection upgrade;
    }
    location / { try_files $uri $uri/ $uri.html =404; }
}
NGINX
ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email legal@lyraauth.com --redirect || echo 'SSL: run certbot manually if DNS not ready'
cat > /etc/systemd/system/lyra.service << SERVICE
[Unit]
Description=Lyra AI Platform
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m lyra.main
Restart=always
RestartSec=5
Environment=LYRA_HOST=127.0.0.1
Environment=LYRA_PORT=8080
Environment=PYTHONPATH=$APP_DIR
StandardOutput=append:$APP_DIR/data/logs/lyra.log
StandardError=append:$APP_DIR/data/logs/lyra-error.log
[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable lyra
systemctl start lyra
echo ''
echo '=== lyraauth.com is LIVE ==='
echo 'Website: https://lyraauth.com'
echo 'API:     https://lyraauth.com/api/health'
echo 'Widget:  https://lyraauth.com/widget.js'
echo 'Logs:    tail -f /opt/lyra/data/logs/lyra.log'
