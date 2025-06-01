#!/bin/bash
# scripts/python/install_deps.sh
# Install packages from project-root requirements.txt

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/venv-scrape-sports-25"
REQUIREMENTS="$ROOT_DIR/requirements.txt"

if [[ ! -f "$REQUIREMENTS" ]]; then
  echo "❌ $REQUIREMENTS not found in $ROOT_DIR. Run freeze_requirements.sh or create it manually."
  exit 1
fi

if [[ -d "$VENV_DIR" ]]; then
  echo "📦 Installing packages from $REQUIREMENTS"
  source "$VENV_DIR/bin/activate"
  pip install --upgrade pip
  pip install -r "$REQUIREMENTS"
  echo "✅ Packages installed"
else
  echo "❌ Virtualenv not found at $VENV_DIR. Run env_create.sh first."
  exit 1
fi
