# Deep Investigation: Model Performance Degradation Root Cause Analysis

**Date:** 2026-01-30
**Status:** 🔴 CRITICAL BUG FOUND + Multiple Issues Identified

---

## Executive Summary

After comprehensive investigation using 6 parallel analysis agents, we found:

| Finding | Severity | Impact |
|---------|----------|--------|
| **Fatigue Score Bug** | 🔴 CRITICAL | All fatigue scores stored as 0 since Jan 25 |
| Calibration Issues | 🟡 HIGH | Model over-predicts high scorers by 6.86 pts |
| Breakout Player Detection | 🟡 HIGH | Rising players under-predicted by 11+ pts |
| Vegas NOT Sharper | ℹ️ INFO | Vegas MAE flat at 5.15, we got worse |
| NBA Scoring Normal | ℹ️ INFO | January is normal, December was anomaly |

**Root Cause:** Multiple compounding issues, but the **fatigue score bug** introduced Jan 25 is critical and needs immediate fix.

---

## Finding 1: CRITICAL BUG - Fatigue Score Calculation

### The Bug

A bug introduced on **January 25, 2026** causes all fatigue scores to be stored as **0 or near-zero** instead of the correct 0-100 range.

**Location:** `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Problem:**
```python
# Line storing fatigue score
'fatigue_score': int(factor_scores['fatigue_score']),  # Returns -5 to 0 adjustment, NOT 0-100 score
```

The `calculate()` method in `fatigue_factor.py` returns an **adjustment value** (-5.0 to 0.0), but the processor expects a **raw score** (0-100). Converting to int gives 0 for most values.

### Evidence

| Week | Avg Fatigue Score | Production Ready % |
|------|-------------------|-------------------|
| 2026-01-18 | **95.29** | 88% |
| 2026-01-25 | **-0.07** | 42% |

The fatigue score collapsed from ~95 to near-zero on Jan 25.

### Impact

- Model receives **incorrect fatigue information** (all zeros)
- Well-rested players treated same as fatigued players
- Feature quality degradation cascades to predictions
- **This aligns with model performance drop in late January**

### Fix Required

```python
# Change from:
'fatigue_score': int(factor_scores['fatigue_score']),

# To:
'fatigue_score': int(factor_contexts['fatigue_context_json']['final_score']),
```

### Backfill Needed

Reprocess `player_composite_factors` and `ml_feature_store_v2` for dates >= 2026-01-25.

---

## Finding 2: Vegas Lines Did NOT Get Sharper

### Monthly Vegas MAE (Last 3 Months)

| Month | Vegas MAE | Our MAE | Gap |
|-------|-----------|---------|-----|
| Nov 2025 | 5.15 | 5.59 | +0.44 |
| Dec 2025 | 5.17 | 5.48 | +0.31 |
| Jan 2026 | 5.15 | 5.59 | +0.44 |

**Vegas accuracy is FLAT at 5.15-5.17 MAE.** No sharpening trend.

### Historical Trend

| Season | Vegas MAE | Our MAE | Gap |
|--------|-----------|---------|-----|
| 2021-22 | 5.03 | 5.13 | +0.10 |
| 2022-23 | 5.08 | 5.23 | +0.15 |
| 2023-24 | 4.95 | 5.20 | +0.25 |
| 2024-25 | 4.90 | 5.14 | +0.24 |
| **2025-26** | **5.15** | **5.59** | **+0.44** |

**Our gap nearly DOUBLED this season** while Vegas actually got slightly WORSE (5.15 vs 4.90).

### Conclusion

**This is NOT Vegas getting sharper - our model degraded.**

---

## Finding 3: Our Model's Absolute Accuracy Degraded

### Weekly MAE Trend

| Week | Our MAE | Bias | Change |
|------|---------|------|--------|
| Dec 21 | **4.11** | -0.50 | Baseline |
| Dec 28 | **4.43** | -0.32 | +8% |
| Jan 04 | **4.55** | +0.24 | +11% |
| Jan 11 | **6.02** | +0.21 | +46% |
| Jan 25 | **5.66** | +0.30 | +38% |

**Our MAE increased from 4.1 to 5.7 - a 38% degradation in absolute accuracy.**

### By Player Tier

| Tier | Dec MAE | Jan MAE | Change |
|------|---------|---------|--------|
| Stars (20+ ppg) | 5.38 | **9.19** | +71% worse |
| Bench (<6 ppg) | 2.91 | 3.21 | +10% worse |

**Star player accuracy degraded 7x more than bench players.**

---

## Finding 4: NBA Scoring Patterns Are Normal

### January Is Normal, December Was Anomaly

| Month | Avg Team Points | Avg Pace |
|-------|-----------------|----------|
| Dec 2025 | **116.7** | 101.9 |
| Jan 2026 | **113.0** | 100.4 |
| Historical Jan Avg | 113.5 | 100.5 |

January 2026 (113.0 ppg) matches historical January averages perfectly. **December 2025 was unusually high.**

### Implication

The NBA didn't change - if our model was calibrated for December's high-scoring environment, it would struggle in a normal January.

---

## Finding 5: Severe Calibration Issues

### Calibration by Prediction Range

| Predicted Range | Avg Predicted | Avg Actual | Error |
|-----------------|---------------|------------|-------|
| 0-10 pts | 6.57 | 7.60 | **+1.03** (under-predict) |
| 10-15 pts | 12.26 | 12.15 | -0.11 |
| 15-20 pts | 17.22 | 15.99 | -1.23 |
| 20-25 pts | 22.18 | 19.33 | **-2.86** |
| 25-30 pts | 27.16 | 23.52 | **-3.64** |
| 30+ pts | 32.90 | 26.04 | **-6.86** |

**Classic regression-to-mean miscalibration:**
- Low predictions under-predict actual
- High predictions over-predict actual by up to 6.86 points

### Calibration Slope

- **Actual slope: 0.75** (ideal = 1.0)
- For every 1-point prediction increase, actual only increases 0.75 points
- Model needs ~25% shrinkage toward mean

### Shocking Finding: Vegas Line Alone Beats Our Model

| Method | MAE |
|--------|-----|
| Our Model | 5.43 |
| 50% Model / 50% Line | 5.06 |
| **Vegas Line Only** | **5.03** |

Simply using the Vegas line produces better point predictions than our model.

---

## Finding 6: Breakout Players Are Worst Cases

### Top Under-Predicted Players (January 2026)

| Player | Games | Avg Predicted | Avg Actual | Under-Prediction |
|--------|-------|---------------|------------|------------------|
| Brice Sensabaugh | 6 | 16.1 | 27.2 | **+11.1** |
| Julius Randle | 5 | 19.4 | 28.8 | **+9.4** |
| Keyonte George | 6 | 20.5 | 29.3 | **+8.9** |
| DeMar DeRozan | 7 | 18.6 | 26.1 | **+7.6** |
| Donovan Mitchell | 6 | 24.8 | 31.5 | **+6.7** |

### Pattern: Rising Players

The model struggles most with players whose baseline it hasn't updated:
- **Brice Sensabaugh**: Went from 7.75 ppg (Dec 2024) to 19.64 ppg (Jan 2026)
- **Keyonte George**: Second-year breakout, averaging 23.1 ppg vs last year's 15-17 ppg
- **Shaedon Sharpe**: Post-injury return with expanded role

**The model anchors too heavily on historical averages.**

---

## Finding 7: Data Quality Degradation

### Upstream Data Issues Growing

| Metric | Nov 2025 | Jan 25 Week |
|--------|----------|-------------|
| upstream_player_daily_cache_incomplete | 59 | **729** |
| upstream_player_composite_factors_incomplete | 4 | **1,325** |
| upstream_player_shot_zone_incomplete | 68 | **753** |

### Quality Tier Degradation

| Tier | Dec 2025 | Jan 2026 |
|------|----------|----------|
| Gold | Present | **Gone** |
| Silver | 35% | 57% |
| Bronze | 15% | **43%** |
| Production Ready | 49% | **23%** |

---

## Root Cause Summary

The model degradation is caused by **multiple compounding factors**:

| Factor | Contribution | Evidence |
|--------|--------------|----------|
| **Fatigue Score Bug** | 🔴 HIGH | All fatigue = 0 since Jan 25 |
| Calibration Drift | 🟡 MEDIUM | Slope = 0.75, should be 1.0 |
| Breakout Detection | 🟡 MEDIUM | Rising players under-predicted 8-11 pts |
| Data Quality | 🟡 MEDIUM | Production ready dropped 49% → 23% |
| December Anomaly | 🟢 LOW | Model may have over-fit to high Dec scoring |

---

## Recommended Actions

### Immediate (Today)

1. **Fix Fatigue Score Bug**
   - File: `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
   - Change to use `factor_contexts['fatigue_context_json']['final_score']`

2. **Backfill Affected Data**
   - Reprocess player_composite_factors for dates >= 2026-01-25
   - Reprocess ml_feature_store_v2 for same dates

### Short-Term (This Week)

3. **Add Calibration Post-Processing**
   - Apply shrinkage: `calibrated = mean + 0.75 * (raw - mean)`
   - Or blend with line: `calibrated = 0.7 * model + 0.3 * line`

4. **Fix Data Quality Issues**
   - Investigate upstream incomplete data
   - Restore gold-tier data generation

### Medium-Term (2-4 Weeks)

5. **Add Breakout Detection Features**
   - Rolling trend indicators (pts_slope_10g)
   - Flag players exceeding seasonal average significantly

6. **Recalibrate Confidence Scores**
   - Current confidence (0.8-1.0) is meaningless
   - Map to actual accuracy by edge size

---

## Validation Queries

### Check Fatigue Score Fix
```sql
SELECT
  game_date,
  AVG(fatigue_score) as avg_fatigue,
  COUNTIF(fatigue_score = 0) as zero_count,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-20'
GROUP BY 1
ORDER BY 1;
```

### Check Model MAE After Fix
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-20'
GROUP BY 1
ORDER BY 1;
```

---

---

## RESOLUTION: Bug Fixed

### Fix Applied

**Commit:** `cec08a99`

**Changes:**
```python
# Before (broken):
fatigue_score = int(factor_scores['fatigue_score'])  # Returns -5 to 0 adjustment
'fatigue_score': int(factor_scores['fatigue_score']),  # Stored 0, -1, -2, etc.

# After (fixed):
fatigue_score = factor_contexts['fatigue_context_json']['final_score']  # Returns 0-100
'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],  # Stores 0-100
```

### Next Steps

1. **Deploy Phase 4 Processor**
   ```bash
   ./bin/deploy-service.sh nba-phase4-precompute-processors
   ```

2. **Backfill Affected Data (Jan 25-30)**
   - Reprocess player_composite_factors for dates >= 2026-01-25
   - Then reprocess ml_feature_store_v2 for same dates

3. **Verify Fix**
   ```sql
   SELECT game_date, AVG(fatigue_score) as avg_fatigue
   FROM nba_precompute.player_composite_factors
   WHERE game_date >= '2026-01-25'
   GROUP BY 1 ORDER BY 1;
   ```
   Expected: avg_fatigue ~90-100 (not 0 or negative)

---

*Investigation completed 2026-01-30 Session 44*
*Critical fatigue score bug identified and FIXED (commit cec08a99)*
