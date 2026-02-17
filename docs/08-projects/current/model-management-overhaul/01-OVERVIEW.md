# Model Management Overhaul

**Session:** 273
**Date:** 2026-02-16
**Status:** IN PROGRESS

## Problem Statement

Three sources of truth for model management, all out of sync:
1. `MONTHLY_MODELS` dict in `catboost_monthly.py` (code)
2. `model_registry` table in BigQuery
3. `ml_experiments` table in BigQuery

Every new model required editing 3+ files + deploying. No concept of model families,
no way to group "all Q43 training runs", and hardcoded lists everywhere.

## Architecture: Before & After

### Before
```
quick_retrain.py → saves locally → manual GCS upload → manual MONTHLY_MODELS edit
                                  → manual model_registry INSERT
                                  → manual ACTIVE_MODELS edit in model_performance.py
                                  → manual TRAINING_END_DATES edit
                                  → git push + deploy
```

### After
```
quick_retrain.py → saves locally → auto GCS upload → auto model_registry INSERT
                                                    ↓
                            Worker reads model_registry at startup (fallback to dict)
                            model_performance.py reads model_registry
                            retrain-reminder reads model_registry per-family
                                                    ↓
                            git push only needed for code changes, NOT model additions
```

## Phases

### Phase 1: Schema Enrichment (COMPLETE)
Added columns to `model_registry`: `model_family`, `feature_set`, `loss_function`,
`quantile_alpha`, `enabled`, `strengths_json`, `evaluation_n_edge_3plus`.

**Model family naming convention:** `{feature_set}_{loss}`
- `v9_mae` — V9 33-feature MAE models
- `v9_q43` — V9 33-feature Quantile alpha=0.43
- `v9_q45` — V9 33-feature Quantile alpha=0.45
- `v12_noveg_mae` — V12 50-feature no-vegas MAE
- `v12_noveg_q43` — V12 50-feature no-vegas Quantile alpha=0.43 (future)
- `v12_noveg_q45` — V12 50-feature no-vegas Quantile alpha=0.45 (future)

**Migration:** `bin/migrations/001_enrich_model_registry.sql`

### Phase 2: Auto-Register from Training (COMPLETE)
`quick_retrain.py` now auto-uploads to GCS and auto-registers in `model_registry`
after governance gates pass. New models are registered with `enabled=FALSE` — user
reviews and enables after verification.

**New flags:** `--skip-auto-upload`, `--skip-auto-register`

### Phase 3: DB-Driven Model Loading (COMPLETE)
`CatBoostMonthly` now queries `model_registry` for enabled shadow models at startup.
Falls back to `MONTHLY_MODELS` dict if registry query fails.

Feature-set-aware: V9 models use 33-feature extraction, V12 models use 50-feature
name-based extraction. No separate prediction class needed per family.

### Phase 4: DB-Driven Performance Monitoring (COMPLETE)
`model_performance.py` reads `ACTIVE_MODELS` and `TRAINING_END_DATES` from
`model_registry` instead of hardcoded lists. Falls back to static lists if query fails.

### Phase 5: Multi-Family Retrain Script (COMPLETE)
`bin/retrain.sh` supports `--family FAMILY`, `--all`, `--enable` flags. Queries
`model_registry` for family configs and derives `quick_retrain.py` arguments
automatically.

### Phase 6: Per-Family Retrain Reminder (COMPLETE)
`retrain_reminder` CF reports per-family staleness instead of just the champion.
Shows all families >= 10 days old with individual urgency levels and specific
retrain commands.

### Phase 7: V12-Q43/Q45 Experiments (PENDING)
Train quantile models with V12's 50 features (vegas-free). First models to combine
expanded features + quantile loss.

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_Q43_EXPERIMENT" \
    --feature-set v12 --no-vegas --quantile-alpha 0.43 \
    --train-start 2025-11-02 --train-end 2026-02-15 --walkforward
```

## Files Changed

| File | Change |
|------|--------|
| `bin/migrations/001_enrich_model_registry.sql` | NEW — ALTER TABLE + backfill |
| `schemas/model_registry.json` | Added 7 new column definitions |
| `schemas/bigquery/predictions/11_ml_model_registry.sql` | Updated CREATE TABLE template |
| `ml/experiments/quick_retrain.py` | Auto-upload, auto-register, model_family computation |
| `predictions/worker/prediction_systems/catboost_monthly.py` | DB-driven loading, feature-set-aware |
| `predictions/worker/worker.py` | Updated logging for registry vs dict source |
| `ml/analysis/model_performance.py` | DB-driven active models from registry |
| `bin/retrain.sh` | Multi-family --all/--family/--enable support |
| `orchestration/cloud_functions/retrain_reminder/main.py` | Per-family staleness reporting |

## Verification

```bash
# 1. Run migration
bq query --use_legacy_sql=false < bin/migrations/001_enrich_model_registry.sql

# 2. Verify backfill
bq query --use_legacy_sql=false "
SELECT model_id, model_family, feature_set, loss_function, enabled
FROM nba_predictions.model_registry
WHERE model_family IS NOT NULL"

# 3. Test multi-family retrain (dry run)
./bin/retrain.sh --all --dry-run

# 4. Test retrain reminder locally
PYTHONPATH=. python orchestration/cloud_functions/retrain_reminder/main.py

# 5. Deploy and verify worker loads from registry
git push origin main
# Check logs: "Loaded N models from model_registry (X from registry, Y from dict)"
```

## Key Design Decisions

1. **Fallback everywhere** — Every registry query has a fallback to hardcoded values.
   If BQ is down, the worker still loads models from the dict.

2. **enabled=FALSE by default** — Auto-registered models don't generate predictions
   until explicitly enabled. This prevents untested models from running.

3. **Feature-set-aware CatBoostMonthly** — One class handles both V9 (33-feature)
   and V12 (50-feature) models based on `feature_set` metadata from registry.

4. **MONTHLY_MODELS dict preserved** — Not deleted, serves as fallback and
   documentation of existing models.

5. **Migration uses IF NOT EXISTS** — Safe to run multiple times.
