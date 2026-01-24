#!/bin/bash
# Deploy Phase 1 (Scrapers) and Phase 2 (Raw Processors) to Cloud Run
# Usage: ./bin/deploy_phase1_phase2.sh [--phase1-only | --phase2-only]

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "🚀 Phase 1 & 2 Deployment Script"
echo "================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Parse arguments
DEPLOY_PHASE1=true
DEPLOY_PHASE2=true

if [ "$1" = "--phase1-only" ]; then
  DEPLOY_PHASE2=false
  echo "Mode: Phase 1 Only"
elif [ "$1" = "--phase2-only" ]; then
  DEPLOY_PHASE1=false
  echo "Mode: Phase 2 Only"
else
  echo "Mode: Both Phases"
fi
echo ""

# Deploy Phase 1: Scrapers
if [ "$DEPLOY_PHASE1" = true ]; then
  echo "📡 Deploying Phase 1: NBA Stats Scrapers"
  echo "========================================"

  gcloud run deploy nba-phase1-scrapers \
    --source=. \
    --region=$REGION \
    --platform=managed \
    --allow-unauthenticated \
    --memory=2Gi \
    --timeout=540 \
    --update-env-vars=SERVICE=scrapers \
    --update-secrets=BETTINGPROS_API_KEY=bettingpros-api-key:latest,SENTRY_DSN=sentry-dsn:latest

  echo ""
  echo "✅ Phase 1 deployment complete!"
  echo ""
fi

# Deploy Phase 2: Raw Processors
if [ "$DEPLOY_PHASE2" = true ]; then
  echo "⚙️  Deploying Phase 2: Raw Data Processors"
  echo "========================================="

  gcloud run deploy nba-phase2-raw-processors \
    --source=. \
    --region=$REGION \
    --platform=managed \
    --allow-unauthenticated \
    --memory=2Gi \
    --timeout=540 \
    --update-env-vars=SERVICE=phase2,ENABLE_PHASE2_COMPLETION_DEADLINE=true,PHASE2_COMPLETION_TIMEOUT_MINUTES=30 \
    --update-secrets=SENTRY_DSN=sentry-dsn:latest

  echo ""
  echo "✅ Phase 2 deployment complete!"
  echo ""
fi

echo "🎉 Deployment Complete!"
echo "======================"

# Health check
echo ""
echo "🏥 Running health checks..."
echo ""

if [ "$DEPLOY_PHASE1" = true ]; then
  PHASE1_URL=$(gcloud run services describe nba-phase1-scrapers --region=$REGION --format="value(status.url)")
  echo "Phase 1 URL: $PHASE1_URL"
  curl -s "$PHASE1_URL/health" && echo "" || echo "❌ Phase 1 health check failed"
fi

if [ "$DEPLOY_PHASE2" = true ]; then
  PHASE2_URL=$(gcloud run services describe nba-phase2-raw-processors --region=$REGION --format="value(status.url)")
  echo "Phase 2 URL: $PHASE2_URL"
  curl -s "$PHASE2_URL/health" && echo "" || echo "❌ Phase 2 health check failed"
fi

echo ""
echo "✅ All done!"
