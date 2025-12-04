# Processor Enhancements - December 2025

**Date:** 2025-12-03
**Processor:** `upcoming_player_game_context`
**Phase:** 3 (Analytics)

---

## Overview

This document records code enhancements made to the `upcoming_player_game_context` processor during the backfill project. These changes improve data quality and enable features that were previously stubbed out.

---

## Enhancements Made

### 1. Player Registry Integration

**Problem:** The processor had a TODO stub for registry lookup, resulting in `universal_player_id` always being NULL.

**Solution:** Implemented full registry lookup using `RegistryReader`.

**Files Changed:**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Code Locations:**
| Location | Change |
|----------|--------|
| Lines 78-79 | Added `from shared.utils.player_registry import RegistryReader` |
| Lines 115-123 | Added `RegistryReader` initialization with 5-min cache |
| Lines 1271-1304 | Implemented `_extract_registry()` method |
| Line 1647 | Removed TODO comment |

**How It Works:**
```python
# Initialization
self.registry_reader = RegistryReader(
    source_name='upcoming_player_game_context',
    cache_ttl_seconds=300
)

# During extraction phase
def _extract_registry(self) -> None:
    unique_players = list(set(p[0] for p in self.players_to_process))
    uid_map = self.registry_reader.get_universal_ids_batch(unique_players)
    self.registry = uid_map  # {player_lookup: universal_player_id}

# During context building
'universal_player_id': self.registry.get(player_lookup),
```

**Impact:**
- `universal_player_id` column now populated for players in registry
- Enables cross-source player matching
- Improves data linkage for predictions

---

### 2. Prop Streak Calculation

**Problem:** `prop_over_streak` and `prop_under_streak` were always 0 (TODO).

**Solution:** Implemented streak calculation based on historical points vs current prop line.

**Files Changed:**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Code Locations:**
| Location | Change |
|----------|--------|
| Lines 1628-1633 | Reordered to get `prop_info` before performance metrics |
| Lines 1919-1975 | Updated `_calculate_performance_metrics()` signature |
| Lines 1999-2039 | Added new `_calculate_prop_streaks()` method |

**How It Works:**
```python
def _calculate_prop_streaks(self, historical_data: pd.DataFrame,
                             current_points_line: Optional[float]) -> Tuple[int, int]:
    """
    Calculate consecutive games over/under the current prop line.

    Returns (over_streak, under_streak) - only one can be non-zero.
    """
    if current_points_line is None or historical_data.empty:
        return 0, 0

    over_streak = 0
    under_streak = 0

    for _, row in historical_data.iterrows():
        points = row.get('points')
        if points > current_points_line:
            if under_streak > 0:
                break  # Streak broken
            over_streak += 1
        elif points < current_points_line:
            if over_streak > 0:
                break  # Streak broken
            under_streak += 1
        # Exact match continues streak without incrementing

    return over_streak, under_streak
```

**Logic:**
- Iterates through games (most recent first)
- Counts consecutive over/under the current line
- Streak ends when player goes opposite direction
- Exact matches (pushes) continue streak without incrementing

**Impact:**
- `prop_over_streak` shows consecutive games over the line
- `prop_under_streak` shows consecutive games under the line
- Useful for betting trend analysis

---

### 3. Sample Size Tracking (Previous Session)

For completeness, these columns were added in the previous session:

| Column | Type | Description |
|--------|------|-------------|
| `l5_games_used` | INT64 | Actual games in L5 calculation (0-5) |
| `l5_sample_quality` | STRING | Quality tier: excellent/good/limited/insufficient |
| `l10_games_used` | INT64 | Actual games in L10 calculation (0-10) |
| `l10_sample_quality` | STRING | Quality tier |

---

## Schema Impact

**No schema changes required.** All columns already existed in BigQuery but weren't being populated:
- `universal_player_id` (STRING)
- `prop_over_streak` (INT64)
- `prop_under_streak` (INT64)

---

## Backfill Requirements

After making these changes, a backfill is required to populate the new data:

```bash
# Run backfill for date range
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2021-11-15
```

**Performance:** ~3 min/date due to completeness checking (10 BQ queries per date)

---

## Verification Queries

### Verify Registry Population
```sql
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN universal_player_id IS NOT NULL THEN 1 ELSE 0 END) as has_uid,
  ROUND(SUM(CASE WHEN universal_player_id IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as pct
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
```

### Verify Prop Streaks
```sql
SELECT
  player_lookup,
  game_date,
  current_points_line,
  prop_over_streak,
  prop_under_streak
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= '2021-11-10'
  AND current_points_line IS NOT NULL
  AND (prop_over_streak > 0 OR prop_under_streak > 0)
ORDER BY game_date, player_lookup
LIMIT 20
```

### Verify Sample Tracking
```sql
SELECT
  l5_sample_quality,
  COUNT(*) as count,
  ROUND(AVG(l5_games_used), 2) as avg_games
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date BETWEEN '2021-10-19' AND '2021-11-15'
GROUP BY 1
ORDER BY 1
```

---

## ✅ Completed Optimization: Parallel Completeness Checking

### IMPLEMENTED (December 3, 2025)

**Problem:** Sequential BQ completeness queries caused ~2.5-3 min overhead per date.

**Solution:** Run completeness checks in parallel using `ThreadPoolExecutor`.

**Processors Updated:**
1. `upcoming_player_game_context` - 5 checks → parallel (5x speedup)
2. `player_daily_cache` - 4 checks → parallel (4x speedup)

**Code Pattern:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

completeness_windows = [
    ('l5', 5, 'games'),
    ('l10', 10, 'games'),
    ('l7d', 7, 'days'),
    ('l14d', 14, 'days'),
]

def run_completeness_check(window_config):
    name, lookback, window_type = window_config
    return (name, self.completeness_checker.check_completeness_batch(...))

with ThreadPoolExecutor(max_workers=len(completeness_windows)) as executor:
    futures = {executor.submit(run_completeness_check, config): config[0]
              for config in completeness_windows}
    for future in as_completed(futures):
        name, result = future.result()
        completeness_results[name] = result
```

**Performance Impact:**
| Processor | Before | After | Speedup |
|-----------|--------|-------|---------|
| upcoming_player_game_context | ~2.5 min | ~30 sec | 5x |
| player_daily_cache | ~2 min | ~30 sec | 4x |

**Deployments:**
- Analytics processors: Deployed 2025-12-03
- Precompute processors: Deployed 2025-12-03

---

## Future Optimization Opportunities

### Combined Query Optimization (LOWER PRIORITY)

**Current:** Even with parallel execution, still running multiple BQ queries simultaneously.

**Proposed:** Single multi-window query that fetches all data once and computes completeness client-side.

**Impact:** Further reduce from ~30 sec to ~5 sec

**Status:** Not worth implementing unless backfill performance becomes critical.

### Processor Instance Reuse
Current: Creates new processor instance per date in backfill
Opportunity: Reuse BQ client, schedule service, team mapper

---

## ✅ Phase 4 Enhancement: "Process Everyone, Mark Quality" (December 4, 2025)

### Problem Discovered

During backfill of `player_composite_factors` for Nov 16-30, 2021:

| Before Fix | Result |
|------------|--------|
| Nov 18: 212 players | Only 11 processed (5%)! |
| Processing time | 663 seconds (11 minutes) |
| Root cause | 201 players SKIPPED due to `team_context=False` |

**Why `team_context=False`?**
- Early in season (Nov 18 = day 30), teams hadn't played enough games
- `upcoming_team_game_context.is_production_ready=TRUE` requires L7D AND L14D = 100%
- Most teams only had 33-80% completeness early season
- Result: Cascade pattern blocked most players

**Why so slow?**
- Each failed player called `_increment_reprocess_count()` → 2 BigQuery queries
- 201 failed players × 2 queries = 400+ queries at ~1.4s each = 559 seconds!

### Solution: "Process Everyone, Mark Quality"

Changed from **skip** to **process with quality flags** (matching Phase 3 pattern):

**Code Changes in `player_composite_factors_processor.py`:**

| Lines | Before | After |
|-------|--------|-------|
| 882-901 | `continue` (skip player) | Log info, continue processing |
| 912-934 | `continue` (skip player) | Log info, continue processing |
| 1064-1069 | N/A | Added 5 upstream readiness fields |
| 1071 | N/A | Added `own_data_incomplete` to quality issues |

**New Schema Fields Added:**
```sql
upstream_player_shot_ready BOOLEAN,    -- TRUE if player_shot_zone_analysis ready
upstream_team_defense_ready BOOLEAN,   -- TRUE if team_defense_zone_analysis ready
upstream_player_context_ready BOOLEAN, -- TRUE if upcoming_player_game_context ready
upstream_team_context_ready BOOLEAN,   -- TRUE if upcoming_team_game_context ready
all_upstreams_ready BOOLEAN,           -- TRUE if ALL upstream sources ready
```

### Results After Fix

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Players processed | 11/212 (5%) | 212/212 (100%) | 20x coverage |
| Processing time | 663 seconds | 37.8 seconds | 17x faster |
| Circuit breaker queries | 400+ | 0 | Eliminated |

### Quality Tracking for Phase 5

Phase 5 now has everything needed to make informed decisions:

| Field | Type | Use Case |
|-------|------|----------|
| `is_production_ready` | Boolean | Filter: only high-confidence predictions |
| `all_upstreams_ready` | Boolean | Quick upstream check |
| `data_completeness_pct` | Float | Weight prediction confidence |
| `upstream_*_ready` (5) | Booleans | Diagnose which source incomplete |
| `data_quality_issues` | Array | Detailed issue list |

**Example Phase 5 Usage:**
```sql
-- High confidence predictions only
SELECT * FROM player_composite_factors
WHERE is_production_ready = TRUE;

-- All players with confidence weighting
SELECT
  player_lookup,
  predicted_points,
  data_completeness_pct / 100.0 AS confidence_weight
FROM player_composite_factors;
```

### Why This Is Better Than Skipping

| Approach | Skip Players | Process Everyone |
|----------|-------------|------------------|
| Early season player | No record at all | Record with quality flags |
| Phase 5 can use? | No - missing input | Yes - can filter or weight |
| Backfill coverage | 25% of players | 100% of players |
| Decision maker | Phase 4 | Phase 5 (better separation) |

### Files Changed

- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
  - Lines 881-921: Removed skip logic, added quality logging
  - Lines 1064-1073: Added upstream readiness fields to record
- `schemas/bigquery/precompute/player_composite_factors.sql`
  - Lines 222-227: Added 5 upstream readiness columns

---

## Related Files

- Processor: `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- Backfill: `backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py`
- Registry: `shared/utils/player_registry/`
- Handoff: `docs/09-handoff/2025-12-03-PROCESSOR-IMPROVEMENTS-HANDOFF.md`
