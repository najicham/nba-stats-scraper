#!/bin/bash
# FILE: bin/deployment/deploy_gamebook_job.sh
# 
# Deploys NBA Gamebook Backfill as Cloud Run Job
# This job runs for ~6 hours, downloads 5,583 PDFs, then terminates

set -e  # Exit on any error

# Configuration
JOB_NAME="nba-gamebook-backfill"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

echo "🏀 Deploying NBA Gamebook Backfill Job"
echo "======================================"
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "scripts/Dockerfile.gamebook" ]]; then
    echo "❌ Error: scripts/Dockerfile.gamebook not found"
    echo "   Make sure you're running from project root"
    exit 1
fi

if [[ ! -f "scripts/gamebook_backfill_job.py" ]]; then
    echo "❌ Error: scripts/gamebook_backfill_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first (using same pattern as service deployment)
IMAGE_NAME="gcr.io/$PROJECT_ID/nba-gamebook-backfill"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists (same as deploy_scrapers_simple.sh)
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root (same pattern as deploy_scrapers_simple.sh)
cp scripts/Dockerfile.gamebook ./Dockerfile

gcloud builds submit \
    --tag=$IMAGE_NAME \
    --project=$PROJECT_ID \
    --quiet

# Clean up temporary Dockerfile
rm ./Dockerfile

# Deploy the Cloud Run Job using the built image
echo ""
echo "Creating Cloud Run Job..."

gcloud run jobs create $JOB_NAME \
    --image=$IMAGE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --task-timeout=7h \
    --memory=2Gi \
    --cpu=1 \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL" \
    --quiet

echo ""
echo "✅ Job deployed successfully!"
echo ""
echo "🚀 To start the 6-hour backfill (safe to close laptop after this):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo "   Logs: gcloud logs read --filter=\"resource.labels.job_name=$JOB_NAME\" --limit=50"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./bin/deploy_gamebook_job.sh"