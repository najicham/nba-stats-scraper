# Weekly Model Retraining Guide

## Overview

Models must be retrained every 7 days to maintain accuracy. Walk-forward simulation across 2 seasons (Session 458, CLEAN data after leakage fix) proved:
- **56-day rolling window + 7-day retrain cadence** is the optimal configuration
- 7-day retrain beats 14-day by ~1pp HR consistently
- Stale models (10+ days) become **confidently wrong** — high edge but low HR

### Critical Finding: Model vs Pipeline (Session 458)

**The raw model is ~53% HR at edge 3+.** The BB pipeline (signals + filters) is where the value lives:
- Raw model edge 3+: **53.4%** (N=2,193 across 2 seasons)
- BB pipeline overall: **60.3%** (156 picks, 3.6/day)
- BB edge 5+: **65.6%** (122 picks, 2.9/day)
- BB edge 5+ with combo signals: **74-83%** (18-50 picks)

Previous 85% HR claim (Sessions 454-457) was **entirely due to data leakage** — features 0-4 included today's actual game score in rolling averages. See Session 458 handoff for full details.

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

## Validated Configuration (Session 458 — Clean Data)

| Parameter | Value | Evidence |
|-----------|-------|----------|
| Training window | 56 days (rolling) | 53.4% HR vs 52.8% (42d) vs 52.2% (90d) |
| Retrain cadence | 7 days | +1pp over 14-day cadence |
| Feature set | V12_NOVEG | Best across 80+ experiments |
| CatBoost params | iter=1000, lr=0.05, depth=6, l2=3 | Production defaults |
| Vegas features | Excluded from training | Used only for HR grading |

## BB Pipeline Performance (2025-26 Season)

The BB pipeline is where profitability comes from, not raw model accuracy:

| Tier | Rule | HR | N | Picks/Day |
|------|------|-----|-----|-----------|
| Platinum | Edge 5+ with combo_3way/combo_he_ms | **83.3%** | 18 | 1.3 |
| Gold | Edge 7+ | **78.8%** | 33 | 1.6 |
| Silver | Edge 5+ with rest_advantage_2d | **74.0%** | 50 | 2.4 |
| Ultra (current) | Current ultra_tier=true | **73.0%** | 37 | 1.9 |
| Edge 5+ OVER | All OVER at edge 5+ | **67.1%** | 73 | 2.1 |
| Edge 5+ (all) | All picks at edge 5+ | **65.6%** | 122 | 2.9 |
| All BB | Everything | **60.3%** | 156 | 3.6 |
| **Edge 3-5** | Low-edge picks | **40.0%** | 34 | — |

**Key insight:** Edge 3-5 picks are net-negative. The path to 70%+ is raising the edge floor and using signal combos, not improving the raw model.

## Governance Gates

Every retrained model must pass (enforced in `quick_retrain.py`):
1. Edge 3+ hit rate >= 60%
2. Vegas bias within ±1.5 points
3. No tier bias > ±5 points
4. Both OVER and UNDER HR >= 52.4% at edge 3+
5. N >= 50 graded predictions in eval window

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
- Walk-forward results (clean): `results/nba_walkforward_clean/`
- Walk-forward results (leaked, historical reference): `results/nba_walkforward/`
- [Model Registry](MODEL-REGISTRY.md)
- [quick_retrain.py](../../../../ml/experiments/quick_retrain.py)
- [retrain.sh](../../../../bin/retrain.sh)
