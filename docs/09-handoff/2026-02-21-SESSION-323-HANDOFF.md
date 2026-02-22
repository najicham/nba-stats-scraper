# Session 323 Handoff: Model Health Gate + Retrain + Experiments

**Date:** 2026-02-21
**Focus:** Restore model health gate, retrain models, V13/V14 feature experiments
**Status:** PARTIALLY COMPLETE

## What Was Done

### Phase A: Model Health Gate — DEPLOYED

**Commit:** `a69900e8` — auto-deploying via Cloud Build.

Restored the model health gate in `signal_best_bets_exporter.py` (removed Session 270, restored Session 323). When champion V9 7-day rolling HR < 52.4% (breakeven at -110 odds), the exporter returns 0 picks with full metadata and `health_gate_active: true` flag.

**Session 322 replay study** proved blocking picks during decay outperforms all strategies:
- Health gate strategy: **29.9% ROI**
- Oracle strategy (best possible): **17.7% ROI**
- Current drawdown: best bets 5-8 (38.5%) over last 14 days

**Files changed:**
- `data_processors/publishing/signal_best_bets_exporter.py` — early return when blocked
- `ml/signals/aggregator.py` — ALGORITHM_VERSION bumped to `v323_health_gate`
- `tests/unit/publishing/test_signal_best_bets_exporter.py` — 4 new tests (16/16 passing)

**Current state:** V9 champion is HEALTHY at 80.0% HR 7d (N=5 during ASB). Gate won't trigger today.

### Phases B/C/D: Retrain & Experiments — ALL FAILED N GATE

All 6 models failed governance due to **ASB eval data scarcity**. Training window: Dec 25 - Feb 5. Eval window: Feb 6-12 (only 7 days of pre-ASB games).

| Model | MAE | HR 3+ | N (3+) | Vegas Bias | Dir Balance | Gates Passed |
|-------|-----|-------|--------|------------|-------------|-------------|
| V9 MAE | 4.82 | 25.0% | 4 | -0.15 | FAIL | 2/6 |
| V13 (60f) | 4.75 | 42.9% | 7 | -0.14 | FAIL | 2/6 |
| **V14 (65f)** | **4.68** | **65.0%** | 20 | -0.20 | **PASS** | **5/6** |
| **V12 Q43** | 4.86 | **65.3%** | 49 | -1.50 | FAIL | 3/6 |
| V9 Q43 | 4.91 | 55.6% | 36 | -1.51 | FAIL | 2/6 |
| V9 Q45 | 4.89 | 58.1% | 31 | -1.32 | FAIL | 2/6 |

### Phase E: Shadow Deployment

- **V12 No-Vegas Q43**: Shadow deployed, enabled, ready for automatic discovery
  - Model: `catboost_v9_50f_noveg_train20251225-20260205_20260221_211702`
  - GCS: `gs://nba-props-platform-models/catboost_v9_50f_noveg_train20251225-20260205_20260221_211702.cbm`
  - Family: `v12_noveg_q43`
- **V14**: Registered but DISABLED (status=experiment). No production feature extraction path exists.

## Key Findings

### V13/V14 Features Are Dead Weight
- V13 features (FG% rolling averages, indices 54-59): **0.00% importance** in all experiments
- V14 features (engineered FG% signals, indices 60-64): **0.00% importance**
- **Do NOT invest in feature store wiring** for V13/V14. The V12 base is sufficient.
- V14's superior results (best MAE, best directional balance) come from the V12 base, not the new features

### ASB Creates Governance Blind Spot
- 7-day eval window during ASB produces N=4-49 edge 3+ picks (vs N>=50 gate)
- Current champion was also manually promoted with N=10 < 50
- This is a structural limitation — consider relaxing N gate to N>=20 during ASB periods

### Quantile Models Generate More Volume
- Q43/Q45 produce 31-49 edge 3+ picks vs MAE's 4-7
- But heavily UNDER-skewed (57-68% UNDER picks)

## Next Steps

1. **Retrain after post-ASB games (Feb 28+):** Games resume Feb 22. After ~7 days of post-ASB data, retrain with `--train-end 2026-02-28 --eval-days 7`. Eval window (Mar 1-7) should have enough games for N>=50.

2. **Monitor V12 Q43 shadow:** Check `validate-daily` Phase 0.486 for shadow model gap detection. Compare against champion V9.

3. **Consider V14 feature store wiring?** Despite 0% importance now, the features might gain importance with more training data. LOW priority — only revisit if retraining experiments consistently show value.

4. **Health gate verification:** After today's deploy, verify gate works correctly when model enters decay. Check `v1/signal-best-bets/latest.json` for `health_gate_active` field during next drawdown.

## Model Health State (as of Feb 20)

| Model | State | HR 7d | Days Stale |
|-------|-------|-------|------------|
| catboost_v9 (champion) | HEALTHY | 80.0% | 15 |
| catboost_v9_low_vegas | HEALTHY | 61.5% | 15 |
| catboost_v12_noveg | WATCH | 57.1% | 15 |
| catboost_v12 | DEGRADING | 54.5% | 15 |
| catboost_v9_q45 | BLOCKED | 50.0% | 26 |
| catboost_v12_noveg_q43 | BLOCKED | 50.0% | 26 |
| catboost_v12_noveg_q45 | BLOCKED | 43.8% | 26 |
| catboost_v9_q43 | BLOCKED | 42.9% | 26 |
