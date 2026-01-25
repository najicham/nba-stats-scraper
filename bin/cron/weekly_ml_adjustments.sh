#!/bin/bash
# Weekly ML Adjustment Updates
#
# Runs every Sunday at 6 AM ET to update ML scoring tier adjustments
# This keeps the adjustments current as model performance evolves.
#
# Created: 2026-01-25
# Part of: Post-Grading Quality Improvements (Session 17)
#
# Usage:
#   ./bin/cron/weekly_ml_adjustments.sh
#
# Schedule with cron (run at 6 AM ET every Sunday):
#   0 6 * * 0 cd /home/naji/code/nba-stats-scraper && ./bin/cron/weekly_ml_adjustments.sh >> /var/log/nba-ml-adjustments.log 2>&1

set -euo pipefail

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Change to project root
cd "$PROJECT_ROOT"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "ERROR: Virtual environment not found at .venv/bin/activate"
    exit 1
fi

# Get current date
CURRENT_DATE=$(date +%Y-%m-%d)

# Log start
echo "=========================================="
echo "Weekly ML Adjustments Update"
echo "Date: $CURRENT_DATE"
echo "Started: $(date)"
echo "=========================================="

# Run ML adjustment backfill for current date
echo "Running scoring tier backfill..."
if python backfill_jobs/ml_feedback/scoring_tier_backfill.py --as-of-date "$CURRENT_DATE"; then
    echo "✅ ML adjustments updated successfully"
    exit_code=0
else
    echo "❌ ML adjustments failed"
    exit_code=1
fi

# Log completion
echo "=========================================="
echo "Completed: $(date)"
echo "Exit code: $exit_code"
echo "=========================================="

exit $exit_code
