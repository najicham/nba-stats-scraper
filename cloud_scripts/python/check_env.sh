#!/bin/bash
# scripts/python/check_env.sh
# Verifies environment setup for scrape-sports-25

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/venv-scrape-sports-25"
REQUIREMENTS="$ROOT_DIR/requirements.txt"
SA_KEY="$ROOT_DIR/scripts/service-account-key.json"

echo "🔍 Checking environment for scrape-sports-25..."

# Python version check
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
if [[ "$PYTHON_VERSION" < "3.10" ]]; then
  echo "❌ Python 3.10+ is required. Found: $PYTHON_VERSION"
  exit 1
else
  echo "✅ Python version: $PYTHON_VERSION"
fi

# Virtualenv existence
if [[ -d "$VENV_DIR" ]]; then
  echo "✅ Virtualenv found at $VENV_DIR"
else
  echo "❌ Virtualenv not found. Run: ./scripts/python/env_create.sh"
  exit 1
fi

# Activate venv test
source "$VENV_DIR/bin/activate"
if [[ "$VIRTUAL_ENV" == "$VENV_DIR" ]]; then
  echo "✅ Vi

