# Session 243 Continuation Prompt

Copy everything below the line into a new chat.

---

Read the handoff doc and project results first, then continue the V12/V13 experiment suite:

```
cat docs/09-handoff/2026-02-13-SESSION-243-HANDOFF.md
cat docs/08-projects/current/mean-reversion-analysis/05-SESSION-243-V12-V13-EXPERIMENT-RESULTS.md
```

## Context

Session 243 ran 11 model experiments (8 V12, 3 V13) and 5 SQL analyses. Key findings:

- **V12 RSM50 is the best config** (57.1% edge 3+ HR, OVER 64.3%, UNDER 52.4%, MAE 4.82) using `--feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise`
- **FG% features got 0% importance in CatBoost** despite SQL showing 60.8% OVER rate after cold shooting — the signal is about direction not magnitude, so CatBoost can't use it for MAE prediction
- **`line_vs_season_avg` leaks vegas info** in no-vegas mode (5-13% importance). It's computed from `vegas_points_line - season_avg`. Needs to be excluded.
- **Dead features:** `breakout_flag, playoff_game, spread_magnitude, teammate_usage_available, multi_book_line_std` — always 0% importance
- **Continuation filter hurts** — suppressed OVER bets on under streaks actually hit 69.1%
- **Game total 230-234 OVER: 80% HR** (n=30, needs validation)
- All experiments: train Nov 2 - Jan 31, eval Feb 1-12, no date overlap

V13 contract (60 features, 56 no-vegas) and `augment_v13_features()` are already implemented in `shared/ml/feature_contract.py` and `ml/experiments/quick_retrain.py`.

## What to Do

### 1. More V12 RSM50 Variants

RSM50 won but we only tested one RSM value. Try:

- **RSM50 + exclude `line_vs_season_avg`** (remove the vegas leak — this is high priority, the current winner may be inflated by vegas info)
- **RSM30 and RSM70** to find the optimal subsampling rate
- **RSM50 + Huber loss** (Huber generated the most edge 3+ samples at 57, RSM50 had best HR — combine them)
- **RSM50 + quantile alpha 0.47** (slight UNDER bias aligned with continuation effect)

### 2. New Feature Ideas to Implement and Test

The FG% signal is real but needs different feature engineering to give CatBoost something it can use:

**A. Personalized FG% Z-Score:** `fg_cold_z_score = (fg_pct_last_3 - season_fg_pct) / season_fg_std` — captures "cold for THIS player" which might be more predictive than absolute thresholds

**B. Volume-Adjusted Expected Points:** `expected_pts_from_shooting = fg_pct_last_3 * fga_last_3 * 2 + three_pct_last_3 * tpa_last_3` — converts FG% into expected points, closer to what CatBoost needs

**C. FG% Acceleration:** `fg_pct_last_3 - fg_pct_last_5` — is shooting getting worse or better?

**D. Fatigue-Cold Interaction:** `minutes_load_last_7d * (1 - fg_pct_last_3)` — high minutes + bad shooting

**E. 3PT% Variance:** `three_pct_std_last_5` — captures shooting inconsistency

To add these: update `shared/ml/feature_contract.py` with a V14 contract, add `augment_v14_features()` to `quick_retrain.py`, wire it up like V13 was wired.

### 3. Post-Prediction Rule Layer

Since FG% works as a directional signal but not a model feature, test rule-based filters AFTER prediction:
- Filter 1: OVER predictions where player is FG% cold (<40% L2) AND under streak 2+ — what's the HR?
- Filter 2: UNDER predictions where player is FG% hot (>50% L2) — what's the HR?
- Filter 3: OVER predictions in game total 230-234 — validate the 80% signal across more dates

### 4. SQL Explorations

Run more SQL analyses to discover new signals before adding features:
- Does 3PT% cold streak predict differently than overall FG% cold?
- Does free throw rate (FTA/FGA) predict anything? (players who get to the line more are less dependent on shooting)
- Does the FG% cold signal vary by home/away?
- Is the game total 230-234 OVER signal stable month-over-month or was it one hot week?

## Schema Reminders

- `prediction_accuracy`: `line_value` (not prop_line), `actual_points` (not actual_stat), no `stat_type` column
- `nbac_gamebook_player_stats`: `minutes_decimal` (not minutes_played), has `field_goals_made/attempted`, `three_pointers_made/attempted`
- `player_game_summary`: has `minutes_played`, `points`, `usage_rate`

## Approach

Use the DOC procedure — save results to `docs/08-projects/current/mean-reversion-analysis/`. Run experiments in parallel where possible. Present results in decision matrices. Check governance gates (60% edge 3+ HR, 50+ samples, directional balance, vegas bias +/-1.5, tier bias +/-5).
