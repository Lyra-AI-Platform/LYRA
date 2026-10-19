#!/bin/bash
# ============================================================
# Connect Lyra Watch to the X API.
#
# Run in a real terminal on the NAS (the token is typed at a hidden prompt, never
# echoed, never put on a command line or in shell history):
#   ssh <nas>  then  sudo bash /opt/lyra/deploy/set-x-token.sh
#
# Stores the Bearer Token in /etc/lyra/x.env (root only, mode 600) and loads it into
# the lyra service. Run again to replace it; `sudo rm /etc/lyra/x.env` and restart to stop.
# Optional: X_MONTHLY_POST_CAP (default 10000) to match your X plan's monthly read limit.
# ============================================================
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }

printf "Paste the X Bearer Token (Keys and tokens → Bearer Token), then press Enter: "
read -rs TOKEN; echo
[ -n "$TOKEN" ] || { echo "No token entered."; exit 1; }

printf "Monthly post cap for your X plan [10000]: "
read -r CAP; CAP="${CAP:-10000}"
[[ "$CAP" =~ ^[0-9]+$ ]] || { echo "Cap must be a number."; exit 1; }

echo "→ Checking the token with X..."
# The header goes in on stdin, so the token never appears in the process list.
code=$(printf 'Authorization: Bearer %s' "$TOKEN" | curl -s -o /dev/null -w "%{http_code}" -H @- \
  "https://api.x.com/2/users/by/username/X")
if [ "$code" != "200" ]; then
  echo "X answered $code. Check it's the Bearer Token (not the Access Token) and that the app has read access."
  exit 1
fi

install -d -m 700 /etc/lyra
umask 077
printf 'X_BEARER_TOKEN=%s\nX_MONTHLY_POST_CAP=%s\n' "$TOKEN" "$CAP" > /etc/lyra/x.env
chmod 600 /etc/lyra/x.env
unset TOKEN

install -d /etc/systemd/system/lyra.service.d
printf '[Service]\nEnvironmentFile=/etc/lyra/x.env\n' > /etc/systemd/system/lyra.service.d/x.conf
systemctl daemon-reload
systemctl restart lyra
echo "✓ X connected. In a minute, https://lyraauth.com/api/watch/health should show sources.x.on = true."
