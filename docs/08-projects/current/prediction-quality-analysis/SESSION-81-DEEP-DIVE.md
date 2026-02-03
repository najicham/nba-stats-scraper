# Prediction Quality Deep Dive - Session 81

**Date:** February 2, 2026
**Session:** 81
**Focus:** Understanding why catboost_v9 shows 33% overall hit rate vs 79% high-edge hit rate

---

## Executive Summary

**The Mystery:** catboost_v9 showed 33.2% overall hit rate but 79% hit rate on high-edge picks.

**The Answer:**
1. **39% of "predictions" were PASS** (non-bets, ties) with 0% hit rate, included in original calculation
2. **73% of actual bets had edge < 3** and lost money (~50% hit rate)
3. **Only 27% of bets were profitable** (edge 3+, 65% hit rate)

**Real Performance:** 54.7% hit rate on actual bets, +4.5% ROI

**Solution:** Filter to edge >= 3 for **+43% more profit** and **24% ROI**

---

## The Complete Analysis

### Data Set: catboost_v9 Graded Predictions

- **Date Range:** Jan 9 - Feb 1, 2026
- **Total Predictions:** 2,535
- **Line Source:** ACTUAL_PROP only
- **System:** catboost_v9 (original V9 model)

### Discovery #1: PASS Predictions Misleading

**Original Hit Rate Calculation (WRONG):**
```sql
SELECT COUNT(*) as total, COUNTIF(prediction_correct) as correct
FROM prediction_accuracy
WHERE system_id = 'catboost_v9'
-- Result: 2535 total, 842 correct = 33.2% hit rate
```

**Problem:** Includes 997 PASS recommendations (39% of predictions)
- PASS = Predicted points equals line exactly (tie, no bet)
- PASS = Error/fallback conditions
- PASS always has 0% "hit rate" because it's not a directional bet

**Correct Calculation:**
```sql
-- Exclude PASS/HOLD (non-bets)
WHERE recommendation IN ('OVER', 'UNDER')
-- Result: 1537 actual bets, 841 correct = 54.7% hit rate
```

**Lesson:** Always filter to `recommendation IN ('OVER', 'UNDER')` for hit rate analysis.

---

### Discovery #2: Edge Matters, Confidence Doesn't

**Hit Rate and Profitability by Edge (Actual Bets Only):**

| Edge Range | Bets | % Total | Hit Rate | Profit (units) | ROI | Status |
|------------|------|---------|----------|----------------|-----|--------|
| 0-2 | 754 | 49% | 51.1% | -19.0 | -2.5% | ❌ Losing |
| 2-3 | 375 | 24% | 50.9% | -10.4 | -2.8% | ❌ Losing |
| 3-5 | 265 | 17% | 57.4% | +25.2 | +9.5% | ✅ Winning |
| 5+ | 143 | 9% | 79.0% | +72.7 | +50.9% | ✅✅ Excellent |
| **TOTAL** | **1,537** | **100%** | **54.7%** | **+68.5** | **+4.5%** | ⚠️ Marginal |

**Key Findings:**
- **73% of bets are unprofitable** (edge < 3): 1,129 bets losing -29.4 units
- **27% of bets drive ALL profit** (edge 3+): 408 bets winning +97.9 units
- Need 52.4% hit rate to break even at -110 odds, edge < 3 bets are below this

---

### Discovery #3: Confidence Score Paradox

**Why high confidence (0.92+) has WORSE performance (49% vs 55%):**

| Confidence | Edge Group | Bets | Hit Rate | ROI |
|------------|------------|------|----------|-----|
| High (0.92+) | Edge 3+ | 11 | 63.6% | +21.5% |
| High (0.92+) | Edge < 3 | 134 | 47.8% | -8.8% |
| Normal (0.80-0.92) | Edge 3+ | 397 | 65.0% | +24.1% |
| Normal (0.80-0.92) | Edge < 3 | 995 | 51.5% | -1.8% |

**The Problem:**
- Model can be 95% confident predicting 18.2 when Vegas says 18.5 (low edge)
- **92% of high-confidence predictions** (134/145) have edge < 3 and lose money
- High confidence ≠ High edge ≠ Profitability

**Conclusion:** Confidence is NOT a useful filter. Edge is everything.

---

### Discovery #4: Optimal Edge Threshold

**Strategy Comparison:**

| Strategy | Bets | Hit Rate | Total Profit | ROI | % of Original |
|----------|------|----------|--------------|-----|---------------|
| **Current (Edge >= 0)** | 1,537 | 54.7% | +68.5 u | 4.5% | 100% |
| Proposed (Edge >= 2) | 783 | 58.2% | +87.5 u | 11.2% | 51% |
| **RECOMMENDED (Edge >= 3)** | 408 | 65.0% | **+97.9 u** | **24.0%** | 27% |
| Conservative (Edge >= 5) | 143 | 79.0% | +72.7 u | 50.9% | 9% |

**Why Edge >= 3 is Optimal:**
- ✅ **Maximizes total profit** (97.9 units vs 72.7 for edge >= 5)
- ✅ **Best risk/reward balance** (24% ROI, reasonable volume)
- ✅ **Maintains good sample size** (408 bets over 3 weeks = ~17 bets/day)
- ✅ **43% more profit than current** (97.9 vs 68.5 units)

**Why Edge >= 5 is Suboptimal:**
- ✅ Best ROI (50.9%)
- ❌ Sacrifices 25 units of profit for lower volume
- ❌ Only 9% of bets (too selective, ~5 bets/day)

---

## Recommendations

### 🎯 #1: Implement Edge >= 3 Filter (CRITICAL)

**Priority:** P0 - Immediate impact
**Effort:** Low (1-2 hours)
**Impact:** +43% profit, +19.5% ROI improvement

**Implementation Options:**

**Option A: Frontend Filtering (Quick)**
```python
# In website UI or API response
predictions = [p for p in predictions
               if abs(p['predicted_points'] - p['line_value']) >= 3]
```

**Option B: Coordinator Filtering (Better)**
```python
# In predictions/coordinator/coordinator.py
if require_edge_filter:
    predictions = [p for p in predictions
                   if p.get('edge', 0) >= 3]
```

**Option C: Pre-Prediction (Best - Future)**
- Analyze feature importance to predict when edge >= 3 likely
- Only run expensive model inference on high-edge opportunities
- Reduces costs by 73%

**Metrics to Track:**
- Daily bets with edge >= 3
- Hit rate on edge 3+ picks
- Total profit/ROI
- Alert if edge 3+ volume drops below 10 bets/day

---

### 🎯 #2: Fix Monitoring & Reporting

**Priority:** P1 - Prevents misinterpretation
**Effort:** Low (1 hour)

**Current Issues:**
- Shows "33% overall hit rate" (includes PASS non-bets)
- "Premium: 63.6% on 11 bets" (statistically noisy)
- Confidence-based filters don't work

**Fix:**

**Update `/hit-rate-analysis` skill:**
```sql
-- ALWAYS filter to actual bets
WHERE recommendation IN ('OVER', 'UNDER')

-- Show metrics by edge tier, not confidence
SELECT
  CASE
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'High Quality (5+ edge)'
    WHEN ABS(predicted_points - line_value) >= 3 THEN 'Medium Quality (3-5 edge)'
    ELSE 'Low Quality (<3 edge)'
  END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(SUM(CASE WHEN prediction_correct THEN 0.909 ELSE -1.0 END), 1) as profit,
  ROUND(SUM(CASE WHEN prediction_correct THEN 0.909 ELSE -1.0 END) / COUNT(*) * 100, 1) as roi_pct
FROM prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY tier
```

**Update CLAUDE.md:**
- Change "Premium Picks" definition from confidence to edge
- Remove confidence-based filters
- Add edge-based standard filters

---

### 🎯 #3: Stop Using Confidence Filters

**Priority:** P1 - Prevents bad bets
**Effort:** Low (documentation update)

**Current "Premium" Filter (BROKEN):**
```python
# DON'T USE THIS
confidence >= 0.92 AND edge >= 3
# Only 11 bets, 92% have edge < 3 and lose money
```

**New Quality Tiers:**
```python
# Use edge-based tiers instead
HIGH_QUALITY = edge >= 5      # 79% hit rate, 51% ROI
MEDIUM_QUALITY = 3 <= edge < 5  # 57% hit rate, 10% ROI
DONT_SHOW = edge < 3           # 50% hit rate, loses money
```

**Update in:**
- Website UI filtering
- Email/Slack notifications
- API documentation
- CLAUDE.md hit rate section

---

### 🎯 #4: Consider Pre-Filtering (Future Optimization)

**Priority:** P2 - Cost optimization
**Effort:** Medium (1-2 days)
**Savings:** 73% reduction in prediction costs

**Concept:**
- Currently: Generate all predictions, filter edge < 3 after
- Proposed: Identify edge >= 3 opportunities before expensive model inference

**Approach:**
1. Train lightweight "edge estimator" model
2. Fast feature-based heuristic (e.g., |recent_avg - vegas_line| >= 2)
3. Only run CatBoost on likely high-edge opportunities

**Benefits:**
- Reduce prediction worker compute costs (73% fewer predictions)
- Reduce grading costs (73% fewer grades)
- Faster user experience (no low-quality predictions to filter)
- Same profit (+97.9 units on edge 3+)

**Analysis Needed:**
- Feature importance for edge prediction
- Correlation between pre-inference features and final edge
- Cost/benefit of additional filtering step

---

## Queries for Future Analysis

### Check Current Edge Distribution
```sql
SELECT
  CASE
    WHEN ABS(predicted_points - current_points_line) < 2 THEN '<2'
    WHEN ABS(predicted_points - current_points_line) < 3 THEN '2-3'
    WHEN ABS(predicted_points - current_points_line) < 5 THEN '3-5'
    ELSE '5+'
  END as edge_bucket,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND line_source = 'ACTUAL_PROP'
GROUP BY edge_bucket
ORDER BY edge_bucket
```

### Monitor Edge 3+ Performance
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(SUM(CASE WHEN prediction_correct THEN 0.909 ELSE -1.0 END), 1) as profit
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND recommendation IN ('OVER', 'UNDER')
  AND ABS(predicted_points - line_value) >= 3
GROUP BY week
ORDER BY week DESC
```

---

## Next Steps

1. **Immediate (Today):**
   - Update CLAUDE.md with edge >= 3 recommendation
   - Document correct hit rate methodology (exclude PASS)
   - Add queries to project docs

2. **Short-term (This Week):**
   - Implement edge >= 3 filter in coordinator
   - Update monitoring to use edge-based tiers
   - Remove confidence-based filters from documentation

3. **Medium-term (Next Week):**
   - Analyze prediction distribution (Task #6)
   - Compare catboost_v9_2026_02 vs catboost_v9 (Task #5)
   - Evaluate pre-filtering feasibility

4. **Long-term (Next Month):**
   - Train edge estimator for pre-filtering
   - A/B test edge thresholds (2.5 vs 3.0)
   - Optimize for different user risk profiles

---

## References

- **Session:** 81 (Feb 2, 2026)
- **Data:** catboost_v9 predictions Jan 9 - Feb 1, 2026
- **Query Location:** Session 81 analysis queries (this document)
- **Related:** CLAUDE.md Hit Rate Measurement section

---

**Status:** Analysis complete ✅
**Action Items:** Update docs, implement edge >= 3 filter
**Impact:** +43% profit improvement available

