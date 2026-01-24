#!/bin/bash
# Test Regeneration: 3 December Dates
# Purpose: Validate XGBoost V1 + validation gate before full regeneration

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

COORDINATOR_URL="https://prediction-coordinator-756957797294.us-west2.run.app/start"
API_KEY="${COORDINATOR_API_KEY:?Error: COORDINATOR_API_KEY environment variable not set}"

# Test with 3 December dates (more likely to work than November)
DATES=(
  "2025-12-01"
  "2025-12-02"
  "2025-12-03"
)

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       TEST REGENERATION: 3 DATES                               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Testing dates: ${DATES[@]}"
echo "Delay between batches: 30 seconds (fast test)"
echo ""

AUTH_TOKEN=$(gcloud auth print-identity-token --quiet)

processed=0
for date in "${DATES[@]}"; do
  processed=$((processed + 1))
  echo -e "${YELLOW}[$processed/3] Processing $date...${NC}"

  response=$(curl -s -w "\n%{http_code}" -X POST "$COORDINATOR_URL" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\", \"min_minutes\": 0, \"force\": true}")

  http_code=$(echo "$response" | tail -n1)
  response_body=$(echo "$response" | head -n-1)

  if [ "$http_code" = "200" ] || [ "$http_code" = "202" ]; then
    echo -e "  ${GREEN}✓ Batch started (HTTP $http_code)${NC}"
    batch_id=$(echo "$response_body" | grep -o '"batch_id":"[^"]*"' | cut -d'"' -f4 || echo "")
    if [ -n "$batch_id" ]; then
      echo "  Batch ID: $batch_id"
    fi
  else
    echo -e "  ${RED}✗ Failed (HTTP $http_code)${NC}"
    echo "  Response: $response_body"
  fi

  if [ $processed -lt 3 ]; then
    echo "  Waiting 30s..."
    sleep 30
  fi
  echo ""
done

echo -e "${GREEN}Test batches triggered. Waiting 3 minutes for processing...${NC}"
sleep 180

echo ""
echo -e "${YELLOW}Checking results...${NC}"
echo ""

# Check if XGBoost V1 predictions were generated
bq query --nouse_legacy_sql "
SELECT
  game_date,
  COUNT(*) as xgboost_v1_predictions,
  COUNTIF(current_points_line = 20.0) as placeholders,
  MIN(created_at) as first_created,
  MAX(created_at) as last_created
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date IN ('2025-12-01', '2025-12-02', '2025-12-03')
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
GROUP BY game_date
ORDER BY game_date"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       TEST COMPLETE                                            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. If XGBoost V1 predictions were generated with 0 placeholders:"
echo "     → Run full regeneration: ./regenerate_xgboost_v1_missing.sh"
echo ""
echo "  2. If no XGBoost V1 predictions or placeholders found:"
echo "     → Investigate XGBoost V1 failures further"
echo "     → Check worker logs for errors"
echo ""
