# Weekly Model Retraining Guide

## Overview

Models must be retrained every 7 days to maintain accuracy. Walk-forward simulation across 2 seasons (Sessions 454-457) proved:
- **56-day rolling window + 7-day retrain cadence** is the optimal configuration
- 7-day retrain beats 14-day by ~2pp HR consistently
- Stale models (10+ days) become **confidently wrong** — high edge but low HR
- The model needs ~4 months of in-season data to reach peak performance (85%+ HR at edge 3+)

### Audit Status (Session 457)

The 85% HR claim has been **audited and confirmed legitimate**:
- **No data leakage**: All 54 features verified to use `game_date < current_date` temporal boundaries
- **No future data in features 50-53**: prop_over/under_streak use historical game lines, not current. Combined importance only 5.0%.
- **Seed-stable**: 5 random seeds produce 84.6%-85.5% HR at edge 3+ (<1pp variance)
- **Not trivially gameable**: Naive baseline (always OVER) = 48.6%, random predictor at edge 3+ = 49.9%
- **Feature importance clean**: Top 5 features (62% of model) are all historical scoring averages
- **DNP survivorship**: ~10% DNP rate excluded, but DNPs don't have prop lines in production either (apples-to-apples)
- Minor caveats: retrospective feature store regeneration gives slightly cleaner data than real-time (<1-2pp)

## Schedule

| Day | Action | Tool |
|-----|--------|------|
| **Monday 5 AM ET** | `weekly-retrain` CF auto-retrains all enabled families | Automated (Session 458) |
| **Monday 9 AM ET** | `retrain-reminder` CF sends Slack alert (backup verification) | Automated |
| Monday 6 AM - 11:30 AM | Daily pipeline runs (Phase 1-4) | Automated |
| Monday ~11:30 AM | Phase 5 predictions use freshly retrained models | Automated |
| Post-retrain | Monitor via Slack notification (success/blocked/error) | `#nba-alerts` |

**Manual override:** `./bin/retrain.sh --all --enable` — runs the same retraining logic locally.

## Quick Start

```bash
# Retrain all enabled model families (56-day rolling window)
./bin/retrain.sh --all --enable

# Dry run to preview
./bin/retrain.sh --all --dry-run

# Train a specific family
./bin/retrain.sh --family v12_noveg_mae --enable

# Custom training end date
./bin/retrain.sh --all --enable --train-end 2026-03-08
```

## Validated Configuration

From walk-forward simulation (Session 455, 2 full seasons of data):

| Parameter | Value | Evidence |
|-----------|-------|----------|
| Training window | 56 days (rolling) | 85.0% HR vs 84.2% (42d) vs 85.3% (90d, but fewer picks) |
| Retrain cadence | 7 days | +2pp over 14-day cadence |
| Feature set | V12_NOVEG | Best across 80+ experiments |
| CatBoost params | iter=1000, lr=0.05, depth=6, l2=3 | Production defaults |
| Vegas features | Excluded from training | Used only for HR grading |

## Seasonal Performance Pattern

Walk-forward reveals a predictable seasonal cycle:

| Period | Edge 3+ HR | Edge 3+ as % of preds | Notes |
|--------|-----------|----------------------|-------|
| Nov (weeks 1-4) | 48-55% | 25-40% | Model warming up, few high-edge picks |
| Dec (weeks 5-8) | 54-84% | 7-39% | Varies by season, model still calibrating |
| Jan-Feb | 56-90% | 4-45% | Recovery phase, highly variable |
| Mar-Jun | 85-94% | 30-40% | **Peak performance — model fully calibrated** |

**Key insight:** Low HR in Nov-Dec is NOT fixable with features. It's data availability — the model needs ~3-4 months of in-season data to diverge from the line. Fresh 7-day retraining is the ONLY intervention that consistently helps.

## Governance Gates

Every retrained model must pass (enforced in `quick_retrain.py`):
1. Edge 3+ hit rate >= 60%
2. Vegas bias within ±1.5 points
3. No tier bias > ±5 points
4. Both OVER and UNDER HR >= 52.4% at edge 3+
5. N >= 50 graded predictions in eval window

## How `bin/retrain.sh` Works

1. Queries `model_registry` for all enabled model families
2. For each family: runs `quick_retrain.py` with family's feature_set + loss_function
3. Uses 56-day rolling window ending yesterday
4. Auto-uploads to GCS, auto-registers in `model_registry`
5. With `--enable`: sets `enabled=TRUE` on new model
6. Worker picks up new model on next prediction cycle

## Automation (Session 458)

### `weekly-retrain` Cloud Function — DEPLOYED
- **Trigger:** Cloud Scheduler, every Monday 5 AM ET
- **Logic:** Queries `model_registry` for enabled families, trains each with 56d rolling window
- **Governance gates enforced:** HR>=60% edge 3+, vegas bias ±1.5, directional balance, N>=50
- **Auto-registers** passing models with `enabled=TRUE`. Worker picks up on next prediction cycle.
- **Slack notification** on success/blocked/error per family
- **Safety:** Max 5 families/run, skips families retrained <5 days ago, min 3 models remain enabled
- **Specs:** Gen2 CF, 4GiB memory, 2 CPU, 1800s timeout
- **Dry run:** `?dry_run=true` query param
- **Single family:** `?family=v12_noveg_mae` query param

### Other Retrain Infrastructure
- `retrain-reminder` CF: Monday 9 AM ET — backup Slack alert if auto-retrain fails
- `monthly-retrain` CF: **DEPRECATED** (V8 baseline, 60d window). Superseded by weekly-retrain.
- `bin/retrain.sh`: Manual equivalent for ad-hoc retraining

### Prior-Season Warm-Start (Future Experiment)
CatBoost `fit()` supports `init_model` parameter for continuing training from existing model.
Could help Nov-Dec warm-up phase (+10pp potential). Test in walk-forward framework first:
- Modify `walk_forward_simulation.py` to pass prior season's model as `init_model`
- Compare Nov-Dec HR with/without warm-start
- If validated, add `--warm-start` flag to `quick_retrain.py`

## Rollback

```bash
# Disable bad model
python bin/deactivate_model.py MODEL_ID --re-export

# If all models are bad, force worker cache refresh
gcloud run services update prediction-worker --region=us-west2 \
    --update-env-vars="MODEL_CACHE_REFRESH=$(date +%Y%m%d_%H%M)"
```

## Related

- Walk-forward simulation: `scripts/nba/training/walk_forward_simulation.py`
- BB pipeline gap analysis: `scripts/nba/training/bb_pipeline_gap_analysis.py`
- Walk-forward results: `results/nba_walkforward/`
- [Model Registry](MODEL-REGISTRY.md)
- [quick_retrain.py](../../../../ml/experiments/quick_retrain.py)
- [retrain.sh](../../../../bin/retrain.sh)
