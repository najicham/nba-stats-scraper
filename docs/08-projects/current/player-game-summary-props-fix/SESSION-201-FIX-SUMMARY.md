# Session 201: Fix player_game_summary Prop Line Join

**Date:** 2026-02-11
**Status:** ✅ COMPLETE

## Problem

`over_under_result` was NULL for ALL records in `nba_analytics.player_game_summary` (all 2,710 February records). This caused `last_10_results` in the frontend API (`tonight/all-players.json`) to show all dashes instead of O/U indicators.

## Root Cause

Silent game_id format mismatch in the JOIN between player stats and prop lines:

- `player_game_summary` uses **date-based game_ids**: `20260210_IND_NYK`
- `odds_api_player_points_props` uses **NBA official game_ids**: `0022500774`

The LEFT JOIN on `c.game_id = p.game_id` produced NULL for all prop fields because game_ids never matched.

## Solution

Changed the JOIN to use `game_date + player_lookup` instead of `game_id + player_lookup`:

1. Added `game_date` to `deduplicated_props` CTE SELECT
2. Changed WHERE clause from `game_id IN (...)` to `game_date IN (...)`
3. Changed JOIN predicate from `c.game_id = p.game_id` to `c.game_date = p.game_date`
4. Updated ROW_NUMBER() PARTITION from `game_id, player_lookup` to `game_date, player_lookup`

**Files Changed:**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` (2 locations)

## Verification

### Before Fix
```sql
SELECT over_under_result, COUNT(*) FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-02-01' GROUP BY 1;
-- Result: NULL | 2710
```

### After Fix (Feb 10 test)
```sql
SELECT
  COUNT(*) as total_records,
  COUNTIF(points_line IS NOT NULL) as records_with_props,
  COUNTIF(over_under_result IS NOT NULL) as records_with_result,
  ROUND(100.0 * COUNTIF(over_under_result IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as result_pct
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-10';
-- Result: 139 total, 66 with props (47.5%), 58 with result (41.7%)
```

### Sample Data (Correct)
```
player_lookup         | points | line  | result | margin
---------------------|--------|-------|--------|--------
victorwembanyama     | 40     | 22.5  | OVER   | 17.5
jalenbrunson         | 40     | 26.5  | OVER   | 13.5
kawhileonard         | 24     | 29.5  | UNDER  | -5.5
```

### Frontend API Impact
```sql
-- last_10_results now shows O/U instead of dashes
victorwembanyama: "O-OOOO"
jalenbrunson:     "O-UOUU"
cooperflagg:      "O-OO"
```

## Deployment

1. Committed fix: `d28701fb`
2. Pushed to main → auto-deployed via Cloud Build
3. Deployment completed: 2026-02-11 18:19 UTC
4. Tested on Feb 10: ✅ PASS

## Backfill Status

| Date Range | Status | Coverage |
|------------|--------|----------|
| Feb 1-6    | ✅ Complete | 29-33% |
| Feb 7-8    | ⚠️ Partial | 0-2% |
| Feb 9-11   | ✅ Complete | 33-42% |

**Note:** Feb 7-8 were processed BEFORE the fix was deployed (Feb 8 last processed: 2026-02-09 12:15:57). These dates have player records but NULL over_under_result. They will auto-fix on next natural Phase 3 reprocessing.

## Manual Reprocessing (if needed)

To force reprocess Feb 7-8:
```bash
for date in 2026-02-07 2026-02-08; do
  gcloud pubsub topics publish nba-phase2-raw-complete \
    --message="{
      \"output_table\": \"nba_raw.nbac_gamebook_player_stats\",
      \"game_date\": \"$date\",
      \"status\": \"success\",
      \"record_count\": 1,
      \"backfill_mode\": true
    }" \
    --project=nba-props-platform
done
```

## Key Files

- **Processor:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- **Prop Calculator:** `data_processors/analytics/player_game_summary/sources/prop_calculator.py` (unchanged, works correctly)
- **Frontend Export:** `data_processors/publishing/tonight_all_players_exporter.py:273` (queries over_under_result)

## Success Criteria

- [x] over_under_result is non-NULL for players with prop lines
- [x] points_line field is populated in player_game_summary
- [x] last_10_results in tonight/all-players.json shows O/U instead of dashes
- [x] No regressions in other player_game_summary fields

## Impact

- **Before:** 0% of records had over_under_result (all NULL)
- **After:** 30-40% of records have over_under_result (players with prop lines)
- **Expected:** Not all players have prop lines (role players, DNPs), so <100% is normal
