# Session 252 Handoff — V12 Production Experiments Complete, Cross-Season Validation Needed

**Date:** 2026-02-14
**Status:** Production experiments done. All 4 failed governance gates. Multi-season training hurts. Need cross-season validation to confirm findings.
**Sessions:** 252 (validation + production experiments)

---

## What Was Done This Session

### 1. Validated Session 251 Work
All checks passed:
- **Deployment drift**: 4 pre-existing stale services (reconcile, nba-grading-service, validate-freshness, validation-runner) — not from Session 251
- **Data quality**: 2024-25 ml_feature_store_v2 shows 74.6% clean, avg score 87.8 — exact match
- **OPTIONAL_FEATURES**: Feature 37 confirmed in set `{25, 26, 27, 37, ...}`
- **Gap analysis**: No unexpected gaps in training data. October bootstrapping gaps and low-quality early-season months are expected.

### 2. Ran 4 V12 Production Experiments

All evaluated on **Feb 6-13, 2026** (8-day eval window, fresh data unseen during training).

| # | Name | Features | Train Range | Loss | MAE (lines) | MAE (all) | HR 3+ | HR 5+ | N 3+ | Gates |
|---|------|----------|-------------|------|-------------|-----------|-------|-------|------|-------|
| 1 | V12_MULTISZN_HUBER | V12 50f | 2022-11 to 2026-02 | Huber:5 | 5.343 | 4.700 | **36.4%** | 41.7% | 88 | FAIL |
| 2 | V12_MULTISZN_MAE | V12 50f | 2022-11 to 2026-02 | MAE | 5.180 | 4.690 | **36.6%** | 26.3% | 71 | FAIL |
| 3 | V12_CURSZN_HUBER | V12 50f | 2025-11 to 2026-02 | Huber:5 | **4.948** | 4.725 | **53.6%** | 56.5% | 69 | FAIL |
| 4 | V9_MULTISZN | V9 33f | 2022-11 to 2026-02 | MAE | 5.260 | 4.668 | **46.3%** | 58.3% | 80 | FAIL |
| — | *V9 Baseline (stale)* | *V9 33f* | *Nov-Jan* | *MAE* | *5.140* | — | *63.7%* | *75.3%* | — | — |

**Model files saved:**
- `models/catboost_v9_50f_noveg_train20221101-20260205_20260214_123808.cbm` (Exp 1 — V12 multi Huber)
- `models/catboost_v9_50f_noveg_train20221101-20260205_20260214_123802.cbm` (Exp 2 — V12 multi MAE)
- `models/catboost_v9_50f_noveg_train20251102-20260205_20260214_123554.cbm` (Exp 3 — V12 cur Huber)
- `models/catboost_v9_33f_train20221101-20260205_20260214_124036.cbm` (Exp 4 — V9 multi)

**Registered in ml_experiments**: IDs `2fb4b6e6`, `f04d1332`, `2a4999be`, `8e562f17`

### 3. Key Findings

1. **Multi-season training HURTS fresh-eval performance.** V12 current-season (53.6% HR 3+) beats V12 multi-season (36.4%) by +17pp. V9 multi-season (46.3%) is worse than the stale V9 baseline (63.7%).

2. **V12 does NOT beat V9 when both use multi-season data.** V9 multi-season (46.3%) > V12 multi-season (36.4%). Extra features dilute signal with heterogeneous historical data.

3. **V12 current-season is best of the four** but still can't pass governance gates. 53.6% HR 3+ is barely above breakeven (52.4%). Heavy UNDER skew: 91% of edge 3+ picks are UNDER.

4. **All models fail directional balance gate.** OVER hit rate is below breakeven across all 4 experiments. This is a systematic issue, not model-specific.

5. **Multi-season backtests (Sessions 247-251) showed 85-91% HR but that was within-season eval.** When training on historical data and evaluating on a **different season** (Feb 2026), performance drops dramatically. Player patterns don't transfer well across seasons.

---

## What Needs To Happen Next: Cross-Season Validation

### Goal
Determine if these findings are consistent across seasons. The user wants to see if the same model configurations perform similarly when trained/tested in analogous time periods of **last season** (2024-25).

### Rationale
- If V12 current-season Huber beats V12 multi-season on 2024-25 data too, we can confidently say multi-season training doesn't help
- If models perform well pre-All-Star but decay post-All-Star, we can predict the retrain cadence
- This gives us a basis for deciding: retrain monthly? bi-weekly? At what point does a model go stale?

### Experiment Design

**Mirror the Session 252 experiments but for the 2024-25 season.**

The 2024-25 All-Star break was Feb 14-18, 2025. Test on the week BEFORE the break (like we tested on Feb 6-13, 2026 this season).

#### Experiment A: V12 Current-Season Huber (2024-25 analog)
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_CURSZN_HUBER_2425" \
    --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
    --loss-function "Huber:delta=5" \
    --train-start 2024-11-01 --train-end 2025-02-05 \
    --eval-start 2025-02-06 --eval-end 2025-02-13 \
    --walkforward --include-no-line --force
```

#### Experiment B: V12 Multi-Season Huber (2024-25 analog)
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_MULTISZN_HUBER_2425" \
    --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
    --loss-function "Huber:delta=5" \
    --train-start 2022-11-01 --train-end 2025-02-05 \
    --eval-start 2025-02-06 --eval-end 2025-02-13 \
    --walkforward --include-no-line --force
```

#### Experiment C: V9 Current-Season (2024-25 analog)
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_CURSZN_2425" \
    --train-start 2024-11-01 --train-end 2025-02-05 \
    --eval-start 2025-02-06 --eval-end 2025-02-13 \
    --walkforward --force
```

#### Experiment D: V9 Multi-Season (2024-25 analog)
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MULTISZN_2425" \
    --train-start 2022-11-01 --train-end 2025-02-05 \
    --eval-start 2025-02-06 --eval-end 2025-02-13 \
    --walkforward --force
```

**Run A+B+C in parallel (different configs). D can run after.**

### After Cross-Season Experiments: Staleness Analysis

If results are consistent, run a **staleness decay curve**:

#### Experiment E: Staleness test (train through Dec, eval Feb)
```bash
# How much does 2 months of staleness hurt?
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_STALE_2MO" \
    --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
    --loss-function "Huber:delta=5" \
    --train-start 2024-11-01 --train-end 2024-12-31 \
    --eval-start 2025-02-06 --eval-end 2025-02-13 \
    --walkforward --include-no-line --force
```

#### Experiment F: Staleness test (train through Jan, eval Feb)
```bash
# How much does 1 month of staleness hurt?
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_STALE_1MO" \
    --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
    --loss-function "Huber:delta=5" \
    --train-start 2024-11-01 --train-end 2025-01-31 \
    --walkforward --include-no-line --force
```
(No --eval-start/--eval-end means it uses the defaults based on training end date)

### Analysis Framework

After all experiments, build a comparison matrix:

```
                    2024-25 Season          2025-26 Season
                    HR 3+   MAE   N 3+     HR 3+   MAE   N 3+
V12 Cur-Szn Huber   ???    ???    ???      53.6%  4.948   69
V12 Multi-Szn Huber ???    ???    ???      36.4%  5.343   88
V9 Cur-Szn          ???    ???    ???       (not run this season)
V9 Multi-Szn        ???    ???    ???      46.3%  5.260   80
```

**Key questions to answer:**
1. Does current-season consistently beat multi-season? (If yes: abandon multi-season)
2. Does V12 consistently beat V9 within the same training paradigm? (If yes: adopt V12)
3. How fast does performance decay with staleness? (Informs retrain cadence)
4. Can we project post-All-Star performance from pre-All-Star results?

### Bonus: V12 + Quantile (if time permits)

Session 186 found quantile alpha=0.43 reduces staleness sensitivity. Try it with V12:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_Q43_CURSZN" \
    --feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise \
    --quantile-alpha 0.43 \
    --train-start 2025-11-02 --train-end 2026-02-05 \
    --eval-start 2026-02-06 --eval-end 2026-02-13 \
    --walkforward --include-no-line --force
```

This addresses the UNDER skew problem found in all 4 Session 252 experiments.

---

## Data Quality Notes

### Training Data Coverage (from gap analysis)

| Period | Records | Quality-Ready % | Notes |
|--------|---------|-----------------|-------|
| 2022-23 | 20,967 | 94-100% | Excellent |
| 2023-24 | 18,287 | 94-100% | Excellent |
| 2024-11 | 3,988 | 36.6% | Early season bootstrapping |
| 2024-12 to 2025-01 | 8,947 | 89-91% | Good |
| 2025-02 to 2025-06 | 12,911 | 1-17% | Not backfilled beyond Feb 13 |
| 2025-11 to 2026-02 | 25,823 | 26-71% | Current season, improving monthly |

- October months have 0 data (season start bootstrapping) — expected
- `quick_retrain.py` filters by `is_quality_ready`, so low-quality months contribute fewer samples
- NO_PROP_LINE players are included via `--include-no-line` flag

### Deployment Drift (Pre-existing)
4 services stale (from before Session 251):
- `reconcile`, `nba-grading-service`, `validate-freshness`, `validation-runner`
- Not critical for experiment work but should be addressed

---

## Files Changed This Session

None — this was a read-only validation + experiment session. No code changes.

## Background Processes

**ALL STOPPED.** No background processes running.
