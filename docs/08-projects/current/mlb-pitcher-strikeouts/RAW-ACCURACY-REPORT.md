# MLB Strikeout Predictions - Raw Accuracy Analysis

**Generated**: 2026-01-13 18:38:03
**Analysis Type**: Layer 1 - Raw Prediction Accuracy
**Data Period**: 2024-04-09 to 2025-09-28

---

## Executive Summary

**Verdict**: MARGINAL
**Recommendation**: Forward validation required before betting deployment

### Key Metrics
- **Total Predictions**: 8,345
- **Mean Absolute Error (MAE)**: 1.455
- **Prediction Bias**: +0.016 K (over-predicting)
- **Within 2K**: 72.9%

---

## Overall Accuracy Metrics

| Metric | Value |
|--------|-------|
| Total Predictions | 8,345 |
| MAE | 1.455 ± 1.121 |
| RMSE | 1.836 |
| Bias | +0.016 K |
| Directional Accuracy | 64.4% |
| Within 1K | 41.8% |
| Within 2K | 72.9% |
| Within 3K | 89.8% |
| Avg Predicted | 5.08 K |
| Avg Actual | 5.07 K |

### Interpretation

**MAE Benchmarks**:
- < 1.5: Excellent
- 1.5-2.0: Good
- 2.0-2.5: Marginal
- > 2.5: Poor

**Baseline Comparison**:
- Training MAE: 1.71
- Production MAE: 1.455
- Delta: -0.255

---

## Accuracy by Confidence Tier

| Confidence Tier | Predictions | MAE | Avg Confidence |
|-----------------|-------------|-----|----------------|
| 75-85% | 8,345 | 1.455 | 0.8 |

**Calibration Status**: ⚠️ NOT Calibrated

---

## Accuracy by Context

### Home vs Away

- **Home Games**: 4,189 predictions, MAE 1.46
- **Away Games**: 4,156 predictions, MAE 1.449

### By Season

- **2024**: 3,869 predictions, MAE 1.375
- **2025**: 4,476 predictions, MAE 1.523


---

## Model Verdict

**Overall Assessment**: MARGINAL

**Recommendation**: Forward validation required before betting deployment

**Confidence Level**: MEDIUM

### Issues Detected

- Model confidence scores not well calibrated


---

## Next Steps

Based on this analysis:

1. ⚠️ Forward validation REQUIRED before betting
2. ⚠️ Start with small sample (10-20 predictions)
3. ⚠️ Monitor performance closely
4. ⚠️ Consider model improvements in parallel
5. ⚠️ Make go/no-go decision after 50 predictions


---

**Analysis Script**: `scripts/mlb/historical_odds_backfill/analyze_raw_accuracy.py`
**Data Source**: `mlb_predictions.pitcher_strikeouts` × `mlb_raw.mlb_pitcher_stats`
