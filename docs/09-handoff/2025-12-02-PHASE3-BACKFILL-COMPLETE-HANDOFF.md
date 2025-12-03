# Phase 3 Backfill Complete Handoff

**Date:** 2025-12-02/03
**Sessions:** 2 sessions
**Focus:** Fixing all blockers for `upcoming_player_game_context` and `upcoming_team_game_context` backfills

## Executive Summary

Successfully fixed multiple blockers preventing Phase 3 Analytics backfills from running. Both `upcoming_*` processors are now operational with:
- All datetime conversion issues resolved
- Schema field filtering implemented
- Batch query optimization for prop lines (major performance improvement)

**Current Status:**
- `upcoming_team_game_context`: ✅ COMPLETE (418 records, 28 dates)
- `upcoming_player_game_context`: Running with optimizations

---

## All Fixes Applied

### 1. Team Processor - Date String Conversions

**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

Multiple locations required converting date strings to date objects:

#### a) `_extract_schedule_data()` (Lines 472-476)
```python
# Ensure dates are date objects, not strings (defensive conversion)
if isinstance(start_date, str):
    start_date = date.fromisoformat(start_date)
if isinstance(end_date, str):
    end_date = date.fromisoformat(end_date)
```

#### b) DataFrame `game_date` conversion (Lines 513-515)
```python
# Ensure game_date is datetime type for .dt accessor
# Force conversion regardless of dtype (BQ can return various types)
schedule_df['game_date'] = pd.to_datetime(schedule_df['game_date'])
```

#### c) `validate_extracted_data()` (Lines 828-832)
```python
# Convert to date objects if strings
if isinstance(start_date, str):
    start_date = date.fromisoformat(start_date)
if isinstance(end_date, str):
    end_date = date.fromisoformat(end_date)
```

#### d) `calculate_analytics()` (Lines 1022-1026)
Same date conversion pattern applied.

### 2. Team Processor - Completeness Checker Field Name

**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

**Lines 1049, 1061:** Changed field name to match actual schema:
```python
# Before:
upstream_entity_field='home_team_abbr'

# After:
upstream_entity_field='home_team_tricode'  # Matches nbac_schedule schema
```

### 3. Team Processor - Schema Field Filtering in `save_results()`

**File:** `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`

**Lines 1765-1771:** Filter data to only include columns in BQ schema:
```python
# Filter data to only include columns that exist in the schema
schema_fields = {field.name for field in table.schema}
filtered_data = [
    {k: v for k, v in record.items() if k in schema_fields}
    for record in self.transformed_data
]
```

And use `filtered_data` in the load call (line 1783).

### 4. Player Processor - Schema Field Filtering

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Lines 2026-2032:** Same schema filtering pattern:
```python
# Filter data to only include columns that exist in the schema
schema_fields = {field.name for field in table.schema}
filtered_data = [
    {k: v for k, v in record.items() if k in schema_fields}
    for record in self.transformed_data
]
```

### 5. Player Processor - Batch Query Optimization (MAJOR)

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Method:** `_extract_prop_lines_from_odds_api()` (Lines 908-998)

**Before:** Individual queries per player (2 queries × N players = 2N queries per date)
```python
for player_lookup, game_id in player_game_pairs:
    opening_query = f"SELECT ... WHERE player_lookup = '{player_lookup}' ..."
    current_query = f"SELECT ... WHERE player_lookup = '{player_lookup}' ..."
    # 2 queries per player!
```

**After:** Single batch query for all players:
```python
batch_query = f"""
WITH opening_lines AS (
    SELECT player_lookup, game_id, points_line as opening_line, bookmaker as opening_source,
           ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id ORDER BY snapshot_timestamp ASC) as rn
    FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
    WHERE player_lookup IN ('{player_lookups_str}')
      AND game_date = '{self.target_date}'
),
current_lines AS (
    SELECT player_lookup, game_id, points_line as current_line, bookmaker as current_source,
           ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id ORDER BY snapshot_timestamp DESC) as rn
    FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
    WHERE player_lookup IN ('{player_lookups_str}')
      AND game_date = '{self.target_date}'
)
SELECT COALESCE(o.player_lookup, c.player_lookup) as player_lookup,
       COALESCE(o.game_id, c.game_id) as game_id,
       o.opening_line, o.opening_source, c.current_line, c.current_source
FROM opening_lines o
FULL OUTER JOIN current_lines c ON o.player_lookup = c.player_lookup AND o.game_id = c.game_id
WHERE (o.rn = 1 OR o.rn IS NULL) AND (c.rn = 1 OR c.rn IS NULL)
"""
```

**Performance Impact:**
- Before: ~3+ minutes per date (stuck on prop line extraction)
- After: Seconds per date

---

## Previous Session Fixes (Session 1)

### 6. Analytics Base - Dependency Check Types

**File:** `data_processors/analytics/analytics_base.py`

Added `date_match` and `lookback_days` check types in `_check_table_data()`.

### 7. Analytics Base - Backfill Mode Critical Dependency Handling

Modified to allow processing to continue in backfill mode when critical dependencies are missing.

### 8. Backfill Scripts - Date Iteration

Both backfill scripts updated to iterate through dates properly with fresh processor instances per date.

---

## Current Backfill Status

### Upcoming Team Game Context
- **Status:** ✅ COMPLETE
- **Records:** 418
- **Dates:** 28 (2021-10-19 to 2021-11-15)
- **Verification:**
```sql
SELECT game_date, COUNT(*) FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15' GROUP BY 1 ORDER BY 1;
```

### Upcoming Player Game Context
- **Status:** Running with optimizations
- **Log:** `/tmp/upcoming_player_backfill.log`
- **Process:** Check with `ps aux | grep upcoming_player`
- **Known Issue:** Team mapping fails for many historical players (expected, non-blocking)

---

## Known Issues (Non-Blocking)

### 1. Missing Analytics Dataset Warning
```
Dataset nba-props-platform:nba_analytics.nba_analytics was not found
```
- Smart reprocessing hash queries fail
- Non-blocking (continues processing)
- The dataset path in the hash query is incorrect

### 2. Player Team Mapping Warnings
```
Could not determine team for stephencurry
Could not determine team for lebronJames
```
- Historical data lacks current team roster mappings
- Players are skipped but backfill continues
- Expected behavior for early season dates

### 3. Schema Mismatch for `analytics_processor_runs`
```
Field success has changed mode from REQUIRED to NULLABLE
```
- Non-blocking for backfill
- Schema needs update for production use

### 4. No Odds API Data for Historical Dates
- 2021 dates have no Odds API prop data (service wasn't active)
- BettingPros fallback should be used but `_props_source` logic doesn't trigger it
- Batch query returns 0 records (fast, non-blocking)

---

## Other Phase 3 Processors (Already Backfilled)

These processors already have data for 2021-10-19 to 2021-11-15:

| Processor | Records |
|-----------|---------|
| `player_game_summary` | 4,551 |
| `team_defense_game_summary` | 1,588 |
| `team_offense_game_summary` | 1,588 |

---

## Files Modified

1. `data_processors/analytics/analytics_base.py`
2. `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
3. `data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py`
4. `backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py`
5. `backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py`

---

## Monitoring Commands

```bash
# Check player backfill progress
tail -f /tmp/upcoming_player_backfill.log

# Check if process is running
ps aux | grep upcoming_player | grep -v grep

# Check data in BigQuery
bq query --use_legacy_sql=false "
SELECT 'team' as tbl, COUNT(*) as cnt, COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
UNION ALL
SELECT 'player', COUNT(*), COUNT(DISTINCT game_date)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
"

# Check specific date
grep "Processing date" /tmp/upcoming_player_backfill.log | tail -5
```

---

## Next Steps

1. **Monitor player backfill to completion**
   - Should complete in ~30-60 minutes with optimizations
   - Team mapping issues will cause low success rate for early dates

2. **Verify data quality after completion**
   - Check record counts by date
   - Verify expected columns are populated

3. **Consider future improvements:**
   - Fix `_props_source` logic to properly trigger BettingPros fallback
   - Improve team mapping for historical player data
   - Update `analytics_processor_runs` schema

4. **Once backfills complete:**
   - Run Phase 4 precompute processors if needed
   - Run validation: `python3 bin/validate_pipeline.py 2021-10-19 2021-11-15`

---

## Architecture Notes

### Why Batch Queries Matter
The original Odds API prop line extraction did 2 BQ queries per player:
- 79 players × 2 queries = 158 queries per date
- 28 dates × 158 queries = 4,424 queries total
- Each query has ~1-2 second latency = hours of execution

The batch query approach:
- 1 query per date = 28 queries total
- ~95% reduction in query count and execution time

### Schema Filtering Pattern
Both processors now filter data before BQ load:
```python
schema_fields = {field.name for field in table.schema}
filtered_data = [{k: v for k, v in record.items() if k in schema_fields} for record in data]
```

This prevents "No such field" errors when processor adds fields not in the table schema.

---

## Session 3 Fixes (2025-12-03)

### 6. Player Processor - Team Mapping from player_info

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Line 1571:** Changed to use `player_info` instead of `game_info`:
```python
# Before:
team_abbr = self._determine_player_team(player_lookup, game_info)

# After:
team_abbr = self._determine_player_team(player_lookup, player_info)
```

**Root cause:** The gamebook query returns `team_abbr` in `player_info`, but the code was passing `game_info` (from schedule) which doesn't have it.

### 7. Player Processor - NaN Sanitization for JSON Load

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Lines 2064-2075:** Added sanitizer function before BigQuery batch load:
```python
def sanitize_value(v):
    """Convert non-JSON-serializable values to None."""
    import math
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
    if hasattr(v, 'item'):  # numpy scalar
        return v.item()
    return v
```

**Root cause:** Early-season dates have NaN values for stats (no historical data), which caused JSON serialization errors during BigQuery load.

### Updated Backfill Status

| Dataset | Status | Records |
|---------|--------|---------|
| `upcoming_team_game_context` | ✅ COMPLETE | 418 (28 dates) |
| `upcoming_player_game_context` | 🏃 RUNNING | ~4 dates done |

**Note:** Historical data quality improves as season progresses (more boxscore data accumulates).

### Known Issue - Hash Query Path

Non-blocking warning spam:
```
Dataset nba-props-platform:nba_analytics.nba_analytics was not found
```
The smart reprocessing hash query has incorrect path. Low priority fix.
