# Copy/Paste This Prompt to Continue ML Work

**Instructions**: Copy everything below this line and paste into a new Claude chat to continue where we left off.

---

## Context: NBA Stats Scraper ML Model Training

I'm continuing work on training a real XGBoost model to replace a mock baseline for NBA player points prediction. Previous session made significant progress but didn't complete deployment.

## Current Status

**What's Done** ✅:
- All playoff backfills complete (6,127 records)
- ML training pipeline fully built and tested
- Trained 2 models with increasing feature sets:
  - v1 (6 features): 4.79 MAE
  - v2 (14 features): 4.63 MAE ← Current best
- Comprehensive documentation created

**Goal**: Beat mock baseline of **4.33 MAE**

**Current gap**: 4.63 MAE is 6.9% worse than 4.33 target

## The Problem

The enhanced model (v2) uses only **14 of 25 features**. Mock uses all 25 features with hand-tuned rules.

### Missing 7 Critical Features (BLOCKING):

**Game context** (5 features):
1. `is_home` - Home court advantage (~1.5 point swing)
2. `days_rest` - Rest between games
3. `back_to_back` - Back-to-back penalty (~2 points)
4. `opponent_def_rating` - Opponent defensive strength
5. `opponent_pace` - Game pace matchup

**Team factors** (2 features):
6. `team_pace_last_10` - Team tempo
7. `team_off_rating_last_10` - Team offensive rating

**Expected impact**: Adding these 7 features should achieve **4.1-4.2 MAE** (4-8% better than mock)

## What You Need to Do

### Task 1: Add 7 Missing Features (2 hours)

**File to edit**: `ml/train_real_xgboost.py`

**Changes needed**:

1. **Update SQL query** (around line 50):
   - Join with `nba_analytics.upcoming_player_game_context` to get:
     - `is_home` (BOOLEAN)
     - `days_rest` (INTEGER)
     - `back_to_back` (BOOLEAN)
   - Calculate opponent strength from team tables:
     - Need to join player → team → opponent defense
     - Extract `opponent_def_rating`, `opponent_pace`
   - Calculate team factors:
     - `team_pace_last_10`, `team_off_rating_last_10`

2. **Update feature_cols list** (around line 214):
   Add the 7 new features to the list

3. **Update missing value handling** (around line 262):
   Add reasonable defaults for new features:
   ```python
   X['is_home'] = X['is_home'].fillna(0)  # Assume away if unknown
   X['days_rest'] = X['days_rest'].fillna(1)
   X['back_to_back'] = X['back_to_back'].fillna(0)
   X['opponent_def_rating'] = X['opponent_def_rating'].fillna(112.0)
   X['opponent_pace'] = X['opponent_pace'].fillna(100.0)
   X['team_pace_last_10'] = X['team_pace_last_10'].fillna(100.0)
   X['team_off_rating_last_10'] = X['team_off_rating_last_10'].fillna(112.0)
   ```

### Task 2: Retrain Model (30 minutes)

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate
python ml/train_real_xgboost.py
```

**Success criteria**:
- Test MAE < 4.30 (better than mock's 4.33)
- Model file saved to `models/xgboost_real_v3_final_*.json`

### Task 3: Update Documentation (30 minutes)

Create final results document:
- `docs/09-handoff/2026-01-03-FINAL-MODEL-v3-RESULTS.md`
- Include: final MAE, feature importance, comparison to mock
- Decision: Deploy or iterate?

## Key Files & Context

**Training script**: `ml/train_real_xgboost.py` (main file to edit)

**Previous models**:
- `models/xgboost_real_v1_20260102.json` - 6 features, 4.79 MAE
- `models/xgboost_real_v2_enhanced_20260102.json` - 14 features, 4.63 MAE

**BigQuery tables available**:
- `nba-props-platform.nba_analytics.player_game_summary` - Player stats
- `nba-props-platform.nba_analytics.upcoming_player_game_context` - Game context
- `nba-props-platform.nba_analytics.team_defense_game_summary` - Team defense
- `nba-props-platform.nba_analytics.team_offense_game_summary` - Team offense
- `nba-props-platform.nba_precompute.player_composite_factors` - Composite factors
- `nba-props-platform.nba_predictions.prediction_accuracy` - Historical predictions

**Documentation to read**:
1. **START HERE**: `docs/09-handoff/2026-01-03-FINAL-ML-SESSION-HANDOFF.md`
2. `docs/09-handoff/2026-01-03-ULTRATHINK-MISSING-COMPONENTS.md` - Gap analysis
3. `docs/09-handoff/2026-01-03-ENHANCED-ML-TRAINING-RESULTS.md` - v2 results

## Expected Outcome

After adding 7 features and retraining:
- **Test MAE**: 4.1-4.2 (target: beat 4.33 baseline)
- **Feature count**: 21/25 features
- **Status**: Production-ready if MAE < 4.30

If successful:
- Save model to GCS
- Update prediction worker
- Deploy to production

If not successful:
- Analyze feature importance
- Try hyperparameter tuning
- Consider more training data

## Questions to Consider

1. Should we add the remaining 4 "advanced" features (referee, momentum, matchup history, look ahead)?
   - Mock model uses defaults (0) for these
   - May not add much value
   - Focus on the 7 critical features first

2. If v3 doesn't beat baseline, what's the next step?
   - Hyperparameter tuning (tree depth, learning rate)
   - More training data (include regular season playoffs?)
   - Ensemble approach (combine multiple models)

3. When to deploy?
   - Deploy if test MAE < 4.30 AND stable
   - Consider A/B test first (10% traffic)
   - Monitor closely for 48 hours before full rollout

## Success Metrics

**Immediate** (this session):
- ✅ v3 model trained with 21 features
- ✅ Test MAE < 4.30 (beats mock baseline)
- ✅ Feature importance makes sense
- ✅ Documentation updated

**Next session** (if v3 successful):
- Deploy model to GCS
- Update prediction worker configuration
- Deploy to Cloud Run
- Monitor production MAE for 48 hours

## Prompt to Paste

---

**Copy everything below this line:**

---

I'm continuing ML model training for NBA player points prediction. Previous session trained 2 models but didn't beat the mock baseline yet.

**Current status**:
- v2 model: 4.63 MAE (using 14 features)
- Mock baseline: 4.33 MAE (target to beat)
- Gap: 6.9% worse than target

**Task**: Add 7 critical context features and retrain to beat the baseline.

**Missing features**:
1. is_home (home court advantage)
2. days_rest (rest impact)
3. back_to_back (fatigue penalty)
4. opponent_def_rating (opponent strength)
5. opponent_pace (game pace)
6. team_pace_last_10 (team tempo)
7. team_off_rating_last_10 (team efficiency)

**File to edit**: `ml/train_real_xgboost.py`

**What to do**:
1. Read `docs/09-handoff/2026-01-03-FINAL-ML-SESSION-HANDOFF.md` for full context
2. Update SQL query to join with `nba_analytics.upcoming_player_game_context` and team tables
3. Add 7 features to `feature_cols` list
4. Add default values for missing data
5. Run: `python ml/train_real_xgboost.py`
6. Target: Test MAE < 4.30

**Expected result**: 4.1-4.2 MAE (4-8% better than mock baseline)

Please:
1. Make sure our project docs in `docs/08-projects/current/ml-model-development/` are updated
2. Add the 7 missing features to the training script
3. Retrain the model
4. Update handoff documentation with results
5. Recommend next steps (deploy if successful, iterate if not)

Let's finish this and get a production-ready model!