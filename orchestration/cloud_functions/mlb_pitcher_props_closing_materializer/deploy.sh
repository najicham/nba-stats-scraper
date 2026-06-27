#!/bin/bash
# Deploy mlb-pitcher-props-closing-materialize Cloud Function (Gen2).
#
# Reads time-series snapshots from mlb_raw.oddsa_pitcher_props for the prior
# game_date and writes one closing row per (game_pk, player_lookup, bookmaker)
# into mlb_raw.pitcher_props_closing.
#
# Triggered by mlb-pitcher-props-closing-materialize scheduler at 09:00 UTC daily.

set -e

PROJECT="${PROJECT:-nba-props-platform}"
REGION="${REGION:-us-west2}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-756957797294-compute@developer.gserviceaccount.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(mktemp -d)"
trap "rm -rf $PKG_DIR" EXIT

echo "[1/3] Building deploy package at $PKG_DIR..."
cp "$SCRIPT_DIR/main.py" "$PKG_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$PKG_DIR/"

echo "[2/3] Deploying mlb-pitcher-props-closing-materialize Gen2 CF..."
cd "$PKG_DIR"
gcloud functions deploy mlb-pitcher-props-closing-materialize \
  --project="$PROJECT" \
  --region="$REGION" \
  --gen2 \
  --runtime=python311 \
  --source=. \
  --entry-point=main \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=512Mi \
  --timeout=540s \
  --max-instances=3 \
  --service-account="$SERVICE_ACCOUNT" \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT"

echo "[3/3] Ensuring scheduler service account has run.invoker..."
gcloud run services add-iam-policy-binding mlb-pitcher-props-closing-materialize \
  --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/run.invoker" >/dev/null

echo "✓ mlb-pitcher-props-closing-materialize deployed."
echo "  Scheduler: mlb-pitcher-props-closing-materialize (cron '0 9 * 3-10 *', UTC)"
