# Session 356 Handoff — V16 Features Deployed to Feature Store

**Date:** 2026-02-27
**Previous:** Session 355 — Experiment roadmap execution (all 5 priorities)

## What Session 356 Did

### V16 Features Deployed to Production Feature Store

Added two new features that encode a player's recent history vs their prop line:

1. **`over_rate_last_10`** (feature 55): Fraction of last 10 games where `actual_points > prop_line`. Range 0.0-1.0.
2. **`margin_vs_line_avg_last_5`** (feature 56): Average of `(actual_points - prop_line)` over last 5 games.

These are the features from the V16 experiment (Session 355) which achieved **75% HR edge 3+ (OVER 88.9%, UNDER 63.6%)** — the best experiment result.

### Changes Made

| File | Changes |
|------|---------|
| `shared/ml/feature_contract.py` | V16/V16_NOVEG contracts (56/52 features), feature store updated to v2_57features, defaults, source maps |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | `_batch_extract_v16_line_history()` — rolling window query from prediction_accuracy + player_game_summary |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | FEATURE_VERSION=v2_57features, FEATURE_COUNT=57, validation ranges, computation in _extract_all_features |
| `predictions/worker/prediction_systems/catboost_monthly.py` | v16_noveg feature set support (52 features), imports V16_NOVEG_FEATURE_NAMES |
| `ml/experiments/quick_retrain.py` | V16 contract import, auto-upgrades feature_set to v16 when --v16-features used |

### BigQuery Schema

Added 6 columns to `ml_feature_store_v2`:
- `feature_55_value`, `feature_55_quality`, `feature_55_source`
- `feature_56_value`, `feature_56_quality`, `feature_56_source`

### Backfill Results

- **13,822 records** updated (Dec 1, 2025 → Feb 27, 2026)
- `over_rate_last_10`: 12,587 records (players with 5+ games with prop lines)
- `margin_vs_line_avg_last_5`: 13,172 records (players with 3+ games with prop lines)
- Value ranges verified: over_rate [0.0, 1.0] avg 0.468; margin [-25, +25] avg -0.17

### Deployment

All services deployed with commit `bd7f451a`:
- Phase 4 precompute processors (manual deploy)
- Prediction worker (auto-deploy via Cloud Build)
- All 16 services confirmed up to date (zero drift)

---

## What to Do Next (Priority Order)

### 1. Train and Enable V16 Model (HIGHEST PRIORITY)

The feature store now has V16 features. Train a fresh V16 model:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V16_PRODUCTION" --feature-set v12 --no-vegas \
    --v16-features \
    --train-start 2025-12-01 --train-end 2026-02-27 \
    --eval-start 2026-02-23 --eval-end 2026-02-27 \
    --force --enable
```

The `--v16-features` flag auto-upgrades feature_set to `v16`, which means:
- Model registered with `feature_set='v16_noveg'`
- Worker uses 52-feature vector (V12_NOVEG + 2 V16)
- Model family will be `v16_noveg_mae` (or `v16_noveg_q55` etc.)

**Alternative:** Re-enable the existing V16 model from Session 355:
```sql
-- Check the model in registry first
SELECT model_id, gcs_path, enabled, feature_set, feature_count
FROM nba_predictions.model_registry
WHERE gcs_path LIKE '%v16%';
```

If re-enabling the Session 355 model, UPDATE its `feature_set` to `v16_noveg` and `feature_count` to 52.

### 2. Monitor Anchor-Line Model

The anchor-line model (`catboost_v12_noveg_q5_train0115_0222`) was enabled as shadow in Session 355. Check its first graded predictions:

```sql
SELECT game_date, COUNT(*) as picks,
       COUNTIF(is_correct) as correct,
       ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE '%anchor%' OR system_id LIKE '%q5_train0115%'
GROUP BY game_date ORDER BY game_date;
```

### 3. Daily Steering

Run `/daily-steering` and `/validate-daily` to check overall system health.

---

## Key Files

| File | Purpose |
|------|---------|
| `shared/ml/feature_contract.py` | V16 contract definitions (V16_NOVEG = 52 features) |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | V16 batch extraction query |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | V16 feature computation |
| `predictions/worker/prediction_systems/catboost_monthly.py` | V16 prediction routing |
| `ml/experiments/quick_retrain.py` | V16 training support |

## Models Currently Enabled (Shadow)

All existing shadow models from prior sessions, plus:
- `catboost_v12_noveg_q5_train0115_0222` — Anchor-line model (Session 355)

V16 model NOT yet enabled — needs training or re-registration with correct feature_set.

## Dead Ends (Don't Revisit)

Same as Session 355 — see that handoff for full list.
