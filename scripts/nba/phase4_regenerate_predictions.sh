#!/bin/bash
# PHASE 4: REGENERATE PREDICTIONS
# Date: 2026-01-16
# Purpose: Regenerate predictions for deleted dates
# Run this AFTER: Phase 1 deployed, Phase 2 deleted, Phase 3 backfilled

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="nba-props-platform"
TOPIC="nba-prediction-coordinator-trigger"
BATCH_DELAY=180  # 3 minutes between batches

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         PHASE 4: PREDICTION REGENERATION                       ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# STEP 1: REGENERATE JAN 9-10, 2026 (Priority: Testing)
# ============================================================================

echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}STEP 1: Regenerate Jan 9-10, 2026 (2 dates)${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "This tests that Phase 1 code fixes work correctly."
echo "Recent dates have fresh data and are quick to regenerate."
echo ""
read -p "Continue with Jan 9-10 regeneration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted by user"
    exit 1
fi

for date in 2026-01-09 2026-01-10; do
    echo -e "${GREEN}📅 Regenerating $date...${NC}"

    gcloud pubsub topics publish $TOPIC \
        --project=$PROJECT_ID \
        --message="{\"target_date\": \"$date\", \"mode\": \"backfill\"}"

    echo "   ✅ Triggered"
    echo "   ⏳ Waiting ${BATCH_DELAY}s for completion..."
    sleep $BATCH_DELAY
done

echo ""
echo -e "${GREEN}✅ Jan 9-10 regeneration triggered${NC}"
echo ""
echo "Validate results before continuing:"
echo "  bq query --use_legacy_sql=false \\"
echo "    \"SELECT game_date, system_id, COUNT(*) as count, \\"
echo "     COUNTIF(current_points_line = 20.0) as placeholders \\"
echo "     FROM nba_predictions.player_prop_predictions \\"
echo "     WHERE game_date IN ('2026-01-09', '2026-01-10') \\"
echo "     GROUP BY game_date, system_id \\"
echo "     ORDER BY game_date, system_id\""
echo ""
read -p "Validation passed? Continue with XGBoost V1? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Stopped after Jan 9-10. Run XGBoost regeneration manually when ready."
    exit 0
fi

# ============================================================================
# STEP 2: REGENERATE XGBOOST V1 (53 dates - Nov 19, 2025 to Jan 10, 2026)
# ============================================================================

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}STEP 2: Regenerate XGBoost V1 (53 dates)${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "This will regenerate ALL XGBoost V1 predictions from Nov 19, 2025 to Jan 10, 2026."
echo "Estimated time: ~4 hours (53 dates × 3 minutes)"
echo ""
read -p "Continue with XGBoost V1 regeneration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "XGBoost V1 regeneration skipped"
    exit 0
fi

# Generate date list from backup table
echo "Fetching dates from deleted_placeholder_predictions..."
dates=$(bq query --use_legacy_sql=false --format=csv --project=$PROJECT_ID \
    "SELECT DISTINCT game_date
     FROM nba_predictions.deleted_placeholder_predictions_20260116
     WHERE system_id = 'xgboost_v1'
     ORDER BY game_date" | tail -n +2)

date_count=$(echo "$dates" | wc -l)
echo "Found $date_count dates to regenerate"
echo ""

processed=0
echo "$dates" | while read date; do
    processed=$((processed + 1))
    echo -e "${GREEN}📅 [$processed/$date_count] Regenerating XGBoost V1 for $date...${NC}"

    # Trigger regeneration for xgboost_v1 only
    gcloud pubsub topics publish $TOPIC \
        --project=$PROJECT_ID \
        --message="{\"target_date\": \"$date\", \"mode\": \"backfill\", \"systems\": [\"xgboost_v1\"]}"

    echo "   ✅ Triggered"

    # Wait between batches (except last one)
    if [ $processed -lt $date_count ]; then
        echo "   ⏳ Waiting ${BATCH_DELAY}s before next batch..."
        sleep $BATCH_DELAY
    fi
done

echo ""
echo -e "${GREEN}✅ XGBoost V1 regeneration complete${NC}"
echo ""
echo "Validate results:"
echo "  bq query --use_legacy_sql=false \\"
echo "    \"SELECT COUNT(*) as total, \\"
echo "     COUNTIF(current_points_line = 20.0) as placeholders, \\"
echo "     COUNT(DISTINCT game_date) as dates \\"
echo "     FROM nba_predictions.player_prop_predictions \\"
echo "     WHERE system_id = 'xgboost_v1' \\"
echo "     AND game_date BETWEEN '2025-11-19' AND '2026-01-10'\""
echo ""

# ============================================================================
# STEP 3: VALIDATION
# ============================================================================

echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}STEP 3: Final Validation${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Running final validation queries..."
echo ""

# Check for any remaining placeholders
echo "1. Checking for remaining placeholders..."
placeholders=$(bq query --use_legacy_sql=false --format=csv --project=$PROJECT_ID \
    "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE current_points_line = 20.0" | tail -n +2)

if [ "$placeholders" -eq 0 ]; then
    echo -e "   ${GREEN}✅ No placeholders found${NC}"
else
    echo -e "   ${RED}❌ Found $placeholders placeholders!${NC}"
fi

# Check line source distribution
echo ""
echo "2. Checking line source distribution..."
bq query --use_legacy_sql=false --project=$PROJECT_ID \
    "SELECT
        line_source,
        COUNT(*) as count,
        ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
     FROM nba_predictions.player_prop_predictions
     WHERE game_date >= '2025-11-19'
     GROUP BY line_source
     ORDER BY count DESC"

# Check system coverage
echo ""
echo "3. Checking system coverage..."
bq query --use_legacy_sql=false --project=$PROJECT_ID \
    "SELECT
        system_id,
        COUNT(*) as predictions,
        COUNT(DISTINCT game_date) as dates,
        COUNTIF(current_points_line != 20.0) as valid_lines
     FROM nba_predictions.player_prop_predictions
     WHERE game_date BETWEEN '2025-11-19' AND '2026-01-15'
     GROUP BY system_id
     ORDER BY system_id"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            PHASE 4 REGENERATION COMPLETE                       ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Review validation results above"
echo "  2. Check prediction_accuracy table for grading results"
echo "  3. Verify win rates are in 50-65% range"
echo "  4. Proceed to Phase 5 (monitoring setup)"
echo ""
