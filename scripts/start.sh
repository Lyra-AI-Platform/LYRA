#!/usr/bin/env bash
# Lyra AI Platform — Start Script
# Copyright (C) 2026 Lyra Contributors — All Rights Reserved. See LICENSE.
LYRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$LYRA_DIR/.venv/bin/python" ]; then
  PYTHON="$LYRA_DIR/.venv/bin/python"
else
  PYTHON="python3"
fi

echo ""
echo "  ✦  Lyra AI Platform"
echo "  Starting at http://127.0.0.1:7860"
echo "  Press Ctrl+C to stop"
echo ""

cd "$LYRA_DIR"
exec $PYTHON -m uvicorn lyra.main:app --host "${LYRA_HOST:-127.0.0.1}" --port "${LYRA_PORT:-7860}" --log-level info
