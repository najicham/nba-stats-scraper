# ML Feature Catalog

**Last Updated:** 2026-01-25
**Model Version:** CatBoost V8 (34 features)

## Overview

This document catalogs all 34 features used in the CatBoost V8 prediction model. Features are extracted from the ML Feature Store (`nba_predictions.ml_feature_store_v2`) which aggregates data from Phase 3 analytics and Phase 4 precompute tables.

## Feature Index

### Base Features (0-24)

| Index | Feature Name | Description | Source | Fallback |
|-------|-------------|-------------|--------|----------|
| 0 | `points_avg_last_5` | Average points in last 5 games | Phase 4 | Season avg |
| 1 | `points_avg_last_10` | Average points in last 10 games | Phase 4 | Season avg |
| 2 | `points_avg_season` | Season average points | Phase 3 | 10.0 |
| 3 | `points_std_last_10` | Standard deviation last 10 games | Phase 4 | 5.0 |
| 4 | `games_in_last_7_days` | Games played in last 7 days | Phase 4 | 2 |
| 5 | `fatigue_score` | Fatigue composite score (0-100) | Phase 4 | 70 |
| 6 | `shot_zone_mismatch_score` | Shot zone vs opponent defense mismatch | Phase 4 | 0 |
| 7 | `pace_score` | Pace advantage score | Phase 4 | 0 |
| 8 | `usage_spike_score` | Usage spike score (teammate injuries) | Phase 4 | 0 |
| 9 | `rest_advantage` | Rest days vs opponent (calculated) | Calculated | 0 |
| 10 | `injury_risk` | Injury risk score (calculated) | Calculated | 0 |
| 11 | `recent_trend` | Recent performance trend (calculated) | Calculated | 0 |
| 12 | `minutes_change` | Minutes change vs season average (calculated) | Calculated | 0 |
| 13 | `opponent_def_rating` | Opponent defensive rating | Phase 3/4 | 112.0 |
| 14 | `opponent_pace` | Opponent pace factor | Phase 3/4 | 100.0 |
| 15 | `home_away` | Home game indicator (1=home, 0=away) | Phase 3 | 0 |
| 16 | `back_to_back` | Back-to-back game indicator | Phase 3 | 0 |
| 17 | `playoff_game` | Playoff game indicator | Phase 3 | 0 |
| **18** | **`pct_paint`** | **% shots from paint (NULLABLE)** | **Phase 4/3** | **NULL** ⚠️ |
| **19** | **`pct_mid_range`** | **% shots from mid-range (NULLABLE)** | **Phase 4/3** | **NULL** ⚠️ |
| **20** | **`pct_three`** | **% shots from 3-point (NULLABLE)** | **Phase 4/3** | **NULL** ⚠️ |
| 21 | `pct_free_throw` | Free throw rate (calculated) | Calculated | 20 |
| 22 | `team_pace` | Team pace factor last 10 games | Phase 3/4 | 100.0 |
| 23 | `team_off_rating` | Team offensive rating last 10 games | Phase 3/4 | 112.0 |
| 24 | `team_win_pct` | Team winning percentage (calculated) | Calculated | 0.5 |

### Vegas Features (25-28)

| Index | Feature Name | Description | Source | Fallback |
|-------|-------------|-------------|--------|----------|
| 25 | `vegas_points_line` | Current Vegas points line | Vegas API | Season avg |
| 26 | `vegas_opening_line` | Opening Vegas line | Vegas API | Season avg |
| 27 | `vegas_line_move` | Line movement (current - opening) | Vegas API | 0.0 |
| 28 | `has_vegas_line` | Vegas line availability indicator | Vegas API | 0.0 |

### Opponent History Features (29-30)

| Index | Feature Name | Description | Source | Fallback |
|-------|-------------|-------------|--------|----------|
| 29 | `avg_points_vs_opponent` | Historical avg vs this opponent | Phase 4 | Season avg |
| 30 | `games_vs_opponent` | Career games vs this opponent | Phase 4 | 0 |

### Minutes/PPM Features (31-32)

| Index | Feature Name | Description | Source | Fallback |
|-------|-------------|-------------|--------|----------|
| 31 | `minutes_avg_last_10` | Average minutes last 10 games | Phase 4 | 25.0 |
| 32 | `ppm_avg_last_10` | Points per minute last 10 games | Phase 4 | 0.4 |

### Data Quality Indicator (33)

| Index | Feature Name | Description | Source | Fallback |
|-------|-------------|-------------|--------|----------|
| **33** | **`has_shot_zone_data`** | **Shot zone data availability (1.0 = complete, 0.0 = missing)** | **Calculated** | **0.0** |

## Shot Zone Features (18-20) - Special Handling

**Updated:** 2026-01-25

### Overview

Features 18-20 (shot zone percentages) use **NULLABLE** extraction instead of league average defaults. This allows the ML model to distinguish between "average shooter" and "data unavailable."

### Fallback Behavior

```
BigDataBall PBP (primary)
  ↓
NBAC PBP (fallback)
  ↓
NULL (data unavailable)
```

### Data Sources

1. **BigDataBall PBP** (Primary - 94% coverage)
   - Has shot coordinates (x, y)
   - Precise zone classification
   - Includes assisted/unassisted tracking
   - Includes and-1 and blocks data

2. **NBAC PBP** (Fallback - 100% coverage)
   - Basic zone classification only
   - No shot coordinates
   - No assisted/unassisted tracking
   - No blocks data

3. **NULL** (When both fail)
   - Explicitly signals missing data to model
   - Feature #33 (`has_shot_zone_data`) = 0.0
   - CatBoost learns optimal handling via tree splits

### Example Feature Values

**Case 1: BigDataBall data available**
```python
{
    'pct_paint': 0.35,        # 35% of shots from paint
    'pct_mid_range': 0.20,    # 20% from mid-range
    'pct_three': 0.35,        # 35% from three
    'has_shot_zone_data': 1.0 # All data available
}
```

**Case 2: NBAC fallback (basic zones only)**
```python
{
    'pct_paint': 0.30,        # 30% of shots from paint
    'pct_mid_range': 0.25,    # 25% from mid-range
    'pct_three': 0.40,        # 40% from three
    'has_shot_zone_data': 1.0 # Basic zones available
}
```

**Case 3: Both sources failed**
```python
{
    'pct_paint': None,        # NULL (not 30.0 default)
    'pct_mid_range': None,    # NULL (not 20.0 default)
    'pct_three': None,        # NULL (not 35.0 default)
    'has_shot_zone_data': 0.0 # Missing data indicator
}
```

### Model Handling

**CatBoost V8** handles NULL values natively:
- NULL values stored as `np.nan` in feature vector
- Validation allows NaN for indices 18-20 only
- CatBoost uses tree splits to learn optimal handling
- Model can learn different patterns for missing vs available data

### Quality Impact

- **Gold tier (BigDataBall):** Full shot zone data + advanced metrics
- **Silver tier (NBAC fallback):** Basic shot zones only
- **Bronze tier (NULL):** Model uses has_shot_zone_data=0.0 signal

## Feature Versioning

| Version | Features | Date Added | Key Changes |
|---------|----------|------------|-------------|
| V1 | 25 | 2025-10 | Initial production model |
| V8.0 | 33 | 2026-01 | Added Vegas, opponent history, minutes/PPM |
| **V8.1** | **34** | **2026-01-25** | **Added shot zone missingness indicator** |

## Related Documentation

- [Shot Zone Handling Improvements](../../09-handoff/IMPROVE-SHOT-ZONE-HANDLING.md)
- [Shot Zone Failure Runbook](../../02-operations/runbooks/shot-zone-failures.md)
- [ML Feature Store Processor](../../../data_processors/precompute/ml_feature_store/ml_feature_store_processor.py)
- [CatBoost V8 Prediction System](../../../predictions/worker/prediction_systems/catboost_v8.py)
