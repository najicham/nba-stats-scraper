#!/bin/bash
# bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
#
# Deploy MLB Prediction Worker to Cloud Run
#
# Usage: ./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
#
# Prerequisites:
# - gcloud CLI authenticated
# - Docker installed
# - Model uploaded to GCS

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_NAME="mlb-prediction-worker"

# Docker image configuration
IMAGE_NAME="mlb-prediction-worker"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_FULL="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:latest"

# Model path in GCS
# V1.6 Classifier Model - 60% win rate vs V1.4 in shadow testing, 10.6% MAE improvement
# Previous: mlb_pitcher_strikeouts_v1_4features_20260114_142456.json (V1.4)
MODEL_PATH="gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json"

# Service account (default compute service account)
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

# ============================================================================
# Functions
# ============================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
    exit 1
}

check_prerequisites() {
    log "Checking prerequisites..."

    if ! command -v gcloud &> /dev/null; then
        error "gcloud CLI not found"
    fi

    if ! command -v docker &> /dev/null; then
        error "docker not found"
    fi

    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        error "Not logged in to gcloud"
    fi

    log "Prerequisites OK"
}

build_and_push_image() {
    log "Building Docker image..."

    cd "$PROJECT_ROOT"

    # Build image
    docker build \
        -f docker/mlb-prediction-worker.Dockerfile \
        -t "$IMAGE_FULL" \
        -t "$IMAGE_LATEST" \
        .

    log "Pushing Docker image to Artifact Registry..."

    # Configure docker auth
    gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

    # Push both tags
    docker push "$IMAGE_FULL"
    docker push "$IMAGE_LATEST"

    log "Image pushed: $IMAGE_FULL"
}

deploy_cloud_run() {
    log "Deploying to Cloud Run..."

    # Build environment variables
    ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID}"
    ENV_VARS="${ENV_VARS},MLB_MODEL_PATH=${MODEL_PATH}"
    ENV_VARS="${ENV_VARS},MLB_PREDICTIONS_TABLE=mlb_predictions.pitcher_strikeouts"
    ENV_VARS="${ENV_VARS},PYTHONPATH=/app"

    # Add email alerting configuration if available
    EMAIL_STATUS="DISABLED"
    if [[ -n "${BREVO_SMTP_PASSWORD:-}" && -n "${EMAIL_ALERTS_TO:-}" ]]; then
        log "Adding email alerting configuration..."

        ENV_VARS="${ENV_VARS},BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
        ENV_VARS="${ENV_VARS},BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
        ENV_VARS="${ENV_VARS},BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME:-}"
        ENV_VARS="${ENV_VARS},BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
        ENV_VARS="${ENV_VARS},BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL:-}"
        ENV_VARS="${ENV_VARS},BREVO_FROM_NAME=${BREVO_FROM_NAME:-MLB Prediction System}"
        ENV_VARS="${ENV_VARS},EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
        ENV_VARS="${ENV_VARS},EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"

        EMAIL_STATUS="ENABLED"
    else
        log "Email alerting not configured (set BREVO_SMTP_PASSWORD and EMAIL_ALERTS_TO)"
    fi

    log "Email Alerting: $EMAIL_STATUS"

    gcloud run deploy "$SERVICE_NAME" \
        --image "$IMAGE_FULL" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --platform managed \
        --allow-unauthenticated \
        --service-account "$SERVICE_ACCOUNT" \
        --memory 2Gi \
        --cpu 2 \
        --timeout 300 \
        --min-instances 0 \
        --max-instances 5 \
        --concurrency 10 \
        --set-env-vars "$ENV_VARS"

    log "Deployment complete"
}

test_service() {
    log "Testing service health..."

    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")

    log "Service URL: $SERVICE_URL"

    # Test health endpoint
    HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/health")
    if [ "$HEALTH_STATUS" = "200" ]; then
        log "Health check: PASSED"
    else
        error "Health check FAILED (status: ${HEALTH_STATUS})"
    fi

    # Test info endpoint
    log "Service info:"
    curl -s "${SERVICE_URL}/" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  Service: {d.get(\"service\")}')
print(f'  Model: {d.get(\"model\", {}).get(\"id\")}')
print(f'  MAE: {d.get(\"model\", {}).get(\"mae\")}')
"
}

# ============================================================================
# Main
# ============================================================================

main() {
    echo "=========================================="
    echo " MLB Prediction Worker Deployment"
    echo "=========================================="
    echo "Project: ${PROJECT_ID}"
    echo "Region: ${REGION}"
    echo "Service: ${SERVICE_NAME}"
    echo "Model: ${MODEL_PATH}"
    echo ""

    check_prerequisites

    # Check model exists
    log "Checking model in GCS..."
    if ! gsutil ls "${MODEL_PATH}" > /dev/null 2>&1; then
        error "Model not found at ${MODEL_PATH}"
    fi
    log "Model found"

    build_and_push_image
    deploy_cloud_run
    test_service

    echo ""
    echo "=========================================="
    echo " Deployment Complete"
    echo "=========================================="

    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")

    echo "Service: ${SERVICE_NAME}"
    echo "URL: ${SERVICE_URL}"
    echo ""
    echo "Test prediction:"
    echo "  curl -X POST ${SERVICE_URL}/predict \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"pitcher_lookup\": \"garrett_crochet\", \"game_date\": \"2025-09-15\", \"strikeouts_line\": 7.5}'"
    echo ""
}

main "$@"
