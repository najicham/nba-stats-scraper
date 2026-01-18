#!/bin/bash
# bin/predictions/deploy/deploy_prediction_worker.sh
#
# Deploy Phase 5 Prediction Worker to Cloud Run
#
# Usage:
#   ./bin/predictions/deploy/deploy_prediction_worker.sh [environment]
#
# Arguments:
#   environment - dev, staging, or prod (default: prod)
#
# Example:
#   ./bin/predictions/deploy/deploy_prediction_worker.sh dev
#   ./bin/predictions/deploy/deploy_prediction_worker.sh prod

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Environment (default: prod - this is a single-environment project)
ENVIRONMENT="${1:-prod}"

# Project configuration
case "$ENVIRONMENT" in
    dev)
        PROJECT_ID="nba-props-platform-dev"
        REGION="us-west2"
        SERVICE_NAME="prediction-worker-dev"
        MIN_INSTANCES=0
        MAX_INSTANCES=5
        CONCURRENCY=5
        MEMORY="2Gi"
        CPU=1
        TIMEOUT=300
        ;;
    staging)
        PROJECT_ID="nba-props-platform-staging"
        REGION="us-west2"
        SERVICE_NAME="prediction-worker-staging"
        MIN_INSTANCES=0
        MAX_INSTANCES=10
        CONCURRENCY=5
        MEMORY="2Gi"
        CPU=1
        TIMEOUT=300
        ;;
    prod)
        PROJECT_ID="nba-props-platform"
        REGION="us-west2"
        SERVICE_NAME="prediction-worker"
        MIN_INSTANCES=0  # Scale to zero - predictions run via local backfill scripts, not Cloud Run
        # Concurrency settings - configurable via environment variables
        # Default: 10 instances × 5 concurrent = 50 concurrent (optimized Dec 31, 2025)
        #   Reduced from 100 workers - sufficient for ~450 players/day
        #   40% cost reduction while maintaining 2-3 min completion time
        # Emergency: 4 instances × 3 concurrent = 12 concurrent (safe mode)
        MAX_INSTANCES="${WORKER_MAX_INSTANCES:-10}"
        CONCURRENCY="${WORKER_CONCURRENCY:-5}"
        MEMORY="2Gi"
        CPU=2
        TIMEOUT=300
        ;;
    *)
        echo "Error: Invalid environment '$ENVIRONMENT'"
        echo "Valid environments: dev, staging, prod"
        exit 1
        ;;
esac

# Docker image configuration
IMAGE_NAME="predictions-worker"
IMAGE_TAG="${ENVIRONMENT}-$(date +%Y%m%d-%H%M%S)"
IMAGE_FULL="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${ENVIRONMENT}-latest"

# Pub/Sub configuration
PUBSUB_SUBSCRIPTION="prediction-request-${ENVIRONMENT}"
PUBSUB_READY_TOPIC="prediction-ready-${ENVIRONMENT}"

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
    
    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        error "gcloud CLI not found. Please install Google Cloud SDK."
    fi
    
    # Check if docker is installed
    if ! command -v docker &> /dev/null; then
        error "docker not found. Please install Docker."
    fi
    
    # Check if logged in to gcloud
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        error "Not logged in to gcloud. Run: gcloud auth login"
    fi
    
    log "Prerequisites OK"
}

build_and_push_image() {
    log "Building Docker image..."
    
    cd "$PROJECT_ROOT"
    
    # Build image (with --no-cache to ensure latest code is used)
    docker build \
        --no-cache \
        -f docker/predictions-worker.Dockerfile \
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

    # CRITICAL: Preserve existing environment variables to avoid deleting CATBOOST_V8_MODEL_PATH
    # This was the root cause of the Jan 2026 CatBoost V8 incident
    log "Fetching current environment variables to preserve critical settings..."

    # Get current CATBOOST_V8_MODEL_PATH (if exists)
    CATBOOST_MODEL_PATH=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format=json 2>/dev/null | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CATBOOST_V8_MODEL_PATH") | .value' || echo "")

    # Build environment variables string
    ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID},PREDICTIONS_TABLE=nba_predictions.player_prop_predictions,PUBSUB_READY_TOPIC=${PUBSUB_READY_TOPIC}"

    # Add CATBOOST_V8_MODEL_PATH if it exists
    if [ -n "$CATBOOST_MODEL_PATH" ]; then
        log "Preserving CATBOOST_V8_MODEL_PATH: $CATBOOST_MODEL_PATH"
        ENV_VARS="${ENV_VARS},CATBOOST_V8_MODEL_PATH=${CATBOOST_MODEL_PATH}"
    else
        log "WARNING: CATBOOST_V8_MODEL_PATH not found in current service"
        log "WARNING: Predictions will use FALLBACK mode (50% confidence)"
        log "Set CATBOOST_V8_MODEL_PATH after deployment using:"
        log "  gcloud run services update $SERVICE_NAME --region $REGION --project $PROJECT_ID \\"
        log "    --update-env-vars CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/[MODEL_FILE]"
    fi

    # Add XGBOOST_V1_MODEL_PATH (Session 88 - Option D Phase 5A)
    # Default to newly trained model from 2021 data
    XGBOOST_V1_MODEL_PATH="${XGBOOST_V1_MODEL_PATH:-gs://nba-scraped-data/ml-models/xgboost_v1_33features_20260117_163206.json}"
    log "Setting XGBOOST_V1_MODEL_PATH: $XGBOOST_V1_MODEL_PATH"
    ENV_VARS="${ENV_VARS},XGBOOST_V1_MODEL_PATH=${XGBOOST_V1_MODEL_PATH}"

    # Deploy with all environment variables
    gcloud run deploy "$SERVICE_NAME" \
        --image "$IMAGE_FULL" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --platform managed \
        --memory "$MEMORY" \
        --cpu "$CPU" \
        --timeout "$TIMEOUT" \
        --concurrency "$CONCURRENCY" \
        --min-instances "$MIN_INSTANCES" \
        --max-instances "$MAX_INSTANCES" \
        --set-env-vars "$ENV_VARS" \
        --allow-unauthenticated \
        --service-account "prediction-worker@${PROJECT_ID}.iam.gserviceaccount.com" \
        --ingress all \
        --quiet

    log "Cloud Run deployment complete"
}

configure_pubsub() {
    log "Configuring Pub/Sub subscription..."
    
    # Get Cloud Run service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    log "Service URL: $SERVICE_URL"
    
    # Create or update Pub/Sub push subscription
    PUSH_ENDPOINT="${SERVICE_URL}/predict"
    
    # Check if subscription exists
    if gcloud pubsub subscriptions describe "$PUBSUB_SUBSCRIPTION" \
        --project "$PROJECT_ID" &> /dev/null; then
        
        log "Updating existing subscription..."
        gcloud pubsub subscriptions update "$PUBSUB_SUBSCRIPTION" \
            --project "$PROJECT_ID" \
            --push-endpoint "$PUSH_ENDPOINT" \
            --push-auth-service-account "prediction-worker@${PROJECT_ID}.iam.gserviceaccount.com" \
            --ack-deadline 300 \
            --quiet
    else
        log "Creating new subscription..."
        gcloud pubsub subscriptions create "$PUBSUB_SUBSCRIPTION" \
            --project "$PROJECT_ID" \
            --topic "prediction-request-${ENVIRONMENT}" \
            --push-endpoint "$PUSH_ENDPOINT" \
            --push-auth-service-account "prediction-worker@${PROJECT_ID}.iam.gserviceaccount.com" \
            --ack-deadline 300 \
            --quiet
    fi
    
    log "Pub/Sub configuration complete"
}

verify_deployment() {
    log "Verifying deployment..."
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    log "Service deployed at: $SERVICE_URL"
    
    # Check service status
    gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.conditions[0].status)" | grep -q "True" || \
        error "Service not ready"
    
    log "Deployment verified successfully"
}

send_deployment_notification() {
    log "Sending deployment notification..."

    # Get Slack webhook from Secret Manager (if exists)
    SLACK_WEBHOOK=$(gcloud secrets versions access latest \
        --secret="deployment-notifications-slack-webhook" \
        --project="$PROJECT_ID" 2>/dev/null || echo "")

    if [ -z "$SLACK_WEBHOOK" ]; then
        log "No Slack webhook configured - skipping notification"
        return 0
    fi

    # Get service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")

    # Get deployer
    DEPLOYER=$(gcloud config get-value account 2>/dev/null || echo "unknown")

    # Get current timestamp
    TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S %Z")

    # Get image tag (short version for readability)
    IMAGE_SHORT=$(echo "$IMAGE_TAG" | cut -d'-' -f1-2)

    # Send notification to Slack
    curl -X POST "$SLACK_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{
            \"text\": \"✅ NBA Prediction Worker Deployed\",
            \"blocks\": [
                {
                    \"type\": \"header\",
                    \"text\": {
                        \"type\": \"plain_text\",
                        \"text\": \"✅ NBA Prediction Worker Deployed\"
                    }
                },
                {
                    \"type\": \"section\",
                    \"fields\": [
                        {
                            \"type\": \"mrkdwn\",
                            \"text\": \"*Environment:*\n${ENVIRONMENT}\"
                        },
                        {
                            \"type\": \"mrkdwn\",
                            \"text\": \"*Version:*\n${IMAGE_SHORT}\"
                        },
                        {
                            \"type\": \"mrkdwn\",
                            \"text\": \"*Deployed by:*\n${DEPLOYER}\"
                        },
                        {
                            \"type\": \"mrkdwn\",
                            \"text\": \"*Timestamp:*\n${TIMESTAMP}\"
                        }
                    ]
                },
                {
                    \"type\": \"section\",
                    \"fields\": [
                        {
                            \"type\": \"mrkdwn\",
                            \"text\": \"*Max Instances:*\n${MAX_INSTANCES}\"
                        },
                        {
                            \"type\": \"mrkdwn\",
                            \"text\": \"*Concurrency:*\n${CONCURRENCY}\"
                        }
                    ]
                },
                {
                    \"type\": \"section\",
                    \"text\": {
                        \"type\": \"mrkdwn\",
                        \"text\": \"<${SERVICE_URL}|Service URL> • <${SERVICE_URL}/health|Health Check>\"
                    }
                }
            ]
        }" 2>&1 | grep -q "ok" && \
        log "Notification sent successfully" || \
        log "Warning: Failed to send notification (non-fatal)"
}

show_deployment_info() {
    log "============================================"
    log "Deployment Summary"
    log "============================================"
    log "Environment:       $ENVIRONMENT"
    log "Project ID:        $PROJECT_ID"
    log "Region:            $REGION"
    log "Service Name:      $SERVICE_NAME"
    log "Image:             $IMAGE_FULL"
    log "Min Instances:     $MIN_INSTANCES"
    log "Max Instances:     $MAX_INSTANCES"
    log "Concurrency:       $CONCURRENCY"
    log "Memory:            $MEMORY"
    log "CPU:               $CPU"
    log "Timeout:           ${TIMEOUT}s"
    log "Subscription:      $PUBSUB_SUBSCRIPTION"
    log "============================================"

    # Get service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")

    log "Service URL: $SERVICE_URL"
    log "Health Check: ${SERVICE_URL}/health"
    log ""
    log "Next steps:"
    log "  1. Test with: ./bin/predictions/deploy/test_prediction_worker.sh $ENVIRONMENT"
    log "  2. Monitor logs: gcloud run services logs read $SERVICE_NAME --project $PROJECT_ID --region $REGION"
    log "  3. Check metrics: https://console.cloud.google.com/run/detail/${REGION}/${SERVICE_NAME}/metrics?project=${PROJECT_ID}"
}

# ============================================================================
# Main
# ============================================================================

main() {
    log "Starting deployment for environment: $ENVIRONMENT"
    
    check_prerequisites
    build_and_push_image
    deploy_cloud_run
    configure_pubsub
    verify_deployment
    send_deployment_notification
    show_deployment_info

    log "Deployment complete! 🚀"
}

# Run main function
main
