# Session 285 Handoff — Deployment Fixes, Feature Store Backfill, Archetype Dimensions

**Date:** 2026-02-17
**Focus:** Fix deployment drift, discover feature store data gap, backfill 18K rows, build 23 new archetype dimensions
**Status:** Backfill DONE. Archetype replays need re-running with fixed data.

---

## What Was Done

### 1. Deployment Drift Fixed (5 services)

All services brought to latest commit `014f7cf8`:

| Service | Type | Method |
|---------|------|--------|
| nba-grading-service | Cloud Run | `hot-deploy.sh` (first attempt TLS timeout, retry succeeded) |
| validate-freshness | Cloud Function | `deploy-function.sh` |
| reconcile | Cloud Function | `deploy-function.sh` |
| validation-runner | Cloud Function | `deploy-function.sh` |
| **Model manifest** | GCS + BQ | Updated manifest to match production model |

**Model manifest sync:** Production model `catboost_v9_33f_train20251102-20260205_20260216_191144.cbm` (Session 276 retrain sprint) was missing from GCS manifest. Added it, demoted old model, ran `./bin/model-registry.sh sync` to update BQ registry.

### 2. Feature Store Data Gap Discovery & Fix

**Root cause found:** The `feature_N_value` individual columns (dual-write) were only added to the feature store processor code on **Feb 13, 2026** (commit `83a4f08c`, Session 235). Before that, only the `features` array blob was written. This means:

- **Nov 4-27:** ~80% populated (partial backfill ran in Jan-Feb)
- **Nov 28 → Feb 11:** 0-7% populated (no dual-write code existed)
- **Feb 12+:** 85-93% populated (dual-write active)

**Impact:** The `features` blob (used by CatBoost for training/prediction) was 100% healthy for ALL dates. Only the individual `feature_N_value` columns (used by replay engine dimensional analysis) were empty. **No impact on production predictions or model quality.**

**Backfill executed:** UPDATE query extracting `features[OFFSET(N)]` → `feature_N_value` for all 54 features, respecting source logic (default/missing/fallback → NULL). 11 weekly batches, 18,394 rows updated. All dates now at 85-93% population.

**Dead features confirmed:**
- `feature_47` (teammate_usage_available) — intentionally always NaN
- `feature_50` (multi_book_line_std) — intentionally always NaN

### 3. Archetype Dimensions Built (23 new, dims 24-46)

Added to `ml/experiments/season_replay_full.py` `compute_dimensions()`:

| # | Dimension | Key Features Used |
|---|-----------|-------------------|
| 24 | Shooting Profile | pct_three (f20), pct_paint (f18), pct_mid (f19) |
| 25 | Shot Profile x Direction | Same + edge direction |
| 26 | Usage Tier | usage_rate_last_5 (f49) |
| 27 | Usage x Direction | Same + direction |
| 28 | Consistency Archetype | pts_std (f3) |
| 29 | Consistency x Direction | Same + direction |
| 30 | Star 3PT Archetype | line 25+ AND pct_three > 0.35 |
| 31 | Role Trajectory | minutes_change (f12), minutes_avg (f31) |
| 32 | Star Teammate Out | star_teammates_out (f37) |
| 33 | Star Out x Direction | Same + direction |
| 34 | Pace x Usage | team_pace (f22), usage_rate (f49) |
| 35 | Book Disagreement | multi_book_line_std (f50) — **DEAD, always NaN** |
| 36 | Book Disagree x Direction | Same — **DEAD** |
| 37 | Cold Streak | consecutive_games_below_avg (f47*) |
| 38 | Cold Streak x Direction | Same + direction |
| 39 | Line vs Season Avg | line_vs_season_avg (f53) |
| 40 | Line Pricing x Direction | Same + direction |
| 41 | Game Environment | game_total_line (f38), spread_magnitude (f41) |
| 42 | Game Env x Direction | Same + direction |
| 43 | Efficiency (PPM) | ppm_avg_last_10 (f32) |
| 44 | Compound Archetypes | Multi-feature combos (7 archetypes) |
| 45 | Signal Combos | 12 signal pair combinations |
| 46 | PPM x Tier | ppm + line range |

**Note:** Dimensions 35-36 (Book Disagreement) will never fire because feature_50 is dead. Remove or replace with a different feature.

### 4. Initial Replay Results (Pre-Backfill — INVALID)

Ran both seasons but 2025-26 had empty feature columns. Results showed massive coverage gaps:
- Compound Archetypes: 0 picks in 2025-26
- Pace x Usage: 0 picks in 2025-26
- Signal Combos: 90% fewer picks in 2025-26

**These results are INVALID.** Must re-run with backfilled data.

---

## Files Changed

| File | Change |
|------|--------|
| `ml/experiments/season_replay_full.py` | Added 23 new dimensions (24-46) in `compute_dimensions()` |
| GCS `manifest.json` | Updated production model to Session 276 retrain |
| BQ `model_registry` | Synced via `./bin/model-registry.sh sync` |
| BQ `ml_feature_store_v2` | Backfilled 18,394 rows of feature_N_value columns |

---

## Immediate Next Step: Re-Run Archetype Replays

The backfill is done. Re-run both seasons to get valid cross-season archetype results:

```bash
# 2025-26 season (best config: Cad7 + Roll42 + BL40 + AvoidFam)
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2025-11-04 --season-end 2026-02-17 \
    --cadence 7 --rolling-train-days 42 --player-blacklist-hr 40 \
    --avoid-familiar \
    --save-json ml/experiments/results/replay_2526_archetypes_v2.json

# 2024-25 season (same config)
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2024-11-06 --season-end 2025-04-13 \
    --cadence 7 --rolling-train-days 42 --player-blacklist-hr 40 \
    --avoid-familiar \
    --save-json ml/experiments/results/replay_2425_archetypes_v2.json
```

Then analyze cross-season patterns:
1. Extract HR + N for each new dimension from both JSON files
2. Find STABLE winners (HR > 55% both seasons, N >= 20 each)
3. Identify signal combos worth operationalizing
4. Remove dead dimensions (35-36 Book Disagreement)

---

## What to Look For in Results

### Highest-Priority Archetypes to Validate

From the (invalid) first run, these patterns showed promise in 2024-25 and need cross-season validation:

| Pattern | 2425 HR | 2425 N | Why It Matters |
|---------|---------|--------|----------------|
| Low Usage UNDER | 65.9% | 660 | High volume + high HR |
| Star 3PT UNDER | 63.2% | 310 | Specific, actionable |
| bench_under + rest_adv combo | 61.7% | 661 | Signal combo synergy |
| Pace+Usage Combo | 69.5% | 59 | Player archetype edge |
| Consistent Star UNDER | 68.8% | 48 | Highest HR compound |
| Volatile OVER | 42.0% | 81 | Anti-pattern to BLOCK |

### Anti-Patterns to Confirm

| Pattern | 2425 HR | Action if Confirmed |
|---------|---------|---------------------|
| 3PT Heavy OVER | 47.7% | Block in aggregator |
| Low Usage OVER | 37.2% | Block in aggregator |
| Volatile OVER | 42.0% | Block in aggregator |
| Underpriced OVER | 40.9% | Block in aggregator |

---

## Known Issues

- **Dimensions 35-36 (Book Disagreement):** Uses feature_50 which is dead (always NaN). Replace with alternative or remove.
- **feature_47 (teammate_usage_available):** Also dead. Used in some compound archetypes — those will never fire.
- **2024-25 replay skipped cycles 12-19:** All-Star break gap in data. Expected behavior.
- **Deployment drift:** Now CLEAN. All services on `014f7cf8`.

---

## Session Summary

| Item | Status |
|------|--------|
| Deployment drift | FIXED (5 services redeployed) |
| Model manifest | SYNCED (production model registered) |
| Feature store gap | FOUND & FIXED (18,394 rows backfilled) |
| Archetype dimensions | BUILT (23 new, in replay engine) |
| Archetype validation | PENDING (re-run with backfilled data) |
| Production impact | NONE (features blob was always healthy) |
