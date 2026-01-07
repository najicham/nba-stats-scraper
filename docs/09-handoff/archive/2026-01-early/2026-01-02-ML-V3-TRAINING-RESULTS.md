# ML Model v3 Training Results - Session Report
**Date**: 2026-01-02
**Duration**: ~3 hours (ultrathink analysis + implementation + training)
**Objective**: Train v3 model with all 25 features to beat mock baseline
**Status**: ❌ **FAILED TO BEAT BASELINE**

---

## 🎯 EXECUTIVE SUMMARY

### What We Did
1. ✅ Deep codebase analysis using 4 parallel exploration agents
2. ✅ Validated data availability for 2021-2024 (precompute tables have full coverage)
3. ✅ Updated training script to 25 features (14 existing + 7 new + 4 placeholders)
4. ✅ Successfully trained v3 model
5. ❌ **Model performs WORSE than mock baseline**

### The Results

| Metric | Mock Baseline | v2 (14 features) | v3 (25 features) | Target |
|--------|---------------|------------------|------------------|--------|
| Test MAE | **4.27** ⭐ | 4.63 (-8.4%) | 4.63 (-8.4%) | < 4.27 |
| Samples | 9,829 | 9,643 | 9,643 | -- |
| Features | 25 (hand-tuned) | 14 | 25 | 25 |

### Key Finding
**Adding 7 new features + 4 placeholders provided ZERO improvement** over v2.
The model test MAE remained exactly 4.63 points.

---

## 📊 DETAILED ANALYSIS

### Model Performance Breakdown

**Training Performance:**
- Train MAE: 4.03
- Val MAE: 5.02
- Test MAE: 4.63
- **Validation significantly worse than test** → poor generalization

**Comparison to Mock (test period 2024-02-04 to 2024-04-14):**
- Mock: 4.27 MAE (47% within 3 pts, 68% within 5 pts)
- Real: 4.63 MAE (42% within 3 pts, 65% within 5 pts)
- **Gap: +0.36 points (8.4% worse)**

### Feature Importance (Top 10)

| Feature | Importance | Type |
|---------|-----------|------|
| points_avg_last_10 | 58.1% | Original |
| points_avg_season | 10.0% | Original |
| points_avg_last_5 | 6.9% | Original |
| three_pt_rate_last_10 | 1.9% | Original |
| **opponent_def_rating_last_15** | **1.9%** | **NEW** |
| **days_rest** | **1.9%** | **NEW** |
| **back_to_back** | **1.8%** | **NEW** |
| **opponent_pace_last_15** | **1.8%** | **NEW** |
| assisted_rate_last_10 | 1.7% | Original |
| **team_pace_last_10** | **1.7%** | **NEW** |

**Analysis:**
- Top 3 features (all original): 75% of importance
- All 7 new features combined: ~9% importance
- Model still heavily reliant on simple recent averages
- New context features ARE being used, but not enough to improve performance

---

## 🔍 DATA QUALITY INVESTIGATION

### Validation Queries Run

**1. Precompute Table Coverage** ✅
- team_defense_zone_analysis: 2021-11-02 to 2024-04-14 (521 dates)
- player_daily_cache: 2021-11-02 to 2024-04-14 (704 dates)
- **Both tables have complete historical coverage**

**2. Feature NULL Rates** ✅
- All new features: 0% NULL (thanks to COALESCE with defaults)
- Average values reasonable (team_pace: 99.47, opp_def: 113.23)
- **No data quality issues detected**

**3. Training Data Loaded**
- Total: 64,285 games (2021-11-06 to 2024-04-14)
- Unique players: 802
- **WARNING**: 60,893 missing values for minutes_avg_last_10 (95%!)
  - This was filled with 0, which might bias the model

---

## 🛠️ IMPLEMENTATION DETAILS

### Features Added (7 new + 4 placeholders = 11 total)

**New Real Features (7):**
1. `is_home` - Calculated from game_id parsing (`SPLIT(game_id, '_')[SAFE_OFFSET(2)] = team_abbr`)
2. `days_rest` - LAG window function on game_date
3. `back_to_back` - days_rest = 1
4. `opponent_def_rating_last_15` - From team_defense_zone_analysis
5. `opponent_pace_last_15` - From team_defense_zone_analysis.opponent_pace
6. `team_pace_last_10` - From player_daily_cache
7. `team_off_rating_last_10` - From player_daily_cache

**Placeholder Features (4):**
- referee_favorability_score = 0
- look_ahead_pressure_score = 0
- matchup_history_score = 0
- momentum_score = 0

### SQL Changes Made

1. **Added to player_games CTE:**
   - game_id, team_abbr, opponent_team_abbr columns
   - is_home calculation

2. **Added to player_performance CTE:**
   - days_rest (LAG window function)
   - back_to_back (CASE WHEN days_rest = 1)

3. **Added JOINs:**
   - LEFT JOIN to team_defense_zone_analysis (opponent metrics)
   - LEFT JOIN to player_daily_cache (team metrics)

4. **Feature ordering:**
   - Reordered all 25 features to match xgboost_v1.py worker expectations exactly

---

## 🚨 CRITICAL ISSUES DISCOVERED

### Issue 1: Mock Prediction Field is Unreliable ⚠️

**Problem**: The `mock_prediction` field in `prediction_accuracy` table shows MAE = 8.65, but actual mock performance is 4.27 MAE.

**Impact**: Training script's comparison is misleading (shows +46% improvement when actually -8.4%)

**Fix**: Always run proper evaluation query:
```sql
SELECT AVG(ABS(actual_points - predicted_points)) as true_mae
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'xgboost_v1'
  AND game_date BETWEEN '2024-02-04' AND '2024-04-14'
```

### Issue 2: minutes_avg_last_10 has 95% Missing Values ⚠️

**Problem**: 60,893 out of 64,285 records (94.7%) are missing minutes_avg_last_10

**Likely cause**: Window function returns NULL for early career games (first 10 games)

**Current handling**: Filled with 0 (may bias predictions downward)

**Recommended fix**: Fill with player's average minutes instead of 0

### Issue 3: Placeholder Features Add Noise ⚠️

**Problem**: 4 placeholder features (all zeros) waste model capacity

**Impact**: Model has to learn these features don't matter, reducing effective feature count

**Recommendation**: Train v4 with only 21 REAL features (remove 4 placeholders)

### Issue 4: Model Doesn't Generalize Well ⚠️

**Evidence**: Validation MAE (5.02) >> Test MAE (4.63)

**Possible causes**:
- Overfitting to training data (train MAE 4.03 is very low)
- Data distribution shift between validation and test periods
- Hyperparameters may need tuning (early stopping, regularization)

---

## 💡 WHY DID v3 FAIL TO IMPROVE?

### Hypothesis 1: Hand-Tuned Rules Are Genuinely Better

The mock model uses carefully crafted non-linear rules:
```python
# From mock_xgboost_model.py
if fatigue < 50: adjustment = -2.5
elif fatigue < 70: adjustment = -1.0
elif fatigue < 85: adjustment = 0
else: adjustment = +0.5

if back_to_back: adjustment -= 2.2
if opponent_def < 108: adjustment -= 1.5
if is_home: adjustment += 1.0
```

**XGBoost with 64k samples may not discover these exact thresholds.**

### Hypothesis 2: Placeholder Features Confuse the Model

4 features that are always 0 waste ~16% of feature slots (4/25).
Model capacity could be better used on real features.

### Hypothesis 3: Missing Data Bias

95% of records have minutes_avg_last_10 = 0 (filled from NULL).
This creates a strong bias toward zero for that feature, reducing its usefulness.

### Hypothesis 4: Feature Engineering Is Insufficient

The new features (is_home, days_rest, back_to_back) only account for ~5% of importance.
Mock model uses these features with strong non-linear rules that XGBoost isn't learning.

**Example**: Mock applies -2.2 point penalty for back-to-back.
XGBoost learned back_to_back has 1.8% importance (much weaker signal).

---

## 📈 COMPARISON TO PREVIOUS MODELS

| Model | Features | Test MAE | vs Mock | Status |
|-------|----------|----------|---------|--------|
| Mock | 25 (hand-tuned) | **4.27** | -- | 🏆 Current best |
| v1 | 6 | 4.79 | -12.2% | ❌ Too simple |
| v2 | 14 | 4.63 | -8.4% | ⚠️ No improvement |
| **v3** | **25** | **4.63** | **-8.4%** | **❌ No improvement** |

**Conclusion**: Adding features from 6 → 14 → 25 provided diminishing returns.
v2 to v3 provided ZERO improvement despite 11 new features.

---

## 🎯 RECOMMENDED NEXT STEPS

### Option 1: Train v4 Without Placeholders (RECOMMENDED)

**Approach**: Remove 4 placeholder features, train with 21 real features

**Expected outcome**: Slight improvement (4.55-4.60 MAE)

**Effort**: 30 minutes (quick edit + retrain)

**Rationale**: Placeholders waste model capacity on noise

### Option 2: Fix Missing Data and Retrain

**Approach**:
1. Fix minutes_avg_last_10 missing values (use player average, not 0)
2. Investigate other missing data patterns
3. Retrain v3 or v4

**Expected outcome**: Moderate improvement (4.40-4.50 MAE)

**Effort**: 2-3 hours (data investigation + fixes)

**Rationale**: 95% missing data for a key feature is a serious issue

### Option 3: Hyperparameter Tuning

**Approach**:
- Increase max_depth (6 → 8) for more complex rules
- Decrease learning_rate (0.1 → 0.05) for better convergence
- Add early stopping to prevent overfitting
- Increase n_estimators (200 → 500)

**Expected outcome**: Moderate improvement (4.30-4.45 MAE)

**Effort**: 3-4 hours (grid search + multiple training runs)

**Rationale**: Mock model uses complex non-linear rules that need deeper trees

### Option 4: Accept Mock Model and Move On (PRAGMATIC)

**Approach**: Keep using mock model, focus effort elsewhere

**Rationale**:
- Mock achieves 4.27 MAE with hand-tuned rules
- 3 training attempts (v1, v2, v3) all failed to beat it
- ML may not be better than domain expertise for this problem
- Other improvements might have higher ROI:
  - Better data collection
  - More frequent updates
  - Improved feature engineering for non-ML systems
  - Better monitoring and alerting

**Recommendation**: Accept mock model for now, revisit ML when:
- More training data available (>100k samples)
- Better features implemented (referee data, travel data, etc.)
- Advanced techniques available (deep learning, ensemble methods)

---

## 📁 FILES CREATED/MODIFIED

### Modified Files
- `/home/naji/code/nba-stats-scraper/ml/train_real_xgboost.py` (updated to 25 features)

### Created Files
- `/home/naji/code/nba-stats-scraper/models/xgboost_real_v3_25features_20260102.json` (trained model)
- `/home/naji/code/nba-stats-scraper/models/xgboost_real_v3_25features_20260102_metadata.json` (metadata)
- `/tmp/xgboost_v3_training.log` (full training log)

### Documentation
- `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-02-ML-V3-TRAINING-RESULTS.md` (this file)

---

## 🧠 KEY LEARNINGS

### Technical Insights

1. **More features ≠ better performance**
   v2 (14 features) = v3 (25 features) both at 4.63 MAE

2. **Placeholder features harm performance**
   4 zero-valued features waste 16% of model capacity

3. **Hand-tuned rules can beat ML**
   Domain expertise with careful thresholds > XGBoost on 64k samples

4. **Data quality matters more than quantity**
   95% missing values for key feature (minutes_avg_last_10) creates bias

5. **Mock prediction field is unreliable**
   Always validate with proper evaluation queries

### Process Insights

1. **Ultrathink analysis was valuable**
   4 parallel agents identified data availability issues upfront

2. **Data validation saved time**
   15-minute BigQuery checks prevented hours of wrong implementation

3. **Feature order matters for deployment**
   Worker expects exact feature order, must match precisely

4. **Testing assumptions is critical**
   Handoff docs claimed easy win, reality was different

---

## 📊 FINAL VERDICT

**Recommendation**: **DO NOT DEPLOY v3 MODEL**

**Reasons**:
1. ❌ 8.4% worse than mock baseline
2. ❌ No improvement over v2 despite 11 additional features
3. ❌ Poor generalization (val MAE >> test MAE)
4. ❌ Data quality issues (95% missing minutes_avg_last_10)

**Next Actions**:
1. **Immediate**: Try Option 1 (remove placeholders, train v4 with 21 features)
2. **Short-term**: Investigate and fix missing data issue (Option 2)
3. **Medium-term**: Hyperparameter tuning if v4 shows promise (Option 3)
4. **Fallback**: Accept mock model is good enough (Option 4)

---

## 🚀 COPY/PASTE PROMPT FOR NEXT SESSION

```
Continue ML model development for NBA points prediction.

Previous session (2026-01-02):
- Trained v3 model with 25 features (14 original + 7 new + 4 placeholders)
- Result: 4.63 MAE (8.4% WORSE than mock baseline 4.27 MAE)
- No improvement over v2 (also 4.63 MAE with 14 features)

Task: Train v4 model with 21 REAL features (remove 4 placeholders)

Files to edit:
- /home/naji/code/nba-stats-scraper/ml/train_real_xgboost.py

Changes needed:
1. Remove these placeholder features from SQL SELECT and feature_cols list:
   - referee_favorability_score
   - look_ahead_pressure_score
   - matchup_history_score
   - momentum_score

2. Update model_id to "xgboost_real_v4_21features"

3. Train model: python ml/train_real_xgboost.py

Expected: Slight improvement (4.55-4.60 MAE target)

Context docs:
- /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-02-ML-V3-TRAINING-RESULTS.md
- /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-COMPLETE-SESSION-HANDOFF.md
```

---

**END OF SESSION REPORT**
