# Sample Size Tracking Implementation Handoff

**Date:** 2025-12-03
**Status:** BACKFILL IN PROGRESS (9/28 dates, ~50 min remaining)

---

## Executive Summary

Successfully implemented sample size tracking columns (`l5_games_used`, `l5_sample_quality`, `l10_games_used`, `l10_sample_quality`) for `upcoming_player_game_context` processor. This enables downstream processors to know how many games were actually used in rolling averages, critical for data quality assessment.

---

## Current Backfill Status

**Process:** `PYTHONPATH=/home/naji/code/nba-stats-scraper python3 backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py --start-date 2021-10-19 --end-date 2021-11-15`

**Log:** `/tmp/upcoming_player_backfill_v2.log`

**Progress:** 9/28 dates (32%) | ETA ~50 minutes

### Monitoring Commands
```bash
# Check progress
grep -c "✅" /tmp/upcoming_player_backfill_v2.log

# Watch live
tail -f /tmp/upcoming_player_backfill_v2.log | grep -E "Processing date|✅"

# Verify BQ data
bq query --use_legacy_sql=false "
SELECT game_date, AVG(l5_games_used) as avg_l5, COUNT(*) as records
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
GROUP BY 1 ORDER BY 1"
```

---

## Code Changes Made

### 1. Sample Size Tracking (upcoming_player_game_context_processor.py)

**Location:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Lines 1907-1946:** Added sample size tracking to `_calculate_performance_metrics()`:
```python
# Track how many games were actually used
l5_games_used = len(last_5)
l10_games_used = len(last_10)

return {
    'points_avg_last_5': ...,
    'l5_games_used': l5_games_used,
    'l5_sample_quality': self._determine_sample_quality(l5_games_used, 5),
    'l10_games_used': l10_games_used,
    'l10_sample_quality': self._determine_sample_quality(l10_games_used, 10),
    ...
}
```

**Lines 1926-1946:** New `_determine_sample_quality()` method:
```python
def _determine_sample_quality(self, games_count: int, target_window: int) -> str:
    if games_count >= target_window:
        return 'excellent'
    elif games_count >= int(target_window * 0.7):
        return 'good'
    elif games_count >= int(target_window * 0.5):
        return 'limited'
    else:
        return 'insufficient'
```

### 2. BigQuery Schema Updated

Added 4 columns to `nba_analytics.upcoming_player_game_context`:
- `l5_games_used` (INT64)
- `l5_sample_quality` (STRING)
- `l10_games_used` (INT64)
- `l10_sample_quality` (STRING)

Total columns: 120 (was 116)

### 3. Hash Query Bug Fix (analytics_base.py)

**Location:** `data_processors/analytics/analytics_base.py:981-985`

Fixed doubled dataset reference when `table_name` includes dataset prefix:
```python
# Handle table_name that may already include dataset prefix
if '.' in self.table_name:
    table_ref = f"{self.project_id}.{self.table_name}"
else:
    table_ref = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
```

### 4. Documentation Updated

- `docs/05-development/guides/quality-tracking-system.md` - Added sample size tracking section
- `docs/06-reference/quality-columns-reference.md` - Added sample size columns reference

---

## Phase Consistency Analysis

### Current State of Sample Size Tracking Across Phases

| Processor | Phase | Sample Size Columns | Quality Tiers | Status |
|-----------|-------|---------------------|---------------|--------|
| `upcoming_player_game_context` | 3 | `l5_games_used`, `l10_games_used` | `l5_sample_quality`, `l10_sample_quality` | ✅ DONE |
| `player_shot_zone_analysis` | 4 | `games_in_sample_10`, `games_in_sample_20` | `sample_quality_10`, `sample_quality_20` | ✅ EXISTS |
| `team_defense_zone_analysis` | 4 | `games_in_sample` | ❌ MISSING | GAP |
| `ml_feature_store` | 4 | ❌ MISSING | ❌ MISSING | GAP |
| `player_composite_factors` | 4 | ❌ MISSING | ❌ MISSING | GAP |
| `predictions/worker` | 5 | ❌ NOT USING | ❌ NOT USING | GAP |

---

## Areas for Next Session to Study and Improve

### HIGH PRIORITY - Data Quality Flow

#### 1. Player Registry Implementation (NOT DONE)
**Location:** `upcoming_player_game_context_processor.py:1258-1261`

The `_extract_registry()` method is a TODO stub:
```python
def _extract_registry(self) -> None:
    """Extract universal player IDs from registry (optional)."""
    # TODO: Implement registry lookup from nba_reference.nba_players_registry
    pass
```

**Registry exists:** `nba_reference.nba_players_registry` has 3,908 records with `universal_player_id`, `player_lookup`, `team_abbr`, `season`.

**Impact:** All records currently have `universal_player_id = NULL`. Implementing this would:
- Enable cross-source player matching
- Provide team fallback for players without gamebook data
- Improve data linkage for predictions

**Questions to explore:**
- How is the registry populated? Is it complete for 2021 season?
- Should registry be the primary source for team mapping vs gamebook?
- What happens with traded players - does registry track team changes?

#### 2. Sample Quality Propagation to Phase 4
**Issue:** `ml_feature_store` doesn't include sample quality columns from upstream.

**Questions to explore:**
- Should `ml_feature_store` pass through `l5_sample_quality`, `l10_sample_quality`?
- Or should it aggregate them (e.g., "overall_sample_quality")?
- How would predictions use this? Weight adjustments? Confidence scoring?

#### 3. Predictions Confidence Adjustment
**Current:** `predictions/worker` uses `is_production_ready` boolean but ignores sample quality tiers.

**Opportunity:** Adjust prediction confidence based on sample quality:
```python
# Hypothetical improvement
if sample_quality == 'insufficient':
    confidence *= 0.5
elif sample_quality == 'limited':
    confidence *= 0.75
elif sample_quality == 'good':
    confidence *= 0.9
# 'excellent' = full confidence
```

### MEDIUM PRIORITY - Performance Optimization

#### 4. Completeness Checker Optimization
**Current behavior:** 10 BigQuery queries per date (5 windows × 2 queries each)

**Questions to explore:**
- Can we batch completeness queries across all windows?
- Can we cache team schedules to reduce queries?
- Profile which step is slowest: extraction, completeness check, or context calculation?

**Timing analysis needed:**
```python
# Add timing to identify bottlenecks
import time
start = time.time()
# ... operation ...
logger.info(f"Operation took {time.time() - start:.2f}s")
```

#### 5. Backfill Processor Instance Reuse
**Current:** Creates fresh `UpcomingPlayerGameContextProcessor()` for each date.

**Opportunity:** Reuse processor instance across dates:
- BQ client already handles connection pooling
- Schedule service could be reused
- Team mapper could be reused

**Location:** `backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py`

### LOW PRIORITY - Consistency Improvements

#### 6. Add `sample_quality` to `team_defense_zone_analysis`
**Current:** Has `games_in_sample` but no quality tier.

**Fix:** Add `_determine_sample_quality()` method (copy from `player_shot_zone_analysis`).

#### 7. Standardize Column Naming
**Inconsistency found:**
- Phase 3: `l5_games_used`, `l5_sample_quality`
- Phase 4: `games_in_sample_10`, `sample_quality_10`

**Questions:**
- Should naming be standardized across phases?
- If so, which convention wins?

---

## Ideas for Deep Analysis

### Understanding the Completeness System

The completeness checking is complex. Study these files:
1. `shared/utils/completeness_checker.py` - Core logic
2. `data_processors/analytics/upcoming_player_game_context_processor.py:1346` - How it's called
3. `shared/processors/patterns/quality_columns.py` - How results are stored

**Key questions:**
- Why does completeness sometimes exceed 100%?
- What happens when `expected_games = 0`?
- How does bootstrap mode affect completeness?

### Understanding Data Flow for a Single Player

Trace a single player through all phases:
```bash
# Example: Trace LeBron James through the pipeline
bq query --use_legacy_sql=false "
SELECT 'player_game_summary' as source, game_date, points
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'lebron-james' AND game_date >= '2021-10-19'
ORDER BY game_date LIMIT 5"

bq query --use_legacy_sql=false "
SELECT 'upcoming_player' as source, game_date, l5_games_used, l5_sample_quality, points_avg_last_5
FROM nba_analytics.upcoming_player_game_context
WHERE player_lookup = 'lebron-james' AND game_date >= '2021-10-19'
ORDER BY game_date LIMIT 5"
```

### Understanding Bootstrap Mode

**Location:** `upcoming_player_game_context_processor.py`

Study when and why bootstrap mode activates:
- `backfill_bootstrap_mode` - What triggers it?
- `season_boundary_detected` - How is this determined?
- What calculations are skipped in bootstrap mode?

---

## Files to Read for Context

### Core Processor Files
1. `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
2. `data_processors/analytics/analytics_base.py`
3. `shared/utils/completeness_checker.py`

### Phase 4 Comparisons
1. `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` - Good example of sample tracking
2. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - Needs sample propagation

### Phase 5 Integration
1. `predictions/worker/data_loaders.py` - What columns are queried
2. `predictions/worker/worker.py:495-514` - How completeness is used

---

## Verification After Backfill Completes

```bash
# 1. Verify all dates loaded
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as dates, COUNT(*) as records
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'"

# 2. Verify sample quality distribution
bq query --use_legacy_sql=false "
SELECT
  l5_sample_quality,
  COUNT(*) as count,
  ROUND(AVG(l5_games_used), 2) as avg_games
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
GROUP BY 1
ORDER BY 1"

# 3. Run pipeline validation
python3 bin/validate_pipeline.py 2021-10-19 2021-11-15
```

---

## Next Steps Checklist

After backfill completes:
- [ ] Verify data quality with queries above
- [ ] Run Phase 4 precompute processors for the date range
- [ ] Consider implementing player registry lookup
- [ ] Document any issues discovered

For future improvement:
- [ ] Add sample_quality to team_defense_zone_analysis
- [ ] Propagate sample columns through ml_feature_store
- [ ] Use sample quality in predictions confidence
- [ ] Profile and optimize completeness checker

---

## Session Notes

- Backfill processing ~3 min per date due to completeness checking (10 BQ queries per date)
- Sample quality transitions observed: `insufficient` → `limited` as season progresses
- No errors encountered during backfill
- Hash query bug fix confirmed working (no more doubled dataset warnings)
