#!/bin/bash
# Template for deduplicating a specific date in BettingPros props data
# Usage: ./deduplicate_date_template.sh YYYY-MM-DD

if [ -z "$1" ]; then
    echo "Usage: ./deduplicate_date_template.sh YYYY-MM-DD"
    echo "Example: ./deduplicate_date_template.sh 2024-11-12"
    exit 1
fi

DATE=$1

echo "=== Deduplicating $DATE ==="
echo "NOTE: This only works if streaming buffer has cleared (90+ min after last insert)"
echo ""

# Step 1: Check current state
bq query --use_legacy_sql=false "
SELECT 
  game_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT source_file_path) as unique_files
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '$DATE'
GROUP BY game_date
"

# Step 2: Create backup
bq query --use_legacy_sql=false "
CREATE OR REPLACE TABLE \`nba-props-platform.nba_raw.bettingpros_player_points_props_backup_$(date +%Y%m%d)\` AS
SELECT * FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '$DATE'
"

# Step 3: Delete duplicates (keep latest processed_at)
bq query --use_legacy_sql=false "
DELETE FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '$DATE'
  AND CONCAT(
    CAST(offer_id AS STRING), '|',
    bet_side, '|',
    bookmaker, '|',
    CAST(line_id AS STRING), '|',
    CAST(processed_at AS STRING)
  ) IN (
    SELECT CONCAT(
      CAST(offer_id AS STRING), '|',
      bet_side, '|',
      bookmaker, '|',
      CAST(line_id AS STRING), '|',
      CAST(processed_at AS STRING)
    )
    FROM (
      SELECT *,
        ROW_NUMBER() OVER (
          PARTITION BY offer_id, bet_side, bookmaker, line_id 
          ORDER BY processed_at DESC
        ) as rn
      FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
      WHERE game_date = '$DATE'
    )
    WHERE rn > 1
  )
"

# Step 4: Verify
bq query --use_legacy_sql=false "
SELECT 
  game_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT source_file_path) as unique_files
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '$DATE'
GROUP BY game_date
"

echo "✅ Deduplication complete for $DATE"
