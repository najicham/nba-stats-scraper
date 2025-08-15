#!/bin/bash
# FILE: backfill/nbac_injury/deploy_nbac_injury_backfill.sh
# 
# Deploys NBA Injury Reports Backfill as Cloud Run Job
# This job runs for ~8-12 hours, collects injury reports using 30-minute intervals, then terminates

set -e  # Exit on any error

# Configuration
JOB_NAME="nba-injury-backfill"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

echo "🏥 Deploying NBA Injury Reports Backfill Job"
echo "============================================"
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "backfill/nbac_injury/Dockerfile.nbac_injury_backfill" ]]; then
    echo "❌ Error: backfill/nbac_injury/Dockerfile.nbac_injury_backfill not found"
    echo "   Make sure you're running from project root"
    exit 1
fi

if [[ ! -f "backfill/nbac_injury/nbac_injury_backfill_job.py" ]]; then
    echo "❌ Error: backfill/nbac_injury/nbac_injury_backfill_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first (using same pattern as service deployment)
IMAGE_NAME="gcr.io/$PROJECT_ID/nba-injury-backfill"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists (same as deploy_scrapers_simple.sh)
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root (same pattern as deploy_scrapers_simple.sh)
cp backfill/nbac_injury/Dockerfile.nbac_injury_backfill ./Dockerfile

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
    --task-timeout=24h \
    --memory=4Gi \
    --cpu=2 \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL" \
    --quiet

echo ""
echo "✅ Job deployed successfully!"
echo ""
echo "🚀 To start the injury reports backfill:"
echo "   # Dry run first (see what would be processed):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION --args='--dry-run --seasons=2024 --limit=20'"
echo ""
echo "   # Small test (10 intervals):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION --args='--seasons=2024 --limit=10'"
echo ""
echo "   # Full 4-season backfill (~8-12 hours):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo "   Monitor: ./bin/backfill/nbac_injury_monitor.sh quick"
echo "   Watch: ./bin/backfill/nbac_injury_monitor.sh watch"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./backfill/nbac_injury/deploy_nbac_injury_backfill.sh"