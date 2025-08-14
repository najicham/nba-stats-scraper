#!/bin/bash
# FILE: backfill/bp_props/deploy_bp_props_backfill.sh
# 
# Deploys BettingPros Historical Backfill as Cloud Run Job
# This job runs for ~4-6 hours, downloads historical prop data from 3 seasons, then terminates

set -e  # Exit on any error

# Configuration
JOB_NAME="nba-bp-backfill"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

echo "🏀 Deploying BettingPros Historical Backfill Job"
echo "==============================================="
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "backfill/bp_props/Dockerfile.bp_props_backfill" ]]; then
    echo "❌ Error: backfill/bp_props/Dockerfile.bp_props_backfill not found"
    echo "   Make sure you're running from project root"
    exit 1
fi

if [[ ! -f "backfill/bp_props/bp_props_backfill_job.py" ]]; then
    echo "❌ Error: backfill/bp_props/bp_props_backfill_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first (using same pattern as service deployment)
IMAGE_NAME="gcr.io/$PROJECT_ID/nba-bp-backfill"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists (same as deploy_scrapers_simple.sh)
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root (same pattern as deploy_scrapers_simple.sh)
cp backfill/bp_props/Dockerfile.bp_props_backfill ./Dockerfile

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
echo "🚀 To start the historical backfill (3 seasons: 2021-22, 2022-23, 2023-24):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "🧪 To test with single season (2021-22):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION \\"
echo "     --args=\"--seasons=2021 --limit=10\""
echo ""
echo "🔍 To dry run (see what would be processed):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION \\"
echo "     --args=\"--dry-run --seasons=2021\""
echo ""
echo "📊 To monitor progress:"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo "   Logs: gcloud logs read --filter=\"resource.labels.job_name=$JOB_NAME\" --limit=50"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./backfill/bp_props/deploy_bp_props_backfill.sh"
echo ""
echo "📁 Data will be stored in:"
echo "   Events: gs://nba-scraped-data/bettingpros/events/{date}/"
echo "   Props: gs://nba-scraped-data/bettingpros/player-props/points/{date}/"