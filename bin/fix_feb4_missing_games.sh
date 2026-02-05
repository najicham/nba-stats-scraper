#!/usr/bin/env bash
#
# Fix missing CLE@LAC and MEM@SAC games from Feb 4, 2026
#
# ROOT CAUSE: Phase 3 ran before these games' raw data was available
# SOLUTION: Reprocess Feb 4 to pick up the missing games
#

set -euo pipefail

echo "========================================"
echo "Fix Missing Feb 4 Games"
echo "Date: $(date)"
echo "========================================"
echo ""

echo "Problem: Phase 3 analytics missing CLE@LAC and MEM@SAC from Feb 4"
echo "  - Raw data: 7 games, 241 players"
echo "  - Analytics: 5 games, 171 players (missing 70 players)"
echo ""

# Verify raw data exists
echo "Step 1: Verify raw data exists for missing games..."
RAW_COUNT=$(bq query --project_id=nba-props-platform --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = '2026-02-04'
  AND player_status IN ('active', 'dnp', 'inactive')
  AND game_id IN ('20260204_CLE_LAC', '20260204_MEM_SAC')
" | tail -1)

if [ "$RAW_COUNT" != "69" ]; then
  echo "ERROR: Expected 69 raw records, found $RAW_COUNT"
  exit 1
fi
echo "  ✓ Found 69 raw records for missing games"
echo ""

# Verify analytics is missing these games
echo "Step 2: Verify analytics is missing these games..."
ANALYTICS_COUNT=$(bq query --project_id=nba-props-platform --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-02-04'
  AND game_id IN ('20260204_CLE_LAC', '20260204_MEM_SAC')
" | tail -1)

if [ "$ANALYTICS_COUNT" != "0" ]; then
  echo "  ! Analytics already has $ANALYTICS_COUNT records for these games"
  echo "  ! Skipping reprocessing"
  exit 0
fi
echo "  ✓ Analytics is missing these games (0 records found)"
echo ""

# Reprocess Feb 4
echo "Step 3: Reprocessing Feb 4..."
echo "  Note: This will re-MERGE all 7 games (5 existing + 2 missing)"
echo ""

cd /home/naji/code/nba-stats-scraper

PYTHONPATH=. python3 -c "
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
import sys

processor = PlayerGameSummaryProcessor({
    'start_date': '2026-02-04',
    'end_date': '2026-02-04',
    'force_reprocess': True  # Override smart skip
})

try:
    processor.run()
    print('✓ Reprocessing complete')
    sys.exit(0)
except Exception as e:
    print(f'ERROR: Reprocessing failed: {e}')
    sys.exit(1)
"

echo ""
echo "Step 4: Verify fix..."
FINAL_COUNT=$(bq query --project_id=nba-props-platform --use_legacy_sql=false --format=csv --quiet "
SELECT
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as players
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-02-04'
" | tail -1)

echo "  Analytics now has: $FINAL_COUNT"
echo "  Expected: 7 games, ~241 players"
echo ""

echo "========================================"
echo "Fix complete!"
echo "========================================"
