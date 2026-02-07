#!/bin/bash
# Usage: ./bin/cloud-deploy.sh <service-name>
#
# Deploys a service using Google Cloud Build.
# Builds and pushes from Google's network, avoiding local docker push
# TLS timeout issues (the #1 cause of deployment failures from WSL2).
#
# Advantages over local deploy:
# - No TLS handshake timeouts (builds inside Google's network)
# - Faster push (no upload from local machine)
# - Consistent build environment
#
# Disadvantages:
# - Slower build start (~30s to upload source tarball)
# - No local dependency testing (imports checked post-deploy)
# - Costs ~$0.003/min for build time
#
# For full validation (dependency testing, smoke tests), use:
#   ./bin/deploy-service.sh <service-name>

set -e

SERVICE=$1
REGION="us-west2"
PROJECT="nba-props-platform"

# Ensure we're running from repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

if [ -z "$SERVICE" ]; then
    echo "Usage: ./bin/cloud-deploy.sh <service-name>"
    echo ""
    echo "Deploy via Cloud Build (avoids local docker push TLS timeouts)"
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
    SERVICE="nba-scrapers"
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
echo "CLOUD DEPLOY: $SERVICE"
echo "=============================================="
echo "Commit:     $BUILD_COMMIT"
echo "Dockerfile: $DOCKERFILE"
echo "Method:     Cloud Build (remote)"
echo "=============================================="
echo ""

# Submit to Cloud Build
# --config uses the repo's cloudbuild.yaml
# --substitutions passes service-specific values
echo "[1/3] Submitting to Cloud Build..."
# Note: --region is NOT passed to builds submit (Cloud Build runs globally)
# The --region flag is only used for Cloud Run deployment in cloudbuild.yaml
gcloud builds submit \
    --config cloudbuild.yaml \
    --substitutions="_SERVICE=$SERVICE,_DOCKERFILE=$DOCKERFILE,_BUILD_TIMESTAMP=$BUILD_TIMESTAMP,SHORT_SHA=$BUILD_COMMIT" \
    --project "$PROJECT" \
    --quiet 2>&1 | while IFS= read -r line; do
    # Show progress but filter verbose output
    case "$line" in
        *"Step"*|*"SUCCESS"*|*"DONE"*|*"ERROR"*|*"Deploying"*|*"Service URL"*)
            echo "  $line"
            ;;
    esac
done

BUILD_EXIT=${PIPESTATUS[0]}

if [ "$BUILD_EXIT" -ne 0 ]; then
    echo ""
    echo "ERROR: Cloud Build failed (exit code $BUILD_EXIT)"
    echo "Check logs: gcloud builds list --project $PROJECT --limit 1"
    exit 1
fi

# [2/3] Verify deployment
echo ""
echo "[2/3] Verifying deployment..."
DEPLOYED_SHA=$(gcloud run services describe "$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="value(metadata.labels.commit-sha)" 2>/dev/null || echo "unknown")

if [ "$DEPLOYED_SHA" = "$BUILD_COMMIT" ]; then
    echo "  Commit SHA verified: $DEPLOYED_SHA"
else
    echo "  WARNING: Expected $BUILD_COMMIT, got $DEPLOYED_SHA"
fi

# [3/3] Health check
echo ""
echo "[3/3] Health check..."
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
echo "DEPLOYED in ${DURATION}s (via Cloud Build)"
echo "=============================================="
echo "Service: $SERVICE"
echo "Commit:  $BUILD_COMMIT"
echo "URL:     $SERVICE_URL"
echo "=============================================="
