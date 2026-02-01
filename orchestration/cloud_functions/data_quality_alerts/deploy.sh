#!/bin/bash
# Deploy Data Quality Alerts Cloud Function
#
# Usage:
#   ./deploy.sh [environment]
#
# Environment: prod (default) or dev

set -e

ENVIRONMENT=${1:-prod}
REGION="us-west2"
PROJECT_ID="nba-props-platform"

# Function name
if [ "$ENVIRONMENT" = "prod" ]; then
    FUNCTION_NAME="data-quality-alerts"
else
    FUNCTION_NAME="data-quality-alerts-dev"
fi

echo "=== Deploying Data Quality Alerts Cloud Function ==="
echo "Environment: $ENVIRONMENT"
echo "Function: $FUNCTION_NAME"
echo "Region: $REGION"
echo ""

# Check if we have required env vars
if [ -z "$SLACK_WEBHOOK_URL_ERROR" ]; then
    echo "⚠️  WARNING: SLACK_WEBHOOK_URL_ERROR not set"
    echo "   Alerts will not be sent for CRITICAL issues"
fi

if [ -z "$SLACK_WEBHOOK_URL_WARNING" ]; then
    echo "⚠️  WARNING: SLACK_WEBHOOK_URL_WARNING not set"
    echo "   Alerts will not be sent for WARNING issues"
fi

echo ""
read -p "Continue with deployment? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 1
fi

# Get repo root directory
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
FUNCTION_DIR="$(cd "$(dirname "$0")" && pwd)"

# Copy shared module for deployment (Session 57)
echo ""
echo "Copying shared module for deployment..."
mkdir -p "$FUNCTION_DIR/shared/utils"
cp "$REPO_ROOT/shared/__init__.py" "$FUNCTION_DIR/shared/" 2>/dev/null || echo "# Shared module init" > "$FUNCTION_DIR/shared/__init__.py"
cp "$REPO_ROOT/shared/utils/__init__.py" "$FUNCTION_DIR/shared/utils/" 2>/dev/null || echo "# Utils init" > "$FUNCTION_DIR/shared/utils/__init__.py"
cp "$REPO_ROOT/shared/utils/performance_diagnostics.py" "$FUNCTION_DIR/shared/utils/"
echo "✓ Shared module copied"

# Deploy function
echo ""
echo "Deploying Cloud Function..."

# Change to function directory for deployment (the --source . uses current directory)
cd "$FUNCTION_DIR"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime python311 \
    --region $REGION \
    --source . \
    --entry-point check_data_quality \
    --trigger-http \
    --allow-unauthenticated \
    --timeout=540 \
    --memory=512MB \
    --set-env-vars GCP_PROJECT_ID=$PROJECT_ID,SLACK_WEBHOOK_URL_ERROR=${SLACK_WEBHOOK_URL_ERROR},SLACK_WEBHOOK_URL_WARNING=${SLACK_WEBHOOK_URL_WARNING} \
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
echo "  curl \"$FUNCTION_URL?game_date=2026-01-26&dry_run=true\""
echo ""

# Ask about scheduler setup
if [ "$ENVIRONMENT" = "prod" ]; then
    echo ""
    read -p "Create/update Cloud Scheduler job? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        SCHEDULER_JOB="${FUNCTION_NAME}-job"

        # Check if job exists
        if gcloud scheduler jobs describe $SCHEDULER_JOB --location=$REGION --project=$PROJECT_ID &>/dev/null; then
            echo "Updating existing scheduler job..."
            gcloud scheduler jobs update http $SCHEDULER_JOB \
                --location=$REGION \
                --schedule="0 19 * * *" \
                --time-zone="America/New_York" \
                --uri="$FUNCTION_URL" \
                --http-method=GET \
                --project=$PROJECT_ID
        else
            echo "Creating new scheduler job..."
            gcloud scheduler jobs create http $SCHEDULER_JOB \
                --location=$REGION \
                --schedule="0 19 * * *" \
                --time-zone="America/New_York" \
                --uri="$FUNCTION_URL" \
                --http-method=GET \
                --description="Daily data quality checks for NBA predictions pipeline" \
                --project=$PROJECT_ID
        fi

        echo ""
        echo "Scheduler job configured to run daily at 7 PM ET"
        echo ""
        echo "Test scheduler with:"
        echo "  gcloud scheduler jobs run $SCHEDULER_JOB --location=$REGION --project=$PROJECT_ID"
    fi
fi

# Cleanup copied shared module
echo ""
echo "Cleaning up copied shared module..."
rm -rf "$FUNCTION_DIR/shared"
echo "✓ Cleanup complete"

echo ""
echo "=== Next Steps ==="
echo "1. Test the function with dry_run=true"
echo "2. Verify alerts are sent to correct Slack channels"
echo "3. Run with real data to confirm queries work"
echo "4. Monitor function logs for errors"
echo ""
echo "View logs with:"
echo "  gcloud functions logs read $FUNCTION_NAME --gen2 --region $REGION --limit 50 --project $PROJECT_ID"
