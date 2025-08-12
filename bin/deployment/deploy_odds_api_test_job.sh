#!/bin/bash
# FILE: bin/deployment/deploy_odds_api_test_job.sh
# 
# Deploys Odds API Single-Day Test as Cloud Run Job
# Based on the proven gamebook deployment pattern
# UPDATED: Enhanced with better error handling and validation

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

# Check if running from project root
if [[ ! -f "scrapers/main_scraper_service.py" ]]; then
    echo "❌ Error: Must run from project root directory"
    echo "   Current directory: $(pwd)"
    echo "   Expected files: scrapers/main_scraper_service.py"
    exit 1
fi

# Verify required files exist
echo "🔍 Checking required files..."
required_files=(
    "scripts/Dockerfile.odds_api_test"
    "scripts/odds_api_single_day_test_job.py"
    "scrapers/utils/nba_team_mapper.py"
    "scrapers/oddsapi/oddsa_events_his.py"
    "scrapers/oddsapi/oddsa_player_props_his.py"
)

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "❌ Error: Required file not found: $file"
        echo "   Make sure all scraper files are in place"
        exit 1
    else
        echo "   ✅ $file"
    fi
done

echo ""
echo "✅ All required files found"

# Check if gcloud is authenticated and project is set
echo ""
echo "🔍 Verifying GCP authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    echo "❌ Error: Not authenticated with gcloud"
    echo "   Run: gcloud auth login"
    exit 1
fi

CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [[ "$CURRENT_PROJECT" != "$PROJECT_ID" ]]; then
    echo "⚠️  Warning: Current project is '$CURRENT_PROJECT', expected '$PROJECT_ID'"
    echo "   Setting project to $PROJECT_ID..."
    gcloud config set project $PROJECT_ID
fi

echo "✅ GCP authentication verified"

# Check if the scraper service is running
echo ""
echo "🔍 Checking scraper service availability..."
if curl -s --max-time 10 "${SERVICE_URL}/health" > /dev/null; then
    echo "✅ Scraper service is responding at $SERVICE_URL"
else
    echo "⚠️  Warning: Scraper service not responding at $SERVICE_URL"
    echo "   The job will fail if the service isn't running"
    echo "   Continue anyway? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled"
        exit 1
    fi
fi

# Build and push the image first
IMAGE_NAME="gcr.io/$PROJECT_ID/odds-api-single-day-test"
echo ""
echo "🏗️  Building Docker image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    BACKUP_NAME="Dockerfile.backup.$(date +%s)"
    echo "📋 Backing up existing root Dockerfile to $BACKUP_NAME..."
    mv Dockerfile "$BACKUP_NAME"
fi

# Copy Dockerfile to root for Cloud Build
cp scripts/Dockerfile.odds_api_test ./Dockerfile

echo "   Building image: $IMAGE_NAME"
if gcloud builds submit \
    --tag="$IMAGE_NAME" \
    --project="$PROJECT_ID" \
    --quiet; then
    echo "✅ Image built successfully"
else
    echo "❌ Failed to build image"
    rm -f ./Dockerfile  # Clean up
    exit 1
fi

# Clean up temporary Dockerfile
rm -f ./Dockerfile

# Deploy the Cloud Run Job using the built image
echo ""
echo "🚀 Deploying Cloud Run Job..."

# Delete existing job if it exists
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "📝 Job '$JOB_NAME' exists - deleting and recreating..."
    if gcloud run jobs delete "$JOB_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --quiet; then
        echo "   ✅ Old job deleted"
    else
        echo "   ❌ Failed to delete old job"
        exit 1
    fi
fi

echo "🆕 Creating job with updated image..."
if gcloud run jobs create "$JOB_NAME" \
    --image="$IMAGE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --task-timeout=30m \
    --memory=1Gi \
    --cpu=1 \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL" \
    --quiet; then
    echo "✅ Job created successfully"
else
    echo "❌ Failed to create job"
    exit 1
fi

echo ""
echo "🎉 Deployment completed successfully!"
echo ""
echo "🚀 Testing Commands:"
echo "   # Dry run (recommended first):"
echo "   gcloud run jobs execute $JOB_NAME --args=\"--dry-run\" --region=$REGION"
echo ""
echo "   # Test with 2 events only:"
echo "   gcloud run jobs execute $JOB_NAME --args=\"--limit-events=2\" --region=$REGION"
echo ""
echo "   # Full test (all ~8 events):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "📊 Monitoring Commands:"
echo "   # View job status:"
echo "   gcloud run jobs describe $JOB_NAME --region=$REGION"
echo ""
echo "   # View execution logs:"
echo "   gcloud logs read --filter=\"resource.labels.job_name=$JOB_NAME\" --limit=50"
echo ""
echo "   # Follow logs in real-time:"
echo "   gcloud logs tail --filter=\"resource.labels.job_name=$JOB_NAME\""
echo ""
echo "⏸️  Management Commands:"
echo "   # Cancel running execution:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "   # Delete job completely:"
echo "   gcloud run jobs delete $JOB_NAME --region=$REGION"
echo ""
echo "🔄 To redeploy with updates:"
echo "   ./bin/deployment/deploy_odds_api_test_job.sh"
echo ""
echo "📂 Expected GCS Results:"
echo "   Events: gs://nba-scraped-data/odds-api/events-history/2024-04-10/"
echo "   Props:  gs://nba-scraped-data/odds-api/player-props-history/2024-04-10/"
echo "           └─ {event_id}-LALDET/{timestamp}-snap-0400.json"