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
#   - nba-phase2-raw-processors
#   - nba-phase3-analytics-processors
#   - nba-phase4-precompute-processors
#   - nba-scrapers
#   - nba-phase1-scrapers
#   - unified-dashboard
#   - nba-grading-service

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
    echo "  - nba-phase2-raw-processors"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase4-precompute-processors"
    echo "  - nba-scrapers"
    echo "  - nba-phase1-scrapers"
    echo "  - unified-dashboard"
    echo "  - nba-grading-service"
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
  nba-phase2-raw-processors)
    DOCKERFILE="data_processors/raw/Dockerfile"
    EXPECTED_SERVICE="raw-processor"
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
  unified-dashboard)
    DOCKERFILE="services/unified_dashboard/Dockerfile"
    EXPECTED_SERVICE="unified-dashboard"
    ;;
  nba-grading-service)
    DOCKERFILE="data_processors/grading/nba/Dockerfile"
    EXPECTED_SERVICE="nba_grading_service"
    ;;
  *)
    echo "ERROR: Unknown service: $SERVICE"
    echo ""
    echo "Available services:"
    echo "  - prediction-coordinator"
    echo "  - prediction-worker"
    echo "  - nba-phase2-raw-processors"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase4-precompute-processors"
    echo "  - nba-scrapers"
    echo "  - nba-phase1-scrapers"
    echo "  - unified-dashboard"
    echo "  - nba-grading-service"
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
echo "[1/7] Building $SERVICE from repo root with $DOCKERFILE..."
docker build \
    -t "$REGISTRY/$SERVICE:latest" \
    -t "$REGISTRY/$SERVICE:$BUILD_COMMIT" \
    --build-arg BUILD_COMMIT="$BUILD_COMMIT" \
    --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
    -f "$DOCKERFILE" .

echo ""
echo "[2/7] Pushing image..."
docker push "$REGISTRY/$SERVICE:latest"
docker push "$REGISTRY/$SERVICE:$BUILD_COMMIT"

echo ""
echo "[3/7] Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
    --image="$REGISTRY/$SERVICE:latest" \
    --region="$REGION" \
    --project="$PROJECT" \
    --update-env-vars="BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP,GCP_PROJECT_ID=$PROJECT" \
    --quiet

echo ""
echo "[4/7] Verifying deployment..."
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
echo "[5/7] Verifying service identity..."

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

# [6/7] Verify heartbeat code is correct
echo ""
echo "[6/7] Verifying heartbeat code..."

# Check if heartbeat fix is in deployed image
HEARTBEAT_CHECK=$(docker run --rm "$REGISTRY/$SERVICE:$BUILD_COMMIT" \
    cat /app/shared/monitoring/processor_heartbeat.py 2>/dev/null | \
    grep -c "return self.processor_name" || echo "0")

if [ "$HEARTBEAT_CHECK" -eq "0" ]; then
    echo ""
    echo "=============================================="
    echo "⚠️  HEARTBEAT CODE VERIFICATION FAILED"
    echo "=============================================="
    echo "The deployed image may not have the heartbeat fix."
    echo ""
    echo "Expected: 'return self.processor_name' in processor_heartbeat.py"
    echo "Found:    Different or missing code"
    echo ""
    echo "This could cause Firestore document proliferation!"
    echo ""
    echo "Actions:"
    echo "1. Check shared/monitoring/processor_heartbeat.py in main branch"
    echo "2. Verify Docker build included latest code"
    echo "3. Consider rebuilding with --no-cache flag"
    echo "=============================================="
else
    echo ""
    echo "=============================================="
    echo "✅ HEARTBEAT CODE VERIFIED"
    echo "=============================================="
    echo "Heartbeat fix confirmed in deployed image"
    echo "Document ID format: processor_name (correct)"
    echo "=============================================="
fi

# [7/7] Service-specific validation
echo ""
echo "[7/7] Service-specific validation..."

case $SERVICE in
  prediction-worker)
    echo ""
    echo "Checking recent predictions..."
    RECENT_PREDICTIONS=$(bq query --use_legacy_sql=false --format=csv \
      "SELECT COUNT(*) as cnt FROM nba_predictions.player_prop_predictions
       WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)" 2>/dev/null | tail -1)

    if [ "$RECENT_PREDICTIONS" = "0" ] || [ -z "$RECENT_PREDICTIONS" ]; then
      echo "⚠️  WARNING: No predictions created in last 2 hours"
      echo "   This may be expected if no games are scheduled"
      echo "   Check scheduler: gcloud scheduler jobs list --location=us-west2 | grep predictions"
    else
      echo "✅ Recent predictions found: $RECENT_PREDICTIONS"
    fi
    ;;

  prediction-coordinator)
    echo ""
    echo "Checking batch execution logs..."
    BATCH_ERRORS=$(gcloud logging read \
      "resource.type=\"cloud_run_revision\"
       AND resource.labels.service_name=\"prediction-coordinator\"
       AND severity>=ERROR" \
      --limit=5 \
      --format="value(timestamp,textPayload)" \
      --project="$PROJECT" 2>/dev/null | head -5)

    if [ -z "$BATCH_ERRORS" ]; then
      echo "✅ No recent errors in coordinator logs"
    else
      echo "⚠️  WARNING: Recent errors detected:"
      echo "$BATCH_ERRORS"
    fi
    ;;

  nba-phase4-precompute-processors)
    echo ""
    echo "Checking Vegas line coverage..."
    if [ -f "bin/monitoring/check_vegas_line_coverage.sh" ]; then
      ./bin/monitoring/check_vegas_line_coverage.sh --days 1 || \
        echo "⚠️  WARNING: Vegas line coverage check failed - monitor closely"
    else
      echo "⚠️  WARNING: Vegas line coverage script not found"
    fi
    ;;

  nba-phase3-analytics-processors)
    echo ""
    echo "Checking processor heartbeats..."
    # Check if processors have sent heartbeats recently
    HEARTBEAT_AGE=$(gcloud logging read \
      "resource.type=\"cloud_run_revision\"
       AND resource.labels.service_name=\"nba-phase3-analytics-processors\"
       AND jsonPayload.message=~\"Heartbeat\"" \
      --limit=1 \
      --format="value(timestamp)" \
      --project="$PROJECT" 2>/dev/null | head -1)

    if [ -z "$HEARTBEAT_AGE" ]; then
      echo "⚠️  WARNING: No recent heartbeats found"
      echo "   Service may not be processing data"
    else
      echo "✅ Recent heartbeat detected: $HEARTBEAT_AGE"
    fi
    ;;

  nba-grading-service)
    echo ""
    echo "Checking grading completeness..."
    if [ -f "bin/monitoring/check_grading_completeness.sh" ]; then
      ./bin/monitoring/check_grading_completeness.sh || \
        echo "⚠️  WARNING: Grading completeness check failed"
    else
      echo "⚠️  WARNING: Grading completeness script not found"
    fi
    ;;

  *)
    echo "No service-specific validation configured for $SERVICE"
    ;;
esac

# Check for errors in recent logs (all services)
echo ""
echo "Checking for recent errors..."
ERROR_COUNT=$(gcloud logging read \
  "resource.type=\"cloud_run_revision\"
   AND resource.labels.service_name=\"$SERVICE\"
   AND severity>=ERROR
   AND timestamp>=\"$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
  --limit=10 \
  --format="value(severity)" \
  --project="$PROJECT" 2>/dev/null | wc -l)

if [ "$ERROR_COUNT" -eq 0 ]; then
  echo "✅ No errors in last 10 minutes"
else
  echo "⚠️  WARNING: $ERROR_COUNT errors detected in last 10 minutes"
  echo "   Review logs: gcloud logging read 'resource.labels.service_name=\"$SERVICE\" AND severity>=ERROR' --limit=10"
fi

echo ""
echo "=============================================="
echo "POST-DEPLOYMENT VALIDATION COMPLETE"
echo "=============================================="
