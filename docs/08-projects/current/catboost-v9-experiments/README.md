# CatBoost V9 Experiments

**Status**: In Progress
**Started**: 2026-01-30
**Owner**: Claude Code Session

## Overview

CatBoost V9 extends V8 with two key improvements:
1. **Trajectory Features** (3 new) - Capture player momentum/trends
2. **Recency-Weighted Training** - Recent games weighted higher

## Why V9?

### Problem: V8 Model Degradation
V8 was trained on 2021-2024 data but NBA dynamics shifted mid-season:
- Stars trending UP (load management early season → full steam now)
- Bench players trending DOWN (rotations tightening)
- V8's static averages miss these trends

### Solution: Trajectory Features
| Feature | Description | Captures |
|---------|-------------|----------|
| `pts_slope_10g` | Linear regression slope over L10 | Direction of trend |
| `pts_vs_season_zscore` | Z-score of L5 vs season avg | How hot/cold vs baseline |
| `breakout_flag` | 1.0 if L5 > season_avg + 1.5*std | Exceptional performance |

### Solution: Recency Weighting
- Half-life of 180 days (6 months)
- Recent games get higher weights during training
- Model adapts to current NBA meta, not historical patterns

## Files Created

| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v9.py` | V9 prediction system |
| `predictions/worker/worker.py` | Updated to include V9 in shadow mode |
| `ml/experiments/train_walkforward.py` | Training script (already supports recency weighting) |

## Experiment Plan

### Phase 1: Baseline Experiments (Current)

| Exp ID | Features | Recency | Half-Life | Purpose |
|--------|----------|---------|-----------|---------|
| A1 | 33 (V8) | No | - | V8 baseline reproduction |
| A2 | 33 (V8) | Yes | 180 days | Recency only |
| A3 | 33 (V8) | Yes | 90 days | Shorter half-life |
| A4 | 33 (V8) | Yes | 365 days | Longer half-life |

### Phase 2: Trajectory Feature Experiments (Future)

| Exp ID | Features | Recency | Half-Life | Purpose |
|--------|----------|---------|-----------|---------|
| B1 | 36 (V9) | No | - | Trajectory features only |
| B2 | 36 (V9) | Yes | 180 days | Full V9 (target config) |
| B3 | 36 (V9) | Yes | 90 days | Aggressive recency |

### Phase 3: Time-Period Analysis

| Exp ID | Train Period | Test Period | Purpose |
|--------|--------------|-------------|---------|
| C1 | 2021-2024 | 2024-25 | Standard holdout |
| C2 | 2023-2024 | 2024-25 | Recent data only |
| C3 | 2024 only | Jan 2025 | Most recent |

## Training Commands

### A1: V8 Baseline (No Recency)
```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id A1_V8_BASELINE \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --verbose
```

### A2: 33 Features + Recency (180 days)
```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id A2_RECENCY_180 \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --use-recency-weights --half-life 180 \
    --verbose
```

### A3: 33 Features + Recency (90 days)
```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id A3_RECENCY_90 \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --use-recency-weights --half-life 90 \
    --verbose
```

### A4: 33 Features + Recency (365 days)
```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --experiment-id A4_RECENCY_365 \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --use-recency-weights --half-life 365 \
    --verbose
```

## Success Criteria

1. **MAE Improvement**: V9 MAE < 3.40 (V8 baseline)
2. **Hit Rate Improvement**: Better over/under prediction accuracy
3. **Stability**: Consistent performance across different time periods
4. **Shadow Mode Validation**: 1-2 weeks A/B comparison in production

## TODO List

### Immediate (Today)
- [x] Create CatBoost V9 prediction system
- [x] Update worker.py to include V9 in shadow mode
- [x] Create documentation
- [ ] Run A1-A4 experiments (baseline + recency variations)
- [ ] Analyze experiment results

### Short-term (This Week)
- [ ] Backfill feature store with trajectory features
- [ ] Run B1-B2 experiments (trajectory features)
- [ ] Deploy best model to shadow mode
- [ ] Monitor shadow mode predictions

### Medium-term (1-2 Weeks)
- [ ] Complete A/B comparison (V8 vs V9)
- [ ] Analyze grading results from production
- [ ] Decide on promotion (V9 → champion)

## Results Log

### Experiment Results (2026-01-30)

| Exp ID | MAE | vs Baseline | Configuration |
|--------|-----|-------------|---------------|
| **A1_V8_BASELINE** | **4.0235** | - | No recency (BEST) |
| C3_CURRENT_SEASON | 4.0330 | +0.2% | Current season, 90-day |
| A4_RECENCY_365 | 4.0760 | +1.3% | Full data, 365-day |
| A2_RECENCY_180 | 4.1681 | +3.6% | Full data, 180-day |
| A3_RECENCY_90 | 4.1816 | +3.9% | Full data, 90-day |
| C2_RECENT_2YR | 4.1820 | +3.9% | 2-year, 180-day |

### Key Finding: Recency Weighting Doesn't Help

**Result:** Every recency-weighted model performed WORSE than the baseline. More aggressive weighting = worse MAE.

**Why?** Uniform recency weighting isn't the right approach. The hypothesis was about **seasonal patterns** (stars playing more in January/All-Star), not general recency.

### Revised Hypothesis

The original observation was:
> "Stars get more minutes near All-Star break, bench rotations tighten"

This is a **seasonal effect**, not a **recency effect**. Recency weighting (recent games matter more uniformly) doesn't capture:
- January/February specific patterns
- Player-tier differences (stars vs. bench)
- Minutes trends (increasing vs. stable)

### Recommended Next Experiments

1. **Seasonal Features**: Add `is_january`, `days_to_all_star`, `pct_season_completed`
2. **Minutes Trend**: Add `minutes_slope_10g` to detect if player is getting more time
3. **Player-Tier Models**: Train separate models for stars vs. role players vs. bench
4. **Trajectory Only**: Test V9 trajectory features WITHOUT recency weighting

## Architecture

```
V8 (Champion)                    V9 (Shadow)
├── 33 features                  ├── 33 features (base)
├── Standard training            ├── + 3 trajectory features
├── MAE: 3.40                    ├── Recency-weighted training
└── production predictions       └── shadow predictions (logged only)
```

## Monitoring Queries

### Compare V8 vs V9 Predictions
```sql
SELECT system_id,
    COUNT(*) as predictions,
    AVG(ABS(predicted_points - actual_points)) as mae,
    AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-02-01'
  AND system_id IN ('catboost_v8', 'catboost_v9')
GROUP BY 1
```

### Check Feature Store Trajectory Features
```sql
SELECT
    game_date,
    feature_count,
    COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-25'
GROUP BY 1, 2
ORDER BY 1
```

## References

- [V8 Performance Analysis](../catboost-v8-performance-analysis/README.md)
- [Model Degradation Root Cause](../catboost-v8-performance-analysis/MODEL-DEGRADATION-ROOT-CAUSE-ANALYSIS.md)
- [ML Feature Store Processor](../../../../data_processors/precompute/ml_feature_store/ml_feature_store_processor.py)
