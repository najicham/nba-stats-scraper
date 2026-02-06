# Feature Completeness Tracking (Session 142)

## Problem

Session 141 implemented zero tolerance for default features -- predictions are blocked when ANY feature uses a fabricated default value. This is correct: a default like `avg_points=10.0` for a 27 PPG player is a lie. But coverage dropped from ~180 to ~75 predictions per game day.

We need to:
1. **Track which features are missing** per prediction for diagnostics
2. **Know exactly what's defaulted** so we can fix the pipeline
3. **Document the feature contract** so future sessions know what to fix

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

Current: ~75 predictions/day (players with ALL 33 features from real data).

To increase coverage, fix in priority order:
1. **Composite factors (5-8)**: Fix processor for 52 additional players (+52 potential)
2. **Shot zones (18-20)**: Handle sparse data for 126 players (some overlap)
3. **Player history (0-4)**: Bootstrap new players (some overlap)
4. **Vegas (25-27)**: Structural -- only fixable by changing feature requirements

## Files Modified

| File | Change |
|------|--------|
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | Added `default_feature_indices ARRAY<INT64>` |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Added `default_feature_indices ARRAY<INT64>` |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Emits `default_feature_indices` from existing `is_default` dict |
| `predictions/worker/worker.py` | Writes `default_feature_indices` to prediction record |
| `predictions/worker/data_loaders.py` | Loads `default_feature_indices` from feature store |
| `shared/ml/feature_contract.py` | Added feature source classification constants |

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
