#!/bin/bash
# scripts/python/env_create.sh

# Navigate two levels up to project root
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/venv-scrape-sports-25"

if [[ -d "$VENV_DIR" ]]; then
  echo "✅ Virtualenv already exists at $VENV_DIR"
else
  echo "📦 Creating virtual environment in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  echo "✅ Virtualenv created at $VENV_DIR"
fi
