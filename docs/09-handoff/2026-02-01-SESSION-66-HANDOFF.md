# Session 66 Handoff - 2026-02-01

## Session Summary

Investigated V8 hit rate degradation and discovered the **root cause was data leakage** in the player_daily_cache processor. The 84.5% hit rate for Jan 1-8 was an illusion - the features included the current game's stats in rolling averages.

## Critical Finding: Data Leakage Bug

### The Bug

In `player_daily_cache_processor.py`:

```python
# BUG (before Jan 26, 2026):
WHERE game_date <= '{analysis_date}'  # Included current game (data leakage!)

# FIX (after Jan 26, 2026):
WHERE game_date < '{analysis_date}'  # Correctly excludes current game
```

### Timeline

| Date | Event |
|------|-------|
| **Jan 9, 2026** | All historical predictions (2021-Jan 8) created with LEAKED features |
| **Jan 26, 2026** | Bug fixed in commit `2f12827b` |
| **Jan 30 - Feb 1** | Jan 9+ predictions created with CORRECT features |

### Impact

| Metric | Leaked (Jan 1-8) | True (Jan 9+) |
|--------|-----------------|---------------|
| Premium Hit Rate | 84.5% | 52.5% |
| High Conf Hit Rate | 70.2% | 58.1% |
| Predictions correlated with actuals | 0.724 | 0.621 |

**The 84% hit rate was fake.** The true model performance is ~52-58%.

## Fixes Applied

| Change | File | Commit |
|--------|------|--------|
| Add features_snapshot JSON field | Schema, worker, backfill | `dc354967` |
| Document root cause | This handoff | - |

## True Model Performance (Post-Fix)

### By Filter Tier

| Filter Tier | Predictions | Hit Rate | Avg Edge |
|-------------|-------------|----------|----------|
| Premium (92+ conf, 3+ edge) | 59 | 52.5% | 4.0 |
| High Conf (92+) | 136 | 58.1% | 1.8 |
| High Edge (5+) | 437 | 57.0% | 7.6 |
| Standard | 1,156 | 51.1% | 2.7 |

### Weekly Trend (92+ Confidence)

| Week | Predictions | Hit Rate |
|------|-------------|----------|
| Jan 4 | 35 | 45.7% |
| Jan 11 | 56 | 60.7% |
| Jan 18 | 39 | 46.2% |
| Jan 25 | 65 | 64.6% |

## Features Snapshot Field

Added `features_snapshot` JSON field to predictions table to store feature values at prediction time:

```sql
-- Columns added:
features_snapshot JSON        -- Key feature values used
feature_version STRING        -- v2_33features, v2_37features, etc.
feature_quality_score FLOAT64 -- Quality score (0-100)
```

This enables:
1. Debugging when hit rates change unexpectedly
2. Detecting feature drift over time
3. Preventing repeat of this issue (can compare features later)

## Known Issues

1. **All historical predictions (2021-Jan 8, 2026) used leaked features** - cannot be trusted for accuracy analysis
2. **Model performance is ~52-58%** - barely above random for betting purposes
3. **Need to evaluate if model retraining can improve** - current model may not be production-ready

## Next Session Tasks

### P1 - Critical
1. **Decide on model strategy**: Is 52-58% hit rate acceptable? Options:
   - Retrain model on current v37 features
   - Run `exp_20260201_current_szn` challenger experiment
   - Consider alternative approaches

2. **Fix broken features**: `pace_score`, `team_win_pct` are still broken

### P2 - High
3. **Regenerate ALL historical predictions** with correct features (for accurate backtesting)
4. **Deploy prediction worker** with features_snapshot field

### P3 - Medium
5. **Set up feature drift monitoring** using features_snapshot
6. **Create dashboard** for true hit rate tracking

## Key Learnings

1. **Always store feature snapshots** - enables debugging when metrics change
2. **Data leakage is insidious** - symptoms (high accuracy) can mask the problem
3. **Verify feature queries** - `<=` vs `<` can cause massive data leakage
4. **Backfilling predictions doesn't fix the original** - Jan 1-8 predictions still use old features

## Files Changed This Session

| File | Change |
|------|--------|
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | Added features_snapshot, feature_version, feature_quality_score |
| `predictions/worker/worker.py` | Store features_snapshot for CatBoost V8 |
| `ml/backfill_v8_predictions.py` | Store features_snapshot in backfill |

## Commits This Session

```
dc354967 feat: Add features_snapshot field to predictions for debugging
```

---

*Session 66 - 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
