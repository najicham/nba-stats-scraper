#!/bin/bash
# Deploy mlb-self-heal Cloud Function (Gen2)
# Mirrors NBA self-heal-predictions but for MLB pitcher strikeout pipeline.
# Triggered by mlb-self-heal-trigger scheduler at 12:45 PM ET, March-October only.

set -e

PROJECT="${PROJECT:-nba-props-platform}"
REGION="${REGION:-us-west2}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-756957797294-compute@developer.gserviceaccount.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PKG_DIR="$(mktemp -d)"
trap "rm -rf $PKG_DIR" EXIT

echo "[1/3] Building deploy package at $PKG_DIR..."
cp "$SCRIPT_DIR/main.py" "$PKG_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$PKG_DIR/"
cp -rL "$REPO_ROOT/shared" "$PKG_DIR/"

echo "[2/3] Deploying mlb-self-heal Gen2 CF..."
cd "$PKG_DIR"
gcloud functions deploy mlb-self-heal \
  --project="$PROJECT" \
  --region="$REGION" \
  --gen2 \
  --runtime=python311 \
  --source=. \
  --entry-point=mlb_self_heal_check \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=1Gi \
  --timeout=540s \
  --max-instances=3 \
  --service-account="$SERVICE_ACCOUNT" \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT"

echo "[3/3] Ensuring scheduler service account has run.invoker..."
gcloud run services add-iam-policy-binding mlb-self-heal \
  --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role="roles/run.invoker" >/dev/null

echo "✓ mlb-self-heal deployed. Scheduler: mlb-self-heal-trigger (45 12 * 3-10 *, America/New_York)"
