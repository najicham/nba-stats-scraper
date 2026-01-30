# CatBoost V8 Performance Analysis Project

**Status:** ROOT CAUSE IDENTIFIED - FIX APPLIED
**Started:** 2026-01-29 (Session 23)
**Updated:** 2026-01-29 (Session 24)

## Key Discovery (Session 24)

**THE MODEL WORKS!** CatBoost V8 achieved **74.25% hit rate** on the 2024-25 season (true out-of-sample data). The poor 52% performance in January 2026 was caused by a **feature passing bug**, not model failure.

| Period | Hit Rate | Status |
|--------|----------|--------|
| 2024-25 Season | **74.25%** | Model working correctly |
| Jan 2026 | 52% | Feature passing bug active |

## Documents

| Document | Purpose |
|----------|---------|
| [CATBOOST-V8-PERFORMANCE-ANALYSIS.md](./CATBOOST-V8-PERFORMANCE-ANALYSIS.md) | Main analysis with Session 24 updates |
| [SESSION-24-INVESTIGATION-FINDINGS.md](./SESSION-24-INVESTIGATION-FINDINGS.md) | Full investigation findings |
| [WALK-FORWARD-EXPERIMENT-PLAN.md](./WALK-FORWARD-EXPERIMENT-PLAN.md) | Experiment framework for training optimization |
| [PREVENTION-PLAN.md](./PREVENTION-PLAN.md) | How to prevent this bug class in the future |
| [experiments/D1-results.json](./experiments/D1-results.json) | 2024-25 season performance data |

## Root Causes Identified

### 1. Feature Passing Bug (FIXED)

**Location:** `predictions/worker/worker.py`

The worker wasn't populating Vegas/opponent/PPM features in the features dict:

| Feature | Before Fix | After Fix |
|---------|-----------|-----------|
| `vegas_points_line` | None | Prop line value |
| `has_vegas_line` | 0.0 (wrong!) | 1.0 |
| `ppm_avg_last_10` | 0.4 | Calculated (~0.9) |

**Impact:** Predictions inflated by +29 points (64.48 vs 34.96 expected)

**Fix:** Added v3.7 feature enrichment block (lines 815-870)

### 2. Training/Inference Gap

- Model trained on 33 features from 4 tables
- Inference only had 25 features from 1 table
- 8 features used silent defaults

### 3. Silent Fallbacks

- Missing features defaulted to values without alerts
- No monitoring detected the issue

## Prevention Strategy

See [PREVENTION-PLAN.md](./PREVENTION-PLAN.md) for full details:

1. **Layer 1:** Expand feature store to include all 33 features
2. **Layer 2:** Activate model contract validation
3. **Layer 3:** Classify fallback severity (NONE/MINOR/MAJOR/CRITICAL)
4. **Layer 4:** Add monitoring metrics and alerts
5. **Layer 5:** Add feature parity tests
6. **Layer 6:** Add daily validation checks

## Action Items

### Completed
- [x] Identify root cause of 52% hit rate
- [x] Verify model works (74.25% on 2024-25)
- [x] Fix feature passing bug in worker.py
- [x] Document findings

### In Progress
- [ ] Deploy fix to production
- [ ] Monitor predictions for improvement

### Next Steps
- [ ] Add `prediction_quality` column for degraded predictions
- [ ] Add Prometheus metrics for feature fallbacks
- [ ] Configure Cloud Monitoring alerts
- [ ] Add feature parity tests
- [ ] Expand feature store to 33 features

## Experiment Results

### D1: Existing V8 on 2024-25 Season

| Metric | Value |
|--------|-------|
| Predictions | 13,315 |
| Hit Rate | **74.25%** |
| ROI | **+41.75%** |
| Decay | None (72-79% for 13 months) |

### Best Performing Segments

| Segment | Hit Rate |
|---------|----------|
| High-confidence (95%+) | 79.64% |
| High-conf UNDER | 78.09% |
| All UNDER | 76.54% |

## Related Files

| File | Purpose |
|------|---------|
| `predictions/worker/worker.py` | Feature passing fix location |
| `predictions/worker/prediction_systems/catboost_v8.py` | Model inference code |
| `ml/train_final_ensemble_v8.py` | Training script |
| `ml/model_contract.py` | Contract validation (needs activation) |
| `docs/09-handoff/2026-01-29-SESSION-20-CATBOOST-V8-FIX-AND-SAFEGUARDS.md` | Original fix documentation |

---

*Created: 2026-01-29 Session 23*
*Updated: 2026-01-29 Session 24*
