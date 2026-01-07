#!/bin/bash
###############################################################################
# Deploy BigQuery Backup Cloud Function
#
# Creates Cloud Function and Cloud Scheduler job for daily backups
#
# Usage:
#   ./bin/operations/deploy_backup_function.sh
#
# Created: 2026-01-03 (Session 7)
###############################################################################

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="bigquery-backup"
SCHEDULER_JOB_NAME="bigquery-daily-backup"
SCHEDULE="0 2 * * *"  # Daily at 2:00 AM PST
TIME_ZONE="America/Los_Angeles"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}[$(date +%T)]${NC} Deploying BigQuery backup infrastructure..."

# Step 1: Deploy Cloud Function
echo -e "${GREEN}[$(date +%T)]${NC} Deploying Cloud Function: $FUNCTION_NAME"

gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=cloud_functions/bigquery_backup \
  --entry-point=backup_bigquery_tables \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=3600s \
  --memory=512MB \
  --max-instances=1 \
  --set-env-vars=PROJECT_ID=$PROJECT_ID

echo -e "${GREEN}[$(date +%T)]${NC} Cloud Function deployed successfully"

# Get function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME \
  --region=$REGION \
  --gen2 \
  --format='value(serviceConfig.uri)')

echo -e "${GREEN}[$(date +%T)]${NC} Function URL: $FUNCTION_URL"

# Step 2: Create Cloud Scheduler job
echo -e "${GREEN}[$(date +%T)]${NC} Creating Cloud Scheduler job: $SCHEDULER_JOB_NAME"

# Check if job already exists
if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$REGION &>/dev/null; then
  echo -e "${YELLOW}[$(date +%T)]${NC} Scheduler job already exists, updating..."

  gcloud scheduler jobs update http $SCHEDULER_JOB_NAME \
    --location=$REGION \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$FUNCTION_URL?type=daily" \
    --http-method=POST \
    --attempt-deadline=3600s
else
  echo -e "${GREEN}[$(date +%T)]${NC} Creating new scheduler job..."

  gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
    --location=$REGION \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$FUNCTION_URL?type=daily" \
    --http-method=POST \
    --attempt-deadline=3600s \
    --description="Daily BigQuery table backups to GCS"
fi

echo -e "${GREEN}[$(date +%T)]${NC} Cloud Scheduler job configured successfully"

# Step 3: Test the function
echo -e "${GREEN}[$(date +%T)]${NC} Testing backup function..."
echo -e "${YELLOW}[$(date +%T)]${NC} This will trigger a test backup (may take a few minutes)..."

curl -X POST "$FUNCTION_URL?type=daily" -H "Content-Type: application/json" -d '{}' || \
  echo -e "${YELLOW}[$(date +%T)]${NC} Function test failed (may need authentication setup)"

echo ""
echo -e "${GREEN}[$(date +%T)]${NC} ================================================================"
echo -e "${GREEN}[$(date +%T)]${NC} Deployment Complete!"
echo -e "${GREEN}[$(date +%T)]${NC} ================================================================"
echo ""
echo -e "  Function Name:     $FUNCTION_NAME"
echo -e "  Function URL:      $FUNCTION_URL"
echo -e "  Scheduler Job:     $SCHEDULER_JOB_NAME"
echo -e "  Schedule:          $SCHEDULE ($TIME_ZONE)"
echo -e "  Next Run:          $(date -d 'tomorrow 02:00' '+%Y-%m-%d %H:%M %Z' 2>/dev/null || echo 'Check Cloud Console')"
echo ""
echo -e "  Manual trigger:    gcloud scheduler jobs run $SCHEDULER_JOB_NAME --location=$REGION"
echo -e "  View logs:         gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50"
echo -e "  List backups:      gsutil ls gs://nba-bigquery-backups/"
echo ""
echo -e "${GREEN}[$(date +%T)]${NC} Automated daily backups are now enabled!"
