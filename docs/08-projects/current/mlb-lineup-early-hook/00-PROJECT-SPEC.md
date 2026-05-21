# MLB Strikeout Prediction — Project Spec

*(Folder `mlb-lineup-early-hook` keeps the original name. Rescoped twice on 2026-05-20
after an 8-agent then a 15-agent review. The project is now broader than lineup
early-hooks, and **fixes the betting machinery before adding model features**.)*

**Created:** 2026-05-20
**Status:** Phase 0 **DONE + VERIFIED**. Plan rescoped fixes-first and reviewed across 4
rounds (2026-05-20). **APPROVED — building.** Stage 1 + no-regret prerequisites underway.
**Origin:** Handoff `docs/09-handoff/2026-05-20-ENGINE-ROADMAP-HANDOFF.md` §3.

---

## 1. Goal & strategic reframe

Improve the profitability of MLB pitcher **strikeout** prop betting. The product:
a CatBoost regressor predicting strikeout count → an OVER-only best-bets pipeline.

**The 15-agent review changed the priority order.** The original plan added model
features to lower strikeout MAE. But the data shows the model is **already at market
accuracy** and the *betting machinery around it* is leaking value:

- Model K MAE **1.827** vs the market closing-line MAE **1.846** — a ~1% edge. The model
  essentially re-derives the line.
- Actionable OVER hit rate is **49.5%** — a coin-flip against the number.
- The win probability is a **hand-tuned constant** `p_over = sigmoid(0.7 × edge)`
  (`catboost_v2_regressor_predictor.py`) — never fit to outcomes. Consequence:
  **edge→HR is non-monotonic** (edge 0.5–1.0 → 54% HR; edge 1.0–1.5 → **44%**).
- The selection layer **loses money**: best-bets pick rank 4 hits 45.5%, rank 5 hits
  42.9% — both under break-even. "Top-5/day" pads thin days with sub-coin-flip picks.
- CLV (closing-line value) **cannot even be measured**: `pitcher_props_closing` is
  ~98% synthetic placeholder rows; the `clv_*` columns are 100% NULL.

**Therefore:** adding features to a mis-calibrated model whose ranks 4–5 lose money will
not move ROI. **Stage 1 fixes the machinery** (calibration, selection/staking,
closing-line capture, validation, monitoring). **Stage 2 adds strikeout features.**
**Stage 3** (conditional) is the original per-batter lineup early-hook model.

---

## 2. Review history

- **8-agent review (2026-05-20)** — descoped the elaborate per-batter opposing-lineup
  model from "the project" to a conditional later stage; corrected the premise (lineup
  quality is a *second-order* driver of early hooks).
- **15-agent review (2026-05-20)** — found the betting machinery leaks more value than
  any feature would add; reprioritized to fixes-first. Confirmed *augment the single
  model* (no new model / ensemble / fleet).
- **25-agent design pass (2026-05-20)** — designed the discovery harness
  (`01-DISCOVERY-HARNESS-SPEC.md`).
- **25-agent review (2026-05-20)** — adopted changes folded into this revision:
  - **Buy, don't build.** Purchase an odds feed instead of building closing-line
    capture (§7.2); source FanGraphs Stuff+ free instead of building a proxy (§8-I).
  - **Add a model-market blend** to Stage 1.1 (§7.1) — theory-backed, ~30 lines.
  - **Reconcile with the prior MLB dead-ends doc** —
    `docs/08-projects/current/mlb-2026-season-strategy/05-DEAD-ENDS.md` already tested
    `opponent K-rate`, `ballpark K-factor`, `is_day_game`, and Quantile loss as NOISE
    or negative. Stage 2 features that resemble these must beat the dead-end baseline
    (§8).
  - **Game-script family added** (§8) — a real ~1.75-K swing the specs missed; needs
    D7 (the empty `oddsa_game_lines`).
  - Verdict on process: the plan is well-vetted; **further review has hit diminishing
    returns — build now.**

---

## 3. Phase 0 — Lineup data capture (DONE + VERIFIED 2026-05-20)

`mlb_raw.mlb_lineup_batters` night-game capture had collapsed to ~0% in 2026 (100% in
2024/2025). Root cause: the `mlb_lineups` scraper ran only 11 am / 1 pm ET (night
lineups post ~3–4 pm ET), compounded by a dedup guard.

**Fixed:** added `mlb-lineups-afternoon` (4 pm ET) + `mlb-lineups-overnight` (3 am ET)
scheduler jobs; `SKIP_DEDUPLICATION = True` on `MlbLineupsProcessor` (commit `eb056db4`);
deployed `mlb-phase2-raw-processors`. Verified: 2026-05-19 went 0 → 15 games / 30 teams.
**Open follow-up:** register `mlb_lineups` in `expected_outputs_planner`.

> Lineup data only matters for **Stage 3**. Stages 1–2 do not depend on it.

---

## 4. Architecture decisions

| Decision | Rationale |
|----------|-----------|
| **Augment the single CatBoost regressor** — no new model, no ensemble, no fleet | MLB *already built* multi-model infra in Jan 2026 (5 predictor classes, shadow tables, registry) and it collapsed back to one model. A fleet needs algorithm diversity MLB's small data can't sustain (one feature table, ~5K starts/season). CatBoost (depth 4, L2=10) is heavily regularized — added features can't "untune" it. K-rate and innings are statistically orthogonal (`CORR ≈ −0.07`), so a two-stage IP×K/9 compose has no shared structure to exploit. |
| **Move to a count-distribution output** | Switch CatBoost loss RMSE → **Poisson** (already a CLI flag in `train_regressor_v2.py`; K counts have variance/mean ≈ 1.25, mildly overdispersed). Then `P(K > line) = 1 − PoissonCDF(floor(line), λ)` — an honest, per-pitcher probability replacing the constant sigmoid. Implemented in Stage 1.5.1. |
| **Keep OVER-only betting** | Confirmed, not assumed: the regressor structurally never projects far below the line, so UNDER has no usable edge spread (walk-forward showed 47–49%). Resolved — not revisited. |

Rejected: separate early-hook model, ensemble, two-stage IP×K/9, direct OVER/UNDER
classifier (couples the model to today's line distribution; an abandoned
`train_pitcher_strikeouts_classifier.py` already exists).

---

## 5. Data & infrastructure corrections (prerequisites)

| # | Correction | Notes |
|---|-----------|-------|
| D1 | Repoint `mlb_game_feed` → `mlb_game_feed_pitches` | `mlb_game_feed` is empty; `_pitches` is the real table (~920K rows). |
| D2 | Build a **static pitcher-handedness lookup** | Easy — `mlb_raw.mlb_pitcher_stats.throws` is **100% populated for 2024 & 2025** (the earlier "50% null" was a 2022–23 artifact). One reference table; no scraper needed. Unblocks 6.A v2. |
| D3 | Resolve arsenal-view populated/empty discrepancy | Two audits disagreed (0 vs ~3.7K rows). Verify before Stage 2's Stuff+/archetype work. |
| D4 | PA/pitch features are **2025+ and land D+1** | `mlb_game_feed_pitches` & `statcast_pitcher_daily` land ~07:15 / 12:05 UTC the next day. Most recent usable game for a date-D prediction is D−1 — leak-free *and* available before the 12:55 pm ET export. Add a partition-presence gate. |
| D5 | Add a **morning umpire-assignment scrape** | The `mlb_umpire_assignments` scraper runs 20:30 UTC — *after* both exports. HP umps are published ~1 day pre-game; the data exists, the schedule is wrong. Add a ~14:00 UTC scheduler. Gates 6.F. |
| D6 | Closing lines | Superseded — **buy an odds feed** (§7.2) rather than fix `pitcher_props_closing` capture. |
| D7 | Fix the empty `oddsa_game_lines` table | 0 rows; the scraper writes nothing. Backfill `pitcher_game_summary.game_total_line` / `team_implied_runs` (dead columns). Gates feature K (game script). |

---

## 6. Look-ahead discipline (NON-NEGOTIABLE)

Reference lesson: `bench_under` used post-game data and inflated hit rate ~52% → 76%.

1. Every feature uses only games **strictly before `game_date`** (`< game_date`; window
   functions `1 PRECEDING`, never `CURRENT ROW`). Enforce as a CI assertion.
2. **Explicit pre-game allowlist for `batter_game_summary`** — only `*_last_N`,
   `season_*`, `days_since_last_game`, `games_last_30_days`. The target game's actuals,
   the confirmed post-game `batting_order`, and `vs_pitcher_*` (BvP) are banned.
3. Ban `_latest` arsenal tables in training (they stamp end-of-season mix on April
   games); use `_season` windowed.
4. **Correct leakage test:** point-in-time determinism — a feature for date D must be
   byte-identical whether computed on D or recomputed 30 days later.
5. 6.D line-movement: same-day features come from `oddsa_pitcher_props` only;
   `pitcher_props_closing` materializes D+1 and is a `< D` historical feature only.

---

## 7. Stage 1 — Fix the betting machinery (THE NEXT BUILD)

The highest-EV work. None of it requires new model features.

### 7.1 Calibration & probabilistic output
- Switch training loss RMSE → **Poisson** in `train_regressor_v2.py` (CLI flag exists;
  A/B via `season_replay.py`).
- Replace the constant `sigmoid(0.7 × edge)` with `P(K > line) = 1 − PoissonCDF(floor(line), λ)`,
  λ = predicted K. ~15 lines in the predictor; `edge = λ − line` is unchanged so the
  existing pipeline still runs.
- **Re-rank and select bets on calibrated P(over) vs book-implied probability**, not raw
  `edge` — this directly fixes the non-monotonic edge→HR collapse (currently band-aided
  by a `MAX_EDGE = 1.25` cap).
- Optional second layer: isotonic calibration (a prototype exists at
  `scripts/mlb/isotonic_calibration_analysis.py`, never wired in), fit walk-forward,
  separate OVER/UNDER and home/away.
- Port the NBA Brier-score emitter so `mlb_predictions.model_performance_daily.brier_score_*`
  (columns exist, 100% NULL) is populated.
- **Model–market blend.** The model MAE (1.827) ≈ market MAE (1.846) and they make
  decorrelated errors — a walk-forward-fit blend `blended = w·model + (1−w)·line`
  provably lowers MAE (Bates–Granger). One scalar `w` fit per rolling window, bounded
  `w ≥ 0.3`; recompute `edge` from the blend. ~30 lines; cannot overfit at 5K starts.
  It also mechanically suppresses small-divergence picks — i.e. it *is* the §7.3
  quality gate, derived from theory.

### 7.2 Closing-line capture & CLV — BUY a feed (revised)
The 25-agent review's build-vs-buy finding: do **not** build closing-line capture.
- **Buy an odds feed** with real closing lines + finer snapshots (SportsGameOdds or The
  Odds API, ~$99–200/mo). This replaces the entire D6 build, unblocks CLV, *and* makes
  the §8 line-pattern features testable. Highest ROI per dollar in the project.
- Once the feed lands real closing lines, populate
  `prediction_accuracy.clv_raw / clv_directional / clv_quality_flag` (100% NULL today)
  — the prerequisite for the §7.4 CLV gate.
- Interim, before the subscription: capture a same-day final snapshot at first pitch
  from the existing `oddsa_pitcher_props` (a scheduler, not a build).

### 7.3 Betting selection & staking
- Replace the fixed **top-5/day** with an **absolute quality gate** (calibrated-P /
  edge threshold validated by bucket HR); let daily pick count flex. Ranks 4–5 hit
  45.5% / 42.9% — the cap is buying losers, and it binds only 8 of 29 days anyway.
- **Stake by calibrated bucket HR, not raw edge** (edge is non-monotonic). Flatten the
  "ultra" 2u overlay to 1u until it clears N ≥ 30 at a validated HR (currently 5–10 at
  50%, the worst bucket).
- Add **per-archetype edge thresholds** — high-K/high-variance starters (SD ≈ 2.7) need
  a wider edge than low-variance contact pitchers (SD ≈ 2.2). A flat 0.75/1.25 is
  mis-calibrated across pitcher types.
- After any Stage 2 retrain, **re-fit all thresholds** on the new calibration.

### 7.4 Validation framework (used by every later stage)
- **Primary gate = paired-bootstrap MAE.** Use all ~5,000 pitcher-starts (not the ~500
  graded best-bets), paired with/without the change, bootstrap 95% CI lower bound > 0.
  Multi-season where data allows (line history goes back to 2022; PA features 2025+).
- **CLV gate** (once §7.2 lands): positive CLV at N ≥ 150.
- **Calibration gate:** Brier score / reliability must not regress.
- **HR is a directional sanity check only, NOT a gate.** At ~500 graded picks/season the
  minimum detectable HR effect is ~+9pp — a realistic +1–2pp gain is invisible. Require
  HR *not to regress*; never gate on an HR delta from one season.
- Pre-register thresholds before running (avoids with/without fishing).

### 7.5 Monitoring
- Deploy `mlb_freshness_checker.py` (exists, never scheduled); extend it to the Stage 2
  source tables (`mlb_game_feed_pitches`, `statcast_pitcher_daily`,
  `mlb_umpire_assignments`, `oddsa_pitcher_props`).
- Populate `mlb_predictions.feature_coverage_monitoring` (table exists, empty, no
  writers) with per-feature non-NULL rates; alert when a feature's coverage drops
  sharply. "Degrade gracefully (CatBoost NaN-native)" hides silent signal loss.
- MLB retrain is **manual** today (`weekly-retrain` CF is NBA-only). Decide whether to
  add an MLB auto-retrain with a governance gate that includes a feature-coverage check.

---

## 8. Stage 2 — Strikeout features

Built **after Stage 1**, only on the now-calibrated model. All features land in
`mlb_analytics.pitcher_game_summary` (the table the worker and `train_regressor_v2.py`
actually read — **not** a precompute table; a precompute table the worker never queries
is invisible, which is why `lineup_k_analysis` was vapor). Fill the existing dead
`f26_lineup_k_vs_hand` / `f33_lineup_weak_spots` columns where applicable.

**Apply empirical-Bayes shrinkage** to every rolling rate feature below (blend the
pitcher/team rate toward league mean, weighted by sample size) — standard practice
(ZiPS/Steamer/ATC) and especially important for the thin 2025+/early-season windows.

### Build order (waves — do NOT ship all at once)

**Wave 1 — fast-feedback slice** (low effort, populated tables, no PA pipeline):
- **A. Opponent K-rate vs starter handedness** — PA-weighted K% of the opponent's
  likely 9 batters (not raw team average), split by the starter's hand (D2). Also emit
  a **tail/dispersion** variant (count of opposing batters with K% > threshold) — that
  variant, not the mean, is the §9 gate for Stage 3.
- **C. Velocity-drop / spin** — *two* features: (1) last-start FB-velo z-score vs
  trailing-10-start mean/SD; (2) within-start early-vs-late FB-velo decline. Fastball
  only. From `statcast_pitcher_daily` (2024+) and `mlb_game_feed_pitches` (2025+).
- **D. Line movement** — open→current line delta + cross-book disagreement from
  `oddsa_pitcher_props`. Keep its influence bounded (don't let the model become a
  line-follower); treat the closing line as a `< D` historical/CLV feature only.

**Wave 2 — shared PA pipeline** from `mlb_game_feed_pitches`:
- **B. 2-strike putaway rate** = K / (PA reaching 2 strikes) — *not* whiff-per-pitch
  (count-confounded). Trailing-10-start, EB-shrunk.
- **E. Times-through-order** — `expected_tto_penalty = P(reach TTO3) × (TTO1 K% − TTO3 K%)`,
  a per-pitcher pre-game scalar.
- **H. CSW%** (called-strike + whiff rate) — the best single-number K predictor per
  public research; rolling, EB-shrunk. Same table, near-zero extra effort.

**Wave 3 — higher effort:**
- **F. Umpire strike-zone tendency** — per-ump rolling called-strike / K rate from
  `mlb_game_feed_pitches` joined to assignments (`mlb_umpire_stats` is empty/broken).
  Trailing-50-start window, strong EB shrink (~92 umps, ~15–20 starts each). **Needs D5
  (morning scrape)** or it's unusable for the main export.
- **I. Stuff+ pitch-quality — SOURCE, don't build.** FanGraphs publishes Stuff+ /
  Pitching+ / PitchingBot grades free; pull rolling point-in-time values via
  `pybaseball`. This kills the proxy-build (the spec's previously-flagged biggest
  effort). Use windowed values, not season-to-date leaderboard snapshots (§6.3).

**Independent (any wave):**
- **G. Opener / role flag + OVER suppression** — 5.6–7% of starts are <3 IP (openers);
  `prior_2_starts_both_short` predicts the next short start 82.7% of the time. Add the
  flag as a feature **and** suppress likely openers from OVER best-bets (their K line
  ~1–2 breaks the edge math). A `ml/signals/mlb/` filter. Low effort, pre-game-safe.
- **J. Environment** — wire existing park-K factors (`mlb_reference.ballpark_k_factors`,
  `pitcher_game_summary.ballpark_k_factor`/`day_night_k_diff` — verify they're in
  `FEATURE_COLS`; if computed-but-unused that's a free win) + a one-time Open-Meteo
  historical weather backfill (free, ERA5, keyed on `game_date` + ballpark lat/long).
  Weather is a modest secondary signal — temperature/air-density only, skip wind.

**K. Game script** *(needs D7)* — `team_implied_runs` (game total × moneyline-implied
win prob), `game_total_line`, and `opp_starter_season_k9`. A starter's K total swings
~1.75 across game scripts (losing big → chased early; the realized split is monotone).
The pre-game proxy is the game lines. **D7: fix the empty `oddsa_game_lines` table** and
backfill `pitcher_game_summary.game_total_line` / `team_implied_runs` (dead columns
today). Model features, not signals. Score against the model residual — partly collinear
with opener flags and opponent K-rate.

**Interaction features** (explicit ratio/product terms — help on small N):
pitcher K% × opponent lineup K%; putaway rate × opponent chase rate; velo-drop ×
expected_tto_penalty.

**Reconcile with prior dead-ends.** `mlb-2026-season-strategy/05-DEAD-ENDS.md` tested
`opponent K-rate`, `ballpark K-factor`, and `is_day_game` as NOISE. Features A and J
resemble these — they ship **only** as the sharper variants (A = PA-weighted,
handedness-split, dispersion; J = elevation/dome, not raw day flag) and must beat the
dead-end baseline in the §7.4 gate, or they don't ship. The harness dead-ends ledger is
pre-seeded from that doc.

Each wave is validated independently through the §7.4 framework. Keep only what clears.

---

## 9. Stage 3 — CONDITIONAL: per-batter lineup early-hook model

Build **only if** the §8 feature **A tail/dispersion variant** shows real cross-season
signal. (Gating on a team-*average* would be invalid — the mean is collinear with the
existing `opponent_team_k_rate` feature and washes out the lineup-composition signal a
per-batter model exists to capture.)

If pursued: reframed as a **pitch-count / damage / times-through-order model** with
lineup-threat as one input (not a "lineup → IP" pipeline); batter inputs are
K%/whiff%/chase, not wOBA; **scraper-first** (RotoWire MLB for projected lineups);
projected-lineup accuracy measured against captured confirmed lineups (Phase 0).
Note: history-derived projected lineups are only ~39% accurate on exact batting slot —
a real constraint on this stage.

---

## 10. Integration path

1. Stage 2 features → `pitcher_game_summary` via `pitcher_game_summary_processor.py`.
2. Add columns to `FEATURE_COLS` + `load_data()` SQL in `train_regressor_v2.py`.
3. **Deployment order matters:** upload + register + shadow the new model artifact in
   GCS *first*, then merge the worker `FEATURE_COLS` change. Never the reverse — the MLB
   worker auto-deploys (`cloudbuild-mlb-worker.yaml`), so a worker requesting features a
   deployed model lacks (or vice versa) breaks predictions.
4. Stage 3 early-hook logic ships as a `ml/signals/mlb/` filter (fits OVER-only).
5. Any precompute table must have all three of: created table, registered processor +
   trigger, verified Pub/Sub subscription — or it repeats the `lineup_k_analysis` fate.

---

## 11. Deferred / parked

- Two-stage IP×K/9 model — rejected (compounds error; K-rate ⊥ IP).
- Per-segment models — segments too thin; use segment-interaction features + per-segment
  edge thresholds (§7.3) instead.
- Catcher framing — `catcher_framing` table empty.
- Wind / fine humidity — needs stadium-orientation modeling; more an HR than K signal.
- Model fleet / ensemble — revisit only after the feature well is exhausted.

---

## 12. Open decisions — RESOLVED (2026-05-20)

1. **MLB auto-retrain** — **keep manual through Stage 1–2.** An auto-retrain CF that
   re-fits a mis-calibrated model just industrializes a leak; the MLB governance gate
   doesn't exist yet. Build the MLB auto-retrain CF *last*, as a Stage 1.5 item, gated
   behind the calibration + feature-coverage checks.
2. **Closing-line fix scope** — **superseded.** Buy an odds feed (§7.2) rather than
   build/own the capture. CLV-as-a-gate stays in the project but is not on the critical
   path — ship Stage 1.1/1.3/1.4 without waiting on it.
3. **Folder rename** — **yes, rename** the project folder to `mlb-strikeout-model` (the
   current name describes only the conditional Stage 3). Cosmetic; do it with the next
   commit, leave a stub at the old path.

---

## 13. Sequencing & effort

| Step | Effort | Status / gating |
|------|--------|-----------------|
| Phase 0 — lineup capture | Low | **DONE + VERIFIED** |
| D1–D6 data/infra corrections | Low–Med | with Stage 1 (D5 gates 6.F; D2 gates 6.A v2) |
| **Stage 1.1 — Poisson loss + real P(over) + Brier** | Med | **next, on approval** |
| **Stage 1.2 — closing-line capture + CLV** | Med | next |
| **Stage 1.3 — selection/staking fix** | Low–Med | next |
| Stage 1.4 — validation framework | Low | enables all later gates |
| Stage 1.5 — monitoring (freshness, feature-coverage) | Low–Med | next |
| Stage 2 Wave 1 — features A, C, D | Med | after Stage 1 |
| Stage 2 Wave 2 — features B, E, H (+ shared PA pipeline) | Med–High | after Wave 1 gate |
| Stage 2 Wave 3 — features F, I | High | after D3/D5 |
| Stage 2 — features G, J | Low–Med | parallel |
| Stage 3 — per-batter lineup model | High | **conditional** on feature A tail-variant clearing the gate |

**Approved 2026-05-20 — building.** First: no-regret prerequisites (D1, D2, register
`mlb_lineups`, deploy `mlb_freshness_checker`) + Stage 1.1.
