#!/usr/bin/env bash
# Lyra AI Platform — Installer
# Copyright (C) 2026 Lyra Contributors — All Rights Reserved. See LICENSE.
set -e
LYRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON=${PYTHON:-python3}

echo ""
echo "  ✦  Lyra AI Platform — Installer"
echo "  ──────────────────────────────"

$PYTHON -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" || {
  echo "[ERROR] Python 3.10+ required"; exit 1; }

VENV="$LYRA_DIR/.venv"
[ ! -d "$VENV" ] && $PYTHON -m venv "$VENV"

if [[ "$OSTYPE" == "msys" || "$OS" == "Windows_NT" ]]; then
  PIP="$VENV/Scripts/pip"
else
  PIP="$VENV/bin/pip"
fi

$PIP install --upgrade pip -q
$PIP install -r "$LYRA_DIR/requirements.txt" -q

# Try GPU llama.cpp
if python3 -c "import torch; torch.cuda.is_available()" 2>/dev/null; then
  CMAKE_ARGS="-DLLAMA_CUDA=on" $PIP install llama-cpp-python --upgrade -q 2>/dev/null || true
fi

mkdir -p "$LYRA_DIR/data/models" "$LYRA_DIR/data/uploads" "$LYRA_DIR/data/memory" "$LYRA_DIR/data/logs"

for pkg in lyra lyra/api lyra/core lyra/models lyra/memory lyra/search lyra/telemetry lyra/plugins; do
  touch "$LYRA_DIR/$pkg/__init__.py"
done

echo ""
echo "  ✅  Installation complete!"
echo ""
echo "  Start Lyra:   ./scripts/start.sh"
echo "  Open at:      http://localhost:7860"
echo ""
