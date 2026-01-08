#!/bin/bash
# deploy_mlb_scrapers.sh - Deploy MLB Scrapers to Cloud Run
#
# WHAT THIS DOES:
# 1. Deploys mlb-phase1-scrapers Cloud Run service
# 2. Configures environment variables and secrets
# 3. Tests health endpoint
#
# USAGE: ./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh
#
# Created: 2026-01-07

set -e

SERVICE_NAME="mlb-phase1-scrapers"
REGION="us-west2"
PROJECT_ID="nba-props-platform"

# Capture git commit SHA for deployment tracking
GIT_COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "========================================"
echo " Deploying MLB Scrapers to Cloud Run"
echo "========================================"
echo "Start time: $DEPLOY_START_DISPLAY"
echo "Git commit: $GIT_COMMIT_SHA ($GIT_BRANCH)"
echo "Service: $SERVICE_NAME"
echo "Region: $REGION"
echo ""

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,SPORT=mlb"
ENV_VARS="$ENV_VARS,GCS_BUCKET=nba-scraped-data"
ENV_VARS="$ENV_VARS,COMMIT_SHA=$GIT_COMMIT_SHA"
ENV_VARS="$ENV_VARS,GIT_BRANCH=$GIT_BRANCH"
ENV_VARS="$ENV_VARS,DEPLOY_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Add API keys if available
if [[ -n "$BDL_API_KEY" ]]; then
    ENV_VARS="$ENV_VARS,BDL_API_KEY=$BDL_API_KEY"
    echo "BDL API key configured"
fi

if [[ -n "$ODDS_API_KEY" ]]; then
    ENV_VARS="$ENV_VARS,ODDS_API_KEY=$ODDS_API_KEY"
    echo "Odds API key configured"
fi

# Add email configuration if available
if [[ -n "$AWS_SES_ACCESS_KEY_ID" ]]; then
    ENV_VARS="$ENV_VARS,AWS_SES_ACCESS_KEY_ID=$AWS_SES_ACCESS_KEY_ID"
    ENV_VARS="$ENV_VARS,AWS_SES_SECRET_ACCESS_KEY=$AWS_SES_SECRET_ACCESS_KEY"
    ENV_VARS="$ENV_VARS,AWS_SES_REGION=${AWS_SES_REGION:-us-west-2}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "Email alerting configured (AWS SES)"
fi

echo ""
echo "Deploying to Cloud Run..."

# Deploy using source (Cloud Build)
gcloud run deploy $SERVICE_NAME \
    --source . \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 5 \
    --set-env-vars="$ENV_VARS" \
    --project $PROJECT_ID

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)' --project $PROJECT_ID)

echo ""
echo "========================================"
echo " Deployment Complete!"
echo "========================================"
echo "Service URL: $SERVICE_URL"
echo ""

# Test health endpoint
echo "Testing health endpoint..."
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/health" || echo "000")

if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo "Health check: PASSED"
else
    echo "Health check: FAILED (HTTP $HEALTH_RESPONSE)"
    echo "Service may need a few seconds to start..."
fi

# Calculate deployment time
DEPLOY_END_TIME=$(date +%s)
DEPLOY_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))

echo ""
echo "Deployment duration: ${DEPLOY_DURATION}s"
echo ""
echo "Available endpoints:"
echo "  $SERVICE_URL/health"
echo "  $SERVICE_URL/scrape?scraper=mlb_schedule&date=2025-06-15"
echo "  $SERVICE_URL/list-scrapers"
echo ""
