#!/bin/bash
# Deploy the nba-monitoring-alerts Cloud Function.
#
# Standalone CF (no shared/ deps). HTTP-triggered; invoked every 4h by the
# existing `nba-monitoring-alerts` Cloud Scheduler job (OIDC, compute SA).
# This deploy does NOT create/modify the scheduler — it already exists.
#
# Env vars: `gcloud functions deploy` PRESERVES existing env vars when neither
# --set-env-vars nor --update-env-vars is passed. Do NOT add --set-env-vars here
# (it would wipe LOG_LEVEL / LOG_EXECUTION_ID and any SLACK_WEBHOOK_URL).
#
# Usage: ./deploy.sh

set -e

REGION="us-west2"
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="nba-monitoring-alerts"
SCHED_SA="756957797294-compute@developer.gserviceaccount.com"

FUNCTION_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$FUNCTION_DIR"

echo "=== Deploying $FUNCTION_NAME ($REGION) ==="

gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --runtime python311 \
    --region "$REGION" \
    --source . \
    --entry-point run_all_checks \
    --trigger-http \
    --no-allow-unauthenticated \
    --timeout=300 \
    --memory=512MB \
    --project "$PROJECT_ID"

# Ensure the scheduler's runtime SA can still invoke after redeploy.
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
    --region="$REGION" --project="$PROJECT_ID" \
    --role="roles/run.invoker" \
    --member="serviceAccount:${SCHED_SA}" >/dev/null 2>&1 || true

FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --gen2 --region "$REGION" --project "$PROJECT_ID" --format="value(serviceConfig.uri)")
echo ""
echo "=== Deployed. URL: $FUNCTION_URL ==="
echo "Verify a clean run:"
echo "  gcloud scheduler jobs run nba-monitoring-alerts --location=$REGION --project=$PROJECT_ID"
echo "  gcloud functions logs read $FUNCTION_NAME --gen2 --region $REGION --limit 40 --project $PROJECT_ID"
