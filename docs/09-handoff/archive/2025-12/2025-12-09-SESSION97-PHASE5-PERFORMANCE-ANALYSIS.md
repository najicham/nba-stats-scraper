# Session 97 Handoff: Phase 5 Prediction Backfill Performance Analysis

**Date:** 2025-12-09
**Focus:** Performance analysis and optimization recommendations for Phase 5 backfill
**Status:** Analysis complete, backfill running, optimizations documented
**Commit:** 82abb33 (Phase 5 schema and data loader fixes)

---

## Executive Summary

Session 97 performed deep analysis of Phase 5 prediction backfill performance. The backfill is functional but **10-20x slower than optimal** due to sequential per-player BigQuery queries. This document provides detailed bottleneck analysis and optimization recommendations for future backfills.

**Key Finding:** Each game date takes 3-7 minutes due to ~150 sequential BigQuery queries (one per player). Batch loading could reduce this to ~20-40 seconds per date.

---

## Current Backfill Status

### Phase 5 Running (as of session end)

| Metric | Value |
|--------|-------|
| Background ID | `05d87c` |
| Log File | `/tmp/phase5_backfill_fixed.log` |
| Date Range | Nov 15 - Dec 31, 2021 |
| Total Game Dates | 45 |
| Progress | ~11/45 (24%) |
| Predictions Stored | ~6,900 in BigQuery |
| ETA | ~3-4 hours remaining |

### Observed Timing Data (from actual run)

| Game Date | Players | Duration | Sec/Player | Predictions | Notes |
|-----------|---------|----------|------------|-------------|-------|
| Nov 15 | ~150 | 376s | 2.5s | 241 | Normal |
| Nov 16 | 0 | 7s | - | 0 | No games |
| Nov 17 | ~150 | 363s | 2.4s | 232 | Normal |
| Nov 18 | ~90 | 219s | 2.4s | 141 | Fewer games |
| Nov 19 | ~190 | 1287s | 6.8s | 190 | **4x SLOWER** |
| Nov 20 | ~130 | 325s | 2.5s | 203 | Normal |
| Nov 21 | ~70 | 173s | 2.5s | 110 | Sunday slate |
| Nov 22 | ~150 | 358s | 2.4s | 225 | Normal |
| Nov 23 | 0 | 9s | - | 0 | No games |
| Nov 24 | ~180 | 446s | 2.5s | 276 | Holiday |

**Average:** ~2.5s per player, ~5-6 minutes per game date

---

## Code Architecture Analysis

### File Locations

| Component | File | Lines of Interest |
|-----------|------|-------------------|
| Backfill orchestrator | `backfill_jobs/prediction/player_prop_predictions_backfill.py` | 436-458 (player loop) |
| Data loader | `predictions/worker/data_loaders.py` | 163-286 (historical games query) |
| Features loader | `predictions/worker/data_loaders.py` | 51-157 (features query) |
| Prediction systems | `predictions/worker/prediction_systems/*.py` | Various |

### Execution Flow Per Game Date

```
run_predictions_for_date(game_date)                    # ~5-6 min total
├── check_phase4_dependencies(game_date)               # ~1s (3 BQ queries)
├── get_players_for_date(game_date)                    # ~1s (1 BQ query)
└── for player in players:                             # ~150 iterations
    └── generate_predictions_for_player()              # ~2.5s each
        ├── load_features()                            # ~100ms (BQ query)
        ├── load_historical_games()                    # ~1.5s (BQ query) ← PRIMARY BOTTLENECK
        ├── MovingAverageBaseline.predict()            # ~10ms
        ├── ZoneMatchupV1.predict()                    # ~10ms
        ├── SimilarityBalancedV1.predict()             # ~50ms
        ├── XGBoostV1.predict()                        # ~20ms
        └── EnsembleV1.predict()                       # ~30ms
```

### Bottleneck Analysis

#### Primary Bottleneck: Sequential `load_historical_games()` Queries

**Location:** `predictions/worker/data_loaders.py:163-286`

**Current behavior:**
```python
def load_historical_games(self, player_lookup, game_date, lookback_days=90, max_games=30):
    query = """
    WITH recent_games AS (
        SELECT game_date, opponent_team_abbr, points, minutes_played
        FROM player_game_summary
        WHERE player_lookup = @player_lookup          # ONE player at a time
          AND game_date < @game_date
          AND game_date >= DATE_SUB(@game_date, INTERVAL @lookback_days DAY)
        ...
    )
    """
    # Executes ONE query per player
```

**Problem:**
- 150 players × 1 BQ query each = 150 queries per date
- Each query has ~1-1.5s latency (network + BQ overhead)
- Total: 150 × 1.5s = ~225s just for historical games loading

#### Secondary Bottleneck: Sequential `load_features()` Queries

**Location:** `predictions/worker/data_loaders.py:51-157`

Same pattern - one query per player for features. Less severe (~100ms each) but still adds ~15s per date.

---

## Optimization Recommendations

### Option 1: Batch Data Loading (RECOMMENDED)

**Estimated Speedup:** 10-15x
**Implementation Effort:** Medium (4-6 hours)

**Approach:** Replace 150 individual queries with 2 batch queries per date.

#### Batch Historical Games Query

```python
def load_historical_games_batch(self, player_lookups: List[str], game_date: date):
    """Load historical games for ALL players in ONE query"""

    query = """
    WITH recent_games AS (
        SELECT
            player_lookup,
            game_date,
            opponent_team_abbr,
            points,
            minutes_played,
            LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as next_game
        FROM `{project}.nba_analytics.player_game_summary`
        WHERE player_lookup IN UNNEST(@player_lookups)     -- ALL players at once
          AND game_date < @game_date
          AND game_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
    )
    SELECT
        player_lookup,
        game_date,
        opponent_team_abbr,
        points,
        minutes_played,
        DATE_DIFF(next_game, game_date, DAY) as days_until_next
    FROM recent_games
    ORDER BY player_lookup, game_date DESC
    """.format(project=self.project_id)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    # Returns dict keyed by player_lookup
    results = {}
    for row in self.client.query(query, job_config=job_config):
        if row.player_lookup not in results:
            results[row.player_lookup] = []
        results[row.player_lookup].append({
            'game_date': row.game_date.isoformat(),
            'opponent_team_abbr': row.opponent_team_abbr,
            'points': float(row.points) if row.points else 0.0,
            ...
        })
    return results
```

#### Batch Features Query

```python
def load_features_batch(self, player_lookups: List[str], game_date: date):
    """Load features for ALL players in ONE query"""

    query = """
    SELECT
        player_lookup,
        features,
        feature_names,
        feature_quality_score,
        ...
    FROM `{project}.nba_predictions.ml_feature_store_v2`
    WHERE player_lookup IN UNNEST(@player_lookups)
      AND game_date = @game_date
      AND feature_version = @feature_version
    """.format(project=self.project_id)

    # Similar implementation...
```

#### Modified Backfill Flow

```python
def run_predictions_for_date(self, game_date):
    players = self.get_players_for_date(game_date)
    player_lookups = [p['player_lookup'] for p in players]

    # TWO batch queries instead of 300 individual queries
    all_features = self._data_loader.load_features_batch(player_lookups, game_date)
    all_historical = self._data_loader.load_historical_games_batch(player_lookups, game_date)

    for player in players:
        lookup = player['player_lookup']
        features = all_features.get(lookup)
        historical = all_historical.get(lookup, [])

        # Generate predictions using pre-loaded data
        preds = self.generate_predictions_with_data(lookup, game_date, features, historical)
```

**Expected Performance:**
- Current: 150 queries × 1.5s = 225s for historical, 150 × 0.1s = 15s for features = 240s
- Optimized: 2 queries × 3s = 6s (batch queries are larger but only 2)
- **Speedup: 40x just for data loading**
- Total per date: ~30-40s instead of 5-6 minutes

### Option 2: Parallel Data Loading with ThreadPoolExecutor

**Estimated Speedup:** 3-5x
**Implementation Effort:** Low (1-2 hours)

**Approach:** Keep individual queries but run them concurrently.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_all_player_data(self, players, game_date, max_workers=10):
    """Load data for all players in parallel"""

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for player in players:
            lookup = player['player_lookup']
            future = executor.submit(
                self._load_player_data,
                lookup, game_date
            )
            futures[future] = lookup

        for future in as_completed(futures):
            lookup = futures[future]
            try:
                results[lookup] = future.result()
            except Exception as e:
                logger.warning(f"Failed loading {lookup}: {e}")

    return results
```

**Trade-offs:**
- Simpler to implement than batch loading
- Still makes many queries (could hit BQ rate limits)
- Less efficient than batch loading

### Option 3: Combined Approach (BEST)

**Estimated Speedup:** 15-20x
**Implementation Effort:** Medium-High (6-8 hours)

1. Use batch queries for bulk data loading
2. Use ThreadPoolExecutor for prediction generation (CPU-bound)
3. Pre-fetch next date's data while current date processes

---

## Anomaly Investigation: Nov 19 (4x Slower)

The Nov 19, 2021 date took 1287s (21 min) vs typical 300-400s. Investigation needed:

### Potential Causes

1. **More games/players:** Nov 19 had 190 players vs typical 150
2. **BigQuery cold cache:** First query of day might be slower
3. **Network issues:** Temporary latency spike
4. **Complex player histories:** Some players may have more historical data

### Investigation Commands

```bash
# Check Nov 19 player count
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_lookup) as players
FROM nba_analytics.player_game_summary
WHERE game_date = '2021-11-19'"

# Check if any players had unusually long histories
grep "Loaded.*historical games" /tmp/phase5_backfill_fixed.log | \
  awk -F'Loaded | historical' '{print $2}' | sort -rn | head -20
```

---

## Areas for Further Research

### 1. BigQuery Query Optimization

**Questions to investigate:**
- Are there missing indexes on `player_lookup` or `game_date`?
- Would partitioned tables improve query performance?
- Is there BQ slot throttling affecting backfills?

**Commands to check:**
```bash
# Check table partitioning
bq show --schema --format=prettyjson nba_analytics.player_game_summary

# Check query statistics
bq show -j <job_id>  # Get job ID from BQ console
```

### 2. Prediction System Performance

The prediction systems themselves are fast (~100ms total), but could be profiled:

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()
# Run predictions
profiler.disable()
stats = pstats.Stats(profiler).sort_stats('cumulative')
stats.print_stats(20)
```

**Files to profile:**
- `predictions/worker/prediction_systems/similarity_balanced_v1.py` - Does similarity matching
- `predictions/worker/prediction_systems/ensemble_v1.py` - Combines all systems

### 3. Memory vs. Speed Trade-offs

Current design loads data per-player. Could pre-load ALL player data for a season:

```python
# One-time load at backfill start
all_historical_data = load_all_games_for_season('2021-22')  # ~500MB in memory
all_features = load_all_features_for_season('2021-22')       # ~200MB in memory

# Then per-date processing is instant lookups
for game_date in game_dates:
    for player in players:
        historical = all_historical_data[player][game_date]
        features = all_features[player][game_date]
```

**Trade-off:** Uses more memory but eliminates all BQ queries during processing.

### 4. Checkpoint Granularity

Current checkpoint saves per-date. For long dates, could checkpoint per-player:

```python
checkpoint.mark_player_complete(game_date, player_lookup)
```

### 5. Existing Batch Loading Stub

Note: `data_loaders.py:409-434` already has a `load_features_batch()` stub:

```python
def load_features_batch(self, player_game_pairs, feature_version='v1_baseline_25'):
    """
    Load features for multiple players at once

    Future optimization: Single query for multiple players

    Args:
        player_game_pairs: List of (player_lookup, game_date) tuples
    """
    # TODO: Implement batch loading if needed
    # For now, use single queries
    results = {}
    for player_lookup, game_date in player_game_pairs:
        features = self.load_features(player_lookup, game_date, feature_version)
        if features:
            results[(player_lookup, game_date)] = features
    return results
```

**This is the perfect place to implement batch optimization.**

---

## Implementation Priority

For the next session working on Phase 5 performance:

### Priority 1: Implement Batch Historical Games Loading
- File: `predictions/worker/data_loaders.py`
- Add: `load_historical_games_batch()` method
- Expected: 10x speedup on data loading

### Priority 2: Implement Batch Features Loading
- File: `predictions/worker/data_loaders.py`
- Modify: existing `load_features_batch()` stub
- Expected: 2x additional speedup

### Priority 3: Update Backfill to Use Batch Methods
- File: `backfill_jobs/prediction/player_prop_predictions_backfill.py`
- Modify: `run_predictions_for_date()` to call batch methods
- Expected: Full 10-15x speedup realized

### Priority 4: Investigate Nov 19 Anomaly
- Determine if it was a one-off or systematic issue
- Add timing instrumentation if needed

---

## Monitoring Commands

### Check Backfill Progress
```bash
# View real-time log
tail -f /tmp/phase5_backfill_fixed.log

# Summary of completed dates
grep -E "(Processing game date|Success.*predictions in)" /tmp/phase5_backfill_fixed.log | tail -30

# Check if process running
ps aux | grep "player_prop_predictions" | grep -v grep
```

### Check BigQuery Predictions
```bash
# Count by date
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2021-11-01'
GROUP BY game_date
ORDER BY game_date"

# Total count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total, COUNT(DISTINCT game_date) as days
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2021-11-01'"
```

---

## Session History

| Session | Focus |
|---------|-------|
| 94 | Reclassification complete - 0 correctable failures |
| 95 | Started Phase 5 backfill (had schema issues) |
| 96 | Fixed schema, backfill started successfully |
| **97** | Performance analysis, optimization recommendations |

---

## Next Session Recommendations

1. **Let current backfill complete** (~3-4 hours remaining as of session end)
2. **Implement batch loading optimizations** before Jan-Jun 2022 backfill
3. **Run Oct 2021 precompute backfill** if not already done
4. **Verify prediction accuracy** once backfill completes

---

## Key Files Reference

| Purpose | File |
|---------|------|
| Backfill orchestrator | `backfill_jobs/prediction/player_prop_predictions_backfill.py` |
| Data loaders (OPTIMIZE HERE) | `predictions/worker/data_loaders.py` |
| Moving average baseline | `predictions/worker/prediction_systems/moving_average_baseline.py` |
| Zone matchup system | `predictions/worker/prediction_systems/zone_matchup_v1.py` |
| Similarity system | `predictions/worker/prediction_systems/similarity_balanced_v1.py` |
| XGBoost system | `predictions/worker/prediction_systems/xgboost_v1.py` |
| Ensemble system | `predictions/worker/prediction_systems/ensemble_v1.py` |
| Season dates config | `shared/config/nba_season_dates.py` |
| Backfill checkpoint | `shared/backfill/checkpoint.py` |

---

## Contact/Resources

- **Handoff Docs:** `docs/09-handoff/`
- **Phase 5 Log:** `/tmp/phase5_backfill_fixed.log`
- **BigQuery Console:** https://console.cloud.google.com/bigquery?project=nba-props-platform
