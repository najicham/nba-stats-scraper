#!/bin/bash
# Test MLB Slack Alert Integration

PROJECT_ID="nba-props-platform"
TOPIC="mlb-monitoring-alerts"

echo "======================================"
echo "MLB Slack Alerts - Test Script"
echo "======================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "Testing all severity levels..."
echo ""

# Test 1: INFO
echo -e "${GREEN}[1/4] Testing INFO alert...${NC}"
gcloud pubsub topics publish $TOPIC \
  --message='{"severity":"info","title":"MLB Monitoring Test - INFO","message":"This is a test INFO level alert from the automated test script","context":{"test":true,"severity":"info","timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}}' \
  --project=$PROJECT_ID
echo "  ✓ INFO alert published"
echo ""

sleep 2

# Test 2: WARNING
echo -e "${YELLOW}[2/4] Testing WARNING alert...${NC}"
gcloud pubsub topics publish $TOPIC \
  --message='{"severity":"warning","title":"MLB Monitoring Test - WARNING","message":"This is a test WARNING level alert. This would typically indicate low coverage or stale data.","context":{"test":true,"severity":"warning","coverage_pct":85,"threshold":90,"timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}}' \
  --project=$PROJECT_ID
echo "  ✓ WARNING alert published"
echo ""

sleep 2

# Test 3: ERROR
echo -e "${RED}[3/4] Testing ERROR alert...${NC}"
gcloud pubsub topics publish $TOPIC \
  --message='{"severity":"error","title":"MLB Monitoring Test - ERROR","message":"This is a test ERROR level alert. This would typically indicate a job failure or data quality issue.","context":{"test":true,"severity":"error","failed_job":"mlb-analytics","error_count":3,"timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}}' \
  --project=$PROJECT_ID
echo "  ✓ ERROR alert published"
echo ""

sleep 2

# Test 4: CRITICAL
echo -e "${RED}[4/4] Testing CRITICAL alert...${NC}"
gcloud pubsub topics publish $TOPIC \
  --message='{"severity":"critical","title":"MLB Monitoring Test - CRITICAL","message":"This is a test CRITICAL level alert. This would typically indicate a complete pipeline failure requiring immediate attention.","context":{"test":true,"severity":"critical","pipeline":"analytics","status":"failed","affected_games":15,"timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"}}' \
  --project=$PROJECT_ID
echo "  ✓ CRITICAL alert published"
echo ""

echo "======================================"
echo "All test alerts published!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Check your Slack channels for the test alerts"
echo "2. Verify alerts appear in the correct channels based on severity:"
echo "   - INFO → General monitoring channel"
echo "   - WARNING → Warnings channel"
echo "   - ERROR/CRITICAL → Critical alerts channel"
echo ""
echo "3. View Cloud Function logs:"
echo "   gcloud functions logs read mlb-alert-forwarder --region=us-west2 --gen2 --limit=50"
echo ""
echo "4. If alerts don't appear, check:"
echo "   - Slack webhook secrets are valid"
echo "   - Cloud Function has Secret Manager access"
echo "   - Service account permissions are correct"
echo ""
