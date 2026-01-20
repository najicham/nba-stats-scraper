# Prediction System Optimization - TODO List

**Created:** 2026-01-18 (Session 98)
**Last Updated:** 2026-01-19 (Session 112 - Ensemble V1.1 Complete & Operational)
**Current Phase:** System Monitoring + Performance Tracking

---

## ✅ COMPLETED: Ensemble V1.1 Quick Win (Session 110)

**Status:** ✅ COMPLETE & OPERATIONAL (as of Session 112)
**Completion:** Session 110 (Jan 18) - Deployed
**Verification:** Session 112 (Jan 19) - Confirmed Working
**Result:** All 7 prediction systems generating predictions (614 total for Jan 19)

### Completed Implementation ✅
- ✅ Created `ensemble_v1_1.py` with CatBoost V8 as 5th system
- ✅ Implemented fixed performance-based weights:
  - CatBoost V8: 45% (best system)
  - Similarity: 25% (complementarity)
  - Moving Average: 20% (momentum)
  - Zone Matchup: 10% (reduced from 25%)
  - XGBoost: 0% (skip mock)
- ✅ Integrated into `worker.py`
- ✅ Deployed to Cloud Run
- ✅ Verified operational: 91 predictions generated on Jan 19
- ✅ Fixed worker crash (Session 112): Missing google-cloud-firestore dependency

**Reference:**
- Session 110 Handoff: `docs/09-handoff/SESSION-110-ENSEMBLE-V1.1-AND-COMPREHENSIVE-TODOS.md`
- Session 112 Handoff: `docs/09-handoff/SESSION-112-PREDICTION-WORKER-FIRESTORE-FIX.md`

---

## 🚀 CURRENT PRIORITY: Monitor Ensemble V1.1 Performance (Jan 20+)

**Status:** ⏳ READY TO START
**Time Commitment:** 5 minutes/day for 5 days
**Goal:** Validate Ensemble V1.1 achieves expected MAE improvement (5.41 → 4.9-5.1)

---

## 🎯 Updated Priority: Dual System Monitoring (Jan 20-24)

**Status:** ⏳ WAITING TO START
**Time Commitment:** 5 minutes/day for 5 days
**Goal:** Monitor BOTH XGBoost V1 V2 AND Ensemble V1.1 performance

### Daily Tasks (Jan 20-24) - UPDATED TIMELINE

**Note:** NBA games resume Jan 20 (MLK Day weekend had no games)

#### Day 1: Jan 20 (Tuesday) - FIRST MONITORING DAY 🎬
- [ ] **Morning:** Run dual monitoring query (XGBoost V1 V2 + Ensemble V1.1)
- [ ] **Record XGBoost V1 V2:** MAE = ___, Win Rate = ___%, Volume = ___
- [ ] **Record Ensemble V1.1:** MAE = ___, Win Rate = ___%, Volume = ___
- [ ] **Record CatBoost V8:** MAE = ___ (comparison baseline)
- [ ] **Check:** Status flags (✅ GOOD / ⚠️ WARNING / 🚨 CRITICAL)
- [ ] **Validate:**
  - [ ] Both systems generating predictions
  - [ ] Ensemble V1.1 MAE ≤ 5.2 (acceptable first day)
  - [ ] XGBoost V1 V2 MAE ≤ 5.0 (acceptable first day)
  - [ ] Win Rates ≥ 45%
  - [ ] Zero placeholders
- [ ] **Compare:** Ensemble V1 vs V1.1 (improvement visible?)

**Success Criteria:**
- Both systems working ✅
- Ensemble V1.1 shows early improvement signs
- No critical errors

---

#### Day 2: Jan 21 (Wednesday) - STABILITY CHECK
- [ ] **Morning:** Run dual monitoring query
- [ ] **Record Both Systems:** MAE, Win Rate, Volume
- [ ] **Compare:** Day 1 vs Day 2 trends
- [ ] **Check:** Status flags
- [ ] **Validate:**
  - [ ] Consistent volume (200-400 predictions each)
  - [ ] MAE stable or improving
  - [ ] Win Rate ≥ 48%
- [ ] **Head-to-Head:** Ensemble V1.1 beating V1?

**Success Criteria:**
- MAE not increasing
- Ensemble V1.1 performance advantage visible
- Consistent volume

---

#### Day 3: Jan 22 (Thursday) - TREND ANALYSIS
- [ ] **Morning:** Run dual monitoring query
- [ ] **Record Both Systems:** MAE, Win Rate, Volume
- [ ] **Analyze:** 3-day trends for both systems
- [ ] **Calculate:** 3-day averages
- [ ] **Evaluate:** Are trends positive?
- [ ] **Compare:** V1.1 win rate vs V1

**Success Criteria:**
- Clear trends emerging
- Ensemble V1.1 avg MAE ≤ 5.0
- XGBoost V1 V2 avg MAE ≤ 4.5
- Both systems stable

---

#### Day 4: Jan 23 (Friday) - PRE-DECISION
- [ ] **Morning:** Run dual monitoring query
- [ ] **Record Both Systems:** MAE, Win Rate, Volume
- [ ] **Calculate:** 4-day averages
- [ ] **Assess:** Likely decision outcomes?
- [ ] **Prepare:** Decision queries for tomorrow

**Success Criteria:**
- Trends clear and stable
- Preparing for Day 5 decisions

---

#### Day 5: Jan 24 (Saturday) - DUAL DECISION DAY ⭐⭐

**Decision 1: Ensemble V1.1 Promotion**
- [ ] **Morning:** Run 5-day aggregate for Ensemble V1.1
- [ ] **Calculate:**
  - [ ] 5-day avg MAE = ___
  - [ ] 5-day avg Win Rate = ___
  - [ ] Win rate vs Ensemble V1 = ___%
- [ ] **Decide:** Promote Ensemble V1.1?
  - [ ] MAE ≤ 5.0 AND Win rate vs V1 > 55% → ✅ PROMOTE
  - [ ] 5.0 < MAE < 5.2 → ⚠️ KEEP MONITORING
  - [ ] MAE > 5.2 → 🚨 ROLLBACK
- [ ] **Document:** Ensemble V1.1 decision

**Decision 2: XGBoost V1 V2 Next Steps**
- [ ] **Run:** 5-day aggregate for XGBoost V1 V2
- [ ] **Calculate:**
  - [ ] 5-day avg MAE = ___
  - [ ] 5-day avg Win Rate = ___
  - [ ] Std Dev MAE = ___
- [ ] **Decide:** Use decision matrix
  - [ ] MAE ≤ 4.0 → ✅ EXCELLENT → Track B
  - [ ] MAE 4.0-4.2 → ✅ GOOD → Track B
  - [ ] MAE 4.2-4.5 → ⚠️ ACCEPTABLE → Track E first
  - [ ] MAE > 4.5 → 🚨 POOR → Investigate
- [ ] **Consider:** Add XGBoost V1 V2 to Ensemble V1.1?

**Final Tasks:**
- [ ] **Document:** Update PROGRESS-LOG.md with both decisions
- [ ] **Create:** Handoff for next session
- [ ] **Plan:** Schedule next session based on decisions

**Success Criteria:**
- Both decisions made with data
- Next steps documented
- Ready to proceed

---

## 📋 Post-Decision Tasks

### If Decision: ✅ Track B (Ensemble Retraining)

**Estimated Time:** 8-10 hours
**Prerequisites:** XGBoost V1 V2 MAE ≤ 4.2, Win Rate ≥ 50%

#### Phase 1: Planning & Analysis (2 hours)
- [ ] Read track-b-ensemble/README.md thoroughly
- [ ] Review current ensemble architecture
- [ ] Analyze component models (XGBoost V1 V2, CatBoost V8, etc.)
- [ ] Design new ensemble configuration
- [ ] Create training-plan.md document

#### Phase 2: Training Preparation (2 hours)
- [ ] Update training script: ml_models/nba/train_ensemble_v1.py
- [ ] Set XGBoost V1 V2 model path
- [ ] Verify training data available (2021-2025 backfill)
- [ ] Verify component predictions available
- [ ] Configure hyperparameters (Ridge alpha, etc.)
- [ ] Set up train/validation split

#### Phase 3: Model Training (2 hours)
- [ ] Generate base predictions from all 6 systems
- [ ] Train meta-learner (Ridge or Stacking)
- [ ] Monitor training progress
- [ ] Validate results
- [ ] Save model artifacts
- [ ] Compare to validation baseline

#### Phase 4: Validation & Analysis (2 hours)
- [ ] Run out-of-sample testing
- [ ] Head-to-head vs CatBoost V8 (3.40 MAE)
- [ ] Check confidence calibration
- [ ] Analyze meta-learner weights
- [ ] Test OVER/UNDER balance
- [ ] Performance by player tier
- [ ] Document findings in validation-results.md

#### Phase 5: Deployment (2 hours)
- [ ] Upload model to GCS bucket
- [ ] Update prediction worker environment variables
- [ ] Test in staging (if available)
- [ ] Deploy to production
- [ ] Monitor first predictions
- [ ] Verify model loaded correctly
- [ ] Monitor for 24-48 hours
- [ ] Document deployment in deployment-guide.md

**Success Criteria:**
- Ensemble MAE ≤ 3.5 (improvement over current)
- Ideally: MAE ≤ 3.40 (competitive with CatBoost V8)
- No regressions
- Confidence calibration maintained

---

### If Decision: ⚠️ Track E (E2E Testing First)

**Estimated Time:** 5-6 hours over 3-5 days
**Prerequisites:** XGBoost V1 V2 MAE 4.2-4.5 (acceptable but want validation)

#### Setup (1 hour)
- [ ] Read track-e-e2e-testing/README.md
- [ ] Review 7 test scenarios
- [ ] Create test-scenarios.md with schedule
- [ ] Set up monitoring alerts

#### Scenario 1: Happy Path (48-72 hours passive)
- [ ] Monitor daily orchestration at 00:00 UTC
- [ ] Verify Phase 4 processors complete
- [ ] Verify Phase 5 coordinator triggers at 23:00 UTC
- [ ] Check all 6 systems generate predictions
- [ ] Confirm predictions written to BigQuery
- [ ] Verify grading runs next day
- [ ] Document: Zero manual interventions needed?

#### Scenario 2: XGBoost V1 V2 Validation (ongoing)
- [ ] Track daily MAE vs validation (3.726)
- [ ] Compare to CatBoost V8 daily
- [ ] Verify confidence calibration holding
- [ ] Check feature importance stability
- [ ] Document trends

#### Scenario 3: Feature Quality (3 days)
- [ ] Check feature completeness >95%
- [ ] Verify daily updates
- [ ] Validate pace features populating
- [ ] Check value ranges normal
- [ ] Document quality metrics

#### Scenario 4: Coordinator Performance (3 days)
- [ ] Monitor batch loading times (<10s)
- [ ] Check for timeout errors
- [ ] Verify 100% player coverage
- [ ] Confirm Session 102 fix working
- [ ] Document performance

#### Scenario 5: Grading & Alerts (3 days)
- [ ] Verify grading coverage >70%
- [ ] Test coverage alert triggers correctly
- [ ] Check games graded within 24h
- [ ] Confirm metrics calculating
- [ ] Document alert behavior

#### Final Report (1 hour)
- [ ] Compile all test results
- [ ] Create final-report.md
- [ ] Update production-readiness-checklist.md
- [ ] Make go/no-go decision for Track B
- [ ] Document recommendation

**Success Criteria:**
- 100% autonomous operation (no manual intervention)
- All systems healthy
- Grading coverage >70%
- XGBoost V1 V2 stabilized
- Ready to proceed to Track B

---

### If Decision: 🚨 Investigate Model Issues

**Estimated Time:** 2-4 hours
**Prerequisites:** XGBoost V1 V2 MAE > 4.5 or Win Rate < 48%

#### Step 1: Verify Model Loading (30 min)
- [ ] Check worker logs for model loading
- [ ] Verify model file path correct
- [ ] Check for loading errors
- [ ] Confirm model loaded successfully
- [ ] Document findings

#### Step 2: Check Feature Quality (30 min)
- [ ] Query feature completeness for recent dates
- [ ] Check for NULL rates higher than expected
- [ ] Verify feature value ranges
- [ ] Compare to training data distribution
- [ ] Document quality issues

#### Step 3: Compare Predictions to Training (1 hour)
- [ ] Sample recent predictions
- [ ] Check prediction reasonableness
- [ ] Verify confidence scores make sense
- [ ] Look for outliers
- [ ] Compare to validation predictions
- [ ] Document anomalies

#### Step 4: Head-to-Head Comparison (30 min)
- [ ] Compare XGBoost V1 V2 to CatBoost V8 (same dates)
- [ ] Check if both systems have high MAE (difficult games)
- [ ] Or if only XGBoost V1 V2 high (model issue)
- [ ] Document comparison

#### Step 5: Check Model Version (15 min)
- [ ] Verify correct model deployed via gcloud
- [ ] Check XGBOOST_V1_MODEL_PATH environment variable
- [ ] Confirm using correct model file
- [ ] Document deployment state

#### Step 6: Review Training Metrics (15 min)
- [ ] Re-check validation MAE (3.726)
- [ ] Compare to production MAE
- [ ] Calculate degradation percentage
- [ ] Check if within tolerance
- [ ] Document gap analysis

#### Step 7: Decide on Action (30 min)
- [ ] Based on findings, determine root cause:
  - [ ] Feature quality issue → Fix extraction, redeploy
  - [ ] Model loading issue → Fix deployment
  - [ ] Model genuinely underperforms → Consider rollback or retrain
  - [ ] Games were difficult → Wait for more data
- [ ] Document decision
- [ ] Create action plan
- [ ] Update stakeholders

**Success Criteria:**
- Root cause identified
- Action plan created
- Decision made (fix, rollback, wait)
- Next steps clear

---

## 📚 Reference Checklist

### Before Each Session
- [ ] Read PLAN-NEXT-SESSION.md
- [ ] Check PROGRESS-LOG.md for latest status
- [ ] Review previous day's results (if multi-day)
- [ ] Have monitoring queries ready

### Daily Monitoring Essentials
- [ ] BigQuery access working
- [ ] Queries ready to run
- [ ] Recording spreadsheet/doc ready
- [ ] Alert thresholds memorized

### Decision Day Prep
- [ ] All 5 days of data collected
- [ ] Aggregate query tested
- [ ] Decision matrix printed/available
- [ ] Next session time blocked

### Track B Prep (if going that route)
- [ ] Training script reviewed
- [ ] Training data verified available
- [ ] GCS bucket access confirmed
- [ ] 8-10 hours scheduled

### Track E Prep (if going that route)
- [ ] Test scenarios understood
- [ ] 3-5 day period scheduled
- [ ] Monitoring set up
- [ ] 5-6 hours spread over days scheduled

---

## 🎯 Long-Term Roadmap

### Week 1 (Jan 19-25)
- [x] Track A: Monitoring setup (COMPLETE)
- [x] Track D: Pace features (COMPLETE - already implemented!)
- [ ] Track A: Daily monitoring (Jan 19-23)
- [ ] Decision: Track B or E (Jan 23)

### Week 2-3 (Jan 26 - Feb 8)
- [ ] Track B: Ensemble retraining (8-10 hours)
- [ ] Track E: E2E testing (5-6 hours) - if not done Week 1
- [ ] Track A: Continue XGBoost V1 V2 monitoring

### Week 4+ (Feb 9+)
- [ ] Track C: Infrastructure monitoring (10-12 hours)
  - [ ] Model performance alerts
  - [ ] Infrastructure health alerts
  - [ ] Data quality monitoring
  - [ ] Real-time dashboards
  - [ ] 4 comprehensive runbooks

---

## ✅ Completed Tasks

### Session 112 (Jan 19) 🎉
- [x] **Fixed 37-hour prediction pipeline outage**
- [x] **Root cause:** Missing `google-cloud-firestore==2.14.0` dependency
- [x] **Solution:** Added dependency, deleted/redeployed worker from scratch
- [x] **Verified:** All 7 systems operational including Ensemble V1.1
- [x] **Predictions:** 614 total (91 per system, 69 for similarity)
- [x] **Session 107 metrics:** Confirmed 100% populated for Jan 19
- [x] **Documentation:** Comprehensive handoff with lessons learned
- [x] Reference: `docs/09-handoff/SESSION-112-PREDICTION-WORKER-FIRESTORE-FIX.md`

### Session 111 (Jan 19)
- [x] **Deployed Session 107 metrics** (7 new variance + star tracking features)
- [x] **Fixed analytics processor** schema evolution
- [x] **Fixed prediction coordinator** deployment script
- [x] **Investigated prediction failures** (fixed in Session 112)
- [x] Reference: `docs/09-handoff/SESSION-111-SESSION-107-METRICS-AND-PREDICTION-DEBUGGING.md`

### Session 110 (Jan 18)
- [x] **Implemented Ensemble V1.1** with performance-based weights
- [x] **Added CatBoost V8** to ensemble (45% weight)
- [x] **Deployed to production** (revision 00072-cz2)
- [x] **Expected improvement:** MAE 5.41 → 4.9-5.1 (6-9% better)
- [x] **Integration complete:** All 7 systems configured
- [x] Reference: `docs/09-handoff/SESSION-110-ENSEMBLE-V1.1-AND-COMPREHENSIVE-TODOS.md`

### Session 109 (Jan 18 - Afternoon/Evening)
- [x] **Deep system analysis** via 3 parallel agents (documentation, architecture, monitoring)
- [x] **Performance analysis** discovered Ensemble V1 flaw (excludes CatBoost, includes poor Zone Matchup)
- [x] **Root cause identified:** Ensemble V1 performs 12.5% worse than best system (should be better!)
- [x] **Strategic planning:** Evaluated 3 approaches, chose Quick Win
- [x] **Ridge meta-learner training script created** (377 lines, saved for future use)
- [x] **Ensemble V1.1 implementation plan created** (580+ lines, step-by-step guide)
- [x] **Documentation created:**
  - Performance analysis report (14 sections, comprehensive)
  - Ensemble retraining recommendations
  - Reusable BigQuery analysis queries
  - Complete implementation plan with test scripts
- [x] Updated TODO.md with Ensemble V1.1 priority
- [x] Total deliverables: 6 documents, ~3,000 lines of code/docs

### Session 98 (Jan 18 - Morning)
- [x] Investigated "XGBoost grading gap" (RESOLVED - not a bug)
- [x] Discovered 6-system concurrent architecture
- [x] Established XGBoost V1 V2 Day 0 baseline
- [x] Created 5-day monitoring checklist
- [x] Created comprehensive next session plan
- [x] Updated all project documentation
- [x] Marked Investigation as RESOLVED
- [x] Updated track priorities
- [x] Pushed all changes to remote

### Previous Sessions
- [x] Session 90: Project setup and structure
- [x] Session 88-89: XGBoost V1 V2 training and deployment
- [x] Session 102: Coordinator optimizations (batch loading)
- [x] Session 103: Team pace features (already implemented)

---

## 🔗 Quick Links

**Daily Monitoring:**
- [Next Session Plan](./PLAN-NEXT-SESSION.md) ⭐ **START HERE**
- [Monitoring Checklist](./track-a-monitoring/MONITORING-CHECKLIST.md)
- [Daily Queries](./track-a-monitoring/daily-monitoring-queries.sql)
- [Day 0 Baseline](./track-a-monitoring/day0-xgboost-v1-v2-baseline-2026-01-18.md)

**Project Docs:**
- [Master Plan](./MASTER-PLAN.md)
- [Progress Log](./PROGRESS-LOG.md)
- [Project README](./README.md)

**Track READMEs:**
- [Track B (Ensemble)](./track-b-ensemble/README.md)
- [Track E (E2E Testing)](./track-e-e2e-testing/README.md)
- [Track C (Infrastructure)](./track-c-infrastructure/README.md)

**Handoffs:**
- [Session 98 Handoff](../../09-handoff/SESSION-98-DOCS-WITH-REDACTIONS.md)
- [Investigation (RESOLVED)](./INVESTIGATION-XGBOOST-GRADING-GAP.md)

---

**Last Updated:** 2026-01-18
**Next Update:** After Day 5 decision (Jan 23)
**Status:** ⏳ Ready for daily monitoring
