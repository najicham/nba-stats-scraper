# ULTRATHINK: ML Strategy & Execution Plan

**Date**: January 8, 2026, 7:00 PM PST
**Context**: XGBoost v5 underperformed (4.63 vs 4.32 mock baseline)
**Purpose**: Strategic analysis and pragmatic path forward
**Priority**: HIGH - Define ML roadmap for next 3 months

---

## SITUATION ANALYSIS

### Current State
- ✅ Mock model: 4.32 MAE (beats 4.27 baseline)
- ❌ XGBoost v5: 4.63 MAE (7.3% worse than mock)
- ✅ Data quality improved: usage_rate 47% → 95%
- ⚠️ Precompute coverage: 77-90% for training period (2021-2024)
- ✅ Production system working: Predictions flowing via mock

### Why This Happened
1. **Incomplete training data**: 10-23% of precompute features missing
2. **Mock is sophisticated**: Hand-tuned expert system with domain knowledge
3. **Historical vs current data gap**: Training on old incomplete data, testing on newer complete data

### Strategic Question
**"Should we build real ML or improve the mock?"**

Wrong question. Real question:

**"How do we achieve 4.0-4.1 MAE in the next 3 months?"**

---

## ULTRATHINK ANALYSIS

### Perspective 1: Business Value

**Current ROI:**
- Mock model cost: ~40 hours development (sunk cost)
- Mock performance: 4.32 MAE (acceptable)
- Mock maintenance: Low (just code, no data dependencies)
- **Business outcome**: Predictions working, users satisfied

**ML Investment So Far:**
- Data pipeline fixes: ~60 hours
- Training attempts: ~20 hours
- Infrastructure: ~40 hours
- **Total**: ~120 hours invested
- **Business outcome**: No better predictions yet

**Key Insight**: We've spent 3× more time on ML infrastructure than mock development, with worse results.

**But**: Infrastructure improvements benefit entire platform (analytics, reporting, monitoring).

**Conclusion**: ML investment has secondary value even if predictions don't improve.

---

### Perspective 2: Technical Debt

**Mock Model Debt:**
- ✅ Pro: Interpretable, explainable, maintainable
- ✅ Pro: No data dependencies (works even if pipelines break)
- ✅ Pro: Fast inference (pure Python, no model loading)
- ❌ Con: Hard to improve systematically
- ❌ Con: Doesn't leverage historical data
- ❌ Con: Manual tuning required for each change
- ❌ Con: Doesn't scale to new features/leagues

**ML Model Debt:**
- ✅ Pro: Learns from data automatically
- ✅ Pro: Scales to new features
- ✅ Pro: Improves as data quality improves
- ❌ Con: Black box (hard to debug)
- ❌ Con: Requires complete features
- ❌ Con: Training pipeline maintenance
- ❌ Con: Model versioning, deployment complexity

**Key Insight**: Mock has low operational debt but high evolution debt. ML has high operational debt but low evolution debt.

**Conclusion**: Choose based on time horizon:
- Short-term (3-6 months): Mock wins (lower operational cost)
- Long-term (1-2 years): ML wins (easier to evolve)

---

### Perspective 3: Data Quality Reality Check

**Historical Data (2021-2024) - Training Period:**
| Feature Source | Coverage | Quality |
|----------------|----------|---------|
| player_game_summary | 100% | ✅ Excellent (after fixes) |
| team_offense_game_summary | 99% | ✅ Excellent (after game_id fix) |
| player_composite_factors | 89% | ⚠️ Good but incomplete |
| team_defense_zone_analysis | 86% | ⚠️ Good but incomplete |
| player_daily_cache | 77% | ⚠️ Acceptable but gaps |

**Recent Data (2024-2026) - Production Period:**
| Feature Source | Coverage | Quality |
|----------------|----------|---------|
| All Phase 3 | 99% | ✅ Excellent |
| All Phase 4 | 95%+ | ✅ Excellent (recently fixed) |

**Key Insight**: We have a **data quality time gap**:
- Historical data: Good but incomplete (77-89% coverage)
- Recent data: Excellent (95%+ coverage)

**This explains everything:**
- Mock evaluated on recent data → sees complete features → performs well
- XGBoost trained on historical data → sees incomplete features → learns poorly

**Conclusion**: XGBoost will likely perform MUCH better if:
1. Trained on 2024-2026 data (but only 1.5 years - small dataset)
2. OR we backfill precompute for 2021-2024 (large dataset with complete features)

---

### Perspective 4: Competitive Advantage

**What Mock Does Well:**
- Baseline predictions (weighted averages)
- Known adjustments (fatigue, defense, venue)
- Standard scenarios (starters, normal minutes)

**What Mock Does Poorly:**
- Edge cases (role changes, injury returns)
- Non-linear interactions (3+ features)
- Temporal patterns (streaks, momentum)
- Opponent-specific adjustments (beyond defense rating)
- Context beyond encoded rules

**What ML Could Do Better:**
- Discover hidden patterns in data
- Learn complex interactions automatically
- Adapt to meta changes (rule changes, play styles)
- Personalize predictions per player archetype
- Handle rare scenarios via similar examples

**Key Insight**: Mock has high baseline performance, ML has higher ceiling.

**Analogy**:
- Mock = Expert chess player using opening theory
- ML = AlphaZero learning from scratch

In chess, AlphaZero wins. In sports betting? Unknown.

**Conclusion**: We don't know if ML ceiling is high enough to justify investment without trying with complete data.

---

### Perspective 5: Resource Efficiency

**Option A: Improve Mock** (Recommended Short-term)
- Time: 4-6 hours
- Resources: 1 engineer, no infra changes
- Risk: Low (code changes only)
- Expected MAE: 4.0-4.2
- Confidence: High (70-80%)
- Reversible: Yes (can always revert)

**Option B: Backfill + Retrain** (Recommended Long-term)
- Time: 16-24 hours (backfill 12h, retrain 4h, validate 4h, deploy 4h)
- Resources: 1 engineer + compute costs
- Risk: Medium (backfill could fail, model might still lose)
- Expected MAE: 3.9-4.2
- Confidence: Medium (50-60%)
- Reversible: Yes (keep mock as fallback)

**Option C: Hybrid Approach** (Creative Alternative)
- Time: 6-8 hours
- Resources: 1 engineer
- Risk: Low (both systems available)
- Expected MAE: 4.0-4.1
- Confidence: Medium-High (60-70%)
- Architecture: `final_prediction = mock_prediction + ml_residual_correction`

**Option D: Feature Engineering** (Experimental)
- Time: 8-12 hours
- Resources: 1 engineer + domain expert
- Risk: Medium-High (may not work)
- Expected MAE: 4.2-4.5
- Confidence: Low (30-40%)

**Key Insight**: Time investment vs confidence analysis favors:
1. Quick mock improvements (high confidence/low time)
2. Then backfill (medium confidence/medium time)
3. Then retrain (inherits backfill investment)

**Conclusion**: Sequential approach beats big bang ML rewrite.

---

### Perspective 6: Learning & Iteration

**What We Learned So Far:**
1. ✅ usage_rate critical → Fixed it! → 95% coverage
2. ✅ game_id format matters → Fixed it! → Perfect joins
3. ✅ Mock is sophisticated → Can improve it further
4. ✅ Precompute coverage matters → Need backfill
5. ✅ Historical data has gaps → Recent data is clean

**What We Still Don't Know:**
1. ❓ Can XGBoost beat mock with complete features?
2. ❓ What's the theoretical performance ceiling?
3. ❓ Which features matter most (vs what mock uses)?
4. ❓ Are there patterns mock misses?
5. ❓ How much do precompute features actually help?

**Key Insight**: We have enough information to improve mock, but not enough to confidently say ML will win.

**Scientific Approach**: Run experiments to answer unknowns:
1. Improve mock → establishes new baseline
2. Backfill precompute → removes data excuse
3. Retrain ML → fair comparison
4. A/B test in production → ground truth

**Conclusion**: We need more data points before committing to ML-only approach.

---

## STRATEGIC RECOMMENDATION

### Three-Phase Plan

#### **PHASE 1: Quick Wins (This Session - 3 hours)**
**Goal**: Improve mock to 4.0-4.2 MAE with minimal effort

**Approach**: Analyze mock's errors and add targeted improvements

**Tasks**:
1. Query prediction_accuracy to find where mock fails most
2. Identify patterns (player types, scenarios, opponents)
3. Add rules/adjust weights for top failure modes
4. Test on validation set
5. Deploy if better than 4.32

**Success Criteria**: Mock MAE < 4.25

**Why This First**:
- High confidence, low risk
- Establishes new baseline to beat
- Buys time for infrastructure work
- Provides immediate business value

---

#### **PHASE 2: Infrastructure Fix (Next Week - Parallel)**
**Goal**: Complete precompute backfill for clean ML training

**Track A: Backfill Execution (12 hours)**
1. Backfill player_composite_factors (2021-2024)
2. Backfill team_defense_zone_analysis (2021-2024)
3. Backfill player_daily_cache (2021-2024)
4. Validate coverage: target 95%+ on all tables
5. Document completeness

**Track B: Mock Optimization (4 hours)**
1. Systematic weight tuning using gradient descent on historical errors
2. Add missing interaction terms (usage × pace, paint × defense)
3. Create ensemble: mock_v1 (current) + mock_v2 (tuned)
4. A/B test internally

**Success Criteria**:
- Precompute coverage: 95%+ for 2021-2024
- Mock MAE: 4.0-4.1 (if tuning works)

**Why This Phase**:
- Removes data quality excuse for ML
- Parallel tracks maximize efficiency
- Infrastructure improvements benefit entire platform
- Sets foundation for Phase 3

---

#### **PHASE 3: ML vs Mock Showdown (Week 3 - Decision Point)**
**Goal**: Determine if ML can beat optimized mock with complete data

**Approach**: Fair comparison with all advantages

**Tasks**:
1. Extract training data from 2021-2024 (95%+ coverage now)
2. Train XGBoost v6 with complete features
3. Train alternative models (LightGBM, CatBoost, Neural Net)
4. Ensemble: best 3 models
5. Compare against Phase 2 mock (4.0-4.1 baseline)

**Decision Tree**:

**If ML wins (MAE < 4.0)**:
- Deploy ML to production
- Keep mock as fallback
- Monitor for drift
- Declare success! 🎉

**If ML loses (MAE > 4.1)**:
- Keep optimized mock as primary
- Use ML for edge cases (low-confidence predictions)
- Revisit in 6 months (more data, better features)
- Declare "mission accomplished" - mock is good enough

**If ML ties (MAE 4.0-4.1)**:
- Deploy hybrid: mock for fast inference, ML for high-stakes
- Ensemble both: (mock + ml) / 2
- A/B test in production for 2 weeks
- Choose winner based on real accuracy

**Success Criteria**: Clear winner emerges, decision made

---

## EXECUTION PLAN: PHASE 1 (TODAY)

### Step 1: Analyze Mock Model's Failure Modes (30 min)

**Query**: Find where mock performs worst
```sql
WITH mock_errors AS (
  SELECT
    pa.player_lookup,
    pa.game_date,
    pa.predicted_points as mock_pred,
    pgs.points as actual,
    ABS(pa.predicted_points - pgs.points) as error,
    pgs.usage_rate,
    pgs.minutes_played,
    pgs.points_last_5,
    pgs.points_last_10,
    pgs.starter_flag,
    pgs.home_game,
    pgs.back_to_back,
    -- Categorize error size
    CASE
      WHEN ABS(pa.predicted_points - pgs.points) > 10 THEN 'extreme'
      WHEN ABS(pa.predicted_points - pgs.points) > 7 THEN 'large'
      WHEN ABS(pa.predicted_points - pgs.points) > 5 THEN 'medium'
      ELSE 'small'
    END as error_category,
    -- Identify scenario
    CASE
      WHEN pgs.minutes_played > pgs.minutes_avg_last_10 + 10 THEN 'minutes_spike'
      WHEN pgs.minutes_played < pgs.minutes_avg_last_10 - 10 THEN 'minutes_drop'
      WHEN pgs.usage_rate > pgs.usage_rate_last_10 + 8 THEN 'usage_spike'
      WHEN pgs.usage_rate < pgs.usage_rate_last_10 - 8 THEN 'usage_drop'
      WHEN pgs.back_to_back THEN 'back_to_back'
      WHEN pgs.starter_flag = FALSE THEN 'bench_player'
      ELSE 'standard'
    END as scenario
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
    ON pa.player_lookup = pgs.player_lookup
    AND pa.game_date = pgs.game_date
  WHERE pa.game_date BETWEEN '2024-02-08' AND '2024-04-30'
    AND pa.system_id = 'mock_xgboost_v1'
)
SELECT
  scenario,
  error_category,
  COUNT(*) as occurrences,
  ROUND(AVG(error), 2) as avg_error,
  ROUND(AVG(mock_pred), 1) as avg_prediction,
  ROUND(AVG(actual), 1) as avg_actual,
  ROUND(AVG(mock_pred) - AVG(actual), 2) as bias
FROM mock_errors
GROUP BY scenario, error_category
ORDER BY scenario, error_category
```

**Goal**: Identify top 3-5 scenarios where mock systematically fails

---

### Step 2: Design Improvements (45 min)

**Based on error analysis**, add improvements to mock model:

**Example Improvements**:

1. **Minutes Spike Detection** (if mock underpredict when minutes spike):
```python
# Add to mock_xgboost_model.py
if minutes > minutes_avg_last_10 + 8:
    # Player getting expanded role
    minutes_spike_adj = (minutes - minutes_avg_last_10) * 0.3
    total_adj += minutes_spike_adj
```

2. **Bench Player Variance** (if mock overpredicts bench players):
```python
if usage_rate < 20:  # Low usage bench player
    # More volatile performance, regress to mean more
    baseline_weight = 0.7  # Increase mean reversion
    baseline = (
        points_last_5 * 0.25 +
        points_last_10 * 0.35 +
        points_season * 0.40  # Higher weight on season avg
    )
```

3. **Usage Spike Amplification** (if mock underpredicts usage spikes):
```python
# Current: usage_spike * 0.45 for large spikes
# New: Add non-linear boost for extreme spikes
if usage_spike > 10:
    usage_adj = usage_spike * 0.60  # Increased from 0.45
elif usage_spike > 5:
    usage_adj = usage_spike * 0.45
```

4. **Opponent-Specific Adjustments**:
```python
# Add team-specific defense multipliers
team_defense_mismatch = {
    'BOS': {'paint_heavy': -1.2, 'perimeter_heavy': -0.8},  # Elite all-around
    'MIN': {'paint_heavy': -1.0, 'perimeter_heavy': -1.2},  # Elite perimeter
    'MEM': {'paint_heavy': -0.5, 'perimeter_heavy': -1.0},  # Weak interior
    # ... etc
}
```

5. **Fatigue Curve Refinement**:
```python
# Current: 5-level step function
# New: Smooth curve
fatigue_adj = -4.0 * ((100 - fatigue) / 100) ** 2
# This creates smooth degradation instead of steps
```

**Select top 3 improvements** based on:
- Highest error reduction potential
- Easiest to implement
- Most generalizable

---

### Step 3: Implement & Test (60 min)

**Implementation**:
1. Create new file: `predictions/shared/mock_xgboost_model_v2.py`
2. Copy from v1, add improvements
3. Add version flag: `model_version = 'mock_v2'`

**Testing**:
1. Create test script: `ml/evaluate_mock_v2.py`
2. Load same test data as XGBoost evaluation (2024-02-08 to 2024-04-30)
3. Compare:
   - Mock v1: 4.32 MAE (baseline)
   - Mock v2: ? MAE (improved)
   - XGBoost v5: 4.63 MAE (current ML)

**Success Criteria**:
- Mock v2 MAE < 4.25 (improvement of 0.07+)
- No regressions on easy cases
- Improvements on identified failure modes

---

### Step 4: Deploy or Iterate (45 min)

**If Mock v2 beats v1**:
1. Update prediction worker to use mock_v2
2. Deploy to staging
3. Run shadow predictions for 24 hours
4. Compare against v1 in production
5. If stable: promote to production

**If Mock v2 doesn't beat v1**:
1. Analyze why improvements didn't help
2. Try alternative improvements
3. Consider that mock v1 is already well-tuned
4. Move to Phase 2 (backfill) as primary path

**Documentation**:
- Record what was tried
- Document results
- Update handoff for next session

---

## PHASE 2 & 3 PREP (For Next Week)

### Phase 2 Backfill Checklist

**Player Composite Factors**:
- [ ] Check current coverage: `SELECT COUNT(*) FROM player_composite_factors WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'`
- [ ] Identify missing dates
- [ ] Run backfill: `./bin/backfill/backfill_player_composite_factors.sh 2021-10-01 2024-05-01`
- [ ] Validate: Target 95%+ coverage
- [ ] Document: Note any dates that couldn't be backfilled

**Team Defense Zone Analysis**:
- [ ] Similar process
- [ ] Expected: Easier than player_composite (less data)

**Player Daily Cache**:
- [ ] Similar process
- [ ] Expected: Most time-consuming (23% currently missing)

**Success Metric**:
```sql
-- All should return 95%+
SELECT 'composite' as table_name,
  COUNT(*) as records,
  COUNT(DISTINCT game_date) as dates
FROM player_composite_factors
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01';
```

---

### Phase 3 ML Experiments

**Model Variations to Try**:
1. XGBoost v6 (complete features, no changes)
2. XGBoost v6-tuned (reduced overfitting)
3. LightGBM (faster, sometimes better)
4. CatBoost (handles categoricals well)
5. Ensemble (combine best 3)

**Evaluation Framework**:
```python
models = {
    'mock_v1': 4.32,      # Original baseline
    'mock_v2': 4.15,      # (projected from Phase 1)
    'xgboost_v5': 4.63,   # Current (incomplete features)
    'xgboost_v6': ???,    # With complete features
    'lightgbm_v1': ???,
    'catboost_v1': ???,
    'ensemble': ???
}

# Champion: mock_v2 (4.15)
# Goal: Beat champion by 0.05+ (4.10 or better)
```

---

## DECISION FRAMEWORKS

### When to Choose Mock Over ML

**Choose Mock If**:
- ✅ Mock MAE < 4.15 after Phase 1 improvements
- ✅ ML can't beat mock by 0.10+ after Phase 3
- ✅ Interpretability is critical (regulatory, user trust)
- ✅ Data pipeline has reliability issues
- ✅ ML maintenance overhead too high

**Choose ML If**:
- ✅ ML beats mock by 0.10+ (4.05 vs 4.15)
- ✅ ML scales to new features/leagues easily
- ✅ Team has ML ops capability
- ✅ Can maintain training pipeline
- ✅ Want to leverage growing historical data

**Choose Hybrid If**:
- ✅ ML and mock tie (within 0.05)
- ✅ Each excels in different scenarios
- ✅ Want redundancy/fallback
- ✅ Can maintain both systems

---

### ROI Analysis

**Mock Improvement Investment**:
- Time: 8-12 hours total (Phase 1 + Phase 2 Track B)
- Cost: ~$800-1200 (engineer time)
- Expected gain: 4.32 → 4.10 MAE (0.22 improvement)
- Per-hour impact: 0.018-0.027 MAE improvement

**ML Investment**:
- Time: 24-32 hours total (backfill + training + deployment)
- Cost: ~$2400-3200 (engineer time + compute)
- Expected gain: 4.32 → 4.05 MAE (0.27 improvement, if successful)
- Per-hour impact: 0.008-0.011 MAE improvement
- Risk: 50% chance of no improvement

**Quick Math**: Mock improvements are 2-3× more time-efficient IF they work.

**But**: ML investments compound (better infrastructure, reusable pipeline, scalable).

**Conclusion**: Do both, sequentially. Mock for quick wins, ML for long-term foundation.

---

## SUCCESS METRICS

### Phase 1 Success
- [ ] Mock v2 deployed with MAE < 4.25
- [ ] Error analysis completed and documented
- [ ] 2-3 improvements implemented and tested
- [ ] Handoff doc created for Phase 2

### Phase 2 Success
- [ ] Precompute coverage: 95%+ for 2021-2024
- [ ] Mock v2 optimized: MAE 4.0-4.15 range
- [ ] Infrastructure documented and validated
- [ ] Ready for ML training with complete data

### Phase 3 Success (One of):
- [ ] ML beats mock by 0.10+ → Deploy ML
- [ ] Mock beats ML → Keep mock, declare victory
- [ ] Tie → Deploy hybrid
- [ ] Clear decision made with data backing it

### Overall Success (3-4 weeks from now)
- [ ] Production MAE: 4.0-4.1 (beat original 4.27 baseline by 6-7%)
- [ ] System is stable and maintainable
- [ ] Team knows which approach (mock/ML/hybrid) to invest in
- [ ] Infrastructure ready for scale (new leagues, new markets)

---

## RISK MITIGATION

### Risk 1: Mock improvements don't work
**Probability**: 30%
**Impact**: Medium (wasted 8 hours)
**Mitigation**: Have Phase 2 ready to start immediately
**Backup**: Skip to infrastructure backfill

### Risk 2: Backfill fails or takes too long
**Probability**: 20%
**Impact**: High (blocks ML path)
**Mitigation**: Prioritize most critical tables first, accept 90% coverage
**Backup**: Train ML on recent data only (2024-2026, smaller dataset)

### Risk 3: ML still loses after backfill
**Probability**: 40%
**Impact**: Low (mock is acceptable)
**Mitigation**: Accept mock as production system, use ML for specific cases
**Backup**: Revisit in 6 months with more data

### Risk 4: Both mock and ML plateau at 4.1-4.2
**Probability**: 30%
**Impact**: Low (still beat baseline)
**Mitigation**: Accept theoretical limit, focus on other improvements (UI, coverage, speed)
**Backup**: Investigate alternative approaches (deep learning, LLMs, ensemble methods)

---

## CONTINGENCY PLANS

### If Phase 1 Takes Longer Than Expected
- Time-box to 4 hours max
- If not making progress, document learnings and move to Phase 2
- Don't get stuck optimizing mock endlessly

### If We Run Out of Time This Session
- Complete error analysis (Step 1)
- Document top 3 improvements to try
- Create detailed handoff for next session
- Ensure Phase 2 prep is ready

### If User Wants Different Approach
- Present this analysis
- Ask for strategic preference:
  - Quick wins vs long-term foundation
  - Risk tolerance (try ML vs safe mock)
  - Time horizon (weeks vs months)
- Adapt plan based on feedback

---

## HANDOFF TO NEXT SESSION

### If Phase 1 Completes Successfully
**Next session starts with**:
- Mock v2 in production at ~4.15 MAE
- Clear backfill task list
- 2-week timeline for Phase 2+3
- Decision framework ready

### If Phase 1 Incomplete
**Next session starts with**:
- Error analysis results
- Improvement ideas documented
- Clear task: implement and test
- Phase 2 ready to start in parallel

### Critical Information to Preserve
- [ ] Error analysis query and results
- [ ] Improvement hypotheses and rationale
- [ ] Test results (what worked, what didn't)
- [ ] Mock v2 code changes
- [ ] Decision on whether to proceed to Phase 2

---

## FINAL RECOMMENDATION

**Start with Phase 1 today** (mock improvements):
1. Low risk, high confidence
2. Quick wins for business
3. Establishes new baseline
4. Buys time for infrastructure work

**Prepare Phase 2 in parallel** (backfill + mock tuning):
1. Removes data quality blockers
2. Benefits entire platform
3. Sets up fair ML comparison
4. Hedge against Phase 1 failure

**Reserve judgment on ML** until Phase 3:
1. No rush - mock is working
2. Need complete data for fair test
3. Infrastructure value regardless
4. Can always do ML in 3 months

**This is the pragmatic path**:
- Progress now (mock improvements)
- Fix foundations (backfill)
- Test fairly (ML vs mock with complete data)
- Decide with confidence (data-driven)

---

## APPENDIX: Query Library

### Error Analysis Query
```sql
-- See Step 1 in Phase 1 Execution Plan
-- Identifies where mock fails most
```

### Feature Coverage Query
```sql
-- Checks precompute coverage for training period
SELECT
  'composite_factors' as table_name,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_date) as covered_dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01';

-- Repeat for other precompute tables
```

### Backfill Progress Query
```sql
-- Check backfill completion
WITH date_series AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY('2021-10-01', '2024-05-01')) as date
),
actual_dates AS (
  SELECT DISTINCT game_date as date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
)
SELECT
  COUNT(ds.date) as total_dates,
  COUNT(ad.date) as covered_dates,
  ROUND(100.0 * COUNT(ad.date) / COUNT(ds.date), 1) as coverage_pct
FROM date_series ds
LEFT JOIN actual_dates ad ON ds.date = ad.date;
```

---

**READY TO EXECUTE PHASE 1** ✅

Next step: Run error analysis query and identify mock's failure modes.
