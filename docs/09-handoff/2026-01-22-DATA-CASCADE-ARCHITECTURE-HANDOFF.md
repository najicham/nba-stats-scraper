# Data Cascade Architecture Problem - Handoff Document

**Date:** January 22, 2026
**For:** New Chat Session
**Priority:** HIGH - Architectural Issue Requiring Design Work

---

## TL;DR

**Problem:** When historical data is missing (e.g., a game's boxscore), subsequent days continue processing and make predictions using incomplete rolling averages. The system doesn't detect or flag this.

**Ask:** Design and implement a solution to:
1. Detect when historical data gaps affect feature calculations
2. Track data lineage so we know what to re-run after backfills
3. Either block, warn, or flag predictions made with incomplete history

---

## Context from Today's Session

### What We Found

During a historical data audit (Jan 1-21, 2026), we discovered:

1. **4 games were missing from analytics** (player_game_summary):
   - Jan 1: BOS @ SAC, UTA @ LAC
   - Jan 17: WAS @ DEN
   - Jan 18: POR @ SAC

2. **Subsequent days (Jan 2-21) processed normally** - completeness checks passed

3. **But rolling averages were calculated with missing data:**
   - `points_avg_last_10` used 8 games instead of 10 for affected players
   - `recent_trend` calculations were biased
   - Predictions were generated with these biased features

4. **We backfilled the analytics data** - but features for Jan 2-18 are still biased

### The Gap in Current Architecture

```
Current Flow:
  Schedule → Raw Data → Analytics → Features → Predictions
                ↓
         Completeness Check: "Does TODAY have data?" ✓
                ↓
         Rolling Average: Uses whatever history exists (8/10 games) - NO WARNING
```

```
Needed Flow:
  Schedule → Raw Data → Analytics → Features → Predictions
                ↓
         Completeness Check: "Does TODAY have data?" ✓
         Historical Check: "Is lookback window complete?" ✗
                ↓
         Rolling Average: Flag as "incomplete_history" or BLOCK
```

---

## Key Files to Understand

### 1. Completeness Checker
**File:** `/home/naji/code/nba-stats-scraper/shared/utils/completeness_checker.py`

```python
# Current: Only checks TODAY's data
def check_daily_completeness_fast(self, entity_ids, target_date, ...):
    query = f"""
    SELECT DISTINCT {entity_field}
    FROM {upstream_table}
    WHERE DATE({date_field}) = @target_date  # <-- Only checks today
    """
```

**Gap:** No method to check if historical lookback window (last 60 days) is complete.

### 2. Feature Extractor (Rolling Averages)
**File:** `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/feature_extractor.py`

```python
# Lines 408-451: _batch_extract_last_10_games
query = f"""
SELECT *
FROM player_game_summary
WHERE game_date < '{game_date}'
  AND game_date >= '{lookback_date}'  # 60-day window
QUALIFY ROW_NUMBER() OVER (...) <= 10
"""
# Returns whatever exists - could be 8, 9, or 10 games
# NO tracking of how many games were actually found
```

**Gap:** Doesn't track or flag when fewer than 10 games are found.

### 3. Feature Calculator
**File:** `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/feature_calculator.py`

```python
# Lines 131-150: recent_trend calculation
if len(last_10_games) < 5:
    return 0.0  # Defaults to neutral - silent degradation
```

**Gap:** Silent fallback, no logging or flagging.

### 4. ML Feature Store Processor
**File:** `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

This orchestrates feature generation. Key method: `process()` at ~line 200.

---

## Proposed Solutions (From Analysis)

### Solution A: Defensive Pre-Flight Check (QUICK WIN)

Add validation before feature generation:

```python
def validate_historical_completeness(player_lookup, target_date, min_games=10):
    """Check if player has sufficient historical data."""
    query = f"""
    SELECT
        COUNT(DISTINCT game_date) as actual_games,
        {min_games} as expected_games
    FROM player_game_summary
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{target_date}'
      AND game_date >= DATE_SUB('{target_date}', INTERVAL 60 DAY)
    """
    result = run_query(query)
    if result.actual_games < min_games * 0.8:  # 80% threshold
        return False, f"Only {result.actual_games}/{min_games} games found"
    return True, "OK"
```

**Pros:** Simple, catches most issues
**Cons:** Per-player queries are slow at scale

### Solution B: Metadata Tracking (RECOMMENDED)

Add quality metadata to each feature record:

```python
# In ml_feature_store_v2 schema, add:
{
    "historical_completeness": {
        "games_found": 8,
        "games_expected": 10,
        "completeness_pct": 80.0,
        "missing_dates": ["2026-01-01", "2026-01-17"],
        "is_reliable": False
    }
}
```

Then filter predictions:
```python
# In prediction coordinator
if not feature_record.historical_completeness.is_reliable:
    skip_or_flag_prediction()
```

**Pros:** Full visibility, can filter unreliable predictions downstream
**Cons:** Schema changes, storage increase

### Solution C: Dependency Graph (LONG-TERM)

Track which dates contributed to each feature:

```sql
CREATE TABLE nba_precompute.feature_lineage (
    feature_id STRING,
    target_date DATE,
    player_lookup STRING,
    contributing_dates ARRAY<DATE>,  -- Dates used in rolling window
    created_at TIMESTAMP
);
```

On backfill, query for affected records:
```sql
SELECT DISTINCT target_date, player_lookup
FROM feature_lineage
WHERE '2026-01-01' IN UNNEST(contributing_dates)
-- Returns all features that used Jan 1 in their calculation
```

**Pros:** Complete solution, enables automated cascade re-runs
**Cons:** Complex, significant development effort

---

## Implementation Priorities

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | Add logging when rolling window < 10 games | 1 hour | Visibility |
| P1 | Track `games_found` in feature metadata | 4 hours | Quality tracking |
| P1 | Add `is_reliable` flag based on threshold | 2 hours | Filtering |
| P2 | Pre-flight historical check (batch) | 8 hours | Prevention |
| P3 | Full dependency graph | 2-3 days | Automation |

---

## Testing the Problem

### Reproduce the Issue

```sql
-- Find players who played on Jan 1 and see their feature quality
SELECT
    f.game_date,
    f.player_lookup,
    f.points_avg_last_10,
    (SELECT COUNT(*)
     FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
     WHERE pgs.player_lookup = f.player_lookup
       AND pgs.game_date < f.game_date
       AND pgs.game_date >= DATE_SUB(f.game_date, INTERVAL 60 DAY)
    ) as actual_historical_games
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` f
WHERE f.game_date = '2026-01-10'
  AND f.player_lookup IN (
    SELECT DISTINCT player_lookup
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '2026-01-01'
  )
LIMIT 20;
```

### Verify After Fix

After implementing metadata tracking:
```sql
SELECT
    game_date,
    COUNT(*) as total_features,
    COUNTIF(historical_completeness.is_reliable) as reliable,
    COUNTIF(NOT historical_completeness.is_reliable) as unreliable
FROM ml_feature_store_v2
WHERE game_date >= '2026-01-01'
GROUP BY game_date
ORDER BY game_date;
```

---

## Questions to Resolve

1. **What's the acceptable completeness threshold?**
   - Suggestion: 80% (8/10 games minimum)

2. **Should we BLOCK or FLAG incomplete features?**
   - Block: Safest, but may halt processing
   - Flag: Allows processing, filters downstream

3. **How far back should we re-run after a backfill?**
   - Conservative: 60 days (full lookback window)
   - Practical: 14 days (most recent impact)

4. **Performance budget for historical checking?**
   - Batch check is ~10 seconds per date
   - Is that acceptable before each processing run?

---

## Related Documentation

- `/docs/09-handoff/2026-01-22-HISTORICAL-DATA-AUDIT-REPORT.md` - Full audit findings
- `/docs/09-handoff/2026-01-22-DATA-CASCADE-PROBLEM-HANDOFF.md` - Initial analysis
- `/docs/08-projects/current/historical-backfill-audit/` - Backfill procedures

---

## Summary for New Chat

**Your mission:** Design and implement a solution so that:

1. The system KNOWS when historical data is incomplete
2. Features are FLAGGED when calculated with incomplete data
3. We can IDENTIFY what needs re-running after a backfill

Start by reviewing the files listed above, then propose an implementation approach. The P0/P1 tasks can be done quickly and provide immediate value.

---

**Handoff Author:** Claude Code (Jan 22, 2026 Session)
