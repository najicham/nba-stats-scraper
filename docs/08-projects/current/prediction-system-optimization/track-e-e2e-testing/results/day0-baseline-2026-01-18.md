# Track E: Day 0 Baseline - 2026-01-18

**Captured:** 2026-01-18 ~19:00 UTC
**Purpose:** Establish baseline metrics for new XGBoost V1 V2 model and system health

---

## 📊 Executive Summary

**System Status:** ✅ Operational
**XGBoost V1 V2:** ✅ Deployed and generating predictions
**Critical Finding:** ⚠️ XGBoost V1 not being graded since 2026-01-10

---

## 🎯 XGBoost V1 V2 Baseline

### Deployment Details
- **Model:** xgboost_v1_33features_20260118_103153
- **Deployed:** 2026-01-18 18:33 UTC
- **Validation MAE:** 3.726 points
- **Training Samples:** 101,692 (2021-2025)

### Current Production Status (2026-01-18)
- **Predictions Generated:** 280 (for 57 unique players)
- **Created:** 2026-01-17 23:01 UTC (first run after deployment)
- **Average Prediction:** 10.29 points
- **Average Confidence:** 0.77 (77%)
- **Prediction Range:** 0.0 to 28.7 points
- **Placeholders:** 0 ✅ (quality gate working)
- **Model Version:** NULL ⚠️ (Session 102 fix may not have worked)

### Historical Performance (Old XGBoost V1)
- **Last Graded:** 2026-01-10
- **Historical MAE:** 4.47 points (old model, validation was 4.26)
- **Total Graded:** 6,219 predictions
- **Date Range:** 2025-11-19 to 2026-01-10

### Key Observation
🚨 **No XGBoost V1 predictions have been graded since 2026-01-10** (8 days ago)
- This affects our ability to validate the new model's production performance
- Need to investigate why grading stopped for this system

---

## 🔄 All Prediction Systems Status

### Active Systems (2026-01-18)
| System | Predictions | Players | Avg Confidence | Status |
|--------|-------------|---------|----------------|--------|
| xgboost_v1 | 280 | 57 | 0.77 | ✅ Active |
| catboost_v8 | 280 | 57 | - | ✅ Active |
| ensemble_v1 | 280 | 57 | - | ✅ Active |
| moving_average | 280 | 57 | - | ✅ Active |
| similarity_balanced_v1 | 280 | 57 | - | ✅ Active |
| zone_matchup_v1 | 280 | 57 | - | ✅ Active |

**All 6 systems generating predictions** ✅

---

## 📈 Recent Grading Status

### Grading Coverage (Last 5 Days)
| Date | Systems Graded | Total Graded | Coverage Issue |
|------|----------------|--------------|----------------|
| 2026-01-18 | 0 | 0 | Games not complete yet |
| 2026-01-17 | 4 | 17 total | Very low (57 predictions made) |
| 2026-01-16 | 0 | 0 | No grading |
| 2026-01-15 | 4 | 60 total | Low coverage |
| 2026-01-14 | 4 | 201 total | Better coverage |
| 2026-01-13 | 5 | 252 total | Good coverage |

### System-Specific Grading (2026-01-13, most recent complete day)
| System | Graded | Win Rate | MAE |
|--------|--------|----------|-----|
| catboost_v8 | 53 | 45.3% | 5.85 |
| ensemble_v1 | 53 | 45.3% | 6.07 |
| moving_average | 53 | 47.2% | 5.90 |
| similarity_balanced_v1 | 40 | 47.5% | 6.13 |
| zone_matchup_v1 | 53 | 45.3% | 7.28 |
| **xgboost_v1** | **0** | **N/A** | **N/A** |

**Critical Issue:** XGBoost V1 not in recent grading data ⚠️

---

## 💾 Feature Store Health

### Recent Data (Last 6 Days: 2026-01-13 to 2026-01-18)
- **Total Records:** 1,173
- **Unique Dates:** 6
- **Unique Players:** 503
- **Latest Date:** 2026-01-18 ✅ (updated today)
- **Status:** ✅ Healthy and updating

### Data Freshness
✅ Feature store is current and updating daily

---

## 🎯 Baseline Expectations

### XGBoost V1 V2 Performance Targets
Based on validation (3.726 MAE):
- **Expected Production MAE:** 3.73 ± 0.5 points (range: 3.2 - 4.2)
- **Alert Threshold:** MAE > 4.2 for 3+ days
- **Target Win Rate:** ≥ 52% (break-even for betting)
- **Confidence Calibration:** Within ±5% of actual accuracy

### Comparison to Champion (CatBoost V8)
- **CatBoost V8 Validation:** 3.40 MAE
- **XGBoost V1 V2 Validation:** 3.726 MAE
- **Gap:** 9.6% (XGBoost slightly worse)
- **Goal:** Production gap should be similar (8-12%)

---

## 🚨 Issues Identified

### Critical Issues
1. **XGBoost V1 Not Being Graded** (Priority: HIGH)
   - Last graded: 2026-01-10 (8 days ago)
   - Impact: Cannot validate new model performance
   - Action: Investigate grading system for xgboost_v1

2. **Model Version NULL** (Priority: MEDIUM)
   - Session 102 fix may not have deployed correctly
   - Makes tracking model versions difficult
   - Action: Verify coordinator deployment

### Minor Issues
3. **Grading Coverage Inconsistent** (Priority: LOW)
   - Some days have very low coverage (<20%)
   - Session 102 alert should catch this
   - Action: Monitor coverage alert

---

## ✅ Positive Findings

### What's Working Well
- ✅ All 6 prediction systems generating predictions
- ✅ XGBoost V1 V2 model deployed and running
- ✅ Zero placeholder predictions (quality gate effective)
- ✅ High confidence scores (0.77 avg = 77%)
- ✅ Feature store updating daily
- ✅ Prediction volume consistent (~280/day for recent games)

---

## 📋 Next Steps

### Immediate (Today)
1. ✅ Create Track A monitoring query (next task)
2. [ ] Set up daily tracking routine
3. [ ] Investigate XGBoost V1 grading issue

### Short-term (Next 3 Days)
4. [ ] Monitor XGBoost V1 V2 predictions daily
5. [ ] Wait for games to complete and check if grading works
6. [ ] Validate coordinator batch loading at 23:00 UTC
7. [ ] Compare XGBoost V1 to CatBoost V8 when grading available

### Medium-term (Next Week)
8. [ ] Analyze first week of XGBoost V1 V2 data
9. [ ] Create comprehensive performance report
10. [ ] Decide if model meets production criteria

---

## 📊 Key Metrics to Track

### Daily Checks
- [ ] Prediction volume (target: ~280-600/day)
- [ ] Placeholder count (target: 0)
- [ ] Average confidence (baseline: 0.77)
- [ ] Grading status (check if xgboost_v1 being graded)

### Weekly Analysis
- [ ] Production MAE vs validation (3.726)
- [ ] Win rate trend
- [ ] Confidence calibration
- [ ] Head-to-head vs CatBoost V8

---

## 🔬 Investigation Needed

### XGBoost V1 Grading Gap
**Question:** Why hasn't XGBoost V1 been graded since 2026-01-10?

**Hypotheses:**
1. System_id mismatch in grading pipeline
2. Grading coverage too low for recent dates
3. Games not completing or boxscores missing
4. Grading processor filtering out xgboost_v1

**Investigation Steps:**
1. Check grading processor code for system_id filtering
2. Verify boxscore availability for recent games
3. Check if other systems also have gaps
4. Review grading logs for errors

---

## 📝 Baseline Document Metadata

**Created:** 2026-01-18 ~19:00 UTC
**Author:** Engineering Team (Session 90)
**Purpose:** Track E baseline establishment
**Next Update:** After first XGBoost V1 V2 predictions are graded
**Related:** [Track E README](../README.md), [Track A README](../../track-a-monitoring/README.md)

---

**Status:** ✅ Baseline Established
**Critical Blocker:** XGBoost V1 grading gap (needs investigation)
**Overall Health:** ✅ System operational, new model running
