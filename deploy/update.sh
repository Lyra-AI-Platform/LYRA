#!/bin/bash
# ============================================================
# lyraauth.com — Update Script
# Run this whenever you push new code
# Usage: bash update.sh
# ============================================================

set -e

APP_DIR="/opt/lyra"
APP_USER="lyra"
BRANCH="${LYRA_BRANCH:-claude/vix-expert-stock-predictor-u7j0br}"

echo "→ Pulling latest code..."
sudo -u $APP_USER git -C $APP_DIR fetch origin $BRANCH
sudo -u $APP_USER git -C $APP_DIR checkout $BRANCH
sudo -u $APP_USER git -C $APP_DIR pull origin $BRANCH

echo "→ Installing any new dependencies..."
sudo -u $APP_USER $APP_DIR/.venv/bin/pip install --quiet -r $APP_DIR/requirements.txt

echo "→ Restarting Lyra..."
systemctl restart lyra

echo "→ Reloading nginx..."
nginx -t && systemctl reload nginx

echo "✓ Update complete — lyraauth.com is running the latest version"
systemctl status lyra --no-pager -l
