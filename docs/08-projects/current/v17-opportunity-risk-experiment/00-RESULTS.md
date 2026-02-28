# V17 Opportunity Risk Features — Experiment Results

**Session:** 360
**Date:** 2026-02-27
**Status:** DEAD END — features provide no signal

## Hypothesis

Session 359's 12-experiment matrix showed `points_avg_season` dominates at 28% feature importance — the model wants MORE player-specific signal. UNDER predictions remain weakest (50-60% HR). V17 adds 3 features that capture **risk of reduced opportunity** — the gap the model can't currently express.

## Features Added (indices 57-59)

| Index | Name | What | Data Source | Default |
|-------|------|------|-------------|---------|
| 57 | `blowout_minutes_risk` | Fraction of team's L10 games with 15+ margin | `team_offense_game_summary.margin_of_victory` | 0.2 |
| 58 | `minutes_volatility_last_10` | Stdev of player minutes over L10 | `player_game_summary.minutes_played` | 4.0 |
| 59 | `opponent_pace_mismatch` | team_pace - opponent_pace | Computed from existing features 22 and 14 | 0.0 |

## Experiment Results

All experiments used: train Dec 1 - Feb 15, eval Feb 16-27.

| Exp | Config | Edge 3+ HR | N | OVER HR | UNDER HR | Top V17 Feature |
|-----|--------|-----------|---|---------|----------|-----------------|
| E1 | V17 noveg | 56.7% | 30 | 72.7% (11) | 47.4% (19) | None in top 10 |
| E2 | V17 vegas=0.25 | 58.1% | 31 | 66.7% (15) | 50.0% (16) | None in top 10 |

**Comparison (same eval window):**

| Model | Edge 3+ HR | OVER | UNDER | N |
|-------|-----------|------|-------|---|
| V12 vegas=0.25 (A3, Session 359) | **75.0%** | 100% | 60% | 16 |
| V16 noveg + rec14 (D1, Session 359) | **69.0%** | 81.8% | 61.1% | 29 |
| V17 noveg (E1) | 56.7% | 72.7% | 47.4% | 30 |
| V17 vegas=0.25 (E2) | 58.1% | 66.7% | 50.0% | 31 |

## Feature Importance

**V17 noveg (E1):**
```
1. points_avg_season          37.15%
2. points_avg_last_10         17.09%
3. line_vs_season_avg         12.30%
4. points_avg_last_5           6.72%
5. minutes_avg_last_10         2.37%
...
   blowout_minutes_risk       <1%
   minutes_volatility_last_10 <1%
   opponent_pace_mismatch     <1%
```

**V17 vegas=0.25 (E2):**
```
1. points_avg_season          30.52%
2. points_avg_last_10         15.44%
3. line_vs_season_avg         10.10%
4. points_avg_last_5           8.28%
5. vegas_points_line            6.20%
...
   blowout_minutes_risk       <1%
   minutes_volatility_last_10 <1%
   opponent_pace_mismatch     <1%
```

All 3 V17 features below 1% importance in both experiments. The model finds zero signal.

## Data Coverage

Feature coverage was excellent — this wasn't a data issue:

| Feature | Train Coverage | Eval Coverage |
|---------|---------------|---------------|
| blowout_minutes_risk | 91.2% (8744/9590) | 96.1% (196/204) |
| minutes_volatility_last_10 | 99.5% (9542/9590) | 99.5% (203/204) |
| opponent_pace_mismatch | 100% (9590/9590) | 100% (204/204) |

## Why It Failed

1. **Blowout risk is team-level, not player-level.** A team being in blowouts doesn't tell the model much about THIS player's points — the model already has `points_avg_season` (37%) which captures the player's scoring role.

2. **Minutes volatility doesn't predict direction.** High stdev means the player's minutes vary, but that doesn't tell you whether they'll score OVER or UNDER today. It's noise, not signal.

3. **Pace mismatch is already captured.** Features 22 (team_pace) and 14 (opponent_pace) already exist independently. Subtracting them adds no information that CatBoost couldn't learn from the originals via tree splits.

## Infrastructure Delivered

Despite the dead-end features, the implementation is complete and reusable:
- Feature contract: V17/V17_NOVEG contracts (59/55 features)
- Feature store: `v2_60features` schema with BQ columns added
- Feature extractor: `_batch_extract_v17_opportunity_risk()` with SQL query
- Feature store processor: Computes and writes features 57-59
- Quick retrain: `--feature-set v17_noveg --v17-features` flag
- Prediction worker: `v17_noveg` feature vector building (55 features)

## Files Modified

1. `shared/ml/feature_contract.py` — V17 contracts, defaults, source maps
2. `data_processors/precompute/ml_feature_store/feature_extractor.py` — V17 extraction
3. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — V17 computation
4. `ml/experiments/quick_retrain.py` — V17 CLI support + BQ feature computation
5. `predictions/worker/prediction_systems/catboost_monthly.py` — V17 worker support
6. `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` — Migration DDL
