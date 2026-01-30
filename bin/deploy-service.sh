#!/bin/bash
# Usage: ./bin/deploy-service.sh <service-name>
# Deploys a Cloud Run service with correct build context
#
# IMPORTANT: This script builds from the repository root to ensure
# shared/ modules are available in the Docker build context.
#
# Supported services:
#   - prediction-coordinator
#   - prediction-worker
#   - nba-phase3-analytics-processors
#   - nba-phase4-precompute-processors
#   - nba-scrapers
#   - nba-phase1-scrapers

set -e

SERVICE=$1
REGION="us-west2"
PROJECT="nba-props-platform"
REGISTRY="us-west2-docker.pkg.dev/$PROJECT/nba-props"

# Ensure we're running from repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

if [ -z "$SERVICE" ]; then
    echo "Usage: ./bin/deploy-service.sh <service-name>"
    echo ""
    echo "Available services:"
    echo "  - prediction-coordinator"
    echo "  - prediction-worker"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase4-precompute-processors"
    echo "  - nba-scrapers"
    echo "  - nba-phase1-scrapers"
    exit 1
fi

# Map service names to Dockerfile paths
case $SERVICE in
  prediction-coordinator)
    DOCKERFILE="predictions/coordinator/Dockerfile"
    ;;
  prediction-worker)
    DOCKERFILE="predictions/worker/Dockerfile"
    ;;
  nba-phase3-analytics-processors)
    DOCKERFILE="data_processors/analytics/Dockerfile"
    ;;
  nba-phase4-precompute-processors)
    DOCKERFILE="data_processors/precompute/Dockerfile"
    ;;
  nba-scrapers|nba-phase1-scrapers)
    DOCKERFILE="scrapers/Dockerfile"
    ;;
  *)
    echo "ERROR: Unknown service: $SERVICE"
    echo ""
    echo "Available services:"
    echo "  - prediction-coordinator"
    echo "  - prediction-worker"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase4-precompute-processors"
    echo "  - nba-scrapers"
    echo "  - nba-phase1-scrapers"
    exit 1
    ;;
esac

# Verify Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    echo "ERROR: Dockerfile not found at $DOCKERFILE"
    exit 1
fi

# Get build metadata
BUILD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "=============================================="
echo "DEPLOYMENT: $SERVICE"
echo "=============================================="
echo "Dockerfile:      $DOCKERFILE"
echo "Registry:        $REGISTRY"
echo "Build commit:    $BUILD_COMMIT"
echo "Build timestamp: $BUILD_TIMESTAMP"
echo "=============================================="

echo ""
echo "[1/4] Building $SERVICE from repo root with $DOCKERFILE..."
docker build \
    -t "$REGISTRY/$SERVICE:latest" \
    -t "$REGISTRY/$SERVICE:$BUILD_COMMIT" \
    --build-arg BUILD_COMMIT="$BUILD_COMMIT" \
    --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
    -f "$DOCKERFILE" .

echo ""
echo "[2/4] Pushing image..."
docker push "$REGISTRY/$SERVICE:latest"
docker push "$REGISTRY/$SERVICE:$BUILD_COMMIT"

echo ""
echo "[3/4] Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
    --image="$REGISTRY/$SERVICE:latest" \
    --region="$REGION" \
    --project="$PROJECT" \
    --set-env-vars="BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP" \
    --quiet

echo ""
echo "[4/4] Verifying deployment..."
sleep 10

# Get the latest revision
REVISION=$(gcloud run services describe "$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="value(status.latestReadyRevisionName)" 2>/dev/null)

echo ""
echo "=============================================="
echo "DEPLOYMENT COMPLETE"
echo "=============================================="
echo "Service:  $SERVICE"
echo "Revision: $REVISION"
echo "Commit:   $BUILD_COMMIT"
echo "=============================================="

# Show recent logs
echo ""
echo "Recent logs:"
gcloud logging read \
    "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"$SERVICE\"" \
    --limit=10 \
    --project="$PROJECT" \
    --format="table(timestamp,textPayload)" 2>/dev/null || echo "(no logs available yet)"
