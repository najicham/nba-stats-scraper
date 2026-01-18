# XGBoost V1 V2 - 5-Day Monitoring Checklist

**Start Date:** 2026-01-19 (Day 1 - First grading)
**End Date:** 2026-01-23 (Day 5 - Decision point)
**Frequency:** Daily (5 minutes each morning)
**Purpose:** Validate XGBoost V1 V2 production performance before Track B (Ensemble)

---

## ✅ Daily Checklist (5 minutes/day)

### Each Morning (9:00 AM local time)

**Step 1: Run Daily Query (2 min)**
```bash
bq query --use_legacy_sql=false < track-a-monitoring/daily-monitoring-queries.sql
```

Or run Query 1 directly:
```sql
-- Copy from daily-monitoring-queries.sql (Query 1)
```

**Step 2: Record Metrics (1 min)**

| Date | MAE | Win Rate | Volume | Status | Notes |
|------|-----|----------|--------|--------|-------|
| Jan 19 (D1) | ___ | ___% | ___ | ✅/⚠️/🚨 | ___ |
| Jan 20 (D2) | ___ | ___% | ___ | ✅/⚠️/🚨 | ___ |
| Jan 21 (D3) | ___ | ___% | ___ | ✅/⚠️/🚨 | ___ |
| Jan 22 (D4) | ___ | ___% | ___ | ✅/⚠️/🚨 | ___ |
| Jan 23 (D5) | ___ | ___% | ___ | ✅/⚠️/🚨 | ___ |

**Step 3: Check Alert Flags (1 min)**
- 🚨 HIGH MAE (> 4.2) → Investigate immediately
- ⚠️ ELEVATED MAE (4.0-4.2) → Monitor closely
- ✅ GOOD (< 4.0) → Continue monitoring
- 🚨 LOW WIN RATE (< 50%) → Investigate
- ⚠️ BELOW BREAKEVEN (50-52%) → Monitor
- ✅ GOOD (≥ 52%) → Continue

**Step 4: Quick Validation (1 min)**
- [ ] Predictions graded? (should be YES)
- [ ] Volume normal? (200-400 predictions)
- [ ] No placeholder predictions? (should be 0)
- [ ] Any system errors? (check logs if issues)

---

## 📊 Success Criteria

### Day 1 (Jan 19) - First Grading ✅
**Must Have:**
- [x] XGBoost V1 predictions graded successfully
- [ ] MAE ≤ 5.0 (initial production data)
- [ ] Win rate ≥ 45% (initial, can be lower)
- [ ] Zero placeholder predictions
- [ ] No crashes or errors

**Good to Have:**
- [ ] MAE ≤ 4.5
- [ ] Win rate ≥ 50%

**Red Flags:**
- 🚨 MAE > 6.0 (much worse than validation)
- 🚨 Win rate < 40%
- 🚨 Grading failed completely
- 🚨 Placeholder predictions appearing

---

### Days 2-3 (Jan 20-21) - Stabilization
**Must Have:**
- [ ] MAE trend stable (not increasing daily)
- [ ] Win rate ≥ 48%
- [ ] Consistent volume (200-400/day)
- [ ] Grading coverage ≥ 70%

**Good to Have:**
- [ ] MAE ≤ 4.2 (within 15% of validation)
- [ ] Win rate ≥ 52% (breakeven)
- [ ] MAE variance < 0.5 daily

**Red Flags:**
- 🚨 MAE increasing each day
- 🚨 Win rate declining
- 🚨 Grading coverage < 50%
- 🚨 Erratic predictions (huge swings)

---

### Days 4-5 (Jan 22-23) - Decision Point
**Must Have:**
- [ ] 5-day average MAE ≤ 4.5
- [ ] 5-day average win rate ≥ 50%
- [ ] No critical errors
- [ ] System stable (no restarts needed)

**Good to Have:**
- [ ] 5-day average MAE ≤ 4.0
- [ ] 5-day average win rate ≥ 52%
- [ ] MAE improving or stable
- [ ] Confidence calibration good

**Decision Criteria:**
✅ **PASS (Proceed to Track B):**
- Average MAE ≤ 4.2
- Win rate ≥ 50%
- Stable trend (no major issues)
→ **Action:** Start Track B (Ensemble retraining)

⚠️ **CONDITIONAL PASS (Track E first):**
- MAE 4.2-4.5
- Win rate 48-52%
- Some stability concerns
→ **Action:** Complete Track E (E2E Testing), then Track B

🚨 **FAIL (Investigate):**
- MAE > 4.5
- Win rate < 48%
- Major instability
→ **Action:** Investigate model issues before proceeding

---

## 📈 Trend Analysis (End of Day 5)

### Calculate 5-Day Aggregates
```sql
-- Run this on Day 5 (Jan 23)
SELECT
  'XGBoost V1 V2 - 5 Day Summary' as summary,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT game_date) as days_graded,

  -- Performance
  ROUND(AVG(absolute_error), 2) as avg_mae,
  ROUND(STDDEV(absolute_error), 2) as stddev_mae,
  ROUND(MIN(absolute_error), 2) as min_mae,
  ROUND(MAX(absolute_error), 2) as max_mae,

  -- Win rate
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as avg_win_rate,

  -- vs Baseline
  ROUND(AVG(absolute_error) - 3.726, 2) as mae_vs_validation,
  ROUND((AVG(absolute_error) - 3.726) / 3.726 * 100, 1) as pct_worse_than_validation,

  -- Status
  CASE
    WHEN AVG(absolute_error) <= 4.0 THEN '✅ EXCELLENT'
    WHEN AVG(absolute_error) <= 4.2 THEN '✅ GOOD'
    WHEN AVG(absolute_error) <= 4.5 THEN '⚠️ ACCEPTABLE'
    ELSE '🚨 POOR'
  END as performance_status

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-19'
  AND game_date <= '2026-01-23'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE;
```

### Expected Results

**Excellent Performance (Proceed to Track B immediately):**
- Avg MAE: 3.5-4.0
- Win Rate: 52-58%
- Status: ✅ EXCELLENT

**Good Performance (Proceed to Track B):**
- Avg MAE: 4.0-4.2
- Win Rate: 50-54%
- Status: ✅ GOOD

**Acceptable Performance (Consider Track E first):**
- Avg MAE: 4.2-4.5
- Win Rate: 48-52%
- Status: ⚠️ ACCEPTABLE

**Poor Performance (Investigate first):**
- Avg MAE: > 4.5
- Win Rate: < 48%
- Status: 🚨 POOR

---

## 🔍 Daily Investigation Triggers

### If MAE > 4.5 on any single day:
1. Check prediction volume (low volume = high variance)
2. Check game difficulty (playoffs, high-stakes games)
3. Compare to CatBoost V8 (if both high, it's the games)
4. Review feature quality for that day
5. Check for system errors or timeouts

### If Win Rate < 45% on any single day:
1. Check sample size (< 100 predictions = not significant)
2. Check OVER vs UNDER balance
3. Check confidence distribution
4. Compare to baseline systems
5. Look for systematic bias

### If Grading Coverage < 70%:
1. Check if games completed (might be postponed)
2. Check grading processor logs
3. Verify boxscore availability
4. Check for grading errors
5. Alert if coverage low 2+ days in a row

---

## 📝 Daily Log Template

```markdown
## Day X: [Date] - [Status]

**Metrics:**
- MAE: [value]
- Win Rate: [value]%
- Volume: [value] predictions
- Games: [count]

**Status:** ✅ GOOD / ⚠️ WARNING / 🚨 ALERT

**Observations:**
- [Any notable patterns]
- [Comparisons to baseline]
- [Issues encountered]

**Actions Taken:**
- [If any investigation needed]

**Carry Forward:**
- [Anything to watch tomorrow]
```

---

## 🎯 End-of-Week Report (Day 5)

### Summary Template

```markdown
# XGBoost V1 V2 - 5-Day Production Summary

**Dates:** 2026-01-19 to 2026-01-23
**Status:** [✅ PASS / ⚠️ CONDITIONAL / 🚨 FAIL]

## Key Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Average MAE | ≤ 4.2 | [___] | [status] |
| Average Win Rate | ≥ 50% | [___]% | [status] |
| Total Predictions | ~1,000-1,500 | [___] | [status] |
| Grading Coverage | ≥ 70% | [___]% | [status] |

## Performance Trend
- Day 1: MAE [___], WR [___]%
- Day 2: MAE [___], WR [___]%
- Day 3: MAE [___], WR [___]%
- Day 4: MAE [___], WR [___]%
- Day 5: MAE [___], WR [___]%

**Trend:** [Improving / Stable / Declining]

## Comparison to Validation
- Validation MAE: 3.726
- Production MAE: [___]
- Difference: [___] ([___]%)
- Verdict: [Within tolerance / Slightly worse / Much worse]

## Issues Encountered
- [List any problems]
- [Resolutions]

## Recommendation

**[Choose one]:**

### ✅ PASS - Proceed to Track B
Model performance is stable and good. Ready to retrain Ensemble V1 with new XGBoost V1 V2.

**Next Steps:**
1. Start Track B (Ensemble retraining)
2. Continue passive monitoring during ensemble work
3. Target: Complete Track B within 8-10 hours

### ⚠️ CONDITIONAL - Track E First
Model performance is acceptable but want more validation before building on it.

**Next Steps:**
1. Complete Track E (E2E Testing) - 5-6 hours
2. Continue monitoring during Track E
3. Reassess after Track E complete

### 🚨 FAIL - Investigate
Model performance below expectations. Investigate before proceeding.

**Next Steps:**
1. Deep dive investigation (2-4 hours)
2. Check feature quality, model loading, etc.
3. Consider rollback if critical issues
4. Reassess after investigation
```

---

## 🔗 Quick Links

- [Day 0 Baseline](./day0-xgboost-v1-v2-baseline-2026-01-18.md)
- [Daily Monitoring Queries](./daily-monitoring-queries.sql)
- [Tracking Routine](./TRACKING-ROUTINE.md)
- [Progress Log](../PROGRESS-LOG.md)
- [Track B README](../track-b-ensemble/README.md)
- [Track E README](../track-e-e2e-testing/README.md)

---

**Created:** 2026-01-18
**Monitoring Start:** 2026-01-19
**Decision Point:** 2026-01-23
**Owner:** Engineering Team
