#!/bin/bash
# ============================================================================
# FILE: scripts/delete_espn_phantom_game.sh
# ============================================================================
# Delete the ESPN phantom game (HOU @ PHI on 2025-01-15) that never existed
# This game was incorrectly scraped by ESPN scraper
#
# CRITICAL: Review the verification query before executing deletion!
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  DELETE ESPN PHANTOM GAME${NC}"
echo -e "${YELLOW}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${RED}WARNING: This will permanently delete data from BigQuery!${NC}"
echo ""
echo "Game to delete:"
echo "  Date:     2025-01-15"
echo "  Game ID:  20250115_HOU_PHI"
echo "  Reason:   This game never existed (phantom game)"
echo "  Reality:  HOU played @ DEN, not @ PHI on this date"
echo ""

# Step 1: Verify what will be deleted
echo -e "${GREEN}[1/3] VERIFICATION - Showing data that will be deleted:${NC}"
echo ""

bq query --use_legacy_sql=false "
SELECT
  game_date,
  game_id,
  CONCAT(away_team_abbr, ' @ ', home_team_abbr) as matchup,
  COUNT(*) as player_records,
  STRING_AGG(DISTINCT team_abbr, ', ') as teams
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
  AND game_id = '20250115_HOU_PHI'
GROUP BY game_date, game_id, away_team_abbr, home_team_abbr
"

echo ""
read -p "Does this look correct? Continue with deletion? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}Deletion cancelled by user.${NC}"
    exit 0
fi

# Step 2: Execute deletion
echo ""
echo -e "${RED}[2/3] DELETION - Removing phantom game data...${NC}"
echo ""

bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
  AND game_id = '20250115_HOU_PHI'
"

echo ""
echo -e "${GREEN}✓ Deletion complete${NC}"

# Step 3: Verify deletion
echo ""
echo -e "${GREEN}[3/3] VERIFICATION - Confirming deletion:${NC}"
echo ""

bq query --use_legacy_sql=false "
SELECT
  '=== POST-DELETION CHECK ===' as check,
  COUNT(*) as remaining_records,
  CASE 
    WHEN COUNT(*) = 0 THEN '✅ Phantom game successfully deleted'
    ELSE '🔴 ERROR: Records still exist!'
  END as status
FROM \`nba-props-platform.nba_raw.espn_boxscores\`
WHERE game_date = '2025-01-15'
  AND game_id = '20250115_HOU_PHI'
"

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  DELETION COMPLETE${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Re-run validation: ./scripts/validate-espn-recent.sh"
echo "  2. Review ESPN scraper logs to understand how phantom game was created"
echo "  3. Add validation to prevent future phantom games"
echo ""
