#!/bin/bash
# bin/schedulers/setup_mlb_schedulers.sh
#
# Create Cloud Scheduler jobs for MLB pipeline automation.
# Jobs are created PAUSED by default since MLB is in off-season.
# Enable them before MLB season starts (~March 20, 2026).
#
# Usage:
#   ./bin/schedulers/setup_mlb_schedulers.sh           # Create paused
#   ./bin/schedulers/setup_mlb_schedulers.sh --enable  # Create and enable
#
# Created: 2026-01-07

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
TIMEZONE="America/New_York"

# Service URLs
SCRAPERS_URL="https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app"
ANALYTICS_URL="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
PRECOMPUTE_URL="https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
PREDICTIONS_URL="https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"
GRADING_URL="https://mlb-phase6-grading-f7p3g7f6ya-wl.a.run.app"

# Check for --paused flag (default is enabled)
PAUSE_AFTER=false
if [[ "$1" == "--paused" ]]; then
    PAUSE_AFTER=true
    echo "Will PAUSE scheduler jobs after creation"
else
    echo "Creating ENABLED scheduler jobs (use --paused to pause after creation)"
fi

echo ""
echo "=============================================="
echo "  MLB Cloud Scheduler Setup"
echo "=============================================="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Timezone: $TIMEZONE"
echo "=============================================="
echo ""

create_job() {
    local JOB_NAME=$1
    local SCHEDULE=$2
    local URL=$3
    local BODY=$4
    local DESC=$5

    echo -n "Creating $JOB_NAME... "

    # Check if exists
    if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
        echo "already exists"
        return 0
    fi

    if gcloud scheduler jobs create http "$JOB_NAME" \
        --schedule="$SCHEDULE" \
        --uri="$URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="$BODY" \
        --time-zone="$TIMEZONE" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --description="$DESC" \
        2>/dev/null; then

        echo -n "created"

        # Pause if requested
        if [[ "$PAUSE_AFTER" == "true" ]]; then
            gcloud scheduler jobs pause "$JOB_NAME" --location="$REGION" --project="$PROJECT_ID" 2>/dev/null
            echo " (paused) ✓"
        else
            echo " ✓"
        fi
    else
        echo "FAILED"
    fi
}

echo "=== Phase 1: Scrapers ==="

# Morning schedule fetch (10 AM ET - before games)
create_job \
    "mlb-schedule-daily" \
    "0 10 * * *" \
    "$SCRAPERS_URL/execute-workflow" \
    '{"workflow": "mlb_schedule"}' \
    "Fetch MLB schedule and probable pitchers"

# Lineups - multiple times as they're announced
create_job \
    "mlb-lineups-morning" \
    "0 11 * * *" \
    "$SCRAPERS_URL/scrape" \
    '{"scraper": "mlb_lineups", "date": "TODAY"}' \
    "Fetch starting lineups (morning)"

create_job \
    "mlb-lineups-pregame" \
    "0 13 * * *" \
    "$SCRAPERS_URL/scrape" \
    '{"scraper": "mlb_lineups", "date": "TODAY"}' \
    "Refresh starting lineups (pregame)"

# Pitcher props
create_job \
    "mlb-props-morning" \
    "30 10 * * *" \
    "$SCRAPERS_URL/scrape" \
    '{"scraper": "mlb_pitcher_props", "date": "TODAY"}' \
    "Fetch pitcher strikeout lines (morning)"

create_job \
    "mlb-props-pregame" \
    "30 12 * * *" \
    "$SCRAPERS_URL/scrape" \
    '{"scraper": "mlb_pitcher_props", "date": "TODAY"}' \
    "Refresh pitcher strikeout lines (pregame)"

# Live box scores during games (1 PM - 11 PM ET, every 5 minutes)
create_job \
    "mlb-live-boxscores" \
    "*/5 13-23 * * *" \
    "$SCRAPERS_URL/scrape" \
    '{"scraper": "mlb_live_box_scores", "date": "TODAY"}' \
    "Live game data every 5 minutes"

# Overnight final results (2 AM ET - after late west coast games)
create_job \
    "mlb-overnight-results" \
    "0 2 * * *" \
    "$SCRAPERS_URL/scrape" \
    '{"scraper": "mlb_box_scores", "date": "YESTERDAY"}' \
    "Final box scores for yesterday"

echo ""
echo "=== Phase 5: Predictions ==="

# Generate predictions after lineups are finalized
create_job \
    "mlb-predictions-generate" \
    "0 13 * * *" \
    "$PREDICTIONS_URL/predict-batch" \
    '{"game_date": "TODAY"}' \
    "Generate pitcher strikeout predictions"

# Shadow mode A/B testing (V1.4 vs V1.6) - runs 30 min after predictions
create_job \
    "mlb-shadow-mode-daily" \
    "30 13 * * *" \
    "$PREDICTIONS_URL/execute-shadow-mode" \
    '{"game_date": "TODAY"}' \
    "Run shadow mode comparison (V1.4 vs V1.6)"

echo ""
echo "=== Phase 6: Grading ==="

# Grade yesterday's predictions (morning after games complete)
create_job \
    "mlb-grading-daily" \
    "0 10 * * *" \
    "$GRADING_URL/grade-date" \
    '{"game_date": "YESTERDAY"}' \
    "Grade yesterday predictions"

# Grade shadow mode predictions (V1.4 vs V1.6) - runs after regular grading
create_job \
    "mlb-shadow-grading-daily" \
    "30 10 * * *" \
    "$GRADING_URL/grade-shadow" \
    '{}' \
    "Grade shadow mode predictions"

echo ""
echo "=============================================="
echo "  Scheduler Setup Complete"
echo "=============================================="
echo ""
echo "Jobs created (11 total):"
echo "  mlb-schedule-daily        10:00 AM - Fetch schedule"
echo "  mlb-lineups-morning       11:00 AM - Get lineups"
echo "  mlb-lineups-pregame        1:00 PM - Refresh lineups"
echo "  mlb-props-morning         10:30 AM - Get K lines"
echo "  mlb-props-pregame         12:30 PM - Refresh K lines"
echo "  mlb-live-boxscores        Every 5 min (1-11 PM)"
echo "  mlb-overnight-results      2:00 AM - Final scores"
echo "  mlb-predictions-generate   1:00 PM - Make predictions"
echo "  mlb-shadow-mode-daily      1:30 PM - Shadow mode A/B test"
echo "  mlb-grading-daily         10:00 AM - Grade yesterday"
echo "  mlb-shadow-grading-daily  10:30 AM - Grade shadow mode"
echo ""
if [[ "$PAUSE_AFTER" == "true" ]]; then
    echo "All jobs are PAUSED. To enable before MLB season:"
    echo "  gcloud scheduler jobs resume mlb-schedule-daily --location=$REGION"
    echo "  # Or enable all:"
    echo "  for job in \$(gcloud scheduler jobs list --location=$REGION --format='value(name)' | grep mlb); do"
    echo "    gcloud scheduler jobs resume \$job --location=$REGION"
    echo "  done"
else
    echo "All jobs are ENABLED. To pause during off-season:"
    echo "  for job in \$(gcloud scheduler jobs list --location=$REGION --format='value(name)' | grep mlb); do"
    echo "    gcloud scheduler jobs pause \$job --location=$REGION"
    echo "  done"
fi
echo ""
echo "To list MLB scheduler jobs:"
echo "  gcloud scheduler jobs list --location=$REGION | grep mlb"
