# Session 355 Handoff — Experiment Roadmap Execution

**Date:** 2026-02-27
**Previous:** Session 354 — Star UNDER fix, experiment roadmap

## What Session 355 Did

### 1. Prop Line Anchor Training (Priority 1) — IMPLEMENTED + TESTED

Added `--anchor-line` flag to `quick_retrain.py`. When active:
- Training target changes from `actual_points` to `actual_points - prop_line`
- At eval time: `predicted_points = prop_line + model.predict(X)`
- Auto-sets quantile alpha = 0.50 (predict median deviation)
- Prop line (`feature_25_value`) is ONLY the target anchor, never a feature
- Model filename includes `_anchor` suffix

**Key result:** Feature importance completely reshaped — no single dominant feature! `deviation_from_avg_last3` (7.8%), `ppm_avg_last_10` (4.7%), `pts_vs_season_zscore` (3.9%). Compare to normal V12 where `points_avg_season` alone = 18%+.

**HR edge 3+: 70.0% (N=10)** — promising but tiny sample. OVER: 100%, UNDER: 57.1%.

**CRITICAL BLOCKER:** The anchor-line model cannot be deployed as shadow without worker changes. The worker expects the model to predict raw points, but this model predicts deviations. Need to add anchor-line support to the prediction worker (`predictions/worker/`) to reverse the transform: `predicted_points = prop_line + model_output`. Model is **disabled** in registry until worker support is added.

### 2. Differenced Features (Priority 2) — IMPLEMENTED + TESTED

Added `--diff-features` flag to `quick_retrain.py`. Adds 3 computed features:
- `season_avg_vs_line = points_avg_season - prop_line`
- `last5_avg_vs_line = points_avg_last_5 - prop_line`
- `last10_avg_vs_line = points_avg_last_10 - prop_line`

These are computed post-extraction from existing feature columns. NaN where no prop line exists.

**Feature importance:** `last5_avg_vs_line` got 5.16% (#4), `last10_avg_vs_line` got 4.13% (#6). Meaningful signal.

**HR edge 3+: 57.14% (N=14)** — below breakeven. UNDER still 42.9%. Diff features alone don't fix UNDER bias. Model **disabled** in registry.

### 3. New Negative Filters (Priority 3) — DEPLOYED

Added three new filters to `ml/signals/aggregator.py`:

| Filter | HR | N | What |
|--------|-----|---|------|
| Med teammate usage UNDER | 32.0% | 25 | Blocks UNDER when teammate_usage 15-30 |
| Starter V12 UNDER | 46.7% | 30 | Blocks V12 UNDER when season_avg 15-20 |
| Premium signal edge floor bypass | 95%+ | — | combo_3way, combo_he_ms bypass edge floor |

- `teammate_usage_available` piped through `supplemental_data.py` → pred dict (from `feature_47_value` in feature store)
- Premium signal bypass: edge floor check now looks for `combo_3way`/`combo_he_ms` signals before rejecting low-edge picks
- Algorithm version bumped to `v355_usage_starter_filters_premium_bypass`
- 11 new tests added, all 48 tests pass

### 4. Model Training Results Summary

| Model | HR 3+ | N | OVER% | Deviation Std | Feature Diversity | Status |
|-------|-------|---|-------|---------------|-------------------|--------|
| Anchor-line (base) | 70% | 10 | 24% pred | 0.98 | Excellent | **Disabled** (needs worker) |
| Diff-features only | 57% | 14 | — | — | Moderate | Disabled |
| Anchor + diff | 40% | 5 | 0% pred | 0.06 | Collapsed | Disabled |
| Anchor + catwt | 50% | 4 | 1% pred | 0.19 | Good | Disabled |

**Key insight:** Anchor-line model with diff-features collapses — deviation std drops to 0.06 (near-constant prediction). The diff features in deviation space are too correlated. Use anchor-line WITHOUT diff features.

---

## What to Do Next

### HIGHEST PRIORITY: Worker Anchor-Line Support

The anchor-line approach shows the most promise (complete feature importance restructuring), but needs worker-side changes before it can run in production:

1. In the prediction worker's model loading/prediction code, detect anchor-line models (metadata or naming convention)
2. At prediction time: `predicted_points = prop_line + model.predict(features)` instead of just `model.predict(features)`
3. The prop line is available in the feature store as `feature_25_value`
4. Re-enable the anchor-line model after worker support is deployed

**Files to modify:** `predictions/worker/` — wherever `model.predict()` is called for regression models.

### Re-train Anchor-Line with More Data

The 39-day window (Jan 15 - Feb 22) only yielded 3,136 training samples with valid prop lines (out of 4,178 total). Consider:
- Extending training window to 60+ days
- Using all available data from Nov 2025

### Continue Roadmap Priorities 4-5

From Session 354 handoff:
- **Priority 4: Conformal Prediction Intervals** — Train Q20/Q80 bracket models for directional gating
- **Priority 5: V16 Features** — `over_rate_last_10`, `margin_vs_line_avg_last_5`

### Volume Increases (Priority 6)

The premium signal bypass (combo_3way, combo_he_ms exempt from edge floor) should increase pick volume slightly for 95%+ HR signals. Monitor impact.

---

## Models Registered This Session

| Model ID | Family | GCS Path | Status |
|----------|--------|----------|--------|
| `catboost_v12_noveg_q5_train0115_0222` | v12_noveg_q5 | `catboost_v12_50f_noveg_anchor_...cbm` | **Disabled** (needs worker) |
| `catboost_v12_noveg_train0115_0222` | v12_noveg_mae | `catboost_v12_53f_noveg_diff_...cbm` | Disabled |

Two additional q5 entries (anchor+diff, anchor+catwt) also disabled.

## Key Files Changed

| File | Changes |
|------|---------|
| `ml/experiments/quick_retrain.py` | `--anchor-line`, `--diff-features` flags |
| `ml/signals/aggregator.py` | 3 new filters, premium signal bypass, algorithm version bump |
| `ml/signals/supplemental_data.py` | `teammate_usage_available` piped through |
| `tests/unit/signals/test_aggregator.py` | 11 new tests for new filters |

## Dead Ends Confirmed

- **Anchor-line + diff-features combined**: Collapses to near-constant deviation (std=0.06). The diff features in deviation space are redundant.
- **Anchor-line + category weights**: Similar collapse (std=0.19). Category weights don't help in deviation space.
- **Diff-features only (MAE)**: 57% HR, doesn't fix UNDER bias.
