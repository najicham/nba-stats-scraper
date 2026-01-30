# CatBoost V8 Performance Analysis Project

**Status:** ⚠️ MODEL DRIFT DETECTED - RETRAINING NEEDED
**Started:** 2026-01-29 (Session 23)
**Updated:** 2026-01-30 (Session 27)
**Next Phase:** Retraining Experiments (Urgent)

## Key Discovery (Session 27)

**MODEL DRIFT DETECTED!** CatBoost V8 shows significant performance degradation on the 2025-26 season:

| Season | Hit Rate | MAE | Status |
|--------|----------|-----|--------|
| 2022-24 | 75.1% | 4.08 | ✅ Good |
| 2024-25 | 74.3% | 4.18 | ✅ Good |
| **2025-26** | **61.3%** | **6.34** | ⚠️ **DEGRADED** |

The model was trained on 2021-2024 data and is now 1.5+ years out of sample. **Retraining with recent data is urgently needed.**

## Documents

| Document | Purpose |
|----------|---------|
| [CATBOOST-V8-PERFORMANCE-ANALYSIS.md](./CATBOOST-V8-PERFORMANCE-ANALYSIS.md) | Main analysis with Session 24 updates |
| [SESSION-24-INVESTIGATION-FINDINGS.md](./SESSION-24-INVESTIGATION-FINDINGS.md) | Full investigation findings |
| [WALK-FORWARD-EXPERIMENT-PLAN.md](./WALK-FORWARD-EXPERIMENT-PLAN.md) | Experiment framework and results |
| [EXPERIMENT-INFRASTRUCTURE.md](./EXPERIMENT-INFRASTRUCTURE.md) | How to run experiments (scripts, commands) |
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

### Completed (Session 25)
- [x] Identify root cause of 52% hit rate
- [x] Verify model works (74.25% on 2024-25)
- [x] Fix feature passing bug in worker.py
- [x] Document findings
- [x] Deploy fix to production (revision 00033)
- [x] Verify predictions improved (avg_edge -0.21 vs 4-6 before)
- [x] Standardize confidence to percentage scale (0-100)
- [x] Prevention Task #8: Fallback severity classification
- [x] Prevention Task #9: Prometheus metrics (3 metrics + /metrics endpoint)
- [x] Prevention Task #10: Feature parity tests (32 tests)
- [x] Configure Cloud Monitoring alert for CRITICAL fallbacks
- [x] Deploy grading views to BigQuery (5 views consolidated)

### Walk-Forward Experiments (Sessions 26-27)
See `WALK-FORWARD-EXPERIMENT-PLAN.md` and `EXPERIMENT-INFRASTRUCTURE.md` for details:
- [x] Create experiment infrastructure (train, evaluate, compare scripts)
- [x] Run Experiments A1-A3 (training window size) - 72-74% hit rate
- [x] Run Experiments B1-B3_fixed (recency vs volume) - 69-71% on clean data
- [x] Discover model drift on 2025-26 season (61% vs 74%)
- [ ] **URGENT: Retraining experiments (see below)**

### URGENT: Retraining Experiments Needed

The model has degraded on 2025-26. Run these experiments:

```bash
# Experiment 1: Train on 2024-25 only
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id RECENT_2024_25 \
    --train-start 2024-10-01 --train-end 2025-06-30 \
    --eval-start 2025-10-01 --eval-end 2026-01-28

# Experiment 2: Train on first 3 months of 2025-26
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id INSEASON_2025_26 \
    --train-start 2025-10-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-28

# Experiment 3: Combined recent data
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id COMBINED_RECENT \
    --train-start 2024-10-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-28

# Experiment 4: All data including 2024-25
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id ALL_DATA \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-28

# Compare all
PYTHONPATH=. python ml/experiments/compare_results.py
```

### Future Improvements
- [ ] Expand ml_feature_store_v2 to 33 features
- [ ] Add `prediction_quality` column for degraded predictions
- [ ] Standardize other systems' confidence to percentage

## Experiment Results

### Session 27: Walk-Forward Validation (Clean Data)

After fixing the feature store L5/L10 bug, experiments were re-run on clean data:

| Exp | Training | Eval | Hit Rate | ROI | MAE | Data Status |
|-----|----------|------|----------|-----|-----|-------------|
| A1 | 2021-22 | 2022-23 | **72.1%** | +37.5% | 3.89 | ✅ Clean |
| A2 | 2021-23 | 2023-24 | **73.9%** | +41.1% | 3.66 | ✅ Clean |
| A3_fixed | 2021-24 | 2024-25 | **70.8%** | +35.0% | 3.91 | ✅ Clean |
| B1_fixed | 2021-23 | 2024-25 | **70.6%** | +34.7% | 3.93 | ✅ Clean |
| B2_fixed | 2023-24 | 2024-25 | **69.5%** | +32.7% | 3.99 | ✅ Clean |
| B3_fixed | 2022-24 | 2024-25 | **70.7%** | +34.9% | 3.92 | ✅ Clean |

**Key Finding:** Model achieves ~70% on clean 2024-25 data, but only 61% on 2025-26 (model drift).

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
| High edge (5+ pts) | 87.6% |
| Medium edge (3-5 pts) | 78.9% |
| UNDER bets | 77.8% |
| High-confidence (95%+) | 79.64% |

## Related Files

| File | Purpose |
|------|---------|
| `predictions/worker/worker.py` | Feature passing fix location |
| `predictions/worker/prediction_systems/catboost_v8.py` | Model inference code |
| `ml/train_final_ensemble_v8.py` | Original training script |
| `ml/experiments/run_experiment.py` | Walk-forward experiment runner |
| `ml/experiments/compare_results.py` | Experiment comparison tool |
| `ml/experiments/results/` | Experiment models and JSON results |
| `ml/model_contract.py` | Contract validation (needs activation) |
| `docs/09-handoff/2026-01-29-SESSION-20-CATBOOST-V8-FIX-AND-SAFEGUARDS.md` | Original fix documentation |

---

*Created: 2026-01-29 Session 23*
*Updated: 2026-01-29 Session 24*
*Updated: 2026-01-29 Session 26 - Added experiment infrastructure*
