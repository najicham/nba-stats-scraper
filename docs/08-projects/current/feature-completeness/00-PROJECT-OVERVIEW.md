# Feature Completeness Tracking (Sessions 142-145)

## Problem

Session 141 implemented zero tolerance for default features -- predictions are blocked when ANY feature uses a fabricated default value. This is correct: a default like `avg_points=10.0` for a 27 PPG player is a lie. But coverage dropped from ~180 to ~75 predictions per game day.

We need to:
1. **Track which features are missing** per prediction for diagnostics
2. **Know exactly what's defaulted** so we can fix the pipeline
3. **Document the feature contract** so future sessions know what to fix
4. **Make vegas features optional** so bench players without prop lines still get predictions (Session 145)
5. **Fix cache timing** so the feature store sees daily cache data (Session 144)

## Solution

### New Field: `default_feature_indices`

Added `ARRAY<INT64>` column to both:
- `nba_predictions.player_prop_predictions` -- every prediction records which features were real vs fabricated
- `nba_predictions.ml_feature_store_v2` -- feature store records which features defaulted

Empty array = all features are real data. Non-empty = those indices used defaults.

### Feature Source Classification

Added to `shared/ml/feature_contract.py`:

| Source | Feature Indices | Pipeline Component |
|--------|----------------|-------------------|
| Phase 4 | 0-8, 13-14, 22-23, 29, 31-32 | Phase 4 precompute processors |
| Phase 3 | 15-17 | Phase 3 analytics |
| Calculated | 9-12, 21, 24, 28, 30, 33-36 | Feature store on-the-fly |
| Vegas | 25-27 | Odds API scrapers |
| Shot Zone | 18-20 | Shot zone analysis |

## Pipeline Gap Analysis (Feb 6, 2026)

Based on last 7 days of data:

| Feature | Index | Default Count | Affected Players | Root Cause |
|---------|-------|--------------|------------------|------------|
| vegas_points_line | 25 | 1,436 | 464 | Not all players have prop lines (NORMAL) |
| vegas_opening_line | 26 | 1,436 | 464 | Same as above |
| vegas_line_move | 27 | 1,436 | 464 | Same as above |
| pct_paint | 18 | 512 | 126 | Shot zone data missing for low-minutes players |
| pct_mid_range | 19 | 512 | 126 | Same |
| pct_three | 20 | 512 | 126 | Same |
| minutes_avg_last_10 | 31 | 328 | 90 | Daily cache missing for new/traded players |
| ppm_avg_last_10 | 32 | 328 | 90 | Same |
| points_std_last_10 | 3 | 298 | 91 | Insufficient game history |
| games_in_last_7_days | 4 | 298 | 91 | Same |
| team_pace | 22 | 298 | 91 | Team context missing |
| team_off_rating | 23 | 298 | 91 | Same |
| points_avg_last_5 | 0 | 260 | 79 | New/traded players |
| points_avg_last_10 | 1 | 222 | 69 | Same, longer window |
| fatigue_score | 5 | 103 | 52 | Composite factors processor |
| shot_zone_mismatch | 6 | 103 | 52 | Same |
| pace_score | 7 | 103 | 52 | Same |
| usage_spike_score | 8 | 103 | 52 | Same |
| points_avg_season | 2 | 1 | 1 | Rare edge case |

### Key Insights

1. **Vegas (25-27)**: 1,436 defaults is NORMAL. Only ~40% of players have prop lines. These players can never have zero defaults unless we change how vegas features work.
2. **Shot zones (18-20)**: 512 defaults for 126 players. These are low-minutes players without enough shot data. Fix: improve shot zone processor to handle sparse data.
3. **Player history (0-4, 31-32)**: 260-328 defaults for 79-91 players. New/traded players with insufficient game history. Fix: bootstrap from previous team stats.
4. **Composite factors (5-8)**: 103 defaults for 52 players. These need the PlayerCompositeFactorsProcessor to run. Fix: ensure processor covers all players.

### Path to Higher Coverage

**Before Session 144-145:** ~75 predictions/day (37% fully complete records)

**After Session 144 (cache miss fallback):** ~50-63% fully complete (cache timing fix)

**After Session 145 (vegas optional):** ~95-100% predictions enabled (vegas no longer blocks)

#### Fixes Applied (Sessions 144-145)

| Fix | Session | Impact | Status |
|-----|---------|--------|--------|
| Cache miss fallback (`feature_extractor.py`) | 144 | 37% → ~50% complete | **Deployed** |
| Vegas features optional in zero-tolerance | 145 | ~50% → ~95% predictions enabled | **Implemented** |
| Gap tracking table (`feature_store_gaps`) | 144 | Automatic gap detection | **Deployed** |
| `required_default_count` field | 145 | Distinguishes required vs optional defaults | **Implemented** |
| `--include-bootstrap` flag for backfill | 144 | Bootstrap period backfill support | **Implemented** |

#### Root Cause Analysis (Session 144)

| Root Cause | Features | Default Rate | Fix |
|-----------|----------|-------------|-----|
| **PlayerDailyCacheProcessor** only caches today's game players (~175/457) | 0-4, 22-23, 31-32 | 13% | **FIXED** - fallback computes from last_10_games |
| **Vegas lines** unavailable for bench players (~60%) | 25-27 | 60% | **FIXED** - made optional in zero-tolerance |
| **Shot zone** timing/coverage gaps | 18-20 | 24% | **PARTIALLY FIXED** by cache fallback |
| **Composite factors** processor coverage | 5-8 | 4% | OK - low rate |

#### Remaining Work

1. **Fix PlayerDailyCacheProcessor root cause** - Cache all season players, not just today's games
2. **Scraper health monitoring** - Alert when tier 1-2 star players lack vegas lines (indicates scraper issue)
3. **Shot zone coverage** - Improve processor for sparse-data players

## Files Modified

| File | Change | Session |
|------|--------|---------|
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | Added `default_feature_indices ARRAY<INT64>` | 142 |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Added `default_feature_indices`, `required_default_count` | 142, 145 |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | `default_feature_indices`, `required_default_count`, `OPTIONAL_FEATURES` | 142, 145 |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | `_compute_cache_fields_from_games()` fallback | 144 |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | `_record_feature_store_gaps()`, `skip_early_season_check` | 144 |
| `predictions/coordinator/quality_gate.py` | Uses `required_default_count` for gating | 145 |
| `predictions/worker/worker.py` | Uses `required_default_count` for filtering | 145 |
| `shared/ml/feature_contract.py` | `FEATURES_OPTIONAL`, `FEATURE_SOURCE_MAP` | 142, 145 |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | `--include-bootstrap`, `_resolve_gaps_for_date()` | 144 |

## Verification

```sql
-- Check that new records have default_feature_indices populated
SELECT game_date,
       COUNTIF(default_feature_indices IS NOT NULL) as has_indices,
       COUNTIF(default_feature_indices IS NULL) as missing_indices
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1;

-- Check which features are most defaulted (last 7 days)
SELECT idx, COUNT(*) as default_count
FROM nba_predictions.ml_feature_store_v2,
UNNEST(default_feature_indices) as idx
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 2 DESC;
```
