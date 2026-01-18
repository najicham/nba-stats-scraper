#!/bin/bash
# Complete December + January Regeneration
# XGBoost V1 confirmed working for these dates

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

COORDINATOR_URL="https://prediction-coordinator-756957797294.us-west2.run.app/start"
API_KEY="0B5gc7vv9oNZYjST9lhe4rY2jEG2kYdz"
BATCH_DELAY=180  # 3 minutes

# Remaining December + January dates (XGBoost V1 confirmed working)
DATES=(
  "2025-12-05"
  "2025-12-06"
  "2025-12-07"
  "2025-12-11"
  "2025-12-13"
  "2025-12-18"
  "2026-01-10"
)

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       DECEMBER + JANUARY REGENERATION (7 DATES)               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Dates: ${#DATES[@]} (XGBoost V1 confirmed working)"
echo "Estimated time: ~21 minutes (3 min/date)"
echo "Validation gate: ACTIVE"
echo ""

AUTH_TOKEN=$(gcloud auth print-identity-token --quiet)

processed=0
successful=0

for date in "${DATES[@]}"; do
  processed=$((processed + 1))
  echo -e "${YELLOW}[$processed/7] Processing $date...${NC}"

  response=$(curl -s -w "\n%{http_code}" -X POST "$COORDINATOR_URL" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$date\", \"min_minutes\": 0, \"force\": true}")

  http_code=$(echo "$response" | tail -n1)
  response_body=$(echo "$response" | head -n-1)

  if [ "$http_code" = "200" ] || [ "$http_code" = "202" ]; then
    echo -e "  ${GREEN}✓ Batch started (HTTP $http_code)${NC}"
    successful=$((successful + 1))
    batch_id=$(echo "$response_body" | grep -o '"batch_id":"[^"]*"' | cut -d'"' -f4 || echo "")
    if [ -n "$batch_id" ]; then
      echo "  Batch ID: $batch_id"
    fi
  else
    echo -e "  ❌ Failed (HTTP $http_code)"
    echo "  Response: $response_body"
  fi

  if [ $processed -lt 7 ]; then
    echo "  Waiting ${BATCH_DELAY}s..."
    sleep $BATCH_DELAY
  fi
  echo ""
done

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              REGENERATION COMPLETE                             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Summary: $successful/7 batches started successfully"
echo ""
echo "Next: Wait 5-10 minutes for processing, then consolidate staging tables"
echo ""
