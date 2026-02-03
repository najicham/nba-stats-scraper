#!/bin/bash
# Verify recent BigQuery writes after deployment
#
# Usage: ./bin/monitoring/verify-bigquery-writes.sh <service-name> [lookback-minutes]
#
# Purpose: Detect silent BigQuery write failures where services complete
# successfully but write 0 records to expected tables.
#
# Real Example (Session 80): Grading service completed with 0 errors,
# published Firestore completion events, but wrote 0 records due to
# missing dataset reference.
#
# Exit codes:
#   0 - All tables have recent writes
#   1 - One or more tables missing recent writes (CRITICAL)
#   2 - Invalid usage / unknown service

set -euo pipefail

SERVICE=$1
LOOKBACK_MINUTES=${2:-60}

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "BigQuery Write Verification"
echo "Service: $SERVICE"
echo "Lookback: Last $LOOKBACK_MINUTES minutes"
echo "================================================"
echo ""

# Define expected tables per service
case "$SERVICE" in
  "nba-grading-service")
    TABLES=("nba_predictions.prediction_accuracy")
    ;;
  "nba-phase3-analytics-processors")
    TABLES=(
      "nba_analytics.player_game_summary"
      "nba_analytics.team_offense_game_summary"
      "nba_analytics.team_defense_game_summary"
      "nba_analytics.upcoming_player_game_context"
      "nba_analytics.upcoming_team_game_context"
    )
    ;;
  "nba-phase4-precompute-processors")
    TABLES=(
      "nba_predictions.ml_feature_store_v2"
      "nba_precompute.player_daily_cache"
    )
    ;;
  "prediction-worker")
    TABLES=("nba_predictions.player_prop_predictions")
    ;;
  "prediction-coordinator")
    # Coordinator doesn't write directly to BQ, it orchestrates workers
    echo "ℹ️  Coordinator service doesn't write to BigQuery directly"
    echo "   Skipping BigQuery write verification"
    exit 0
    ;;
  "nba-scrapers")
    # Too many tables to check individually, use generic check
    echo "⚠️  Scraper service writes to many tables"
    echo "   Manual verification recommended"
    exit 0
    ;;
  *)
    echo -e "${RED}❌ Unknown service: $SERVICE${NC}"
    echo ""
    echo "Supported services:"
    echo "  - nba-grading-service"
    echo "  - nba-phase3-analytics-processors"
    echo "  - nba-phase4-precompute-processors"
    echo "  - prediction-worker"
    echo "  - prediction-coordinator (skipped)"
    echo "  - nba-scrapers (skipped)"
    exit 2
    ;;
esac

ERRORS=0
WARNINGS=0

# Check each table for recent writes
for table in "${TABLES[@]}"; do
  echo "Checking $table..."

  # Determine the timestamp field to use
  case "$table" in
    *"prediction_accuracy")
      TIMESTAMP_FIELD="graded_at"
      ;;
    *"player_prop_predictions")
      TIMESTAMP_FIELD="created_at"
      ;;
    *"ml_feature_store_v2")
      TIMESTAMP_FIELD="created_at"
      ;;
    *"player_daily_cache")
      TIMESTAMP_FIELD="updated_at"
      ;;
    *)
      TIMESTAMP_FIELD="processed_at"
      ;;
  esac

  # Query for recent records
  count=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT COUNT(*) as cnt
    FROM \`$table\`
    WHERE $TIMESTAMP_FIELD >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL $LOOKBACK_MINUTES MINUTE)
  " 2>&1 | tail -1)

  # Check if query failed
  if echo "$count" | grep -q "Error\|Not found"; then
    echo -e "  ${YELLOW}⚠️  WARNING: Could not query table (may not exist or no access)${NC}"
    echo "     Error: $count"
    WARNINGS=$((WARNINGS + 1))
    continue
  fi

  # Check record count
  if [[ "$count" == "0" || "$count" == "" ]]; then
    echo -e "  ${RED}❌ CRITICAL: 0 recent writes (last $LOOKBACK_MINUTES minutes)${NC}"
    ERRORS=$((ERRORS + 1))
  else
    echo -e "  ${GREEN}✅ OK: $count recent writes${NC}"
  fi
done

echo ""
echo "================================================"
echo "Summary"
echo "================================================"

if [[ $ERRORS -gt 0 ]]; then
  echo -e "${RED}🚨 CRITICAL: $ERRORS table(s) with no recent writes detected!${NC}"
  echo ""
  echo "Service may be silently failing. Possible causes:"
  echo "  1. Missing dataset in table reference (e.g., f\"{project}.{table}\" instead of f\"{project}.{dataset}.{table}\")"
  echo "  2. Wrong dataset name (typo or project name duplicated)"
  echo "  3. Permission errors (service account lacks BigQuery write permissions)"
  echo "  4. Table doesn't exist (processor assumes table exists but it was deleted/renamed)"
  echo ""
  echo "Investigation:"
  echo "  # Check logs for BigQuery 404 errors"
  echo "  gcloud logging read 'resource.labels.service_name=\"$SERVICE\"'"
  echo "    AND severity>=ERROR"
  echo "    AND textPayload=~\"404.*Dataset\"' \\"
  echo "    --limit=20 --freshness=2h"
  echo ""
  echo "  # Check service account permissions"
  echo "  gcloud projects get-iam-policy nba-props-platform \\"
  echo "    --flatten=\"bindings[].members\" \\"
  echo "    --filter=\"bindings.members:serviceAccount:*$SERVICE*\""
  exit 1
elif [[ $WARNINGS -gt 0 ]]; then
  echo -e "${YELLOW}⚠️  WARNING: $WARNINGS table(s) could not be verified${NC}"
  echo ""
  echo "Tables may not exist yet or permissions may be missing."
  echo "This is expected for new services or optional features."
  exit 0
else
  echo -e "${GREEN}✅ All tables have recent writes - service is writing data correctly${NC}"
  exit 0
fi
