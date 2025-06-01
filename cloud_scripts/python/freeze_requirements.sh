#!/bin/bash
# scripts/python/freeze_requirements.sh
# Freeze current pip environment to project-root requirements.txt

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/venv-scrape-sports-25"
REQUIREMENTS="$ROOT_DIR/requirements.txt"

if [[ -d "$VENV_DIR" ]]; then
  source "$VENV_DIR/bin/activate"
  echo "📦 Freezing environment to $REQUIREMENTS"
  pip freeze > "$REQUIREMENTS"
  echo "✅ Saved dependencies to $REQUIREMENTS"
else
  echo "❌ Virtualenv not found at $VENV_DIR. Run env_create.sh first."
fi
