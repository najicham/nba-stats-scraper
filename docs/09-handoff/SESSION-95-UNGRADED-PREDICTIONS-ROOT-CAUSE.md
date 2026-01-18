# Session 95: Ungraded Predictions Root Cause Analysis

**Date:** 2026-01-18
**Issue:** 2,060+ ungraded predictions for Jan 15, and no grading for Jan 16-17
**Status:** 🔴 **ROOT CAUSE IDENTIFIED** - Schema mismatch

---

## Executive Summary

Grading is failing for recent dates (Jan 15-17) due to a **game_id format mismatch** between the predictions table and the analytics table. This prevents the grading pipeline from joining predictions with actual game results.

### Impact
- **Jan 15**: 2,193 predictions created, only 133 graded (6% graded)
- **Jan 16**: 1,328 predictions created, 0 graded
- **Jan 17**: 313 predictions created, 0 graded
- **Total ungraded**: ~3,500 predictions

---

## Root Cause: Game ID Format Mismatch

### Predictions Table Format
**Table:** `nba_predictions.player_prop_predictions`
**Game ID Format:** NBA official game IDs

```
game_id: 0022500578
game_id: 0022500580
game_id: 0022500585
```

### Analytics Table Format
**Table:** `nba_analytics.player_game_summary`
**Game ID Format:** Date_Team_Team

```
game_id: 20260115_ATL_POR
game_id: 20260115_BOS_MIA
game_id: 20260115_CHA_LAL
```

### Why This Breaks Grading

The grading pipeline joins predictions with actuals using `game_id`:

```sql
FROM predictions p
LEFT JOIN player_game_summary a
  ON p.game_id = a.game_id  -- ❌ These never match!
```

Since `0022500578 ≠ 20260115_ATL_POR`, the join fails and predictions can't be graded.

---

## Investigation Timeline

### 1. Initial Discovery
- Handoff mentioned "175 ungraded predictions from yesterday"
- Found 2,193 predictions for Jan 15, but only 133 graded

### 2. Boxscore Check
- Confirmed boxscores exist: 9 games, 215 player records for Jan 15
- Boxscores available for Jan 16: 6 games, 238 player records

### 3. Grading Trigger Attempts
Triggered grading manually via Pub/Sub:
```bash
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-01-15","run_aggregation":true}'
```

Result: Function ran but grading still incomplete

### 4. Log Analysis
Found error in Cloud Function logs:
```
"Grading failed for 2026-01-17: {
  'status': 'auto_heal_pending',
  'predictions_found': 313,
  'actuals_found': 0,  ❌
  'graded': 0,
  'message': 'Phase 3 analytics triggered, grading should retry later'
}"
```

### 5. Game ID Discovery
Query revealed the mismatch:
```sql
-- 9 games with predictions
SELECT DISTINCT game_id FROM player_prop_predictions WHERE game_date = '2026-01-15'
-- Returns: 0022500578, 0022500580, 0022500585, etc.

-- 9 games with boxscores
SELECT DISTINCT game_id FROM player_game_summary WHERE game_date = '2026-01-15'
-- Returns: 20260115_ATL_POR, 20260115_BOS_MIA, etc.
```

**None of the game_ids matched** → Grading joins fail → Predictions ungraded

---

## Why 133 Predictions Were Graded

The 133 graded predictions likely came from:
1. An older actuals source with matching game_id format
2. A previous grading run before schema migration
3. Manual grading with game_id mapping

Evidence:
```sql
SELECT game_id, actual_points FROM prediction_accuracy WHERE game_date = '2026-01-15' LIMIT 1
-- game_id: 0022500578, actual_points: 9 ✅ (has actuals)
```

The graded predictions DO have actual_points, confirming they found actuals somewhere.

---

## Solution Options

### Option A: Add Game ID Mapping Table (Recommended)
Create a lookup table to map between formats:

```sql
CREATE TABLE nba_raw.game_id_mapping (
  nba_official_id STRING,    -- 0022500578
  analytics_id STRING,        -- 20260115_ATL_POR
  game_date DATE
)
```

Update grading pipeline:
```sql
FROM predictions p
JOIN game_id_mapping m ON p.game_id = m.nba_official_id
LEFT JOIN player_game_summary a ON m.analytics_id = a.game_id
```

**Pros:**
- Non-breaking change
- Supports both formats
- Can backfill mapping for historical data

**Cons:**
- Requires maintaining mapping table
- Additional join in grading queries

### Option B: Standardize game_id in Analytics Table
Migrate `player_game_summary` to use NBA official game_ids:

```sql
-- Add new column
ALTER TABLE player_game_summary ADD COLUMN nba_game_id STRING

-- Populate from raw source with NBA IDs
UPDATE player_game_summary ...

-- Switch grading to use new column
```

**Pros:**
- Cleaner long-term solution
- Single source of truth for game_ids

**Cons:**
- Breaking change for existing queries
- Requires Phase 3 pipeline updates
- Backfill required for historical data

### Option C: Add game_id Conversion in Grading Function
Update the grading processor to convert between formats:

```python
def convert_game_id(nba_id, game_date):
    # Parse NBA ID and construct analytics ID
    # Example: 0022500578 + team lookup → 20260115_ATL_POR
    return analytics_id
```

**Pros:**
- Isolated to grading pipeline
- No schema changes

**Cons:**
- Requires team abbreviation lookup
- Complex conversion logic
- Fragile if format changes

---

## Immediate Next Steps

1. **Choose solution** (recommend Option A: mapping table)
2. **Backfill game_id mapping** for Jan 15-17
3. **Update grading pipeline** to use mapping
4. **Re-run grading** for Jan 15, 16, 17
5. **Validate** all predictions graded successfully
6. **Monitor** for future game_id mismatches

---

## Related Issues

### Session 94: Accuracy Table Duplicates
- Separate issue with 190k duplicate rows
- Not related to game_id mismatch
- Being handled in Session 94

### Phase 3 Auto-Heal
- Grading function detected missing actuals
- Triggered Phase 3 analytics (didn't help due to game_id mismatch)
- Auto-heal working as designed, but can't solve format mismatch

---

## Data Quality Impact

### Grading Coverage (Jan 15)
- **Predictions**: 2,193 (100%)
- **Graded**: 133 (6%)
- **Ungraded**: 2,060 (94%) ❌

### System Performance Metrics
- **Affected Systems**: All 6 prediction systems
- **Affected Dates**: Jan 15, 16, 17 (possibly more)
- **Accuracy Metrics**: Unreliable for recent dates

---

## Key Files

**Grading Pipeline:**
- `orchestration/cloud_functions/grading/main.py`
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

**Data Tables:**
- `nba_predictions.player_prop_predictions` (predictions with NBA IDs)
- `nba_analytics.player_game_summary` (actuals with analytics IDs)
- `nba_predictions.prediction_accuracy` (grading results)

---

## Recommendations

1. **Immediate:** Create game_id mapping table and backfill Jan 15-17
2. **Short-term:** Update grading pipeline to use mapping
3. **Long-term:** Standardize game_id format across all tables
4. **Monitoring:** Add alert for grading failures due to ID mismatch

---

**Document Version:** 1.0
**Created:** 2026-01-18
**Session:** 95
**Status:** 🔴 ROOT CAUSE IDENTIFIED - Awaiting fix
