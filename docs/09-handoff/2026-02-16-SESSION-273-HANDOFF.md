# Session 273 Handoff — Model Management Overhaul + Signal System Rethink

**Date:** 2026-02-16
**Status:** Model management COMPLETE, signal rethink PENDING

## What Was Done This Session

### Model Management Overhaul (Phases 1-6 COMPLETE)

Replaced the fragmented model management system (3 sources of truth, hardcoded lists
everywhere) with a single source of truth in BigQuery `model_registry`.

**Key changes:**
1. **Schema enriched** — `model_registry` now has `model_family`, `feature_set`,
   `loss_function`, `quantile_alpha`, `enabled`, `strengths_json`, `evaluation_n_edge_3plus`
2. **Auto-register from training** — `quick_retrain.py` auto-uploads to GCS and
   auto-registers in `model_registry` after gates pass (enabled=FALSE by default)
3. **DB-driven model loading** — Worker reads enabled models from registry at startup,
   falls back to MONTHLY_MODELS dict if BQ fails. Feature-set-aware: V9 (33 features)
   and V12 (50 features) handled by same `CatBoostMonthly` class.
4. **DB-driven performance monitoring** — `model_performance.py` reads active models
   from registry instead of hardcoded `ACTIVE_MODELS` list
5. **Multi-family retrain** — `bin/retrain.sh` supports `--family`, `--all`, `--enable`
6. **Per-family retrain reminders** — CF reports all stale families, not just champion

**Migration ran and verified:**
```
v9_mae (production, enabled) — catboost_v9_33features_20260201_011018 (39d old!)
v12_noveg_mae (active, enabled) — catboost_v12_50f_huber_rsm50_... (16d old)
v8_mae (active, disabled)
+ 4 more disabled/deprecated v9 models
```

**Q43/Q45 models are NOT in the registry** — they only exist in the MONTHLY_MODELS
fallback dict. They'll get registered when retrained with the new auto-register flow.

### Files Changed

| File | Change |
|------|--------|
| `bin/migrations/001_enrich_model_registry.sql` | NEW — ALTER TABLE + backfill (already ran) |
| `schemas/model_registry.json` | 7 new columns |
| `schemas/bigquery/predictions/11_ml_model_registry.sql` | Updated template |
| `ml/experiments/quick_retrain.py` | Auto-upload, auto-register, `--skip-auto-upload/register` |
| `predictions/worker/prediction_systems/catboost_monthly.py` | DB-driven + feature-set-aware |
| `predictions/worker/worker.py` | Registry vs dict logging |
| `ml/analysis/model_performance.py` | `get_active_models_from_registry()` |
| `bin/retrain.sh` | Multi-family `--all`/`--family`/`--enable` |
| `orchestration/cloud_functions/retrain_reminder/main.py` | Per-family staleness |
| `docs/08-projects/current/model-management-overhaul/01-OVERVIEW.md` | NEW |
| `docs/08-projects/current/model-management-overhaul/02-SIGNAL-SYSTEM-ANALYSIS.md` | NEW |

**NOT committed/pushed yet.** All changes are local.

## What Needs to Happen Next

### 1. Commit and Deploy (5 min)

```bash
git add -A && git commit -m "feat: model management overhaul — DB-driven loading, multi-family retrain, per-family reminders"
git push origin main
# Auto-deploys via Cloud Build triggers
```

### 2. Signal System Rethink (THE BIG OPEN QUESTION)

**Read first:** `docs/08-projects/current/model-management-overhaul/02-SIGNAL-SYSTEM-ANALYSIS.md`

#### The Problem

The signal system has a critical **OVER bias**:
- 5 of 8 core signals are OVER_ONLY
- Both validated combo signals are OVER_ONLY
- **Zero UNDER_ONLY signals in production**
- The 2-signal minimum means Q43/Q45 UNDER picks almost never qualify for best bets

Best bets currently come from **one model only** (`get_best_bets_model_id()` in
`shared/config/model_selection.py`). The signal annotator, aggregator, and exporter
all operate on this single model's predictions.

#### Key Question: Should Best Bets Pull From Multiple Models?

**Current:** One model → signals → top 5 picks
**Proposed:** Multiple models → per-family signals → blended top 5

Options:
- **Option A:** Keep single-model best bets, just promote UNDER prototype signals
- **Option B:** Multi-model aggregation (V9 OVER picks + Q43 UNDER picks → blended top 5)
- **Option C:** Per-family signal profiles + multi-model aggregation

#### Quick Win Available (Option A)

Three UNDER prototype signals already exist in code:
- `b2b_fatigue_under` — `ml/signals/b2b_fatigue_under.py`
- `cold_continuation_2` — `ml/signals/cold_continuation_2.py`
- `fg_cold_continuation` — `ml/signals/fg_cold_continuation.py`

Promoting these to production would immediately give UNDER picks signal coverage.
Backtest them first using `ml/experiments/signal_backtest.py`.

#### Key Files to Study

| File | Why |
|------|-----|
| `shared/config/model_selection.py` | `get_best_bets_model_id()`, `MODEL_CONFIG` — single-model bottleneck |
| `data_processors/publishing/signal_annotator.py` | Phase 6 signal evaluation, calls get_best_bets_model_id() |
| `data_processors/publishing/signal_best_bets_exporter.py` | GCS export, BestBetsAggregator usage |
| `ml/signals/aggregator.py` | Scoring formula, health weighting, combo blocking |
| `ml/signals/registry.py` | 22 signals registered, build_default_registry() |
| `ml/signals/combo_registry.py` | 7 validated combos, SYNERGISTIC/ANTI_PATTERN |
| `ml/signals/signal_health.py` | Regime classification (HOT/NORMAL/COLD) |
| `predictions/coordinator/signal_calculator.py` | Daily signal computation, `PRIMARY_ALERT_MODEL = 'catboost_v9'` |

#### Signal Direction Distribution (the core issue)

```
OVER_ONLY:  minutes_surge, 3pt_bounce, cold_snap, blowout_recovery, combo_he_ms
BOTH:       model_health, high_edge, pace_mismatch
UNDER_ONLY: (none in production)
```

#### Recommended Path

1. **Backtest UNDER prototypes** — use `signal_backtest.py` on the 3 existing UNDER signals
2. **Promote winners** — add to `build_default_registry()` in `registry.py`
3. **Add per-family signal profiles** — extend `MODEL_CONFIG` in `model_selection.py`
4. **Multi-model best bets** — modify `signal_annotator.py` to evaluate multiple models,
   `aggregator.py` to blend picks from different families

### 3. Retrain All Families (When Ready)

Both enabled families are stale:
```
v9_mae:         39d old (URGENT)
v12_noveg_mae:  16d old (OVERDUE)
```

After deploying the new code:
```bash
./bin/retrain.sh --all --promote    # Retrain both families
```

This will auto-register new models in the registry. The worker will pick them up
on next restart (or redeploy).

### 4. V12-Q43/Q45 Experiments (Phase 7, After Retrain)

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V12_Q43_EXPERIMENT" \
    --feature-set v12 --no-vegas --quantile-alpha 0.43 \
    --train-start 2025-11-02 --train-end 2026-02-15 --walkforward
```

First models to combine V12's 50 features + quantile loss. Auto-registers as
`v12_noveg_q43` family with `enabled=FALSE`.

## Architecture Context

### Model Family Naming Convention
`{feature_set}_{loss}` — e.g., `v9_mae`, `v9_q43`, `v12_noveg_mae`, `v12_noveg_q43`

### Registry-Driven Loading Flow
```
Worker startup → get_enabled_monthly_models()
  → queries model_registry WHERE enabled=TRUE AND is_production=FALSE AND status='active'
  → falls back to MONTHLY_MODELS dict if query fails
  → CatBoostMonthly checks feature_set to decide V9 (33-feat) or V12 (50-feat) extraction
```

### Signal Best Bets Flow (Current)
```
Phase 6 → signal_annotator.py → get_best_bets_model_id() → ONE model
  → evaluates 22 signals
  → BestBetsAggregator scores: edge × signal_count × health_multiplier
  → blocks ANTI_PATTERN combos
  → requires MIN_SIGNAL_COUNT = 2
  → exports top 5 to signal-best-bets/{date}.json
```

## Testing Commands

```bash
# Verify registry state
bq query --use_legacy_sql=false "SELECT model_id, model_family, feature_set, enabled, status FROM nba_predictions.model_registry ORDER BY model_family"

# Test multi-family retrain
./bin/retrain.sh --all --dry-run

# Test retrain reminder
PYTHONPATH=. python orchestration/cloud_functions/retrain_reminder/main.py

# Check deployment
./bin/check-deployment-drift.sh --verbose
```
