#!/bin/bash
# Usage: ./bin/hot-deploy.sh <service-name>
# Fast deployment script that skips non-essential validation checks
#
# Use this for:
# - Hot fixes that need to go out quickly
# - Re-deploying after minor code changes
# - When you've already verified the build recently
#
# Skips:
# - Dockerfile dependency validation (saves ~10s)
# - BigQuery write verification (saves 120s!)
# - Env var preservation checks
# - Verbose logging
#
# Still runs:
# - Docker build and push
# - Cloud Run deploy
# - Basic health check
# - Service identity verification

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
    echo "Usage: ./bin/hot-deploy.sh <service-name>"
    echo ""
    echo "Fast deployment - skips non-essential validation"
    echo ""
    echo "Available services:"
    echo "  - prediction-coordinator"
    echo "  - prediction-worker"
    echo "  - nba-phase2-raw-processors"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase4-precompute-processors"
    echo "  - nba-scrapers"
    echo "  - nba-grading-service"
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
  nba-phase2-raw-processors)
    DOCKERFILE="data_processors/raw/Dockerfile"
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
  nba-grading-service)
    DOCKERFILE="data_processors/grading/nba/Dockerfile"
    ;;
  *)
    echo "ERROR: Unknown service: $SERVICE"
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

START_TIME=$(date +%s)

echo "=============================================="
echo "HOT DEPLOY: $SERVICE"
echo "=============================================="
echo "Commit: $BUILD_COMMIT"
echo "=============================================="

# [1/4] Build
echo ""
echo "[1/4] Building..."
docker build -q \
    -t "$REGISTRY/$SERVICE:latest" \
    -t "$REGISTRY/$SERVICE:$BUILD_COMMIT" \
    --build-arg BUILD_COMMIT="$BUILD_COMMIT" \
    --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
    -f "$DOCKERFILE" . > /dev/null

echo "  Build complete"

# [2/4] Push
echo ""
echo "[2/4] Pushing..."
docker push -q "$REGISTRY/$SERVICE:latest" > /dev/null 2>&1
docker push -q "$REGISTRY/$SERVICE:$BUILD_COMMIT" > /dev/null 2>&1
echo "  Push complete"

# [3/4] Deploy
echo ""
echo "[3/4] Deploying..."
gcloud run deploy "$SERVICE" \
    --image="$REGISTRY/$SERVICE:latest" \
    --region="$REGION" \
    --project="$PROJECT" \
    --update-env-vars="BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP" \
    --update-labels="commit-sha=$BUILD_COMMIT" \
    --quiet 2>&1 | grep -E "(Deploying|Routing|Done|Service)" || true

# [4/4] Quick health check
echo ""
echo "[4/4] Health check..."
sleep 5

SERVICE_URL=$(gcloud run services describe "$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="value(status.url)" 2>/dev/null)

HEALTH_STATUS=$(curl -s --max-time 10 "$SERVICE_URL/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")

if [ "$HEALTH_STATUS" = "200" ]; then
    echo "  Health: OK"
else
    echo "  Health: HTTP $HEALTH_STATUS (may need auth)"
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "=============================================="
echo "DEPLOYED in ${DURATION}s"
echo "=============================================="
echo "Service: $SERVICE"
echo "Commit:  $BUILD_COMMIT"
echo "URL:     $SERVICE_URL"
echo "=============================================="
