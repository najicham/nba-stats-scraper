# Session 355 Handoff — Experiment Roadmap Execution (All 5 Priorities)

**Date:** 2026-02-27
**Previous:** Session 354 — Star UNDER fix, experiment roadmap

## What Session 355 Did

### 1. Prop Line Anchor Training (Priority 1) — IMPLEMENTED + DEPLOYED

Added `--anchor-line` flag to `quick_retrain.py`. When active:
- Training target changes from `actual_points` to `actual_points - prop_line`
- At eval time: `predicted_points = prop_line + model.predict(X)`
- Auto-sets quantile alpha = 0.50 (predict median deviation)
- Prop line (`feature_25_value`) is ONLY the target anchor, never a feature
- Model filename includes `_anchor` suffix

**Worker support added:** `catboost_monthly.py` auto-detects anchor-line models from GCS path (`_anchor_`) and applies reverse transform at prediction time. If no prop line available for a player, returns `ANCHOR_LINE_NO_PROP_LINE` error.

**Results (39-day window, Jan 15 - Feb 22):**
- Feature importance completely reshaped — no single dominant feature!
- `deviation_from_avg_last3` (7.8%), `ppm_avg_last_10` (4.7%), `pts_vs_season_zscore` (3.9%)
- HR edge 3+: 70.0% (N=10), OVER: 100%, UNDER: 57.1%
- **Enabled as shadow:** `catboost_v12_noveg_q5_train0115_0222`

**60-day window variant COLLAPSED:** std=0.03, 0% OVER rate. Longer training window = model converges to population median. Disabled.

### 2. Differenced Features (Priority 2) — IMPLEMENTED

Added `--diff-features` flag: `season_avg_vs_line`, `last5_avg_vs_line`, `last10_avg_vs_line`.
- `last5_avg_vs_line` got 5.16% importance (#4)
- HR edge 3+: 57.14% (N=14) — below breakeven. Doesn't fix UNDER bias alone.
- **Disabled** in registry.

### 3. New Negative Filters (Priority 3) — DEPLOYED + LIVE

Three new filters in `aggregator.py` (algorithm version `v355`):

| Filter | HR | N | What |
|--------|-----|---|------|
| Med teammate usage UNDER | 32.0% | 25 | Blocks UNDER when teammate_usage 15-30 |
| Starter V12 UNDER | 46.7% | 30 | Blocks V12 UNDER when season_avg 15-20 |
| Premium signal bypass | 95%+ | — | combo_3way, combo_he_ms bypass edge floor |

- `teammate_usage_available` piped through `supplemental_data.py`
- 11 new tests, all 48 pass

### 4. Conformal Prediction Intervals (Priority 4) — TRAINED

Q20 and Q80 bracket models trained:
- Q20: pure UNDER predictor (57.1% UNDER, N=70, 0 OVER)
- Q80: pure OVER predictor (52.8% OVER, N=72, 0 UNDER)

**Not deployed** — these are confidence gates, not standalone models. The conformal filter (`only UNDER when Q80 < line`, `only OVER when Q20 > line`) needs architecture work in the aggregator to run bracket models per player alongside the main model.

### 5. V16 Features (Priority 5) — IMPLEMENTED, BEST RESULTS

Added `--v16-features` flag: `over_rate_last_10`, `margin_vs_line_avg_last_5`.
Computed as per-player rolling stats from training data.

**HR edge 3+: 75.0% (N=20)** — best of ALL experiments!
- OVER: 88.9% (N=9), UNDER: 63.6% (N=11)
- Both directions above breakeven
- Vegas bias: +0.29

**NOT deployable yet** — model has 52 features but worker provides 50. V16 features need to be added to the feature store pipeline (`data_processors/precompute/ml_feature_store/`) before deployment.

### 6. Worker Anchor-Line Support — DEPLOYED

Added to `predictions/worker/prediction_systems/catboost_monthly.py`:
- `_is_anchor_line` detection from GCS path
- Reverse transform in `_predict_v12()`: `predicted_points = prop_line + raw_prediction`
- Graceful handling when no prop line available

---

## Experiment Results Summary

| Model | HR 3+ | N | OVER | UNDER | Status |
|-------|-------|---|------|-------|--------|
| **V16 features** | **75.0%** | 20 | 88.9% | 63.6% | Disabled (needs feature store) |
| Anchor-line (39d) | 70.0% | 10 | 100% | 57.1% | **Shadow** |
| Anchor-MAE | 70.0% | 10 | 100% | 57.1% | Disabled (identical) |
| Diff-features | 57.1% | 14 | 71.4% | 42.9% | Disabled |
| Anchor+diff | 40.0% | 5 | 0% | 0% | Disabled |
| Anchor+catwt | 50.0% | 4 | 1% | 0% | Disabled |
| Anchor 60d | 40.0% | 5 | 0% | 0% | Disabled |

---

## What to Do Next (Priority Order)

### 1. Deploy V16 Features to Feature Store (HIGHEST IMPACT)

The V16 model is the clear winner (75% HR, balanced directions). To deploy it:
1. Add `over_rate_last_10` and `margin_vs_line_avg_last_5` to `data_processors/precompute/ml_feature_store/feature_calculator.py`
2. These require joining `player_game_summary` actual points against `prediction_accuracy` prop lines (rolling window per player)
3. Add to `shared/ml/feature_contract.py` as features 55-56
4. Re-enable the V16 model in registry after feature store support

### 2. Monitor Anchor-Line Model in Shadow

The anchor-line model is enabled as shadow. Watch for:
- Does it produce valid predictions? (prop line availability)
- Feature importance pattern: confirms deviation_from_avg is the real signal
- Compare HR against other models after 2+ days of grading

### 3. Conformal Prediction Integration

The Q20/Q80 bracket models are local files. To use them as confidence gates:
- Architecture option A: Run bracket models in the worker alongside main model, store Q20/Q80 predictions
- Architecture option B: Post-processing in the aggregator using pre-computed bracket predictions
- Filter: only UNDER when Q80 < line, only OVER when Q20 > line

---

## Models Currently Enabled (Shadow)

| Model ID | Family | What |
|----------|--------|------|
| `catboost_v12_noveg_q55_train0115_0222` | v12_noveg_q55 | Session 354 Q55 TW retrain |
| `catboost_v12_noveg_q5_train0115_0222` | v12_noveg_q5 | **Anchor-line model** (Session 355) |

Plus all existing production/shadow models from prior sessions.

## Dead Ends Confirmed This Session

- **Anchor-line + 60-day window**: Collapses to constant (std=0.03). Quantile 0.50 + more data = population median
- **Anchor-line + diff-features**: Collapses to constant (std=0.06). Diff features redundant in deviation space
- **Anchor-line + category weights**: Similar collapse (std=0.19)
- **Diff-features only**: Doesn't fix UNDER bias (42.9% UNDER HR)

## Key Files Changed

| File | Changes |
|------|---------|
| `ml/experiments/quick_retrain.py` | `--anchor-line`, `--diff-features`, `--v16-features` flags |
| `ml/signals/aggregator.py` | 3 new filters, premium signal bypass |
| `ml/signals/supplemental_data.py` | `teammate_usage_available` piped through |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Anchor-line reverse transform |
| `tests/unit/signals/test_aggregator.py` | 11 new tests |
