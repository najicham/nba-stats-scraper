#!/bin/bash
# Deploy Weekly Retrain Cloud Function
#
# Usage:
#   ./deploy.sh          # Deploy to production
#   ./deploy.sh dev      # Deploy dev version
#
# Session 458 - Weekly Auto-Retrain

set -e

ENVIRONMENT=${1:-prod}
REGION="us-west2"
PROJECT_ID="nba-props-platform"
GCS_BUCKET="nba-props-platform-models"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

if [ "$ENVIRONMENT" = "prod" ]; then
    FUNCTION_NAME="weekly-retrain"
else
    FUNCTION_NAME="weekly-retrain-dev"
fi

echo "=== Deploying Weekly Retrain Cloud Function ==="
echo "Environment: $ENVIRONMENT"
echo "Function:    $FUNCTION_NAME"
echo "Region:      $REGION"
echo "Memory:      4GiB / 2 CPU"
echo "Timeout:     1800s (30 min)"
echo ""

# Get function directory
FUNCTION_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$FUNCTION_DIR"

# Deploy
echo "Deploying Cloud Function..."

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime python311 \
    --region $REGION \
    --source . \
    --entry-point weekly_retrain \
    --trigger-http \
    --no-allow-unauthenticated \
    --timeout=1800 \
    --memory=4Gi \
    --cpu=2 \
    --update-env-vars GCP_PROJECT_ID=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-""} \
    --project $PROJECT_ID

# Get function URL
echo ""
echo "Getting function URL..."
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --gen2 --region $REGION --project $PROJECT_ID --format="value(serviceConfig.uri)")

echo ""
echo "=== Deployment Complete ==="
echo "Function URL: $FUNCTION_URL"
echo ""
echo "Test with:"
echo "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \"$FUNCTION_URL?dry_run=true\""
echo ""

# Scheduler setup
if [ "$ENVIRONMENT" = "prod" ]; then
    echo ""
    read -p "Create/update Cloud Scheduler job (Monday 5 AM ET)? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        SCHEDULER_JOB="weekly-retrain-job"

        if gcloud scheduler jobs describe $SCHEDULER_JOB --location=$REGION --project=$PROJECT_ID &>/dev/null; then
            echo "Updating existing scheduler job..."
            gcloud scheduler jobs update http $SCHEDULER_JOB \
                --location=$REGION \
                --schedule="0 5 * * 1" \
                --time-zone="America/New_York" \
                --uri="$FUNCTION_URL" \
                --http-method=POST \
                --oidc-service-account-email="$SERVICE_ACCOUNT" \
                --oidc-token-audience="$FUNCTION_URL" \
                --attempt-deadline=1800s \
                --project=$PROJECT_ID
        else
            echo "Creating new scheduler job..."
            gcloud scheduler jobs create http $SCHEDULER_JOB \
                --location=$REGION \
                --schedule="0 5 * * 1" \
                --time-zone="America/New_York" \
                --uri="$FUNCTION_URL" \
                --http-method=POST \
                --oidc-service-account-email="$SERVICE_ACCOUNT" \
                --oidc-token-audience="$FUNCTION_URL" \
                --attempt-deadline=1800s \
                --description="Weekly model retrain - every Monday 5 AM ET (Session 458)" \
                --project=$PROJECT_ID
        fi

        echo ""
        echo "Scheduler configured: Every Monday at 5 AM ET"
        echo ""
        echo "Test scheduler with:"
        echo "  gcloud scheduler jobs run $SCHEDULER_JOB --location=$REGION --project=$PROJECT_ID"
    fi
fi

echo ""
echo "=== Next Steps ==="
echo "1. Test dry run: curl with ?dry_run=true"
echo "2. Test real run: curl with ?family=v12_noveg_mae (single family)"
echo "3. Monitor: gcloud functions logs read $FUNCTION_NAME --gen2 --region $REGION --limit 50"
echo ""
