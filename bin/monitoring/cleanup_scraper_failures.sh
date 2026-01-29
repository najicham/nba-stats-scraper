#!/bin/bash
#
# Wrapper script for cleanup_scraper_failures.py
# Suitable for cron jobs or manual execution
#
# Usage:
#   ./bin/monitoring/cleanup_scraper_failures.sh              # Production run
#   ./bin/monitoring/cleanup_scraper_failures.sh --dry-run    # Test mode
#   ./bin/monitoring/cleanup_scraper_failures.sh --days-back=14  # Look back 14 days
#

set -euo pipefail

# Change to repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

# Set up environment
export GCP_PROJECT="${GCP_PROJECT:-nba-props-platform}"

# Run Python script with all arguments passed through
python3 bin/monitoring/cleanup_scraper_failures.py "$@"
