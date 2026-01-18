#!/bin/bash
# Deploy Prediction Monitoring Cloud Function
#
# Creates 3 endpoints:
# - validate-freshness: Check data freshness before Phase 5
# - check-missing: Detect missing predictions after Phase 5
# - reconcile: Daily end-to-end reconciliation
#
# Author: Claude Code
# Created: 2026-01-18
# Session: 106

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION="us-west2"
SERVICE_ACCOUNT="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com"

echo "========================================"
echo "Deploying Prediction Monitoring Functions"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Deploy validate-freshness endpoint
echo "1/3 Deploying validate-freshness..."
gcloud functions deploy validate-freshness \
    --gen2 \
    --runtime=python312 \
    --region=$REGION \
    --source=. \
    --entry-point=validate_freshness \
    --trigger-http \
    --allow-unauthenticated \
    --service-account=$SERVICE_ACCOUNT \
    --set-env-vars=GCP_PROJECT_ID=$PROJECT_ID \
    --memory=512MB \
    --timeout=540s \
    --max-instances=10

echo "✅ validate-freshness deployed"
echo ""

# Deploy check-missing endpoint
echo "2/3 Deploying check-missing..."
gcloud functions deploy check-missing \
    --gen2 \
    --runtime=python312 \
    --region=$REGION \
    --source=. \
    --entry-point=check_missing \
    --trigger-http \
    --allow-unauthenticated \
    --service-account=$SERVICE_ACCOUNT \
    --set-env-vars=GCP_PROJECT_ID=$PROJECT_ID \
    --set-secrets=SLACK_WEBHOOK_URL_ERROR=slack-webhook-monitoring-error:latest \
    --memory=512MB \
    --timeout=540s \
    --max-instances=10

echo "✅ check-missing deployed"
echo ""

# Deploy reconcile endpoint
echo "3/3 Deploying reconcile..."
gcloud functions deploy reconcile \
    --gen2 \
    --runtime=python312 \
    --region=$REGION \
    --source=. \
    --entry-point=reconcile \
    --trigger-http \
    --allow-unauthenticated \
    --service-account=$SERVICE_ACCOUNT \
    --set-env-vars=GCP_PROJECT_ID=$PROJECT_ID \
    --set-secrets=SLACK_WEBHOOK_URL_ERROR=slack-webhook-monitoring-error:latest \
    --memory=512MB \
    --timeout=540s \
    --max-instances=10

echo "✅ reconcile deployed"
echo ""

echo "========================================"
echo "All functions deployed successfully!"
echo "========================================"
echo ""
echo "Endpoints:"
echo "1. https://$REGION-$PROJECT_ID.cloudfunctions.net/validate-freshness"
echo "2. https://$REGION-$PROJECT_ID.cloudfunctions.net/check-missing"
echo "3. https://$REGION-$PROJECT_ID.cloudfunctions.net/reconcile"
echo ""
echo "Test with:"
echo "  curl https://$REGION-$PROJECT_ID.cloudfunctions.net/validate-freshness"
echo "  curl https://$REGION-$PROJECT_ID.cloudfunctions.net/check-missing"
echo "  curl https://$REGION-$PROJECT_ID.cloudfunctions.net/reconcile"
