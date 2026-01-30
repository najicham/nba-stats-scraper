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

# Map service names to Dockerfile paths and expected service identity
case $SERVICE in
  prediction-coordinator)
    DOCKERFILE="predictions/coordinator/Dockerfile"
    EXPECTED_SERVICE="prediction-coordinator"
    ;;
  prediction-worker)
    DOCKERFILE="predictions/worker/Dockerfile"
    EXPECTED_SERVICE="prediction-worker"
    ;;
  nba-phase3-analytics-processors)
    DOCKERFILE="data_processors/analytics/Dockerfile"
    EXPECTED_SERVICE="analytics-processor"
    ;;
  nba-phase4-precompute-processors)
    DOCKERFILE="data_processors/precompute/Dockerfile"
    EXPECTED_SERVICE="precompute-processor"
    ;;
  nba-scrapers|nba-phase1-scrapers)
    DOCKERFILE="scrapers/Dockerfile"
    EXPECTED_SERVICE="nba-scrapers"
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

# Post-deployment service identity verification
echo ""
echo "[5/5] Verifying service identity..."

SERVICE_URL=$(gcloud run services describe "$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="value(status.url)" 2>/dev/null)

if [ -z "$SERVICE_URL" ]; then
    echo "WARNING: Could not get service URL for verification"
else
    # Wait for service to be ready and retry up to 3 times
    RETRY=0
    MAX_RETRIES=3
    while [ $RETRY -lt $MAX_RETRIES ]; do
        HEALTH_RESPONSE=$(curl -s --max-time 10 "$SERVICE_URL/health" 2>/dev/null || echo "{}")

        # Try to extract service name from response (handles both service and components.scrapers formats)
        ACTUAL_SERVICE=$(echo "$HEALTH_RESPONSE" | jq -r '.service // .components.scrapers.status // "unknown"' 2>/dev/null || echo "unknown")

        # For scrapers, check if status is "operational" (in components) or "nba-scrapers" (in service field)
        if echo "$HEALTH_RESPONSE" | jq -e '.service' >/dev/null 2>&1; then
            ACTUAL_SERVICE=$(echo "$HEALTH_RESPONSE" | jq -r '.service' 2>/dev/null)
        fi

        if [ "$ACTUAL_SERVICE" = "$EXPECTED_SERVICE" ]; then
            echo ""
            echo "=============================================="
            echo "SERVICE IDENTITY VERIFIED"
            echo "=============================================="
            echo "Expected: $EXPECTED_SERVICE"
            echo "Actual:   $ACTUAL_SERVICE"
            echo "Status:   ✅ MATCH"
            echo "=============================================="
            break
        elif [ "$ACTUAL_SERVICE" = "unknown" ] || [ -z "$ACTUAL_SERVICE" ]; then
            RETRY=$((RETRY + 1))
            if [ $RETRY -lt $MAX_RETRIES ]; then
                echo "Waiting for service to respond (attempt $RETRY/$MAX_RETRIES)..."
                sleep 10
            fi
        else
            echo ""
            echo "=============================================="
            echo "⚠️  SERVICE IDENTITY MISMATCH ⚠️"
            echo "=============================================="
            echo "Expected: $EXPECTED_SERVICE"
            echo "Actual:   $ACTUAL_SERVICE"
            echo ""
            echo "CRITICAL: The deployed code does not match the expected service!"
            echo "This indicates WRONG CODE was deployed."
            echo ""
            echo "Actions to take:"
            echo "1. Check the Dockerfile at $DOCKERFILE"
            echo "2. Verify the CMD in the Dockerfile points to the correct module"
            echo "3. Rollback to the previous revision if needed:"
            echo "   gcloud run services update-traffic $SERVICE --to-revisions=PREVIOUS_REVISION=100"
            echo "=============================================="
            exit 1
        fi
    done

    if [ $RETRY -eq $MAX_RETRIES ] && [ "$ACTUAL_SERVICE" != "$EXPECTED_SERVICE" ]; then
        echo "WARNING: Could not verify service identity after $MAX_RETRIES attempts"
        echo "Please manually verify: curl $SERVICE_URL/health"
    fi
fi
