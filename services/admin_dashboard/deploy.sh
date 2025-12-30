#!/bin/bash
# Deploy NBA Admin Dashboard to Cloud Run

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="${GCP_REGION:-us-west2}"
SERVICE_NAME="nba-admin-dashboard"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Deploying NBA Admin Dashboard...${NC}"

# Navigate to repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

echo -e "${GREEN}Building Docker image...${NC}"

# Build the image
docker build -f services/admin_dashboard/Dockerfile -t "${IMAGE_NAME}" .

echo -e "${GREEN}Pushing image to GCR...${NC}"

# Push to GCR
docker push "${IMAGE_NAME}"

echo -e "${GREEN}Deploying to Cloud Run...${NC}"

# Generate a random API key if not set
API_KEY="${ADMIN_DASHBOARD_API_KEY:-$(openssl rand -hex 16)}"

# Deploy to Cloud Run
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE_NAME}" \
    --platform managed \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 2 \
    --timeout 120 \
    --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},ADMIN_DASHBOARD_API_KEY=${API_KEY}" \
    --allow-unauthenticated \
    --quiet

# Get the service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --platform managed \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --format 'value(status.url)')

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Dashboard URL: ${YELLOW}${SERVICE_URL}/dashboard${NC}"
echo -e "API Key: ${YELLOW}${API_KEY}${NC}"
echo ""
echo -e "Access the dashboard at: ${SERVICE_URL}/dashboard?key=${API_KEY}"
echo ""
echo -e "${RED}IMPORTANT: Save the API key! It won't be shown again.${NC}"
echo ""
