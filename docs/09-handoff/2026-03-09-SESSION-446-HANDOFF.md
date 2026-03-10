# Session 446 Handoff — Per-Model Pipeline Deploy + Walk-Forward Planning

**Date:** 2026-03-09
**Session:** 446 (NBA)
**Status:** Per-model pipeline DEPLOYED. Walk-forward simulation PLANNED but not built.

---

## What Was Done

### Per-Model Pipeline Bug Fixes & Deploy

1. **Replay validation passed:** 73.8% HR (62-22) vs 65.9% old system (+7.9pp) across 52 game dates (Jan 9 - Mar 7)
2. **Fixed 3 critical bugs before deploy:**
   - `include_disabled` parameter added to `_query_all_model_predictions()` — disabled_models filter was excluding blocked registry entries during historical replay
   - V9 SQL catch-all added to `build_system_id_sql_filter()` — `catboost_v9_%` prefix missing, so `catboost_v9_train1102_0108` wasn't matched
   - `source_pipeline` field now tagged in exporter before calling merger — was breaking pipeline agreement counting
3. **Removed hardcoded model blocklist from query** — `OR model_id IN ('catboost_v12', 'catboost_v9')` removed from disabled_models CTE. Registry is now single source of truth.
4. **Silent failure logging** — `logger.debug` → `logger.warning` for missing predictions
5. **Re-enabled catboost_v9_train1102_0108** — best model in fleet (12-0 in replay, 87.5% OVER 3-4). Was silently blocked by LEGACY_MODEL_BLOCKLIST.
6. **All 127 tests pass**

### Root Cause: Why Best Model Was Disabled

`LEGACY_MODEL_BLOCKLIST` in `aggregator.py` (Session 382C) blocks any system_id matching bare `catboost_v9`/`catboost_v12`. Combined with old winner-take-all dedup, the best model would win selection then get blocked, falling through to worse alternatives. Per-model pipelines eliminate this class of bug — each model runs independently, registry is only filter.

### Docs Updated
- **CLAUDE.md** — MULTIMODEL section replaced with PIPELINES section, `model_bb_candidates` table added
- **system-features.md** — Signal Discovery section rewritten for per-model architecture
- **multi-model-best-bets/00-ARCHITECTURE.md** — Deprecated with pointer to per-model docs
- **MEMORY.md** — Session 446 findings, algorithm `v446_per_model_deployed`

### Replay Results Summary

| Metric | New (Per-Model) | Old System | Delta |
|--------|----------------|------------|-------|
| Hit Rate | **73.8%** | 65.9% | **+7.9pp** |
| Total Picks | 84 | 129 | -45 |
| P&L (units) | 37.8 | 36.6 | +1.2 |

- OVER: 75.9% vs 65.9% (+10pp), UNDER: 72.7% vs 65.9% (+6.8pp)
- Edge 3-4: 86% vs 44% (+42pp!), Edge 6+: 89% vs 76% (+13pp)
- `catboost_v9_train1102_0108`: 12-0 (100%) in replay
- Pipeline agreement 2+ models: 82.6% HR

---

## What to Do Next

### Priority 1: Build NBA Walk-Forward Simulation (MAIN TASK)

**Goal:** Validate our model fleet and best-bets strategy across MULTIPLE seasons to prove it's not overfit to 2025-26.

**The user's key concern:** "I think a true test is to find a strategy and then have it work over multiple seasons." Current replays only test on the season we tuned on — this is circular validation.

#### Architecture: 3-Layer Walk-Forward

**Layer 1 — Raw Model Walk-Forward** (`scripts/nba/training/walk_forward_simulation.py`, ~700 lines)
- Train CatBoost V12_NOVEG on rolling window → predict → grade → retrain → repeat
- Uses `ml_feature_store_v2` for features, `player_game_summary` for actuals
- Tests: training windows (42/56/90d), retrain cadence (7/14/21d), edge thresholds (1-5 pts)
- Output: daily_metrics.csv, retrain_log.csv, predictions.csv, summary.json

**Layer 2 — Best-Bets Pipeline Replay** (existing `bin/replay_per_model_pipeline.py`)
- Feed Layer 1 predictions through full signal/filter/aggregator/merge stack
- Tests whether the signal+filter strategy adds value on top of raw model

**Layer 3 — Cross-Season Validation** (new orchestration)
- Run Layers 1+2 on multiple seasons
- Compare: does the SAME strategy (same signals, same filters, same thresholds) work across seasons?
- If strategy only works on 2025-26, it's overfit

#### Data Availability

| Season | Clean Feature Store Rows | Line Coverage | Notes |
|--------|------------------------|---------------|-------|
| 2024-25 | ~8,400 (Oct 22 - Feb 13) | ~58% | Broke at ASB (Feb 14). Mar-Jun has rows but `required_default_count=1` |
| 2025-26 | ~13,600 (Nov - Mar 7) | ~58% | Current season, Nov ramp-up (26% clean) |

**2024-25 broken period (Feb 19 - Jun 2025):** Feature store rows exist, upstream data (player_game_summary) is complete, but `required_default_count=1` for 79% of rows. Root cause: quality scorer version artifact — all visible feature sources are non-default. Options:
- **Option A (recommended):** Skip. Use Oct-Feb clean data only as seed model.
- **Option B:** Relax to `required_default_count <= 1` for training-only data
- **Option C:** Re-run Phase 4 backfill with current quality scorer (upstream data exists)

#### Recommended Approach: Hybrid Seeding

1. Train initial model on **2024-25 regular season** (Oct 22 2024 - Feb 13 2025, ~8,400 clean rows)
2. Start predicting **Oct 22, 2025** (Day 1 of 2025-26 season)
3. Retrain every 14 days as 2025-26 data accumulates
4. Rolling window naturally phases out old-season data
5. This answers: "How fast does the model recover from stale pre-season training data?"

#### For True Cross-Season Validation

To test on the 2024-25 season itself, you'd need to seed from 2023-24. The feature store has data from mid-2024 with feature columns, but quality is unknown. Check:
```sql
SELECT FORMAT_DATE('%Y-%m', game_date) as month, COUNT(*) as rows,
  COUNTIF(COALESCE(required_default_count, default_feature_count, 0) = 0) as clean
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2023-10-01' AND '2024-10-20'
GROUP BY 1 ORDER BY 1
```

If 2023-24 data exists and is clean, true cross-season validation becomes possible.

#### Key Design Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Feature set | V12_NOVEG (50 features) | Production standard, excludes vegas |
| Line source | `feature_25_value` (vegas_points_line) | Available in feature store, ~58% coverage |
| Loss function | MAE | Production default for CatBoost regressor |
| Train/val split | 85/15 | Matches `quick_retrain.py` |
| CatBoost params | iterations=1000, lr=0.05, depth=6, l2=3 | Production defaults |
| Quality gate | `required_default_count = 0` | Zero tolerance (match production) |
| Postseason data | EXCLUDE | Different distribution (8-man rotations) |

#### Key Files to Reference

| File | Purpose |
|------|---------|
| `scripts/mlb/training/walk_forward_simulation.py` | MLB reference implementation (754 lines) |
| `shared/ml/feature_contract.py` | V12_NOVEG_FEATURE_NAMES, FEATURE_STORE_NAMES, build_feature_array_from_columns() |
| `shared/ml/training_data_loader.py` | Quality filters, BQ query patterns |
| `ml/experiments/quick_retrain.py` | CatBoost training params, prepare_features(), compute_hit_rate() |
| `bin/replay_per_model_pipeline.py` | Per-model pipeline replay (Layer 2) |

#### Gotchas

- V12_NOVEG uses feature NAMES not positions — indices 25-28 are excluded, so extraction must use `V12_NOVEG_FEATURE_NAMES` mapped to `feature_N_value` columns
- CatBoost handles NaN natively — do NOT fill defaults
- Feature store data starts Nov 2024 (no Oct 2024 for 2024-25 season)
- 2024-25 data breaks at ASB (Feb 14, 2025) — 0 clean rows after
- ~58% of clean rows have lines (F25) — others get MAE only, no HR grading

### Priority 2: Monitor Per-Model Pipeline in Production

Session 450 deployed the per-model pipeline. Monitor:
- `model_bb_candidates` table getting populated
- Per-model pipeline logs for errors
- Pick quality vs replay expectations
- 9 enabled models, 2 BLOCKED pending auto-disable

### Priority 3: Observation Promotion

Wait for data to accumulate (~late March). Current observations have < 10 graded picks in `best_bets_filtered_picks`. Need N >= 20-30 for meaningful CF HR.

### Priority 4: UNDER Signal Expansion

UNDER bottleneck identified in Session 442: 907 candidates/day → 25 BB picks (2.8%). Signals are OVER-oriented. Starter UNDER (18-25 line) = 65.5% HR — gold left on table.

---

## Files Modified This Session

| File | Change |
|------|--------|
| `ml/signals/per_model_pipeline.py` | `include_disabled` param, removed hardcoded blocklist from query, warning logging |
| `shared/config/cross_model_subsets.py` | Added `catboost_v9_%` catch-all to SQL filter |
| `data_processors/publishing/signal_best_bets_exporter.py` | `source_pipeline` tagging before merge |
| `bin/replay_per_model_pipeline.py` | Passes `include_disabled=True` for replay |
| `CLAUDE.md` | PIPELINES section, model_bb_candidates table |
| `docs/02-operations/system-features.md` | Signal Discovery section rewritten |
| `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md` | Deprecated |

## Commits (from Session 445, not yet pushed as of 446 start)
```
d8c21ab2 docs: Session 445 handoff — per-model pipelines + replay
35a113ff feat: Session 443 — per-model pipeline season replay script
bfac51f2 feat: Session 443 — per-model best bets pipelines
```
Session 450 pushed all code to main (15 builds SUCCESS).

## BQ Changes
- `catboost_v9_33f_train20251102-20260108_20260208_170526` re-enabled (shadow → active)
