# CatBoost V9 Experiment Tracker

**Last Updated**: 2026-01-30

## Active Experiments

| Exp ID | Status | Start Time | Features | Recency | Half-Life | Train Period |
|--------|--------|------------|----------|---------|-----------|--------------|
| A1_V8_BASELINE | Running | Now | 33 | No | - | 2021-11-01 to 2025-12-31 |
| A2_RECENCY_180 | Running | Now | 33 | Yes | 180 days | 2021-11-01 to 2025-12-31 |
| A3_RECENCY_90 | Running | Now | 33 | Yes | 90 days | 2021-11-01 to 2025-12-31 |
| A4_RECENCY_365 | Running | Now | 33 | Yes | 365 days | 2021-11-01 to 2025-12-31 |
| C2_RECENT_2YR | Running | Now | 33 | Yes | 180 days | 2023-10-01 to 2025-12-31 |
| C3_CURRENT_SEASON | Running | Now | 33 | Yes | 90 days | 2024-10-01 to 2025-12-31 |

## Completed Results

| Exp ID | MAE | vs V8 (3.40) | Best Iter | Train Samples | Notes |
|--------|-----|--------------|-----------|---------------|-------|
| | | | | | |

## Experiment Hypotheses

### Recency Weighting
- **H1**: Recency weighting improves MAE by giving recent games more influence
- **H2**: 180-day half-life balances recent vs historical data well
- **H3**: 90-day half-life may overfit to recent trends
- **H4**: 365-day half-life may be too conservative

### Training Period
- **H5**: Recent-only training (2 years) may outperform full history
- **H6**: Current season only may capture latest NBA dynamics best
- **H7**: Full history provides more robust generalization

## Next Steps After Phase 1

1. **Analyze Results**: Compare MAE across all experiments
2. **Select Best Config**: Choose configuration for V9 production
3. **Trajectory Features**: If recency helps, add trajectory features
4. **Shadow Deploy**: Deploy best model in shadow mode
5. **A/B Compare**: Monitor V9 vs V8 for 1-2 weeks

## Model Output Locations

Models saved to: `ml/experiments/results/`

| Exp ID | Model File | Metadata File |
|--------|------------|---------------|
| A1 | catboost_v9_exp_A1_V8_BASELINE_*.cbm | *_metadata.json |
| A2 | catboost_v9_exp_A2_RECENCY_180_*.cbm | *_metadata.json |
| A3 | catboost_v9_exp_A3_RECENCY_90_*.cbm | *_metadata.json |
| A4 | catboost_v9_exp_A4_RECENCY_365_*.cbm | *_metadata.json |
| C2 | catboost_v9_exp_C2_RECENT_2YR_RECENCY_*.cbm | *_metadata.json |
| C3 | catboost_v9_exp_C3_CURRENT_SEASON_*.cbm | *_metadata.json |

## Quick Analysis Queries

### Compare Feature Store Data Availability
```sql
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as records,
    AVG(feature_quality_score) as avg_quality
FROM nba_predictions.ml_feature_store_v2
GROUP BY 1 ORDER BY 1
```

### Training Data Distribution
```sql
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(DISTINCT player_lookup) as players,
    COUNT(*) as games
FROM nba_predictions.ml_feature_store_v2
WHERE feature_count >= 33
GROUP BY 1 ORDER BY 1
```
