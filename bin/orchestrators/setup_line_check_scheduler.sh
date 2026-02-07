#!/bin/bash
# Session 152: Setup schedulers for hourly line checks and morning summary
#
# Two schedulers:
# 1. line-check-hourly: Every hour 8 AM - 6 PM ET
#    - Detects new lines and line moves
#    - Triggers targeted re-prediction for affected players
#    - Phase 6 re-export happens automatically via event-driven flow
#
# 2. morning-summary: 7:30 AM ET daily
#    - Sends Slack summary of predictions, line coverage, feature quality
#    - Runs after overnight predictions complete (~7 AM)

set -euo pipefail

PROJECT_ID=${PROJECT_ID:-nba-props-platform}
REGION=${REGION:-us-west2}

echo "=== Setting up line check and morning summary schedulers ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Prediction coordinator endpoint
COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"

# Service account for Cloud Run invocation
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

# ============================================================================
# 1. Hourly Line Check (8 AM - 6 PM ET)
# ============================================================================
echo "Creating line-check-hourly scheduler..."
gcloud scheduler jobs delete line-check-hourly --location=$REGION --quiet 2>/dev/null || true

gcloud scheduler jobs create http line-check-hourly \
  --location=$REGION \
  --schedule="0 8-18 * * *" \
  --time-zone="America/New_York" \
  --uri="$COORDINATOR_URL/check-lines" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "TODAY"}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --description="Session 152: Hourly line check (8AM-6PM ET). Detects new/moved lines, triggers re-prediction."

echo "  Created: line-check-hourly (every hour 8 AM - 6 PM ET)"
echo ""

# ============================================================================
# 2. Morning Summary (7:30 AM ET)
# ============================================================================
echo "Creating morning-summary scheduler..."
gcloud scheduler jobs delete morning-summary --location=$REGION --quiet 2>/dev/null || true

gcloud scheduler jobs create http morning-summary \
  --location=$REGION \
  --schedule="30 7 * * *" \
  --time-zone="America/New_York" \
  --uri="$COORDINATOR_URL/morning-summary" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"game_date": "TODAY"}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --description="Session 152: Morning prediction/line coverage summary to Slack."

echo "  Created: morning-summary (7:30 AM ET daily)"
echo ""

# ============================================================================
# Summary
# ============================================================================
echo "=== Schedulers created successfully ==="
echo ""
echo "Schedule summary (all times ET):"
echo "  2:30 AM   - predictions-early: REAL_LINES_ONLY mode"
echo "  7:00 AM   - overnight-predictions: Full prediction run"
echo "  7:30 AM   - morning-summary: Slack coverage report"
echo "  8-6 PM    - line-check-hourly: Detect new/moved lines (11 runs/day)"
echo "  11:30 AM  - same-day-predictions: Catch late additions"
echo ""
echo "To verify:"
echo "  gcloud scheduler jobs list --location=$REGION --filter='name:line-check OR name:morning'"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run line-check-hourly --location=$REGION"
echo "  gcloud scheduler jobs run morning-summary --location=$REGION"
