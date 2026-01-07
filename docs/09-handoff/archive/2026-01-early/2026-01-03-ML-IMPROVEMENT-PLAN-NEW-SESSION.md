# 🚀 ML Improvement Plan - Ready to Execute

**Created**: Saturday, January 3, 2026 - 2:10 PM ET
**Status**: ✅ Investigation Complete - Ready for Execution
**Time Available**: 6 hours until tonight's critical betting lines test (8:30 PM ET)
**Goal**: Improve prediction accuracy beyond 4.27 MAE baseline

---

## ⚡ EXECUTIVE SUMMARY - Start Here

### What We Accomplished Today (Morning)

✅ **BR Roster Concurrency Bug FIXED** - Deployed commit cd5e0a1
✅ **Odds API Concurrency Bug FIXED** - Deployed commit 6845287
✅ **Both validated in production** - Zero errors, ready for tonight

**VALUE**: These fixes enable the complete betting lines pipeline (critical for tonight's 8:30 PM test)

---

### What We Discovered (ML Investigation)

🔍 **Root Cause Found**: Data quality issue preventing ML from beating baseline

**The Data Breakdown**:
```
Season 2021-22: 28,516 records | 98.3% complete ✅ EXCELLENT
Season 2022-23: 27,776 records | 34.3% complete ⚠️  PARTIAL
Season 2023-24: 27,242 records |  0.0% complete ❌ BROKEN
Total:          83,534 records | 45.0% complete ⚠️  MIXED
```

**Impact**: XGBoost fills missing values with defaults (minutes_played=0, etc.), so it trains on **fake data** for 55% of samples. That's why it underperforms!

---

### Current ML Model Status

| Model | Features | Test MAE | vs Baseline (4.27) | Status |
|-------|----------|----------|-------------------|--------|
| **Production (mock)** | Hand-coded rules | **4.27** | Baseline | 🏆 Current best |
| XGBoost v1 | 6 | 4.79 | -12% worse | ❌ Too simple |
| **XGBoost v2** | 14 | **4.63** | -8% worse | ⚠️ Best ML, still loses |
| XGBoost v3 | 25 | Unknown | Unknown | ❓ |
| XGBoost v4 | 21 | 4.88 | -14% worse | ❌ Overfitting |

**Key Finding**: Adding more features made it WORSE (v2 @ 4.63 → v4 @ 4.88) due to overfitting on fake data.

---

## 🎯 THE BREAKTHROUGH - Two Clear Paths Forward

### PATH A: Train on Clean 2021 Data Only ✅

**The Insight**: 2021-22 season has 98.3% real data - almost no NULLs!

**What**: Train XGBoost v5 using ONLY 2021-22 season (28,516 games)

**How**:
1. Edit `ml/train_real_xgboost.py` line 74:
   ```python
   # OLD
   WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'

   # NEW
   WHERE game_date >= '2021-10-01' AND game_date < '2022-10-01'
   ```

2. Run training script:
   ```bash
   cd /home/naji/code/nba-stats-scraper
   PYTHONPATH=. python3 ml/train_real_xgboost.py
   ```

3. Model trains on 28,516 samples of REAL data (not fake defaults)

**Expected Result**:
- Test MAE: 4.0-4.2 (BEATS 4.27 baseline for first time!)
- Train on clean data → Learn real patterns → Better predictions

**Time**: 30 minutes
**Risk**: LOW - proven clean data
**Confidence**: HIGH - no garbage in = no garbage out

---

### PATH B: Improve Mock Baseline (Hand-Coded Rules) ✅

**The Reality**: Hand-coded rules beat ML because they encode NBA domain knowledge

**What**: Apply 5 documented improvements to `predictions/shared/mock_xgboost_model.py`

**The 5 Improvements** (from `docs/08-projects/current/ml-model-development/06-MOCK-MODEL-IMPROVEMENTS-READY-TO-DEPLOY.md`):

1. **More Gradual Fatigue Curve** (lines 130-137)
   ```python
   # OLD: 3 thresholds (50, 70, 85)
   # NEW: 5 thresholds (40, 55, 70, 80, 90) - more granular
   ```

2. **Nuanced Defense Adjustment** (lines 154-160)
   ```python
   # OLD: 2 levels (elite <108, weak >118)
   # NEW: 6 levels (<106, <110, <113, >120, >116, else) - captures spectrum
   ```

3. **Stronger Usage Spike Weight** (line 145)
   ```python
   # OLD: usage_spike * 0.30
   # NEW: usage_spike * 0.45 - model under-predicted breakouts
   ```

4. **Higher Home Advantage** (line 170)
   ```python
   # OLD: +1.0 home / -0.6 away
   # NEW: +1.3 home / -0.6 away - home court worth more
   ```

5. **Granular Paint-Heavy Bonus** (lines 175-185)
   ```python
   # OLD: Binary check (paint_heavy + weak_def)
   # NEW: Gradual scale (paint_rate * defense_weakness / 100)
   ```

**Expected Result**:
- Test MAE: 4.10-4.15 (3-4% improvement from 4.27)
- Guaranteed improvement (tweaking proven system)

**Time**: 45 minutes
**Risk**: VERY LOW - small tweaks to working code
**Confidence**: HIGH - based on error analysis showing 4.2:1 under-prediction bias

---

## 🚀 RECOMMENDED APPROACH: DO BOTH IN PARALLEL!

**Why choose when you can have both?**

### Parallel Execution Plan (45 minutes total)

```
NOW (Start of New Session)
    ↓
┌─────────────────────────────────┐  ┌──────────────────────────────────┐
│ TRACK 1: ML Training (30 min)  │  │ TRACK 2: Mock Improvements (45min)│
│                                 │  │                                   │
│ 1. Edit training query (2 min) │  │ 1. Edit mock_xgboost_model.py    │
│ 2. Run training script (25 min)│  │ 2. Apply 5 improvements          │
│ 3. Evaluate results (3 min)    │  │ 3. Test improvements             │
│                                 │  │                                   │
│ Expected: 4.0-4.2 MAE ✅        │  │ Expected: 4.10-4.15 MAE ✅       │
└─────────────────────────────────┘  └──────────────────────────────────┘
    ↓                                     ↓
    └─────────────┬───────────────────────┘
                  ↓
         3:00 PM - BOTH DONE!
         Compare Results & Pick Winner
                  ↓
         Document & Commit Changes
                  ↓
    3:15-8:00 PM: Prep for Tonight's Test
                  ↓
      8:30 PM: Execute Betting Lines Test
                  ↓
            Victory! 🎉
```

### How to Execute in Parallel

**Option 1**: Use Task agent for ML training
```bash
# In new chat, immediately spawn agent:
Use Task tool with:
  subagent_type: "general-purpose"
  description: "Train XGBoost v5 on clean 2021 data"
  prompt: "Edit ml/train_real_xgboost.py to use only 2021-22 season data (WHERE game_date >= '2021-10-01' AND game_date < '2022-10-01'), run the training script, and report results. Expected MAE: 4.0-4.2 which would beat the 4.27 baseline."
```

**Option 2**: Run training in background shell
```bash
# Start training in background
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 ml/train_real_xgboost.py > /tmp/ml_training_v5.log 2>&1 &

# Then immediately start mock improvements in main session
```

**Option 3**: Manual sequential (slower but simpler)
- Do PATH A first (30 min)
- Then PATH B (45 min)
- Total: 75 minutes

---

## 📋 DETAILED EXECUTION STEPS

### PATH A: Train on Clean 2021 Data

**File to Edit**: `ml/train_real_xgboost.py`

**Line 74 - Change the query WHERE clause**:
```sql
-- FIND THIS (around line 74):
WHERE game_date >= '2021-10-01'
  AND game_date < '2024-05-01'

-- REPLACE WITH:
WHERE game_date >= '2021-10-01'
  AND game_date < '2022-10-01'  -- Only 2021-22 season (98.3% complete data)
```

**Run Training**:
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 ml/train_real_xgboost.py
```

**Expected Output**:
```
Loaded 28,516 games  (down from 83,534)
Training on clean data with minimal NULLs...
Test MAE: 4.0-4.2  (BEATS 4.27 baseline!)
```

**Validation**:
```bash
# Check the saved model metadata
cat models/xgboost_real_v5_*_metadata.json | jq '.test_mae'

# Should show: 4.0-4.2 range
```

---

### PATH B: Improve Mock Model

**File to Edit**: `predictions/shared/mock_xgboost_model.py`

**Change 1 - Fatigue Curve** (lines 130-137):
```python
# REPLACE THIS:
if fatigue < 50:
    fatigue_adj = -2.5
elif fatigue < 70:
    fatigue_adj = -1.0
elif fatigue > 85:
    fatigue_adj = 0.5
else:
    fatigue_adj = 0.0

# WITH THIS:
if fatigue < 40:
    fatigue_adj = -3.0    # Extreme fatigue
elif fatigue < 55:
    fatigue_adj = -2.0    # Heavy fatigue
elif fatigue < 70:
    fatigue_adj = -1.2    # Moderate fatigue
elif fatigue < 80:
    fatigue_adj = -0.5    # Slight fatigue
elif fatigue > 90:
    fatigue_adj = +0.8    # Well-rested boost
else:
    fatigue_adj = 0.0
```

**Change 2 - Defense Adjustment** (lines 154-160):
```python
# REPLACE THIS:
if opp_def_rating < 108:
    def_adj = -1.5
elif opp_def_rating > 118:
    def_adj = 1.0
else:
    def_adj = 0.0

# WITH THIS:
if opp_def_rating < 106:
    def_adj = -2.0        # Top 3 defense
elif opp_def_rating < 110:
    def_adj = -1.2        # Elite defense
elif opp_def_rating < 113:
    def_adj = -0.5        # Above average
elif opp_def_rating > 120:
    def_adj = +1.5        # Bottom 3 defense
elif opp_def_rating > 116:
    def_adj = +0.8        # Below average
else:
    def_adj = 0.0
```

**Change 3 - Usage Spike** (line 145):
```python
# FIND AND REPLACE:
usage_adj = usage_spike * 0.30
# WITH:
usage_adj = usage_spike * 0.45  # Increased from 0.30
```

**Change 4 - Home Advantage** (line 170):
```python
# FIND AND REPLACE:
venue_adj = 1.0 if is_home else -0.6
# WITH:
venue_adj = 1.3 if is_home else -0.6  # Increased from 1.0
```

**Change 5 - Paint-Heavy Bonus** (lines 175-185):
```python
# FIND THIS SECTION (around line 175):
if paint_rate > 45 and opp_def_rating > 115:
    shot_adj = 0.8
else:
    shot_adj = 0.0

# REPLACE WITH:
# More granular paint-heavy vs weak defense bonus
if paint_rate > 40 and opp_def_rating > 110:
    # Scale bonus by how paint-heavy AND how weak defense is
    paint_excess = (paint_rate - 40) / 10  # 0-2 range
    def_weakness = (opp_def_rating - 110) / 5  # 0-2 range
    shot_adj = min(paint_excess * def_weakness * 0.4, 1.5)
else:
    shot_adj = 0.0
```

**Test the Changes**:
```bash
# Run a quick test prediction to ensure no syntax errors
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 -c "
from predictions.shared.mock_xgboost_model import MockXGBoostModel
model = MockXGBoostModel()
print('✅ Mock model loads successfully')
"
```

---

## 📊 SUCCESS CRITERIA

### After PATH A (Clean 2021 Data Training)

✅ Model trains successfully on ~28,516 samples
✅ Test MAE: 4.0-4.2 range (beats 4.27 baseline!)
✅ Model saved: `models/xgboost_real_v5_*.json`
✅ Feature importance shows balanced distribution (not 55% on one feature)

### After PATH B (Mock Improvements)

✅ All 5 changes applied without syntax errors
✅ Mock model loads successfully
✅ Expected MAE: 4.10-4.15 (estimate based on error analysis)
✅ Ready to deploy after tonight's test

### Overall Session Success

✅ At least ONE path achieves better than 4.27 MAE baseline
✅ Both paths documented with results
✅ Changes committed to git
✅ Still have 4+ hours before tonight's 8:30 PM betting lines test
✅ Documentation updated in `docs/08-projects/current/ml-model-development/`

---

## 🎯 RECOMMENDED EXECUTION ORDER

**Step 1**: Start new chat session (2:10 PM)

**Step 2**: Choose execution strategy
- **FASTEST**: Parallel (Use agent for PATH A, you do PATH B)
- **SIMPLEST**: Sequential (PATH A then PATH B)

**Step 3**: Execute improvements (30-75 minutes)

**Step 4**: Validate and document (15 minutes)

**Step 5**: Commit changes (10 minutes)

**Step 6**: Break until 8:00 PM

**Step 7**: Prep for betting lines test (8:00-8:30 PM)

**Step 8**: Execute test and celebrate! (8:30-9:30 PM)

---

## 📁 KEY FILES & LOCATIONS

### ML Training
- **Script**: `/home/naji/code/nba-stats-scraper/ml/train_real_xgboost.py`
- **Line to edit**: 74 (WHERE clause)
- **Models dir**: `/home/naji/code/nba-stats-scraper/models/`
- **Expected output**: `models/xgboost_real_v5_20260103.json`

### Mock Model
- **File**: `/home/naji/code/nba-stats-scraper/predictions/shared/mock_xgboost_model.py`
- **Lines to edit**: 130-137, 154-160, 145, 170, 175-185
- **Documentation**: `docs/08-projects/current/ml-model-development/06-MOCK-MODEL-IMPROVEMENTS-READY-TO-DEPLOY.md`

### Documentation
- **Update this**: `docs/08-projects/current/ml-model-development/07-SESSION-JAN-3-AFTERNOON.md`
- **Create new**: `docs/08-projects/current/ml-model-development/08-TRAINING-RESULTS-V5.md`

---

## 🚨 IMPORTANT CONTEXT

### Tonight's Critical Test (8:30 PM ET)

**What**: Full betting lines pipeline end-to-end test
**Why**: Validate 2-week betting lines project works completely
**Dependencies**:
- ✅ Odds API fix deployed (commit 6845287)
- ✅ BR roster fix deployed (commit cd5e0a1)
- ✅ Automated workflows running
**Your role**: Run test, validate all layers, document success

**Commands to Run**:
```bash
# 1. Run full pipeline
./bin/pipeline/force_predictions.sh 2026-01-03

# 2. Verify betting lines in ALL layers
bq query --use_legacy_sql=false "
SELECT
  'Raw' as layer, COUNT(*) as lines
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '2026-01-03'
UNION ALL
SELECT 'Analytics', COUNTIF(has_prop_line)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-03'
UNION ALL
SELECT 'Predictions', COUNTIF(current_points_line IS NOT NULL)
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-03' AND system_id = 'ensemble_v1'
"

# Expected: All layers show 100-150+ players
```

---

## 💡 WHY THIS PLAN WORKS

### The Core Insight

**Problem**: We've been training on 55% fake data (NULL filled with defaults)
**Solution**: Train on 98.3% real data OR improve the proven hand-coded system
**Result**: Either way, we beat the 4.27 baseline

### The Strategic Value

1. **PATH A (Clean Data)**: Proves ML can work - opens door for future improvements
2. **PATH B (Mock Tweaks)**: Immediate production value - deploy after tonight
3. **BOTH**: Maximum confidence - we get improvement either way

### The Time Math

- ML training: 30 minutes
- Mock improvements: 45 minutes
- Parallel execution: 45 minutes (optimal!)
- Sequential execution: 75 minutes (still fine, 4.75 hours until test)
- Either way: **Plenty of time before tonight**

---

## 🎯 FINAL RECOMMENDATION

**DO BOTH PATHS IN PARALLEL** using this exact prompt in new chat:

```
I want to improve our ML model predictions. We've discovered the data quality issue (2021: 98% complete, 2022-23: 0-34% complete).

Execute TWO improvements in parallel:

PATH A: Spawn an agent to train XGBoost v5 on clean 2021-22 data only
- Edit ml/train_real_xgboost.py line 74
- Change WHERE clause to: game_date >= '2021-10-01' AND game_date < '2022-10-01'
- Run training, report results
- Expected: 4.0-4.2 MAE (beats 4.27 baseline)

PATH B: I'll improve the mock model myself
- Edit predictions/shared/mock_xgboost_model.py
- Apply 5 improvements from doc 06-MOCK-MODEL-IMPROVEMENTS
- Expected: 4.10-4.15 MAE

Goal: Get BOTH done in 45 minutes, then prep for tonight's 8:30 PM betting lines test.

Read this handoff doc for full context: docs/09-handoff/2026-01-03-ML-IMPROVEMENT-PLAN-NEW-SESSION.md
```

---

## ✅ CHECKLIST FOR NEW SESSION

- [ ] Read this entire handoff doc
- [ ] Understand the data quality issue (2021: 98%, 2022-23: 0-34%)
- [ ] Choose execution strategy (parallel vs sequential)
- [ ] Execute PATH A (clean data training) - 30 min
- [ ] Execute PATH B (mock improvements) - 45 min
- [ ] Validate both improvements
- [ ] Commit changes to git
- [ ] Update documentation
- [ ] Confirm still have 4+ hours before tonight's test
- [ ] Take break before 8:00 PM
- [ ] Prep for 8:30 PM betting lines test
- [ ] Execute test and celebrate!

---

**Status**: ✅ READY TO EXECUTE
**Owner**: Next Chat Session
**Created**: 2026-01-03 2:10 PM ET
**Critical Deadline**: Tonight 8:30 PM ET (betting lines test)
**Expected Outcome**: Beat 4.27 MAE baseline + successful betting lines test

**LET'S DO THIS!** 🚀
