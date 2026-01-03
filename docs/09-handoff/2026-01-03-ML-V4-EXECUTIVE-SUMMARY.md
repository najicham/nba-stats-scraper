# ML v4 Investigation - Executive Summary

**Date**: 2026-01-03
**Status**: ✅ Investigation Complete
**Reading Time**: 2 minutes

---

## 🎯 The Bottom Line

**v4 DID NOT perform worse than v3.** Documentation bugs and training script issues created a false narrative.

### The Truth:
- ✅ v4 improved over v3 by 1.2% (4.88 vs 4.94 MAE)
- ❌ Both still 14-16% worse than production mock (4.27 MAE)
- 🐛 Training script compares against wrong baseline (9.19 instead of 4.27)
- 📝 v3 handoff doc referenced wrong training run (4.63 vs actual 4.94)

---

## 📊 Corrected Performance Table

| Model | Test MAE | vs Production (4.27) | Status |
|-------|----------|---------------------|--------|
| **Production Mock** | **4.27** | - | ✅ **BEST** |
| v4 (latest) | 4.88 | -14.3% worse | ⚠️ Better than v3 |
| v3 (saved model) | 4.94 | -15.7% worse | ❌ |
| v2 | 4.63 | -8.4% worse | ❌ |
| v1 | 4.79 | -12.2% worse | ❌ |

**Production verified from BigQuery**: `xgboost_v1` system achieves 4.27 MAE on test period.

---

## 🐛 Critical Bugs Found

### 1. Training Script Mock Comparison (HIGH PRIORITY FIX)
**File**: `ml/train_real_xgboost.py:518-528`

**Problem**: Compares against `mock_prediction` column which contains corrupted data
- Script reports: 9.19 MAE (v4) or 8.65 MAE (v3)
- Reality: 4.27 MAE (verified from production)
- All models falsely claim "46% improvement" when they're actually worse

**Impact**: Wasted 12+ hours of effort on false confidence

**Fix**: Query production predictions directly instead of using joined column
- Time: 30 minutes
- See detailed fix in: `docs/09-handoff/2026-01-03-ML-V4-INVESTIGATION-FINDINGS.md`

### 2. v3 Documentation Mismatch
**Problem**: Handoff doc reported v3 = 4.63 MAE, but saved model has 4.94 MAE
- Two training runs happened (19:21 and 21:52)
- First run (4.63) was logged but not saved
- Second run (4.94) was saved to `models/` but not documented

**Impact**: Everyone thought v4 (4.88) was worse than v3 (assumed 4.63)

---

## ✅ What v4 Actually Achieved

Despite not beating production, v4 made legitimate improvements:

1. **Removed noise**: Deleted 4 zero-valued placeholder features
2. **Fixed missing data**: Added COALESCE fallback for minutes_played (was 95% NULL)
3. **Better hyperparameters**: Depth 8, lr 0.05, early stopping
4. **Better generalization**: Val MAE improved 4.72 → 4.60

**Result**: 1.2% improvement over v3 (4.94 → 4.88)

---

## 💡 Why ML Can't Beat Mock (Yet)

**Mock uses hand-tuned thresholds**:
```python
if back_to_back: adjustment -= 2.2  # Strong penalty
if is_home: adjustment += 1.0       # Clear bonus
```

**XGBoost learned much weaker signals**:
```
back_to_back importance: 1.5%  ← Should be much higher
is_home importance: 1.6%       ← Should be much higher
```

**Why**: 64K samples insufficient to learn precise domain-expert thresholds

**What would help**:
- More data (>100K samples)
- Better features (referee, travel, injury data)
- Deep learning (can learn complex non-linear patterns)
- Ensemble methods (combine v4 + mock)

**None guaranteed to beat 4.27**

---

## 🎯 Recommendations

### Option A: Accept Mock Baseline ✅ RECOMMENDED

**Stop trying to beat 4.27 with current approach**

**Why**:
1. 4 attempts failed (v1, v2, v3, v4)
2. Mock is actually good (beats 4 other production systems)
3. Low ROI: 3+ hours for 1.2% improvement
4. Better to focus on data quality

**Action items**:
- ✅ Document 4.27 as production standard
- ✅ Fix training script bug (30 min)
- ✅ Archive v3/v4 models (not production-ready)
- ✅ Focus on: data quality, backfill, feature collection

**Revisit ML in 3-6 months when**:
- >100K samples available
- Referee/travel/injury data collected
- Advanced techniques explored

---

### Option B: Try v5 ⚠️ NOT RECOMMENDED

**Only if leadership demands beating 4.27 regardless of cost**

| Approach | Expected MAE | Effort | Success Probability |
|----------|--------------|--------|-------------------|
| Ensemble (v4 + mock) | 4.50-4.60 | 2 hours | 5% |
| LightGBM/CatBoost | 4.70-4.85 | 4 hours | 10% |
| Grid search | 4.75-4.85 | 8 hours | 15% |
| Deep learning | 3.80-4.50 | 2-3 days | 30% (high risk) |

**Cost-benefit**: All options have low probability relative to effort

---

### Option C: Fix Training Script Bug 🐛 DO IMMEDIATELY

**Must do regardless of Option A or B**

**Priority**: HIGH
**Time**: 30 minutes
**Impact**: Prevents future false positives

See detailed fix in main findings document.

---

## 📁 Key Files

### Read This First
- `docs/09-handoff/2026-01-03-ML-V4-INVESTIGATION-FINDINGS.md` (full analysis)

### Training Script (HAS BUG)
- `ml/train_real_xgboost.py:518-528` (fix mock comparison)

### Saved Models
- `models/xgboost_real_v4_21features_20260102.json` (v4: 4.88 MAE)
- `models/xgboost_real_v3_25features_20260102.json` (v3: 4.94 MAE)

### Production Mock
- `predictions/shared/mock_xgboost_model.py` (4.27 MAE)

---

## 🔑 Key Takeaways

1. **v4 is better than v3** (4.88 vs 4.94 MAE) ✅
2. **Both are worse than production** (4.27 MAE) ❌
3. **Training script has critical bug** → fix immediately 🐛
4. **Hand-tuned rules beat ML** (for now, with 64K samples) 📊
5. **Stop iterating, focus on data** → revisit in 3-6 months ⏸️

---

## 🚀 Immediate Next Steps

**Today (30 min)**:
1. Fix training script mock comparison bug
2. Commit corrected training script
3. Update team on findings

**This Week (DO NOT)**:
- ❌ Do not train v5 (low ROI)
- ❌ Do not try to beat 4.27 with current data
- ❌ Do not deploy v3 or v4 to production

**This Week (DO)**:
- ✅ Accept mock baseline (4.27 MAE) as production standard
- ✅ Focus on historical backfill (increase samples)
- ✅ Fix data quality issues (95% missing minutes_played)
- ✅ Plan feature collection (referee, travel, injury)

**In 3-6 Months**:
- Revisit ML when >100K samples and better features available

---

**Investigation complete**: 2026-01-03
**Decision required**: Choose Option A or B
**Recommended**: Option A (accept mock) + Option C (fix bug)
