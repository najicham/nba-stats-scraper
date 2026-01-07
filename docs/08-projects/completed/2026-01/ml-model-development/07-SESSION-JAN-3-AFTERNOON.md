# ML Training Session - Jan 3 Afternoon

**Started**: 1:45 PM ET
**Goal**: Train improved XGBoost model or improve mock baseline
**Status**: 🔍 INVESTIGATING

---

## Session Context

### What We Know

**Production Baseline**:
- System: `xgboost_v1` (actually hand-coded rules, not ML)
- Performance: 4.27 MAE (production test set)
- Algorithm: Weighted averages + 10 manual adjustments

**Existing ML Models**:
| Model | Features | Test MAE | Status |
|-------|----------|----------|--------|
| v1 | 6 | 4.79 | Too simple |
| v2 | 14 | 4.63 | Best so far |
| v3 | 25 | Not documented | Unknown |
| v4 | 21 | 4.88 | Overfitting |

**Data Quality Issue**:
- 95% of records missing minutes_played and usage_rate
- Causes XGBoost to rely too heavily on basic averages
- Results in underperformance vs hand-coded rules

---

## Current Situation Analysis

### Discovered While Starting Training

1. **Models v3 and v4 already exist**:
   ```
   xgboost_real_v3_25features_20260102.json  (created 9:52 PM Jan 2)
   xgboost_real_v4_21features_20260102.json  (created 11:41 PM Jan 2)
   ```

2. **v4 metadata shows**:
   - 21 features (all features implemented!)
   - Test MAE: 4.88 (WORSE than v2's 4.63)
   - Overfitting: train 4.11, val 4.60, test 4.88

3. **v2 is currently best ML model**:
   - 14 features
   - Test MAE: 4.63
   - Less overfitting

### The Problem

**Adding more features made the model WORSE:**
- v2 (14 features): 4.63 test MAE ✅
- v4 (21 features): 4.88 test MAE ❌

**Both are still worse than mock baseline:**
- Mock baseline: 4.27 MAE
- Best XGBoost: 4.63 MAE (7.8% worse)

---

## Strategic Options

### Option A: Tune Hyperparameters for 21-Feature Model

**Approach**: v4 has all features but is overfitting
**Solution**: Increase regularization, reduce depth

**Hyperparameter Changes**:
```python
# Current (v4)
max_depth=8, learning_rate=0.05, n_estimators=500

# Proposed (v5)
max_depth=5,           # Reduce from 8 (less complex trees)
learning_rate=0.08,    # Increase from 0.05 (faster, less overfit)
n_estimators=300,      # Reduce from 500
reg_alpha=0.1,         # Add L1 regularization (was 0)
reg_lambda=2.0,        # Increase L2 (was 1)
min_child_weight=5     # Increase from 3 (more conservative splits)
```

**Expected**: 4.4-4.5 test MAE (still worse than 4.27 baseline)
**Time**: 30 minutes

---

### Option B: Improve Mock Baseline (Quick Win)

**Approach**: Hand-coded rules are beating ML
**Solution**: Apply the 5 improvements from doc `06-MOCK-MODEL-IMPROVEMENTS-READY-TO-DEPLOY.md`

**Improvements**:
1. More gradual fatigue curve (5 thresholds instead of 3)
2. More nuanced defense adjustment (6 levels instead of 2)
3. Usage spike gets more weight (0.45 instead of 0.30)
4. Home advantage boost increased (1.3 instead of 1.0)
5. Paint-heavy vs weak defense bonus (more granular)

**Expected**: 4.10-4.15 MAE (3-4% better than current)
**Time**: 45 minutes

---

### Option C: Investigate Data Quality First

**Approach**: Fix NULL data problem before training more models
**Solution**: Check if recent backfills improved data quality

**Steps**:
1. Query player_game_summary for NULL percentages (5 min)
2. If still 95% NULL: Document and skip ML training
3. If improved: Retrain v4 with better data

**Time**: 15 minutes investigation

---

## Recommendation

**ULTRATHINK DECISION**:

Given:
- 6 hours until betting lines test
- ML models currently underperforming baseline
- Data quality issues persist
- Mock improvements are documented and ready

**RECOMMENDED: Option B (Improve Mock Baseline)**

**Reasoning**:
1. **Guaranteed improvement**: 4.27 → 4.10-4.15 MAE (3-4%)
2. **Low risk**: Tweaking existing proven system
3. **Time efficient**: 45 minutes vs 2-3 hours for ML debugging
4. **Immediate value**: Can deploy after tonight's test
5. **ML can wait**: Fix data quality issue separately, retrain later

**Alternative Plan**:
- Do Option C first (15 min) to check data
- If data improved: Try Option A (tuned model)
- If data still bad: Do Option B (mock improvements)

---

## Next Steps

**Decision needed from user**: Which path?

1. **Improve mock baseline** (45 min, guaranteed win)
2. **Tune XGBoost hyperparameters** (30 min, might not beat baseline)
3. **Check data quality first** (15 min, then decide)

---

**Status**: AWAITING DECISION
**Time**: 1:50 PM ET
**Buffer until test**: 6 hours 40 minutes
