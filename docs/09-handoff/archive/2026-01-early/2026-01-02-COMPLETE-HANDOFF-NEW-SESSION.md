# Complete Handoff - ML Investigation & Fix Plan
**Date**: 2026-01-02
**Session Duration**: 6+ hours (Ultrathink analysis + planning)
**Status**: 🟡 Investigation Phase - Ready for Execution
**Next Session**: Start with Phase 1 investigation queries

---

## 🎯 **READ THIS FIRST** (5-Minute Context)

### What Happened

We attempted to train ML models (v1, v2, v3) to beat a mock baseline model (4.33 MAE). All attempts failed:
- v1 (6 features): 4.79 MAE (10.6% worse)
- v2 (14 features): 4.63 MAE (6.9% worse)
- v3 (25 features): 4.63 MAE (6.9% worse - NO improvement from v2!)

### Critical Discovery

**Root Cause**: 95% of training data has missing values. Models are learning from **imputed fake defaults**, not real patterns.

```
CRITICAL DATA QUALITY ISSUES:
├── minutes_avg_last_10: 95.8% NULL (60,893 of 63,547 rows)
├── usage_rate_last_10: 100% NULL (all rows)
├── team_pace_last_10: 36.7% NULL
└── player_composite_factors: 11.6% NULL

ROOT CAUSE: player_game_summary.minutes_played is 99.5% NULL
            (only 423 of 83,534 rows have data)

IMPACT: Window functions on NULL → more NULLs → cascade failure
        Models train on defaults (fatigue=70, usage=25, etc.) not reality
```

### Why This Matters

- **XGBoost v3** learned: "back_to_back has 1.8% importance"
- **Mock model** uses: "back_to_back = -2.2 points penalty"
- **Gap**: Mock's hand-tuned rule is 100x stronger (and correct)

The ML model can't learn the right patterns because **the data isn't there**.

### The Solution

**3-Phase Strategy** (not "just train better models"):

1. **FIX THE DATA** (Weeks 1-4) → +11-19% MAE improvement
2. **QUICK WINS** (Weeks 3-4) → +13-25% MAE improvement
3. **HYBRID ENSEMBLE** (Weeks 5-9) → 20-25% better than mock

**NOT**: Replace mock with ML
**YES**: Combine mock wisdom + ML adaptation

---

## 📋 **YOUR MISSION** (If You Choose to Accept)

### Immediate Goal (Week 1)

**Investigate why `player_game_summary.minutes_played` is 99.5% NULL**

Run 3 diagnostic queries → Identify data source → Trace ETL pipeline → Document findings

**Expected Time**: 4-6 hours
**Success Criteria**: Root cause identified, fix plan created

### Ultimate Goal (9 Weeks)

**Build hybrid ensemble achieving 3.40-3.60 MAE (20-25% better than mock's 4.33)**

Fix data → Retrain models → Build ensemble → Deploy with A/B test

**Expected Time**: 175-250 hours total
**Success Criteria**: Production ensemble beating mock baseline reliably

---

## 🚨 **CRITICAL CONTEXT YOU NEED**

### The Mock Model Isn't Actually "Mock"

It's a **sophisticated expert system** with 10+ carefully hand-tuned rules:

```python
# Example rules from mock_xgboost_model.py
baseline = (points_last_5 * 0.35 + points_last_10 * 0.40 + points_season * 0.25)

if fatigue < 50: adjustment -= 2.5     # Severe fatigue
elif fatigue < 70: adjustment -= 1.0   # Moderate fatigue
elif fatigue > 85: adjustment += 0.5   # Well rested

if back_to_back: adjustment -= 2.2     # Large penalty!
if is_home: adjustment += 1.0          # Home advantage
if opp_def_rating < 108: adjustment -= 1.5  # Elite defense

# Plus 5 more complex interactions...
```

These rules encode **50+ years of NBA basketball knowledge**. XGBoost with 64k samples **cannot learn these thresholds** reliably - it needs 200-500k samples.

**Implication**: Don't try to "beat" the mock - **combine** with it.

### Why All 3 Training Attempts Failed

**NOT** because:
- ❌ Wrong algorithm (XGBoost is fine)
- ❌ Wrong hyperparameters (they're reasonable)
- ❌ Need more features (we have 25!)

**YES** because:
- ✅ **95% of key features are NULL** (training on fake defaults)
- ✅ Mock uses non-linear thresholds XGBoost can't learn with limited data
- ✅ Missing interaction features (pace × usage, fatigue × b2b)

### The Data Quality Crisis

**Where it starts**:
```sql
-- Source table: player_game_summary has 99.5% NULL for minutes_played
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls
FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Result: 83,534 total, 83,111 nulls (99.5%!)
```

**Where it cascades**:
```sql
-- Window function: AVG(minutes_played) OVER (LAST 10 GAMES)
-- Input: 99.5% NULL
-- Output: 99.5% NULL
-- Training script: X['minutes_avg_last_10'].fillna(0)
-- Model learns: "minutes_avg_last_10 = 0 for everyone"
```

This is why **feature importance is 58% on points_last_10** (only feature with real data) and context features have near-zero importance (all defaults).

---

## 📁 **FILES CREATED** (Your Knowledge Base)

All documentation is in `/home/naji/code/nba-stats-scraper/docs/09-handoff/`:

### 1. **2026-01-02-MASTER-INVESTIGATION-AND-FIX-PLAN.md** (30KB) ⭐
**THE MAIN GUIDE** - Everything you need:
- Complete investigation roadmap (7 SQL queries with expected outputs)
- Detailed fix plans for all data issues
- Quick win implementations (filters, injury data)
- Model retraining guides (XGBoost, CatBoost, LightGBM)
- Feature engineering recipes (interactions, embeddings, trends)
- Hybrid ensemble architecture
- 18-week timeline with success criteria

**START HERE** if you want detailed step-by-step instructions.

### 2. **2026-01-02-ULTRATHINK-EXECUTIVE-SUMMARY.md** (12KB)
**THE QUICK BRIEF** - For understanding context:
- One-sentence summary of the problem
- Critical findings from 5-agent analysis
- Recommended strategy (4 phases)
- Expected outcomes table
- Decision framework (go/no-go criteria)

**START HERE** if you want high-level understanding first.

### 3. **2026-01-02-ML-V3-TRAINING-RESULTS.md** (20KB)
**THE TECHNICAL DEEP-DIVE** - Training results:
- Why v3 failed (4.63 vs 4.33 baseline)
- Feature importance analysis (58% in points_avg_last_10)
- Data quality issues discovered
- Comparison to v1 and v2 models

**READ THIS** to understand what's already been tried.

### 4. **2026-01-02-COMPLETE-HANDOFF-NEW-SESSION.md** (THIS FILE)
**THE STARTING POINT** - For new sessions:
- Context and critical findings
- Immediate next steps
- Copy-paste queries ready to run
- Success criteria and decision points

---

## 🔍 **PHASE 1: INVESTIGATION** (Your Starting Point)

### Step 1: Check Raw Data Sources (30 min)

Run these 3 queries to identify which source has `minutes_played`:

```sql
-- Query 1: Check Ball Don't Lie (BDL) API data
SELECT
  'balldontlie' as source,
  COUNT(*) as total_games,
  SUM(CASE WHEN min IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN min IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Query 2: Check NBA.com API data
SELECT
  'nba.com' as source,
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_raw.nbac_player_boxscores`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Query 3: Check Gamebook scraper data
SELECT
  'gamebook' as source,
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_minutes,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
```

**Expected Output**: One of these will show <10% NULL (that's your good source)

**Action**: Note which source has minutes data, proceed to Step 2.

---

### Step 2: Trace ETL Pipeline (1-2 hours)

**Objective**: Find where `minutes_played` is lost in transformation

**File to inspect**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**What to look for**:
```python
# Is minutes_played being selected from raw tables?
SELECT
  player_id,
  game_date,
  points,
  # Look for this line (might be missing):
  COALESCE(bdl.min, nbac.minutes, gamebook.minutes_played) as minutes_played,
  ...
FROM ...
```

**Key questions**:
1. Is `minutes_played` in the SELECT clause?
2. If yes, which source is it pulling from?
3. Are there JOIN conditions filtering out rows?
4. Has this code changed recently? (check git history)

**Tools**:
```bash
# Search for minutes_played in processor
grep -r "minutes_played" data_processors/analytics/player_game_summary/

# Check recent changes
cd data_processors/analytics/player_game_summary/
git log --oneline -20 player_game_summary_processor.py
git diff HEAD~10 player_game_summary_processor.py | grep -i minutes

# Check processor logs for errors
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND textPayload=~"player_game_summary"
  AND severity>=WARNING' --limit 100
```

**Document findings**: Create note with source code snippet, git history, any errors found.

---

### Step 3: Temporal Analysis (30 min)

**Objective**: Determine if this is a recent regression or historical gap

```sql
-- Check NULL rate over time
SELECT
  DATE_TRUNC(game_date, MONTH) as month,
  COUNT(*) as total_games,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY month
ORDER BY month;
```

**Expected patterns**:

**Pattern A: Recent regression** (Sudden spike in NULL rate)
```
2021-10: 5% NULL
2021-11: 5% NULL
...
2023-12: 5% NULL
2024-01: 99% NULL  ← Regression here!
```
**Action**: Find git commit around Jan 2024, rollback code change

**Pattern B: Historical gap** (Consistent high NULL)
```
2021-10: 95% NULL
2021-11: 95% NULL
...
2024-04: 95% NULL
```
**Action**: Data was never collected, need backfill strategy

**Pattern C: Gradual degradation** (Increasing NULL rate)
```
2021-10: 10% NULL
2022-01: 30% NULL
2023-01: 60% NULL
2024-01: 95% NULL
```
**Action**: Data source reliability declining, investigate why

**Document**: Timeline showing when NULL rate changed, hypothesis about cause.

---

### Step 4: Usage Rate Investigation (30 min)

**Check if usage_rate exists or needs calculation**:

```sql
-- Query 1: Check if usage_rate exists anywhere
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN usage_rate IS NULL THEN 1 ELSE 0 END) as null_count,
  ROUND(SUM(CASE WHEN usage_rate IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';

-- Query 2: Check if we have components to calculate it
-- Formula: 100 * ((FGA + 0.44*FTA + TOV) * (Tm_MP/5)) / (MP * (Tm_FGA + 0.44*Tm_FTA + Tm_TOV))
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN fg_attempts IS NULL THEN 1 ELSE 0 END) as null_fga,
  SUM(CASE WHEN ft_attempts IS NULL THEN 1 ELSE 0 END) as null_fta,
  SUM(CASE WHEN turnovers IS NULL THEN 1 ELSE 0 END) as null_tov,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_mp
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
```

**If components exist** (FGA, FTA, TOV, MP all <10% NULL):
- **Action**: Implement usage_rate calculation in processor
- **Effort**: 4-6 hours (SQL update + test + backfill)

**If components don't exist**:
- **Action**: Find different source for usage_rate or mark as future work
- **Impact**: Medium (usage_rate is helpful but not critical)

---

### Step 5: Document Root Cause (1 hour)

**Create investigation report**: `docs/09-handoff/2026-01-02-ROOT-CAUSE-INVESTIGATION.md`

**Include**:
1. **Summary**: One-paragraph description of issue
2. **Timeline**: When did NULL rate spike? (from Step 3)
3. **Source Analysis**: Which raw source has data? (from Step 1)
4. **ETL Trace**: Where is data lost? (from Step 2)
5. **Fix Plan**: What needs to change? (specific file, line numbers, SQL)
6. **Backfill Strategy**: How to recover 2021-2024 data?
7. **Validation**: How to confirm fix worked? (acceptance criteria)

**Example structure**:
```markdown
# Root Cause Investigation - minutes_played NULL Crisis

## Summary
player_game_summary.minutes_played is 99.5% NULL for 2021-2024 period,
causing ML training to use defaults instead of real data. Root cause: [FILL IN].

## Timeline
- 2021-10-01 to 2024-05-01: NULL rate consistently 99.5%
- Pattern: [Regression/Historical Gap/Degradation]

## Source Analysis
- balldontlie: [X% NULL]
- nba.com: [X% NULL]  ← BEST SOURCE
- gamebook: [X% NULL]

## ETL Trace
File: data_processors/analytics/player_game_summary/player_game_summary_processor.py
Line: [XXX]
Issue: [minutes_played not selected / wrong source / JOIN filtering rows]
Code snippet: [...]

## Fix Plan
1. Update processor SQL to select from [best source]
2. Test on 2024-04-01 to 2024-04-07 (one week)
3. If test passes, backfill 2021-10-01 to 2024-05-01
4. Validate NULL rate <5%

## Backfill Strategy
Command: ./bin/analytics/reprocess_player_game_summary.sh \
  --start-date 2021-10-01 --end-date 2024-05-01 --backfill-mode
Estimated time: 6-12 hours
Risk: Low (read-only source data, idempotent processor)

## Validation
SELECT COUNT(*), SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*)
FROM player_game_summary WHERE game_date >= '2021-10-01';
Target: NULL rate <5%
```

---

## 🎯 **DECISION POINTS** (When to Proceed/Stop)

### Decision Point 1: After Investigation (Week 1)

**If root cause is FIXABLE** (data exists in raw source, just not selected):
- ✅ **PROCEED** to Phase 2 (fix implementation)
- **Expected**: 95%+ probability of success
- **Timeline**: 2-3 more weeks to fix + validate

**If root cause is UNFIXABLE** (data doesn't exist anywhere):
- ⚠️ **STOP ML work** - Can't train on data that doesn't exist
- **Alternative**: Accept mock model (4.33 MAE), focus on pipeline improvements
- **ROI**: Better to invest in data collection than broken ML

**If investigation is INCONCLUSIVE** (can't find root cause):
- 🤔 **ESCALATE** - May need help from original data engineers
- **Action**: Document blockers, request support

---

### Decision Point 2: After Data Fix (Week 3-4)

**Run validation query**:
```sql
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
```

**If NULL rate <5%**:
- ✅ **PROCEED** to retrain XGBoost v3 with clean data
- **Expected**: 3.80-4.10 MAE (should beat mock's 4.33)

**If NULL rate still >20%**:
- ⚠️ **INVESTIGATE** - Fix didn't work as expected
- **Action**: Review backfill logs, check processor logic again

---

### Decision Point 3: After Retraining (Week 4-5)

**Retrain XGBoost v3** with clean data:
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
python ml/train_real_xgboost.py
```

**If Test MAE <4.20** (beats mock by >3%):
- ✅ **PROCEED** to Phase 3 (hybrid ensemble)
- **Confidence**: High - ML is working now
- **Timeline**: 4-5 more weeks to build ensemble

**If Test MAE 4.20-4.30** (marginal, close to mock):
- 🤔 **CONSIDER** - May want to try CatBoost or feature engineering first
- **Action**: Quick experiments (1-2 weeks) before full ensemble

**If Test MAE >4.30** (still worse than mock):
- ⚠️ **INVESTIGATE** - Data fix helped but something else is wrong
- **Possible causes**:
  - Other features still have high NULL rates
  - Feature engineering needed (interactions)
  - Hyperparameter tuning needed

---

### Decision Point 4: After Ensemble (Week 8-9)

**Test ensemble on holdout set**:

**If Ensemble MAE <3.60** (20%+ better than mock):
- ✅ **DEPLOY** with A/B test (5% → 25% → 100% traffic)
- **Success!** Hybrid approach worked
- **Monitor**: 2 weeks in production before full rollout

**If Ensemble MAE 3.60-4.00** (10-20% better):
- 🤔 **PARTIAL SUCCESS** - Better but not as good as hoped
- **Options**:
  - Deploy anyway (10% improvement is valuable)
  - Try more feature engineering
  - Try advanced techniques (LSTM if you get more data)

**If Ensemble MAE >4.00** (<10% better than mock):
- ⚠️ **REASSESS** - Hybrid approach not adding enough value
- **Consider**: Accept mock model, focus effort elsewhere

---

## ⚡ **QUICK START GUIDE** (Next 30 Minutes)

### Option A: Jump Right In
```bash
# 1. Read this handoff (you're already doing it)

# 2. Open BigQuery console

# 3. Run Query 1 (BDL source check) - copy from Step 1 above

# 4. Run Query 2 (NBA.com source check)

# 5. Run Query 3 (Gamebook source check)

# 6. Compare results, note which has <10% NULL

# 7. Proceed to Step 2 (trace ETL pipeline)
```

### Option B: Deep Context First
```bash
# 1. Read ULTRATHINK-EXECUTIVE-SUMMARY.md (10 min)

# 2. Skim MASTER-INVESTIGATION-AND-FIX-PLAN.md (20 min)

# 3. Read ML-V3-TRAINING-RESULTS.md (15 min)

# 4. Come back to this handoff and run queries
```

### Option C: Validate Findings First
```bash
# 1. Verify 95% NULL claim is accurate
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as nulls,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100 as pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
"

# Expected: ~99.5% NULL

# 2. If confirmed, proceed with investigation (Step 1)
```

---

## 🚫 **PITFALLS TO AVOID**

### 1. Training More Models Before Fixing Data
**DON'T**: "Let me try v4 with hyperparameter tuning..."
**DO**: Fix the 95% NULL issue first, THEN retrain

**Why**: Garbage in, garbage out. No algorithm can learn from fake data.

### 2. Trying to Beat Mock with Pure ML
**DON'T**: "The mock is just a placeholder to replace"
**DO**: Recognize mock encodes expert knowledge, combine with ML

**Why**: Mock achieves 4.33 MAE with hand-tuned rules. Pure ML unlikely to beat this with 64k samples.

### 3. Building Production Infrastructure Too Early
**DON'T**: "Let's set up MLflow and model registry first"
**DO**: Fix data, get one good model, THEN build infrastructure

**Why**: You're at 70% system maturity. Infrastructure at 95%+.

### 4. Skipping Quick Wins
**DON'T**: "Let's focus on the ML model, we can add filters later"
**DO**: Implement minute/confidence filters (2-4 hours for 13-25% gain)

**Why**: Quick wins have 5-10x better ROI than ML optimization.

### 5. Deploying Without A/B Testing
**DON'T**: "Model beats mock in testing, let's deploy to 100%"
**DO**: Start with 5% traffic, monitor closely, expand gradually

**Why**: Production is different from offline testing. Safe rollout prevents disasters.

### 6. Ignoring Mock Model's Rules
**DON'T**: "Just train XGBoost with more data and features"
**DO**: Study mock's rules, encode as explicit features (interactions)

**Why**: Mock uses fatigue × back_to_back, pace × usage interactions XGBoost won't discover.

---

## 📊 **SUCCESS CRITERIA** (How to Know It's Working)

### Week 1: Investigation Complete ✅
- [ ] Root cause documented (specific file, line, issue)
- [ ] Best data source identified (bdl/nbac/gamebook)
- [ ] Timeline established (regression vs historical gap)
- [ ] Fix plan created (what to change, how to test)
- [ ] Stakeholders informed (if needed)

### Week 3-4: Data Fixed ✅
- [ ] minutes_played NULL rate <5% (target: 95%+ coverage)
- [ ] usage_rate calculated or sourced (target: 90%+ coverage)
- [ ] Precompute tables >90% coverage
- [ ] Validation queries pass
- [ ] Backfill complete for 2021-2024

### Week 4-5: Models Retrained ✅
- [ ] XGBoost v3 MAE <4.20 (beats mock by >3%)
- [ ] Feature importance more balanced (not 75% in top 3)
- [ ] Context features have meaningful importance (back_to_back >5%)
- [ ] Validation MAE close to test MAE (good generalization)
- [ ] Results documented

### Week 8-9: Ensemble Deployed ✅
- [ ] Ensemble MAE <3.60 (20%+ better than mock)
- [ ] A/B test shows improvement in production (not just offline)
- [ ] Meta-learner weights are interpretable (can explain routing)
- [ ] No increase in error rates or prediction latency
- [ ] Monitoring dashboard shows stable performance

---

## 🔧 **TOOLS & COMMANDS**

### BigQuery Queries
```bash
# Run query from command line
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`"

# Save query results to CSV
bq query --use_legacy_sql=false --format=csv "SELECT * FROM ..." > results.csv

# Check table schema
bq show nba-props-platform:nba_analytics.player_game_summary
```

### Git Investigation
```bash
# Find when file last changed
git log --oneline data_processors/analytics/player_game_summary/player_game_summary_processor.py

# See what changed
git diff HEAD~10 player_game_summary_processor.py

# Find when specific text was removed
git log -S "minutes_played" --oneline player_game_summary_processor.py
```

### Cloud Logging
```bash
# Check processor logs
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND textPayload=~"player_game_summary"
  AND timestamp>="2024-01-01"' --limit 100

# Check for errors
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND severity>=ERROR' --limit 50
```

### Training & Evaluation
```bash
# Retrain model
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
python ml/train_real_xgboost.py

# Check model metadata
cat models/xgboost_real_v3_*_metadata.json | python -m json.tool

# List saved models
ls -lh models/
```

---

## 📚 **KNOWLEDGE BASE** (Reference Material)

### Key Concepts

**Mock Model**: Hand-tuned expert system with 10+ rules encoding basketball knowledge
- Uses non-linear thresholds (fatigue <50 = -2.5, 70-85 = 0, >85 = +0.5)
- Interaction effects (pace × usage, fatigue × back_to_back)
- Achieves 4.33 MAE (competitive for sports betting)

**Hybrid Ensemble**: Combining mock + ML models
- Stage 1: Base models (Mock, XGBoost, CatBoost, LightGBM)
- Stage 2: Meta-learner learns when to trust each base model
- Expected: 5-10% better than best single model

**Feature Importance Skew**: Current v3 model
- points_avg_last_10: 58.1% (too concentrated)
- points_avg_season: 10.0%
- points_avg_last_5: 6.9%
- All context features: <2% each (because they're fake defaults)

**Stacked Ensemble**: Training approach
- Split data into K folds
- Train base models on K-1 folds, predict on holdout fold
- Meta-features = predictions from all base models
- Train meta-model on meta-features → learns optimal weighting

### Important Files

**Processor**: `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
- Creates player_game_summary table
- Should select minutes_played from raw sources
- Currently has bug causing 99.5% NULL

**Training Script**: `ml/train_real_xgboost.py`
- 636 lines, comprehensive
- SQL query: lines 50-242 (extract features from BigQuery)
- Feature list: lines 263-306 (currently 25 features)
- Model training: lines 348-356 (XGBoost with early stopping)

**Mock Model**: `predictions/shared/mock_xgboost_model.py`
- The "baseline" we're trying to beat
- Actually a sophisticated expert system
- Has 10+ hand-tuned rules
- Achieves 4.33 MAE

### Common Questions

**Q: Why can't XGBoost learn the mock's rules?**
A: Mock uses complex non-linear thresholds that need 200-500k samples to learn reliably. We only have 64k.

**Q: Should we get more training data?**
A: Maybe later, but fix the 95% NULL issue first. No amount of data helps if it's all fake.

**Q: Why not just use a neural network?**
A: Neural networks need 10-100x more data than tree models. With 64k samples, they'll overfit.

**Q: What if the data can't be fixed?**
A: Accept the mock model (4.33 MAE is competitive). Focus on pipeline reliability, data collection, quick wins.

**Q: How long until production deployment?**
A: Optimistic: 9 weeks. Realistic: 12-18 weeks. Includes data fixes, model development, testing, monitoring.

---

## 🎯 **30-DAY ROADMAP** (Aggressive Timeline)

### Week 1: Investigation
- **Mon-Tue**: Run diagnostic queries, identify data source
- **Wed-Thu**: Trace ETL pipeline, find bug
- **Fri**: Document root cause, create fix plan
- **Deliverable**: Investigation report with fix plan

### Week 2: Fix Implementation
- **Mon**: Update processor code, test on sample data
- **Tue-Wed**: Run backfill for 2021-2024
- **Thu**: Validate data quality >95%
- **Fri**: Document fix, update changelog
- **Deliverable**: Clean data with <5% NULL rate

### Week 3: Quick Wins
- **Mon**: Implement minute threshold filter
- **Tue**: Implement confidence threshold filter
- **Wed**: Measure impact (expect 13-25% improvement)
- **Thu-Fri**: Deploy to production with monitoring
- **Deliverable**: Production filters improving MAE

### Week 4: Model Retraining
- **Mon**: Retrain XGBoost v3 with clean data
- **Tue**: Train CatBoost model
- **Wed**: Train LightGBM model
- **Thu**: Evaluate all models, compare to mock
- **Fri**: DECISION POINT - proceed if any beat mock
- **Deliverable**: Best single model (target: <4.20 MAE)

### Week 5-6: Feature Engineering
- **Week 5**: Create interaction features (fatigue*b2b, pace*usage)
- **Week 6**: Add player embeddings, temporal trends
- **Deliverable**: Enhanced feature set

### Week 7-8: Ensemble Building
- **Week 7**: Build stacked ensemble, train meta-learner
- **Week 8**: Test on holdout, validate performance
- **Deliverable**: Ensemble model (target: <3.60 MAE)

### Week 9: Deployment
- **Mon-Tue**: Deploy with 5% A/B test
- **Wed-Thu**: Monitor, expand to 25%
- **Fri**: DECISION POINT - full rollout if stable
- **Deliverable**: Production ensemble

---

## 📝 **REPORTING TEMPLATE** (Weekly Updates)

Use this template for weekly check-ins:

```markdown
# Week [X] Progress Report - ML Investigation & Fix

## Summary
[1-2 sentences on what was accomplished]

## Completed This Week
- [ ] Task 1 (X hours)
- [ ] Task 2 (X hours)
- [ ] Task 3 (X hours)

## Metrics
- Data Quality: minutes_played NULL rate = [X%] (target: <5%)
- Model Performance: [If trained: MAE = X.XX] (target: <4.20)
- Progress: [X/30] todos complete ([X%])

## Blockers
- [Any blockers or delays]

## Next Week Plan
- [ ] Task 1 (est. X hours)
- [ ] Task 2 (est. X hours)
- [ ] Task 3 (est. X hours)

## Risks
- [Any concerns or risks identified]

## Decisions Needed
- [Any decisions requiring stakeholder input]
```

---

## 🆘 **WHEN TO ASK FOR HELP**

### Scenario 1: Can't Find Root Cause (After 8 hours investigation)
**Signs**:
- Ran all diagnostic queries, results unclear
- Traced ETL pipeline, can't find where data is lost
- All 3 raw sources have high NULL rates

**Action**: Document what you've tried, escalate to data engineering team

### Scenario 2: Fix Doesn't Work (After backfill)
**Signs**:
- Applied fix, ran backfill
- NULL rate still >20%
- Validation queries fail

**Action**: Review backfill logs, check if processor actually re-ran, verify source data

### Scenario 3: Models Still Underperform (After clean data)
**Signs**:
- Data quality >95%
- Retrained v3 with clean data
- Still worse than mock (MAE >4.30)

**Action**: Deep dive into feature importance, check for other data quality issues, consider feature engineering

### Scenario 4: Business Priorities Change
**Signs**:
- New P0 incidents requiring attention
- System maturity drops below 70%
- Budget/timeline constraints

**Action**: Document stopping point, create handoff for resuming later

---

## 🎯 **YOUR FIRST ACTION** (Right Now)

Open BigQuery console and run this query:

```sql
-- Verify the 95% NULL claim
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as total_rows,
  SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) as null_rows,
  ROUND(SUM(CASE WHEN minutes_played IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01';
```

**If null_pct ≈ 99.5%**:
- Claim verified ✅
- Proceed to Step 1 (check raw sources)

**If null_pct <10%**:
- Data was already fixed! 🎉
- Skip to Phase 2 (retrain models with clean data)

**If null_pct 20-80%**:
- Partial issue 🤔
- Still investigate, but less critical

---

## 📞 **HANDOFF COMPLETE**

**You now have**:
- ✅ Full context of the problem (95% NULL data)
- ✅ Understanding of why ML failed (training on fake defaults)
- ✅ Clear strategy (fix data → quick wins → hybrid ensemble)
- ✅ Step-by-step investigation plan (3 queries + ETL trace)
- ✅ All documentation references (4 comprehensive docs)
- ✅ Decision framework (when to proceed/stop)
- ✅ 30-item todo list (tracked in TodoWrite)
- ✅ Success criteria (how to measure progress)
- ✅ Copy-paste queries (ready to run)

**Next steps**:
1. Run the verification query above (2 minutes)
2. If confirmed, proceed to Step 1 (check raw sources)
3. Document findings as you go
4. Update todos using TodoWrite tool
5. Make decisions at checkpoints

**Expected timeline**: 1-9 weeks depending on scope
**Expected outcome**: Hybrid ensemble achieving 3.40-3.60 MAE (20-25% better than mock)

---

**Good luck! The data is waiting to be fixed, and the hybrid ensemble is waiting to be built.** 🚀

**Questions? Reference the MASTER-INVESTIGATION-AND-FIX-PLAN.md for detailed guidance.**
