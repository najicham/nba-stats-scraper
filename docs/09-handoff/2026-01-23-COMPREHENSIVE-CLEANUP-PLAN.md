# Comprehensive Historical Data Cleanup Plan

**Date:** 2026-01-23
**Status:** Ready for Execution
**Estimated Impact:** ~100K predictions improved

---

## Overview

This plan fixes the ESTIMATED_AVG line source issue comprehensively:

1. **Code Changes**: Fix how future predictions populate line columns
2. **Data Migration**: Clean up existing data to match new schema semantics
3. **Conversion**: Convert fixable predictions to use real BettingPros lines

---

## Current State Analysis

### Column Semantics (Before)

| Column | ACTUAL_PROP | ESTIMATED_AVG |
|--------|-------------|---------------|
| `current_points_line` | Real Vegas line | **Estimated L5 avg (WRONG!)** |
| `estimated_line_value` | NULL | L5 average |
| `line_source` | 'ACTUAL_PROP' | 'ESTIMATED_AVG' |
| `has_prop_line` | TRUE | TRUE (should be FALSE!) |

### Column Semantics (After)

| Column | ACTUAL_PROP | NO_PROP_LINE |
|--------|-------------|--------------|
| `current_points_line` | Real Vegas line | **NULL** |
| `estimated_line_value` | L5 average | L5 average |
| `line_source` | 'ACTUAL_PROP' | 'NO_PROP_LINE' |
| `has_prop_line` | TRUE | FALSE |

### Record Counts (2025-26 Season)

| line_source | Count | Action |
|-------------|-------|--------|
| ACTUAL_PROP | 32,129 | Backfill `estimated_line_value` |
| ESTIMATED_AVG | 58,329 | Migrate to NO_PROP_LINE, NULL out `current_points_line` |
| VEGAS_BACKFILL | 5,999 | Leave as-is |
| NO_VEGAS_DATA | 3,017 | Leave as-is |

---

## Execution Plan

### Phase 1: Code Changes (Deploy First)

#### 1.1 Update player_loader.py

Change line 392 to ALWAYS populate `estimated_line_value`:

**Before:**
```python
'estimated_line_value': line_info['base_line'] if line_info['line_source'] == 'ESTIMATED_AVG' else None,
```

**After:**
```python
# v3.10: Always populate estimated_line_value for reference (even when we have real lines)
'estimated_line_value': self._get_player_baseline(player_lookup) if line_info['line_source'] != 'NEEDS_BOOTSTRAP' else None,
```

#### 1.2 Add helper method to player_loader.py

```python
def _get_player_baseline(self, player_lookup: str) -> Optional[float]:
    """Get player's L5 average as baseline reference."""
    query = """
    SELECT points_avg_last_5
    FROM `{project}.nba_analytics.upcoming_player_game_context`
    WHERE player_lookup = @player_lookup
    ORDER BY game_date DESC
    LIMIT 1
    """.format(project=self.project_id)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
        ]
    )

    try:
        results = self.client.query(query, job_config=job_config).result(timeout=30)
        row = next(results, None)
        if row and row.points_avg_last_5:
            return round(float(row.points_avg_last_5) * 2) / 2.0  # Round to 0.5
        return None
    except Exception:
        return None
```

**Note:** This adds a query per player. For efficiency, could batch this in the player loading phase.

#### 1.3 Alternative: Use existing base_line for all cases

Actually, looking at the code, `line_info['base_line']` already contains the line value (either real or estimated). We can simplify:

```python
# In _get_betting_lines(), after getting the line:
# Store the player's baseline (L5 avg) regardless of line source
player_baseline = self._estimate_betting_line_with_method(player_lookup)[0]

# Then in _create_request_for_player():
'estimated_line_value': player_baseline,  # Always populated
```

### Phase 2: Data Migration (Run After Code Deployed)

#### 2.1 Convert ESTIMATED_AVG → NO_PROP_LINE

```sql
-- Step 1: Update line semantics for ESTIMATED_AVG records
-- Move the fake line to estimated_line_value (if not already there)
-- Set current_points_line to NULL
-- Change line_source to NO_PROP_LINE
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions`
SET
  -- Preserve the estimated value if not already set
  estimated_line_value = COALESCE(estimated_line_value, current_points_line),
  -- Clear the current_points_line (it's not a real line)
  current_points_line = NULL,
  -- Clear line_margin (can't calculate without real line)
  line_margin = NULL,
  -- Update line source to be accurate
  line_source = 'NO_PROP_LINE',
  -- Fix has_prop_line
  has_prop_line = FALSE,
  -- Update recommendation to NO_LINE
  recommendation = 'NO_LINE',
  -- Track the update
  updated_at = CURRENT_TIMESTAMP()
WHERE line_source = 'ESTIMATED_AVG'
  AND is_active = TRUE
  AND game_date >= '2021-10-01';
```

**Expected Impact:** ~105K records updated

#### 2.2 Backfill estimated_line_value for ACTUAL_PROP

```sql
-- Step 2: Populate estimated_line_value for ACTUAL_PROP records
-- This gives us the player's baseline for reference
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  estimated_line_value = ROUND(c.points_avg_last_5 * 2) / 2.0,
  updated_at = CURRENT_TIMESTAMP()
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` c
WHERE p.player_lookup = c.player_lookup
  AND p.game_date = c.game_date
  AND p.line_source = 'ACTUAL_PROP'
  AND p.is_active = TRUE
  AND p.estimated_line_value IS NULL
  AND p.game_date >= '2021-10-01'
  AND c.points_avg_last_5 IS NOT NULL;
```

**Expected Impact:** ~32K records updated

### Phase 3: Convert Fixable Predictions

#### 3.1 Find and Convert 2025-26 ESTIMATED_AVG with BettingPros Lines

After Phase 2, the records will be NO_PROP_LINE. Now convert the ones that DO have BettingPros lines:

```sql
-- Step 3: Convert NO_PROP_LINE predictions that have BettingPros lines available
WITH best_bettingpros_lines AS (
  SELECT
    game_date,
    player_lookup,
    -- Pick best sportsbook (DraftKings > FanDuel > others)
    ARRAY_AGG(
      STRUCT(line_value, bookmaker)
      ORDER BY
        CASE LOWER(bookmaker)
          WHEN 'draftkings' THEN 1
          WHEN 'fanduel' THEN 2
          WHEN 'betmgm' THEN 3
          ELSE 4
        END
      LIMIT 1
    )[OFFSET(0)] as best
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE game_date >= '2025-10-01'
  GROUP BY 1, 2
)
UPDATE `nba-props-platform.nba_predictions.player_prop_predictions` p
SET
  current_points_line = b.best.line_value,
  line_source = 'ACTUAL_PROP',
  line_source_api = 'BETTINGPROS',
  sportsbook = UPPER(b.best.bookmaker),
  has_prop_line = TRUE,
  line_margin = ROUND(p.predicted_points - b.best.line_value, 2),
  recommendation = CASE
    WHEN p.predicted_points > b.best.line_value + 2.0 THEN 'OVER'
    WHEN p.predicted_points < b.best.line_value - 2.0 THEN 'UNDER'
    ELSE 'PASS'
  END,
  updated_at = CURRENT_TIMESTAMP()
FROM best_bettingpros_lines b
WHERE p.player_lookup = b.player_lookup
  AND p.game_date = b.game_date
  AND p.line_source = 'NO_PROP_LINE'  -- After Phase 2 migration
  AND p.is_active = TRUE
  AND p.game_date >= '2025-10-01';
```

**Expected Impact:** ~6,400 records converted to gradable predictions

---

## Verification Queries

### After Phase 2.1 (ESTIMATED_AVG → NO_PROP_LINE)

```sql
-- Verify no more ESTIMATED_AVG
SELECT line_source, COUNT(*)
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE AND game_date >= '2021-10-01'
GROUP BY 1;

-- Expected: No 'ESTIMATED_AVG' rows, new 'NO_PROP_LINE' rows
```

### After Phase 2.2 (Backfill estimated_line_value)

```sql
-- Verify estimated_line_value populated for ACTUAL_PROP
SELECT
  line_source,
  COUNTIF(estimated_line_value IS NOT NULL) as has_baseline,
  COUNTIF(estimated_line_value IS NULL) as missing_baseline
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE AND game_date >= '2021-10-01'
GROUP BY 1;

-- Expected: ACTUAL_PROP should have high has_baseline count
```

### After Phase 3 (Convert to BettingPros)

```sql
-- Verify conversions
SELECT
  line_source,
  line_source_api,
  COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE is_active = TRUE AND game_date >= '2025-10-01'
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Expected: More ACTUAL_PROP with BETTINGPROS api
```

---

## Rollback Plan

If something goes wrong, the data can be restored using:

1. **Prediction IDs are unique** - can identify affected records
2. **updated_at timestamp** - records updated in this session
3. **BigQuery time travel** - can query data as of before the update

```sql
-- Rollback example (within 7 days)
SELECT *
FROM `nba_predictions.player_prop_predictions`
FOR SYSTEM_TIME AS OF TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
WHERE game_date = '2026-01-15';
```

---

## Grading Impact

After these changes:

| line_source | Graded? | Metrics |
|-------------|---------|---------|
| ACTUAL_PROP | ✅ Yes | Win rate + MAE |
| NO_PROP_LINE | ❌ No (filtered) | Can query MAE separately |
| VEGAS_BACKFILL | ✅ Yes | Win rate + MAE |
| NO_VEGAS_DATA | ❌ No | - |

The grading filter (`line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')`) will:
- Include all ACTUAL_PROP (newly converted ones too)
- Exclude NO_PROP_LINE (formerly ESTIMATED_AVG)

---

## Execution Order

1. [x] **Review this plan** - Confirmed approach
2. [x] **Run Phase 2.1** - Convert ESTIMATED_AVG → NO_PROP_LINE (**105,438 rows**)
3. [x] **Verify Phase 2.1** - No more ESTIMATED_AVG
4. [x] **Run Phase 2.2** - Backfill estimated_line_value (**85,502 rows**)
5. [x] **Verify Phase 2.2** - 95% baseline coverage for ACTUAL_PROP
6. [x] **Run Phase 3** - Convert fixable to ACTUAL_PROP (**6,417 rows**)
7. [x] **Verify Phase 3** - Converted have OVER/UNDER/PASS recommendations
8. [x] **Code changes** - Update player_loader.py with _get_player_baseline()
9. [x] **Deploy coordinator** - Revision 00088-2rq deployed, healthy
10. [x] **Re-run grading** - Graded all dates (fixed is_active filter in grading query)
11. [x] **Verify grading** - ACTUAL_PROP: 77.9% win rate, MAE 6.75

---

## Execution Summary (Completed 2026-01-23)

| Phase | Action | Records Affected |
|-------|--------|------------------|
| 2.1 | ESTIMATED_AVG → NO_PROP_LINE | 105,438 |
| 2.2 | Backfill estimated_line_value | 85,502 |
| 3 | Convert to ACTUAL_PROP (BettingPros) | 6,417 |
| 4 | Deduplicate predictions table | 49,341 deactivated |
| 5 | Deduplicate grading table | 2,580 deleted |
| 6 | Fix grading query (add is_active filter) | Code change |

**Total:** 197,357 records improved

**Coordinator Revision:** prediction-coordinator-00088-2rq

### Additional Fixes (Session Continuation)

1. **Predictions Table Deduplication**: Found 66,816 duplicates in predictions table (mostly NO_PROP_LINE). Deactivated 49,341 older duplicates keeping only the newest prediction per unique key.

2. **Grading Table Deduplication**: Found 2,290 duplicates in prediction_accuracy table. Deleted 2,580 older duplicates.

3. **Grading Query Fix**: Added `is_active = TRUE` filter to the grading query in `prediction_accuracy_processor.py` to prevent grading deactivated predictions.

### Final Results

```
GRADING RESULTS (2025-26 Season, CatBoost V8):
- ACTUAL_PROP: 7,177 graded, 77.9% win rate, MAE 6.75

PREDICTIONS TABLE (2025-26 Season):
- ACTUAL_PROP: 26,777
- NO_PROP_LINE: 15,232
- VEGAS_BACKFILL: 5,763
- NO_VEGAS_DATA: 2,941
- Total: 50,713 active predictions
```

---

## Time Estimates

| Phase | Records | Estimated Time |
|-------|---------|----------------|
| Code changes | - | 15 min |
| Deploy | - | 5 min |
| Phase 2.1 | ~105K | 2-3 min |
| Phase 2.2 | ~32K | 1-2 min |
| Phase 3 | ~6.4K | 1 min |
| Verification | - | 5 min |

**Total:** ~30 minutes
