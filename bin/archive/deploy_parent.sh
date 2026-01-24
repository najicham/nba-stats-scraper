#!/bin/bash
set -euo pipefail

echo "🚀 Deploying NBA Scrapers from parent directory (preserves module structure)..."

# Load environment variables
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Check required API keys
if [ -z "$ODDS_API_KEY" ] || [ -z "$BDL_API_KEY" ]; then
    echo "❌ Required API keys not found in .env"
    exit 1
fi

echo "✅ API keys loaded: ODDS_API_KEY (${#ODDS_API_KEY} chars), BDL_API_KEY (${#BDL_API_KEY} chars)"

# Deploy from root directory (--source . means current directory)
gcloud run deploy nba-scrapers \
  --source . \
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
echo "✅ Deployed at: $SERVICE_URL"
echo "🧪 Test with: make test"
