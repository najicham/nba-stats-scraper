#!/bin/bash
# Deploy MLB BigQuery snapshot Cloud Function + Scheduler.
#
# Snapshots prediction_accuracy / signal_best_bets_picks / pitcher_strikeouts
# into mlb_predictions_backups daily 11 AM ET. Closes the 30-day BQ recovery
# window beyond BQ's 7-day time-travel.
set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="mlb-snapshot-daily"
SCHEDULER_JOB_NAME="mlb-snapshot-daily"
SCHEDULE="0 11 * * *"
TIME_ZONE="America/New_York"

echo "Deploying $FUNCTION_NAME ..."

gcloud functions deploy "$FUNCTION_NAME" \
  --project="$PROJECT_ID" \
  --gen2 \
  --runtime=python311 \
  --region="$REGION" \
  --source=cloud_functions/mlb_snapshot_daily \
  --entry-point=mlb_snapshot_daily \
  --trigger-http \
  --no-allow-unauthenticated \
  --timeout=540s \
  --memory=256MB \
  --max-instances=1 \
  --update-env-vars=PROJECT_ID="$PROJECT_ID"

FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --gen2 \
  --format='value(serviceConfig.uri)')

INVOKER_SA="756957797294-compute@developer.gserviceaccount.com"

echo "Function URL: $FUNCTION_URL"

# Allow the scheduler SA to invoke the function.
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --member="serviceAccount:${INVOKER_SA}" \
  --role=roles/run.invoker >/dev/null

if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  echo "Updating existing scheduler job ..."
  gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --oidc-service-account-email="$INVOKER_SA" \
    --oidc-token-audience="$FUNCTION_URL" \
    --attempt-deadline=540s
else
  echo "Creating new scheduler job ..."
  gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --oidc-service-account-email="$INVOKER_SA" \
    --oidc-token-audience="$FUNCTION_URL" \
    --attempt-deadline=540s \
    --description="Daily MLB BQ snapshot — pick tables to mlb_predictions_backups"
fi

echo "Deploy complete."
echo "  Manual trigger: gcloud scheduler jobs run $SCHEDULER_JOB_NAME --location=$REGION --project=$PROJECT_ID"
