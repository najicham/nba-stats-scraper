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
- `[pending]` - Remove thresholds in shadow mode

---

## Next Steps

1. ~~Implement threshold-free shadow mode~~ Done
2. Run shadow mode during 2026 season (starts late March)
3. Collect ~30 days of data
4. Analyze accuracy by edge bucket
5. Determine optimal V1.6 threshold for production
