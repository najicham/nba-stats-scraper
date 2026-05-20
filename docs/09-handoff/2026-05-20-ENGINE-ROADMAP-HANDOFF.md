# Handoff — 2026-05-20 — Engine Roadmap Execution + MLB Early-Hook Plan

**Previous session:** executed the P0 foundation + P2 quick-wins of the 2026-05-19
engine improvement roadmap, then ran the P0-4 clean re-run.
**Branch:** `main`. **Commit:** `60279b20` (committed, **NOT pushed** — push triggers
auto-deploy).
**Roadmap:** `docs/08-projects/current/2026-offseason-plan/05-ENGINE-IMPROVEMENT-ROADMAP.md`

---

## 1. What was completed (commit `60279b20`, 14 files)

The **leakage trifecta** and the P2 quick-wins are done, verified, and committed.

| ID | Fix | Files |
|----|-----|-------|
| P0-1 | Temporal train/val split (replaced random `train_test_split` that leaked future games into the early-stopping val set) | `quick_retrain.py`, `weekly_retrain/main.py` |
| P0-2 | Per-row `season_stats` window in `augment_v12_features` (was one `GROUP BY` average stamped on every row → look-ahead). Regression test added. | `quick_retrain.py`, `tests/ml/unit/test_v12_augmentation_leakage.py` |
| P0-3 | CI-aware governance gates — bootstrap 95% CIs, gate fails only when the CI upper bound is below the floor; 28-day holdout; `min_n` 40 | `quick_retrain.py`, `weekly_retrain/main.py` |
| P2-1 | Removed dead `rest_advantage_2d` weight (signal unregistered) | `aggregator.py` |
| P2-2 | Wired `fg.xfip` into MLB `pitcher_loader`; fixed `season_era`→`era_rolling_10` key | `pitcher_loader.py`, `mlb/signals.py` |
| P2-3 | Removed dead MLB `il_return_skip` / `pitch_count_cap_skip` filters (data nonexistent) | `mlb/signals.py`, `mlb/registry.py`, `mlb_filter_counterfactual_evaluator/main.py` |
| P2-4 | Fixed `recent_trend` (feature 11) slice inversion | `feature_calculator.py` |
| P2-6 | Reconciled signal/filter registry drift (36 filters added to `filters.yaml`, `ACTIVE_SIGNALS`, `ELIGIBLE_FOR_AUTO_DEMOTE`/`NEVER_DEMOTE`) | `filters.yaml`, `signal_health.py`, `filter_counterfactual_evaluator/main.py` |
| P2-7 | Phase 4→5 feature-store coverage gate + published-JSON-vs-BQ canary | `phase4_to_phase5/main.py`, `pipeline_canary_queries.py` |

All pre-commit hooks passed. **Nothing pushed or deployed.**

### P0-4 clean re-run — the key finding

Re-ran the foundational experiments on leak-fixed code (`quick_retrain.py` feature
matrix v12_noveg–v19 × 2 windows; `season_walkforward.py` cadence/window sweep).

- **"Adding features consistently hurts" / "v12_noveg is best" / "all experiments
  DEAD_END" was a leakage artifact.** On clean data the feature sets v12_noveg–v19
  are statistically indistinguishable — v12_noveg is *not* the best. The lore is
  invalid; feature experimentation is back on the table.
- **Window/eval-period variance dominates feature-set variance** (8–20pp swing
  between windows vs ~4pp between feature sets, well inside the CI). Single-window
  experiments — how the old lore was built — are unreliable.
- **Cadence/window:** 21-day cadence was the *worst* of 7/14/21; 56-day window ≥
  42-day. The roadmap's "21d/42d beats 7d/56d" hypothesis is **rejected** — keep
  56d window, 7d cadence.
- **No model was registered or deployed** (every run used
  `--skip-register --skip-auto-upload --skip-auto-register`).

---

## 2. Remaining roadmap work (not done)

| Item | Why deferred | Next action |
|------|--------------|-------------|
| **Feature-set walk-forward follow-up** | P0-4 single-window screen was too noisy to crown a winner | Multi-cycle walk-forward of v14/v16/v17/v19 vs v12_noveg via `season_walkforward.py` (or `--walkforward` in `quick_retrain.py`). Only then consider promoting a feature set. |
| **P2-5** drop dead features 41/42/47/50 | Roadmap says fold into the clean re-run; it's a feature-contract change | Do it inside the walk-forward follow-up above. |
| **P2-7 T1-5** quality scorer 54→60 + BQ migration | **Discovery:** `ml_feature_store_v2.feature_55–59_quality` columns are mis-typed `STRING` (should be `FLOAT64` like 0–53); only `feature_54` lacks quality/source entirely. The "clean column-add" is actually a drop/re-add of 5 mistyped columns. Touches the zero-tolerance gate. | Own focused, tested change: drop+re-add `feature_55–59_quality` as `FLOAT64`, add `feature_54_quality/source`, flip `FEATURE_COUNT` 54→60, **add 54–59 to `OPTIONAL_FEATURES`** (or the zero-tolerance gate breaks — verified safe path). The columns are all NULL today so the drop loses nothing. |
| **`bench_under` decision** | Registered as BOTH a +2.0 UNDER signal and a negative filter; the signal keys on post-game `starter_flag` (look-ahead — pre-game proxy HR ≈ 51.8%) | Human call: confirm `starter_flag` is genuinely pre-game-available (RotoWire lineups), or drop the signal weight to ~1.0 / move to shadow. |
| **Roadmap P1 / P3 / P4** | Out of scope of this batch | P1 high-EV experiments (referee signal, bias-corrected edge, auto-halt input fix, archetype, `edge_zscore`), P3 new markets (3PT, assists/rebounds), P4 research bets. See the roadmap doc. |

---

## 3. NEW PROJECT — MLB pitcher early-hook / lineup-quality features

**Goal (from the user):** use *which lineup a pitcher faces* to predict whether he
gets pulled early, and feed that into the strikeout-prop model.

### 3.1 Why this matters

The MLB model predicts pitcher **strikeouts**. Strikeouts ≈ `innings_pitched ×
K_rate`. The model already handles K_rate well (pitch arsenal, opponent K%). The
volatile, under-modeled multiplier is **innings pitched** — a starter who gets
shelled is pulled after 4 IP and physically cannot reach a 6.5 K line. **Opposing
lineup quality drives early hooks, which cap strikeout upside.** That is the
missing signal.

This is effectively the proper version of the abandoned `lineup_k_analysis` work
(see §5 — that table exists but is empty; the prior "A1 lineup features" were
vapor and the "X1 deeper rebuild" was deferred. This *is* the X1 rebuild.).

### 3.2 Proposed plan (phased)

**Phase 0 — Unblock lineup data (gating dependency).**
`mlb_raw.mlb_lineup_batters` is spotty (~8/14 days, 2–6 teams/day). Nothing below
works without reliable *pre-game* lineups. Find/repair a dependable projected-lineup
source (RotoWire-style) and confirm coverage. **Do this first.**

**Phase 1 — Lineup threat score.** For the 9 batters in tonight's lineup, compute
strictly *pre-game*:
- Each batter's recent form (wOBA / OBP / ISO / K%).
- Each batter's performance vs the pitcher's **archetype** — handedness (L/R
  splits), pitch mix (vs high-velo FB, vs breaking-ball-heavy, vs sinkerballers).
  Use *archetype* matching, not batter-vs-this-pitcher (BvP) — BvP samples are too
  small and noisy. The Session 529 MLB pitch-arsenal data enables archetype tags.
- Aggregate the nine into a "lineup threat score" → expected baserunners / runs.

**Phase 2 — Expected-IP / early-hook model.** Predict how deep the starter goes:
inputs = lineup threat score, pitcher recent pitch-count tendency, days rest, and
score-context priors. Output = expected outs / pitch count → expected IP.

**Phase 3 — Integrate into predictions.** Options (test all):
- Lineup-threat + expected-IP as **features** in the CatBoost K regressor
  (`scripts/mlb/training/train_regressor_v2.py`, `pitcher_features` precompute).
- A **two-stage** model: predict expected IP × predict K/9.
- An **early-hook filter/signal** in the MLB BB pipeline (block OVER picks when the
  lineup is dangerous).

**Validation.** Walk-forward replay (`scripts/mlb/training/season_replay.py`); the
bar is improved K MAE and/or MLB BB HR.

### 3.3 Risks / discipline
- **Look-ahead is the #1 hazard** — every batter/lineup feature must be strictly
  pre-game. (See the `bench_under` look-ahead lesson — post-game `starter_flag`
  inflated HR from ~52% to 76%.)
- **Lineup-data reliability** gates everything (Phase 0).
- BvP samples are tiny — archetype matching, not BvP.
- Late scratches: lineups post ~3–4h pre-first-pitch; the `mlb-best-bets-generate-late`
  4:30pm scheduler already exists to catch changes.

---

## 4. State / gotchas for the next session

- **Repo has a large pre-existing uncommitted diff** (~850 files, looks like a mass
  reformat) that predates this work and is unrelated. Commit `60279b20` staged only
  the 14 roadmap files. Leave the rest alone unless the user asks.
- **Nothing is pushed.** `git push origin main` will auto-deploy the changed
  services/CFs — confirm with the user before pushing.
- **P0-4 experiment logs** are in `/tmp/p0-4-runs/` (ephemeral) — re-run if needed.
- **quick_retrain.py date flags:** must pass `--train-start` AND `--train-end`
  together, else they fall through to default (eval window = yesterday). Use
  `--no-production-lines` (eval is hardcoded to `catboost_v9` otherwise).
- Memory updated: `offseason-roadmap-2026-05.md` written; the stale "adding features
  hurts" lore in `MEMORY.md` marked SUPERSEDED.
