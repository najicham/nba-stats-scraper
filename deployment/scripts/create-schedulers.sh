#!/bin/bash
set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_ACCOUNT_EMAIL="mlb-monitoring-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Creating MLB Cloud Schedulers..."

# Monitoring Schedulers

echo "1/9: mlb-gap-detection-daily..."
gcloud scheduler jobs delete mlb-gap-detection-daily --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-gap-detection-daily \
  --location=$REGION \
  --schedule="0 13 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-gap-detection:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "2/9: mlb-freshness-checker-hourly..."
gcloud scheduler jobs delete mlb-freshness-checker-hourly --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-freshness-checker-hourly \
  --location=$REGION \
  --schedule="0 */2 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-freshness-checker:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "3/9: mlb-prediction-coverage-pregame..."
gcloud scheduler jobs delete mlb-prediction-coverage-pregame --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-prediction-coverage-pregame \
  --location=$REGION \
  --schedule="0 22 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-prediction-coverage:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "4/9: mlb-prediction-coverage-postgame..."
gcloud scheduler jobs delete mlb-prediction-coverage-postgame --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-prediction-coverage-postgame \
  --location=$REGION \
  --schedule="0 7 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-prediction-coverage:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "5/9: mlb-stall-detector-hourly..."
gcloud scheduler jobs delete mlb-stall-detector-hourly --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-stall-detector-hourly \
  --location=$REGION \
  --schedule="0 * * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-stall-detector:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

# Validator Schedulers

echo "6/9: mlb-schedule-validator-daily..."
gcloud scheduler jobs delete mlb-schedule-validator-daily --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-schedule-validator-daily \
  --location=$REGION \
  --schedule="0 11 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-schedule-validator:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "7/9: mlb-pitcher-props-validator-4hourly..."
gcloud scheduler jobs delete mlb-pitcher-props-validator-4hourly --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-pitcher-props-validator-4hourly \
  --location=$REGION \
  --schedule="0 10,14,18,22,2,6 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-pitcher-props-validator:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "8/9: mlb-prediction-coverage-validator-pregame..."
gcloud scheduler jobs delete mlb-prediction-coverage-validator-pregame --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-prediction-coverage-validator-pregame \
  --location=$REGION \
  --schedule="0 22 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-prediction-coverage-validator:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo "9/9: mlb-prediction-coverage-validator-postgame..."
gcloud scheduler jobs delete mlb-prediction-coverage-validator-postgame --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs create http mlb-prediction-coverage-validator-postgame \
  --location=$REGION \
  --schedule="0 7 * 4-10 *" \
  --time-zone="UTC" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/mlb-prediction-coverage-validator:run" \
  --http-method=POST \
  --oauth-service-account-email=$SERVICE_ACCOUNT_EMAIL \
  --quiet

echo ""
echo "✅ All 9 Cloud Schedulers created successfully!"
echo ""
echo "Verify with: gcloud scheduler jobs list --location=$REGION | grep mlb-"
