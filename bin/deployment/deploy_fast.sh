#!/bin/bash
set -e

echo "⚡ NBA Scrapers - FAST DEPLOYMENT (30 seconds!)"

# Load environment variables
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Verify required API keys
if [ -z "$ODDS_API_KEY" ] || [ -z "$BDL_API_KEY" ]; then
    echo "❌ Required API keys not found in .env"
    exit 1
fi

# Check if we have a service image built
if [ ! -f ".last_image" ]; then
    echo "🔨 No service image found. Building service image..."
    ./bin/build_service.sh
fi

IMAGE=$(cat .last_image)
echo "🚀 Deploying service image: $IMAGE"

# Deploy the pre-built service image (30 seconds!)
gcloud run deploy nba-scrapers \
  --image "${IMAGE}" \
  --region us-west2 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --max-instances 10 \
  --set-env-vars="GCP_PROJECT=$(gcloud config get-value project)" \
  --set-env-vars="GCS_BUCKET_RAW=nba-analytics-raw-data" \
  --set-env-vars="GCS_BUCKET_PROCESSED=nba-analytics-processed-data" \
  --set-env-vars="ENVIRONMENT=production" \
  --set-env-vars="ODDS_API_KEY=${ODDS_API_KEY}" \
  --set-env-vars="BDL_API_KEY=${BDL_API_KEY}" \
  --set-env-vars="SENTRY_DSN=${SENTRY_DSN}"

SERVICE_URL=$(gcloud run services describe nba-scrapers --region us-west2 --format 'value(status.url)')
echo "✅ FAST deployment complete: $SERVICE_URL"
echo "🧪 Test with: make test"
