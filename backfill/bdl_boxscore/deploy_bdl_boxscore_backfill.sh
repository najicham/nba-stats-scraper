#!/bin/bash
# FILE: backfill/bdl_boxscore/deploy_bdl_boxscore_backfill.sh
# 
# Deploys Ball Don't Lie Boxscore Backfill as Cloud Run Job
# This job runs for ~15-20 minutes, downloads boxscores for 4 seasons, then terminates

set -e  # Exit on any error

# Configuration
JOB_NAME="bdl-boxscore-backfill"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

echo "🏀 Deploying Ball Don't Lie Boxscore Backfill Job"
echo "=================================================="
echo "Job Name: $JOB_NAME"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "Service URL: $SERVICE_URL"
echo ""

# Verify required files exist
if [[ ! -f "backfill/bdl_boxscore/Dockerfile.bdl_boxscore_backfill" ]]; then
    echo "❌ Error: backfill/bdl_boxscore/Dockerfile.bdl_boxscore_backfill not found"
    echo "   Creating Dockerfile..."
    # Create the Dockerfile if it doesn't exist
    cat > backfill/bdl_boxscore/Dockerfile.bdl_boxscore_backfill << 'EOF'
# Dockerfile for Ball Don't Lie Boxscore Backfill Cloud Run Job
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Run the backfill job
CMD ["python", "backfill/bdl_boxscore/bdl_boxscore_backfill_job.py"]
EOF
    echo "✅ Created Dockerfile"
fi

if [[ ! -f "backfill/bdl_boxscore/bdl_boxscore_backfill_job.py" ]]; then
    echo "❌ Error: backfill/bdl_boxscore/bdl_boxscore_backfill_job.py not found"
    echo "   Make sure the job script exists"
    exit 1
fi

echo "✅ Required files found"

# Build and push the image first
IMAGE_NAME="gcr.io/$PROJECT_ID/bdl-boxscore-backfill"
echo ""
echo "Building image (this may take 2-3 minutes)..."

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy Dockerfile to root
cp backfill/bdl_boxscore/Dockerfile.bdl_boxscore_backfill ./Dockerfile

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
echo "🚀 To start the 15-20 minute backfill (much faster than gamebook!):"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "🧪 To test with single season (2023-24):"
echo "   gcloud run jobs execute $JOB_NAME \\"
echo "     --args=\"--service-url=$SERVICE_URL --seasons=2023\" \\"
echo "     --region=$REGION"
echo ""
echo "🔍 To dry run (see what would be processed):"
echo "   gcloud run jobs execute $JOB_NAME \\"
echo "     --args=\"--service-url=$SERVICE_URL --dry-run\" \\"
echo "     --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   ./bin/backfill/bdl_boxscore_monitor.sh"
echo "   Cloud Console: https://console.cloud.google.com/run/jobs/details/$REGION/$JOB_NAME"
echo ""
echo "⏸️  To stop if needed:"
echo "   gcloud run jobs cancel $JOB_NAME --region=$REGION"
echo ""
echo "📈 Expected performance:"
echo "   - Rate: 600 req/min (10x faster than gamebook backfill)"
echo "   - Duration: 15-20 minutes for all 4 seasons"
echo "   - Data: ~800-1000 unique game dates"
echo ""
echo "🔄 To update and redeploy:"
echo "   ./backfill/bdl_boxscore/deploy_bdl_boxscore_backfill.sh"