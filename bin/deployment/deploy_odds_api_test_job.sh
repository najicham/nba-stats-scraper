#!/bin/bash
# FILE: bin/deployment/deploy_odds_api_test_job.sh
# 
# Deploys Odds API Single-Day Test as Cloud Run Job
# Based on the proven gamebook deployment pattern

set -e  # Exit on any error

# Configuration
JOB_NAME="odds-api-single-day-test"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-756957797294.us-west2.run.app"

echo "🎯 Deploying Odds API Single-Day Test Job"
echo "=========================================="
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "scripts/Dockerfile.odds_api_test" ]]; then
    echo "❌ Error: scripts/Dockerfile.odds_api_test not found"
    echo "   Make sure you're running from project root"
    exit 1
fi

if [[ ! -f "scripts/odds_api_single_day_test_job.py" ]]; then
    echo "❌ Error: scripts/odds_api_single_day_test_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first
IMAGE_NAME="gcr.io/$PROJECT_ID/odds-api-single-day-test"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root
cp scripts/Dockerfile.odds_api_test ./Dockerfile

gcloud builds submit \
    --tag=$IMAGE_NAME \
    --project=$PROJECT_ID \
    --quiet

# Clean up temporary Dockerfile
rm ./Dockerfile

# Deploy the Cloud Run Job using the built image
echo ""

# Delete existing job and create new one (simpler than YAML replace)
if gcloud run jobs describe $JOB_NAME --region=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo "📝 Job exists - deleting and recreating with new image..."
    gcloud run jobs delete $JOB_NAME \
        --region=$REGION \
        --project=$PROJECT_ID \
        --quiet
    echo "   ✅ Old job deleted"
fi

echo "🆕 Creating job with updated image..."
gcloud run jobs create $JOB_NAME \
    --image=$IMAGE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --task-timeout=30m \
    --memory=1Gi \
    --cpu=1 \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL" \
    --quiet

echo ""
echo "✅ Job deployed successfully!"
echo ""
echo "🚀 To start the single-day test (April 10, 2024):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "🔍 To run dry-run first (recommended):"
echo "   gcloud run jobs execute $JOB_NAME --args=\"--dry-run\" --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo "   Logs: gcloud logs read --filter=\"resource.labels.job_name=$JOB_NAME\" --limit=50"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./bin/deployment/deploy_odds_api_test_job.sh"