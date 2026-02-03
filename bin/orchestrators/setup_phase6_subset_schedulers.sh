#!/usr/bin/env bash
#
# Setup Phase 6 Subset Export Schedulers
#
# Updates existing schedulers to include new subset exporters:
# 1. phase6-hourly-trends - Add subset-performance (hourly refresh)
# 2. phase6-daily-results - Add subset-definitions (daily update)
#
# Usage:
#   ./setup_phase6_subset_schedulers.sh [--dry-run]
#

set -euo pipefail

PROJECT_ID="nba-props-platform"
LOCATION="us-west2"
TOPIC="nba-phase6-export-trigger"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}DRY RUN MODE - No changes will be made${NC}"
    echo
fi

echo "==========================================="
echo "Phase 6 Subset Export Scheduler Setup"
echo "==========================================="
echo "Project: $PROJECT_ID"
echo "Location: $LOCATION"
echo

# Function to update or create scheduler
update_scheduler() {
    local job_name=$1
    local schedule=$2
    local message_body=$3
    local description=$4

    echo -e "${GREEN}Configuring: $job_name${NC}"
    echo "  Schedule: $schedule"
    echo "  Message: $message_body"
    echo

    if $DRY_RUN; then
        echo -e "${YELLOW}  [DRY RUN] Would update scheduler${NC}"
        return
    fi

    # Check if job exists
    if gcloud scheduler jobs describe "$job_name" --location="$LOCATION" &>/dev/null; then
        # Update existing job
        gcloud scheduler jobs update pubsub "$job_name" \
            --location="$LOCATION" \
            --schedule="$schedule" \
            --topic="$TOPIC" \
            --message-body="$message_body" \
            --description="$description" \
            --quiet

        echo -e "${GREEN}  ✓ Updated existing scheduler${NC}"
    else
        # Create new job
        gcloud scheduler jobs create pubsub "$job_name" \
            --location="$LOCATION" \
            --schedule="$schedule" \
            --topic="$TOPIC" \
            --message-body="$message_body" \
            --description="$description" \
            --time-zone="America/New_York"

        echo -e "${GREEN}  ✓ Created new scheduler${NC}"
    fi
    echo
}

# 1. Update hourly trends to include subset-performance
update_scheduler \
    "phase6-hourly-trends" \
    "0 6-23 * * *" \
    '{"export_types": ["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays", "subset-performance"], "target_date": "today"}' \
    "Hourly trend exports + subset performance (6 AM - 11 PM ET)"

# 2. Update daily results to include subset-definitions
update_scheduler \
    "phase6-daily-results" \
    "0 5 * * *" \
    '{"export_types": ["results", "performance", "best-bets", "subset-definitions"], "target_date": "yesterday"}' \
    "Daily results export + subset definitions (5 AM ET)"

echo "==========================================="
echo "Summary"
echo "==========================================="
echo
echo "Updated Schedulers:"
echo "  1. phase6-hourly-trends"
echo "     - Runs: Every hour 6 AM - 11 PM ET"
echo "     - Exports: trends + subset-performance"
echo
echo "  2. phase6-daily-results"
echo "     - Runs: Daily at 5 AM ET"
echo "     - Exports: results + subset-definitions"
echo
echo "Event-Driven Exports (via phase5_to_phase6):"
echo "  - subset-picks (after predictions complete)"
echo "  - daily-signals (after predictions complete)"
echo
echo -e "${GREEN}✓ Setup complete!${NC}"
echo
echo "Next steps:"
echo "  1. Deploy phase5_to_phase6 orchestrator:"
echo "     cd orchestration/cloud_functions/phase5_to_phase6"
echo "     gcloud functions deploy phase5-to-phase6 --region=us-west2"
echo
echo "  2. Test manual export:"
echo "     PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \\"
echo "       --date $(date +%Y-%m-%d) \\"
echo "       --only subset-picks,daily-signals,subset-performance,subset-definitions"
echo
