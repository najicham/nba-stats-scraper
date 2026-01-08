#!/bin/bash
# Deploy MLB Self-Heal Cloud Function
#
# This function runs before Phase 6 exports to check for missing predictions
# and trigger healing pipelines if necessary.
#
# Schedule: 12:45 PM ET daily (during MLB season)
#
# Usage: ./bin/orchestrators/mlb/deploy_mlb_self_heal.sh

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
FUNCTION_NAME="mlb-self-heal"
ENTRY_POINT="mlb_self_heal_check"
RUNTIME="python311"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SOURCE_DIR="$PROJECT_ROOT/orchestration/cloud_functions/mlb_self_heal"

echo "========================================"
echo " Deploying MLB Self-Heal Function"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo "Entry Point: $ENTRY_POINT"
echo ""

# Check source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: Source directory not found: $SOURCE_DIR"
    exit 1
fi

# Deploy the function
echo "Deploying Cloud Function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --runtime="$RUNTIME" \
    --region="$REGION" \
    --source="$SOURCE_DIR" \
    --entry-point="$ENTRY_POINT" \
    --trigger-http \
    --allow-unauthenticated \
    --memory=512Mi \
    --timeout=300s \
    --min-instances=0 \
    --max-instances=1 \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID" \
    --project="$PROJECT_ID"

# Get function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --gen2 \
    --format="value(serviceConfig.uri)")

echo ""
echo "========================================"
echo " Deployment Complete"
echo "========================================"
echo "Function URL: $FUNCTION_URL"
echo ""

# Test health endpoint
echo "Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s "${FUNCTION_URL}/health" 2>/dev/null || echo '{"error": "no response"}')
echo "$HEALTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$HEALTH_RESPONSE"

# Create scheduler job (paused by default - MLB is off-season)
echo ""
echo "Creating Cloud Scheduler job (PAUSED)..."

SCHEDULER_NAME="mlb-self-heal-daily"

# Check if scheduler job exists
if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "Scheduler job already exists, updating..."
    gcloud scheduler jobs update http "$SCHEDULER_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="45 12 * * *" \
        --time-zone="America/New_York" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --description="MLB Self-heal check - runs 15 min before Phase 6 exports"
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http "$SCHEDULER_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="45 12 * * *" \
        --time-zone="America/New_York" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --description="MLB Self-heal check - runs 15 min before Phase 6 exports"
fi

# Pause the job (MLB off-season)
gcloud scheduler jobs pause "$SCHEDULER_NAME" --location="$REGION" --project="$PROJECT_ID"
echo "Scheduler job paused (MLB off-season)"

echo ""
echo "========================================"
echo " Setup Complete"
echo "========================================"
echo ""
echo "Function: $FUNCTION_URL"
echo "Scheduler: $SCHEDULER_NAME (PAUSED)"
echo ""
echo "To enable before MLB season:"
echo "  gcloud scheduler jobs resume $SCHEDULER_NAME --location=$REGION"
echo ""
echo "To test manually:"
echo "  curl -X POST $FUNCTION_URL"
echo ""
