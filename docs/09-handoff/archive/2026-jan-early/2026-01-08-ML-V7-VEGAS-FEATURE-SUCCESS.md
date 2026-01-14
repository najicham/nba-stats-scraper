# ML v7 Training Results: Vegas Features Success

**Date**: January 8, 2026
**Session Goal**: Improve ML model by adding Vegas betting lines as features
**Result**: **SUCCESS** - 6.3% improvement over v6

---

## Executive Summary

| Metric | Before (v6) | After (v7 Ensemble) | Change |
|--------|-------------|---------------------|--------|
| Test MAE | 4.14 | 3.881 | **-6.3%** |
| vs Mock Baseline | -13.8% | -19.1% | +5.3pp |
| Features | 25 | 31 | +6 |

**Key finding**: Vegas betting lines are the **3rd most important feature** (15.6% importance), after only recent points averages.

---

## What We Did

### 1. Explored Vegas Data
- Found `bettingpros_player_points_props` table with 1.8M+ lines
- Coverage: 54% of player-games (top players only)
- Covers full training period (2021-2024)
- Vegas consensus MAE: 4.97 (we already beat them by 17%!)

### 2. Added New Features
| Feature | Description | Importance |
|---------|-------------|------------|
| `vegas_points_line` | Market consensus closing line | **15.6%** (#3) |
| `has_vegas_line` | Coverage indicator (for imputation) | 6.6% (#5) |
| `vegas_opening_line` | Opening line | 3.5% (#6) |
| `avg_points_vs_opponent` | Player's historical avg vs this team | 2.8% (#7) |
| `vegas_line_move` | Line movement (closing - opening) | 1.0% |
| `games_vs_opponent` | Sample size for opponent history | 0.8% |

### 3. Trained Multiple Models
| Model | Test MAE | vs v6 | Notes |
|-------|----------|-------|-------|
| XGBoost v7 | 3.906 | -5.6% | Solid improvement |
| LightGBM v7 | 3.901 | -5.8% | Slightly better |
| CatBoost v7 | 3.899 | -5.8% | Best individual |
| CatBoost (Optuna) | 3.888 | -6.1% | Tuned hyperparams |
| **Stacked Ensemble** | **3.881** | **-6.3%** | Ridge meta-learner |

---

## Model Architecture

### Stacked Ensemble (Best Model)
```
Layer 1: Train XGBoost, LightGBM, CatBoost on training data
Layer 2: Ridge regression meta-learner on validation predictions
Final:   Weighted combination with learned coefficients
         XGB: 0.557, LGB: -0.212, CB: 0.661
```

### Training Configuration
- **Training data**: 77,828 player-games (2021-11 to 2024-06)
- **Split**: 70% train, 15% validation, 15% test
- **Features**: 31 (25 base + 6 new)
- **Vegas coverage**: 54% (imputed with season average for missing)

---

## Files Created

### Training Scripts
- `ml/train_xgboost_v7.py` - XGBoost with Vegas features
- `ml/train_multi_model_v7.py` - Multi-model comparison + ensemble
- `ml/optuna_optimize_v7.py` - Hyperparameter optimization

### Saved Models
- `models/xgboost_v7_31features_*.json`
- `models/lightgbm_v7_31features_*.txt`
- `models/catboost_v7_31features_*.cbm`
- `models/catboost_v7_optuna_*.cbm`
- `models/multi_model_v7_comparison_*.json` (metadata)

---

## Why It Worked

1. **Vegas captures complementary signal**: Even though we beat Vegas overall, the market knows things we don't (injuries, lineups, news)

2. **Proper handling of missing data**:
   - Used `has_vegas_line` indicator
   - Imputed missing lines with player season average
   - Preserved all training data while capturing Vegas signal

3. **Player-opponent history adds value**: Historical performance vs specific teams provides matchup-specific signal

4. **Ensemble diversity**: XGBoost, LightGBM, CatBoost make different errors → averaging reduces overall error

---

## Future Opportunities

### Quick Wins (Already Explored)
- ✅ Vegas points line as feature
- ✅ Vegas line movement
- ✅ Player-vs-opponent history
- ✅ LightGBM/CatBoost comparison
- ✅ Stacked ensemble
- ✅ Hyperparameter optimization

### Remaining Ideas
| Idea | Expected Impact | Effort |
|------|-----------------|--------|
| Two-stage model (minutes → points/min) | -0.02 to -0.05 | Medium |
| Injury report integration | -0.01 to -0.03 | Medium |
| Game-level odds (totals/spreads) | Need data source | High |
| Player clustering + specialist models | -0.01 to -0.03 | Medium |
| Real-time line movement features | Need data pipeline | High |

### Theoretical Floor
Based on player performance variance, the theoretical floor is approximately **3.5 MAE**. We're at 3.88, which is 90% of the way there. Remaining gains will be incremental.

---

## Recommendations

### For Production
1. Deploy the stacked ensemble (3.881 MAE)
2. If too complex, use CatBoost v7 optimized (3.888 MAE)
3. Ensure Vegas lines are refreshed before predictions

### For Further Improvement
1. **Two-stage model**: Predict minutes first, then points/minute
2. **Injury integration**: You have `nbac_injury_report` table - use it
3. **Feature engineering**: Add teammate availability, game importance

---

## Summary

**Before**: XGBoost v6 with 25 features → 4.14 MAE
**After**: Stacked ensemble with 31 features → 3.881 MAE

**Improvement**: 0.259 points (6.3%)
**vs Mock baseline**: Now 19.1% better (was 13.8%)

The biggest win was recognizing that Vegas lines, despite being less accurate than our model overall, contain complementary signal that improves predictions when used as a feature.
