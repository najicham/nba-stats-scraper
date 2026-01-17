#!/bin/bash
# scripts/deploy_mlb_multi_model.sh
#
# MLB Multi-Model Architecture Deployment Script
#
# Usage:
#   ./scripts/deploy_mlb_multi_model.sh [stage]
#
# Stages:
#   phase1   - Deploy V1 baseline only (safe mode)
#   phase2   - Deploy V1 + V1.6 (two systems)
#   phase3   - Deploy all systems including ensemble
#   rollback - Rollback to V1 baseline only
#
# Example:
#   ./scripts/deploy_mlb_multi_model.sh phase1
#   ./scripts/deploy_mlb_multi_model.sh phase3

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
REGION=${GCP_REGION:-"us-central1"}
SERVICE_NAME="mlb-prediction-worker"

# Model paths
V1_MODEL_PATH="gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json"
V1_6_MODEL_PATH="gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json"

# Parse stage argument
STAGE=${1:-"phase1"}

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}MLB Multi-Model Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Stage: $STAGE"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo ""

# Determine active systems based on stage
case "$STAGE" in
  phase1)
    echo -e "${YELLOW}Phase 1: V1 Baseline Only (Safe Mode)${NC}"
    ACTIVE_SYSTEMS="v1_baseline"
    ;;
  phase2)
    echo -e "${YELLOW}Phase 2: V1 + V1.6 (Two Systems)${NC}"
    ACTIVE_SYSTEMS="v1_baseline,v1_6_rolling"
    ;;
  phase3)
    echo -e "${YELLOW}Phase 3: All Systems (V1 + V1.6 + Ensemble)${NC}"
    ACTIVE_SYSTEMS="v1_baseline,v1_6_rolling,ensemble_v1"
    ;;
  rollback)
    echo -e "${RED}Rollback: Reverting to V1 Baseline${NC}"
    ACTIVE_SYSTEMS="v1_baseline"
    ;;
  *)
    echo -e "${RED}Error: Invalid stage '$STAGE'${NC}"
    echo "Valid stages: phase1, phase2, phase3, rollback"
    exit 1
    ;;
esac

echo "Active systems: $ACTIVE_SYSTEMS"
echo ""

# Confirm deployment
read -p "Deploy to production? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo -e "${RED}Deployment cancelled${NC}"
  exit 0
fi

echo ""
echo -e "${GREEN}Starting deployment...${NC}"
echo ""

# Build Docker image using Cloud Build
echo "Building Docker image..."
gcloud builds submit \
  --project="$PROJECT_ID" \
  --config=cloudbuild-mlb-worker.yaml \
  .

echo ""
echo "Deploying to Cloud Run..."
# Create temporary env vars file
ENV_VARS_FILE=$(mktemp)
cat > "$ENV_VARS_FILE" <<EOF
MLB_ACTIVE_SYSTEMS: "${ACTIVE_SYSTEMS}"
MLB_V1_MODEL_PATH: "${V1_MODEL_PATH}"
MLB_V1_6_MODEL_PATH: "${V1_6_MODEL_PATH}"
MLB_ENSEMBLE_V1_WEIGHT: "0.3"
MLB_ENSEMBLE_V1_6_WEIGHT: "0.5"
GCP_PROJECT_ID: "${PROJECT_ID}"
EOF

gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="gcr.io/$PROJECT_ID/$SERVICE_NAME:latest" \
  --env-vars-file="$ENV_VARS_FILE" \
  --memory=2Gi \
  --cpu=2 \
  --timeout=300 \
  --max-instances=10 \
  --allow-unauthenticated \
  --quiet

# Clean up temp file
rm -f "$ENV_VARS_FILE"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Get service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --format="value(status.url)")

echo "Service URL: $SERVICE_URL"
echo ""

# Verify deployment
echo -e "${GREEN}Verifying deployment...${NC}"
echo ""

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/")

if [ "$HTTP_CODE" = "200" ]; then
  echo -e "${GREEN}✓ Health check passed (HTTP 200)${NC}"

  # Get service info
  SERVICE_INFO=$(curl -s "$SERVICE_URL/")
  echo ""
  echo "Service Info:"
  echo "$SERVICE_INFO" | python3 -m json.tool
  echo ""

  # Extract active systems from response
  DEPLOYED_SYSTEMS=$(echo "$SERVICE_INFO" | python3 -c "import sys, json; print(', '.join(json.load(sys.stdin).get('active_systems', [])))" 2>/dev/null || echo "unknown")

  echo -e "${GREEN}Active Systems: $DEPLOYED_SYSTEMS${NC}"

  if [ "$DEPLOYED_SYSTEMS" = "$ACTIVE_SYSTEMS" ]; then
    echo -e "${GREEN}✓ Correct systems deployed${NC}"
  else
    echo -e "${YELLOW}⚠ Warning: Deployed systems don't match expected${NC}"
    echo "  Expected: $ACTIVE_SYSTEMS"
    echo "  Deployed: $DEPLOYED_SYSTEMS"
  fi
else
  echo -e "${RED}✗ Health check failed (HTTP $HTTP_CODE)${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Next Steps${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "1. Monitor logs:"
echo "   gcloud logging tail --project=$PROJECT_ID --resource-type=cloud_run_revision --filter='resource.labels.service_name=$SERVICE_NAME'"
echo ""
echo "2. Test predictions (update date):"
echo "   curl -X POST $SERVICE_URL/predict-batch \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"game_date\": \"2026-01-20\", \"write_to_bigquery\": false}'"
echo ""
echo "3. Verify system coverage (after predictions run):"
echo "   bq query \"SELECT * FROM \\\`$PROJECT_ID.mlb_predictions.daily_coverage\\\` WHERE game_date = CURRENT_DATE()\""
echo ""
echo "4. Monitor system performance:"
echo "   bq query \"SELECT * FROM \\\`$PROJECT_ID.mlb_predictions.system_performance\\\`\""
echo ""
