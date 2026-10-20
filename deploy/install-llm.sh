#!/bin/bash
# ============================================================
# lyraauth.com — give Lyra chat a real local model (run on the NAS as root)
#
#   Ollama (https://ollama.com) runs the model as its own service, listening on
#   127.0.0.1 only. Lyra talks to it (lyra/core/ollama_backend.py) and falls back to
#   the old engine if it's ever down.
#
#   Model: qwen3:4b-instruct (2.5 GB). The NAS has 4 CPU cores, 7.7 GB RAM and no GPU,
#   which fits a 4B model with room for the site; anything bigger would swap.
#
# Usage:  sudo bash deploy/install-llm.sh            (safe to run again)
#         LYRA_LLM=qwen3:1.7b sudo bash deploy/install-llm.sh   (smaller, faster)
# ============================================================
set -euo pipefail

MODEL="${LYRA_LLM:-qwen3:4b-instruct}"
CTX="${LYRA_LLM_CTX:-4096}"

[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }

if ! command -v ollama >/dev/null; then
  echo "→ Installing Ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo "→ Ollama: local only, one model, one request at a time…"
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/lyra.conf <<EOF
[Service]
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_KEEP_ALIVE=24h
EOF
systemctl daemon-reload
systemctl enable --now ollama
systemctl restart ollama
for i in $(seq 1 30); do curl -fs http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done

echo "→ Downloading $MODEL (a few minutes the first time)…"
ollama pull "$MODEL"

echo "→ Pointing Lyra chat at it…"
mkdir -p /etc/systemd/system/lyra.service.d
cat > /etc/systemd/system/lyra.service.d/llm.conf <<EOF
[Service]
Environment=LYRA_OLLAMA_MODEL=$MODEL
Environment=LYRA_OLLAMA_CTX=$CTX
EOF
systemctl daemon-reload
systemctl restart lyra

echo "→ Warming the model up…"
curl -fs http://127.0.0.1:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"Say ready.\",\"stream\":false,\"keep_alive\":\"24h\",\"options\":{\"num_ctx\":$CTX,\"num_predict\":5}}" >/dev/null || true

for i in $(seq 1 30); do curl -fs http://127.0.0.1:7860/api/health >/dev/null && break; sleep 2; done
echo -n "✓ Lyra chat model: "
curl -fs http://127.0.0.1:7860/api/health | python3 -c 'import sys, json; print(json.load(sys.stdin).get("chat_model"))'
free -h | sed -n 1,2p
