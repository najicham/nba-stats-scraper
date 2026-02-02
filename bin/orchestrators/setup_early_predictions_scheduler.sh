#!/bin/bash
# Setup scheduler for early predictions
# Runs at 2:30 AM ET to generate predictions as soon as lines are available
#
# Timeline (all times ET):
#   2:00 AM  - nba-props-morning scraper runs (7 AM UTC)
#   2:15 AM  - Lines typically available in bettingpros
#   2:30 AM  - predictions-early: Generate predictions for players WITH real lines
#   7:00 AM  - overnight-predictions: Full prediction run (all players)
#
# Session 74: Earlier Prediction Timing
# Vegas lines are available at 2 AM ET, but predictions were waiting until 7 AM.
# This scheduler runs immediately after lines are available.
#
# Key feature: require_real_lines=true
# - Only generates predictions for players with ACTUAL betting lines
# - Skips players with NO_PROP_LINE (no real line available)
# - Results in higher quality predictions (no estimated lines)

set -euo pipefail

PROJECT_ID=${PROJECT_ID:-nba-props-platform}
REGION=${REGION:-us-west2}

echo "=== Setting up early predictions scheduler ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Prediction coordinator endpoint
PREDICTION_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start"

# Get service account for Cloud Run invocation
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

echo "Creating predictions-early scheduler (2:30 AM ET)..."
# Delete existing job if present
gcloud scheduler jobs delete predictions-early --location=$REGION --quiet 2>/dev/null || true

# Create new scheduler with require_real_lines=true
gcloud scheduler jobs create http predictions-early \
  --location=$REGION \
  --schedule="30 2 * * *" \
  --time-zone="America/New_York" \
  --uri="$PREDICTION_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "TODAY", "require_real_lines": true, "force": true}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --description="Early predictions (2:30 AM ET) - REAL LINES ONLY mode. Session 74."

echo ""
echo "=== Scheduler created successfully ==="
echo ""
echo "Schedule summary (all times ET):"
echo "  2:30 AM  - predictions-early: REAL_LINES_ONLY mode (~140 players)"
echo "  7:00 AM  - overnight-predictions: ALL_PLAYERS mode (full run)"
echo "  11:30 AM - same-day-predictions: Catch late additions"
echo ""
echo "To verify:"
echo "  gcloud scheduler jobs describe predictions-early --location=$REGION"
echo ""
echo "To run immediately for testing:"
echo "  gcloud scheduler jobs run predictions-early --location=$REGION"
echo ""
echo "To check line availability first:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(DISTINCT player_lookup) FROM nba_raw.bettingpros_player_points_props WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL\""
