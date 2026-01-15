# V1.5 Model Training Notes

**Date**: 2026-01-15
**Model ID**: `mlb_pitcher_strikeouts_v1_5_bp_20260115_074103`

---

## Model Summary

| Metric | Value |
|--------|-------|
| Features | 28 (20 V1 + 8 BettingPros) |
| Training samples | 4,144 |
| Test samples | 889 |
| Test MAE | 1.731 |
| Test Hit Rate | **52.98%** |

---

## Feature Importance

| Rank | Feature | Type | Importance |
|------|---------|------|------------|
| 1 | f40_betting_line | BP | **30.0%** |
| 2 | f41_bp_projection | BP | 4.6% |
| 3 | f45_perf_season_over_pct | BP | 3.1% |
| 4 | f46_combined_signal | BP | 3.1% |
| 5 | f47_over_implied_prob | BP | 3.1% |

**BettingPros features total: 51.6% of importance**

---

## Key Observation

The betting line itself is the #1 feature at 30% importance. This indicates:
1. The market is already efficient
2. Model is largely learning to predict the line, not beat it
3. Edge comes from the other 70% of features

---

## Data Segmentation Research

From NBA ML model V8/V10 comparison:
- **V8 (2.5 seasons)**: 72.5% hit rate - WINNER
- **V10 (4+ seasons)**: 72.2% hit rate - lost

**More data hurt performance** due to:
1. Market efficiency improved over time
2. Distribution shift in game patterns
3. Feature quality degraded in recent data

---

## Recommended Next Steps

1. **Test different training windows**
   - 2024-2025 only (2.5 seasons)
   - Compare to all 4 years (2022-2025)

2. **Investigate hit rate discrepancy**
   - V1 reported 67.27% vs V1.5's 52.98%
   - Different grading methodology?

3. **Focus on high-confidence picks**
   - Filter for `perf_last_5` edge cases
   - Only bet when trend and projection agree

---

## Files

| File | Location |
|------|----------|
| Training script | `scripts/mlb/training/train_pitcher_strikeouts_v1_5.py` |
| Model | `models/mlb/mlb_pitcher_strikeouts_v1_5_bp_20260115_074103.json` |
| Metadata | `models/mlb/mlb_pitcher_strikeouts_v1_5_bp_20260115_074103_metadata.json` |
