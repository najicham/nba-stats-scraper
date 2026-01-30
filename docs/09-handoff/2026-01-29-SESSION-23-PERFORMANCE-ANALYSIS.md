# Session 23 Handoff - CatBoost V8 Performance Analysis

**Date:** 2026-01-29
**Previous Session:** 22 (Line Validation and Cleanup)
**Focus:** Deep analysis of CatBoost V8 prediction performance

---

## Critical Discovery: Data Leakage Invalidates Historical Results

### The Problem

On January 9, 2026, **114,884 predictions were generated retroactively** for games from 2021-2025. The model was trained on Nov 2021 - June 2024 data, meaning these "predictions" were made on data the model had already seen.

| Year | Predictions | Created | Valid? |
|------|-------------|---------|--------|
| 2021-2024 | 89,000+ | 2026-01-09 | NO - training data |
| 2025 early | 28,000+ | 2026-01-09 | NO - retroactive |
| 2026 Jan 12+ | ~1,737 | Before game | YES - forward-looking |

### Impact

- **Reported 73% hit rate:** INVALID (data leakage)
- **True 2026 performance:** ~54% overall, ~66% with filtering
- **Realistic expectation:** 55-65% with proper filtering

---

## Issues Identified

### 1. Data Leakage (Critical)
- Historical predictions generated AFTER training on same data
- Cannot trust any hit rate metrics on 2021-2024 data

### 2. Confidence Scale Bug (High)
- Some predictions use 0-1 scale, others use 0-100
- Percent-scale 95%+ = 66% hit rate
- Decimal-scale all tiers = 48-52% (coin flip)

### 3. Line Source Attribution (Medium)
- ~38% of predictions have unverifiable line sources
- Backfills create phantom lines that don't exist in raw data

### 4. Feature Passing Bug (High)
- Already documented in Session 20
- Worker doesn't pass Vegas/opponent/PPM features correctly
- Causes extreme predictions (60+ points)

---

## Performance Summary

### True Forward-Looking Performance (Jan 12-28, 2026)

| Filter | Predictions | Hit Rate | ROI |
|--------|-------------|----------|-----|
| All predictions | 2,365 | 54% | ~3% |
| Percent-scale 95%+ | 732 | **66%** | ~20% |
| BETTINGPROS lines | ~1,000 | 57% | ~9% |
| ODDS_API lines | ~1,300 | 52% | ~0% |

### Can We Achieve 70%+?

**Possibly, with aggressive filtering:**
- 95%+ confidence (percent scale only)
- BETTINGPROS lines only
- Forward-looking predictions only
- This reduces volume to ~10-20 predictions/day

---

## New Documentation Created

### `/docs/08-projects/current/catboost-v8-performance-analysis/`
New project directory for model performance analysis:

- `CATBOOST-V8-PERFORMANCE-ANALYSIS.md` - Comprehensive analysis
- `README.md` - Project overview

### Key Queries Documented

- Forward-looking predictions filter
- Confidence scale detection
- Line source verification
- Daily monitoring query

---

## Next Session Recommendations

### Priority 1: Validate True Performance
1. Run the monitoring query to get clean forward-looking metrics
2. Track daily performance from Jan 29 onwards
3. Separate percent-scale vs decimal-scale predictions

### Priority 2: Fix Bugs
1. Fix confidence scale (standardize to 0-100)
2. Ensure feature passing is correct (Session 20 fix)
3. Add `is_forward_looking` flag to predictions

### Priority 3: Decide on Retraining
After 2-3 weeks of clean data:
1. Evaluate if current model is viable
2. If not, plan retraining with proper train/test split
3. Consider hyperparameter tuning

---

## Key Questions for Next Session

1. **What's the true forward-looking hit rate** after filtering?
2. **Is the confidence scale fix deployed?** Need to verify
3. **Should we retrain** or tune the current model?
4. **What's the minimum viable hit rate** for profitability?

---

## Files Changed

| File | Change |
|------|--------|
| `docs/08-projects/current/catboost-v8-performance-analysis/CATBOOST-V8-PERFORMANCE-ANALYSIS.md` | Created |
| `docs/08-projects/current/catboost-v8-performance-analysis/README.md` | Created |
| `docs/09-handoff/2026-01-29-SESSION-23-PERFORMANCE-ANALYSIS.md` | Created |

---

## Summary for User

**Bottom line:** The 73% hit rate was too good to be true. It was caused by evaluating the model on data it was trained on. True out-of-sample performance is ~54% overall, but **~66% with high-confidence filtering** (95%+, percent scale).

To achieve 70%+, you'll need aggressive filtering which reduces prediction volume significantly. The next step is to collect 2-3 weeks of clean forward-looking data and reassess.

---

*Session 23 Complete*
*Next: New chat to validate clean data and true performance*
