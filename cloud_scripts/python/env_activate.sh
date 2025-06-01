#!/bin/bash
# scripts/python/env_activate.sh

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/venv-scrape-sports-25"

if [[ -d "$VENV_DIR" ]]; then
  echo "🟢 Activating virtualenv..."
  source "$VENV_DIR/bin/activate"
else
  echo "❌ Virtualenv not found at $VENV_DIR. Run env_create.sh first."
fi
