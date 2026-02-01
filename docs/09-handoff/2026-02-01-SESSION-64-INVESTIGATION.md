# Session 64 Investigation - V8 Hit Rate Root Cause

**Date:** 2026-02-01
**Status:** Root Cause Confirmed, Ready for Fix
**Priority:** CRITICAL

---

## Executive Summary

Session 63 hypothesized that Vegas line coverage differences between daily and backfill modes caused the V8 hit rate collapse. **This hypothesis is WRONG.**

The actual root cause: **The Jan 30 morning backfill ran with broken code** that wasn't populating Vegas/opponent/PPM features correctly.

---

## Original Hypothesis: DISPROVEN

| Period | Vegas Coverage | Hit Rate | Conclusion |
|--------|---------------|----------|------------|
| Jan 1-7 | 37.5% | 66.1% | Lower coverage, HIGHER hit rate |
| Jan 9+ | 45.3% | 50.4% | Higher coverage, LOWER hit rate |

**Vegas coverage is NOT the issue.** Higher coverage correlates with WORSE hit rate!

---

## Actual Root Cause: Deployment Timing Bug

### Timeline (UTC)

| Time | Event | Impact |
|------|-------|--------|
| Jan 29 19:17 PST = Jan 30 03:17 UTC | Feature enrichment fix committed (ea88e526) | Fix in git but not deployed |
| Jan 30 07:41-08:37 UTC | Jan 9+ predictions backfilled | **Used BROKEN code** |
| Jan 30 19:10+ UTC | Fix finally deployed | Too late - backfill already done |

### The Bug (from commit ea88e526)

> "Worker wasn't populating Vegas/opponent/PPM features (indices 25-32). has_vegas_line=0.0 and ppm=0.4 defaults caused +29 point prediction errors"

This explains why predictions are systematically wrong in Jan 9+.

---

## Evidence

### Prediction Quality Metrics

| Metric | Jan 1-7 (good code) | Jan 9+ (broken code) | Impact |
|--------|---------------------|----------------------|--------|
| Mean Absolute Error | 4.3 pts | 5.8 pts | **35% worse** |
| Std Dev of Error | 5.6 | 7.4 | **32% worse** |
| Direction Accuracy | 66% | 51% | **15 pts worse** |
| High-Edge Hit Rate | 76.6% | 50.9% | **26 pts worse** |

### Code Version Comparison

Predictions made with fixed code (after Jan 30 19:10 UTC deployment):

| Code Version | Predictions | Graded | Hit Rate |
|--------------|-------------|--------|----------|
| Before fix (broken) | 2303 | 668 | 50.6% |
| After fix (fixed) | 559 | 41 | 58.5% |

The fixed code shows **~8 percentage point improvement**.

---

## Why Session 63 Hypothesis Was Wrong

Session 63 focused on:
1. Daily vs backfill code path differences for Vegas lines
2. Phase 3 vs raw table coverage

But the actual issue was:
1. **Deployment lag** - fix committed but not deployed for 12+ hours
2. **Feature population bug** - Vegas/opponent/PPM features not set correctly
3. **Nothing to do with Vegas line source** - the source is fine

---

## Fix Required

The fix (ea88e526) is already deployed (as of Jan 30 19:10 UTC).

**Action needed:** Re-run predictions for Jan 9-28 using current code.

### Verification Steps

1. Check deployed revision:
   ```bash
   gcloud run revisions describe prediction-worker-00053-h75 --region=us-west2
   ```

2. Re-run predictions for a test date (e.g., Jan 12):
   ```bash
   # Trigger prediction regeneration for Jan 12
   curl -X POST "https://prediction-coordinator.../trigger" \
     -d '{"date": "2026-01-12", "force_regenerate": true}'
   ```

3. Compare new predictions to old:
   - Should see different predicted_points values
   - Features should have correct Vegas/opponent/PPM values

4. Wait for games to grade and verify improved hit rate

---

## Prevention Recommendations

1. **Automated Deployment After Fix**: Set up CI/CD to auto-deploy critical fixes
2. **Pre-backfill Deployment Check**: Script to verify latest code is deployed before running backfills
3. **Feature Validation**: Add runtime checks for critical features (has_vegas_line, ppm values)

---

## Key Files Changed in Investigation

| File | Change |
|------|--------|
| ea88e526 | Fixed feature enrichment bug in prediction worker |
| 6c6ca504 | Fixed NaN handling for Vegas features |
| Session 64 docs | This investigation document |

---

## Next Session Checklist

- [ ] Re-run predictions for Jan 9-28 with fixed code
- [ ] Verify hit rates improve to ~60%+
- [ ] Update V8-FIX-EXECUTION-PLAN.md to reflect actual root cause
- [ ] Consider retraining V8 on data with correct features

---

## Verification Complete

Model test with correct features works:

```
Model loaded: True
Predicted points: 18.23
Confidence: 89.0
Recommendation: PASS
```

The current code correctly handles Vegas/opponent/PPM features from the feature store.

---

## Regenerate Predictions Command

To regenerate predictions for Jan 9-28 using fixed code:

```bash
# Dry run first
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-28 \
  --dry-run

# Actual backfill
PYTHONPATH=. python ml/backfill_v8_predictions.py \
  --start-date 2026-01-09 \
  --end-date 2026-01-28
```

Note: This will INSERT new predictions. Existing predictions will need to be
marked as superseded or deleted before regeneration to avoid duplicates.

---

*Created: 2026-02-01 Session 64*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
