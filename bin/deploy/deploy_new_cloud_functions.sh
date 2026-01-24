#!/bin/bash
# Deploy new cloud functions created in Resilience Session 2
# Created: 2026-01-24

set -e

echo "==================================="
echo "Deploying New Cloud Functions"
echo "==================================="

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
RUNTIME="python311"

echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Deploy pipeline-dashboard
echo "1. Deploying pipeline-dashboard..."
gcloud functions deploy pipeline-dashboard \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source=orchestration/cloud_functions/pipeline_dashboard \
  --entry-point=pipeline_dashboard \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=256MB \
  --project="$PROJECT_ID"

echo "   pipeline-dashboard deployed!"
echo ""

# Deploy auto-backfill-orchestrator
echo "2. Deploying auto-backfill-orchestrator..."
gcloud functions deploy auto-backfill-orchestrator \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source=orchestration/cloud_functions/auto_backfill_orchestrator \
  --entry-point=auto_backfill_orchestrator \
  --trigger-http \
  --timeout=120s \
  --memory=512MB \
  --project="$PROJECT_ID"

echo "   auto-backfill-orchestrator deployed!"
echo ""

echo "==================================="
echo "Deployment Complete!"
echo "==================================="
echo ""
echo "Verify deployments:"
echo "  Pipeline Dashboard: https://$REGION-$PROJECT_ID.cloudfunctions.net/pipeline-dashboard?date=$(date +%Y-%m-%d)"
echo "  Auto-Backfill: https://$REGION-$PROJECT_ID.cloudfunctions.net/auto-backfill-orchestrator?dry_run=true"
echo ""
