#!/bin/bash
# Deploy Live Export Cloud Function and Schedulers
#
# This deploys:
# 1. Cloud Function for live score exports
# 2. Cloud Scheduler jobs for frequent updates during game windows
#
# Usage:
#   ./bin/deploy/deploy_live_export.sh
#   ./bin/deploy/deploy_live_export.sh --function-only
#   ./bin/deploy/deploy_live_export.sh --schedulers-only

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-nba-props-platform}"
REGION="us-west2"
FUNCTION_NAME="live-export"
SERVICE_ACCOUNT="processor-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Parse arguments
DEPLOY_FUNCTION=true
DEPLOY_SCHEDULERS=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --function-only)
            DEPLOY_SCHEDULERS=false
            shift
            ;;
        --schedulers-only)
            DEPLOY_FUNCTION=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== Live Export Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Deploy Cloud Function
if [ "$DEPLOY_FUNCTION" = true ]; then
    echo "=== Deploying Cloud Function ==="

    cd "$PROJECT_ROOT"

    # Copy dependencies to function directory temporarily
    FUNC_SRC="$PROJECT_ROOT/orchestration/cloud_functions/live_export"
    echo "Preparing function source with dependencies..."

    # Copy needed modules (copy entire directories to ensure all dependencies)
    mkdir -p "$FUNC_SRC/data_processors"
    mkdir -p "$FUNC_SRC/shared"

    # Copy entire directories (base_exporter needs shared.clients, shared.utils, shared.config)
    cp -r "$PROJECT_ROOT/data_processors/publishing" "$FUNC_SRC/data_processors/"
    cp -r "$PROJECT_ROOT/shared/clients" "$FUNC_SRC/shared/"
    cp -r "$PROJECT_ROOT/shared/utils" "$FUNC_SRC/shared/"
    cp -r "$PROJECT_ROOT/shared/config" "$FUNC_SRC/shared/"

    # Ensure __init__.py files exist
    touch "$FUNC_SRC/data_processors/__init__.py"
    touch "$FUNC_SRC/shared/__init__.py"

    # Fetch BDL API key from Secret Manager
    BDL_API_KEY=$(gcloud secrets versions access latest --secret=BDL_API_KEY --project="$PROJECT_ID" 2>/dev/null || echo "")
    if [ -z "$BDL_API_KEY" ]; then
        echo "⚠️  WARNING: BDL_API_KEY not found in Secret Manager"
        echo "   Live box scores will not work without this key"
    fi

    # Deploy as HTTP-triggered function (better for frequent calls)
    gcloud functions deploy "$FUNCTION_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --runtime=python311 \
        --memory=512MB \
        --timeout=120s \
        --max-instances=5 \
        --min-instances=0 \
        --entry-point=main \
        --trigger-http \
        --allow-unauthenticated \
        --service-account="$SERVICE_ACCOUNT" \
        --source="$FUNC_SRC" \
        --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=nba-props-platform-api,BDL_API_KEY=$BDL_API_KEY" \
        --no-gen2

    # Clean up copied files
    echo "Cleaning up temporary files..."
    rm -rf "$FUNC_SRC/data_processors"
    rm -rf "$FUNC_SRC/shared"

    # Get the function URL
    FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --format="value(httpsTrigger.url)")

    echo "Function URL: $FUNCTION_URL"
    echo ""
fi

# Deploy Cloud Scheduler jobs
if [ "$DEPLOY_SCHEDULERS" = true ]; then
    echo "=== Deploying Cloud Scheduler Jobs ==="

    # Get function URL if not already set
    if [ -z "$FUNCTION_URL" ]; then
        FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
            --project="$PROJECT_ID" \
            --region="$REGION" \
            --format="value(httpsTrigger.url)" 2>/dev/null || echo "")
    fi

    if [ -z "$FUNCTION_URL" ]; then
        echo "Error: Function URL not found. Deploy the function first."
        exit 1
    fi

    # Delete existing schedulers if they exist
    for job in live-export-evening live-export-late-night; do
        gcloud scheduler jobs delete "$job" \
            --project="$PROJECT_ID" \
            --location="$REGION" \
            --quiet 2>/dev/null || true
    done

    # Evening games window: 7 PM - 11 PM ET (every 3 minutes)
    # Cron: */3 19-23 * * * (every 3 minutes from 7 PM to 11:59 PM)
    echo "Creating evening scheduler (7 PM - 11:59 PM ET, every 3 min)..."
    gcloud scheduler jobs create http live-export-evening \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="*/3 19-23 * * *" \
        --time-zone="America/New_York" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"target_date": "today"}' \
        --attempt-deadline=120s \
        --description="Live scores export during evening games (7 PM - midnight ET)"

    # Late night window: 12 AM - 1 AM ET (every 3 minutes)
    # Cron: */3 0-1 * * * (every 3 minutes from midnight to 1:59 AM)
    echo "Creating late-night scheduler (12 AM - 1:59 AM ET, every 3 min)..."
    gcloud scheduler jobs create http live-export-late-night \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="*/3 0-1 * * *" \
        --time-zone="America/New_York" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"target_date": "today"}' \
        --attempt-deadline=120s \
        --description="Live scores export during late-night games (midnight - 2 AM ET)"

    echo ""
    echo "Schedulers deployed:"
    gcloud scheduler jobs list --project="$PROJECT_ID" --location="$REGION" \
        --filter="name:live-export" --format="table(name,schedule,state)"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "To test manually:"
echo "  curl -X POST '$FUNCTION_URL' -H 'Content-Type: application/json' -d '{\"target_date\": \"$(date +%Y-%m-%d)\"}'"
echo ""
echo "To check logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --limit=50"
echo ""
