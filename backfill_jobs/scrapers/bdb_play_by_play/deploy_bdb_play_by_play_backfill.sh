#!/bin/bash
# FILE: backfill/bdb_play_by_play/deploy_bdb_play_by_play_backfill.sh
# 
# Deploys BigDataBall 2024-25 Season Backfill as Cloud Run Job
# This job runs for ~4-8 hours, downloads missing enhanced play-by-play data, then terminates

set -e  # Exit on any error

# Configuration
JOB_NAME="bdb-play-by-play-backfill"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

echo "🏀 Deploying BigDataBall 2024-25 Enhanced Play-by-Play Backfill Job"
echo "=================================================================="
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "backfill/bdb_play_by_play/Dockerfile.bdb_play_by_play_backfill" ]]; then
    echo "❌ Error: backfill/bdb_play_by_play/Dockerfile.bdb_play_by_play_backfill not found"
    echo "   Make sure you're running from project root"
    exit 1
fi

if [[ ! -f "backfill/bdb_play_by_play/bdb_play_by_play_backfill_job.py" ]]; then
    echo "❌ Error: backfill/bdb_play_by_play/bdb_play_by_play_backfill_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first (using same pattern as bp_props deployment)
IMAGE_NAME="gcr.io/$PROJECT_ID/bdb-play-by-play-backfill"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists (same as deploy_scrapers_simple.sh)
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root (same pattern as bp_props deployment)
cp backfill/bdb_play_by_play/Dockerfile.bdb_play_by_play_backfill ./Dockerfile

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
echo "🚀 To start the 2024-25 season backfill (entire season + playoffs):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "🧪 To test with limited date range:"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION \\"
echo "     --args=\"--start_date\",\"2024-10-01\",\"--end_date\",\"2024-11-01\""
echo ""
echo "🔍 To dry run (see what would be processed):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION \\"
echo "     --args=\"--dry-run\""
echo ""
echo "📊 To monitor progress:"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo "   Logs: gcloud logs read --filter=\"resource.labels.job_name=$JOB_NAME\" --limit=50"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./backfill/bdb_play_by_play/deploy_bdb_play_by_play_backfill.sh"
echo ""
echo "📁 Data will be stored in:"
echo "   gs://nba-scraped-data/big-data-ball/2024-25/{date}/game_{game_id}/"
echo ""
echo "🔧 Debugging tools:"
echo "   Manual discovery: curl \"$SERVICE_URL/bigdataball_discovery?date=2024-10-15\""
echo "   Manual download: curl \"$SERVICE_URL/bigdataball_pbp?game_id=0022500001&export_groups=dev\""