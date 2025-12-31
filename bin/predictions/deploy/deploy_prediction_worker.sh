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
    
    # Build image
    docker build \
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
        --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},PREDICTIONS_TABLE=nba_predictions.player_prop_predictions,PUBSUB_READY_TOPIC=${PUBSUB_READY_TOPIC}" \
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
    show_deployment_info
    
    log "Deployment complete! 🚀"
}

# Run main function
main
