#!/bin/bash
JOB_NAME="nba-odds-api-backfill"
REGION="us-west2"
SERVICE_URL="https://nba-scrapers-756957797294.us-west2.run.app"

IMAGE_NAME="gcr.io/nba-props-platform/nba-odds-api-backfill"

# Copy Dockerfile to root temporarily
cp scripts/Dockerfile.odds_api_backfill Dockerfile

# Build
gcloud builds submit --tag=$IMAGE_NAME --quiet .

# Clean up
rm Dockerfile

# Deploy job
gcloud run jobs delete $JOB_NAME --region=$REGION --quiet 2>/dev/null || true
gcloud run jobs create $JOB_NAME \
    --image=$IMAGE_NAME \
    --region=$REGION \
    --task-timeout=8h \
    --memory=2Gi \
    --cpu=1 \
    --max-retries=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL"

echo "✅ Job deployed successfully!"