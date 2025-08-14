#!/bin/bash
# FILE: backfill/odds_api_props/deploy_odds_api_props_backfill.sh
# 
# Deploys NBA Odds API Season Backfill as Cloud Run Job
# This job runs for hours, collects historical props data for entire seasons, then terminates

set -e  # Exit on any error

# Configuration
JOB_NAME="nba-odds-api-season-backfill"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-756957797294.us-west2.run.app"

echo "🎯 Deploying NBA Odds API Season Backfill Job"
echo "=============================================="
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "backfill/odds_api_props/Dockerfile.odds_api_props_backfill" ]]; then
    echo "❌ Error: backfill/odds_api_props/Dockerfile.odds_api_props_backfill not found"
    echo "   Make sure you're running from project root"
    exit 1
fi

if [[ ! -f "backfill/odds_api_props/odds_api_props_backfill_job.py" ]]; then
    echo "❌ Error: backfill/odds_api_props/odds_api_props_backfill_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first (using same pattern as service deployment)
IMAGE_NAME="gcr.io/$PROJECT_ID/nba-odds-api-season-backfill"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists (same as deploy_scrapers_simple.sh)
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root (same pattern as deploy_scrapers_simple.sh)
cp backfill/odds_api_props/Dockerfile.odds_api_props_backfill ./Dockerfile

gcloud builds submit \
    --tag=$IMAGE_NAME \
    --project=$PROJECT_ID \
    --quiet

# Clean up temporary Dockerfile
rm ./Dockerfile

# Deploy the Cloud Run Job using the built image
echo ""

# 🔧 FIX: Delete existing job and create new one (simpler than YAML replace)
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
    --task-timeout=8h \
    --memory=2Gi \
    --cpu=1 \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL" \
    --quiet

echo ""
echo "✅ Job deployed successfully!"
echo ""
echo "🚀 To start the season backfill (safe to close laptop after this):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "🧪 For testing with dry run:"
echo "   gcloud run jobs execute $JOB_NAME --args=\"--dry-run --seasons=2023 --limit=5\" --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo "   Logs: gcloud logs read --filter=\"resource.labels.job_name=$JOB_NAME\" --limit=50"
echo "   Monitor script: ./bin/backfill/odds_api_props_monitor.sh quick"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./backfill/odds_api_props/deploy_odds_api_props_backfill.sh"
echo ""
echo "🎯 Next steps:"
echo "   1. Test: $JOB_NAME --args=\"--dry-run --seasons=2023 --limit=5\""
echo "   2. Single season: $JOB_NAME --args=\"--seasons=2023\""
echo "   3. Full backfill: $JOB_NAME --args=\"--seasons=2021,2022,2023,2024\""