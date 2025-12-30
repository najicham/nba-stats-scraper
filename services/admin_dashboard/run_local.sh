#!/bin/bash
# Run NBA Admin Dashboard locally for development

set -e

# Navigate to repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Set environment variables
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/services/admin_dashboard"
export FLASK_ENV=development
export GCP_PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
export ADMIN_DASHBOARD_API_KEY="${ADMIN_DASHBOARD_API_KEY:-dev-key-123}"
export PORT=8080

echo "Starting NBA Admin Dashboard locally..."
echo "Dashboard URL: http://localhost:8080/dashboard"
echo "API Key: ${ADMIN_DASHBOARD_API_KEY}"
echo ""

# Run the Flask app
cd services/admin_dashboard
python main.py
