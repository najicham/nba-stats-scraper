#!/bin/bash
# bin/predictions/deploy/deploy_prediction_coordinator.sh
#
# Deploy Phase 5 Prediction Coordinator to Cloud Run
#
# Purpose:
#   Builds Docker image and deploys coordinator service that orchestrates
#   daily prediction batches by fanning out work to prediction workers.
#
# Usage:
#   ./bin/predictions/deploy/deploy_prediction_coordinator.sh [environment]
#
# Arguments:
#   environment - dev, staging, or prod (default: dev)
#
# Example:
#   ./bin/predictions/deploy/deploy_prediction_coordinator.sh dev
#   ./bin/predictions/deploy/deploy_prediction_coordinator.sh prod
#
# What This Script Does:
#   1. Validates prerequisites (gcloud, docker)
#   2. Builds Docker image with coordinator code
#   3. Pushes image to Artifact Registry
#   4. Deploys to Cloud Run with environment-specific config
#   5. Verifies deployment health
#   6. (Optional) Sets up Cloud Scheduler job for daily triggers

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Environment (default: dev)
ENVIRONMENT="${1:-dev}"

# Project configuration by environment
case "$ENVIRONMENT" in
    dev)
        PROJECT_ID="nba-props-platform-dev"
        REGION="us-west2"
        SERVICE_NAME="prediction-coordinator-dev"

        # Scaling: Single instance for threading lock compatibility
        MIN_INSTANCES=0
        MAX_INSTANCES=1  # IMPORTANT: Threading locks require single instance

        CONCURRENCY=8  # 8 concurrent /complete events
        MEMORY="1Gi"   # Coordinator is lightweight
        CPU=1
        TIMEOUT=600    # 10 minutes (batch startup can be slow with 450 players)
        ;;
    staging)
        PROJECT_ID="nba-props-platform-staging"
        REGION="us-west2"
        SERVICE_NAME="prediction-coordinator-staging"

        # Scaling: Single instance for threading lock compatibility
        MIN_INSTANCES=0
        MAX_INSTANCES=1

        CONCURRENCY=8
        MEMORY="1Gi"
        CPU=1
        TIMEOUT=600
        ;;
    prod)
        PROJECT_ID="nba-props-platform"
        REGION="us-west2"
        SERVICE_NAME="prediction-coordinator"

        # Scaling: Production can use single instance OR migrate to Firestore
        # Current: Single instance with threading locks
        # Future: Multiple instances with Firestore state management
        MIN_INSTANCES=1  # Always running for immediate response
        MAX_INSTANCES=1  # Threading locks - increase after Firestore migration

        CONCURRENCY=8
        MEMORY="2Gi"
        CPU=2
        TIMEOUT=600
        ;;
    *)
        echo "Error: Invalid environment '$ENVIRONMENT'"
        echo "Valid environments: dev, staging, prod"
        exit 1
        ;;
esac

# Docker image configuration
IMAGE_NAME="predictions-coordinator"
IMAGE_TAG="${ENVIRONMENT}-$(date +%Y%m%d-%H%M%S)"
IMAGE_FULL="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${ENVIRONMENT}-latest"

# Pub/Sub topics (coordinator publishes to these)
PREDICTION_REQUEST_TOPIC="prediction-request-${ENVIRONMENT}"
PREDICTION_READY_TOPIC="prediction-ready-${ENVIRONMENT}"
BATCH_SUMMARY_TOPIC="prediction-batch-complete-${ENVIRONMENT}"

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
    
    # Check if project exists
    if ! gcloud projects describe "$PROJECT_ID" &> /dev/null; then
        error "Project $PROJECT_ID not found. Check PROJECT_ID configuration."
    fi
    
    log "Prerequisites OK"
}

build_and_push_image() {
    log "Building Docker image..."
    
    cd "$PROJECT_ROOT"
    
    # Build image
    docker build \
        -f docker/predictions-coordinator.Dockerfile \
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
    
    # Deploy coordinator service
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
        --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},PREDICTION_REQUEST_TOPIC=${PREDICTION_REQUEST_TOPIC},PREDICTION_READY_TOPIC=${PREDICTION_READY_TOPIC},BATCH_SUMMARY_TOPIC=${BATCH_SUMMARY_TOPIC}" \
        --allow-unauthenticated \
        --service-account "prediction-coordinator@${PROJECT_ID}.iam.gserviceaccount.com" \
        --ingress all \
        --quiet
    
    log "Cloud Run deployment complete"
}

setup_cloud_scheduler() {
    log "Setting up Cloud Scheduler (optional)..."
    
    # Get Cloud Run service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    # Cloud Scheduler job name
    SCHEDULER_JOB="prediction-coordinator-daily-${ENVIRONMENT}"
    
    # Check if job already exists
    if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
        --project "$PROJECT_ID" \
        --location "$REGION" &> /dev/null; then
        
        log "Updating existing Cloud Scheduler job..."
        gcloud scheduler jobs update http "$SCHEDULER_JOB" \
            --project "$PROJECT_ID" \
            --location "$REGION" \
            --schedule "0 6 * * *" \
            --time-zone "America/Los_Angeles" \
            --uri "${SERVICE_URL}/start" \
            --http-method POST \
            --oidc-service-account-email "prediction-coordinator@${PROJECT_ID}.iam.gserviceaccount.com" \
            --headers "Content-Type=application/json" \
            --message-body '{}' \
            --quiet
    else
        log "Creating new Cloud Scheduler job..."
        gcloud scheduler jobs create http "$SCHEDULER_JOB" \
            --project "$PROJECT_ID" \
            --location "$REGION" \
            --schedule "0 6 * * *" \
            --time-zone "America/Los_Angeles" \
            --uri "${SERVICE_URL}/start" \
            --http-method POST \
            --oidc-service-account-email "prediction-coordinator@${PROJECT_ID}.iam.gserviceaccount.com" \
            --headers "Content-Type=application/json" \
            --message-body '{}' \
            --quiet
    fi
    
    log "Cloud Scheduler configured (runs daily at 6:00 AM PT)"
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
    log "Topics:"
    log "  - Request:       $PREDICTION_REQUEST_TOPIC"
    log "  - Ready:         $PREDICTION_READY_TOPIC"
    log "  - Summary:       $BATCH_SUMMARY_TOPIC"
    log "============================================"
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    log "Service URL: $SERVICE_URL"
    log "Health Check: ${SERVICE_URL}/health"
    log ""
    log "Endpoints:"
    log "  POST ${SERVICE_URL}/start    - Start prediction batch"
    log "  GET  ${SERVICE_URL}/status   - Check batch status"
    log "  POST ${SERVICE_URL}/complete - Worker completion event (internal)"
    log ""
    log "Test batch manually:"
    log "  TOKEN=\$(gcloud auth print-identity-token)"
    log "  curl -X POST ${SERVICE_URL}/start \\"
    log "    -H \"Authorization: Bearer \$TOKEN\" \\"
    log "    -H \"Content-Type: application/json\" \\"
    log "    -d '{\"game_date\": \"2025-11-08\"}'"
    log ""
    log "Monitor logs:"
    log "  gcloud run services logs read $SERVICE_NAME \\"
    log "    --project $PROJECT_ID --region $REGION --limit 100"
    log ""
    log "View metrics:"
    log "  https://console.cloud.google.com/run/detail/${REGION}/${SERVICE_NAME}/metrics?project=${PROJECT_ID}"
}

# ============================================================================
# Main
# ============================================================================

main() {
    log "Starting deployment for environment: $ENVIRONMENT"
    
    check_prerequisites
    build_and_push_image
    deploy_cloud_run
    verify_deployment
    
    # Ask about Cloud Scheduler setup
    if [ "$ENVIRONMENT" = "prod" ]; then
        read -p "Set up Cloud Scheduler for daily 6 AM triggers? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            setup_cloud_scheduler
        else
            log "Skipping Cloud Scheduler setup (can run manually later)"
        fi
    fi
    
    show_deployment_info
    
    log "Deployment complete! 🚀"
}

# Run main function
main
