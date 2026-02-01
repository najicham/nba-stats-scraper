#!/bin/bash
# bin/verify-deployment-before-backfill.sh
#
# CRITICAL: Run this before any backfill to ensure latest code is deployed.
#
# Session 64 Learning: The V8 hit rate collapse was caused by running a backfill
# with old code. The fix was committed but not deployed for 12 hours, and the
# backfill ran during that window with broken code.
#
# Usage:
#   ./bin/verify-deployment-before-backfill.sh prediction-worker
#   ./bin/verify-deployment-before-backfill.sh nba-phase3-analytics-processors
#
# Returns:
#   0 - Safe to run backfill
#   1 - Deployment mismatch - deploy first!

set -e

SERVICE=$1

if [[ -z "$SERVICE" ]]; then
    echo "Usage: $0 <service-name>"
    echo ""
    echo "Services:"
    echo "  prediction-worker"
    echo "  prediction-coordinator"
    echo "  nba-phase3-analytics-processors"
    echo "  nba-phase4-precompute-processors"
    exit 1
fi

echo "=============================================="
echo "Pre-Backfill Deployment Verification"
echo "=============================================="
echo ""
echo "Service: $SERVICE"
echo ""

# Get required commit (current HEAD)
REQUIRED_COMMIT=$(git rev-parse --short HEAD)
REQUIRED_COMMIT_FULL=$(git rev-parse HEAD)
echo "Required commit: $REQUIRED_COMMIT"

# Get deployed commit from Cloud Run labels
DEPLOYED_INFO=$(gcloud run services describe "$SERVICE" --region=us-west2 \
    --format="yaml(metadata.labels,status.latestReadyRevisionName)" 2>/dev/null)

if [[ $? -ne 0 ]]; then
    echo ""
    echo "❌ ERROR: Could not describe service $SERVICE"
    echo "   Check if service exists and you have permissions."
    exit 1
fi

# Extract commit-sha from labels
DEPLOYED_COMMIT=$(echo "$DEPLOYED_INFO" | grep "commit-sha:" | awk '{print $2}' | tr -d "'")
REVISION=$(echo "$DEPLOYED_INFO" | grep "latestReadyRevisionName:" | awk '{print $2}')

if [[ -z "$DEPLOYED_COMMIT" ]]; then
    echo ""
    echo "⚠️  WARNING: No commit-sha label found on deployment."
    echo "   This service may not have been deployed with ./bin/deploy-service.sh"
    echo ""
    echo "   To fix: ./bin/deploy-service.sh $SERVICE"
    exit 1
fi

echo "Deployed commit: $DEPLOYED_COMMIT"
echo "Revision: $REVISION"
echo ""

# Compare commits
if [[ "${DEPLOYED_COMMIT:0:8}" == "${REQUIRED_COMMIT:0:8}" ]]; then
    echo "✅ VERIFIED: Deployment matches current code"
    echo ""
    echo "Safe to run backfill."
    exit 0
else
    echo "❌ DEPLOYMENT MISMATCH!"
    echo ""
    echo "   Required: $REQUIRED_COMMIT (current HEAD)"
    echo "   Deployed: $DEPLOYED_COMMIT"
    echo ""
    echo "   The deployed version is OLDER than your current code."
    echo "   Any backfill you run will use the OLD code, not your fixes!"
    echo ""
    echo "   To fix:"
    echo "   1. ./bin/deploy-service.sh $SERVICE"
    echo "   2. Wait for deployment to complete"
    echo "   3. Run this verification again"
    echo ""
    exit 1
fi
