# Investigation Findings - Phase 4 Grading Analysis (CORRECTED)

**Investigation Date:** 2026-01-17
**Data Period:** January 1-15, 2026 (15 days, 9,238 predictions after deduplication)
**Status:** ✅ Duplicate fix complete, findings corrected with clean data

---

## 🚨 CRITICAL UPDATE: Duplicate Predictions Fixed

**Major Data Quality Issue Discovered and Resolved:**

- **Original dataset:** 11,554 predictions
- **After deduplication:** 9,238 predictions
- **Duplicates removed:** 2,316 (20% of dataset!)
- **Impact:** All previous metrics were inflated and inaccurate

**Duplicate Analysis:**
- Jan 16: 2,232 duplicates (worst day)
- Jan 15: 1,641 duplicates
- Jan 9: 1,127 duplicates
- Root cause: Missing unique constraint on prediction_grades table
- Fix: De-duplicated data + added composite key constraint

**All metrics below reflect CLEAN DATA after deduplication.**

---

## Executive Summary

Three major investigations completed with actionable insights (corrected data):

1. **LeBron James Mystery**: All systems underpredict, 5.88% accuracy (1/17 predictions)
2. **Best Players**: Evan Mobley leads at 80.85% (no 100% players found)
3. **Worst Players**: LeBron, Quenton Jackson, Donovan Mitchell all <11% accuracy
4. **catboost_v8 Bug**: Confidence normalization broken (76% of values >1, should be 0-1)

**Overall Dataset Quality (Clean):**
- 419 unique players tracked
- 15 unique game dates
- 9,238 total predictions
- 3,690 correct predictions
- **Overall accuracy: 39.94%** (much lower than previously reported ~60%)

---

## Investigation 1: LeBron James Underprediction Mystery

### The Problem (CORRECTED DATA)
- **Clean data:** 5.88% accuracy (1/17 predictions)
- **Previous incorrect data:** 4.55% accuracy (1/22 predictions with duplicates)
- **Comparison:** Average accuracy is 39.94%, LeBron is 7x worse

### Root Cause Analysis (CORRECTED)

**Clean Data Summary:**
- Actual points: Average 28.8, range 26-31
- Predicted points: Average 20.5, range 12.4-22.9
- **Average error: -8.3 points** (massive underprediction)

**By System (Clean Data):**

| System | Predictions | Correct | Avg Actual | Avg Predicted | Avg Error | Avg Confidence |
|--------|-------------|---------|------------|---------------|-----------|----------------|
| catboost_v8 | 5 | 1 | 28.8 | 22.9 | -5.9 | **5300** ⚠️ |
| similarity_balanced_v1 | 3 | 0 | 29.3 | 18.0 | -11.3 | 81.7 |
| zone_matchup_v1 | 3 | 0 | 29.3 | 12.4 | **-16.9** | 49.7 |
| ensemble_v1 | 3 | 0 | 29.3 | 18.8 | -10.5 | 60.7 |
| moving_average | 2 | 0 | 28.5 | 21.8 | -6.7 | 52.0 |
| moving_average_baseline_v1 | 1 | 0 | 31.0 | 22.6 | -8.4 | 45.0 |

### Key Insights

1. **zone_matchup_v1 catastrophic failure (-16.9 error)**
   - Predicted 12.4, actual 29.3
   - Caused by inverted defense logic (bug fixed in Session 91)
   - Should improve dramatically post-fix

2. **catboost_v8 confidence normalization broken ⚠️**
   - Showing 5300 instead of 0.53 (100x multiplier error)
   - Affects 1,192 out of 1,557 catboost_v8 predictions (76%)
   - Critical bug needs immediate fix

3. **All systems underpredict by 6-17 points**
   - Systems don't capture "LeBron in playoff push mode"
   - Historical averages don't match current performance
   - Load management unpredictability

### Recommendations

1. **Immediate:** Fix catboost_v8 confidence normalization bug
2. **Short-term:** Blacklist LeBron from recommendations until models improve
3. **Long-term:** Build superstar archetype with wider variance tolerance

---

## Investigation 2: Donovan Mitchell Overprediction

### The Problem (CORRECTED DATA)
- **Clean data:** 10.53% accuracy (4/38 predictions)
- **Previous incorrect data:** 6.45% accuracy (4/62 with duplicates)

### Analysis (Clean Data)

**By System:**

| System | Predictions | Correct | Avg Actual | Avg Predicted | Avg Error |
|--------|-------------|---------|------------|---------------|-----------|
| zone_matchup_v1 | 9 | 0 | 21.4 | 26.4 | +5.0 |
| ensemble_v1 | 9 | 1 | 21.4 | 28.4 | +6.9 |
| moving_average | 8 | 0 | 20.0 | 26.8 | +6.8 |
| similarity_balanced_v1 | 8 | 2 | 20.4 | 29.8 | **+9.4** |
| catboost_v8 | 3 | 1 | 31.0 | 28.3 | -2.7 |
| moving_average_baseline_v1 | 1 | 0 | 33.0 | 25.9 | -7.1 |

### Key Insights

1. **Opposite of LeBron**: Systems OVERpredict by 5-9 points
2. **High variance player**: 13-33 point range makes predictions unreliable
3. **Different systems fail differently**: Some overpredict, some underpredict

### Recommendation

- Blacklist high-variance players (standard deviation > 8 points)
- Flag Mitchell predictions as unreliable

---

## Investigation 3: Best vs Worst Players (CORRECTED)

### Most Predictable (15+ predictions, Clean Data)

| Player | Predictions | Correct | Accuracy |
|--------|-------------|---------|----------|
| Evan Mobley | 47 | 38 | **80.85%** |
| Jabari Smith Jr | 64 | 50 | **78.13%** |
| Alperen Sengun | 57 | 44 | **77.19%** |
| De'Andre Hunter | 39 | 30 | **76.92%** |
| Tyus Jones | 25 | 19 | **76.00%** |

**Pattern**: Big men (centers) dominate predictability - consistent role, minutes, usage

### Least Predictable (15+ predictions, Clean Data)

| Player | Predictions | Correct | Accuracy |
|--------|-------------|---------|----------|
| LeBron James | 17 | 1 | **5.88%** |
| Quenton Jackson | 29 | 2 | **6.90%** |
| Jake LaRavia | 22 | 2 | **9.09%** |
| Caleb Love | 20 | 2 | **10.00%** |
| Donovan Mitchell | 38 | 4 | **10.53%** |

**Pattern**: Mix of superstars (LeBron, Mitchell) and bench players with inconsistent minutes

### Discrepancy from Previous Report

- **Previous claim:** dorianfinneysmith at 100% accuracy
- **Reality:** No 100% accuracy players with 15+ predictions
- **Likely cause:** Duplicate data inflating small sample sizes

---

## Investigation 4: System Performance (CORRECTED)

### Overall System Accuracy (Clean Data)

| System | Predictions | Correct | Accuracy |
|--------|-------------|---------|----------|
| moving_average | 1,547 | 735 | **47.51%** |
| similarity_balanced_v1 | 1,642 | 672 | **40.93%** |
| zone_matchup_v1 | 2,013 | 819 | **40.69%** |
| ensemble_v1 | 2,013 | 819 | **40.69%** |
| catboost_v8 | 1,557 | 548 | **35.20%** |
| moving_average_baseline_v1 | 466 | 97 | **20.82%** |

### Critical Findings

1. **All systems below 50% accuracy** - worse than random!
2. **moving_average is best** at 47.51% (not catboost_v8 as previously thought)
3. **catboost_v8 is 5th out of 6** despite confidence bug showing inflated values
4. **Previous ROI calculations are invalid** due to duplicate data

**Note:** ROI analysis needs to be recalculated with clean data.

---

## Investigation 5: catboost_v8 Confidence Normalization Bug 🚨

### The Problem

**catboost_v8 confidence values are NOT normalized to 0-1 range:**

- Min: 0.5
- Max: **95** (should be 0.95)
- Average: **69.1** (should be 0.69)
- **1,192 out of 1,557 values (76%)** are > 1

### Impact

1. All ROI calculations using catboost_v8 are invalid
2. High-confidence filtering (>0.70) is actually catching nearly everything
3. Dashboard confidence charts are broken for catboost_v8
4. Calibration analysis is meaningless

### Root Cause

Looking at the previous session's code fix:
```python
# data_loaders.py line 983-985
if system_id == 'catboost_v8':
    confidence_score = confidence_score / 100.0
```

This normalization exists but is NOT being applied to existing data in BigQuery.

### Fix Required

1. **Immediate:** Update existing catboost_v8 records in BigQuery
   ```sql
   UPDATE `nba_predictions.prediction_grades`
   SET confidence_score = confidence_score / 100.0
   WHERE system_id = 'catboost_v8' AND confidence_score > 1
   ```

2. **Validation:** Ensure future predictions are normalized correctly

---

## Investigation 6: Optimal Betting Strategy (NEEDS RECALCULATION)

⚠️ **All previous betting strategy analysis is invalid due to:**
1. Duplicate predictions inflating win rates
2. catboost_v8 confidence normalization bug
3. Incorrect system accuracy metrics

**Action Required:** Recalculate after fixing catboost_v8 confidence bug.

---

## Critical Bugs Summary

### 🔴 P0 - Critical (Data Integrity)

1. **Duplicate Predictions** - ✅ FIXED
   - 2,316 duplicates removed
   - Unique constraint added
   - Monitoring view created

2. **catboost_v8 Confidence Normalization** - ❌ NEEDS FIX
   - 76% of values are wrong (not normalized 0-1)
   - Blocking all ROI/betting analysis
   - Fix: One-time UPDATE + validate ingestion

### 🟡 P1 - High (Model Quality)

3. **zone_matchup_v1 Inverted Defense** - ✅ FIXED (Session 91)
   - Awaiting new prediction data for validation

4. **similarity_balanced_v1 Overconfidence** - ✅ FIXED (Session 91)
   - Awaiting new prediction data for validation

### 🟢 P2 - Medium (Feature Improvements)

5. **Player Blacklist Needed**
   - LeBron, Donovan Mitchell, high-variance players
   - Prevent unreliable predictions from reaching users

6. **Superstar Archetype Missing**
   - Models fail on elite players with load management
   - Need separate modeling approach

---

## Next Steps

### This Week
1. ✅ Fix duplicate predictions (DONE)
2. ❌ Fix catboost_v8 confidence normalization (IN PROGRESS)
3. ⏳ Wait 2-3 days for post-fix prediction data
4. ⏳ Recalculate all ROI metrics with clean data + fixed confidence

### Next Week
1. Validate Session 91 fixes (zone_matchup_v1, similarity_balanced_v1)
2. Build player blacklist system
3. Recalculate optimal betting strategies
4. Update dashboard with corrected metrics

### Month 2
1. Implement superstar archetype
2. Build variance detection
3. Start Phase 4 Priority 1 (Automated Recalibration)

---

## Data Quality Lessons Learned

1. **Always add unique constraints to tables** - prevented duplicate detection
2. **Validate confidence score ranges** - catboost_v8 bug went unnoticed
3. **Monitor data volumes** - 20% duplicates should have triggered alerts
4. **Check raw data before analysis** - assumptions about normalization were wrong

---

**Document Version:** 2.0 (Corrected after deduplication)
**Last Updated:** 2026-01-17
**Status:** Clean data validated, catboost_v8 fix pending
