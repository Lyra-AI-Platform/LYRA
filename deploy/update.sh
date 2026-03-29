#!/bin/bash
# lyraauth.com — Update script
cd /opt/lyra
git pull origin main
.venv/bin/pip install --quiet -r requirements.txt 2>/dev/null || true
systemctl restart lyra
nginx -t && systemctl reload nginx
echo 'Update complete'
systemctl status lyra --no-pager
