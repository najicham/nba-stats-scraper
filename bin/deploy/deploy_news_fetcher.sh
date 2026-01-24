#!/bin/bash
# Deploy News Fetcher Cloud Function and Scheduler
#
# This deploys:
# 1. Cloud Function for news fetching + AI summarization
# 2. Cloud Scheduler job to run every 15 minutes
#
# Usage:
#   ./bin/deploy/deploy_news_fetcher.sh
#   ./bin/deploy/deploy_news_fetcher.sh --function-only
#   ./bin/deploy/deploy_news_fetcher.sh --scheduler-only

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-nba-props-platform}"
REGION="us-west2"
FUNCTION_NAME="news-fetcher"
SERVICE_ACCOUNT="processor-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Parse arguments
DEPLOY_FUNCTION=true
DEPLOY_SCHEDULER=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --function-only)
            DEPLOY_SCHEDULER=false
            shift
            ;;
        --scheduler-only)
            DEPLOY_FUNCTION=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== News Fetcher Deployment ==="
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
    FUNC_SRC="$PROJECT_ROOT/orchestration/cloud_functions/news_fetcher"
    echo "Preparing function source with dependencies..."

    # Copy needed modules
    mkdir -p "$FUNC_SRC/scrapers"
    mkdir -p "$FUNC_SRC/shared"
    mkdir -p "$FUNC_SRC/data_processors/publishing"

    # Copy scrapers/news module
    cp -r "$PROJECT_ROOT/scrapers/news" "$FUNC_SRC/scrapers/"

    # Copy shared utilities (for player registry and auth)
    cp -r "$PROJECT_ROOT/shared/utils" "$FUNC_SRC/shared/"

    # Copy data_processors/publishing (for NewsExporter)
    # Create minimal __init__.py to avoid importing all exporters
    cat > "$FUNC_SRC/data_processors/publishing/__init__.py" << 'EOF'
"""Minimal publishing exports for Cloud Function."""
from .base_exporter import BaseExporter
from .news_exporter import NewsExporter
EOF
    cp "$PROJECT_ROOT/data_processors/publishing/base_exporter.py" "$FUNC_SRC/data_processors/publishing/"
    cp "$PROJECT_ROOT/data_processors/publishing/news_exporter.py" "$FUNC_SRC/data_processors/publishing/"

    # Ensure __init__.py files exist
    touch "$FUNC_SRC/scrapers/__init__.py"
    touch "$FUNC_SRC/shared/__init__.py"
    touch "$FUNC_SRC/data_processors/__init__.py"

    # Deploy as HTTP-triggered function
    gcloud functions deploy "$FUNCTION_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --runtime=python311 \
        --memory=1024MB \
        --timeout=300s \
        --max-instances=3 \
        --min-instances=0 \
        --entry-point=main \
        --trigger-http \
        --allow-unauthenticated \
        --service-account="$SERVICE_ACCOUNT" \
        --source="$FUNC_SRC" \
        --set-env-vars="GCP_PROJECT=$PROJECT_ID" \
        --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest" \
        --no-gen2

    # Clean up copied files
    echo "Cleaning up temporary files..."
    rm -rf "$FUNC_SRC/scrapers"
    rm -rf "$FUNC_SRC/shared"
    rm -rf "$FUNC_SRC/data_processors"

    # Get the function URL
    FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --format="value(httpsTrigger.url)")

    echo "Function URL: $FUNCTION_URL"
    echo ""
fi

# Deploy Cloud Scheduler job
if [ "$DEPLOY_SCHEDULER" = true ]; then
    echo "=== Deploying Cloud Scheduler Job ==="

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

    # Delete existing scheduler if it exists
    gcloud scheduler jobs delete "news-fetcher" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --quiet 2>/dev/null || true

    # Create scheduler: every 15 minutes, all day
    # Cron: */15 * * * * (every 15 minutes)
    echo "Creating news fetcher scheduler (every 15 minutes)..."
    gcloud scheduler jobs create http news-fetcher \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="*/15 * * * *" \
        --time-zone="America/New_York" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body='{"sports": ["nba", "mlb"], "generate_summaries": true, "max_articles": 50}' \
        --attempt-deadline=300s \
        --description="Fetch sports news from RSS feeds and generate AI summaries"

    echo ""
    echo "Scheduler deployed:"
    gcloud scheduler jobs list --project="$PROJECT_ID" --location="$REGION" \
        --filter="name:news-fetcher" --format="table(name,schedule,state)"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "To test manually:"
echo "  curl -X POST '$FUNCTION_URL' -H 'Content-Type: application/json' -d '{\"sports\": [\"nba\"], \"generate_summaries\": true}'"
echo ""
echo "To check logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --limit=50"
echo ""
echo "To run scheduler manually:"
echo "  gcloud scheduler jobs run news-fetcher --project=$PROJECT_ID --location=$REGION"
echo ""
