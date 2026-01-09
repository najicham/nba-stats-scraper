# v8 Stacked Ensemble - Technical Summary

## Architecture

```
Layer 1 (Base Models):
┌─────────────────────────────────────────────────────────────┐
│  XGBoost          LightGBM         CatBoost                 │
│  MAE: 3.45        MAE: 3.47        MAE: 3.43                │
│  max_depth=6      max_depth=6      depth=6                  │
│  lr=0.03          lr=0.03          lr=0.07                  │
│  reg_lambda=5     reg_lambda=5     l2_leaf_reg=3.8          │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
Layer 2 (Meta-Learner):
┌─────────────────────────────────────────────────────────────┐
│  Ridge Regression (alpha=1.0)                               │
│  Coefficients: XGB=0.38, LGB=-0.10, CB=0.74                 │
│  Final: 0.38*XGB - 0.10*LGB + 0.74*CatBoost                │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    Final MAE: 3.40
```

---

## Training Configuration

| Parameter | Value |
|-----------|-------|
| Training Period | 2021-11-01 to 2024-06-01 |
| Total Samples | 76,863 player-games |
| Train Split | 70% (53,804 samples) |
| Validation Split | 15% (11,530 samples) |
| Test Split | 15% (11,529 samples) |
| Features | 33 |

---

## Features (33 Total)

### Base Features (25) - from ml_feature_store_v2
- Recent performance: `points_avg_last_5`, `points_avg_last_10`, `points_std_last_10`
- Season averages: `points_avg_season`, `minutes_avg_season`
- Trends: `recent_trend`, `momentum`
- Opponent: `opponent_def_rating`, `opponent_pace`
- Context: `home_away`, `rest_days`, `back_to_back`
- Usage: `usage_rate`, `ast_rate`, `true_shooting_pct`
- And others...

### Vegas Features (4) - added in v7
- `vegas_points_line` - consensus prop line
- `vegas_opening_line` - opening line
- `vegas_line_movement` - movement from open to close
- `vegas_line_indicator` - binary over/under indicator

### Opponent History (2)
- `points_avg_vs_opponent` - historical average against this team
- `games_vs_opponent` - number of previous matchups

### Minutes/PPM History (2) - **BREAKTHROUGH in v8**
- `ppm_avg_last_10` - points per minute, last 10 games
- `minutes_avg_last_10` - average minutes, last 10 games

---

## Feature Importance

| Rank | Feature | Importance | Category |
|------|---------|------------|----------|
| 1 | points_avg_last_5 | 31.8% | Base |
| 2 | points_avg_last_10 | 18.6% | Base |
| 3 | **ppm_avg_last_10** | **14.6%** | **Minutes/PPM** |
| 4 | **minutes_avg_last_10** | **10.9%** | **Minutes/PPM** |
| 5 | points_std_last_10 | 6.3% | Base |
| 6 | points_avg_season | 3.1% | Base |
| 7 | vegas_points_line | 2.0% | Vegas |
| 8 | vegas_opening_line | 1.5% | Vegas |
| 9 | recent_trend | 1.3% | Base |
| 10 | opponent_def_rating | 0.9% | Base |

**Key insight**: Minutes/PPM features (rank 3 & 4) were the breakthrough that dropped MAE from 3.88 to 3.40.

---

## Performance Metrics

### Test Set (2024-02 to 2024-06)
| Metric | Value |
|--------|-------|
| MAE | 3.40 |
| vs Mock (4.80) | -29.1% |
| vs Vegas (4.97) | -31.6% |
| Within 5 pts | ~78% |

### Out-of-Sample 2024-25 Season (35,137 games)
| Metric | Value |
|--------|-------|
| MAE | 3.49 |
| vs Vegas (4.98) | -25.4% |
| Within 5 pts | 76.0% |

### Performance by Player Tier (2024-25)
| Tier | Avg PPG | MAE | Games |
|------|---------|-----|-------|
| Bench | 0-8 | 2.83 | 15,072 |
| Role | 8-15 | 3.65 | 12,201 |
| Starter | 15-22 | 4.26 | 5,035 |
| Star | 22+ | 5.12 | 2,651 |

Stars have highest variance (hardest to predict), bench players are most predictable.

---

## Betting Performance

| Metric | Value |
|--------|-------|
| Over/Under Accuracy | 71.6% |
| Break-even threshold | 52.4% |
| Edge over break-even | +19.2% |

### Accuracy by Confidence Level
| Our Edge vs Vegas | Accuracy | Games |
|-------------------|----------|-------|
| Any prediction | 71.6% | 19,515 |
| > 1 pt edge | 77.6% | 14,268 |
| > 3 pts edge | 86.2% | 6,451 |
| > 5 pts edge | 91.5% | 2,708 |

**Bigger disagreements with Vegas = higher accuracy**

---

## Model Files

```
# Primary model files
models/xgboost_v8_33features_20260108_211817.json
models/lightgbm_v8_33features_20260108_211817.txt
models/catboost_v8_33features_20260108_211817.cbm
models/ensemble_v8_20260108_211817_metadata.json

# Training script
ml/train_final_ensemble_v8.py

# Validation script
ml/validate_v8_2024_25.py
```

---

## Dependencies

- xgboost >= 1.7.0
- lightgbm >= 3.3.0
- catboost >= 1.1.0
- scikit-learn >= 1.2.0 (for Ridge meta-learner)
- pandas, numpy
