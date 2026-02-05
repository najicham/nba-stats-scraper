#!/bin/bash
#
# Fix Feb 4, 2026 missing NBAC data
#
# This script:
# 1. Manually triggers nbac_gamebook_pdf scraper for all 7 Feb 4 games
# 2. Waits for scraping to complete
# 3. Reprocesses Phase 3 analytics
# 4. Verifies data was created
#
# Usage: ./bin/fix_feb4_data.sh
#

set -e

echo "=========================================="
echo "Feb 4, 2026 Data Recovery Script"
echo "=========================================="
echo ""

# Configuration
SCRAPER_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape"
ANALYTICS_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/process-date-range"
TARGET_DATE="2026-02-04"

# Feb 4 games (from schedule: DEN@NYK, MIN@TOR, BOS@HOU, NOP@MIL, OKC@SAS, MEM@SAC, CLE@LAC)
GAMES=(
  "20260204/DENNYK"
  "20260204/MINTOR"
  "20260204/BOSHOU"
  "20260204/NOPMIL"
  "20260204/OKCSAS"  # FIXED: Was "OKCSA" (5 chars) - Session 124
  "20260204/MEMSAC"
  "20260204/CLELAC"
)

echo "Step 1: Validate game codes"
echo "--------------------------------------------"
# Run validation (created in Session 124)
if [ -f ./bin/validate_game_codes.sh ]; then
  for game in "${GAMES[@]}"; do
    if ! ./bin/validate_game_codes.sh "$game" > /dev/null 2>&1; then
      echo "❌ CRITICAL: Invalid game code detected: $game"
      echo "   Run: ./bin/validate_game_codes.sh \"$game\" for details"
      exit 1
    fi
  done
  echo "✅ All game codes validated"
else
  echo "⚠️  Warning: Game code validator not found, skipping validation"
fi
echo ""

echo "Step 2: Get authentication token"
TOKEN=$(gcloud auth print-identity-token)
if [ -z "$TOKEN" ]; then
  echo "❌ Failed to get authentication token"
  exit 1
fi
echo "✅ Token acquired"
echo ""

echo "Step 3: Scrape gamebook PDFs for ${#GAMES[@]} games"
echo "--------------------------------------------"
SCRAPE_SUCCESS=0
SCRAPE_FAILED=0

for game in "${GAMES[@]}"; do
  echo "Scraping: $game"

  response=$(curl -s -w "\n%{http_code}" -X POST "$SCRAPER_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"scraper\": \"nbac_gamebook_pdf\", \"game_code\": \"$game\", \"group\": \"prod\"}")

  http_code=$(echo "$response" | tail -n1)
  body=$(echo "$response" | head -n-1)

  if [ "$http_code" -eq 200 ]; then
    echo "  ✅ Success"
    ((SCRAPE_SUCCESS++))
  else
    echo "  ❌ Failed (HTTP $http_code): $body"
    ((SCRAPE_FAILED++))
  fi

  sleep 3
done

echo ""
echo "Scraping summary: $SCRAPE_SUCCESS success, $SCRAPE_FAILED failed"

if [ $SCRAPE_FAILED -gt 0 ]; then
  echo "⚠️  Warning: Some scrapes failed. Continuing anyway..."
fi

echo ""
echo "Step 4: Wait for data to be exported to BigQuery"
echo "--------------------------------------------"
echo "Waiting 60 seconds for GCS → BigQuery export..."
sleep 60
echo "✅ Wait complete"
echo ""

echo "Step 5: Verify raw data exists"
echo "--------------------------------------------"
raw_count=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = '$TARGET_DATE'" \
  2>&1 | tail -1)

echo "Raw records found: $raw_count"

if [ "$raw_count" -eq "0" ]; then
  echo "❌ CRITICAL: No raw data found after scraping!"
  echo "   Check scraper logs for errors"
  exit 1
fi

echo "✅ Raw data verified"
echo ""

echo "Step 6: Reprocess Phase 3 analytics"
echo "--------------------------------------------"
response=$(curl -s -w "\n%{http_code}" -X POST "$ANALYTICS_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"start_date\": \"$TARGET_DATE\",
    \"end_date\": \"$TARGET_DATE\",
    \"processors\": [\"PlayerGameSummaryProcessor\", \"TeamOffenseGameSummaryProcessor\", \"TeamDefenseGameSummaryProcessor\"],
    \"backfill_mode\": true
  }")

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | head -n-1)

if [ "$http_code" -eq 200 ]; then
  echo "✅ Phase 3 reprocessing triggered"
else
  echo "❌ Failed to trigger Phase 3 (HTTP $http_code): $body"
  exit 1
fi

echo ""
echo "Step 7: Wait for analytics processing"
echo "--------------------------------------------"
echo "Waiting 120 seconds for analytics to complete..."
sleep 120
echo "✅ Wait complete"
echo ""

echo "Step 8: Verify analytics data"
echo "--------------------------------------------"
analytics_count=$(bq query --use_legacy_sql=false --format=csv \
  "SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = '$TARGET_DATE'" \
  2>&1 | tail -1)

echo "Analytics records found: $analytics_count"

if [ "$analytics_count" -eq "0" ]; then
  echo "❌ WARNING: No analytics records found!"
  echo "   Check Phase 3 logs for errors"
  exit 1
fi

echo "✅ Analytics verified"
echo ""

echo "=========================================="
echo "✅ Feb 4 Data Recovery Complete!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  - Scraped: $SCRAPE_SUCCESS/$((${#GAMES[@]})) games"
echo "  - Raw records: $raw_count"
echo "  - Analytics records: $analytics_count"
echo ""
echo "Next steps:"
echo "  1. Verify prediction coverage for Feb 5 improved"
echo "  2. Investigate orchestration failure root cause"
echo "  3. Add monitoring to prevent recurrence"
echo ""
