#!/bin/bash
# Phase 4b: Regenerate XGBoost V1 predictions
# Generated: 2026-01-17
# Purpose: Regenerate XGBoost V1 predictions for dates with deleted placeholders

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
COORDINATOR_URL="https://prediction-coordinator-756957797294.us-west2.run.app/start"
API_KEY="0B5gc7vv9oNZYjST9lhe4rY2jEG2kYdz"
BATCH_DELAY=180  # 3 minutes between batches

# Dates to regenerate (from deleted_placeholder_predictions_20260116)
DATES=(
  "2025-11-19"
  "2025-11-20"
  "2025-11-21"
  "2025-11-22"
  "2025-11-23"
  "2025-11-24"
  "2025-11-25"
  "2025-11-26"
  "2025-11-28"
  "2025-11-29"
  "2025-11-30"
  "2025-12-01"
  "2025-12-02"
  "2025-12-03"
  "2025-12-04"
  "2025-12-05"
  "2025-12-06"
  "2025-12-07"
  "2025-12-08"
  "2025-12-09"
  "2025-12-10"
  "2025-12-11"
  "2025-12-12"
  "2025-12-13"
  "2025-12-14"
  "2025-12-16"
  "2025-12-17"
  "2025-12-18"
  "2025-12-19"
  "2026-01-09"
  "2026-01-10"
)

TOTAL_DATES=${#DATES[@]}

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       PHASE 4B: XGBOOST V1 REGENERATION                        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Total dates: $TOTAL_DATES"
echo "Estimated time: ~$((TOTAL_DATES * 3)) minutes"
echo ""

# Get auth token
AUTH_TOKEN=$(gcloud auth print-identity-token)

processed=0
for date in "${DATES[@]}"; do
  processed=$((processed + 1))
  echo -e "${YELLOW}[$processed/$TOTAL_DATES] Processing $date...${NC}"

  # Trigger prediction generation for this date
  # Use min_minutes=0 for historical dates to include all players
  response=$(curl -s -w "\n%{http_code}" -X POST "$COORDINATOR_URL" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\", \"min_minutes\": 0, \"force\": true}")

  http_code=$(echo "$response" | tail -n1)
  response_body=$(echo "$response" | head -n-1)

  if [ "$http_code" = "200" ]; then
    echo -e "  ${GREEN}✓ Batch started${NC}"

    # Extract batch_id if available
    batch_id=$(echo "$response_body" | grep -o '"batch_id":"[^"]*"' | cut -d'"' -f4 || echo "")
    if [ -n "$batch_id" ]; then
      echo "  Batch ID: $batch_id"
    fi
  else
    echo -e "  ${RED}✗ Failed (HTTP $http_code)${NC}"
    echo "  Response: $response_body"
  fi

  # Wait between batches (except for the last one)
  if [ $processed -lt $TOTAL_DATES ]; then
    echo "  Waiting ${BATCH_DELAY}s before next batch..."
    sleep $BATCH_DELAY
  fi
  echo ""
done

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              REGENERATION COMPLETE                             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Validate XGBoost V1 predictions:"
echo "     bq query --nouse_legacy_sql \\"
echo "       \"SELECT COUNT(*) as total, \\"
echo "        COUNTIF(current_points_line = 20.0) as placeholders, \\"
echo "        COUNT(DISTINCT game_date) as dates \\"
echo "        FROM \\\`nba-props-platform.nba_predictions.player_prop_predictions\\\` \\"
echo "        WHERE system_id = 'xgboost_v1' \\"
echo "        AND game_date BETWEEN '2025-11-19' AND '2026-01-10'\""
echo ""
echo "  2. Proceed to Phase 5 (monitoring setup)"
echo ""
