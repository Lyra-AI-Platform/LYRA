#!/bin/bash
# ============================================================
# Lyra Watch watchdog: keeps the people index and live feed updating.
#
# systemd already restarts lyra if the process crashes (Restart=on-failure).
# This covers the other case: the process is up but its update loops have
# stalled. Every 15 minutes it asks /api/watch/health; after two failed
# checks in a row it restarts lyra, at most once an hour.
#
# Usage on the NAS:  sudo bash /opt/lyra/deploy/install-watchdog.sh
# Logs:              journalctl -t lyra-watchdog
# Remove:            sudo systemctl disable --now lyra-watchdog.timer
# ============================================================
set -euo pipefail

cat > /usr/local/bin/lyra-watchdog <<'EOF'
#!/bin/bash
# One health check; restarts lyra when Lyra Watch has stopped updating.
STATE=/var/lib/lyra-watchdog
mkdir -p "$STATE"
URL="${LYRA_HEALTH_URL:-http://127.0.0.1:7860/api/watch/health}"
code=$(curl -s -o "$STATE/last.json" -w "%{http_code}" --max-time 20 "$URL" || echo 000)

if [ "$code" = "200" ]; then
  rm -f "$STATE/failures"
  exit 0
fi

failures=$(( $(cat "$STATE/failures" 2>/dev/null || echo 0) + 1 ))
echo "$failures" > "$STATE/failures"
logger -t lyra-watchdog "health check failed ($code, $failures in a row): $(head -c 300 "$STATE/last.json" 2>/dev/null)"

last=$(cat "$STATE/last_restart" 2>/dev/null || echo 0)
if [ "$failures" -ge 2 ] && [ $(( $(date +%s) - last )) -ge 3600 ]; then
  logger -t lyra-watchdog "restarting lyra"
  date +%s > "$STATE/last_restart"
  rm -f "$STATE/failures"
  systemctl restart lyra
fi
EOF
chmod 755 /usr/local/bin/lyra-watchdog

cat > /etc/systemd/system/lyra-watchdog.service <<'EOF'
[Unit]
Description=Lyra Watch health check
After=lyra.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/lyra-watchdog
EOF

cat > /etc/systemd/system/lyra-watchdog.timer <<'EOF'
[Unit]
Description=Check Lyra Watch is still updating, every 15 minutes

[Timer]
OnBootSec=20min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now lyra-watchdog.timer
echo "✓ lyra-watchdog installed:"
systemctl list-timers lyra-watchdog.timer --no-pager
