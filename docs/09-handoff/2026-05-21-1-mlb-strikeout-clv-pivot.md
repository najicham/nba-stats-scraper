# Handoff — MLB Pitcher-Strikeout: Leak Fix + Validation + Strategic Pivot

**Date:** 2026-05-21 · **Session:** continues `2026-05-20-3-mlb-strikeout-stage-1.1.md`
**Project:** `docs/08-projects/current/mlb-lineup-early-hook/`

---

## TL;DR

A full **leak-free validation** of the pitcher-strikeout betting system is complete. It
found and fixed a critical look-ahead leak, built a durable leak-free harness, and ran
extensive backtests reviewed across ~65 agents. The verdict overturned the project's
founding thesis:

> The de-leaked model has **no robust edge over the market**. The betting machinery has
> **no profit leak**. The "28.6% hit rate" scare was a 14-day-window artifact (real
> cross-season OVER HR ≈ 55-59%, thin but not zero). Two structural-edge hypotheses were
> tested and **both failed pre-registered bars**.

**12 commits this session — all pushed to `main` and auto-deployed.** No service behavior
changed (the leak fix is correctness-only code; the Poisson `p_over`/blend ship inert).

---

## What was done

### 1. FanGraphs look-ahead leak — found and fixed
`mlb_raw.fangraphs_pitcher_season_stats` holds only **post-season** snapshots (all dated
2026-01-15 / 2026-03-09). Nine files joined it `season_year = EXTRACT(YEAR FROM game_date)`,
leaking completed-season FIP/swstr/csw into mid-season games — ~23% of model feature
importance (`f72_fip` was the #2 feature). Fixed: all 9 files switched to a **prior-season
join** (`season_year = year - 1`); `mlb_analytics.pitcher_game_summary` surgically
backfilled (`scripts/mlb/backfill_pitcher_game_summary_leakfix.sql`, idempotent).
Commits `a490ddc2`, `e1c7a667`.

### 2. Leak-free validation harness — the durable asset
- `scripts/mlb/training/season_replay.py` — rewired walk-forward backtest; imports
  `poisson_p_over` + `fit_w_nested_holdout`, removed the duplicated `SIGMOID_SCALE`, added
  `--blend-weight`/`--no-blend`/`--rescue-min-edge`, `raw_pred_k` output, April-coverage
  parity.
- `scripts/mlb/training/calibration_report.py` (NEW) — scores old sigmoid vs Poisson
  `p_over` (Brier/ECE/monotonicity/pitcher-clustered bootstrap); has `--self-test`.
- `scripts/mlb/clv_report.py` (NEW) — closing-line-value report per pick.
- `train_regressor_v2.py` — `fit_w_nested_holdout` (nested holdout fixes the double-use of
  the 14-day window for both governance and `w`-fitting).

### 3. Validation verdict (2 seasons × 5 seeds, 20-agent reviewed)
- **The de-leaked model has no real edge over the market** — 2024 model MAE 1.787 is
  *worse* than the line (1.763); 2025 barely wins (1.710 vs 1.722). The handoff's "model
  matches market 1.83 vs 1.85" was the *leaked* model.
- **No machinery profit leak** — Poisson `p_over` ≈ the old sigmoid (Brier tied within
  noise); the model-market blend *hurts* (do not activate it — keep `w=1.0`); signal
  rescue is marginal/EV-negative; per-signal pruning yields nothing; UNDER is a build with
  no evidence it pays.
- **Backtest +3-7% ROI is optimistic** — `bp_pitcher_props` aggregates odds across books
  and the `innings_pitched≥3` filter is look-ahead. Realistic ≈ breakeven.
- **The "28.6% HR" scare was noise** — a ~6-15 record on one 14-day window. Real
  cross-season OVER HR at edge≥0.75 ≈ 55-59% (N>1,200/side), thin but above breakeven.

### 4. Two structural-edge hypotheses tested — both FAILED pre-registered bars
- **Agent 13's mid/high-K OVER niche** — re-tested leak-free (tier = pitcher's prior-starts
  K-avg, not full-sample career). The claimed 62-65% niche collapsed to 53.7% (2024 47%).
  "Stable both seasons" was a look-ahead artifact.
- **Clean opponent-lineup feature** — per-start avg season K-rate of the actual 9 opposing
  batters. Pre-reg bar: T2 |r|≥0.06 AND T1≠0. Result: T0=+0.155, T1=+0.078, **T2=+0.040
  (FAIL)**. The feature would marginally improve model *accuracy* but the market already
  prices opponent strength → no betting edge. (`/tmp/opp_lineup_test.py`, not committed.)

---

## The strategic pivot

The founding thesis ("model matches the market; the machinery leaks the value; fix the
machinery, add features second") was built on the *leaked* model and is refuted. You
cannot out-predict an efficient, heavily-modeled market with public data. The project
pivots from **out-modeling the market** to **finding an edge that can structurally exist**,
judged by the only honest scoreboard: **closing-line value (CLV)**.

Full revised plan: `docs/08-projects/current/mlb-lineup-early-hook/02-EXECUTION-PLAN.md`.

---

## Commits (all on `main`, auto-deployed)

`a490ddc2` leak fix · `22443c91` Stage 1.1 Poisson/blend · `8b074f63` leak-free blend
fitting · `9d1494ed` replay/production parity · `13d0185f` calibration report ·
`7bead276` harness pre-run fixes · `86e92d61`/`d4eca515` Stage 1.4 findings ·
`d5f71537` `--rescue-min-edge` · `e1c7a667` backfill SQL · `f010da96` execution-plan
rewrite · `22d5cf0a` CLV report tool + Phase B correction.

---

## Open decisions for the owner

1. **Pause MLB best-bets output?** The live MLB worker serves a *leak-trained* `.cbm` on
   *de-leaked* features (train/serve skew). Recommended op action: set
   `nba_orchestration.halt_state` reason=`manual` until a clean model exists. **Do NOT
   roll back the worker** — the leak fix is code on `main`, in every revision; rollback is
   the wrong lever. This needs explicit owner sign-off (it stops production output).
2. **Continue vs wind down.** Every machinery/signal/feature lever tested this session
   came up empty or breakeven. The two remaining honest threads are below.
3. **If continuing — the two threads (from the execution plan):**
   - **Fix the closing-line capture** so CLV becomes measurable. `oddsa_pitcher_props`
     snapshots intraday but only ~2.6% of game-pitchers get a true ≤30-min-pre-pitch
     snapshot. This is a scheduling fix ($0), not a new subscription. CLV is the real
     arbiter — without it, every ROI number is unreliable.
   - **C1 — the information-speed edge (lineup early-hook).** The project's namesake:
     when confirmed lineups/scratches/weather land before the book moves, is there CLV in
     that window? Phase 0 already built the lineup-capture infra.

---

## Discipline note for the next session

Every test this session got a **pre-registered pass/fail bar set before it ran**. Two
structural hypotheses (the niche, the opponent-lineup feature) failed those bars cleanly.
Do not re-litigate failed tests or start a new model-feature test — adding *public*
features to a model on an efficient market cannot create edge. The next move is the
owner's strategic decision (above), then — if continuing — fix the closing-line capture
so CLV can finally be measured.
