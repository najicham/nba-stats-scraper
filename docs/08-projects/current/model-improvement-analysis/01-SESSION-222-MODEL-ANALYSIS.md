# Session 222: Model Decay Analysis & Experiment Roadmap

**Date:** 2026-02-12
**Session:** 222
**Status:** Research complete, actionable experiment plan ready

## Executive Summary

The champion model (`catboost_v9`) has decayed from 71.2% to 39.9% edge 3+ hit rate over 35 days. A fresh retrain with Q43 quantile failed governance gates (51.4% HR, UNDER bias, insufficient sample). After analyzing 96 prior experiments, per-player performance, shadow model behavior, and the full feature set, this document identifies **what's broken**, **why retrains fail**, and **5 concrete experiments** to try next.

---

## Part 1: What's Wrong With the Current Model

### 1.1 The Decay Timeline

| Week | Edge 3+ HR | MAE | Vegas Bias | Status |
|------|-----------|-----|------------|--------|
| Jan 4-10 | 58.8% | 4.64 | +0.01 | Profitable |
| Jan 11-17 | **71.2%** | 5.08 | +0.78 | Peak performance |
| Jan 18-24 | 66.7% | 4.64 | -0.05 | Declining |
| Jan 25-31 | 55.4% | 4.80 | -0.20 | Below peak |
| Feb 1-7 | **37.6%** | 5.69 | -0.43 | Below breakeven |
| Feb 8-11 | **39.0%** | 4.91 | +0.21 | Still losing |

The decay follows a predictable 3-week lifecycle: peak at 2-3 weeks of staleness, then rapid decline. This is the **retrain paradox** — staleness creates the betting edge, but too much staleness kills accuracy.

### 1.2 The UNDER Bias Problem

The model's decay is **not uniform** — it's concentrated in UNDER predictions:

| Direction | Total Picks | Edge 3+ Picks | Edge 3+ HR | Status |
|-----------|-------------|---------------|-----------|--------|
| OVER | 264 | 80 | **47.5%** | Near breakeven |
| UNDER | 437 | 103 | **34.0%** | Catastrophic |

The model generates 60% more UNDER picks than OVER, and UNDER is where all the losses come from.

### 1.3 Tier × Direction Breakdown (The Smoking Gun)

| Tier | OVER HR (edge 3+) | UNDER HR (edge 3+) | UNDER Count |
|------|-------------------|---------------------|-------------|
| Stars (25+) | **62.5%** (5/8) | **50.0%** (6/12) | 12 |
| Starters (15-24) | 31.8% (7/22) | 40.0% (20/50) | 50 |
| Role (5-14) | **51.0%** (25/49) | **22.0%** (9/41) | 41 |
| Bench (<5) | 100% (1/1) | N/A | 0 |

**Key findings:**
- **Role Player UNDER is the disaster zone**: 22.0% HR. The model systematically predicts role players will score under their line, but they keep going over.
- **Stars OVER is the best bet**: 62.5% HR. The model correctly identifies when stars exceed their line.
- **Starters OVER is also bad**: 31.8% HR. Model over-predicts starters but they fall short.

### 1.4 Individual Player Failures

Players the model is consistently wrong about (0% HR, edge 3+):
- **Trey Murphy III**: 0/6, all UNDER, avg edge 9.6 — model massively under-predicts him
- **Jabari Smith Jr**: 0/5, all UNDER, avg edge 5.5
- **Jaren Jackson Jr**: 0/5, all UNDER, avg edge 6.3
- **Kobe Sanders**: 0/3, all UNDER

Players the model gets right (66.7%+ HR):
- **Joel Embiid**: 2/3, all OVER — model correctly predicts star upside
- **Donovan Mitchell**: 2/3, mixed directions
- **Jarrett Allen**: 2/3, all OVER
- **Julius Randle**: 2/3, all UNDER

**Pattern**: Failures are concentrated in UNDER bets on mid-tier players. Successes are in OVER bets on stars and accurate UNDER calls on select veterans.

---

## Part 2: Why Retrains Fail (96 Experiments, 5 Failure Modes)

### 2.1 The Retrain Paradox (Core Problem)

The paradox, proven across 7 architectures × 2 evaluation windows (Session 183):

| Training Recency | Avg Edge 3+ Picks | Avg HR 3+ |
|------------------|-------------------|-----------|
| Stale (Dec 31 train, Jan eval) | 178 | **77.6%** |
| Fresh (Jan 31 train, Feb eval) | 16 | **43.4%** |

**Mechanism**: The model's #1 and #2 features are `vegas_points_line` (29-36% importance) and `vegas_opening_line` (14-17%). Together, Vegas is 43-53% of the model. A stale model's predictions drift from current Vegas lines → this drift IS the betting edge. A fresh retrain eliminates this drift → no edge → no profit.

### 2.2 Five Identified Failure Modes

| # | Failure Mode | Sessions | Status |
|---|-------------|----------|--------|
| 1 | **Vegas Tracking** — fresh model tracks Vegas too closely, generates 0 edge picks | 179, 183 | Unsolved |
| 2 | **Data Quality** — training on records with `vegas_line=0` | 59 | Fixed (quality gates) |
| 3 | **Date Overlap** — train/eval contamination inflates metrics | 176-178 | Fixed (hard guard) |
| 4 | **Residual Collapse** — residual target (actual - vegas) causes 4-6 iteration early stop | 180, 183 | Dead end |
| 5 | **Backtest Gap** — backtests overstate production by 5-10pp | 176+ | Known, unfixable |

### 2.3 What Has Been Tried (Dead Ends)

| Approach | Experiments | Best Result | Why It Failed |
|----------|-----------|-------------|---------------|
| Vegas weight sweep (0.0-1.0) | 6 | 51.9% HR, 54 picks | Linear tradeoff, no sweet spot |
| Residual modeling | 3 | 30% HR | Gradient signal collapses |
| Two-stage pipeline | 2 | 50.8% HR | Coin flip at scale |
| CHAOS (high randomness) | 3 | 58.3%, 12 picks | Not enough volume |
| Matchup feature boost | 2 | 60.0%, 25 picks | Not enough volume |
| Grow policy (Depthwise) | 4 | Worse in all cases | Dead end |
| NO_VEG + quantile combo | 2 | 48.9% HR | Overshoots optimal point |
| CHAOS + quantile combo | 2 | 48.2% HR | Overshoots optimal point |

### 2.4 What Has Worked

| Approach | Result | Limitation |
|----------|--------|-----------|
| **Quantile alpha=0.43** | 65.8% HR edge 3+ when fresh (n=38) | Only UNDER picks, vegas bias -1.62 near limit |
| **Staleness exploitation** | Champion 71.2% peak at 2-3 weeks stale | Decays to <40% after 5 weeks |

Quantile regression is the **only approach** that generates edge when fresh. It works by systematically predicting below the median, creating permanent divergence from Vegas. But it's 100% UNDER direction.

---

## Part 3: Training Data & Feature Gaps

### 3.1 Massive Untapped Training Data

| Season | Usable Rows | Currently Used? |
|--------|-------------|-----------------|
| 2021-22 | 11,660 | No |
| 2022-23 | 11,652 | No |
| 2023-24 | 13,671 | No |
| 2024-25 | 15,193 | No |
| 2025-26 (through Feb 12) | 11,287 | **Only 8,417 (Nov-Jan)** |
| **TOTAL** | **~63,463** | **8,417 (13%)** |

The champion uses **13% of available data**. There are 63K+ clean training rows across 5 seasons.

### 3.2 Feature Gaps (What the Model Doesn't Know)

**High-Impact Missing Signals:**

| Signal | Description | Why It Matters |
|--------|-------------|---------------|
| **Teammate injuries** | Whether a star teammate is OUT | When a star sits, role players get +5-10 PPG usage boost. The model doesn't know this. |
| **Opponent key injuries** | Missing key defenders | Offensive matchup changes significantly. |
| **Minutes projection** | Expected minutes tonight | We only have historical average; DNP risk and blowout benching are invisible. |
| **Recent efficiency** | FG% last 1-3 games | Hot/cold shooting streaks affect scoring. |
| **Game context** | Blowout probability, pace prediction | Model can't anticipate garbage time or high-pace shootouts. |

**Feature Store Observations:**
- `playoff_game` is **dead weight** — always 0 during regular season
- `vegas_line_move` is non-zero for only **15.7%** of records — near-useless
- Only **45.2%** of records have a Vegas line at all — model operates in two regimes
- 6 unused features already exist in the store (indices 33-38): `dnp_rate`, `pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag`, `breakout_risk_score`, `composite_breakout_signal`

### 3.3 Should We Train on Past Seasons?

**Yes, with caveats.**

**Arguments FOR multi-season training:**
1. **7.5× more data** — 63K rows vs 8.4K improves generalization
2. **More diverse game states** — different opponents, venues, lineup configurations
3. **Reduces overfitting** — current model overfits to narrow 68-day window
4. **Player archetype learning** — same player types recur across seasons (3-and-D wings, stretch bigs, etc.)
5. **Historical data quality is good** — 2022-25 seasons have 45-73% clean rates

**Arguments AGAINST (and mitigations):**
1. **Roster changes** — players change teams, roles evolve → Mitigation: use relative features (points vs avg, not absolute stats)
2. **Rule changes** — NBA rule changes shift scoring patterns → Mitigation: 2021+ data is post-modern-rules, fairly consistent
3. **Feature drift** — features computed differently across seasons → Mitigation: the shared feature store normalizes this; the training loader already handles historical data correctly
4. **Recency matters** — last month's games predict tonight better than 2022 games → Mitigation: use recency weighting (`--recency-weight 90` = 90-day half-life)

**Recommendation**: Train on 2023-24 through present (2 full seasons + current). Use recency weighting with 120-day half-life. This gives ~40K rows with appropriate emphasis on recent games. Skip 2021-23 initially — the NBA was still settling post-COVID protocols and the game style was different.

---

## Part 4: Per-Player Tendencies

### 4.1 Model Strengths (Player Types It Gets Right)

1. **High-usage stars on OVER** (62.5% HR): When stars like Embiid, Mitchell, and Allen are projected above their line, the model is right 2/3 of the time. Stars have high game-to-game consistency and the model correctly identifies upside potential.

2. **Veteran role players on UNDER** (selected, 66.7%): Julius Randle UNDER and Simone Fontecchio UNDER are profitable. These are players with predictable ceilings.

3. **Low-variance players**: Players with low `points_std_last_10` are easier to predict. The model's accuracy is inversely correlated with player scoring volatility.

### 4.2 Model Weaknesses (Player Types It Gets Wrong)

1. **Mid-tier UNDER trap** (22.0% HR for role players): The model systematically under-predicts scoring for players in the 5-14 point range. These players are likely experiencing upward role changes (injuries to teammates, rotation adjustments) that the model can't see.

2. **Breakout-prone players** (0% HR): Trey Murphy III, Jabari Smith Jr, Jaren Jackson Jr — young players with high ceiling and high variance. The model predicts their average but they frequently exceed it. This is exactly the pattern the breakout classifier was designed to catch (but it's not ready).

3. **Starter OVER** (31.8% HR): Model over-predicts starters' scoring. These players may face tighter defensive assignments that aren't captured in team-level `opponent_def_rating`.

### 4.3 Player-Specific Model Idea

Could we build **player-specific adjustments** on top of the base model? For example:
- If player is in "breakout-prone" archetype AND model predicts UNDER → reduce confidence or skip
- If player is "high-ceiling star" AND model predicts OVER → boost confidence
- Track per-player bias over rolling 20-game windows and adjust predictions

This is essentially a **calibration layer** — not changing the model itself but post-processing its outputs based on known systematic biases.

---

## Part 5: Experiment Roadmap (5 Proposals)

### Experiment 1: Multi-Season Training with Recency Weighting
**Priority: HIGH | Effort: LOW**

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MULTISZN_Q43" \
    --quantile-alpha 0.43 \
    --train-start 2023-10-01 \
    --train-end 2026-02-10 \
    --recency-weight 120 \
    --force
```

**Hypothesis**: More data + recency weighting will improve generalization while maintaining quantile edge. The model sees ~40K rows instead of 8K, reducing overfitting to recent patterns while still emphasizing current form.

**Success criteria**: Edge 3+ HR ≥ 55%, sample ≥ 50, vegas bias within ±1.5.

### Experiment 2: Direction-Aware Filtering (No Code Change)
**Priority: HIGH | Effort: NONE**

Filter the current champion's output to OVER-only picks:

```sql
-- Simulated OVER-only performance
SELECT
  COUNT(*) as picks,
  COUNTIF(is_correct) as correct,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= '2026-02-01'
  AND edge >= 3
  AND predicted_direction = 'OVER';
-- Result: 47.5% HR on 80 picks (vs 38.0% on all 192)
```

This isn't great yet (47.5% < 52.4% breakeven) but demonstrates the directional asymmetry. A tier filter would improve it further:

```sql
-- Stars OVER only: 62.5% on 8 picks
-- Role OVER only: 51.0% on 49 picks
```

**Actionable today**: Add a `direction_filter` option to the prediction pipeline that suppresses UNDER picks for role players. This alone could swing the champion from -EV to near breakeven.

### Experiment 3: V10 Feature Set with Breakout + Slope Features
**Priority: MEDIUM | Effort: MEDIUM**

The feature store already has 6 unused features (indices 33-38). Train V10 with 37-39 features:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V10_EXPANDED" \
    --quantile-alpha 0.43 \
    --train-start 2025-11-02 \
    --train-end 2026-02-10 \
    --feature-set v10 \
    --force
```

**New features to add:**
- `dnp_rate` (index 33) — helps avoid predicting players who won't play
- `pts_slope_10g` (index 34) — captures hot/cold streaks the model currently misses
- `pts_vs_season_zscore` (index 35) — normalizes for role changes mid-season

**Note**: This requires updating the feature contract and training script to support V10. The features already exist in BigQuery but the training pipeline needs to select them.

### Experiment 4: Teammate Injury Feature
**Priority: HIGH | Effort: HIGH**

The single biggest missing signal. When a star teammate is injured:
- Role players see +3-8 PPG increases
- Usage rates spike 5-15%
- The current model has NO visibility into this

**Implementation sketch:**
1. Query the injury report for each game date
2. For each player, check if their team has any player with `avg_points >= 20` listed as OUT
3. Compute a `star_teammate_out` binary feature (0/1)
4. Optionally compute `teammate_points_missing` (sum of PPG of OUT teammates)
5. Add to Phase 4 precompute and feature store

This directly addresses the **role player UNDER failure** — when a star sits, the role player's line should be OVER, but the model doesn't know a star is sitting.

### Experiment 5: Ensemble of Stale + Fresh Models
**Priority: MEDIUM | Effort: MEDIUM**

Instead of choosing one model, combine:
- A **stale model** (trained through Jan 8) for its natural drift-based edge
- A **fresh quantile model** (trained through Feb 10) for its systematic UNDER bias
- A **direction-aware combiner** that:
  - Uses the stale model's OVER predictions (its strength)
  - Uses the fresh Q43 model's UNDER predictions (its strength)
  - Requires agreement between models for high-confidence picks

```
If stale_model.direction == OVER AND stale_model.edge >= 3:
    → take the OVER bet (47.5% HR baseline, better for Stars)
If fresh_q43.direction == UNDER AND fresh_q43.edge >= 3:
    → take the UNDER bet (Q43 is designed for this)
If both agree on direction AND both have edge >= 3:
    → HIGH confidence pick
```

This requires no model retraining — just a post-processing layer on existing predictions.

---

## Part 6: Immediate Action Items

### This Week (Priority Order)

1. **Add direction filter to suppress Role Player UNDER** — near-zero effort, immediate improvement
2. **Run Experiment 1** (multi-season Q43) — one command, tests the biggest hypothesis
3. **Query the ensemble idea** (Experiment 5) — simulate from existing prediction_accuracy data

### Next 2 Weeks

4. **Build `star_teammate_out` feature** (Experiment 4) — highest expected impact, most effort
5. **Evaluate V10 feature set** (Experiment 3) — medium effort, leverages existing features

### Continue Monitoring

- Q43 shadow: 31 edge 3+ graded, need 50. At ~3/day, ETA ~6 days (Feb 18).
- Q45 shadow: 18 edge 3+ graded, need 50. ETA ~11 days.
- If Q43 passes 50 picks with ≥55% HR, promote regardless of retrain experiments.

---

## Appendix: Feature Importance (Current Champion)

| Rank | Feature | Importance % |
|------|---------|-------------|
| 1 | `vegas_points_line` | 29-36% |
| 2 | `vegas_opening_line` | 14-17% |
| 3 | `points_avg_last_10` | ~12% |
| 4 | `points_avg_last_5` | ~3.4% |
| 5 | `vegas_line_move` | ~3.0% |
| 6 | `ppm_avg_last_10` | ~2.9% |
| 7 | `minutes_avg_last_10` | ~2.7% |
| 8 | `usage_spike_score` | ~2.7% |
| 9 | `opponent_def_rating` | ~2.3% |
| 10 | `fatigue_score` | ~2.0% |
| ... | ... | ... |
| 32 | `back_to_back` | ~0.3% |
| 33 | `playoff_game` | **0.0%** |

Vegas features alone account for **50%+** of all model decisions. This is both the source of accuracy AND the source of the retrain paradox.

## Appendix: Cross-Model Comparison (Feb 2026)

| Model | Edge 3+ Graded | HR Edge 3+ | OVER/UNDER Split | Vegas Bias | MAE |
|-------|---------------|-----------|------------------|-----------|-----|
| **Champion** (catboost_v9) | 192 | 38.0% | 83 OVER / 103 UNDER | -0.24 | 5.46 |
| train1102_0108 | 13 | 53.8% | 3 / 10 | -0.01 | 4.95 |
| Q43 shadow | 31 | 45.2% | 0 / 31 | -1.60 | 4.59 |
| Q45 shadow | 18 | 50.0% | 0 / 18 | -1.23 | 4.57 |

No model is currently profitable. The best performers have insufficient sample sizes.
