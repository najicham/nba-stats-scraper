# Prediction Accuracy vs Confidence Analysis
**Date**: 2026-01-16
**Analysis Period**: Jan 1-15, 2026
**Focus**: Did predictions degrade or just confidence shift?

---

## Executive Summary

**CRITICAL FINDING**: Both accuracy AND confidence degraded significantly. This is NOT just a confidence recalibration - the predictions themselves got worse.

### Key Metrics Comparison

| Metric | Jan 1-7 | Jan 8-15 | Change |
|--------|---------|----------|--------|
| **Win Rate** | 54.3% | 47.0% | **-7.3pp** |
| **Avg Confidence** | 90.0% | 59.6% | **-30.4pp** |
| **Avg Absolute Error** | 4.22 pts | 6.43 pts | **+52.5%** |
| **Prediction StdDev** | 5.54 | 8.33 | **+50.4%** |
| **Total Picks** | 842 | 783 | -7.0% |

**Verdict**: This is a DUAL degradation - predictions became both less accurate AND less confident.

---

## 1. Prediction Accuracy Analysis

### Absolute Error Comparison
- **Jan 1-7**: 4.22 points average error
- **Jan 8-15**: 6.43 points average error
- **Increase**: +2.21 points (+52.5%)

**Interpretation**: Predictions are missing actual outcomes by 52% more than before. This is a substantial accuracy degradation.

### Win Rate Comparison
- **Jan 1-7**: 54.3% correct predictions
- **Jan 8-15**: 47.0% correct predictions
- **Decline**: -7.3 percentage points

**Interpretation**: The system went from beating the coin flip to performing worse than random. Below 50% suggests systematic directional bias.

### Prediction Variance
- **Jan 1-7**: StdDev = 5.54 points
- **Jan 8-15**: StdDev = 8.33 points
- **Increase**: +50.4%

**Interpretation**: Predictions became much more erratic and unpredictable. Higher variance indicates less stability in the model.

---

## 2. Confidence Distribution Analysis

### Healthy Period (Dec 20 - Jan 7)
Confidence levels were tightly clustered in high-confidence range:

| Confidence | Picks | Actual Win Rate |
|------------|-------|-----------------|
| 95% | 237 | 51.9% |
| 92% | 781 | 58.1% |
| 90% | 566 | 64.3% |
| 89% | 113 | 43.4% |
| 87% | 401 | 56.1% |
| 84% | 63 | 41.3% |

**Pattern**: Most picks (2,161 total) were at 84-95% confidence.

### After Change (Jan 8-15)
Confidence collapsed to much lower levels:

| Confidence | Picks | Actual Win Rate |
|------------|-------|-----------------|
| 89% | 139 | 34.5% |
| 84% | 62 | 43.5% |
| 50% | 582 | 50.3% |

**Pattern**:
- Only 201 picks remained in high-confidence range (84-89%)
- 582 picks (74% of total) dropped to exactly 50% confidence
- High-confidence picks in Jan 8-15 actually performed WORSE (34.5% at 89% confidence)

---

## 3. Confidence Calibration Analysis

### Question: Are stated confidence levels accurate?

A well-calibrated model should have:
- 90% confident picks → 90% win rate
- 50% confident picks → 50% win rate

### Jan 1-7 Calibration

| Stated Confidence | Actual Win Rate | Calibration Error |
|-------------------|-----------------|-------------------|
| 95% | 53.7% | **-41.3pp** (over-confident) |
| 92% | 57.8% | **-34.2pp** (over-confident) |
| 90% | 64.7% | **-25.3pp** (over-confident) |
| 89% | 53.5% | **-35.5pp** (over-confident) |
| 87% | 44.1% | **-42.9pp** (over-confident) |
| 84% | 32.3% | **-51.7pp** (over-confident) |

**Finding**: System was massively over-confident. Picks stated at 90%+ were actually winning ~50-65% of the time.

### Jan 8-15 Calibration

| Stated Confidence | Actual Win Rate | Calibration Error |
|-------------------|-----------------|-------------------|
| 89% | 34.5% | **-54.5pp** (over-confident) |
| 84% | 43.5% | **-40.5pp** (over-confident) |
| 50% | 50.3% | **+0.3pp** (WELL CALIBRATED!) |

**Finding**:
- High-confidence picks (89%, 84%) became EVEN MORE over-confident and performed WORSE
- 50% confidence picks are perfectly calibrated
- Most picks moved to 50% confidence (default/uncertain state)

---

## 4. Cross-System Comparison

Did all systems degrade or just CatBoost V8?

### Win Rate Changes (Jan 1-7 → Jan 8-15)

| System | Jan 1-7 Win Rate | Jan 8-15 Win Rate | Change |
|--------|------------------|-------------------|--------|
| **catboost_v8** | 54.3% | 47.0% | **-7.3pp** |
| ensemble_v1 | 41.8% | 46.6% | +4.8pp |
| moving_average | 44.9% | 48.3% | +3.4pp |
| similarity_balanced_v1 | 40.1% | 46.0% | +5.9pp |
| zone_matchup_v1 | 42.1% | 49.2% | +7.1pp |

**CRITICAL**: CatBoost V8 is the ONLY system that got worse. All other systems improved!

### Confidence Changes

| System | Jan 1-7 Avg Conf | Jan 8-15 Avg Conf | Change |
|--------|------------------|-------------------|--------|
| **catboost_v8** | 90.0% | 59.6% | **-30.4pp** |
| ensemble_v1 | 77.4% | 69.8% | -7.6pp |
| similarity_balanced_v1 | 87.2% | 87.0% | -0.2pp |
| moving_average | 52.0% | 51.3% | -0.7pp |
| zone_matchup_v1 | 51.0% | 51.3% | +0.3pp |

**CRITICAL**: CatBoost V8 had a MASSIVE 30pp confidence drop. Other systems were relatively stable.

### Accuracy Changes (Avg Absolute Error)

| System | Jan 1-7 Error | Jan 8-15 Error | Change |
|--------|---------------|----------------|--------|
| **catboost_v8** | 4.22 pts | 6.43 pts | **+52.5%** |
| ensemble_v1 | 5.11 pts | 6.06 pts | +18.6% |
| moving_average | 5.12 pts | 5.95 pts | +16.2% |
| similarity_balanced_v1 | 5.25 pts | 6.14 pts | +16.9% |
| zone_matchup_v1 | 6.15 pts | 6.60 pts | +7.3% |

**Pattern**: All systems got slightly worse (likely due to harder games), but CatBoost V8's degradation was **3x worse** than other systems.

---

## 5. Key Findings

### Finding 1: Dual Degradation
- Accuracy degraded: +52.5% error, -7.3pp win rate
- Confidence degraded: -30.4pp average confidence
- **This is NOT a calibration fix - both got worse**

### Finding 2: CatBoost V8 is Isolated
- Only CatBoost V8 degraded; all other systems improved
- CatBoost V8's confidence drop was 4-40x larger than other systems
- CatBoost V8's accuracy drop was 3x larger than other systems

### Finding 3: Previous Over-Confidence
- Jan 1-7: System was 25-52pp over-confident across all tiers
- 95% confident picks were only winning 52% of the time
- This suggests the model was "broken" before but in a different way

### Finding 4: 50% Confidence is Default State
- 74% of Jan 8-15 picks have exactly 50% confidence
- These picks are perfectly calibrated (50.3% win rate)
- Suggests the system is "giving up" and defaulting to uncertain

### Finding 5: High-Confidence Picks Got Worse
- Jan 1-7: 89% confident picks → 53.5% actual
- Jan 8-15: 89% confident picks → 34.5% actual
- **High-confidence picks degraded by 19pp in actual performance**

---

## 6. Root Cause Hypotheses

Based on the data, the most likely explanations are:

### Hypothesis 1: Input Data Change (MOST LIKELY)
**Evidence**:
- Sudden, sharp degradation starting Jan 8
- Isolated to CatBoost V8 only
- Other systems unaffected or improved
- Massive confidence collapse suggests missing/corrupted features

**Possible causes**:
- Advanced stats stopped being ingested (Jan 8 change?)
- Feature engineering pipeline broke
- Data quality issue in training data
- Roster/injury data missing

### Hypothesis 2: Model Deployment Issue
**Evidence**:
- Timing coincides with potential deployment
- Confidence collapse to 50% (default state)
- System-specific issue

**Possible causes**:
- Wrong model weights loaded
- Feature normalization broken
- Model versioning error

### Hypothesis 3: Training Data Contamination
**Evidence**:
- Jan 1-7 was over-confident (25-52pp calibration error)
- Jan 8-15 high-confidence picks perform even worse

**Possible causes**:
- Training data included future-looking features
- Data leakage was fixed, exposing true performance
- Model was overfitted to contaminated data

---

## 7. Recommended Actions

### Immediate (Next 2 Hours)
1. **Audit CatBoost V8 input features for Jan 8-15**
   - Compare feature values Jan 7 vs Jan 8
   - Check for NULL/missing values spike
   - Verify advanced stats are still flowing

2. **Verify Model Deployment**
   - Confirm correct model weights are loaded
   - Check feature preprocessing pipeline
   - Validate feature normalization parameters

3. **Disable CatBoost V8 high-confidence picks**
   - 89% confidence picks are only 34.5% accurate
   - These are actively harmful
   - Fall back to 50% confidence picks only

### Short-term (Next 24 Hours)
4. **Retrain calibration layer**
   - Current confidence scores are meaningless
   - Recalibrate using Dec-Jan actual performance
   - Consider Platt scaling or isotonic regression

5. **Compare Jan 1-7 vs Dec data**
   - Was Jan 1-7 also degraded compared to December?
   - Check if over-confidence existed earlier
   - Determine baseline "healthy" period

6. **Audit training data for leakage**
   - Jan 1-7 over-confidence suggests data issues
   - Check for future-looking features
   - Validate time-series splits

### Medium-term (Next Week)
7. **Implement ensemble fallback**
   - CatBoost V8 is unreliable
   - Ensemble_v1 and zone_matchup_v1 improved
   - Use weighted ensemble when CatBoost confidence < 70%

8. **Add monitoring alerts**
   - Confidence distribution shifts
   - Accuracy degradation vs baseline
   - Feature value anomalies

9. **Root cause investigation**
   - Deep dive into Jan 8 data pipeline changes
   - Review deployment logs
   - Interview team about any changes

---

## 8. Conclusion

**Question**: Are predictions still accurate but just less confident?

**Answer**: NO. Both accuracy AND confidence degraded severely.

**Key Metrics**:
- Accuracy: +52.5% error increase
- Win Rate: -7.3pp (below random)
- Confidence: -30.4pp average drop
- Isolation: Only CatBoost V8 affected

**Root Cause**: Most likely input data change or model deployment issue starting Jan 8.

**Critical Risk**: High-confidence picks (89%) are only 34.5% accurate - these are actively hurting performance.

**Recommendation**: Disable CatBoost V8 immediately until root cause is identified and fixed. The system is currently worse than random chance and providing dangerously wrong confidence signals.
