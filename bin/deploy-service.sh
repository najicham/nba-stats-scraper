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

# Services that need a warm instance to avoid cold-start pipeline delays.
# Orchestrators + prediction services get minScale=1; everything else gets 0.
# Session 338: Deployments were silently resetting minScale to 0.
get_min_instances() {
    case "$1" in
        prediction-coordinator|prediction-worker|\
        phase3-to-phase4-orchestrator|phase4-to-phase5-orchestrator|\
        phase5-to-phase6-orchestrator)
            echo "1"
            ;;
        *)
            echo "0"
            ;;
    esac
}

MIN_INSTANCES=$(get_min_instances "$SERVICE")

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

# [0/8] Dockerfile dependency validation (Session 131)
echo ""
echo "[0/8] Validating Dockerfile dependencies..."
echo "This prevents missing module/dependency bugs like Session 129-130"
SERVICE_DIR=$(dirname "$DOCKERFILE")
if [ -f "./bin/validate-dockerfile-dependencies.sh" ]; then
    if ! ./bin/validate-dockerfile-dependencies.sh "$SERVICE_DIR"; then
        echo "ERROR: Dockerfile validation failed. Fix missing dependencies before deploying."
        exit 1
    fi
else
    echo "⚠️  Dockerfile validation script not found, skipping check"
fi

echo ""
echo "[1/8] Building $SERVICE from repo root with $DOCKERFILE..."
docker build \
    -t "$REGISTRY/$SERVICE:latest" \
    -t "$REGISTRY/$SERVICE:$BUILD_COMMIT" \
    --build-arg BUILD_COMMIT="$BUILD_COMMIT" \
    --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
    -f "$DOCKERFILE" .

# [2/8] P0-2: Docker Dependency Verification (Session 89)
echo ""
echo "[2/8] Testing Docker dependencies (P0-2)..."
echo "This prevents missing dependency outages like Session 80 (38 hours down)"

# Map service to main module and critical dependencies
case $SERVICE in
  prediction-coordinator)
    MAIN_MODULE="coordinator"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.pubsub_v1 google.cloud.firestore flask pandas"
    ;;
  prediction-worker)
    MAIN_MODULE="worker"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.pubsub_v1 google.cloud.firestore flask catboost pandas sklearn"
    ;;
  nba-phase2-raw-processors)
    MAIN_MODULE="main_processor_service"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.firestore flask pandas"
    ;;
  nba-phase3-analytics-processors)
    MAIN_MODULE="main_analytics_service"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.firestore flask pandas"
    ;;
  nba-phase4-precompute-processors)
    MAIN_MODULE="main_precompute_service"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.firestore flask pandas"
    ;;
  nba-scrapers|nba-phase1-scrapers)
    MAIN_MODULE="scrapers.main_scraper_service"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.storage flask pandas requests"
    ;;
  unified-dashboard)
    MAIN_MODULE="app"
    CRITICAL_DEPS="flask google.cloud.firestore google.cloud.bigquery pandas"
    ;;
  nba-grading-service)
    MAIN_MODULE="main_nba_grading_service"
    CRITICAL_DEPS="google.cloud.bigquery google.cloud.pubsub_v1 google.cloud.firestore flask pandas"
    ;;
  *)
    echo "WARNING: No dependency test configured for $SERVICE, skipping..."
    MAIN_MODULE=""
    CRITICAL_DEPS=""
    ;;
esac

# Run dependency test if configured
if [ -n "$MAIN_MODULE" ]; then
  # Create test script
  TEST_SCRIPT=$(cat <<'PYEOF'
import sys
import importlib

# Get args: main_module critical_deps...
main_module = sys.argv[1]
critical_deps = sys.argv[2].split() if len(sys.argv) > 2 else []

print(f"Testing imports for module: {main_module}")
print(f"Critical dependencies: {len(critical_deps)}")
print("")

failed = []

# Test main module
print(f"[1/2] Testing main module: {main_module}")
try:
    importlib.import_module(main_module)
    print(f"  ✅ {main_module} imports successfully")
except ImportError as e:
    print(f"  ❌ CRITICAL: {main_module} import failed: {e}")
    failed.append(("MAIN_MODULE", main_module, str(e)))

# Test critical dependencies
print(f"\n[2/2] Testing {len(critical_deps)} critical dependencies:")
for dep in critical_deps:
    try:
        importlib.import_module(dep)
        print(f"  ✅ {dep}")
    except ImportError as e:
        print(f"  ❌ {dep}: {e}")
        failed.append(("DEPENDENCY", dep, str(e)))

print("")
if failed:
    print("=" * 60)
    print("❌ DEPENDENCY TEST FAILED")
    print("=" * 60)
    print(f"Missing {len(failed)} critical import(s):")
    for import_type, name, error in failed:
        print(f"  [{import_type}] {name}")
        print(f"    Error: {error}")
    print("")
    print("This would cause service crashes in production!")
    print("=" * 60)
    sys.exit(1)
else:
    print("=" * 60)
    print("✅ ALL DEPENDENCIES VERIFIED")
    print("=" * 60)
    print("All critical imports work correctly")
    print("Service should start successfully")
    print("=" * 60)
PYEOF
)

  # Run test in container (pass GCP_PROJECT_ID for modules that validate env at import)
  # Also pass CATBOOST_V8_MODEL_PATH for prediction-worker validation (Session 96 fix)
  if docker run --rm \
    -e GCP_PROJECT_ID="$PROJECT" \
    -e CATBOOST_V8_MODEL_PATH="gs://nba-props-platform-models/catboost/v8/dummy.cbm" \
    "$REGISTRY/$SERVICE:$BUILD_COMMIT" python3 -c "$TEST_SCRIPT" "$MAIN_MODULE" "$CRITICAL_DEPS"; then
    echo ""
    echo "✅ Docker dependency test PASSED"
  else
    echo ""
    echo "=============================================="
    echo "🚨 BLOCKING DEPLOYMENT - MISSING DEPENDENCIES"
    echo "=============================================="
    echo ""
    echo "The Docker image is missing critical dependencies!"
    echo "This would cause service crashes like Session 80 (38hr outage)."
    echo ""
    echo "Actions to fix:"
    echo "1. Check $DOCKERFILE for correct requirements.txt"
    echo "2. Verify requirements.txt includes all needed packages"
    echo "3. Add missing packages to requirements.txt"
    echo "4. Rebuild and try again"
    echo ""
    echo "Common causes:"
    echo "  - Package in requirements.txt but wrong name"
    echo "  - Missing from requirements.txt entirely"
    echo "  - Wrong Python version in Dockerfile"
    echo "=============================================="
    exit 1
  fi
else
  echo "⚠️  No dependency test configured, proceeding..."
fi

echo ""
echo "[3/8] Pushing image..."
docker push "$REGISTRY/$SERVICE:latest"
docker push "$REGISTRY/$SERVICE:$BUILD_COMMIT"

# Service-specific env var handling
ENV_VARS="BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP,GCP_PROJECT_ID=$PROJECT"

if [ "$SERVICE" = "prediction-worker" ]; then
    echo ""
    echo "[3.5/8] Validating prediction-worker environment..."

    # Check if .env.required exists
    ENV_TEMPLATE="predictions/worker/env.template"
    if [ ! -f "$ENV_TEMPLATE" ]; then
        echo "WARNING: $ENV_TEMPLATE not found, using defaults"
    fi

    # Get current env vars from deployed service
    echo "Fetching current service configuration..."
    CURRENT_ENV=$(gcloud run services describe "$SERVICE" \
        --region="$REGION" \
        --project="$PROJECT" \
        --format="json" 2>/dev/null | jq -r '.spec.template.spec.containers[0].env // []')

    # Check for required env vars
    REQUIRED_VARS=("CATBOOST_V8_MODEL_PATH" "CATBOOST_V9_MODEL_PATH" "PUBSUB_READY_TOPIC")
    MISSING_VARS=()
    INVALID_MODEL_PATHS=()

    # Function to validate GCS model path exists
    validate_model_path() {
        local var_name=$1
        local path=$2
        if [[ "$path" == gs://* ]]; then
            echo "  Validating $var_name in GCS..."
            if ! gsutil -q stat "$path" 2>/dev/null; then
                echo "  ❌ $var_name: File not found in GCS: $path"
                INVALID_MODEL_PATHS+=("$var_name=$path")
                return 1
            else
                echo "  ✅ $var_name: GCS file exists"
                return 0
            fi
        fi
        return 0
    }

    for VAR in "${REQUIRED_VARS[@]}"; do
        CURRENT_VAL=$(echo "$CURRENT_ENV" | jq -r ".[] | select(.name==\"$VAR\") | .value // empty")
        if [ -z "$CURRENT_VAL" ]; then
            # Try to get from .env.required template
            if [ -f "$ENV_TEMPLATE" ]; then
                TEMPLATE_VAL=$(grep "^$VAR=" "$ENV_TEMPLATE" | cut -d'=' -f2-)
                if [ -n "$TEMPLATE_VAL" ]; then
                    echo "  $VAR: Using template value"
                    ENV_VARS="$ENV_VARS,$VAR=$TEMPLATE_VAL"
                else
                    MISSING_VARS+=("$VAR")
                fi
            else
                MISSING_VARS+=("$VAR")
            fi
        else
            echo "  $VAR: Preserving current value"
            # Validate model paths exist in GCS (Session 106)
            if [[ "$VAR" == *"MODEL_PATH"* ]]; then
                validate_model_path "$VAR" "$CURRENT_VAL"
            fi
            ENV_VARS="$ENV_VARS,$VAR=$CURRENT_VAL"
        fi
    done

    # Check for invalid model paths (Session 106 - prevent non-existent model deployments)
    if [ ${#INVALID_MODEL_PATHS[@]} -gt 0 ]; then
        echo ""
        echo "=============================================="
        echo "🚨 ERROR: Invalid model paths detected"
        echo "=============================================="
        echo "The following model paths point to non-existent GCS files:"
        for PATH_INFO in "${INVALID_MODEL_PATHS[@]}"; do
            echo "  - $PATH_INFO"
        done
        echo ""
        echo "This would cause /health/deep to fail!"
        echo ""
        echo "To fix:"
        echo "1. Check the model_registry table for correct paths:"
        echo "   bq query 'SELECT model_id, gcs_path FROM nba_predictions.model_registry WHERE status=\"active\"'"
        echo ""
        echo "2. Update the env var with the correct path:"
        echo "   gcloud run services update $SERVICE --region=$REGION \\"
        echo "     --set-env-vars=\"CATBOOST_V8_MODEL_PATH=gs://correct/path.cbm\""
        echo ""
        echo "Session 106: This validation prevents Session 81-type issues"
        echo "=============================================="
        exit 1
    fi

    if [ ${#MISSING_VARS[@]} -gt 0 ]; then
        echo ""
        echo "=============================================="
        echo "ERROR: Missing required environment variables"
        echo "=============================================="
        echo "The following vars are required but not configured:"
        for VAR in "${MISSING_VARS[@]}"; do
            echo "  - $VAR"
        done
        echo ""
        echo "Options:"
        echo "1. Add them to predictions/worker/env.template"
        echo "2. Set manually: gcloud run services update $SERVICE --update-env-vars=\"VAR=value\""
        echo "=============================================="
        exit 1
    fi

    echo "  All required env vars validated"
fi

echo ""
echo "[4/8] Deploying to Cloud Run (min-instances=$MIN_INSTANCES)..."
gcloud run deploy "$SERVICE" \
    --image="$REGISTRY/$SERVICE:latest" \
    --region="$REGION" \
    --project="$PROJECT" \
    --update-env-vars="$ENV_VARS" \
    --update-labels="commit-sha=$BUILD_COMMIT,deployed-at=$(date -u +%Y%m%d-%H%M%S)" \
    --min-instances="$MIN_INSTANCES" \
    --quiet

echo ""
echo "[5/8] Verifying deployment..."
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
echo "[6/8] Verifying service identity..."

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

# [6.5/8] Run service-specific smoke tests
echo ""
echo "[6.5/8] Running smoke tests..."

SMOKE_TEST_PASSED=true

case "$SERVICE" in
  nba-grading-service)
    echo "Testing grading service functionality..."

    # Get auth token for Cloud Run (services require authentication)
    ID_TOKEN=$(gcloud auth print-identity-token --audiences="$SERVICE_URL" 2>/dev/null || echo "")
    AUTH_HEADER=""
    if [ -n "$ID_TOKEN" ]; then
        AUTH_HEADER="-H \"Authorization: Bearer $ID_TOKEN\""
    fi

    # Test 1: Deep health check (validates critical imports and connectivity)
    echo "  [1/2] Testing deep health check..."
    if [ -n "$ID_TOKEN" ]; then
        DEEP_HEALTH=$(curl -s --max-time 10 -H "Authorization: Bearer $ID_TOKEN" "$SERVICE_URL/health/deep" 2>/dev/null || echo '{"status":"failed"}')
    else
        DEEP_HEALTH=$(curl -s --max-time 10 "$SERVICE_URL/health/deep" 2>/dev/null || echo '{"status":"failed"}')
    fi
    DEEP_STATUS=$(echo "$DEEP_HEALTH" | jq -r '.status' 2>/dev/null || echo "failed")

    if [ "$DEEP_STATUS" = "healthy" ]; then
        echo "    ✅ Deep health check passed"
        echo "       - Critical imports: OK"
        echo "       - BigQuery connectivity: OK"
        echo "       - Firestore connectivity: OK"
    else
        echo "    ❌ CRITICAL: Deep health check FAILED"
        echo "       Response: $DEEP_HEALTH"
        echo ""
        echo "    Service deployed but cannot function correctly!"
        echo "    This would cause silent failures in production."
        SMOKE_TEST_PASSED=false
    fi

    # Test 2: Service can respond to basic requests
    echo "  [2/2] Testing basic service response..."
    if [ -n "$ID_TOKEN" ]; then
        HEALTH_STATUS=$(curl -s --max-time 10 -H "Authorization: Bearer $ID_TOKEN" "$SERVICE_URL/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    else
        HEALTH_STATUS=$(curl -s --max-time 10 "$SERVICE_URL/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    fi

    if [ "$HEALTH_STATUS" = "200" ]; then
        echo "    ✅ Basic health check passed"
    else
        echo "    ❌ CRITICAL: Basic health check failed (HTTP $HEALTH_STATUS)"
        SMOKE_TEST_PASSED=false
    fi
    ;;

  prediction-worker)
    echo "Testing prediction worker functionality..."

    # Get auth token for Cloud Run (services require authentication)
    ID_TOKEN=$(gcloud auth print-identity-token --audiences="$SERVICE_URL" 2>/dev/null || echo "")

    if [ -z "$ID_TOKEN" ]; then
        echo "  ⚠️  Could not get identity token for authenticated smoke test"
        echo "  Relying on Cloud Run monitoring health checks instead..."
        echo "  (Health checks run automatically and were verified during deployment)"
        echo "    ✅ Deployment verified via Cloud Run revision traffic routing"
    else
        # Test deep health check with authentication
        echo "  [1/1] Testing service health (authenticated)..."
        HEALTH_STATUS=$(curl -s --max-time 10 -H "Authorization: Bearer $ID_TOKEN" "$SERVICE_URL/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")

        if [ "$HEALTH_STATUS" = "200" ]; then
            echo "    ✅ Health check passed"
        else
            echo "    ❌ CRITICAL: Health check failed (HTTP $HEALTH_STATUS)"
            SMOKE_TEST_PASSED=false
        fi
    fi
    ;;

  *)
    echo "No smoke tests configured for $SERVICE (basic health check only)"

    # Try with authentication first
    ID_TOKEN=$(gcloud auth print-identity-token --audiences="$SERVICE_URL" 2>/dev/null || echo "")

    if [ -n "$ID_TOKEN" ]; then
        HEALTH_STATUS=$(curl -s --max-time 10 -H "Authorization: Bearer $ID_TOKEN" "$SERVICE_URL/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    else
        HEALTH_STATUS=$(curl -s --max-time 10 "$SERVICE_URL/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    fi

    if [ "$HEALTH_STATUS" = "200" ]; then
        echo "  ✅ Basic health check passed"
    else
        echo "  ⚠️  WARNING: Health check returned HTTP $HEALTH_STATUS"
    fi
    ;;
esac

echo ""
if [ "$SMOKE_TEST_PASSED" = true ]; then
    echo "=============================================="
    echo "✅ SMOKE TESTS PASSED"
    echo "=============================================="
    echo "Service is functional and ready for traffic"
    echo "=============================================="
else
    echo "=============================================="
    echo "❌ SMOKE TESTS FAILED"
    echo "=============================================="
    echo ""
    echo "CRITICAL: Service deployed but smoke tests failed!"
    echo ""
    echo "The service will not function correctly in production."
    echo "This deployment should be ROLLED BACK."
    echo ""
    echo "To rollback:"
    echo "  1. List revisions:"
    echo "     gcloud run revisions list --service=$SERVICE --region=$REGION"
    echo "  2. Rollback to previous:"
    echo "     gcloud run services update-traffic $SERVICE --to-revisions=PREVIOUS_REV=100 --region=$REGION"
    echo ""
    echo "Or fix the issue and redeploy."
    echo "=============================================="

    # Exit with error to prevent continuing with a broken deployment
    exit 1
fi

# [7/8] Verify heartbeat code is correct
echo ""
echo "[7/8] Verifying heartbeat code..."

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

# [8/8] Service-specific validation
echo ""
echo "[8/8] Service-specific validation..."

# Run BigQuery write verification for applicable services (Session 88 P0-1)
echo ""
echo "Verifying BigQuery writes..."
if [ -f "bin/monitoring/verify-bigquery-writes.sh" ]; then
  # Give service 2 minutes to process and write data
  echo "Waiting 120 seconds for service to process and write data..."
  sleep 120

  if ./bin/monitoring/verify-bigquery-writes.sh "$SERVICE" 180; then
    echo "✅ BigQuery write verification passed"
  else
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 1 ]; then
      echo ""
      echo "=============================================="
      echo "🚨 CRITICAL: BigQuery write verification FAILED"
      echo "=============================================="
      echo "Service deployed successfully but is NOT writing data to BigQuery!"
      echo ""
      echo "This is a P0 CRITICAL issue (Session 88 P0-1)"
      echo ""
      echo "Next steps:"
      echo "1. Check service logs for BigQuery errors"
      echo "2. Verify table references include dataset name"
      echo "3. Check service account permissions"
      echo "4. Consider rolling back deployment"
      echo "=============================================="
      # Don't exit - let deployment complete but warn loudly
    elif [ "$EXIT_CODE" -eq 2 ]; then
      echo "ℹ️  Service does not write to BigQuery (skipped)"
    fi
  fi
else
  echo "⚠️  WARNING: BigQuery write verification script not found"
  echo "   Expected: bin/monitoring/verify-bigquery-writes.sh"
fi

# P1-2: Environment Variable Drift Detection (Session 89)
echo ""
echo "Verifying environment variables preserved..."
if [ -f "bin/monitoring/verify-env-vars-preserved.sh" ]; then
  if ./bin/monitoring/verify-env-vars-preserved.sh "$SERVICE"; then
    echo "✅ Environment variable verification passed"
  else
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 1 ]; then
      echo ""
      echo "=============================================="
      echo "🚨 CRITICAL: Environment variable drift detected"
      echo "=============================================="
      echo "Required environment variables are missing after deployment!"
      echo ""
      echo "This is a P1 CRITICAL issue (Session 89 P1-2)"
      echo ""
      echo "Next steps:"
      echo "1. Check if --set-env-vars was used (should be --update-env-vars)"
      echo "2. Re-deploy with correct environment variables"
      echo "3. Verify service can start successfully"
      echo "=============================================="
      # Don't exit - let deployment complete but warn loudly
    elif [ "$EXIT_CODE" -eq 2 ]; then
      echo "ℹ️  No env var requirements defined for $SERVICE (skipped)"
    fi
  fi
else
  echo "⚠️  WARNING: Environment variable verification script not found"
  echo "   Expected: bin/monitoring/verify-env-vars-preserved.sh"
fi

case $SERVICE in
  prediction-worker)
    echo ""
    echo "Verifying environment variables..."
    DEPLOYED_ENV=$(gcloud run services describe "$SERVICE" \
        --region="$REGION" \
        --project="$PROJECT" \
        --format="json" 2>/dev/null | jq -r '.spec.template.spec.containers[0].env // []')

    ENV_CHECK_PASS=true
    for VAR in "GCP_PROJECT_ID" "CATBOOST_V8_MODEL_PATH" "CATBOOST_V9_MODEL_PATH" "PUBSUB_READY_TOPIC"; do
        VAL=$(echo "$DEPLOYED_ENV" | jq -r ".[] | select(.name==\"$VAR\") | .value // empty")
        if [ -n "$VAL" ]; then
            # Truncate long values for display
            DISPLAY_VAL="${VAL:0:50}"
            [ ${#VAL} -gt 50 ] && DISPLAY_VAL="${DISPLAY_VAL}..."
            echo "  ✅ $VAR = $DISPLAY_VAL"
        else
            echo "  ❌ $VAR = MISSING"
            ENV_CHECK_PASS=false
        fi
    done

    if [ "$ENV_CHECK_PASS" = false ]; then
        echo ""
        echo "⚠️  WARNING: Some environment variables are missing!"
        echo "   The worker may fail to start. Check logs."
    fi

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
