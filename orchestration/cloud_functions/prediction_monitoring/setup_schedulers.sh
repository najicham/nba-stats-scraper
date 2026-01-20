#!/bin/bash
# Setup Cloud Scheduler Jobs for Prediction Monitoring
#
# Creates 3 scheduled jobs:
# 1. validate-freshness-check: Before predictions (5:45 PM ET / 22:45 UTC)
# 2. missing-prediction-check: After predictions complete (7:00 PM ET / 00:00 UTC)
# 3. daily-reconciliation: Full pipeline validation (9:00 AM ET / 14:00 UTC)
#
# Author: Claude Code
# Created: 2026-01-18
# Session: 106

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION="us-west2"
TIMEZONE="America/New_York"

# Cloud Function URLs (update after deployment)
VALIDATE_URL="https://$REGION-$PROJECT_ID.cloudfunctions.net/validate-freshness"
CHECK_MISSING_URL="https://$REGION-$PROJECT_ID.cloudfunctions.net/check-missing"
RECONCILE_URL="https://$REGION-$PROJECT_ID.cloudfunctions.net/reconcile"

echo "========================================"
echo "Setting up Prediction Monitoring Schedulers"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timezone: $TIMEZONE"
echo ""

# Job 1: Data Freshness Validation (before predictions)
# Runs at 5:45 PM ET (15 min before same-day-predictions-tomorrow at 6 PM)
echo "1/3 Creating validate-freshness-check scheduler..."
gcloud scheduler jobs create http validate-freshness-check \
    --location=$REGION \
    --schedule="45 17 * * *" \
    --time-zone=$TIMEZONE \
    --uri="$VALIDATE_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"game_date":"TOMORROW","max_age_hours":24}' \
    --attempt-deadline=540s \
    --description="Validate data freshness before tomorrow's predictions run (5:45 PM ET)" \
    || echo "Job already exists, updating..."

gcloud scheduler jobs update http validate-freshness-check \
    --location=$REGION \
    --schedule="45 17 * * *" \
    --time-zone=$TIMEZONE \
    --uri="$VALIDATE_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"game_date":"TOMORROW","max_age_hours":24}' \
    || true

echo "✅ validate-freshness-check scheduler created (5:45 PM ET daily)"
echo ""

# Job 2: Missing Prediction Check (after predictions)
# Runs at 7:00 PM ET (1 hour after predictions complete)
echo "2/3 Creating missing-prediction-check scheduler..."
gcloud scheduler jobs create http missing-prediction-check \
    --location=$REGION \
    --schedule="0 19 * * *" \
    --time-zone=$TIMEZONE \
    --uri="$CHECK_MISSING_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"game_date":"TOMORROW"}' \
    --attempt-deadline=540s \
    --description="Check for missing predictions after batch completes (7:00 PM ET)" \
    || echo "Job already exists, updating..."

gcloud scheduler jobs update http missing-prediction-check \
    --location=$REGION \
    --schedule="0 19 * * *" \
    --time-zone=$TIMEZONE \
    --uri="$CHECK_MISSING_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"game_date":"TOMORROW"}' \
    || true

echo "✅ missing-prediction-check scheduler created (7:00 PM ET daily)"
echo ""

# Job 3: Daily Reconciliation (morning after games)
# Runs at 9:00 AM ET (reconcile previous day's full pipeline)
echo "3/3 Creating daily-reconciliation scheduler..."
gcloud scheduler jobs create http daily-reconciliation \
    --location=$REGION \
    --schedule="0 9 * * *" \
    --time-zone=$TIMEZONE \
    --uri="$RECONCILE_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"game_date":"TODAY"}' \
    --attempt-deadline=540s \
    --description="Full end-to-end pipeline reconciliation (9:00 AM ET)" \
    || echo "Job already exists, updating..."

gcloud scheduler jobs update http daily-reconciliation \
    --location=$REGION \
    --schedule="0 9 * * *" \
    --time-zone=$TIMEZONE \
    --uri="$RECONCILE_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"game_date":"TODAY"}' \
    || true

echo "✅ daily-reconciliation scheduler created (9:00 AM ET daily)"
echo ""

echo "========================================"
echo "All schedulers created successfully!"
echo "========================================"
echo ""
echo "Schedule Summary:"
echo "  5:45 PM ET - Validate data freshness (before predictions)"
echo "  7:00 PM ET - Check for missing predictions (after predictions)"
echo "  9:00 AM ET - Full daily reconciliation (morning after games)"
echo ""
echo "View schedulers:"
echo "  gcloud scheduler jobs list --location=$REGION | grep -E 'validate-freshness|missing-prediction|daily-reconciliation'"
echo ""
echo "Test manually:"
echo "  gcloud scheduler jobs run validate-freshness-check --location=$REGION"
echo "  gcloud scheduler jobs run missing-prediction-check --location=$REGION"
echo "  gcloud scheduler jobs run daily-reconciliation --location=$REGION"
