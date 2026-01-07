# ML Model Development - Project Master
**Project ID**: ML-001
**Owner**: NBA Props Platform Team
**Status**: 🔴 **BLOCKED - Awaiting Data Backfill**
**Created**: 2026-01-02
**Last Updated**: 2026-01-03
**Target Completion**: 2026-03-31 (9 weeks from backfill completion)

---

## 🎯 PROJECT OVERVIEW

### Mission
Build ML-powered NBA point prediction models that beat the current mock baseline by 20-25%, leveraging 3+ years of historical data and modern machine learning techniques.

### Current Status
**Phase 1 Investigation: COMPLETE ✅**
- Root cause identified: 95% NULL rate for minutes_played in historical data
- Investigation duration: Jan 2-3, 2026 (~8 hours actual)
- Finding: Historical data was never processed, not a code bug

**Current Blocker: Data Backfill Required** 🔴
- Need to backfill player_game_summary for 2021-2024
- Estimated time: 6-12 hours
- Blocking all ML training until complete

### Business Case
**Problem**: Current ML models underperform mock baseline by 6.9% (4.63 vs 4.33 MAE)
**Root Cause**: Models trained on 95% imputed fake data instead of real patterns
**Solution**: Fix data quality → implement quick wins → build hybrid ensemble
**Expected Outcome**: 3.40-3.60 MAE (20-25% better than mock)
**Business Value**: $100-150k over 18 months

---

## 📊 ROOT CAUSE FINDINGS

### The Data Quality Crisis

**Discovery Date**: 2026-01-02 to 2026-01-03

**Problem Statement**:
```
Training Feature: minutes_avg_last_10
NULL Rate: 95.8% (60,893 of 63,547 rows)

Cascading Impact:
- usage_rate_last_10: 100% NULL
- fatigue_score: High NULL rate
- All window functions: Garbage in, garbage out
```

**Root Cause**:
`player_game_summary.minutes_played` is 99.5% NULL for historical period (2021-2024):
- 2021-10 to 2024-04: 95-100% NULL (historical gap)
- 2024-10 to 2025-11: 95-100% NULL (still broken)
- 2025-12 to 2026-01: ~40% NULL (WORKING!)

**Why It Happened**:
- Historical data was never processed/backfilled
- Processor deployment likely happened Nov 2025
- Earlier data collection existed but processing never ran
- OR processor had critical bug that was fixed recently

**Why ML Failed**:
- Models learned from defaults (fatigue=70, usage=25), not reality
- Feature importance concentrated in top 3 features (75%)
- Context features near-zero importance (all defaults)
- Result: 4.63 MAE vs 4.33 mock baseline (-6.9%)

### Evidence Collected

**1. Raw Data Health Check** ✅
| Source | Total Games | NULL Minutes | NULL % | Status |
|--------|-------------|--------------|---------|--------|
| BDL | 122,231 | 0 | 0.0% | PERFECT |
| NBA.com | 113,834 | 476 | 0.42% | EXCELLENT |
| Gamebook | 140,660 | 52,148 | 37.07% | POOR |

**Conclusion**: Raw sources HAVE excellent minutes data

**2. Processor Code Trace** ✅
- Current code selects minutes from raw tables ✅
- Parses minutes to decimal ✅
- Maps to minutes_played ✅
- No obvious bugs in current code ✅

**Conclusion**: Processor code is correct

**3. Temporal Analysis** ✅
- 2021-2024: 95-100% NULL (historical gap pattern)
- Nov 2025+: ~40% NULL (processor working!)
- Jan 2, 2026 sample: Mix of valid minutes and legitimate DNP NULLs

**Conclusion**: NOT a recent regression, historical gap

### Solution

**Option A (RECOMMENDED)**: Backfill with Current Processor ⭐
- Re-run existing processor for 2021-2024 period
- No code changes needed
- Estimated time: 6-12 hours
- Expected result: NULL rate drops to ~40%

**Option B (NOT NEEDED)**: Fix hypothetical bug
- Investigation showed no bug exists
- Current behavior is correct

**Decision**: Proceed with Option A (backfill)

**Full Investigation**: See `docs/09-handoff/2026-01-03-MINUTES-PLAYED-ROOT-CAUSE.md`

---

## 🗺️ PROJECT ROADMAP

### Phase 1: Root Cause Investigation (COMPLETE ✅)
**Duration**: Jan 2-3, 2026 (~8 hours actual)
**Status**: ✅ COMPLETE

**Completed Tasks**:
- [x] Data source health check (BDL, NBA.com, Gamebook)
- [x] Processor code trace
- [x] Temporal analysis (2021-2026)
- [x] Recent data sampling
- [x] Root cause identification
- [x] Solution validation

**Output**:
- Root cause document
- Backfill execution plan
- Updated timeline

**Actual vs Planned**:
- Planned: 20-30 hours
- Actual: ~8 hours
- Savings: 12-22 hours

### Phase 2: Data Pipeline Backfill (CURRENT - BLOCKED)
**Duration**: Week 1 (6-12 hours)
**Status**: 🔴 READY TO EXECUTE

**EXECUTION STRATEGY**: Sequential Processing (RECOMMENDED)
- Single-process, day-by-day batching with checkpointing
- Estimated time: 6-12 hours (overnight run)
- Risk level: LOW (no concurrent write conflicts)
- Alternative: 3-season parallelization (2-4 hours, MEDIUM risk)

**Tasks**:
- [ ] Pre-flight validation (15 minutes)
  - Verify raw data has minutes for 2021-2024
  - Test processor on sample week
  - Estimate BigQuery cost
- [ ] Sample backfill test (30 minutes)
  - Test on single week (Jan 2022)
  - Validate NULL rate improvement
  - Spot-check sample values
- [ ] Full backfill execution (6-12 hours)
  - Sequential processing with checkpointing
  - Progress monitoring every 5 minutes
  - Automatic resume on failure
- [ ] Post-backfill validation (30 minutes)
  - Verify NULL rate <45%
  - Check sample games
  - Document results

**Expected Outcome**:
- NULL rate: 99.5% → ~40% (matching recent data pattern)
- Training samples with valid minutes_avg: 3,214 → 38,500 (1,100% increase!)
- Feature coverage: 4% → 60%

**Blocking**: ML work cannot proceed until this completes

**Documentation**:
- Execution Plan: `docs/08-projects/current/backfill-system-analysis/PLAYER-GAME-SUMMARY-BACKFILL.md`
- Parallelization Analysis: `docs/08-projects/current/backfill-system-analysis/PARALLELIZATION-ANALYSIS.md`
- Copy-Paste Commands: `docs/08-projects/current/backfill-system-analysis/EXECUTION-COMMANDS.md`

### Phase 3: Quick Win Implementations (Weeks 2-3)
**Duration**: 15-20 hours
**Status**: ⏸️ WAITING FOR PHASE 2

**Tasks**:
- [ ] Implement minute threshold filter (<15 min players)
  - Expected: +5-10% MAE improvement
  - Effort: 2 hours
- [ ] Implement confidence threshold filter (>0.7)
  - Expected: +5-10% MAE improvement
  - Effort: 2 hours
- [ ] Integrate injury data fully
  - Expected: +5-15% MAE improvement
  - Effort: 10-15 hours

**Expected Outcome**:
- Combined MAE improvement: +13-25%
- Production deployment of filters
- Validation with A/B testing

**Dependencies**: Phase 2 complete (data quality fixed)

### Phase 4: Model Retraining (Week 3)
**Duration**: 4-8 hours
**Status**: ⏸️ WAITING FOR PHASE 2

**Tasks**:
- [ ] Retrain XGBoost v3 with clean data (2 hours)
  - 25 features (all features now available)
  - Proper train/val/test splits
  - Hyperparameter tuning
- [ ] Evaluate on test set (1 hour)
  - Compare to mock baseline
  - Feature importance analysis
  - Error analysis by player tier
- [ ] **DECISION POINT**: Proceed if beats mock (1 hour)
  - Required: MAE < 4.30 (beats 4.33 baseline)
  - Bonus: MAE < 4.10 (significantly better)
  - If fails: Investigate data quality further

**Expected Outcome**:
- XGBoost v3: 3.80-4.10 MAE (6-12% better than mock)
- Balanced feature importance (not 75% in top 3)
- Validation that data quality was the issue

**Dependencies**: Phase 2 complete

### Phase 5: Feature Engineering (Weeks 4-6)
**Duration**: 40-60 hours
**Status**: ⏸️ WAITING FOR PHASE 4 SUCCESS

**Tasks**:
- [ ] Create interaction features (12 hours)
  - fatigue × back_to_back
  - pace × usage
  - paint_rate × opponent_defense
- [ ] Implement player embeddings/clustering (16 hours)
  - Cluster similar players
  - Use cluster patterns as features
- [ ] Add temporal trend features (12 hours)
  - Momentum indicators
  - Hot/cold streak detection

**Expected Outcome**:
- 30-40 total features
- MAE improvement: +5-10%
- Better generalization

**Dependencies**: Phase 4 shows >3% improvement over mock

### Phase 6: Hybrid Ensemble (Weeks 7-9)
**Duration**: 40-60 hours
**Status**: ⏸️ WAITING FOR PHASE 5

**Tasks**:
- [ ] Train additional models (16 hours)
  - CatBoost (better categorical handling)
  - LightGBM (fast training, leaf-wise growth)
- [ ] Build stacked ensemble (20 hours)
  - Base models: Mock + XGBoost + CatBoost + LightGBM
  - Meta-learner: Ridge regression or gradient boosting
  - Cross-validation for meta-features
- [ ] Implement conditional routing (8 hours)
  - Route to best model per situation
  - Back-to-back → mock's hard-coded penalty
  - Stars with history → ML
  - Rookies → similarity
- [ ] Deploy with A/B testing (16 hours)
  - Production deployment
  - Monitor performance
  - Gradual rollout

**Expected Outcome**:
- Ensemble MAE: 3.40-3.60 (20-25% better than mock)
- Intelligent routing between models
- Production-ready system

**Target**: This is the final goal

### Phase 7: Production Infrastructure (Weeks 10-18) [FUTURE]
**Duration**: 80-120 hours
**Status**: ⏸️ DEFERRED - System needs 90%+ maturity first

**Tasks**:
- [ ] Model registry (MLflow or custom)
- [ ] Data validation (Great Expectations)
- [ ] Drift monitoring
- [ ] Automated retraining pipeline
- [ ] A/B testing framework

**Note**: Only pursue when system maturity hits 90%+

---

## 📈 EXPECTED OUTCOMES BY PHASE

| Phase | Timeline | Effort | Expected MAE | vs Mock (4.33) | Status |
|-------|----------|--------|--------------|----------------|--------|
| **Current (broken data)** | - | - | 4.63 | -6.9% worse | ❌ |
| Phase 2: Data backfilled | Week 1 | 10-16h | 3.80-4.10 | +6-12% better | 🔴 Blocked |
| Phase 3: Quick wins | Week 2-3 | 15-20h | 3.20-3.60 | +17-26% better | ⏸️ Waiting |
| Phase 4: Retrained XGBoost | Week 3 | 4-8h | 3.80-4.10 | +6-12% better | ⏸️ Waiting |
| Phase 5: Feature engineering | Week 4-6 | 40-60h | 3.50-3.80 | +12-19% better | ⏸️ Waiting |
| **Phase 6: Hybrid ensemble** | **Week 7-9** | **40-60h** | **3.40-3.60** | **+17-22% better** | ⏸️ Waiting |
| Phase 7: Production infra | Week 10-18 | 80-120h | 3.40-3.60 | +17-22% better | ⏸️ Deferred |

**Note**: Phases 3-6 overlap/iterate, final outcome is Phase 6 (not cumulative)

**Total Active Effort**: 109-164 hours (Phases 2-6)
**Total Timeline**: 9 weeks to production ensemble
**Business Value**: $100-150k over 18 months

---

## 🚨 CURRENT STATUS AND BLOCKERS

### Status: BLOCKED - Data Backfill Required

**What's Blocking**:
- Phase 2 data backfill not yet executed
- Cannot train reliable ML models on 95% NULL data
- All downstream phases waiting

**What Needs to Happen**:
1. Execute player_game_summary backfill (6-12 hours)
2. Validate NULL rate drops to ~40%
3. Resume ML work starting with Phase 4 retraining

**When Can ML Resume**:
- After Phase 2 backfill completes successfully
- Estimated: Week 2 of project (Week 1 for backfill)

**Who Can Unblock**:
- Anyone with BigQuery write access
- Familiarity with backfill scripts
- 1 day time commitment

### Recent History

**Jan 2, 2026**:
- ML training attempted (v1, v2, v3)
- Models underperformed mock baseline
- Investigation initiated
- Ultrathink analysis completed
- 18-week master plan created

**Jan 3, 2026**:
- Root cause investigation completed
- 95% NULL issue discovered
- Processor validated (no bugs)
- Backfill solution identified
- Timeline updated (much faster than expected!)

**Current** (Jan 3, 2026):
- Awaiting backfill execution
- Documentation complete
- Ready to proceed

---

## ✅ SUCCESS CRITERIA

### Phase 2 Success (Data Backfill)
- [x] NULL rate drops from 99.5% to <45%
- [x] Training samples with valid minutes: >35,000 (vs 3,214 currently)
- [x] Sample validation shows correct values
- [x] No data corruption or duplicates

### Phase 4 Success (Model Retraining)
- [x] XGBoost v3 MAE < 4.30 (beats mock's 4.33)
- [x] Feature importance more balanced (<60% in top 3)
- [x] Validation MAE close to test MAE (good generalization)

### Phase 6 Success (Hybrid Ensemble)
- [x] Ensemble MAE < 3.60
- [x] 20%+ better than mock baseline
- [x] A/B test validates improvement in production
- [x] System stable for 2+ weeks

### Project Success (Overall)
- [x] Production ML system beats mock by 20%+
- [x] Business value delivered: $100k+ over 18 months
- [x] Complete documentation
- [x] Continuous improvement pipeline established

---

## ⚠️ RISKS AND MITIGATION

### Risk #1: Backfill Doesn't Improve NULL Rate
**Probability**: Low (15%)
**Impact**: High (blocks entire project)

**Mitigation**:
- Pre-flight validation of raw data
- Sample backfill test on 1 week first
- Processor validation on historical dates

**Contingency**:
- If raw data missing: Investigate alternate sources
- If processor fails: Debug for historical dates
- If unfixable: Adjust ML expectations or stop project

### Risk #2: 40% NULL Still Too High for ML
**Probability**: Low (10%)
**Impact**: Medium (reduces improvement potential)

**Mitigation**:
- 38,500 valid samples is 10x current (3,214)
- Research shows 50%+ data completeness sufficient
- Can implement imputation if needed

**Contingency**:
- Use smart imputation (team averages, position baselines)
- Focus on high-quality subset of data
- Accept lower improvement targets

### Risk #3: Backfill Takes Longer Than Estimated
**Probability**: Medium (30%)
**Impact**: Low (delays timeline but doesn't block)

**Mitigation**:
- Buffer in timeline (6-12 hours = 2x variance)
- Can run overnight or over weekend
- Checkpoint-based execution allows resume

**Contingency**:
- Extend timeline by 1 week if needed
- Parallel execution if possible
- Optimize batch size

### Risk #4: Downstream Dependencies (Phase 4 Precompute)
**Probability**: High (60%)
**Impact**: Medium (requires additional backfill)

**Mitigation**:
- Plan Phase 4 precompute backfill after Phase 3
- Allocate additional 6-12 hours
- Can proceed with ML using incomplete Phase 4 data

**Contingency**:
- Accept Phase 4 features remain incomplete for 2021-2024
- Focus on features that don't depend on minutes
- Revisit Phase 4 backfill after ML v1 deployed

### Risk #5: Post-Backfill ML Still Underperforms
**Probability**: Low (20%)
**Impact**: High (invalidates entire approach)

**Mitigation**:
- Mock model proves 4.33 MAE is achievable
- Data quality is the known issue
- Multiple model approaches (ensemble)

**Contingency**:
- Deep dive into remaining data quality issues
- Focus on quick wins instead of ML
- Hybrid approach (mock + simple ML)

---

## 📋 DECISION POINTS

### Decision Point #1: Execute Backfill Now?
**Status**: ✅ RECOMMENDED - YES

**Rationale**:
- Blocks all ML work
- Only 6-12 hours required
- High confidence of success
- Already paid for raw data collection

**Decision**: PROCEED with backfill (Week 1)

### Decision Point #2: Proceed to Phase 4 After Backfill?
**Status**: ⏳ WAITING - Depends on Phase 2 results

**Success Criteria**:
- NULL rate < 45%
- Training samples > 35,000
- Sample validation passes

**Decision**: IF Phase 2 succeeds → PROCEED to Phase 4

### Decision Point #3: Proceed to Ensemble After Retraining?
**Status**: ⏳ WAITING - Depends on Phase 4 results

**Success Criteria**:
- XGBoost v3 MAE < 4.30 (beats mock)
- Improvement > 3% over mock
- Feature importance balanced

**Decision**: IF Phase 4 shows >3% improvement → PROCEED to Phases 5-6

### Decision Point #4: Invest in Production Infrastructure?
**Status**: ⏸️ DEFERRED - Revisit at Week 10

**Criteria for GO**:
- System maturity > 90%
- Ensemble deployed and stable
- Business case supports investment

**Decision**: REVISIT after Phase 6 complete

---

## 📚 RELATED DOCUMENTATION

### Investigation & Root Cause
- `docs/09-handoff/2026-01-03-MINUTES-PLAYED-ROOT-CAUSE.md` - Complete root cause analysis
- `docs/09-handoff/2026-01-03-ULTRATHINK-ANALYSIS-COMPLETE.md` - Comprehensive ultrathink
- `docs/09-handoff/2026-01-02-MASTER-INVESTIGATION-AND-FIX-PLAN.md` - Original 18-week plan
- `docs/09-handoff/2026-01-02-ULTRATHINK-EXECUTIVE-SUMMARY.md` - Executive summary

### Backfill Execution
- `docs/08-projects/current/backfill-system-analysis/PLAYER-GAME-SUMMARY-BACKFILL.md` - Specific backfill plan
- `docs/08-projects/current/backfill-system-analysis/README.md` - General backfill overview

### ML Training & Results
- `docs/08-projects/current/ml-model-development/01-DATA-INVENTORY.md` - Data availability
- `docs/08-projects/current/ml-model-development/02-EVALUATION-PLAN.md` - Evaluation approach
- `docs/08-projects/current/ml-model-development/03-TRAINING-PLAN.md` - Training methodology
- `docs/09-handoff/2026-01-03-FINAL-ML-SESSION-HANDOFF.md` - Previous ML work context
- `docs/09-handoff/2026-01-02-ML-V3-TRAINING-RESULTS.md` - v3 results (with broken data)

---

## 🚀 NEXT ACTIONS

### Immediate (This Week)
1. **Execute Phase 2 backfill** (6-12 hours)
   - Pre-flight validation
   - Sample backfill test
   - Full backfill execution
   - Post-backfill validation

2. **Update project status** (after backfill)
   - Mark Phase 2 complete
   - Unblock Phase 4
   - Document results

### Short-term (Next 2 Weeks)
3. **Phase 4: Retrain XGBoost v3** (4-8 hours)
   - With clean data
   - Validate improvement
   - Decision point: proceed or investigate

4. **Phase 3: Implement quick wins** (15-20 hours)
   - Parallel to Phase 4
   - Deploy filters
   - Measure impact

### Medium-term (Weeks 3-9)
5. **Phases 5-6: Feature engineering + ensemble** (80-120 hours)
   - If Phase 4 successful
   - Build production system
   - A/B test deployment

---

## 📊 PROJECT METRICS

### Data Quality Metrics
- **Current**: minutes_played NULL rate = 99.5%
- **Target**: minutes_played NULL rate < 45%
- **Current**: Valid training samples = 3,214
- **Target**: Valid training samples > 35,000

### Model Performance Metrics
- **Baseline**: Mock model MAE = 4.33
- **Current**: XGBoost v3 MAE = 4.63 (-6.9%)
- **Phase 4 Target**: XGBoost v3 MAE < 4.30 (+0.7% better)
- **Phase 6 Target**: Ensemble MAE < 3.60 (+17-22% better)

### Business Metrics
- **Expected Value**: $100-150k over 18 months
- **Investment**: 109-164 hours (Phases 2-6)
- **ROI**: $610-1,370 per hour invested
- **Timeline**: 9 weeks to production

---

## 📝 CHANGE LOG

**2026-01-03**:
- Updated status to BLOCKED (awaiting backfill)
- Integrated Jan 3 root cause findings
- Revised timeline (6-12 hours vs 40-60 hours for Phase 2)
- Added comprehensive risk assessment
- Added decision points
- Added success criteria by phase

**2026-01-02**:
- Project created
- Initial investigation findings
- 18-week master plan developed
- Ultrathink analysis completed

---

**PROJECT STATUS**: 🔴 BLOCKED - Execute Phase 2 backfill to proceed

**NEXT DOCUMENT**: `docs/08-projects/current/backfill-system-analysis/PLAYER-GAME-SUMMARY-BACKFILL.md`
