#!/bin/bash
# Validation script for Phase 4b XGBoost V1 Regeneration
# Run this after regenerate_xgboost_v1.sh completes

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         PHASE 4B VALIDATION                                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check 1: XGBoost V1 prediction count
echo -e "${YELLOW}1. Checking XGBoost V1 prediction count...${NC}"
result=$(bq query --nouse_legacy_sql --format=csv "
SELECT
    COUNT(*) as total_predictions,
    COUNT(DISTINCT game_date) as dates_covered,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date BETWEEN '2025-11-19' AND '2026-01-10'
" | tail -n +2)

echo "   $result"
echo ""

# Check 2: Placeholder count (MUST BE ZERO)
echo -e "${YELLOW}2. Checking for placeholders (CRITICAL: Must be 0)...${NC}"
placeholders=$(bq query --nouse_legacy_sql --format=csv "
SELECT
    COUNT(*) as placeholder_count
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date BETWEEN '2025-11-19' AND '2026-01-10'
  AND current_points_line = 20.0
" | tail -n +2)

if [ "$placeholders" = "0" ]; then
    echo -e "   ${GREEN}✓ PASS: 0 placeholders found${NC}"
else
    echo -e "   ${RED}✗ FAIL: $placeholders placeholders found!${NC}"
fi
echo ""

# Check 3: Line source distribution
echo -e "${YELLOW}3. Checking line source distribution...${NC}"
bq query --nouse_legacy_sql "
SELECT
    line_source,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date BETWEEN '2025-11-19' AND '2026-01-10'
GROUP BY line_source
ORDER BY count DESC"
echo ""

# Check 4: Date coverage
echo -e "${YELLOW}4. Checking date coverage (should be 31 dates)...${NC}"
bq query --nouse_legacy_sql "
SELECT
    game_date,
    COUNT(*) as predictions,
    COUNTIF(current_points_line = 20.0) as placeholders
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date BETWEEN '2025-11-19' AND '2026-01-10'
GROUP BY game_date
ORDER BY game_date"
echo ""

# Check 5: Overall system comparison
echo -e "${YELLOW}5. Checking all systems for completeness...${NC}"
bq query --nouse_legacy_sql "
SELECT
    system_id,
    COUNT(DISTINCT game_date) as dates_covered,
    COUNT(*) as total_predictions,
    COUNTIF(current_points_line = 20.0) as placeholders
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date BETWEEN '2025-11-19' AND '2026-01-10'
GROUP BY system_id
ORDER BY system_id"
echo ""

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              VALIDATION COMPLETE                               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Review validation results above"
echo "  2. If all checks pass, Phase 4 is COMPLETE"
echo "  3. Phase 5 monitoring views are already set up"
echo "  4. Update project documentation"
echo ""
