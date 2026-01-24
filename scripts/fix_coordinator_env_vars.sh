#!/bin/bash
# Fix Prediction Coordinator Missing Environment Variables
# Created: Jan 20, 2026
# Issue: Health check requires PREDICTION_REQUEST_TOPIC and PREDICTION_READY_TOPIC but they're not set

set -euo pipefail

echo "=== Fixing Prediction Coordinator Environment Variables ==="
echo ""
echo "Setting required Pub/Sub topic environment variables..."

gcloud run services update prediction-coordinator \
  --region=us-west2 \
  --update-env-vars="\
PREDICTION_REQUEST_TOPIC=prediction-request-prod,\
PREDICTION_READY_TOPIC=prediction-ready-prod,\
BATCH_SUMMARY_TOPIC=batch-summary-prod,\
ENVIRONMENT=production" \
  --project=nba-props-platform

echo ""
echo "✅ Environment variables updated successfully!"
echo ""
echo "Verifying deployment..."
sleep 5

# Check health endpoint
echo "Checking /health endpoint..."
curl -s https://prediction-coordinator-756957797294.us-west2.run.app/health | jq .

echo ""
echo "Checking /ready endpoint..."
curl -s https://prediction-coordinator-756957797294.us-west2.run.app/ready | jq .

echo ""
echo "=== Fix Complete ==="
