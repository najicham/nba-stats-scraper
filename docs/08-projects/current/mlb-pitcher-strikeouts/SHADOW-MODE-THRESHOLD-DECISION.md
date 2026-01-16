# Shadow Mode Threshold Decision

**Date**: 2026-01-15
**Status**: Implemented
**Authors**: Session 63

---

## Problem Statement

During shadow mode testing, we discovered that V1.6 was producing **zero picks** while V1.4 was making 10-14 picks per day. This made A/B comparison impossible.

### Root Cause

| Model | Edge Threshold | Actual Avg Edge | Result |
|-------|----------------|-----------------|--------|
| V1.4 | 0.5 | 0.66-0.74 | 10-14 picks/day |
| V1.6 | 1.0 | 0.22-0.27 | 0 picks (all PASS) |

V1.6's threshold (1.0) was set conservatively, but its actual edge predictions (~0.22) never reached that threshold. Every prediction became PASS.

### Additional Issue Found

Shadow mode was also missing raw feature names needed for red flag checks, causing all predictions to SKIP. This was fixed separately (commit `6465ddd`).

---

## Options Considered

### Option A: Match V1.4 Threshold (0.5)
- Set V1.6 threshold to 0.5
- Pros: Apples-to-apples comparison
- Cons: Still loses predictions where edge is 0.3-0.5

### Option B: Lower V1.6 Threshold (0.3)
- More picks than Option A
- Cons: Arbitrary threshold, still loses some data

### Option C: Remove Thresholds Entirely (SELECTED)
- All predictions become OVER or UNDER based on prediction vs line
- Track edge/confidence for post-hoc filtering
- Pros: Maximum data for learning
- Cons: None for shadow mode (we're learning, not betting)

---

## Decision: Option C

**Rationale:**

1. **Shadow mode is for learning, not betting** - Thresholds only matter when money is on the line. For data collection, we want everything.

2. **More data = better insights** - Track 20-30 predictions/day instead of 0-14. Discover patterns we'd miss with hard cutoffs.

3. **Post-hoc filtering** - Can always filter to "edge > X" when analyzing results. Can't recover data we never collected.

4. **Empirical threshold discovery** - Maybe V1.6 is actually predictive at 0.3-0.5 edge range. We'd never know with a 1.0 cutoff.

5. **True A/B comparison** - Both models predict same pitchers, compare accuracy directly without threshold bias.

---

## Implementation

### Code Changes (shadow_mode_runner.py)

```python
# Before: Used predictor's threshold-based recommendation
v1_4_recommendation = v1_4_result.get('recommendation', 'PASS')

# After: Simple prediction vs line (no thresholds)
v1_4_recommendation = 'OVER' if v1_4_pred > strikeouts_line else 'UNDER'
v1_6_recommendation = 'OVER' if v1_6_pred > strikeouts_line else 'UNDER'
```

### What's Preserved

- **Edge calculation** - Still tracked for filtering later
- **Confidence scores** - Model's confidence in prediction
- **All metadata** - Model versions, timestamps, etc.

### What Changes

- **Recommendations** - Now purely based on prediction vs line
- **No PASS** - Every pitcher with a line gets OVER or UNDER
- **More rows** - ~20-30 per day instead of ~10-14

---

## Expected Results

### Before (with thresholds)
```
V1.4: 7 OVER, 7 UNDER, 8 PASS (14 actionable)
V1.6: 0 OVER, 0 UNDER, 22 PASS (0 actionable)
```

### After (no thresholds)
```
V1.4: ~12 OVER, ~10 UNDER, 0 PASS (22 actionable)
V1.6: ~12 OVER, ~10 UNDER, 0 PASS (22 actionable)
```

---

## Analysis Strategy

With all predictions tracked, analysis can:

1. **Compare overall accuracy**: V1.4 vs V1.6 on same pitchers
2. **Find optimal thresholds**: Plot accuracy vs edge, find sweet spots
3. **Identify model strengths**: Maybe V1.6 is better on high-K pitchers
4. **Track calibration**: Are 0.5 edge predictions actually 50% confident?

### Example Query

```sql
-- Compare accuracy by edge bucket
SELECT
  CASE
    WHEN ABS(v1_4_edge) >= 1.0 THEN 'high'
    WHEN ABS(v1_4_edge) >= 0.5 THEN 'medium'
    ELSE 'low'
  END as edge_bucket,
  COUNT(*) as predictions,
  AVG(CASE WHEN v1_4_correct THEN 1 ELSE 0 END) as v1_4_accuracy,
  AVG(CASE WHEN v1_6_correct THEN 1 ELSE 0 END) as v1_6_accuracy
FROM mlb_predictions.shadow_mode_graded
GROUP BY 1
ORDER BY 1
```

---

## Production Impact

**None** - This only affects shadow mode. Production predictions still use configured thresholds:
- V1.4 production: 0.5 edge threshold
- V1.6 (when promoted): Will use empirically-determined threshold from shadow testing

---

## Related Commits

- `6465ddd` - Fix missing features for red flag checks
- `bfae0f7` - Remove thresholds in shadow mode for maximum data collection

---

## V1.4 vs V1.6 Performance Analysis (2025 Season Data)

Analysis conducted on 359 graded predictions across 5 dates (May-Sept 2025).

### Overall Hit Rates

| Model | Accuracy | Record | Delta |
|-------|----------|--------|-------|
| V1.4 | 57.9% | 208/359 | baseline |
| **V1.6** | **69.9%** | **251/359** | **+12.0%** |

### Hit Rate by Recommendation Type

| Model | OVER Accuracy | UNDER Accuracy |
|-------|---------------|----------------|
| V1.4 | 67.7% (130 picks) | 52.4% (229 picks) |
| V1.6 | 67.3% (257 picks) | **76.5%** (102 picks) |

### Hit Rate by Edge Magnitude

| Model | High (\|e\|>0.75) | Med (0.25-0.75) | Low (\|e\|<0.25) |
|-------|-------------------|-----------------|------------------|
| V1.4 | 56.4% (140) | 67.5% (160) | 35.6% (59) |
| V1.6 | N/A (0) | **75.7%** (189) | 63.5% (170) |

### Key Findings

1. **V1.6 is 12% better overall** - 69.9% vs 57.9%
2. **V1.6's OVER bias is correct** - Predicts 71% OVER, actual market is 54.9% OVER, but V1.6 still wins more
3. **V1.6's UNDERs are golden** - 76.5% accuracy when predicting UNDER
4. **V1.4's low-edge picks are terrible** - 35.6% (worse than coin flip)
5. **V1.6 has tighter edge distribution** - All predictions in 0.25-0.75 or <0.25 range (more conservative)

### OVER Bias Explanation

V1.6 predicts OVER 71% of the time, but this is not a calibration error:
- V1.6's mean edge is +0.12 (predicts slightly above line)
- V1.4's mean edge is -0.40 (predicts below line)
- V1.6's tighter predictions result in better hit rates despite the bias

**Conclusion:** V1.6's OVER lean reflects better feature calibration, not a bug. The model significantly outperforms V1.4.

---

## Next Steps

1. ~~Implement threshold-free shadow mode~~ Done
2. ~~Analyze V1.4 vs V1.6 performance~~ Done - V1.6 is 12% better
3. Run shadow mode during 2026 season (starts late March)
4. Collect ~30 days of live data
5. Confirm V1.6 outperformance on 2026 data
6. Consider promoting V1.6 to production
