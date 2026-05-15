#!/bin/bash
# Deploy mlb-regime-monitor Cloud Function (Gen2).
#
# B1 daily monitor of MLB UNDER regime quality. Reads
# `mlb_predictions.prediction_accuracy`, evaluates T1/T3/T4 triggers,
# persists state in `mlb_orchestration.direction_regime_state`, and posts
# a Slack alert to #nba-betting-signals on HEALTHY <-> DEGRADING transitions.
#
# Triggered by mlb-regime-monitor-daily scheduler at 09:00 UTC.

set -e

PROJECT="${PROJECT:-nba-props-platform}"
REGION="${REGION:-us-west2}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-756957797294-compute@developer.gserviceaccount.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(mktemp -d)"
trap "rm -rf $PKG_DIR" EXIT

# TODO (Path A Tier 3, deferred 2026-05-15): create a `slack-webhook-signals`
# secret for #nba-betting-signals and migrate via --set-secrets pattern below.
# Currently the SLACK_WEBHOOK_URL_SIGNALS env var is unset live (empty), so
# alerts silently no-op until either: (a) the secret is created and bound,
# or (b) the operator sets SLACK_WEBHOOK_URL_SIGNALS in their shell.
SLACK_SIGNALS="${SLACK_WEBHOOK_URL_SIGNALS:-}"
if [ -z "$SLACK_SIGNALS" ]; then
    echo "⚠️  WARNING: SLACK_WEBHOOK_URL_SIGNALS not set (alerts will no-op)."
fi

echo "[1/3] Building deploy package at $PKG_DIR..."
cp "$SCRIPT_DIR/main.py" "$PKG_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$PKG_DIR/"

echo "[2/3] Deploying mlb-regime-monitor Gen2 CF..."
cd "$PKG_DIR"
gcloud functions deploy mlb-regime-monitor \
  --project="$PROJECT" \
  --region="$REGION" \
  --gen2 \
  --runtime=python311 \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=512Mi \
  --timeout=120s \
  --max-instances=2 \
  --service-account="$SERVICE_ACCOUNT" \
  --update-env-vars="GCP_PROJECT_ID=$PROJECT,SLACK_WEBHOOK_URL_SIGNALS=${SLACK_SIGNALS}"

echo "[3/3] Ensuring scheduler service account has run.invoker..."
gcloud run services add-iam-policy-binding mlb-regime-monitor \
  --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/run.invoker" >/dev/null

echo "✓ mlb-regime-monitor deployed."
echo "  Scheduler: mlb-regime-monitor-daily (cron '0 9 * 3-10 *', UTC)"
echo "  Add via: ./bin/schedulers/setup_mlb_schedulers.sh"
