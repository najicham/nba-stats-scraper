#!/bin/bash
# Deploy the Scraper Availability Monitor Cloud Function
#
# This function checks all key scrapers for data availability and sends alerts.
# Schedule: 8 AM ET daily (13:00 UTC)
#
# Usage:
#   ./deploy.sh              # Deploy function only
#   ./deploy.sh --scheduler  # Deploy function + create scheduler job

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="scraper-availability-monitor"
SERVICE_ACCOUNT="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🚀 Deploying ${FUNCTION_NAME}..."

# Deploy the Cloud Function
gcloud functions deploy ${FUNCTION_NAME} \
    --gen2 \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --runtime=python311 \
    --trigger-http \
    --entry-point=check_scraper_availability_handler \
    --timeout=120s \
    --memory=256MB \
    --set-env-vars="GCP_PROJECT=${PROJECT_ID}" \
    --service-account=${SERVICE_ACCOUNT} \
    --no-allow-unauthenticated \
    --source=.

echo "✅ Function deployed!"

# Get the function URL
FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME} \
    --gen2 \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --format='value(serviceConfig.uri)')

echo "📍 Function URL: ${FUNCTION_URL}"

# Create scheduler job if requested
if [[ "$1" == "--scheduler" ]]; then
    echo ""
    echo "📅 Creating Cloud Scheduler job..."

    SCHEDULER_NAME="scraper-availability-daily"

    # Delete existing job if it exists
    gcloud scheduler jobs delete ${SCHEDULER_NAME} \
        --project=${PROJECT_ID} \
        --location=${REGION} \
        --quiet 2>/dev/null || true

    # Create new scheduler job
    gcloud scheduler jobs create http ${SCHEDULER_NAME} \
        --project=${PROJECT_ID} \
        --location=${REGION} \
        --schedule="0 13 * * *" \
        --time-zone="UTC" \
        --uri="${FUNCTION_URL}" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{}' \
        --oidc-service-account-email=${SERVICE_ACCOUNT} \
        --attempt-deadline=180s \
        --description="Daily scraper availability check - 8 AM ET"

    echo "✅ Scheduler job created!"
    echo "   Name: ${SCHEDULER_NAME}"
    echo "   Schedule: 0 13 * * * UTC (8 AM ET)"
fi

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "To test manually:"
echo "  curl -X POST ${FUNCTION_URL} \\"
echo "    -H 'Authorization: Bearer \$(gcloud auth print-identity-token)' \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"date\": \"2026-01-20\"}'"
