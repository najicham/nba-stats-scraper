#!/bin/bash
# bin/deployment/deploy_scrapers.sh - FIXED VERSION
# Combines the reliability of deploy_scrapers_simple.sh with the features of the original

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

# FIXED: Handle Dockerfile context issue (like deploy_scrapers_simple.sh)
echo "📋 Preparing Dockerfile context..."

# Check if scrapers/Dockerfile exists
if [ ! -f "scrapers/Dockerfile" ]; then
    echo "❌ scrapers/Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy scrapers Dockerfile to root for proper context
cp scrapers/Dockerfile ./Dockerfile

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

DEPLOY_STATUS=$?

# Cleanup: Remove temporary Dockerfile
echo "📋 Cleaning up temporary Dockerfile..."
rm ./Dockerfile

# Check deployment result
if [ $DEPLOY_STATUS -eq 0 ]; then
    SERVICE_URL=$(gcloud run services describe nba-scrapers --region us-west2 --format 'value(status.url)' 2>/dev/null)
    echo "✅ Deployed at: $SERVICE_URL"
    echo "🧪 Test with: make test-cloud-scrapers"
    
    # Optional: Quick health check
    echo "🔍 Testing health endpoint..."
    sleep 3
    HEALTH_RESULT=$(curl -s "$SERVICE_URL/health" 2>/dev/null | jq '.available_scrapers | length' 2>/dev/null || echo "pending...")
    echo "📊 Available scrapers: $HEALTH_RESULT"
else
    echo "❌ Deployment failed!"
    exit 1
fi