# CatBoost V8 Performance Regression Analysis

**Date:** 2026-01-29
**Status:** CRITICAL ISSUE IDENTIFIED
**Author:** Claude Opus 4.5

## Executive Summary

CatBoost V8 has experienced a severe performance regression starting around Jan 18, 2026. MAE nearly doubled and the model is making unrealistic extreme predictions (60+ points).

## Performance Comparison

### Before vs After Jan 17

| Period | MAE | Win Rate | Bias | Extreme Predictions (≥50 pts) |
|--------|-----|----------|------|-------------------------------|
| Jan 1-17 | 4.99 | 60.8% | +0.17 | **0** (0%) |
| Jan 18-28 | 9.07 | 51.3% | +5.85 | **24** (2.5%) |

### The Problem

The model is predicting absurdly high point totals:
- Anthony Edwards: Predicted **60 points**, actual 20 (40 point error)
- Shai Gilgeous-Alexander: Predicted **60 points**, actual 24 (36 point error)
- Immanuel Quickley: Predicted **41.6 points**, actual 7 (34.6 point error)

### Prediction Distribution (Jan 20-28)

| Range | Count | Avg Error | Avg Actual |
|-------|-------|-----------|------------|
| 50+ pts | 23 | 30.33 | 24.4 |
| 40-50 pts | 81 | 21.35 | 22.0 |
| 30-40 pts | 104 | 15.09 | 20.1 |
| 20-30 pts | 196 | 9.53 | 15.3 |
| 10-20 pts | 174 | 6.15 | 12.6 |
| <10 pts | 326 | 4.07 | 7.3 |

The low-end predictions (<10 pts, MAE 4.07) are still accurate. The problem is extreme over-predictions.

## OVER vs UNDER Breakdown

| Direction | Picks | MAE | Avg Predicted | Avg Actual | Bias |
|-----------|-------|-----|---------------|------------|------|
| OVER | 967 | 9.5 | 24.0 | 16.0 | **+8.03** |
| UNDER | 934 | 4.48 | 8.5 | 10.7 | -2.17 |

OVER predictions have +8 point bias (predicting 24 when actual is 16).

## Comparison with Other Systems

| System | MAE | Win Rate | Status |
|--------|-----|----------|--------|
| ensemble_v1_1 | 4.39 | 56.0% | **BEST** |
| xgboost_v1 | 4.92 | 55.2% | Good |
| ensemble_v1 | 4.93 | 53.1% | Good |
| moving_average | 5.07 | 51.9% | OK |
| catboost_v8 | **7.03** | 56.0% | **BROKEN** |

CatBoost V8 has the worst MAE despite being the "champion" model.

## Timeline Analysis

### When Did It Start?

| Date | Avg Predicted | Avg Line | Ratio | Extreme (40+) |
|------|---------------|----------|-------|---------------|
| Jan 1-7 | 12-13 pts | 13 pts | ~1.0 | 0 |
| Jan 9-11 | 15-16 pts | 13-14 pts | 1.0-1.05 | 1-9 |
| Jan 19+ | 17-19 pts | 13 pts | **1.15-1.32** | **7-13** |

**The issue began gradually around Jan 9 and accelerated after Jan 19.**

### Most Affected Players

High-usage star players are getting wildly inflated predictions:

| Player | Extreme Preds | Avg Predicted | Avg Line | Over-prediction |
|--------|---------------|---------------|----------|-----------------|
| SGA | 13 | 44.4 | 30.8 | +14 pts |
| Anthony Edwards | 5 | 55.2 | 30.1 | **+25 pts** |
| Julius Randle | 4 | 45.3 | 22.5 | **+23 pts** |
| Kawhi Leonard | 4 | 47.9 | 23.5 | +24 pts |

## Root Cause Hypothesis

Possible causes to investigate:
1. **Model file corruption** - wrong model version loaded?
2. **Feature engineering bug** - features being calculated incorrectly?
3. **Data pipeline issue** - wrong data being fed to the model?
4. **Pre-processing change** - normalization or scaling changed?
5. **Cache issue** - stale cached features?
6. **Feature drift** - model trained on different feature distribution?

## Investigation Steps

### 1. Check Model Version
```bash
# Check which model file is being used
grep -r "catboost" predictions/worker/*.py | grep -i "model\|load"
```

### 2. Check Feature Values
```sql
-- Compare feature values between good and bad periods
SELECT
  game_date,
  AVG(feature_points_avg_last_5) as avg_points_feature,
  AVG(feature_minutes_avg_last_5) as avg_minutes_feature
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-15'
GROUP BY game_date
ORDER BY game_date
```

### 3. Check Prediction Worker Logs
```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" textPayload:"catboost"' \
  --limit=50 --freshness=7d
```

## Immediate Recommendations

1. **Consider disabling CatBoost V8** until root cause is found
2. **Use ensemble_v1_1** as primary system (best current performance)
3. **Investigate the Jan 17-18 timeframe** for code/data changes

## Related Documentation

- Performance Analysis Guide: `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`
- Model deployment: `docs/08-projects/current/ml-model-v8-deployment/`

---

*Analysis Date: 2026-01-29*
