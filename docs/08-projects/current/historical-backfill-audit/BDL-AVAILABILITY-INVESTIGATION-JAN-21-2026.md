# BDL Data Availability Investigation Report
**Date:** January 21, 2026
**Status:** ⚠️ CORRECTED - Email IS Needed

---

## Executive Summary

**31 games are STILL MISSING from BDL data in our BigQuery tables.** A previous investigation incorrectly concluded the data was available - this was due to bugs in the monitoring views.

**Action Required:** Send the BDL support email at `BDL-SUPPORT-EMAIL-DRAFT.md`.

---

## Correction Notice (Jan 21, 2026 - Evening)

A previous version of this document incorrectly stated "All 31 games are now available." This was wrong due to:

1. **View Bug:** The `v_bdl_game_availability` view used `processed_at` column for NBAC timestamp, but this column is NULL for all rows
2. **Incorrect Conclusion:** The view showed `has_nbac_data = false` for all games, leading to flawed analysis
3. **Unverified API Claims:** Direct API verification was claimed but data never appeared in BigQuery

### Verification Query (Correct Data)

```sql
-- All 31 games are STILL MISSING from bdl_player_boxscores
WITH missing_games AS (
  SELECT game_id FROM UNNEST([
    '20260119_MIA_GSW', '20260118_POR_SAC', '20260118_TOR_LAL',
    '20260117_WAS_DEN', '20260117_LAL_POR', '20260116_WAS_SAC',
    '20260115_ATL_POR', '20260115_CHA_LAL', '20260115_UTA_DAL',
    -- ... all 31 games
  ]) AS game_id
),
bdl_games AS (
  SELECT DISTINCT game_id FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= '2026-01-01'
)
SELECT m.game_id,
  CASE WHEN b.game_id IS NOT NULL THEN 'IN BDL' ELSE 'STILL MISSING' END
FROM missing_games m LEFT JOIN bdl_games b ON m.game_id = b.game_id;
-- Result: ALL 31 STILL MISSING
```

### Current BDL vs NBAC Gap (Jan 15-20)

| Date | BDL Games | NBAC Games | Missing |
|------|-----------|------------|---------|
| Jan 15 | 1 | 9 | **8** |
| Jan 16 | 5 | 6 | 1 |
| Jan 17 | 7 | 9 | 2 |
| Jan 18 | 4 | 6 | 2 |
| Jan 19 | 8 | 9 | 1 |
| Jan 20 | 4 | 7 | 3 |

---

## Bugs Fixed in Monitoring Views

### 1. NBAC Timestamp Bug
**Problem:** Used `MIN(processed_at)` for NBAC first-seen timestamp, but `processed_at` is NULL for all rows.

**Fix:** Parse timestamp from `source_file_path` instead:
```sql
-- Before (broken):
MIN(processed_at) AS nbac_first_available_at

-- After (fixed):
MIN(
  PARSE_TIMESTAMP(
    '%Y%m%d_%H%M%S',
    REGEXP_EXTRACT(source_file_path, r'/(\d{8}_\d{6})\.json$')
  )
) AS nbac_first_available_at
```

### 2. SQL Syntax Errors
Multiple views had backticks instead of semicolons, preventing proper deployment.

### 3. Missing Column Alias
**Problem:** `v_bdl_availability_latency` referenced `game_id` but base view had `nba_game_id`

**Fix:** Added alias `nba_game_id AS game_id`

---

## Observability Improvements (Kept & Fixed)

The monitoring views are valuable and have been corrected:

### `nba_orchestration.v_bdl_game_availability`
Shows when each game's data first appeared in BDL vs NBAC.

**Fields:**
- `nba_game_id` - NBA-format game ID
- `game_date`, `matchup` - Game identification
- `estimated_game_end` - Start time + 2.5 hours
- `has_bdl_data`, `has_nbac_data` - Which sources have data
- `first_available_source` - BDL_FIRST, NBAC_FIRST, BDL_ONLY, NBAC_ONLY, NEITHER
- `bdl_first_available_at` - First timestamp BDL data was loaded
- `is_west_coast` - Flag for Pacific timezone venues

### `nba_orchestration.v_bdl_availability_latency`
Calculates latency from game end to data availability.

**Key Metrics:**
- `bdl_latency_minutes` - Minutes from game end to data available
- `bdl_latency_category` - FAST_0_30_MIN, NORMAL_30_60_MIN, SLOW_1_2_HOURS, etc.
- `availability_status` - OK, WARNING, CRITICAL

### `nba_orchestration.v_bdl_availability_summary`
Daily aggregated metrics for monitoring dashboards.

---

## Root Cause Analysis (Partial Credit to Original)

The original investigation correctly identified:
- **76% of missing games are West Coast** (GSW, SAC, LAC, LAL, POR)
- **Late game timing is a factor** - games ending after midnight ET

However, it incorrectly concluded this was purely a timing issue. The data is genuinely missing from BDL's API for these specific games - not just delayed. Multiple scraper runs at 1 AM, 2 AM, 4 AM, and 6 AM ET should have caught them if they were available.

---

## Recommendations

### Immediate (Required)
1. ✅ **Send BDL support email** - Draft at `BDL-SUPPORT-EMAIL-DRAFT.md`
2. ✅ **Deploy fixed views** - SQL at `schemas/bigquery/monitoring/bdl_game_availability_tracking.sql`

### Short-term
3. Add alerting based on `v_bdl_availability_latency.availability_status`
4. Create dashboard showing BDL coverage trends

### Medium-term
5. Implement real-time BDL vs NBAC comparison in scrapers
6. Add automatic retry queue for missing games (see `ERROR-TRACKING-PROPOSAL.md`)

---

## Files Modified

| File | Change |
|------|--------|
| `schemas/bigquery/monitoring/bdl_game_availability_tracking.sql` | Fixed all bugs |
| This document | Corrected conclusions |
| `2026-01-21-DATA-VALIDATION-REPORT.md` | Backfill status updated |

---

## How to Query Availability Going Forward

```sql
-- Find games missing BDL data that should have it
SELECT game_date, matchup, estimated_game_end,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), estimated_game_end, HOUR) as hours_since_end
FROM nba_orchestration.v_bdl_game_availability
WHERE has_bdl_data = FALSE
  AND estimated_game_end < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
ORDER BY game_date DESC;

-- Check BDL vs NBAC source availability
SELECT
  first_available_source,
  COUNT(*) as game_count
FROM nba_orchestration.v_bdl_game_availability
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY first_available_source;
```

---

**Investigation corrected by:** Claude Code session
**Date:** January 21, 2026 (evening)
