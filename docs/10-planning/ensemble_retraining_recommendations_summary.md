# Ensemble Retraining Recommendations - Executive Summary
**Date:** January 18, 2026
**Analysis Period:** Jan 1-17, 2026 (4,547 graded predictions)

---

## The Problem

**Ensemble V1 (5.41 MAE) is 12.5% worse than CatBoost V8 (4.81 MAE)**

This should NOT happen. An ensemble should beat individual systems through complementarity.

---

## Root Causes

### 1. CatBoost V8 NOT in Ensemble
- **Best system (4.81 MAE) is excluded from the ensemble**
- Ensemble uses: Moving Average, Zone Matchup, Similarity, XGBoost V1
- XGBoost V1 appears outdated or missing from production data
- CatBoost V8 runs independently

### 2. Zone Matchup V1 Dragging Performance Down
- Worst MAE: 6.50 (35% worse than CatBoost)
- Extreme negative bias: -4.25 points
- Only 7.3% OVER recommendations (extreme UNDER bias)
- Pulling ensemble to -1.80 bias and 14.9% OVER rate

### 3. Equal Weighting Assumption
- All systems get ~25% weight (1 of 4)
- Doesn't account for performance differences
- Zone Matchup (6.50 MAE) has same influence as Similarity (5.45 MAE)

---

## Current System Performance Rankings

| Rank | System | MAE | Win Rate | OVER Rate | Mean Bias | Confidence |
|------|--------|-----|----------|-----------|-----------|------------|
| 1 | **CatBoost V8** | **4.81** | 50.9% | 39.3% | +0.21 | 87.2% |
| 2 | Ensemble V1 | 5.41 | 39.0% | 14.9% | -1.80 | 74.9% |
| 3 | Similarity | 5.45 | 39.0% | 23.8% | -1.07 | 86.8% |
| 4 | Moving Avg | 5.55 | 39.9% | 27.6% | -1.18 | 51.5% |
| 5 | Zone Matchup | 6.50 | 41.4% | 7.3% | -4.25 | 51.0% |

---

## Key Performance Insights

### CatBoost V8 Excellence
- **3.42 MAE at very high confidence (0.9+)** - 547 predictions (50.5% of volume)
- **59.8% win rate** on high confidence predictions
- Well-calibrated bias (+0.21, nearly neutral)
- **Median error: 3.8 points** (vs Ensemble's 4.4)

### Ensemble V1 Issues
- Only **1.7%** of predictions at very high confidence (vs CatBoost's 50.5%)
- Too conservative with confidence assignment
- **Negative bias (-1.80)** from Zone Matchup influence
- Wins 51.7% of head-to-head matchups vs CatBoost, but with higher variance

### System Agreement
- CatBoost and Ensemble differ by **3.17 points** on average
- When they **disagree** on OVER/UNDER (22.4% of time), predictions differ by **4.88 points**
- Ensemble only beats ALL systems in **14.2% of cases** (but achieves 1.52 MAE when it does!)

---

## Performance Degradation Alert

**Both systems degrading in January 2026**:

| System | December 2025 | January 2026 | Change |
|--------|---------------|--------------|--------|
| CatBoost V8 | 4.16 MAE | 4.81 MAE | **+15.6%** |
| Ensemble V1 | 5.07 MAE | 5.41 MAE | **+6.7%** |

Week 2 (Jan 11-17) particularly bad:
- CatBoost: 6.47 MAE (37.4% win rate)
- Ensemble: 5.78 MAE (34.7% win rate)

**Likely causes**: Model drift, All-Star break load management, trade deadline uncertainty

---

## Recommended Ensemble Weights

### Current (Assumed Equal Weighting)
```
Moving Average:    25%
Zone Matchup:      25%
Similarity:        25%
XGBoost V1:        25%
```

### Proposed V1.1 (Performance-Based)
```
CatBoost V8:       45%  (NEW - best system)
Similarity:        25%  (good complementarity)
Moving Average:    20%  (momentum signal)
Zone Matchup:      10%  (REDUCED - poor performance)
```

### Proposed V2 (Adaptive Context-Aware)
```
DEFAULT:
  CatBoost V8:     45%
  Similarity:      25%
  Moving Avg:      20%
  Zone Matchup:    10%

WHEN CatBoost confidence > 0.9:
  CatBoost V8:     70%
  Similarity:      15%
  Moving Avg:      10%
  Zone Matchup:     5%

WHEN high system agreement (variance < 2.0):
  Equal boost to all weights (normalize to 100%)

WHEN low system agreement (variance > 6.0):
  CatBoost V8:     60%
  Others:          40% distributed
```

---

## Implementation Roadmap

### Phase 1: Quick Wins (1 Week)
**Target: Ensemble MAE 4.9-5.1 (from 5.41)**

1. Add CatBoost V8 to ensemble
2. Reduce Zone Matchup weight to 10%
3. Apply bias correction (+1.5 points)
4. Backtest on December data

**Expected Impact**: -6 to -9% MAE improvement

### Phase 2: Reweighting (2 Weeks)
**Target: Ensemble MAE 4.7-4.9**

1. Implement performance-based weights
2. Add confidence recalibration
3. Shadow mode deployment (7 days)
4. A/B test (20% traffic, 7 days)

**Expected Impact**: -11 to -13% MAE improvement

### Phase 3: Full Ensemble V2 (1 Month)
**Target: Ensemble MAE 4.5-4.7 (beat CatBoost V8)**

1. Train meta-model on 2+ years of predictions
2. Learn context-specific system strengths
3. Adaptive weighting based on rolling 7-day performance
4. Auto-detect and respond to model drift

**Expected Impact**: -13 to -17% MAE improvement, beat CatBoost by 0.1-0.3

---

## Immediate Action Items

### This Week
- [ ] Verify XGBoost V1 location (appears missing from production)
- [ ] Confirm CatBoost V8 not currently in ensemble
- [ ] Run backtest simulation with proposed weights on Dec 2025 data
- [ ] Calculate expected MAE improvement

### Next 2 Weeks
- [ ] Implement Ensemble V1.1 code changes
- [ ] Add CatBoost V8 to ensemble pipeline
- [ ] Reduce Zone Matchup weight to 10%
- [ ] Add bias correction layer (+1.5 points)
- [ ] Deploy in shadow mode (log only, don't use)

### Next Month
- [ ] Compare shadow mode performance vs production
- [ ] If successful, deploy to 20% traffic (A/B test)
- [ ] Monitor daily MAE, win rate, bias
- [ ] Begin Ensemble V2 meta-model training

---

## Success Metrics

### Ensemble V1.1 (Quick Fixes)
- MAE: < 5.1 (currently 5.41)
- Win Rate: > 43% (currently 39.0%)
- OVER Rate: 25-30% (currently 14.9%)
- Bias: -0.5 to +0.5 (currently -1.80)
- High Confidence %: > 15% (currently 1.7%)

### Ensemble V2 (Full Retrain)
- **MAE: < 4.7** (beat CatBoost V8's 4.81)
- Win Rate: > 48%
- OVER Rate: 35-40% (balanced)
- Bias: ±0.2 (well calibrated)
- High Confidence %: > 30%
- **Complementarity**: Beat best individual system 60%+ of time

---

## Risk Mitigation

### Risks
1. **Overfitting to January data**: Only 17 days analyzed
2. **CatBoost V8 also degrading**: Up 15.6% from December
3. **Model drift**: All systems may need retraining, not just reweighting
4. **Integration complexity**: Adding CatBoost to ensemble may have technical challenges

### Mitigations
1. Backtest on multiple months (Nov-Dec 2025)
2. Shadow mode deployment before production
3. A/B test with small traffic percentage
4. Daily monitoring with auto-rollback if performance degrades
5. Keep current ensemble as fallback

---

## Expected Outcome

**Conservative Case** (Ensemble V1.1):
- MAE improves from 5.41 to 4.9-5.1
- Win rate increases from 39% to 43-45%
- Better balanced OVER/UNDER recommendations
- Still trails CatBoost V8 slightly

**Optimistic Case** (Ensemble V2):
- MAE improves from 5.41 to 4.5-4.7
- **Beats CatBoost V8 (4.81) by 0.1-0.3 points**
- Win rate increases to 48-52%
- Achieves true ensemble advantage through complementarity
- Becomes production default prediction system

---

## Questions to Resolve

1. **Where is XGBoost V1?** Code references it but not found in BigQuery
2. **Why isn't CatBoost V8 in ensemble?** Best system excluded
3. **What changed in January?** Both systems degraded significantly
4. **Is reweighting enough?** Or do models need full retraining?
5. **Coverage gap**: Why does Ensemble have 180 fewer predictions than CatBoost?

---

## Next Session Priorities

1. Investigate XGBoost V1 mystery
2. Backtest proposed weights on historical data
3. Implement Ensemble V1.1 code changes
4. Set up shadow mode deployment
5. Create performance monitoring dashboard

**Goal**: Deploy improved ensemble within 2 weeks, beating current 5.41 MAE baseline.
