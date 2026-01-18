# Prediction System Performance Analysis
**Date:** January 18, 2026
**Analysis Period:** January 1-17, 2026 (17 days of data)
**Total Predictions Analyzed:** 4,547 graded predictions with real betting lines
**Analyst:** Claude Code (Session 108)

---

## Executive Summary

### Key Findings

1. **CatBoost V8 is the clear performance leader**: 4.81 MAE vs Ensemble V1's 5.41 MAE (12.5% better)
2. **Ensemble V1 is underperforming expectations**: Should beat individual systems through complementarity, but currently loses to CatBoost on 51.7% of head-to-head matchups
3. **The ensemble uses outdated components**: Currently combines Moving Average, Zone Matchup, Similarity, and XGBoost V1 - but XGBoost V1 is not in production data
4. **CatBoost V8 shows excellent calibration**: Very high confidence (0.9+) predictions achieve 3.42 MAE with 59.8% win rate
5. **Critical performance degradation in January**: CatBoost MAE increased from 4.16 (Dec) to 4.81 (Jan); Ensemble from 5.07 to 5.41

---

## 1. Overall System Performance (Jan 1-17, 2026)

### Complete Rankings by MAE

| Rank | System | Predictions | MAE | RMSE | Std Dev | Mean Bias | Win Rate | Avg Confidence |
|------|--------|-------------|-----|------|---------|-----------|----------|----------------|
| 1 | **CatBoost V8** | 1,082 | **4.81** | 6.43 | 6.43 | +0.21 | 50.9% | 87.2% |
| 2 | Ensemble V1 | 902 | 5.41 | 6.96 | 6.73 | -1.80 | 39.0% | 74.9% |
| 3 | Similarity Balanced V1 | 759 | 5.45 | 7.02 | 6.94 | -1.07 | 39.0% | 86.8% |
| 4 | Moving Average | 586 | 5.55 | 7.08 | 6.99 | -1.18 | 39.9% | 51.5% |
| 5 | Zone Matchup V1 | 902 | 6.50 | 8.42 | 7.27 | -4.25 | 41.4% | 51.0% |

### Key Observations

- **CatBoost V8 dominates**: 0.60 MAE advantage over 2nd place (12.5% improvement)
- **Ensemble paradox**: Ensemble V1 should theoretically beat all individual systems through diversification, but ranks 2nd
- **Win rate disconnect**: CatBoost has highest win rate (50.9%) while having lowest MAE
- **Bias patterns**: All systems except CatBoost show negative bias (predicting too low)

---

## 2. CatBoost V8 vs Ensemble V1 Deep Dive

### Head-to-Head Performance (596 Same-Game Predictions)

| Metric | CatBoost Wins | Ensemble Wins | Ties |
|--------|---------------|---------------|------|
| **Games** | 281 (47.1%) | 308 (51.7%) | 7 (1.2%) |
| **Avg MAE When Winning** | 3.99 | 4.22 | 4.17 |
| **Avg MAE When Losing** | 6.58 | 7.12 | - |
| **Avg Difference** | -2.59 | +2.90 | 0 |

### Critical Insight: Why Is Ensemble Winning More Often?

The data shows an interesting pattern:
- When **CatBoost wins**, it wins by smaller margins (avg 2.59 error difference)
- When **Ensemble wins**, it wins by larger margins (avg 2.90 error difference)
- This explains why Ensemble wins 51.7% of matchups BUT has worse overall MAE (5.41 vs 4.81)
- **Conclusion**: CatBoost is more consistent; Ensemble is more volatile with occasional huge wins

### System Agreement Analysis (558 Multi-System Predictions)

| Metric | Value |
|--------|-------|
| Avg CatBoost-Ensemble Difference | 3.17 points |
| CatBoost Beats Ensemble | 48.9% |
| CatBoost Beats Similarity | 37.8% |
| Ensemble Beats Similarity | 39.6% |

**Key Finding**: 3.17 point average difference between CatBoost and Ensemble suggests they're looking at different factors - good for diversification, but ensemble weighting may be wrong.

### Recommendation Agreement (352 OVER/UNDER Recommendations)

| Agreement Type | Games | % of Total | Avg CatBoost MAE | Avg Ensemble MAE | Prediction Diff |
|----------------|-------|------------|------------------|------------------|-----------------|
| **AGREE** | 273 | 77.6% | 5.86 | 5.40 | 2.17 |
| **DISAGREE** | 79 | 22.4% | 5.00 | 5.13 | 4.88 |

**Critical Insight**: When systems disagree (22.4% of time), they differ by 4.88 points on average. These are the most valuable cases for ensemble learning - but both systems perform similarly (5.00 vs 5.13 MAE), suggesting ensemble isn't capturing the complementary strength.

---

## 3. Performance by Confidence Tier

### CatBoost V8 Confidence Calibration

| Confidence Tier | Predictions | MAE | Win Rate | Avg Confidence |
|-----------------|-------------|-----|----------|----------------|
| **Very High (0.9+)** | 547 | **3.42** | **59.8%** | 91.7% |
| High (0.8-0.9) | 468 | 6.35 | 42.1% | 87.3% |
| Medium (0.5-0.7) | 67 | 5.50 | 40.3% | 50.0% |

**Analysis**: CatBoost shows excellent calibration. Very high confidence predictions (50.5% of volume) achieve:
- 3.42 MAE (29% better than overall 4.81)
- 59.8% win rate (vs 50.9% overall)
- **Actionable**: Filter for confidence > 0.9 would improve performance significantly

### Ensemble V1 Confidence Calibration

| Confidence Tier | Predictions | MAE | Win Rate | Avg Confidence |
|-----------------|-------------|-----|----------|----------------|
| **Very High (0.9+)** | 15 | **2.15** | **53.3%** | 91.6% |
| High (0.8-0.9) | 366 | 4.97 | 44.8% | 83.8% |
| Med-High (0.7-0.8) | 238 | 5.58 | 43.7% | 74.9% |
| Medium (0.5-0.7) | 272 | 6.01 | 25.7% | 63.3% |
| Low (<0.5) | 11 | 6.07 | 54.5% | 45.8% |

**Analysis**: Ensemble also shows good calibration at very high confidence, but:
- Only 15 predictions at 0.9+ (1.7% of volume) vs CatBoost's 547 (50.5%)
- Most predictions (30.1%) fall in medium confidence tier with poor win rate (25.7%)
- **Actionable**: Ensemble is too conservative with high confidence assignments

---

## 4. OVER vs UNDER Bias Analysis

### CatBoost V8 Directional Performance

| Direction | Predictions | MAE | Mean Bias | Win Rate |
|-----------|-------------|-----|-----------|----------|
| **OVER** | 425 | 5.23 | +2.66 | **58.6%** |
| **UNDER** | 476 | **4.70** | -1.85 | **63.4%** |

**Analysis**:
- CatBoost slightly favors UNDER (52.7% of recommendations)
- UNDER recommendations are more accurate (4.70 vs 5.23 MAE)
- UNDER recommendations win more often (63.4% vs 58.6%)
- Overall bias near zero (+0.21) - well calibrated

### Ensemble V1 Directional Performance

| Direction | Predictions | MAE | Mean Bias | Win Rate |
|-----------|-------------|-----|-----------|----------|
| OVER | 134 | 4.69 | +1.81 | 45.5% |
| **UNDER** | 526 | 5.52 | -2.59 | **55.3%** |

**Analysis**:
- Ensemble heavily favors UNDER (79.7% of recommendations)
- OVER recommendations are more accurate (4.69 vs 5.52 MAE) but less frequent
- Strong negative bias (-1.80 overall) suggests systematic underprediction
- **Actionable**: Ensemble may need bias correction

### System Comparison: OVER Recommendation Rate

| System | OVER Rate | UNDER Rate |
|--------|-----------|------------|
| CatBoost V8 | 39.3% | 60.7% |
| **Ensemble V1** | **14.9%** | **85.1%** |
| Moving Average | 27.6% | 72.4% |
| Similarity Balanced | 23.8% | 76.2% |
| **Zone Matchup V1** | **7.3%** | **92.7%** |

**Critical Finding**: Zone Matchup V1 has extreme UNDER bias (92.7%), which is heavily influencing Ensemble V1's recommendations. This explains ensemble's low OVER rate (14.9%) and negative bias (-1.80).

---

## 5. Performance Trends Over Time

### Weekly Performance (January 2026)

#### CatBoost V8

| Week | Date Range | Predictions | MAE | Win Rate |
|------|------------|-------------|-----|----------|
| Week 0 (Jan 1-3) | Jan 1-3 | 316 | **4.33** | **56.0%** |
| Week 1 (Jan 4-10) | Jan 4-10 | 592 | 4.58 | 52.2% |
| Week 2 (Jan 11-17) | Jan 11-17 | 174 | **6.47** | 37.4% |

#### Ensemble V1

| Week | Date Range | Predictions | MAE | Win Rate |
|------|------------|-------------|-----|----------|
| Week 0 (Jan 1-3) | Jan 1-3 | 316 | 5.11 | 36.7% |
| Week 1 (Jan 4-10) | Jan 4-10 | 312 | 5.40 | 45.2% |
| Week 2 (Jan 11-17) | Jan 11-17 | 274 | 5.78 | 34.7% |

### Monthly Comparison: December 2025 vs January 2026

| System | Period | Predictions | MAE | Change |
|--------|--------|-------------|-----|--------|
| CatBoost V8 | December 2025 | 1,319 | **4.16** | Baseline |
| CatBoost V8 | January 2026 | 1,082 | **4.81** | **+15.6% degradation** |
| Ensemble V1 | December 2025 | 1,351 | 5.07 | Baseline |
| Ensemble V1 | January 2026 | 902 | 5.41 | **+6.7% degradation** |

**Critical Alert**: Both systems show performance degradation in January, with CatBoost degrading faster:
- CatBoost: 4.16 → 4.81 MAE (+0.65, +15.6%)
- Ensemble: 5.07 → 5.41 MAE (+0.34, +6.7%)
- Week 2 (Jan 11-17) particularly bad for CatBoost: 6.47 MAE

**Potential Causes**:
1. Model drift - training data from earlier in season may not match current patterns
2. All-Star break approaching - player load management affecting predictions
3. Trade deadline approaching - team dynamics changing
4. Injury patterns changing

---

## 6. Error Distribution Analysis

### Percentile Performance (January 2026)

| System | P10 | P25 | **Median** | P75 | P90 | P95 | Max |
|--------|-----|-----|------------|-----|-----|-----|-----|
| **CatBoost V8** | 0.7 | 1.7 | **3.8** | 6.8 | 9.9 | 12.8 | 30.3 |
| Similarity Balanced | 1.0 | 2.1 | 4.3 | 7.7 | 11.7 | 13.9 | 28.7 |
| **Ensemble V1** | 0.9 | 2.1 | **4.4** | 7.8 | 11.5 | 13.4 | 27.6 |
| Zone Matchup V1 | 0.8 | 2.3 | 5.2 | 9.4 | 13.9 | 16.6 | 29.0 |

**Analysis**:
- CatBoost has lowest median error (3.8 vs 4.4 for Ensemble)
- CatBoost has tighter error distribution (P90 = 9.9 vs Ensemble's 11.5)
- Both systems have similar maximum errors (~30 points)
- **50% of CatBoost predictions are within 3.8 points** vs 4.4 for Ensemble

---

## 7. System-Specific Deep Dives

### Zone Matchup V1

| Metric | Value |
|--------|-------|
| MAE | 6.50 (worst) |
| Mean Bias | -4.25 (extreme) |
| OVER Rate | 7.3% (extreme UNDER bias) |
| Win Rate | 41.4% |

**Issues**:
- Worst performing system by MAE
- Extreme negative bias pulling ensemble predictions down
- Rarely recommends OVER (only 7.3% of time)
- **Recommendation**: Reduce or remove Zone Matchup from ensemble

### Similarity Balanced V1

| Metric | Value |
|--------|-------|
| MAE | 5.45 (3rd best) |
| Coverage | 759 predictions (84% of Ensemble) |
| Win Rate | 39.0% |
| Avg Confidence | 86.8% |

**Analysis**:
- Competitive with Ensemble (5.45 vs 5.41)
- Good confidence calibration
- Limited coverage compared to other systems
- **Recommendation**: Keep in ensemble, increase weight

### Moving Average

| Metric | Value |
|--------|-------|
| MAE | 5.55 (4th best) |
| Coverage | 586 predictions (65% of Ensemble) |
| Win Rate | 39.9% |
| Avg Confidence | 51.5% (lowest) |

**Analysis**:
- Limited coverage suggests data requirements not always met
- Low average confidence
- Competitive MAE
- **Recommendation**: Keep but with lower weight

---

## 8. Ensemble Effectiveness Analysis

### When Does Ensemble Beat All Individual Systems?

| Outcome | Games | % of Total | Avg Ensemble MAE | Avg CatBoost MAE |
|---------|-------|------------|------------------|------------------|
| CatBoost Better | 273 | **48.9%** | 6.58 | 3.96 |
| Tie/Other Better | 206 | 36.9% | 5.14 | 7.81 |
| **Ensemble Best** | **79** | **14.2%** | **1.52** | **4.38** |

**Critical Finding**: Ensemble only beats all systems in 14.2% of cases, but when it does:
- Achieves exceptional 1.52 MAE (vs normal 5.41)
- Beats CatBoost by 2.86 points on average
- Demonstrates the potential value of ensemble approach

**The Problem**: Current ensemble weighting doesn't maximize these opportunities.

---

## 9. Root Cause Analysis: Why Is Ensemble Underperforming?

### Issue 1: XGBoost V1 Not in Production

The ensemble code shows it expects these 4 systems:
1. Moving Average
2. Zone Matchup V1
3. Similarity Balanced V1
4. **XGBoost V1** ← NOT FOUND in production data

**Evidence**:
- `/home/naji/code/nba-stats-scraper/predictions/worker/prediction_systems/ensemble_v1.py` lines 48-73 show XGBoost V1 is expected
- BigQuery shows only `catboost_v8` in `ml_model_predictions` table
- Ensemble predictions table shows `ensemble_v1` but no sign of XGBoost V1

**Impact**: Ensemble is running with only 3 systems instead of 4, OR it's using an outdated XGBoost V1 that's not being tracked.

### Issue 2: Zone Matchup V1 Dragging Down Performance

Zone Matchup V1 metrics:
- Worst MAE: 6.50 (vs CatBoost's 4.81)
- Extreme negative bias: -4.25
- Only 7.3% OVER recommendations

**Impact on Ensemble**:
- Ensemble has -1.80 mean bias (vs CatBoost's +0.21)
- Ensemble has only 14.9% OVER rate (vs CatBoost's 39.3%)
- Zone Matchup pulls ensemble predictions down systematically

### Issue 3: Equal Confidence Weighting

Current ensemble uses confidence-weighted average:
```python
weighted_sum = sum(p['prediction'] * p['confidence'] for p in predictions)
```

**Problem**: This assumes all systems' confidence scores are equally calibrated, but:
- Zone Matchup avg confidence: 51.0%
- CatBoost avg confidence: 87.2%
- Similarity avg confidence: 86.8%

Zone Matchup has lower confidence BUT still gets 25% vote weight (1 of 4 systems).

### Issue 4: CatBoost V8 Not in Ensemble

**Most Critical Issue**: The best performing system (CatBoost V8, 4.81 MAE) is NOT part of the ensemble that's supposed to combine the best systems.

Ensemble V1 was designed for:
- Moving Average
- Zone Matchup V1
- Similarity Balanced V1
- XGBoost V1 (outdated or missing)

Meanwhile, **CatBoost V8** (the current production model) is running independently and outperforming the ensemble by 12.5%.

---

## 10. Recommendations for Ensemble Retraining

### Immediate Actions (High Priority)

1. **Replace XGBoost V1 with CatBoost V8 in Ensemble**
   - Current: XGBoost V1 (outdated/missing)
   - New: CatBoost V8 (4.81 MAE, proven performance)
   - Expected Impact: -0.3 to -0.5 MAE improvement

2. **Reduce or Remove Zone Matchup V1**
   - Current: Equal weight (~25%)
   - Option A: Reduce to 10% weight
   - Option B: Remove entirely
   - Expected Impact: -0.2 to -0.4 MAE, reduce negative bias

3. **Implement Performance-Based Weighting**
   - Current: Confidence-weighted average
   - New: Inverse MAE weighting with recency bias

   Proposed weights based on Jan 2026 performance:
   ```
   CatBoost V8:         45% (MAE 4.81, best)
   Similarity:          25% (MAE 5.45, complementary)
   Moving Average:      20% (MAE 5.55, momentum signal)
   Zone Matchup:        10% (MAE 6.50, keep for edge cases)
   ```

4. **Add Bias Correction Layer**
   - Adjust for ensemble's -1.80 mean bias
   - Apply +1.5 to +2.0 point correction to final predictions
   - Re-evaluate after removing Zone Matchup influence

### Medium-Term Improvements

5. **Dynamic System Weighting Based on Context**
   - High confidence CatBoost (>0.9): 70% weight
   - High system agreement (variance < 2): Increase all weights equally
   - Low system agreement (variance > 6): Increase CatBoost weight to 60%

6. **Confidence Recalibration**
   - Ensemble currently too conservative (only 1.7% of predictions at 0.9+ confidence)
   - Target: 30-40% of predictions at high confidence when systems agree
   - Use agreement variance as primary confidence signal

7. **Add Confidence Tier Filtering**
   - Only make OVER/UNDER recommendations when:
     - CatBoost confidence > 0.85 OR
     - Ensemble confidence > 0.75 AND system agreement > 80%
   - Pass on medium confidence predictions (0.5-0.7)

### Long-Term Strategy

8. **Train Ensemble V2 Meta-Model**
   - Use historical predictions from all 5 systems as features
   - Learn when each system performs best
   - Train on 2+ years of prediction data
   - Target: Ensemble V2 should beat best individual system by 0.3-0.5 MAE

9. **Add XGBoost V2 or LightGBM V1**
   - Retrain on same data as CatBoost V8
   - Use different hyperparameters for diversity
   - Add to ensemble only if it provides complementary errors

10. **Implement Adaptive Weighting**
    - Track rolling 7-day MAE for each system
    - Adjust weights weekly based on recent performance
    - Automatically reduce weight of degrading systems

---

## 11. Expected Performance Improvements

### Conservative Estimates (Ensemble V1.1 - Quick Fixes)

Implementing recommendations 1-3:

| Metric | Current Ensemble | Projected V1.1 | Improvement |
|--------|------------------|----------------|-------------|
| MAE | 5.41 | 4.9-5.1 | -6 to -9% |
| Win Rate | 39.0% | 43-45% | +4-6 points |
| OVER Rate | 14.9% | 25-30% | More balanced |
| Confidence > 0.9 | 1.7% | 15-20% | Better calibration |

### Optimistic Estimates (Ensemble V2 - Full Retraining)

Implementing all recommendations:

| Metric | Current Ensemble | Projected V2 | Improvement |
|--------|------------------|--------------|-------------|
| MAE | 5.41 | 4.5-4.7 | -13 to -17% |
| Win Rate | 39.0% | 48-52% | +9-13 points |
| Confidence Calibration | Poor | Excellent | High conf = high accuracy |
| Coverage | 902 predictions | 1,000+ | Better coverage |

**Goal**: Ensemble V2 should beat CatBoost V8 (4.81 MAE) by 0.1-0.3 points through complementarity.

---

## 12. Monitoring & Validation Plan

### Pre-Deployment Testing

1. **Backtest on December 2025 data**
   - Simulate new weights on historical predictions
   - Validate MAE improvement
   - Check bias correction

2. **Shadow Mode Deployment**
   - Run Ensemble V1.1 alongside current systems
   - Log predictions but don't use for recommendations
   - Compare performance over 7-14 days

3. **A/B Test Setup**
   - 20% traffic to Ensemble V1.1
   - 80% traffic to current best (CatBoost V8)
   - Monitor for 2 weeks before full rollout

### Post-Deployment Monitoring

4. **Daily Performance Dashboard**
   - Track MAE, win rate, bias by system
   - Alert if any system degrades > 10% over 3 days
   - Weekly system weight adjustment

5. **System Health Checks**
   - Confidence distribution analysis
   - Agreement variance tracking
   - OVER/UNDER balance monitoring

6. **Monthly Retraining Schedule**
   - Re-evaluate system weights based on trailing 30 days
   - Adjust for seasonal patterns (playoffs, All-Star break, etc.)
   - Archive performance metrics for long-term analysis

---

## 13. Data Quality Notes

### Coverage Gaps Identified

| System | Jan Predictions | Coverage % | Note |
|--------|-----------------|------------|------|
| CatBoost V8 | 1,082 | 100% (baseline) | Full coverage |
| Ensemble V1 | 902 | 83% | Missing 180 predictions |
| Zone Matchup V1 | 902 | 83% | Same as Ensemble |
| Similarity | 759 | 70% | Requires historical data |
| Moving Average | 586 | 54% | Requires min games |

**Question**: Why does Ensemble have 180 fewer predictions than CatBoost?
- Possible answer: Ensemble requires minimum 2 systems to predict
- Some games may only have CatBoost predictions available

### Data Freshness

- Latest graded data: January 17, 2026
- Total graded games: 4,547 in Jan 2026
- No missing XGBoost V1 data found - appears to not be in production

---

## 14. Technical Debt & System Architecture Issues

### Identified Issues

1. **Ensemble V1 expects XGBoost V1 but uses unknown model**
   - Code references XGBoost V1 in 4 places
   - No XGBoost V1 data in BigQuery
   - Need to clarify what model ensemble is actually using

2. **CatBoost V8 running independently**
   - Not integrated into ensemble
   - Missing opportunity for complementarity
   - Best performing system not part of "best of all systems" ensemble

3. **System prediction storage inconsistent**
   - `ml_model_predictions` only has CatBoost V8
   - `prediction_accuracy_real_lines` has 5-6 systems
   - Need unified prediction storage

4. **Moving Average Baseline V1 vs Moving Average**
   - Two different systems: `moving_average_baseline_v1` (55k predictions) and `moving_average` (597 predictions)
   - Need to clarify which is current production

### Recommended Architecture Changes

1. Create unified prediction pipeline:
   ```
   Phase 4 (Features) → All Systems → Ensemble V2 → Phase 5 (Output)
   ```

2. Log all system predictions to single table with schema:
   ```
   player_lookup, game_id, system_id, predicted_points,
   confidence, recommendation, metadata, timestamp
   ```

3. Build ensemble as final aggregation layer that runs AFTER all individual systems

---

## Conclusion

### The Bottom Line

1. **CatBoost V8 (4.81 MAE) is significantly better than Ensemble V1 (5.41 MAE)** - a 12.5% gap that should not exist
2. **Ensemble is not using CatBoost V8** - the best system is excluded from the ensemble
3. **Zone Matchup V1 is dragging ensemble down** - worst MAE (6.50), extreme bias (-4.25)
4. **Quick wins available**: Replacing XGBoost V1 with CatBoost V8 and reweighting systems could improve ensemble to 4.9-5.1 MAE
5. **Both systems degrading**: CatBoost up 15.6% from December, Ensemble up 6.7% - model drift likely occurring

### Recommended Next Steps

**Immediate (This Week)**:
1. Clarify which model ensemble is actually using (XGBoost V1 location?)
2. Verify CatBoost V8 is not part of current ensemble
3. Run backtest simulation with proposed weights

**Short-Term (Next 2 Weeks)**:
1. Implement Ensemble V1.1 with CatBoost V8, reduced Zone Matchup weight
2. Add bias correction (+1.5 points)
3. Deploy in shadow mode

**Medium-Term (Next Month)**:
1. Train Ensemble V2 meta-model on historical predictions
2. Implement adaptive weighting
3. Add confidence recalibration

**The Goal**: Create an ensemble that achieves 4.5-4.7 MAE by combining the strengths of all systems, beating CatBoost V8's 4.81 MAE through true complementarity.

---

## Appendix: Raw Query Results

All queries executed against `nba-props-platform.nba_predictions.prediction_accuracy_real_lines` on January 18, 2026.

**Data Characteristics**:
- Date range: January 1-17, 2026 (17 days)
- Total predictions: 4,547 graded with real lines
- Systems analyzed: 5 (CatBoost V8, Ensemble V1, Similarity Balanced V1, Moving Average, Zone Matchup V1)
- XGBoost V1: Not found in production data

**Analysis Confidence**: High - based on comprehensive BigQuery analysis with 13 detailed queries covering performance, trends, agreement, calibration, and error distribution.
