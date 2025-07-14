#!/bin/bash
set -e

echo "🚀 Deploying NBA Scrapers to Cloud Run..."

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    # Export variables from .env file (skip comments and empty lines)
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo "✅ Environment variables loaded"
else
    echo "⚠️  No .env file found, checking for required environment variables..."
fi

# Check required API keys
echo "🔑 Checking required API keys..."

if [ -z "$ODDS_API_KEY" ]; then
    echo "❌ ODDS_API_KEY not found in .env file or environment"
    exit 1
fi
echo "✅ ODDS_API_KEY loaded (${#ODDS_API_KEY} characters)"

if [ -z "$BDL_API_KEY" ]; then
    echo "❌ BDL_API_KEY not found in .env file or environment" 
    exit 1
fi
echo "✅ BDL_API_KEY loaded (${#BDL_API_KEY} characters)"

# Use PROJECT_ID from .env if available, otherwise fall back to gcloud config
if [ -n "$PROJECT_ID" ]; then
    GCP_PROJECT="$PROJECT_ID"
else
    GCP_PROJECT=$(gcloud config get-value project)
fi
echo "✅ Using project: $GCP_PROJECT"

cd scrapers

echo "🏗️  Deploying to Cloud Run..."
gcloud run deploy nba-scrapers \
  --source . \
  --region us-west2 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --max-instances 10 \
  --concurrency 10 \
  --set-env-vars="GCP_PROJECT=${GCP_PROJECT}" \
  --set-env-vars="GCS_BUCKET_RAW=${GCS_BUCKET_RAW:-nba-analytics-raw-data}" \
  --set-env-vars="GCS_BUCKET_PROCESSED=${GCS_BUCKET_PROCESSED:-nba-analytics-processed-data}" \
  --set-env-vars="BIGQUERY_DATASET=${BIGQUERY_DATASET:-nba_analytics}" \
  --set-env-vars="ENVIRONMENT=production" \
  --set-env-vars="LOG_LEVEL=${LOG_LEVEL:-INFO}" \
  --set-env-vars="ODDS_API_KEY=${ODDS_API_KEY}" \
  --set-env-vars="BDL_API_KEY=${BDL_API_KEY}" \
  --set-env-vars="SENTRY_DSN=${SENTRY_DSN}"

cd ..

SERVICE_URL=$(gcloud run services describe nba-scrapers --region us-west2 --format 'value(status.url)')
echo "✅ Deployed at: $SERVICE_URL"
echo "🧪 Test with: make test-cloud-scrapers"
