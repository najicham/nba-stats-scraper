#!/bin/bash
# NBA Backfill Progress Monitor
# Tracks completion of Phase 3 and Phase 4 backfill across all dates
# Created: 2026-01-17
# Usage: ./bin/backfill/monitor_backfill_progress.sh [--update] [--year YYYY]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_ID="nba-props-platform"
UPDATE_MODE=false
YEAR_FILTER=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --update)
      UPDATE_MODE=true
      shift
      ;;
    --year)
      YEAR_FILTER="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [--update] [--year YYYY]"
      echo ""
      echo "Options:"
      echo "  --update    Update backfill_progress table with current status"
      echo "  --year      Filter to specific year (e.g., 2022)"
      echo "  --help      Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}NBA Backfill Progress Monitor${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to update progress table
update_progress_table() {
  echo -e "${YELLOW}Updating backfill_progress table...${NC}"

  # Update Phase 3 completion status
  bq query --use_legacy_sql=false <<EOF
-- Update Phase 3 individual processor status
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase3_pgs_complete
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase3_pgs_complete = S.phase3_pgs_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase3_pgs_complete, last_updated)
  VALUES (game_date, phase3_pgs_complete, CURRENT_TIMESTAMP());

-- Team offense
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase3_togs_complete
  FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase3_togs_complete = S.phase3_togs_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase3_togs_complete, last_updated)
  VALUES (game_date, phase3_togs_complete, CURRENT_TIMESTAMP());

-- Team defense
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase3_tdgs_complete
  FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase3_tdgs_complete = S.phase3_tdgs_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase3_tdgs_complete, last_updated)
  VALUES (game_date, phase3_tdgs_complete, CURRENT_TIMESTAMP());

-- Upcoming player context
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase3_upgc_complete
  FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase3_upgc_complete = S.phase3_upgc_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase3_upgc_complete, last_updated)
  VALUES (game_date, phase3_upgc_complete, CURRENT_TIMESTAMP());

-- Upcoming team context
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase3_utgc_complete
  FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase3_utgc_complete = S.phase3_utgc_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase3_utgc_complete, last_updated)
  VALUES (game_date, phase3_utgc_complete, CURRENT_TIMESTAMP());

-- Update Phase 3 complete flag (all 5 processors done)
UPDATE \`nba-props-platform.nba_backfill.backfill_progress\`
SET
  phase3_complete = (
    COALESCE(phase3_pgs_complete, FALSE) AND
    COALESCE(phase3_togs_complete, FALSE) AND
    COALESCE(phase3_tdgs_complete, FALSE) AND
    COALESCE(phase3_upgc_complete, FALSE) AND
    COALESCE(phase3_utgc_complete, FALSE)
  ),
  last_updated = CURRENT_TIMESTAMP()
WHERE TRUE;

-- Update Phase 4 completion status
-- Team defensive zone analytics
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase4_tdza_complete
  FROM \`nba-props-platform.nba_precompute.team_defensive_zone_analytics\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase4_tdza_complete = S.phase4_tdza_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase4_tdza_complete, last_updated)
  VALUES (game_date, phase4_tdza_complete, CURRENT_TIMESTAMP());

-- Player shot zone analytics
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase4_psza_complete
  FROM \`nba-props-platform.nba_precompute.player_shot_zone_analytics\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase4_psza_complete = S.phase4_psza_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase4_psza_complete, last_updated)
  VALUES (game_date, phase4_psza_complete, CURRENT_TIMESTAMP());

-- Player defensive context
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase4_pdc_complete
  FROM \`nba-props-platform.nba_precompute.player_defensive_context\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase4_pdc_complete = S.phase4_pdc_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase4_pdc_complete, last_updated)
  VALUES (game_date, phase4_pdc_complete, CURRENT_TIMESTAMP());

-- Player composite factors
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase4_pcf_complete
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase4_pcf_complete = S.phase4_pcf_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase4_pcf_complete, last_updated)
  VALUES (game_date, phase4_pcf_complete, CURRENT_TIMESTAMP());

-- ML feature store
MERGE \`nba-props-platform.nba_backfill.backfill_progress\` T
USING (
  SELECT DISTINCT
    game_date,
    TRUE as phase4_mlfs_complete
  FROM \`nba-props-platform.nba_precompute.ml_feature_store\`
  WHERE game_date >= '2021-11-01'
) S
ON T.game_date = S.game_date
WHEN MATCHED THEN
  UPDATE SET phase4_mlfs_complete = S.phase4_mlfs_complete, last_updated = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (game_date, phase4_mlfs_complete, last_updated)
  VALUES (game_date, phase4_mlfs_complete, CURRENT_TIMESTAMP());

-- Update Phase 4 complete flag (all 5 processors done)
UPDATE \`nba-props-platform.nba_backfill.backfill_progress\`
SET
  phase4_complete = (
    COALESCE(phase4_tdza_complete, FALSE) AND
    COALESCE(phase4_psza_complete, FALSE) AND
    COALESCE(phase4_pdc_complete, FALSE) AND
    COALESCE(phase4_pcf_complete, FALSE) AND
    COALESCE(phase4_mlfs_complete, FALSE)
  ),
  last_updated = CURRENT_TIMESTAMP()
WHERE TRUE;
EOF

  echo -e "${GREEN}✓ Progress table updated${NC}"
  echo ""
}

# Update if requested
if [ "$UPDATE_MODE" = true ]; then
  update_progress_table
fi

# Build WHERE clause for year filter
WHERE_CLAUSE="WHERE game_date >= '2021-11-01'"
if [ -n "$YEAR_FILTER" ]; then
  WHERE_CLAUSE="WHERE EXTRACT(YEAR FROM game_date) = $YEAR_FILTER"
fi

# Display overall progress summary
echo -e "${BLUE}Overall Progress Summary${NC}"
echo -e "${BLUE}========================${NC}"

bq query --use_legacy_sql=false --format=pretty <<EOF
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_dates,
  COUNTIF(phase3_complete) as phase3_done,
  COUNTIF(phase4_complete) as phase4_done,
  ROUND(100.0 * COUNTIF(phase3_complete) / COUNT(*), 1) as phase3_pct,
  ROUND(100.0 * COUNTIF(phase4_complete) / COUNT(*), 1) as phase4_pct
FROM \`nba-props-platform.nba_backfill.backfill_progress\`
$WHERE_CLAUSE
GROUP BY year
ORDER BY year;
EOF

echo ""
echo -e "${BLUE}Phase 3 Processor Status${NC}"
echo -e "${BLUE}========================${NC}"

bq query --use_legacy_sql=false --format=pretty <<EOF
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNTIF(phase3_pgs_complete) as pgs_done,
  COUNTIF(phase3_togs_complete) as togs_done,
  COUNTIF(phase3_tdgs_complete) as tdgs_done,
  COUNTIF(phase3_upgc_complete) as upgc_done,
  COUNTIF(phase3_utgc_complete) as utgc_done,
  COUNT(*) as total
FROM \`nba-props-platform.nba_backfill.backfill_progress\`
$WHERE_CLAUSE
GROUP BY year
ORDER BY year;
EOF

echo ""
echo -e "${BLUE}Phase 4 Processor Status${NC}"
echo -e "${BLUE}========================${NC}"

bq query --use_legacy_sql=false --format=pretty <<EOF
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNTIF(phase4_tdza_complete) as tdza_done,
  COUNTIF(phase4_psza_complete) as psza_done,
  COUNTIF(phase4_pdc_complete) as pdc_done,
  COUNTIF(phase4_pcf_complete) as pcf_done,
  COUNTIF(phase4_mlfs_complete) as mlfs_done,
  COUNT(*) as total
FROM \`nba-props-platform.nba_backfill.backfill_progress\`
$WHERE_CLAUSE
GROUP BY year
ORDER BY year;
EOF

echo ""
echo -e "${BLUE}Incomplete Dates (Phase 3)${NC}"
echo -e "${BLUE}===========================${NC}"

bq query --use_legacy_sql=false --format=pretty <<EOF
SELECT
  game_date,
  phase3_pgs_complete as pgs,
  phase3_togs_complete as togs,
  phase3_tdgs_complete as tdgs,
  phase3_upgc_complete as upgc,
  phase3_utgc_complete as utgc
FROM \`nba-props-platform.nba_backfill.backfill_progress\`
WHERE phase3_complete = FALSE
  AND game_date >= '2021-11-01'
ORDER BY game_date
LIMIT 20;
EOF

echo ""
echo -e "${BLUE}Incomplete Dates (Phase 4)${NC}"
echo -e "${BLUE}===========================${NC}"

bq query --use_legacy_sql=false --format=pretty <<EOF
SELECT
  game_date,
  phase4_tdza_complete as tdza,
  phase4_psza_complete as psza,
  phase4_pdc_complete as pdc,
  phase4_pcf_complete as pcf,
  phase4_mlfs_complete as mlfs
FROM \`nba-props-platform.nba_backfill.backfill_progress\`
WHERE phase4_complete = FALSE
  AND game_date >= '2021-11-01'
ORDER BY game_date
LIMIT 20;
EOF

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Monitor complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Tip: Run with --update to refresh the progress table first"
echo "Tip: Use --year 2022 to filter to a specific year"
