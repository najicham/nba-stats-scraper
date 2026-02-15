# Session 260: Adaptive Prediction System — Model Selection + Signal Health Feedback

**Date:** 2026-02-15
**Status:** Code complete, deploy pending
**Scope:** Configurable model selection, live signal health weighting

---

## Problem Statement

The champion model (`catboost_v9`) has decayed to ~36.7% edge 3+ HR — well below the 52.4% breakeven threshold. The model health gate correctly blocks all best bets, producing **zero picks per day**. Meanwhile:

- Challenger models (Q45 at 60%, Q43 at 51.3%, V12 at 50%) run in shadow but are unused
- Signal health is computed but never feeds back into scoring
- The entire model lifecycle (decay detection, switching, promotion) is manual

**Deadline:** Feb 19 (All-Star break ends, games resume)

---

## What Was Built

### 1A. Configurable Model Selection

**New file:** `shared/config/model_selection.py`

Two functions:
- `get_best_bets_model_id()` — reads `BEST_BETS_MODEL_ID` env var, defaults to `catboost_v9`
- `get_champion_model_id()` — always returns `catboost_v9` (for baseline grading)

**Modified 3 files** to remove hardcoded `SYSTEM_ID = 'catboost_v9'`:

| File | Change |
|------|--------|
| `ml/signals/supplemental_data.py` | All 3 query functions accept optional `system_id`, default to `get_best_bets_model_id()` |
| `data_processors/publishing/signal_best_bets_exporter.py` | Uses `get_best_bets_model_id()` for queries and BQ writes |
| `data_processors/publishing/signal_annotator.py` | Uses `get_best_bets_model_id()` for subset bridge writes |

**Switching models:**
```bash
# Point best bets at Q45
gcloud run services update <phase6-service> --region=us-west2 \
  --update-env-vars="BEST_BETS_MODEL_ID=catboost_v9_q45_train1102_0131"

# Revert to champion (remove env var → falls back to default)
gcloud run services update <phase6-service> --region=us-west2 \
  --remove-env-vars="BEST_BETS_MODEL_ID"
```

### 1B. Signal Health Weighting (LIVE)

**Modified:** `ml/signals/aggregator.py`

The `BestBetsAggregator` now accepts a `signal_health` dict and applies regime-based multipliers to each signal's contribution to the composite score:

| Regime | Multiplier | Effect |
|--------|-----------|--------|
| HOT | 1.2x | Signal counts as 1.2 signals in effective count |
| NORMAL | 1.0x | No change (default) |
| COLD | 0.5x | Signal counts as 0.5 signals — demoted but not blocked |

**Scoring formula change:**
```
# Before (Session 259):
effective_signals = min(signal_count, 3)

# After (Session 260):
effective_signals = min(sum(health_multiplier for each signal), 3.0)
```

Example: A pick with 2 HOT signals has `effective_signals = 2.4` (vs 2.0 before), giving `signal_multiplier = 1.42` instead of `1.3`.

Example: A pick with 2 COLD signals has `effective_signals = 1.0`, giving `signal_multiplier = 1.0` — effectively a single-signal contribution despite 2 qualifying signals.

**Both callers updated:**
- `signal_best_bets_exporter.py` — queries signal health before aggregation, passes to constructor
- `signal_annotator.py` — same pattern for subset bridge picks

---

## Architecture

```
BEST_BETS_MODEL_ID env var
        │
        ▼
shared/config/model_selection.py
        │
        ├──► supplemental_data.py (queries use model_id)
        ├──► signal_best_bets_exporter.py (BQ writes use model_id)
        └──► signal_annotator.py (subset writes use model_id)

signal_health_daily table
        │
        ▼
get_signal_health_summary()
        │
        ├──► BestBetsAggregator(signal_health=...)
        │         │
        │         ├── _weighted_signal_count()
        │         │       HOT → 1.2x
        │         │       NORMAL → 1.0x
        │         │       COLD → 0.5x
        │         │
        │         └── composite_score uses weighted count
        │
        ├──► signal_best_bets_exporter.py (Phase 6 export)
        └──► signal_annotator.py (subset bridge)
```

---

## Rollback Plan

**Model selection:** Remove `BEST_BETS_MODEL_ID` env var → reverts to champion default. Zero code changes needed.

**Signal health weighting:** If `signal_health_daily` table is empty or query fails, `get_signal_health_summary()` returns `{}`. The aggregator treats missing health data as NORMAL (1.0x multiplier) — identical to Session 259 behavior.

---

## Remaining Steps (This Session / Next)

### Deployment
- [ ] Push to main (auto-deploys)
- [ ] Verify Cloud Build succeeds
- [ ] Set `BEST_BETS_MODEL_ID` on Phase 6 service (after evaluating model performance)

### Backfill (Step 1C from plan)
- [ ] Backfill Q43/Q45 predictions for Feb 1-7 to increase sample sizes
- [ ] Wait for grading, then re-evaluate which model to point at

### Model Selection Decision (Step 1D)
Pre-backfill performance:
| Model | HR edge 3+ | N | Status |
|-------|-----------|---|--------|
| catboost_v9 (champion) | 36.7% | — | BLOCKED (below 52.4%) |
| Q45 | 60.0% | 25 | Best HR, small sample |
| Q43 | 51.3% | 39 | Below breakeven |
| V12 | 50.0% | 56 | Largest sample, coin flip |

**Decision criteria:** After backfill, if any model clears 52.4% with N >= 50, set `BEST_BETS_MODEL_ID` to that model. Otherwise, keep best bets blocked until Feb 19 games provide more data.

---

## Phase 2 Preview (Next Session)

- `model_performance_daily` BQ table — automated daily performance tracking
- Model decay alerts to Slack
- Challenger-beats-champion alerts
- Weekly combo registry refresh
- `validate-daily` Phase 0.58

---

## Files Changed

| File | Action | Lines |
|------|--------|-------|
| `shared/config/model_selection.py` | NEW | 28 |
| `ml/signals/aggregator.py` | MODIFY | +45 |
| `ml/signals/supplemental_data.py` | MODIFY | +25 |
| `data_processors/publishing/signal_best_bets_exporter.py` | MODIFY | +8 |
| `data_processors/publishing/signal_annotator.py` | MODIFY | +12 |
