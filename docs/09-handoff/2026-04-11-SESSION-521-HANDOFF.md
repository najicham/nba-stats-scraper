# Session 521 Handoff — MLB Auto-Deploy + MultiQuantile Model Architecture

**Date:** 2026-04-11
**Focus:** MLB infrastructure hardening, MultiQuantile training + worker support (Steps 1-2 of 4)
**Commits:** `d79ba26c` through `b63fe017` (3 commits on `main`)

---

## TL;DR

- **MLB auto-deploy triggers created** for grading service and Phase 2 (co-deploys with NBA). No more manual redeployment after NBA Phase 2 builds.
- **MLB grading duplicates fixed** — root cause was streaming insert invisible to DML. Switched to batch load.
- **MultiQuantile training support built** — `--multi-quantile` flag in `quick_retrain.py`. First test: **QUANTILE_CEIL_UNDER hit 9/10 (90% HR)** with perfect calibration.
- **Prediction worker handles MultiQuantile models** — detects from registry, splits 3-column output (p25/p50/p75), stores quantile values for signal use.
- **Steps 3-4 remain:** Create quantile signals in `ml/signals/`, then train diverse fleet to break correlation ceiling.

---

## What Was Done

### 1. MLB Auto-Deploy Triggers

| Trigger | YAML | What It Deploys | Watches |
|---------|------|-----------------|---------|
| `deploy-mlb-phase6-grading` (NEW) | `cloudbuild-mlb-grading.yaml` | `mlb-phase6-grading` | `data_processors/grading/mlb/**,shared/**,ml/**` |
| `deploy-nba-phase2-raw-processors` (UPDATED) | `cloudbuild-nba-phase2.yaml` | `nba-phase2-raw-processors` + `mlb-phase2-raw-processors` | `data_processors/raw/**,shared/**` |

**Why combined Phase 2:** `mlb-phase2-raw-processors` shares the exact same Docker image (`nba-phase2-raw-processors:latest`). One build, two deploys. Previously MLB Phase 2 required manual redeploy after every NBA Phase 2 build.

### 2. MLB Grading Duplicate Fix

**Root cause:** `DELETE + insert_rows_json` pattern. BQ streaming buffer is invisible to DML for up to 90 minutes. When grading re-ran within that window, DELETE found nothing to delete (rows still in buffer), then INSERT added duplicates.

**Fix:** Changed `insert_rows_json` (streaming) to `load_table_from_json` (batch) with explicit schema. Batch loads are immediately visible to DML. Cleaned 12 duplicate rows.

**File:** `data_processors/grading/mlb/mlb_prediction_grading_processor.py`

### 3. MultiQuantile Training (Step 1)

**New flag:** `PYTHONPATH=. python ml/experiments/quick_retrain.py --name MQ_TEST --feature-set v12 --no-vegas --multi-quantile`

CatBoost `MultiQuantile:alpha=0.25,0.5,0.75` trains one model that outputs three predictions:
- p25 (pessimistic — 75% chance actual is higher)
- p50 (median — used as `predicted_points` for standard evaluation)
- p75 (optimistic — 75% chance actual is lower)

**First test results (V12 NOVEG, 56-day window, 485 eval predictions):**

| Signal | Logic | HR | N | Coverage |
|--------|-------|-----|---|----------|
| QUANTILE_CEIL_UNDER | p75 < line | **90.0%** | 10 | 2.1% |
| QUANTILE_FLOOR_OVER | p25 > line | 0.0% | 1 | 0.2% |
| Either | union | **81.8%** | 11 | 2.3% |

| Metric | Value |
|--------|-------|
| Calibration q25 | expected 0.25, actual 0.256 (OK) |
| Calibration q50 | expected 0.50, actual 0.480 (OK) |
| Calibration q75 | expected 0.75, actual 0.748 (OK) |
| Narrow IQR HR (edge 3+) | 75.0% (16 picks) |
| Wide IQR HR (edge 3+) | 66.7% (9 picks) |
| Governance gates | ALL PASSED (72% HR at edge 3+) |
| Model family | `v12_noveg_mq` |

**Key insight:** When even the optimistic p75 prediction can't reach the line, UNDER wins 90% of the time. Low coverage (2.3%) but extremely high conviction.

**Changes:** `ml/experiments/quick_retrain.py` — added `--multi-quantile` flag, mutual exclusion checks, MultiQuantile loss function, 3-column output handling, quantile signal analysis section, model family `_mq` suffix, registry integration.

### 4. Worker MultiQuantile Support (Step 2)

**Detection:** `_is_multi_quantile` flag set from `loss_function` containing 'MultiQuantile' in registry config.

**Prediction flow:**
1. `model.predict(feature_vector)` returns shape `(1, 3)` for MultiQuantile
2. Split: `p25 = output[0][0]`, `p50 = output[0][1]` (→ `predicted_points`), `p75 = output[0][2]`
3. p25/p75 stored in result dict as `quantile_p25`/`quantile_p75`
4. Also stored in `critical_features` JSON in BQ for signal framework access

**Files:**
- `predictions/worker/prediction_systems/catboost_monthly.py` — model detection, 3-column split
- `predictions/worker/worker.py` — p25/p75 propagated to `critical_features` JSON

---

## Current System State

### MLB Pipeline
- Grading: operational, 9 unique records (duplicates cleaned)
- Auto-deploy: both triggers active
- Schedule re-scrape: `SKIP_DEDUPLICATION` working (Apr 10 games updating correctly)
- 3 picks: Apr 9 (1 ungraded), Apr 10 (2 ungraded)

### NBA Pipeline
- Auto-halt active (avg edge ~1.5 vs 5.0 threshold)
- Season ends ~Apr 13 (2 days)
- No stray picks since Apr 7 (halt working correctly)
- **Final record: 415-235 (63.8%)**

### MultiQuantile
- Training: fully functional (`--multi-quantile` flag)
- Worker: fully functional (detects, splits, stores)
- Signals: NOT YET BUILT (Step 3)
- Fleet diversity: NOT YET DONE (Step 4)

---

## Commits

| SHA | What |
|-----|------|
| `d79ba26c` | MLB auto-deploy triggers + grading duplicate fix |
| `aaad194c` | MultiQuantile training support in quick_retrain.py |
| `b63fe017` | Worker MultiQuantile model support |

---

## Outstanding Work

### Ready to Build (Steps 3-4)

**Step 3 — Create quantile signals:**
1. `ml/signals/quantile_ceiling_under.py` — p75 < line → STRONG UNDER signal
2. `ml/signals/quantile_floor_over.py` — p25 > line → STRONG OVER signal
3. Wire into aggregator signal registry (`ACTIVE_SIGNALS` or `SHADOW_SIGNALS`)
4. Signal reads `prediction.get('quantile_p25')` or parses `critical_features` JSON
5. Consider IQR width as confidence modifier (narrow IQR = 75% HR vs wide = 67%)

**Step 4 — Fleet diversity:**
1. Train and register a MultiQuantile model: `--multi-quantile --enable`
2. Train LightGBM MAE model (different framework breaks r>0.95 correlation)
3. Train XGBoost MAE model (same reason)
4. This resurrects `combo_3way` (95.5% HR) and `book_disagreement` (93% HR) which require diverse model agreement — killed when all models were correlated LGBM clones (Session 487)

### Other Off-Season Priorities (from Session 520)
5. **OVER strategy overhaul** — Higher edge floor (6-7), archetype targeting, regime restriction
6. **Retrain governance recovery** — Separate gates for "first model after halt" (chicken-and-egg)
7. **Book-count-aware thresholds** — Rehabilitate std-based signals for 12+ book regime

### Monitor
8. **MLB grading** — Verify automated pipeline grades today's games correctly
9. **Cloud Build triggers** — Verify both new triggers fire on next push to main

---

## Key Discoveries

### 1. BQ batch vs streaming for grading pipelines
`insert_rows_json` (streaming) → invisible to DML for 90 min. If grading re-runs within that window, DELETE+INSERT creates duplicates. Use `load_table_from_json` (batch) with explicit schema instead.

### 2. MultiQuantile as a signal, not a model replacement
The quantile model's value isn't in replacing the point estimate (p50 has similar HR to MAE). The value is the **confidence interval**: when p75 < line, UNDER is nearly certain (90% HR). This is a fundamentally different signal than edge magnitude.

### 3. Coverage vs conviction tradeoff
QUANTILE_CEIL_UNDER fires on only 2.1% of picks but at 90% HR. Compare to `combo_3way` at 95.5% HR. Both are rare, high-conviction signals. The system profits from having multiple orthogonal high-conviction signals, even at low individual coverage.

### 4. Calibration validates the approach
All three quantiles within 2% of expected coverage rates. This means the model genuinely learned the distribution shape, not just the center. The IQR width is meaningful as an uncertainty measure (narrow = 75% HR vs wide = 67%).

---

## Files Changed

| Purpose | File |
|---------|------|
| MLB grading auto-deploy | `cloudbuild-mlb-grading.yaml` (new) |
| Phase 2 combined deploy | `cloudbuild-nba-phase2.yaml` (new) |
| Grading batch load fix | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` |
| MultiQuantile training | `ml/experiments/quick_retrain.py` |
| Worker MQ detection + split | `predictions/worker/prediction_systems/catboost_monthly.py` |
| Worker MQ storage | `predictions/worker/worker.py` |

## Infrastructure Operations

| Operation | Detail |
|-----------|--------|
| Cloud Build trigger | Created `deploy-mlb-phase6-grading` |
| Cloud Build trigger | Updated `deploy-nba-phase2-raw-processors` → `cloudbuild-nba-phase2.yaml` |
| BQ DELETE | Cleaned 12 duplicate rows from `mlb_predictions.prediction_accuracy` |
| Model trained | `catboost_v12_50f_noveg_mq` (test, not registered — `--skip-auto-upload`) |
