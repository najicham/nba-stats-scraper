# XGBoost V1 Daily Tracking Routine

**Created:** 2026-01-18
**Purpose:** Simple daily routine to monitor XGBoost V1 V2 performance
**Time Required:** 5 minutes/day

---

## ⚡ Quick Daily Check (5 mins)

### Every Morning (After Games Complete)

**Step 1: Run Primary Query**
```bash
cd /home/naji/code/nba-stats-scraper
bq query --use_legacy_sql=false < docs/08-projects/current/prediction-system-optimization/track-a-monitoring/daily-monitoring-queries.sql
```

Or copy Query 1 from `daily-monitoring-queries.sql` and run in BigQuery Console

**Step 2: Check Status Indicators**
Look for these columns:
- `mae_status`: Should be ✅ GOOD (MAE ≤ 4.2)
- `win_rate_status`: Should be ✅ GOOD (≥52%)
- `total_predictions`: Should be ~200-600

**Step 3: Log Results**
Quick entry in PROGRESS-LOG.md:
```markdown
### [Date] - Daily Check
- XGBoost V1 MAE: X.XX
- Win Rate: XX%
- Status: ✅ GOOD / ⚠️ WARNING / 🚨 ALERT
- Notes: [any observations]
```

---

## 🎯 When to Investigate

### 🚨 CRITICAL (Act Immediately)
- MAE > 5.0 for any single day
- Win rate < 45% for 3+ consecutive days
- Prediction volume drops >50%
- All predictions failing

**Action:**
1. Check service health
2. Review logs for errors
3. Compare to CatBoost V8
4. Escalate if needed

### ⚠️ WARNING (Monitor Closely)
- MAE > 4.2 for 3+ consecutive days
- Win rate < 50% for 7+ days
- Volume drops >20%
- Confidence calibration off >10%

**Action:**
1. Run full diagnostic queries (Queries 2-6)
2. Check feature quality
3. Compare to baseline (3.726 MAE)
4. Document trend in PROGRESS-LOG

### ✅ GOOD (Normal Operation)
- MAE between 3.2 and 4.2
- Win rate ≥ 52%
- Volume stable (within 20% of baseline)
- Confidence well-calibrated

**Action:** Log results, continue monitoring

---

## 📅 Weekly Deep Dive (15 mins)

### Every Monday Morning

**Run All 6 Queries:**
1. Overall Daily Performance (baseline)
2. Week-to-Date Summary (trends)
3. OVER vs UNDER (bias check)
4. Confidence Tiers (calibration)
5. Recent Trend (7-day view)
6. Volume Check (coverage)

**Create Weekly Entry in PROGRESS-LOG.md:**
```markdown
### Week of [Date] - XGBoost V1 V2 Performance

**Overall:**
- Weekly MAE: X.XX (vs validation 3.726)
- Weekly Win Rate: XX%
- Total Predictions: XXX
- Status: ✅/⚠️/🚨

**Key Findings:**
- [Bullet points of interesting observations]

**Trends:**
- [Improving/Stable/Degrading]

**Action Items:**
- [Any follow-up needed]
```

---

## 📊 Baseline Comparison

### Target Metrics (From Validation)
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| MAE | 3.73 ± 0.5 | > 4.2 for 3 days |
| Win Rate | ≥ 52% | < 50% for 7 days |
| Confidence | 0.65-0.80 | Outside range 3 days |
| Volume | ~280-600/day | Drop > 50% |

### Comparison to CatBoost V8 (Champion)
| Model | Validation MAE | Expected Production |
|-------|----------------|---------------------|
| CatBoost V8 | 3.40 | ~3.49 |
| XGBoost V1 V2 | 3.726 | ~3.73 ± 0.5 |
| Gap | 9.6% | Similar expected |

**Goal:** Stay within 10% of CatBoost V8 performance

---

## 📝 Logging Template

### Daily Log Entry (In PROGRESS-LOG.md)
```markdown
**2026-01-XX - XGBoost V1 Daily Check:**
- Predictions: XXX
- MAE: X.XX (status: ✅/⚠️/🚨)
- Win Rate: XX.X%
- vs Validation: +/- X.XX points
- Notes: [observations]
```

### Weekly Log Entry
```markdown
## Week Ending 2026-01-XX - XGBoost V1 V2 Performance

**Summary:**
- Days Tracked: X
- Avg MAE: X.XX
- Avg Win Rate: XX%
- Performance: ON TARGET/ELEVATED/CONCERNING

**Detailed Metrics:**
- Predictions: XXX total (XXX/day avg)
- OVER/UNDER Balance: XX% / XX%
- Confidence Calibration: ±X% (GOOD/NEEDS ATTENTION)

**Observations:**
- [Key findings from week]

**Next Week Focus:**
- [What to watch]
```

---

## 🔍 Diagnostic Checklist

If performance is off-target, work through this checklist:

### Data Quality
- [ ] Feature store updating? (Check ml_feature_store_v2)
- [ ] Vegas lines available? (Check coverage %)
- [ ] Recent player stats fresh? (Check last update)

### Model Health
- [ ] Correct model loaded? (Check model_version)
- [ ] Predictions in valid range? (0-60 points)
- [ ] No placeholders? (Should be 0)
- [ ] Confidence scores reasonable? (0.5-1.0)

### System Health
- [ ] Prediction worker running? (Check Cloud Run)
- [ ] Coordinator executing? (Check logs at 23:00 UTC)
- [ ] No errors in logs? (Review Cloud Logging)
- [ ] Circuit breaker closed? (Check breaker state)

### Comparison
- [ ] Other models performing similarly? (Check CatBoost V8)
- [ ] Grading working for all systems? (Check prediction_accuracy)
- [ ] Games completing normally? (Check boxscore availability)

---

## 🚨 Known Issues to Monitor

### Issue 1: XGBoost V1 Grading Gap
**Status:** ACTIVE (as of 2026-01-18)
**Description:** XGBoost V1 not graded since 2026-01-10
**Impact:** Cannot validate new model performance
**Workaround:** Monitor prediction volume and characteristics
**Resolution:** Under investigation

### Issue 2: Model Version NULL
**Status:** ACTIVE (as of 2026-01-18)
**Description:** Predictions have model_version = NULL
**Impact:** Cannot track which model version made prediction
**Workaround:** Use created_at timestamp (after 2026-01-18 18:33 = V2)
**Resolution:** Verify Session 102 coordinator fix

---

## 📞 Escalation

### When to Escalate
- Critical alert (🚨) persists >24 hours
- Multiple systems affected (not just XGBoost V1)
- Service completely down
- Data quality issues affecting predictions

### Escalation Path
1. Document issue in PROGRESS-LOG.md
2. Run diagnostic checklist
3. Check related systems (coordinator, feature store)
4. Create incident report
5. Notify engineering team

---

## ✅ Success Indicators

**First Week (Jan 18-24):**
- [ ] Daily monitoring established
- [ ] Baseline comparison created
- [ ] No critical alerts
- [ ] Grading working (if fixed)

**First Month (Jan 18 - Feb 18):**
- [ ] Production MAE stable ~3.73 ± 0.5
- [ ] Win rate consistently ≥52%
- [ ] No model degradation over time
- [ ] Competitive with CatBoost V8

---

## 🔗 Quick Links

- **Queries:** [daily-monitoring-queries.sql](./daily-monitoring-queries.sql)
- **Baseline:** [day0-baseline-2026-01-18.md](../track-e-e2e-testing/results/day0-baseline-2026-01-18.md)
- **Progress Log:** [PROGRESS-LOG.md](../PROGRESS-LOG.md)
- **Track A README:** [README.md](./README.md)

---

**Created:** 2026-01-18
**Owner:** Engineering Team
**Next Review:** After first week of data collection
