#!/bin/bash
#
# Weekly Pipeline Health Check
#
# Runs comprehensive validation to catch data gaps within 6 days.
# Prevents issues like the Phase 4 gap (3-month detection delay).
#
# Created: Jan 3, 2026
# Schedule: Run every Sunday at 8 AM
# Cron: 0 8 * * 0 /home/naji/code/nba-stats-scraper/scripts/monitoring/weekly_pipeline_health.sh
#

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs/monitoring"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/weekly_health_$TIMESTAMP.log"

# Create log directory
mkdir -p "$LOG_DIR"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "========================================="
log "WEEKLY PIPELINE HEALTH CHECK"
log "========================================="
log ""

# Calculate date ranges
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -d '7 days ago' +%Y-%m-%d)

log "Checking last 7 days: $START_DATE to $END_DATE"
log ""

# Run validation
log "Running multi-layer validation..."
cd "$PROJECT_ROOT"

if PYTHONPATH=. python3 scripts/validation/validate_pipeline_completeness.py \
    --start-date="$START_DATE" \
    --end-date="$END_DATE" \
    >> "$LOG_FILE" 2>&1; then
    log ""
    log "✅ VALIDATION PASSED - Pipeline healthy"
    EXIT_CODE=0
else
    log ""
    log "❌ VALIDATION FAILED - Gaps detected!"
    log "Review log: $LOG_FILE"
    EXIT_CODE=1
fi

# Archive old logs (keep last 30 days)
log ""
log "Cleaning up old logs (keeping last 30 days)..."
find "$LOG_DIR" -name "weekly_health_*.log" -mtime +30 -delete 2>/dev/null || true

log ""
log "========================================="
log "Health check complete"
log "Log saved to: $LOG_FILE"
log "========================================="

exit $EXIT_CODE
