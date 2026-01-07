#!/bin/bash
# Deduplicate player_game_summary table
# Date: January 6, 2026
# Run after 10 AM PST when streaming buffer clears
# Expected duplicates: ~354 records across 3 dates

set -e  # Exit on error

echo "=========================================="
echo "Player Game Summary Deduplication Script"
echo "=========================================="
echo ""
echo "Start time: $(date)"
echo ""

# Step 1: Test if streaming buffer cleared
echo "Step 1: Testing if streaming buffer has cleared..."
if bq query --use_legacy_sql=false --format=none "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2021-10-20' AND 1=0
" 2>&1 | grep -q "streaming buffer"; then
    echo "❌ STREAMING BUFFER STILL ACTIVE"
    echo "Wait 30-60 minutes and try again"
    exit 1
else
    echo "✅ Streaming buffer cleared - safe to proceed"
fi

echo ""
echo "Step 2: Identifying duplicates..."

# Step 2: Create temp table with duplicates
bq query --use_legacy_sql=false --format=pretty "
CREATE OR REPLACE TABLE \`nba-props-platform.nba_analytics.tmp_duplicates_to_remove\` AS
WITH duplicates AS (
  SELECT
    game_id, game_date, player_lookup,
    COUNT(*) as dup_count
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= '2021-10-19'
  GROUP BY game_id, game_date, player_lookup
  HAVING COUNT(*) > 1
),
ranked AS (
  SELECT
    pgs.game_id, pgs.game_date, pgs.player_lookup,
    ROW_NUMBER() OVER (
      PARTITION BY pgs.game_id, pgs.game_date, pgs.player_lookup
      ORDER BY
        CASE WHEN pgs.minutes_played IS NOT NULL THEN 1 ELSE 0 END DESC,
        pgs.minutes_played DESC NULLS LAST,
        (CAST(pgs.points IS NOT NULL AS INT64) +
         CAST(pgs.assists IS NOT NULL AS INT64) +
         CAST(pgs.fg_attempts IS NOT NULL AS INT64)) DESC
    ) as row_rank
  FROM \`nba-props-platform.nba_analytics.player_game_summary\` pgs
  INNER JOIN duplicates d
    ON pgs.game_id = d.game_id
    AND pgs.game_date = d.game_date
    AND pgs.player_lookup = d.player_lookup
)
SELECT game_date, game_id, player_lookup
FROM ranked
WHERE row_rank > 1
"

# Count duplicates found
DUPLICATE_COUNT=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNT(*) as cnt
FROM \`nba-props-platform.nba_analytics.tmp_duplicates_to_remove\`
" | tail -n 1)

echo ""
echo "Found $DUPLICATE_COUNT duplicate records to remove"
echo ""

if [ "$DUPLICATE_COUNT" -eq 0 ]; then
    echo "✅ No duplicates found - nothing to clean up!"
    bq rm -f nba-props-platform:nba_analytics.tmp_duplicates_to_remove
    exit 0
fi

# Step 3: Delete duplicates
echo "Step 3: Deleting $DUPLICATE_COUNT duplicate records..."
bq query --use_legacy_sql=false --format=none "
DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\` pgs
WHERE EXISTS (
  SELECT 1
  FROM \`nba-props-platform.nba_analytics.tmp_duplicates_to_remove\` tmp
  WHERE pgs.game_date = tmp.game_date
    AND pgs.game_id = tmp.game_id
    AND pgs.player_lookup = tmp.player_lookup
)
"

echo "✅ Deleted $DUPLICATE_COUNT duplicate records"
echo ""

# Step 4: Verify cleanup
echo "Step 4: Verifying no duplicates remain..."
REMAINING_DUPLICATES=$(bq query --use_legacy_sql=false --format=csv "
SELECT COUNTIF(cnt > 1) as duplicate_groups
FROM (
  SELECT COUNT(*) as cnt
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date >= '2021-10-19'
  GROUP BY game_id, game_date, player_lookup
)
" | tail -n 1)

if [ "$REMAINING_DUPLICATES" -eq 0 ]; then
    echo "✅ SUCCESS: Zero duplicates remaining"
else
    echo "⚠️  WARNING: $REMAINING_DUPLICATES duplicate groups still exist!"
    echo "May need to wait longer for streaming buffer or run again"
fi

echo ""

# Step 5: Cleanup temp table
echo "Step 5: Cleaning up temp table..."
bq rm -f nba-props-platform:nba_analytics.tmp_duplicates_to_remove
echo "✅ Temp table removed"

echo ""
echo "=========================================="
echo "Deduplication Complete"
echo "=========================================="
echo "End time: $(date)"
echo ""
echo "Summary:"
echo "  - Duplicates removed: $DUPLICATE_COUNT"
echo "  - Duplicates remaining: $REMAINING_DUPLICATES"
echo ""
