#!/bin/bash
# Deploy Monthly Retrain Cloud Function
#
# Usage:
#   ./deploy.sh [environment]
#
# Creates a Cloud Function that runs monthly to retrain the model

set -e

ENVIRONMENT=${1:-prod}
REGION="us-west2"
PROJECT_ID="nba-props-platform"
GCS_BUCKET="nba-ml-models"

if [ "$ENVIRONMENT" = "prod" ]; then
    FUNCTION_NAME="monthly-retrain"
else
    FUNCTION_NAME="monthly-retrain-dev"
fi

echo "=== Deploying Monthly Retrain Cloud Function ==="
echo "Environment: $ENVIRONMENT"
echo "Function: $FUNCTION_NAME"
echo "Region: $REGION"
echo ""

# Check for Slack webhook
if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo "⚠️  WARNING: SLACK_WEBHOOK_URL not set"
    echo "   Notifications will not be sent"
fi

echo ""
read -p "Continue with deployment? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 1
fi

# Get function directory
FUNCTION_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$FUNCTION_DIR"

# Deploy
echo ""
echo "Deploying Cloud Function..."

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime python311 \
    --region $REGION \
    --source . \
    --entry-point monthly_retrain \
    --trigger-http \
    --allow-unauthenticated \
    --timeout=540 \
    --memory=4Gi \
    --cpu=2 \
    --set-env-vars GCP_PROJECT_ID=$PROJECT_ID,GCS_BUCKET=$GCS_BUCKET,SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-""} \
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
echo "  curl \"$FUNCTION_URL?dry_run=true\""
echo ""

# Ask about scheduler setup
if [ "$ENVIRONMENT" = "prod" ]; then
    echo ""
    read -p "Create/update Cloud Scheduler job (1st of month at 6 AM ET)? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        SCHEDULER_JOB="${FUNCTION_NAME}-job"

        if gcloud scheduler jobs describe $SCHEDULER_JOB --location=$REGION --project=$PROJECT_ID &>/dev/null; then
            echo "Updating existing scheduler job..."
            gcloud scheduler jobs update http $SCHEDULER_JOB \
                --location=$REGION \
                --schedule="0 6 1 * *" \
                --time-zone="America/New_York" \
                --uri="$FUNCTION_URL" \
                --http-method=POST \
                --project=$PROJECT_ID
        else
            echo "Creating new scheduler job..."
            gcloud scheduler jobs create http $SCHEDULER_JOB \
                --location=$REGION \
                --schedule="0 6 1 * *" \
                --time-zone="America/New_York" \
                --uri="$FUNCTION_URL" \
                --http-method=POST \
                --description="Monthly model retrain - runs 1st of each month at 6 AM ET" \
                --project=$PROJECT_ID
        fi

        echo ""
        echo "Scheduler job configured to run on 1st of each month at 6 AM ET"
        echo ""
        echo "Test scheduler with:"
        echo "  gcloud scheduler jobs run $SCHEDULER_JOB --location=$REGION --project=$PROJECT_ID"
    fi
fi

echo ""
echo "=== Next Steps ==="
echo "1. Test the function with dry_run=true"
echo "2. Run a real test: curl -X POST $FUNCTION_URL"
echo "3. Monitor logs: gcloud functions logs read $FUNCTION_NAME --gen2 --region $REGION --limit 50"
echo ""
