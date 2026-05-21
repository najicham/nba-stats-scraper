# Handoff — 2026-05-20 — MLB Strikeout Project: Phase 0 + Planning + Build Start

**Branch:** `main`. All work pushed (through `b03b228d`).
**Project folder:** `docs/08-projects/current/mlb-lineup-early-hook/`
(rename to `mlb-strikeout-model` is an approved-but-not-yet-done cosmetic step.)

---

## 1. What this session did

1. **Pushed the prior session's work** — the engine-roadmap commits (`60279b20`,
   `c7ed62dd`) were committed-but-unpushed; pushed them.

2. **Fixed MLB lineup data capture (Phase 0).** `mlb_raw.mlb_lineup_batters` night-game
   coverage had collapsed to ~0% in 2026 (100% in 2024/25). Root cause: the `mlb_lineups`
   scraper ran only 11am/1pm ET (night lineups post ~3–4pm ET), and a `run_history_mixin`
   dedup guard let the first scrape "win" the date.
   - Added Cloud Scheduler jobs `mlb-lineups-afternoon` (4pm ET) and
     `mlb-lineups-overnight` (3am ET, scrapes `YESTERDAY`); recorded in
     `bin/schedulers/setup_mlb_schedulers.sh`.
   - Fixed the dedup guard — `SKIP_DEDUPLICATION = True` on `MlbLineupsProcessor`
     (commit `eb056db4`); deployed `mlb-phase2-raw-processors` via Cloud Build.
   - **Verified end-to-end:** re-fired the overnight job → 2026-05-19 went 0 → 15 games
     / 30 teams / 325 batter rows.

3. **Planned the MLB strikeout project** across four review rounds (8 + 15 + 25 + 25
   agents). Produced two specs and an execution plan in the project folder:
   - `00-PROJECT-SPEC.md` — the strikeout model plan. Key finding: the model already
     matches the market (MAE 1.83 vs 1.85); the **betting machinery** leaks the value
     (the win-probability is a hand-tuned constant `sigmoid(0.7×edge)` never fit to
     outcomes → edge→hit-rate is non-monotonic; the selection layer buys losers at pick
     ranks 4–5; CLV is unmeasurable — closing lines are 98% synthetic). **Fixes-first:**
     Stage 1 fixes the machinery, Stage 2 adds features, Stage 3 (per-batter lineup
     model) is effectively retired.
   - `01-DISCOVERY-HARNESS-SPEC.md` — a hypothesis-discovery harness for rapidly testing
     candidate features. The **similarity engine was cut** — a separability test showed
     MLB K-rate is ~99.5% multiplicatively separable, so an archetype-matchup grid would
     yield ~0.2 K of signal. The MVH is one ~300–400-line script.
   - `02-EXECUTION-PLAN.md` — the single ordered build checklist. **Start here.**

4. **Started the build (Wave 0 no-regret items):**
   - Registered `mlb_lineups` in `expected_outputs_planner` (`b03b228d`) — closes the
     Phase 0 follow-up; lineup-coverage regressions now trigger gap detection.
   - Built `mlb_reference.pitcher_handedness` (1,113 pitchers, L/R/S) — a static lookup,
     unblocks Stage 2 feature A. Note: 475 inactive 2022–23-only pitchers are NULL
     (acceptable — only active pitchers matter).

---

## 2. Key decisions made (resolved in the specs)

- **Augment the single CatBoost model** — no new model, ensemble, or fleet (MLB tried
  multi-model in Jan 2026; it collapsed).
- **Buy an odds feed** (~$99–200/mo) instead of building closing-line capture — needs an
  owner purchase decision.
- **Source FanGraphs Stuff+ free** via `pybaseball` instead of building a proxy.
- **Cut the similarity/archetype engine** (separability finding).
- **Validate on MAE over ~5K starts**, not hit-rate over ~500 picks (HR is statistically
  underpowered at MLB volume).
- MLB auto-retrain stays **manual** through Stage 1–2.

---

## 3. What's next (see `02-EXECUTION-PLAN.md`)

Immediate, in order:
1. Finish Wave 0 — deploy `mlb_freshness_checker`, D1 repoint, folder rename.
2. **Stage 1.1 — Poisson loss + real `P(over)` + model-market blend.** The first
   shippable result (~1 week incl. Wave 0). The Poisson loss is already a CLI flag in
   `train_regressor_v2.py`; the predictor change (`P(K>line) = 1 − PoissonCDF`) is ~15
   lines in `catboost_v2_regressor_predictor.py`.
3. Stage 1.4 validation framework → Stage 1.3 selection fix → Stage 1.2 CLV.

---

## 4. State / gotchas

- The repo has a large **pre-existing uncommitted diff** (~850 reformatted files) and
  many untracked files — both predate this work. Left untouched. Only this session's
  specific files were committed.
- The dedup-guard fix (`SKIP_DEDUPLICATION`) also dropped the Pub/Sub-redelivery
  concurrency guard for `MlbLineupsProcessor` — acceptable (idempotent `MERGE_UPDATE`,
  ~90s processing).
- `mlb-phase2-raw-processors` deploys via `cloudbuild-nba-phase2.yaml` (bundled with
  nba-phase2 — it IS auto-deployed, contrary to first assumption).
- The stale deploy script `bin/raw/deploy/mlb/deploy_mlb_processors.sh` references a
  non-existent Dockerfile path — use the Cloud Build path instead.
