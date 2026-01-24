#!/bin/bash
# Setup schedulers for same-day predictions
# These run in the morning to generate predictions for today's games
#
# Timeline (all times ET):
#   10:30 AM - Phase 3: UpcomingPlayerGameContextProcessor for TODAY
#   11:00 AM - Phase 4: MLFeatureStoreProcessor for TODAY (same-day mode)
#   11:30 AM - Phase 5: Prediction coordinator for TODAY
#   1:00 PM  - Phase 6: phase6-tonight-picks (existing) exports predictions

set -euo pipefail

PROJECT_ID=${PROJECT_ID:-nba-props-platform}
REGION=${REGION:-us-west2}

echo "=== Setting up same-day prediction schedulers ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Phase 3 endpoint
PHASE3_URL="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range"

# Phase 4 endpoint
PHASE4_URL="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date"

# Prediction coordinator endpoint
PREDICTION_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start"

# Get service account for Cloud Run invocation
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

echo "1. Creating same-day-phase3 scheduler (10:30 AM ET)..."
# Phase 3: Run UpcomingPlayerGameContextProcessor for TODAY
gcloud scheduler jobs delete same-day-phase3 --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http same-day-phase3 \
  --location=$REGION \
  --schedule="30 10 * * *" \
  --time-zone="America/New_York" \
  --uri="$PHASE3_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"start_date": "TODAY", "end_date": "TODAY", "processors": ["UpcomingPlayerGameContextProcessor"], "backfill_mode": true}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --description="Morning Phase 3 for today's games - UpcomingPlayerGameContext"

echo "2. Creating same-day-phase4 scheduler (11:00 AM ET)..."
# Phase 4: Run MLFeatureStoreProcessor for TODAY with same-day flags
gcloud scheduler jobs delete same-day-phase4 --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http same-day-phase4 \
  --location=$REGION \
  --schedule="0 11 * * *" \
  --time-zone="America/New_York" \
  --uri="$PHASE4_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"analysis_date": "TODAY", "processors": ["MLFeatureStoreProcessor"], "backfill_mode": false, "strict_mode": false, "skip_dependency_check": true}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --description="Morning Phase 4 for today's games - MLFeatureStore with same-day mode"

echo "3. Creating same-day-predictions scheduler (11:30 AM ET)..."
# Phase 5: Trigger prediction coordinator for TODAY
gcloud scheduler jobs delete same-day-predictions --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http same-day-predictions \
  --location=$REGION \
  --schedule="30 11 * * *" \
  --time-zone="America/New_York" \
  --uri="$PREDICTION_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"force": true}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --description="Morning predictions for today's games"

echo ""
echo "=== Schedulers created successfully ==="
echo ""
echo "Schedule summary (all times ET):"
echo "  10:30 AM - same-day-phase3: UpcomingPlayerGameContext"
echo "  11:00 AM - same-day-phase4: MLFeatureStore (same-day mode)"
echo "  11:30 AM - same-day-predictions: Prediction coordinator"
echo "  1:00 PM  - phase6-tonight-picks: Export predictions (existing)"
echo ""
echo "To verify:"
echo "  gcloud scheduler jobs list --location=$REGION"
echo ""
echo "To run immediately for testing:"
echo "  gcloud scheduler jobs run same-day-phase3 --location=$REGION"
echo "  gcloud scheduler jobs run same-day-phase4 --location=$REGION"
echo "  gcloud scheduler jobs run same-day-predictions --location=$REGION"
