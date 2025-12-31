#!/bin/bash
# File: bin/validation/deploy_validation_runner.sh
# Purpose: Deploy the validation runner as a Cloud Run Job
# Usage: ./bin/validation/deploy_validation_runner.sh [--dry-run]

set -e

# Configuration
SERVICE_NAME="validation-runner"
REGION="${REGION:-us-west2}"
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse arguments
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run]"
            echo ""
            echo "Options:"
            echo "  --dry-run    Show what would be deployed without deploying"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}========================================"
echo -e "Validation Runner Deployment"
echo -e "========================================${NC}"
echo ""
echo -e "Project:  ${PROJECT_ID}"
echo -e "Region:   ${REGION}"
echo -e "Service:  ${SERVICE_NAME}"
echo -e "Image:    ${IMAGE_NAME}"
echo ""

# Load environment variables if .env exists
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    echo -e "${BLUE}Loading environment from .env...${NC}"
    export $(grep -v '^#' "${PROJECT_ROOT}/.env" | grep -v '^$' | xargs)
fi

# Check for required files
DOCKERFILE="${PROJECT_ROOT}/docker/validation.Dockerfile"
if [[ ! -f "$DOCKERFILE" ]]; then
    echo -e "${YELLOW}Warning: Dockerfile not found at $DOCKERFILE${NC}"
    echo -e "${YELLOW}Using default Python base image configuration${NC}"
    DOCKERFILE=""
fi

# Dry run mode
if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW}DRY RUN - Would execute:${NC}"
    echo ""
    echo "1. Build Docker image:"
    echo "   gcloud builds submit --tag ${IMAGE_NAME}"
    echo ""
    echo "2. Deploy Cloud Run Job:"
    echo "   gcloud run jobs create ${SERVICE_NAME} \\"
    echo "     --image ${IMAGE_NAME} \\"
    echo "     --region ${REGION} \\"
    echo "     --project ${PROJECT_ID} \\"
    echo "     --memory 2Gi \\"
    echo "     --cpu 1 \\"
    echo "     --task-timeout 30m \\"
    echo "     --max-retries 1"
    echo ""
    exit 0
fi

# Build the image
echo -e "${BLUE}Step 1: Building Docker image...${NC}"
BUILD_START=$(date +%s)

if [[ -n "$DOCKERFILE" ]]; then
    gcloud builds submit \
        --tag "${IMAGE_NAME}" \
        --project "${PROJECT_ID}" \
        --dockerfile "${DOCKERFILE}" \
        "${PROJECT_ROOT}"
else
    # Use inline Dockerfile for simple Python validation
    cat > /tmp/validation_dockerfile <<'DOCKERFILE'
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "bin/validation/validate_gcs_bq_completeness.py", "--help"]
DOCKERFILE

    gcloud builds submit \
        --tag "${IMAGE_NAME}" \
        --project "${PROJECT_ID}" \
        --dockerfile /tmp/validation_dockerfile \
        "${PROJECT_ROOT}"
fi

BUILD_END=$(date +%s)
BUILD_TIME=$((BUILD_END - BUILD_START))
echo -e "${GREEN}Build completed in ${BUILD_TIME}s${NC}"
echo ""

# Deploy or update the Cloud Run Job
echo -e "${BLUE}Step 2: Deploying Cloud Run Job...${NC}"

# Check if job exists
if gcloud run jobs describe ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID} >/dev/null 2>&1; then
    echo "Updating existing job..."
    gcloud run jobs update ${SERVICE_NAME} \
        --image ${IMAGE_NAME} \
        --region ${REGION} \
        --project ${PROJECT_ID} \
        --memory 2Gi \
        --cpu 1 \
        --task-timeout 30m \
        --max-retries 1 \
        --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID}"
else
    echo "Creating new job..."
    gcloud run jobs create ${SERVICE_NAME} \
        --image ${IMAGE_NAME} \
        --region ${REGION} \
        --project ${PROJECT_ID} \
        --memory 2Gi \
        --cpu 1 \
        --task-timeout 30m \
        --max-retries 1 \
        --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID}"
fi

echo ""
echo -e "${GREEN}========================================"
echo -e "Deployment Complete!"
echo -e "========================================${NC}"
echo ""
echo "To run the validation job:"
echo "  gcloud run jobs execute ${SERVICE_NAME} --region ${REGION}"
echo ""
echo "To view logs:"
echo "  gcloud run jobs logs ${SERVICE_NAME} --region ${REGION}"
