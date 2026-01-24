#!/bin/bash
# ============================================================================
# FILE: scripts/validate-espn-recent.sh
# ============================================================================
# Quick validation for recent ESPN boxscore data
# Usage: ./scripts/validate-espn-recent.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Project config
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
QUERIES_DIR="validation/queries/raw/espn_boxscore"

echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  ESPN BOXSCORE - RECENT DATA VALIDATION${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Note: ESPN is a sparse backup source${NC}"
echo -e "${YELLOW}Low game counts are EXPECTED and NORMAL${NC}"
echo ""

# ============================================================================
# Step 1: Check what data exists
# ============================================================================
echo -e "${GREEN}[1/4] EXISTENCE CHECK - What ESPN data do we have?${NC}"
echo ""

bq query --use_legacy_sql=false --format=prettyjson < "$QUERIES_DIR/data_existence_check.sql"

read -p "Press Enter to continue to cross-validation..."
echo ""

# ============================================================================
# Step 2: Cross-validate with BDL (PRIMARY CHECK)
# ============================================================================
echo -e "${GREEN}[2/4] CROSS-VALIDATION - Does ESPN match BDL?${NC}"
echo ""
echo -e "${YELLOW}This is the MOST IMPORTANT check${NC}"
echo -e "${YELLOW}Expect: Currently 0 overlap is normal (sparse backup)${NC}"
echo ""

bq query --use_legacy_sql=false --format=prettyjson < "$QUERIES_DIR/cross_validate_with_bdl.sql"

read -p "Press Enter to continue to quality checks..."
echo ""

# ============================================================================
# Step 3: Data quality checks
# ============================================================================
echo -e "${GREEN}[3/4] QUALITY CHECKS - Any structural issues?${NC}"
echo ""

bq query --use_legacy_sql=false --format=prettyjson < "$QUERIES_DIR/data_quality_checks.sql"

read -p "Press Enter to continue to recent activity check..."
echo ""

# ============================================================================
# Step 4: Check last 7 days activity
# ============================================================================
echo -e "${GREEN}[4/4] RECENT ACTIVITY - Any data in last 7 days?${NC}"
echo ""
echo -e "${YELLOW}Note: 'No data' is NORMAL (backup only runs ad-hoc)${NC}"
echo ""

# Modified query to check last 7 days instead of yesterday
bq query --use_legacy_sql=false --format=prettyjson <<EOF
WITH recent_games AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games,
    COUNT(*) as player_records,
    STRING_AGG(
      CONCAT(away_team_abbr, '@', home_team_abbr), 
      ', '
    ) as matchups
  FROM \`$PROJECT_ID.nba_raw.espn_boxscores\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
  ORDER BY game_date DESC
)
SELECT 
  game_date,
  games,
  player_records,
  matchups,
  CASE 
    WHEN games = 0 THEN '⚪ No data (normal for backup)'
    WHEN games > 0 THEN '✅ Data collected'
  END as status
FROM recent_games

UNION ALL

SELECT
  'TOTAL' as game_date,
  CAST(SUM(games) AS INT64) as games,
  CAST(SUM(player_records) AS INT64) as player_records,
  'Last 7 days summary' as matchups,
  CASE
    WHEN SUM(games) = 0 THEN '⚪ Normal (sparse backup source)'
    WHEN SUM(games) > 0 THEN CONCAT('✅ ', CAST(SUM(games) AS STRING), ' games in last week')
  END as status
FROM recent_games;
EOF

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  VALIDATION COMPLETE${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""

# ============================================================================
# Interpretation guide
# ============================================================================
echo -e "${GREEN}📊 HOW TO INTERPRET RESULTS:${NC}"
echo ""
echo -e "${GREEN}✅ GOOD (Expected):${NC}"
echo "  • 1-10 games total (sparse backup = normal)"
echo "  • 0 overlap with BDL (currently expected)"
echo "  • High accuracy when overlap exists (>95%)"
echo "  • ~25 players per game"
echo ""
echo -e "${YELLOW}⚠️ INVESTIGATE:${NC}"
echo "  • Stats differ by 3-5 points from BDL"
echo "  • Player count <20 or >35 per game"
echo "  • Missing rebounds/assists"
echo ""
echo -e "${RED}🔴 CRITICAL (Fix immediately):${NC}"
echo "  • ESPN has data but BDL doesn't (role reversal)"
echo "  • Stats differ by >5 points from BDL"
echo "  • NULL points values"
echo "  • Wrong team count (≠2)"
echo ""
echo -e "${BLUE}💡 NEXT STEPS:${NC}"
echo "  1. If no critical issues: Data is valid ✓"
echo "  2. If ESPN-only games exist: Check why BDL missed them"
echo "  3. If stat mismatches >5pts: Investigate both sources"
echo "  4. If no recent data: NORMAL (backup runs ad-hoc)"
echo ""
