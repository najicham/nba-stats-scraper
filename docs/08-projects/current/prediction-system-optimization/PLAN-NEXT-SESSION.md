# Next Session Plan - XGBoost V1 V2 Monitoring & Track Decision

**Created:** 2026-01-18 (Session 98)
**Next Session Date:** 2026-01-19 to 2026-01-23 (Daily checks)
**Decision Point:** 2026-01-23 (Day 5)
**Current Branch:** session-98-docs-with-redactions

---

## 🎯 Plan Overview

**Strategic Approach:** Passive monitoring (5 min/day × 5 days) to validate XGBoost V1 V2 production performance before committing to Track B (Ensemble retraining).

**Goal:** Gather data to make an informed decision about next track:
- **Option A:** Track B (Ensemble) if XGBoost V1 V2 stable (MAE ≤ 4.2)
- **Option B:** Track E (E2E Testing) if need more validation
- **Option C:** Investigate if XGBoost V1 V2 underperforms

**Why This Matters:** Avoids wasting 8-10 hours on ensemble retraining if new XGBoost model isn't production-ready.

---

## 📅 Daily Tasks (Jan 19-23)

### Morning Routine (5 minutes/day)

**Step 1: Run Monitoring Query (2 min)**
```bash
cd /home/naji/code/nba-stats-scraper

# Option A: Run first query from SQL file
bq query --use_legacy_sql=false --max_rows=30 "$(head -60 docs/08-projects/current/prediction-system-optimization/track-a-monitoring/daily-monitoring-queries.sql | tail -50)"

# Option B: Run inline
bq query --use_legacy_sql=false --max_rows=30 "
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct = TRUE) as wins,
  COUNTIF(prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate_pct,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  CASE
    WHEN AVG(absolute_error) > 4.2 THEN '🚨 HIGH MAE'
    WHEN AVG(absolute_error) > 4.0 THEN '⚠️ ELEVATED MAE'
    ELSE '✅ GOOD'
  END as mae_status,
  CASE
    WHEN SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) < 0.50 THEN '🚨 LOW WIN RATE'
    WHEN SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) < 0.52 THEN '⚠️ BELOW BREAKEVEN'
    ELSE '✅ GOOD'
  END as win_rate_status
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-18'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 30
"
```

**Step 2: Record Results (1 min)**

| Date | MAE | Win Rate | Volume | Status | Notes |
|------|-----|----------|--------|--------|-------|
| Jan 19 (D1) | ___ | ___% | ___ | ✅/⚠️/🚨 | First grading results |
| Jan 20 (D2) | ___ | ___% | ___ | ✅/⚠️/🚨 | Stability check |
| Jan 21 (D3) | ___ | ___% | ___ | ✅/⚠️/🚨 | Trend emerging |
| Jan 22 (D4) | ___ | ___% | ___ | ✅/⚠️/🚨 | Almost there |
| Jan 23 (D5) | ___ | ___% | ___ | ✅/⚠️/🚨 | Decision day |

**Step 3: Check Alerts (1 min)**
- 🚨 HIGH MAE (> 4.2) → Investigate same day
- ⚠️ ELEVATED MAE (4.0-4.2) → Watch closely
- ✅ GOOD (< 4.0) → Continue monitoring
- 🚨 LOW WIN RATE (< 50%) → Investigate
- ⚠️ BELOW BREAKEVEN (50-52%) → Monitor
- ✅ GOOD (≥ 52%) → Continue

**Step 4: Quick Validation (1 min)**
- [ ] Predictions graded? (check volume > 0)
- [ ] Volume normal? (200-400 predictions)
- [ ] No placeholder predictions? (should be 0)
- [ ] Any system errors? (check logs if issues)

---

## 🔍 Day 1 (Jan 19) - Critical First Check

**Special Attention:** First day of grading for XGBoost V1 V2

### Success Criteria (Day 1)
- ✅ **Grading working:** Predictions for Jan 18 appear in prediction_accuracy
- ✅ **MAE reasonable:** ≤ 5.0 (can be higher first day)
- ✅ **Win rate acceptable:** ≥ 45% (can be lower first day)
- ✅ **Zero placeholders:** No 20.0 predictions with 0.50 confidence
- ✅ **No crashes:** System healthy

### If Day 1 Checks FAIL

**If grading didn't work:**
```bash
# Check if any systems graded
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as graded
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date = '2026-01-18'
GROUP BY system_id
ORDER BY graded DESC
"

# If NO systems graded → boxscore issue (postponed games?)
# If other systems graded but not xgboost_v1 → investigate grading processor
```

**If MAE > 6.0 on Day 1:**
```bash
# Compare to other systems
bq query --use_legacy_sql=false "
SELECT
  system_id,
  ROUND(AVG(absolute_error), 2) as mae,
  COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date = '2026-01-18'
GROUP BY system_id
ORDER BY mae
"

# If all systems have high MAE → difficult games (normal)
# If only xgboost_v1 high → investigate model
```

**If Win Rate < 40% on Day 1:**
```bash
# Check sample size
bq query --use_legacy_sql=false "
SELECT COUNT(*) as sample_size
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1' AND game_date = '2026-01-18'
"

# If < 50 predictions → variance (not significant)
# If > 100 predictions → potential issue, investigate
```

---

## 📊 Day 5 (Jan 23) - Decision Point

### Run 5-Day Analysis

**Query: 5-Day Aggregate Performance**
```bash
bq query --use_legacy_sql=false "
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

FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-19'
  AND game_date <= '2026-01-23'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
"
```

### Decision Matrix

**Scenario 1: ✅ EXCELLENT (Avg MAE ≤ 4.0, Win Rate ≥ 52%)**
→ **Decision:** Proceed directly to Track B (Ensemble Retraining)
→ **Confidence:** HIGH - Model performing well
→ **Next Session:** Start Track B immediately (8-10 hours)

**Scenario 2: ✅ GOOD (Avg MAE 4.0-4.2, Win Rate 50-54%)**
→ **Decision:** Proceed to Track B with caution
→ **Confidence:** MEDIUM-HIGH - Model acceptable
→ **Next Session:** Start Track B (8-10 hours)

**Scenario 3: ⚠️ ACCEPTABLE (Avg MAE 4.2-4.5, Win Rate 48-52%)**
→ **Decision:** Complete Track E (E2E Testing) first, then reassess
→ **Confidence:** MEDIUM - Want more validation
→ **Next Session:** Track E (5-6 hours), then decide on Track B

**Scenario 4: 🚨 POOR (Avg MAE > 4.5, Win Rate < 48%)**
→ **Decision:** Investigate model performance issues
→ **Confidence:** LOW - Model underperforming
→ **Next Session:** Investigation (2-4 hours)

---

## 🎯 Track B (Ensemble Retraining) - If Approved

**When to Start:** After Day 5 if XGBoost V1 V2 performance ✅ GOOD or better

**Estimated Time:** 8-10 hours

**Phases:**

### Phase 1: Planning & Analysis (2 hours)
1. Review current ensemble architecture
2. Analyze component models (XGBoost V1 V2, CatBoost V8, etc.)
3. Design new ensemble configuration
4. Create training plan document

### Phase 2: Training Preparation (2 hours)
1. Update training script for new XGBoost V1 V2 model
2. Prepare training data (2021-2025 full backfill)
3. Verify all component predictions available
4. Configure hyperparameters

### Phase 3: Model Training (2 hours)
1. Generate base predictions from all 6 systems
2. Train meta-learner (Ridge or Stacking)
3. Validate results
4. Compare to CatBoost V8 (3.40 MAE target)

### Phase 4: Validation & Analysis (2 hours)
1. Out-of-sample testing
2. Head-to-head vs CatBoost V8
3. Confidence calibration check
4. Feature importance analysis

### Phase 5: Deployment (2 hours)
1. Upload model to GCS
2. Update prediction worker
3. Test in staging
4. Deploy to production
5. Monitor for 24-48 hours

**Success Criteria for Track B:**
- Ensemble MAE ≤ 3.5 (better than current ~3.5)
- Ideally: MAE ≤ 3.40 (competitive with CatBoost V8)
- No regressions vs current ensemble
- Confidence calibration maintained

---

## 🎯 Track E (E2E Testing) - Alternative Path

**When to Start:** If XGBoost V1 V2 performance is ⚠️ ACCEPTABLE

**Estimated Time:** 5-6 hours over 3-5 days

**Why Do This First:**
- Validates entire pipeline (not just XGBoost)
- Confirms Session 102 optimizations working
- Establishes production readiness
- Gives XGBoost V1 V2 more time to prove itself

**Test Scenarios:**

### Scenario 1: Happy Path (48-72 hours)
- Zero manual intervention
- All phases complete autonomously
- Zero timeout errors
- All 6 systems generate predictions

### Scenario 2: XGBoost V1 V2 Validation (7 days)
- Track production MAE vs validation (3.726)
- Compare to CatBoost V8
- Verify confidence calibration
- Check feature importance stability

### Scenario 3: Feature Quality (3 days)
- Feature completeness >95%
- Features updated daily
- Validate pace features populating
- Check value ranges

### Scenario 4: Coordinator Performance (3 days)
- Batch loading <10s consistently
- Zero timeout errors
- 100% player coverage
- Session 102 fix validated

### Scenario 5: Grading & Alerts (3 days)
- Grading coverage >70%
- Coverage alert functioning
- Games graded within 24h
- Metrics calculating correctly

**Deliverables:**
- Test results document
- Production readiness checklist
- Performance trends analysis
- Go/no-go decision for Track B

---

## 🚨 Investigation Plan - If Performance Poor

**When to Start:** If XGBoost V1 V2 performance is 🚨 POOR (MAE > 4.5)

**Estimated Time:** 2-4 hours

**Investigation Steps:**

### 1. Verify Model Loading (30 min)
```bash
# Check worker logs for model loading
gcloud logging read \
  'resource.labels.service_name:"prediction-worker" AND
   textPayload:"XGBoost" AND
   timestamp>="2026-01-18T00:00:00Z"' \
  --limit=50 \
  --project nba-props-platform

# Look for:
# - Model file path correct?
# - Model loaded successfully?
# - Any loading errors?
```

### 2. Check Feature Quality (30 min)
```bash
# Check feature completeness for recent dates
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total_records,
  ROUND(100.0 * COUNTIF(points_avg_last_5 IS NOT NULL) / COUNT(*), 1) as pct_points_last_5,
  ROUND(100.0 * COUNTIF(vegas_points_line IS NOT NULL) / COUNT(*), 1) as pct_vegas_line,
  ROUND(100.0 * COUNTIF(opponent_def_rating IS NOT NULL) / COUNT(*), 1) as pct_opp_def
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2026-01-18'
GROUP BY game_date
ORDER BY game_date DESC
"

# Target: All >95% (except vegas ~70%)
# If low → feature extraction issue
```

### 3. Compare Predictions to Training (1 hour)
```bash
# Sample predictions to check reasonableness
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  game_date,
  current_points_line,
  predicted_points,
  confidence_score,
  points_avg_last_5,
  vegas_points_line
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2026-01-18'
ORDER BY RAND()
LIMIT 20
"

# Check:
# - Predictions reasonable given inputs?
# - Confidence scores make sense?
# - Any obvious outliers?
```

### 4. Head-to-Head Comparison (30 min)
```bash
# Compare to CatBoost V8 (same dates)
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNT(*)) * 100, 1) as win_rate
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2026-01-18'
  AND system_id IN ('xgboost_v1', 'catboost_v8')
GROUP BY system_id
ORDER BY mae
"

# If both high → difficult games
# If only xgboost_v1 high → model issue
```

### 5. Check Model Version (15 min)
```bash
# Verify correct model deployed
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.containers[0].env)"

# Look for XGBOOST_V1_MODEL_PATH
# Should be: gs://nba-scraped-data/ml-models/xgboost_v1_33features_20260118_103153.json
```

### 6. Review Training Metrics (15 min)
```bash
# Re-check training logs/results
# Validation MAE: 3.726
# Production expectation: ≤ 4.2

# If production MAE much higher:
# - Feature drift?
# - Different data distribution?
# - Model not generalizing?
```

### 7. Decide on Action (30 min)
Based on findings:
- **Feature issue:** Fix feature extraction, redeploy
- **Model loading:** Fix deployment, verify model file
- **Model underperforms:** Consider rollback, retrain, or accept higher MAE
- **Games were hard:** Wait more days, variance expected

---

## 📋 Quick Reference Checklist

### Daily (Jan 19-23)
- [ ] Run monitoring query (2 min)
- [ ] Record MAE, Win Rate, Volume (1 min)
- [ ] Check alert flags (1 min)
- [ ] Validate grading working (1 min)

### Decision Day (Jan 23)
- [ ] Run 5-day aggregate query
- [ ] Calculate average MAE and Win Rate
- [ ] Determine status: ✅ EXCELLENT / ✅ GOOD / ⚠️ ACCEPTABLE / 🚨 POOR
- [ ] Decide next track based on matrix
- [ ] Update PROGRESS-LOG.md with decision
- [ ] Create handoff for next session

### If Proceeding to Track B
- [ ] Read track-b-ensemble/README.md
- [ ] Review training plan
- [ ] Prepare training environment
- [ ] Schedule 8-10 hour session

### If Proceeding to Track E
- [ ] Read track-e-e2e-testing/README.md
- [ ] Review test scenarios
- [ ] Schedule monitoring checks
- [ ] Plan 5-6 hour validation session

### If Investigating
- [ ] Follow investigation steps 1-7
- [ ] Document findings
- [ ] Determine root cause
- [ ] Plan remediation
- [ ] Update stakeholders

---

## 📊 Expected Outcomes

### Best Case (Likely: 60% probability)
- XGBoost V1 V2 MAE: 3.7-4.0
- Win Rate: 52-56%
- Status: ✅ EXCELLENT or ✅ GOOD
- Decision: → Track B (Ensemble)
- Timeline: Start Track B immediately

### Good Case (Moderate: 25% probability)
- XGBoost V1 V2 MAE: 4.0-4.2
- Win Rate: 50-54%
- Status: ✅ GOOD
- Decision: → Track B (Ensemble)
- Timeline: Start Track B with confidence

### Acceptable Case (Possible: 10% probability)
- XGBoost V1 V2 MAE: 4.2-4.5
- Win Rate: 48-52%
- Status: ⚠️ ACCEPTABLE
- Decision: → Track E first (E2E)
- Timeline: Track E (5-6 hours), then reassess

### Poor Case (Unlikely: 5% probability)
- XGBoost V1 V2 MAE: > 4.5
- Win Rate: < 48%
- Status: 🚨 POOR
- Decision: → Investigate
- Timeline: Investigation (2-4 hours), then decide

---

## 🔗 Key Documents

**Monitoring:**
- [Day 0 Baseline](docs/08-projects/current/prediction-system-optimization/track-a-monitoring/day0-xgboost-v1-v2-baseline-2026-01-18.md)
- [Monitoring Checklist](docs/08-projects/current/prediction-system-optimization/track-a-monitoring/MONITORING-CHECKLIST.md)
- [Daily Queries](docs/08-projects/current/prediction-system-optimization/track-a-monitoring/daily-monitoring-queries.sql)

**Project:**
- [Master Plan](docs/08-projects/current/prediction-system-optimization/MASTER-PLAN.md)
- [Progress Log](docs/08-projects/current/prediction-system-optimization/PROGRESS-LOG.md)
- [Project README](docs/08-projects/current/prediction-system-optimization/README.md)

**Tracks:**
- [Track B README](docs/08-projects/current/prediction-system-optimization/track-b-ensemble/README.md)
- [Track E README](docs/08-projects/current/prediction-system-optimization/track-e-e2e-testing/README.md)

**Investigation:**
- [Investigation (RESOLVED)](docs/08-projects/current/prediction-system-optimization/INVESTIGATION-XGBOOST-GRADING-GAP.md)

---

**Created:** 2026-01-18 (Session 98)
**Status:** ✅ READY TO EXECUTE
**Next Action:** Daily monitoring starting Jan 19
**Decision Point:** Jan 23 (Day 5)
