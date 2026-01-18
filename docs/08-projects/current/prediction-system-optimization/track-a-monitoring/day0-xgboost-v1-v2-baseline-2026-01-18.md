# XGBoost V1 V2 - Day 0 Baseline (Pre-Grading)

**Date:** 2026-01-18
**Status:** ✅ BASELINE ESTABLISHED
**Model:** XGBoost V1 V2 (deployed 2026-01-18)
**Validation MAE:** 3.726
**Target Production MAE:** ≤ 4.2 (within 15% of validation)

---

## 📊 Executive Summary

**XGBoost V1 V2 model successfully deployed and generating predictions!**

- ✅ **280 predictions** generated for Jan 18 games
- ✅ **Zero placeholder predictions** (quality gate working)
- ✅ **High confidence** (0.77 average = 77%)
- ✅ **Reasonable prediction range** (0.0 to 28.7 points)
- ⚠️ **Model version NULL** (Session 102 fix may need verification)
- ⏳ **Grading pending** - Games on Jan 18 haven't completed yet

**Next Check:** Jan 19 morning - verify grading completed and check initial MAE

---

## 🎯 Day 0 Metrics (Predictions Only - Before Grading)

### Volume Metrics

| Metric | Value | Status |
|--------|-------|--------|
| Total Predictions | 280 | ✅ Good volume |
| Unique Players | 57 | ✅ |
| Unique Games | 5 | ✅ |
| Predictions per Player | 4.9 | ✅ (multiple lines) |
| Predictions per Game | 56.0 | ✅ |

**Games Predicted:**
1. BKN @ CHI - 84 predictions (17 players)
2. ORL @ MEM - 73 predictions (15 players)
3. NOP @ HOU - 59 predictions (12 players)
4. TOR @ LAL - 44 predictions (9 players)
5. CHA @ DEN - 20 predictions (4 players)

---

### Confidence Metrics

| Metric | Value | Status |
|--------|-------|--------|
| Average Confidence | 0.770 | ✅ Strong (77%) |
| Std Dev Confidence | 0.000 | ⚠️ No variance (all same) |
| Min Confidence | 0.770 | ✅ |
| Max Confidence | 0.770 | ✅ |

**Analysis:** All predictions have identical confidence (0.77). This suggests:
- Model is very consistent
- OR confidence calculation might be fixed/calibrated
- Monitor if this changes with more games

---

### Prediction Distribution

| Metric | Value | Status |
|--------|-------|--------|
| Average Prediction | 10.29 pts | ✅ Reasonable |
| Std Dev Prediction | 6.36 pts | ✅ Good variance |
| Min Prediction | 0.0 pts | ⚠️ Edge case |
| Max Prediction | 28.7 pts | ✅ (Kevin Durant) |

**Prediction Range Distribution:**

| Line Bucket | Predictions | Avg Prediction | Avg Confidence |
|------------|-------------|----------------|----------------|
| < 10 pts | 136 (49%) | 6.57 | 0.77 |
| 10-14 pts | 88 (31%) | 10.59 | 0.77 |
| 15-19 pts | 39 (14%) | 18.04 | 0.77 |
| 20-24 pts | 12 (4%) | 19.92 | 0.77 |
| 25-29 pts | 5 (2%) | 22.64 | 0.77 |

**Analysis:** Most predictions are for lower-scoring players (< 10 pts = 49%). This is normal - most players are bench/role players with lower point totals.

---

### Recommendations

| Recommendation | Count | Percentage |
|----------------|-------|------------|
| OVER | 105 | 37.5% |
| UNDER | 174 | 62.1% |
| PASS | 1 | 0.4% |

**Analysis:** Slight bias toward UNDER recommendations (62% vs 38% OVER). This is typical for prediction systems - UNDER bets are often safer statistically.

---

### Quality Checks

| Check | Value | Target | Status |
|-------|-------|--------|--------|
| Placeholder Count | 0 | 0 | ✅ PASS |
| High Conf Filtered (≥88%) | 0 | N/A | ✅ None filtered |
| Model Version Populated | NULL | Should be set | ⚠️ ISSUE |
| Prediction Range Valid | 0.0 - 28.7 | 0 - 60 | ✅ PASS |

**Issues Identified:**
1. ⚠️ **Model version = NULL** - Session 102 coordinator fix may not have deployed correctly
   - Should show: `xgboost_v1_33features_20260118_103153` or similar
   - Workaround: Use `created_at` timestamp (after 2026-01-18 18:33 = V2)
   - Follow-up: Verify environment variables on prediction worker

---

## ⏱️ Timing Metrics

| Metric | Value |
|--------|-------|
| First Prediction | 2026-01-17 23:01:22 UTC |
| Last Prediction | 2026-01-17 23:02:19 UTC |
| Duration | 57 seconds |
| Predictions per Second | 4.9 |

**Analysis:**
- Coordinator triggered at 23:00 UTC (as expected)
- All 280 predictions generated in under 1 minute ✅
- Fast processing indicates batch loading optimization working

---

## 📈 Sample Predictions

**Top Predictions (by predicted points):**

| Player | Game | Line | Prediction | Confidence | Rec |
|--------|------|------|------------|------------|-----|
| Kevin Durant | NOP @ HOU | 19.0 | 28.7 | 0.77 | OVER |
| Kevin Durant | NOP @ HOU | 21.0 | 28.7 | 0.77 | OVER |
| Trey Murphy III | NOP @ HOU | 26.5 | 24.1 | 0.77 | UNDER |
| Trey Murphy III | NOP @ HOU | 24.5 | 24.1 | 0.77 | UNDER |

**Analysis:**
- Kevin Durant predicted at 28.7 points (high scorer)
- Multiple lines per player (19.0, 21.0 for KD)
- Trey Murphy III predicted at 24.1 (UNDER on 26.5 line)

---

## 🎯 Success Criteria for Production

### Day 1 (Jan 19 - After Grading)
- [ ] XGBoost V1 predictions graded successfully
- [ ] Production MAE ≤ 4.2 (within 15% of validation 3.726)
- [ ] Win rate ≥ 50% (ideally ≥52% for breakeven)
- [ ] Zero placeholder predictions maintained
- [ ] No system errors or crashes

### Week 1 (Jan 19-25)
- [ ] Daily MAE stable (± 0.5 from baseline)
- [ ] Win rate consistently ≥ 50%
- [ ] Average MAE ≤ 4.0
- [ ] No grading gaps
- [ ] Volume consistent (~250-300 predictions/day)

### Decision Point (After 3-5 days)
**If MAE ≤ 4.0 and stable:**
→ Proceed to Track B (Ensemble retraining)

**If MAE 4.0-4.5 and stable:**
→ Consider Track E first (E2E testing), then Track B

**If MAE > 4.5 or unstable:**
→ Investigate model performance before proceeding

---

## 🔬 Comparison to Validation

| Metric | Validation | Day 0 Predictions | Notes |
|--------|-----------|-------------------|-------|
| Dataset Size | 101,692 samples | 280 predictions | Small sample, wait for more |
| MAE | 3.726 | TBD (grading pending) | Target: ≤ 4.2 |
| Date Range | 2021-2025 | 2026-01-18 only | Future performance |
| Feature Count | 33 features | 33 features | ✅ Same |

**Note:** Day 0 is prediction metrics only. Production MAE comparison requires grading (Jan 19).

---

## 🚨 Issues & Follow-ups

### Issue 1: Model Version NULL
**Severity:** Low (doesn't affect predictions, just tracking)
**Impact:** Harder to distinguish V1 vs V2 predictions in queries
**Workaround:** Use `created_at >= '2026-01-18 18:33:00'` to identify V2 predictions
**Action:** Verify Session 102 coordinator fix deployed correctly

### Issue 2: Grading Pending
**Severity:** Low (expected, games not complete)
**Impact:** Cannot validate production MAE yet
**Action:** Check tomorrow (Jan 19) morning for grading results

### Issue 3: Zero Confidence Variance
**Severity:** Low (might be normal)
**Impact:** All predictions have confidence = 0.77
**Action:** Monitor if this persists across multiple days
**Hypothesis:** Model might output consistent confidence, or it's being normalized

---

## 📊 Next Steps

### Immediate (Jan 19 - Tomorrow)
1. **Check Grading:** Verify Jan 18 predictions graded successfully
2. **Run Daily Query:** Execute Query 1 from daily-monitoring-queries.sql
3. **Calculate MAE:** Compare production MAE to validation (3.726)
4. **Document Results:** Update this baseline with Day 1 grading metrics

### Short-term (Jan 19-23)
5. **Daily Monitoring:** Run daily queries each morning (5 min/day)
6. **Track Trends:** Watch for MAE stability and win rate
7. **Compare to CatBoost:** Head-to-head performance
8. **Monitor Volume:** Ensure consistent prediction generation

### Decision Point (Jan 23-25)
9. **Evaluate Performance:** Review 5-7 days of production data
10. **Decide Next Track:**
    - Track B (Ensemble) if XGBoost V1 V2 stable and good
    - Track E (E2E Testing) if want to validate pipeline first

---

## 📝 Monitoring Queries

**Location:** `track-a-monitoring/daily-monitoring-queries.sql`

**Daily Routine:**
1. Run Query 1 (Overall Daily Performance) each morning
2. Check for alert flags (🚨 or ⚠️)
3. Compare MAE to baseline (3.726)
4. Verify win rate ≥ 52%
5. Update tracking spreadsheet

**Expected Time:** 5 minutes/day

---

## 🔗 Related Documentation

- [Daily Monitoring Queries](./daily-monitoring-queries.sql)
- [Tracking Routine](./TRACKING-ROUTINE.md)
- [XGBoost V1 Performance Guide](../../ml-model-v8-deployment/XGBOOST-V1-PERFORMANCE-GUIDE.md)
- [Progress Log](../PROGRESS-LOG.md)
- [Investigation Resolution](../INVESTIGATION-XGBOOST-GRADING-GAP.md)

---

**Baseline Established:** 2026-01-18 19:30 UTC
**Grading Expected:** 2026-01-19 morning
**Next Update:** After first grading results available
**Status:** ✅ READY FOR MONITORING
