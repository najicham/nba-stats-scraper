# CatBoost V11 - Seasonal Features

**Status**: IN PROGRESS
**Started**: 2026-01-30
**Hypothesis**: Seasonal patterns (All-Star effects, minutes trends) improve predictions

---

## Background

Session 34 tested recency weighting (V9) and found it **hurts** performance. However, the original observation was about **seasonal patterns**:

> "Stars get more minutes near All-Star break, bench rotations tighten"

This is a **seasonal effect** that varies by player tier, not a uniform recency effect. V11 tests this hypothesis by adding seasonal features to V8's 33-feature baseline.

---

## V11 Feature Design

### Approach: Calculate at Training Time

We add seasonal features **at training time** from `game_date`, not in the feature store. This allows rapid experimentation without infrastructure changes.

### Proposed Features (6 new)

```python
V11_SEASONAL_FEATURES = [
    # Time-of-season (4)
    'week_of_season',         # 0-42 (weeks since season start)
    'pct_season_completed',   # 0.0-1.0
    'days_to_all_star',       # Days until All-Star break (negative after)
    'is_post_all_star',       # 0/1 boolean

    # Minutes trend (2)
    'minutes_slope_10g',      # Linear slope of minutes over L10
    'minutes_vs_season_avg',  # Current minutes vs season average
]
```

**Total: 33 (V8) + 6 = 39 features**

### Feature Calculations

```python
from datetime import date
from shared.config.nba_season_dates import get_season_start_date, get_season_year_from_date

# All-Star break dates (mid-February)
ALL_STAR_DATES = {
    2021: date(2022, 2, 20),  # 2021-22 season
    2022: date(2023, 2, 19),  # 2022-23 season
    2023: date(2024, 2, 18),  # 2023-24 season
    2024: date(2025, 2, 16),  # 2024-25 season
    2025: date(2026, 2, 15),  # 2025-26 season (estimated)
}

def calculate_seasonal_features(game_date: date, season_year: int) -> dict:
    """Calculate seasonal features from game date."""
    season_start = get_season_start_date(season_year)
    all_star_date = ALL_STAR_DATES.get(season_year, date(season_year + 1, 2, 17))

    days_into_season = (game_date - season_start).days
    days_to_all_star = (all_star_date - game_date).days

    return {
        'week_of_season': days_into_season // 7,
        'pct_season_completed': min(1.0, days_into_season / 250),  # ~250 days in season
        'days_to_all_star': days_to_all_star,
        'is_post_all_star': 1.0 if days_to_all_star < 0 else 0.0,
    }
```

### Minutes Trend Features

These require access to historical minutes data. Options:

1. **From feature store**: `minutes_avg_last_10` is already available (feature 31)
2. **Calculate slope**: Need L5 vs L10 or similar comparison
3. **From BigQuery**: Join with player_game_summary for minutes history

For initial experiment, we can approximate using existing features:
- `minutes_slope_10g` ≈ proxy from feature store
- `minutes_vs_season_avg` = `minutes_avg_last_10` / (some season baseline)

---

## Implementation Plan

### Phase 1: Quick Experiment (This Session)

1. Create training script with 4 time-of-season features
2. Run experiment without minutes trend features
3. Compare to V8 baseline

### Phase 2: Full Implementation (If Phase 1 shows promise)

1. Add minutes trend features
2. Train full V11 model
3. Create prediction system
4. Deploy in shadow mode

---

## Files

### Training Script
```
ml/experiments/train_v11_seasonal.py
```

### Results
```
ml/experiments/results/catboost_v11_exp_*.cbm
ml/experiments/results/catboost_v11_exp_*_metadata.json
```

---

## Expected Outcomes

### Success Criteria
- MAE < 4.02 (beats V8 baseline from V9 experiments)
- Improvement in star player predictions near All-Star break

### What Would Prove Hypothesis Wrong
- No improvement from seasonal features
- Seasonal features hurt like recency did

---

## Version Comparison

| Version | Features | Approach | Status |
|---------|----------|----------|--------|
| V8 | 33 | Standard | PRODUCTION |
| V9 | 36 + recency | Uniform recency weighting | DELETED (hurt performance) |
| V10 | 33 | Model file only | No system |
| **V11** | 39 | Seasonal features | IN PROGRESS |

---

*V11 tests the correct hypothesis: seasonal patterns matter, not uniform recency.*
