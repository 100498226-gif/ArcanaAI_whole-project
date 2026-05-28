#!/usr/bin/env bash
set -euo pipefail

# Clean, repeatable local run script for MVP
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"/backend

# Optional: activate venv if present in repo root
VENV="$(pwd)/../../.venv"  # relative from backend to project root .venv
if [ -d "$VENV/bin" ]; then
  source "$VENV/bin/activate"
fi

# Ensure Python path points to backend so `import arcana` works
export PYTHONPATH="$(pwd)":$PYTHONPATH

echo "[info] Starting Arcana MVP backend..."
uvicorn arcana.main:app --reload --port 8000 --host 0.0.0.0
