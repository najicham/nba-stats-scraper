# NBA Player Props Prediction System — Architectural Review & Overhaul Plan

`path: docs/phase-5/architectural-review-overhaul-plan.md`

**Prepared by:** External Review (Claude Opus)
**For:** Claude Code Implementation
**Date:** February 2026
**Status:** Ready for implementation planning

---

## Executive Summary

The current CatBoost prediction system achieved 79.5% hit rate on February 2025 data but has decayed to ~40% on February 2026. After reviewing the full experiment log, feature set, and system architecture, the root cause is clear: **the model learned to echo Vegas lines with a slight discount rather than independently predicting player scoring**. This document proposes a ground-up architectural overhaul with three implementation tiers.

**Core diagnosis:** The model is a Vegas derivative, not a basketball predictor. When Vegas is well-calibrated (as it increasingly is mid-season), there are no edges to find because the model's predictions converge with the lines it's supposed to beat.

**Proposed solution:** A three-model architecture that separates point prediction, edge detection, and bet selection into independent systems with distinct objectives.

---

## Table of Contents

1. [Diagnosis Deep Dive](#1-diagnosis-deep-dive)
2. [Proposed Architecture: Three-Model System](#2-proposed-architecture-three-model-system)
3. [Feature Engineering Overhaul](#3-feature-engineering-overhaul)
4. [Data Source Exploitation Plan](#4-data-source-exploitation-plan)
5. [Training & Evaluation Strategy](#5-training--evaluation-strategy)
6. [Implementation Tiers](#6-implementation-tiers)
7. [Dead End Avoidance Guide](#7-dead-end-avoidance-guide)
8. [Open Questions & Assumptions](#8-open-questions--assumptions)
9. [Success Criteria & Monitoring](#9-success-criteria--monitoring)

---

## 1. Diagnosis Deep Dive

### 1.1 Why the Model Failed

The model's feature importance tells the whole story:

```
vegas_points_line:    15-30% importance  <- Model's primary signal
points_avg_last_5:     6-35% importance  <- Secondary signal
points_avg_last_10:    8-13% importance
vegas_opening_line:    4-14% importance  <- More Vegas dependency
```

Combined, Vegas features (`vegas_points_line`, `vegas_opening_line`, `vegas_line_move`, `has_vegas_line`) account for **20-45% of total feature importance**. The model essentially learned:

```
prediction = vegas_line * discount_factor + minor_adjustments
```

With quantile alpha=0.43, the discount factor systematically pulls predictions below the line, creating artificial UNDER bias. This "works" when Vegas tends to set lines slightly high (common early season when books are still calibrating). It catastrophically fails when:

- Vegas calibration improves (mid/late season with more data)
- Market efficiency increases (sharps have corrected early-season mispricings)
- The UNDER bias means OVER opportunities are invisible to the model

### 1.2 Why February 2025 Worked But February 2026 Doesn't

The same architecture scored 79.5% on Feb 2025. Two likely explanations:

1. **Market maturation**: Sportsbook models improve year-over-year. February 2025's Vegas lines may have had more systematic bias than February 2026's, giving a "dumb" Vegas-echo model easy edges to exploit.

2. **Structural noise**: February 2026 includes trade deadline effects, All-Star break disruption, and rotation experimentation. Rolling averages (`points_avg_last_5`, `points_avg_last_10`) become unreliable when a player's team context changes mid-window. A player traded from a bottom-5 offense to a top-5 offense will have stale averages for 5-10 games.

### 1.3 The Universal OVER Collapse

Across all 9 experiments on Feb 2026 data:
- Most generate near-zero OVER picks
- When OVER picks are generated, hit rates are 0-47%
- UNDER direction consistently performs better (50-61%)

This is the direct consequence of quantile alpha=0.43. The model is structurally incapable of confidently predicting OVER outcomes because it's been trained to predict below the median. **This is not a feature -- it's a fundamental design flaw for a system that needs to identify edges in both directions.**

### 1.4 What This Means for the Overhaul

The model needs to:
1. **Learn basketball independently of Vegas** -- predict what a player will score based on basketball context
2. **Compare its prediction to Vegas** -- as a post-prediction step, not an input feature
3. **Find edges in both directions** -- eliminate structural directional bias
4. **Handle regime changes** -- trade deadline, All-Star break, rotation shifts

---

## 2. Proposed Architecture: Three-Model System

### 2.1 Overview

```
+-----------------------------------------------------+
|                  DATA LAYER                          |
|  Player stats, matchup context, play-by-play,       |
|  team context, schedule, injury reports              |
+---------------+----------------------+---------------+
                |                      |
                v                      v
+----------------------+  +----------------------------+
|   MODEL 1            |  |   MODEL 2                  |
|   Points Predictor   |  |   Market Inefficiency      |
|                      |  |   Detector                 |
|   Input: Basketball  |  |   Input: Vegas lines +     |
|   context ONLY       |  |   market signals +         |
|   (NO Vegas lines)   |  |   contextual features      |
|                      |  |                            |
|   Output: Expected   |  |   Output: Predicted        |
|   points scored      |  |   residual (actual -       |
|   (continuous)       |  |   vegas_line)              |
|                      |  |                            |
|   Loss: MAE/Huber    |  |   Loss: MAE on residual    |
|                      |  |   or classification        |
+-----------+----------+  +-----------+----------------+
            |                         |
            v                         v
+-----------------------------------------------------+
|                  MODEL 3                             |
|                  Bet Selector                        |
|                                                     |
|   Inputs:                                           |
|   - Model 1 prediction vs vegas_line (edge)         |
|   - Model 2 predicted residual                      |
|   - Model 1 prediction uncertainty (std/quantiles)  |
|   - Agreement/disagreement between Model 1 & 2      |
|   - Historical accuracy of similar edge sizes       |
|   - Market features (line movement, book spread)    |
|                                                     |
|   Output: Bet recommendation (OVER/UNDER/SKIP)      |
|   + confidence score                                |
|                                                     |
|   Loss: Betting P&L or binary classification        |
|   (OVER/UNDER profit weighted)                      |
+-----------------------------------------------------+
```

### 2.2 Model 1: Points Predictor (Vegas-Free)

**Objective:** Predict the actual points a player will score, using only basketball information.

**Why this matters:** This model must learn actual basketball dynamics -- how matchups affect scoring, how fatigue changes output, how pace influences points. By excluding Vegas lines, it's forced to develop independent predictive power.

**Target variable:** `actual_points_scored` (continuous)

**Loss function:** Huber loss (robust to outliers from blowout/injury games) or MAE

**Model type:** CatBoost or LightGBM (gradient-boosted trees remain appropriate here)

**Feature set (detailed in Section 3):**
- Player recent performance (rolling averages, trends, streaks)
- Player efficiency metrics (points-per-minute, usage rate, true shooting)
- Matchup context (opponent defense, position-level matchups)
- Game environment (pace, game total implied scoring, home/away)
- Schedule context (rest, back-to-back, travel, minutes load)
- Team context (offensive rating, teammates in/out)
- Shot profile vs opponent defense profile
- Play-by-play derived features (shot quality, clutch performance, garbage time split)

**Key design decisions:**
- Train on ALL player-games, not just those with Vegas lines (much larger training set)
- This means the model can learn from games without prop lines, expanding data significantly
- Use current-season + prior-season weighting (exponential decay)
- Produce both point estimate AND uncertainty estimate (e.g., prediction intervals via quantile regression at Q25/Q50/Q75)

### 2.3 Model 2: Market Inefficiency Detector

**Objective:** Predict where Vegas is systematically wrong.

**Target variable:** `actual_points - vegas_points_line` (the residual/mispricing)

**Why this is different from the failed "Residual mode":** The briefing doc notes that "Residual mode (predict actual - vegas)" was tried and had "poor calibration." However, that was a single model trying to learn residuals with the same feature set. This version:

1. Uses a **dedicated feature set** focused on market signals and situational indicators
2. Runs **alongside** an independent points predictor (not instead of one)
3. Focuses specifically on **known mispricing patterns** rather than general prediction

**Feature set (market-focused):**
- `vegas_line_vs_season_avg` -- is the line below/above the player's season average?
- `vegas_line_vs_recent_avg` -- is the line below/above the player's last-5 average?
- `line_movement` -- direction and magnitude of line movement
- `multi_book_spread` -- range across sportsbooks (wide spread = market disagreement = potential edge)
- `consensus_vs_outlier` -- is the target book's line an outlier vs consensus?
- `consecutive_overs` / `consecutive_unders` -- streak indicators (mean-reversion signal)
- `post_cold_streak_indicator` -- games where player went under 2+ times, line dropped, but fundamentals unchanged
- `opponent_def_rating` -- defensive context that Vegas may over/underweight
- `home_away` -- home/away bias in Vegas pricing
- `back_to_back` -- schedule situation pricing
- `game_total_line` -- expected game environment
- `days_since_trade` -- regime change indicator (recently traded players are mispriced)
- `minutes_trend_vs_line_assumption` -- if minutes are trending up but line hasn't adjusted

**Loss function:** MAE on residuals, or binary classification (OVER/UNDER) with log-loss

**Training constraint:** Only train on games where Vegas lines exist (subset of Model 1's training data)

### 2.4 Model 3: Bet Selector

**Objective:** Decide which predictions represent profitable betting opportunities.

**This is the meta-model.** It doesn't predict points or residuals -- it predicts whether a specific bet will be profitable.

**Input features (derived from Models 1 and 2):**
- `model1_edge` = `model1_prediction - vegas_line` (how far our basketball prediction differs from Vegas)
- `model1_edge_direction` = OVER if positive, UNDER if negative
- `model2_predicted_residual` = Model 2's predicted mispricing
- `model2_direction` = OVER if positive, UNDER if negative
- `models_agree` = 1 if both models point the same direction, 0 otherwise
- `model1_uncertainty` = width of prediction interval (Q75 - Q25)
- `edge_magnitude` = absolute value of model1_edge
- `confidence_ratio` = edge_magnitude / model1_uncertainty (edge relative to noise)
- Historical features:
  - `player_model1_accuracy_last_30d` = how well Model 1 has predicted this player recently
  - `similar_edge_historical_hitrate` = hit rate on similar edge sizes historically
  - `player_props_over_rate_season` = player's actual OVER/UNDER split this season
- Market features:
  - `line_movement_aligned_with_model` = is the line moving toward or away from our prediction?
  - `multi_book_consensus` = market agreement level

**Target variable:** Binary -- did this bet win (1) or lose (0)?

**Loss function:** Log-loss or custom P&L-weighted loss

**Key design decisions:**
- This model should be VERY selective -- it's better to make 5 high-confidence bets per day than 50 marginal ones
- Minimum edge threshold should be a learned parameter, not hardcoded
- Can incorporate Kelly criterion or similar position-sizing logic

### 2.5 How the Three Models Interact

```
Daily Flow:
1. Model 1 generates point predictions for ALL players with games today
2. Model 2 generates mispricing predictions for players with Vegas lines
3. Model 3 evaluates each potential bet using outputs from Models 1 & 2
4. Only bets where Model 3 confidence exceeds threshold are published

Agreement Matrix:
+--------------------------+---------------------+---------------------+
|                          | Model 2: OVER       | Model 2: UNDER      |
+--------------------------+---------------------+---------------------+
| Model 1: OVER            | STRONG OVER signal  | Conflicting -> SKIP |
| (prediction > line)      | -> Model 3 evaluates| or lower confidence |
+--------------------------+---------------------+---------------------+
| Model 1: UNDER           | Conflicting -> SKIP | STRONG UNDER signal |
| (prediction < line)      | or lower confidence | -> Model 3 evaluates|
+--------------------------+---------------------+---------------------+
```

### 2.6 Relationship to Prior Dead Ends

The briefing doc lists these as failed:
- **"Residual mode (predict actual - vegas)"** -- This was a single model. Model 2 in this architecture is paired with an independent Model 1 and uses a market-focused feature set, not the same general features.
- **"Two-stage pipeline"** -- The doc says this "added noise at each stage." The key difference here is that Models 1 and 2 are **parallel, not sequential**. They don't feed into each other -- they independently inform Model 3. There's no cascading error.

**Claude Code should validate:** Confirm the exact configurations of the failed residual mode and two-stage pipeline to ensure this architecture doesn't replicate them. If the prior two-stage pipeline was also a parallel architecture, we need to understand specifically why it failed before rebuilding.

---

## 3. Feature Engineering Overhaul

### 3.1 Features to Remove (Near-Zero Importance, All Experiments)

| Feature | Avg Importance | Reason to Remove |
|---------|---------------|-----------------|
| `injury_risk` | 0.00-0.14% | Generic composite, no predictive signal |
| `back_to_back` | 0.00-0.24% | Binary flag too coarse; replace with continuous fatigue |
| `playoff_game` | 0.00-0.10% | Always 0 in regular season; useless until playoffs |
| `rest_advantage` | 0.07-0.30% | Too blunt; replace with detailed schedule features |
| `has_vegas_line` | 0.10-0.30% | Indicator variable, no real information |

**Net effect:** 33 -> 28 features, removing noise dimensions.

### 3.2 New Features for Model 1 (Points Predictor)

#### 3.2.1 Player Performance (Enhanced)

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `points_avg_last_3` | Ultra-short-term average | BigQuery game logs | Captures very recent form better than last-5 |
| `minutes_avg_last_5` | Recent minutes (keep) | BigQuery game logs | Minutes drive scoring opportunity |
| `ppm_avg_last_5` | Points-per-minute recent | BigQuery game logs | Efficiency matters more than raw points |
| `usage_rate_last_5` | % of team possessions used | BigQuery/play-by-play | How much of the offense runs through this player |
| `true_shooting_last_10` | TS% (efficiency) | BigQuery game logs | Combines 2P/3P/FT efficiency into one metric |
| `scoring_variance_last_10` | Std dev of points | BigQuery game logs | High variance = less predictable = widen intervals |

#### 3.2.2 Streak & Trend Features

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `consecutive_games_over_avg` | Games in a row above season avg | BigQuery game logs | Hot streak indicator |
| `consecutive_games_under_avg` | Games in a row below season avg | BigQuery game logs | Cold streak / bounce-back signal |
| `scoring_trend_slope` | Linear regression slope over last 10 | BigQuery game logs | Directional momentum (not just level) |
| `deviation_from_avg_last_3` | (avg_last_3 - avg_season) / std | BigQuery game logs | Z-score: how hot/cold relative to baseline |

#### 3.2.3 Fatigue Features (Replacing Generic `fatigue_score`)

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `cumulative_minutes_last_7d` | Total minutes played in last 7 days | BigQuery game logs | Cumulative load matters more than game count |
| `games_in_last_7d` | Keep existing | BigQuery game logs | Schedule density |
| `max_minutes_last_3_games` | Highest single-game minutes | BigQuery game logs | Spike detection (one 42-min game is more fatiguing) |
| `days_rest` | Days since last game | BigQuery game logs | Continuous > binary back-to-back flag |
| `minutes_load_ratio` | last_7d_minutes / season_avg_weekly | BigQuery game logs | Relative fatigue vs own baseline |

#### 3.2.4 Matchup Features (Enhanced)

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `opponent_def_rating` | Keep existing | BigQuery team stats | Overall defensive quality |
| `opponent_pace` | Keep existing | BigQuery team stats | Game speed context |
| `opponent_points_allowed_to_position` | Points allowed to player's position | BigQuery/play-by-play | Position-specific defense |
| `opponent_def_rating_last_10` | Recent defensive form | BigQuery team stats | Teams get better/worse defensively |
| `historical_vs_opponent` | Keep `avg_points_vs_opponent` | BigQuery game logs | Head-to-head history |

#### 3.2.5 Team Context Features

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `team_pace` | Keep existing | BigQuery team stats | Game speed |
| `team_off_rating` | Keep existing | BigQuery team stats | Offensive environment |
| `star_teammate_out` | Is team's top scorer (by usage) out? | Injury reports + BigQuery | Creates usage/scoring opportunity |
| `teammate_usage_vacuum` | Total usage rate of inactive teammates | Injury reports + BigQuery | More nuanced than binary star_out |
| `days_since_trade` | Days since player was traded (0 if not traded) | Roster transactions | Regime change indicator; new team = stale averages |

#### 3.2.6 Game Environment Features

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `game_total_line` | Over/under total for the game | The Odds API | Proxy for expected pace/scoring environment |
| `spread` | Point spread for the game | The Odds API | Blowout risk (large spread = more garbage time) |
| `home_away` | Keep existing | Schedule data | Home court effect |
| `is_nationally_televised` | National TV game flag | Schedule data | Players perform differently on big stages (documented) |

#### 3.2.7 Shot Profile Features (Enhanced with Play-by-Play)

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `pct_paint` | Keep existing | BigQuery shot data | Shot distribution |
| `pct_mid_range` | Keep existing | BigQuery shot data | Shot distribution |
| `pct_three` | Keep existing | BigQuery shot data | Shot distribution |
| `free_throw_rate` | Keep existing | BigQuery shot data | And-1s, drives, foul-drawing |
| `shot_quality_avg_last_5` | Average expected FG% of shots taken | Play-by-play data | Are they getting good looks? |
| `pct_assisted_last_5` | % of makes that were assisted | Play-by-play data | Self-creation vs system offense |
| `clutch_scoring_rate` | Points per minute in clutch (< 5 min, < 5 pt margin) | Play-by-play data | Some players score disproportionately in clutch |
| `garbage_time_pct` | % of points in garbage time (> 20 pt margin) | Play-by-play data | Inflated averages from blowouts |

### 3.3 New Features for Model 2 (Market Inefficiency Detector)

| Feature | Description | Source | Rationale |
|---------|-------------|--------|-----------|
| `vegas_line` | The prop line itself | The Odds API | Baseline for residual prediction |
| `vegas_line_vs_season_avg` | `line - season_avg_points` | Computed | Is Vegas pricing below/above true talent? |
| `vegas_line_vs_recent_avg` | `line - avg_last_5` | Computed | Line vs recent form |
| `line_movement` | `current_line - opening_line` | The Odds API | Sharp money signal |
| `multi_book_spread` | `max(line across books) - min(line across books)` | The Odds API | Market disagreement = uncertainty = edge opportunity |
| `book_vs_consensus` | `target_book_line - median(all_book_lines)` | The Odds API | Is the book we're betting an outlier? |
| `consecutive_overs` | Streak of games above the line | Computed from game logs + odds | Mean-reversion signal |
| `consecutive_unders` | Streak of games below the line | Computed from game logs + odds | Mean-reversion signal |
| `post_cold_streak` | 1 if under 2+ games AND line dropped > 1pt | Computed | Buy-low signal |
| `days_since_trade` | Same as Model 1 | Roster transactions | Vegas slow to adjust for traded players |
| `game_total_line` | Same as Model 1 | The Odds API | Expected scoring environment |
| `opponent_def_rating` | Same as Model 1 | BigQuery | Defensive context |
| `home_away` | Same as Model 1 | Schedule | Home/away pricing bias |

### 3.4 Feature Count Summary

| Model | Feature Category | Count |
|-------|-----------------|-------|
| Model 1 | Player performance (enhanced) | 6 |
| Model 1 | Streak & trend | 4 |
| Model 1 | Fatigue (replacing generic) | 5 |
| Model 1 | Matchup (enhanced) | 5 |
| Model 1 | Team context | 5 |
| Model 1 | Game environment | 4 |
| Model 1 | Shot profile (enhanced w/ PBP) | 8 |
| **Model 1 Total** | | **~37** |
| Model 2 | Market & situational | ~13 |
| Model 3 | Meta-features (derived from 1 & 2) | ~12 |

---

## 4. Data Source Exploitation Plan

### 4.1 Play-by-Play Data (Currently Unused in Features)

**Status:** In BigQuery via Big Ball Data scraper.

**Features to extract:**

```sql
-- Shot quality: average expected FG% based on shot distance/type
-- Requires mapping shot coordinates to expected FG% lookup
-- Can use league-average FG% by distance bucket as baseline

-- Clutch performance
SELECT
  player_id,
  game_id,
  SUM(CASE WHEN period >= 4 AND ABS(home_score - away_score) <= 5
       AND game_clock_seconds <= 300 THEN points ELSE 0 END) as clutch_points,
  SUM(CASE WHEN period >= 4 AND ABS(home_score - away_score) <= 5
       AND game_clock_seconds <= 300 THEN minutes ELSE 0 END) as clutch_minutes

-- Garbage time identification
-- Points scored when margin > 20 in 4th quarter
-- Inflate rolling averages but won't recur in competitive games

-- Assisted vs unassisted makes
-- % of field goals that were assisted -> role indicator
```

**Implementation priority:** HIGH -- this is the richest untapped data source and directly improves Model 1's ability to assess scoring quality vs quantity.

### 4.2 Multi-Sportsbook Odds (Currently Single-Book)

**Status:** Available via The Odds API (10+ books).

**Features to extract:**

```python
# For each player prop on a given game:
lines = get_all_book_lines(player_id, game_id, prop_type='points')

features = {
    'consensus_line': np.median(lines),
    'line_spread': max(lines) - min(lines),       # Market disagreement
    'target_book_vs_consensus': target_line - np.median(lines),  # Outlier detection
    'num_books_with_line': len(lines),             # Market depth
    'std_across_books': np.std(lines),             # Market uncertainty
}
```

**Implementation priority:** HIGH -- this is low-effort, high-signal. Market disagreement is one of the most reliable edge indicators in sports betting.

### 4.3 Game Total O/U Lines (Currently Unused)

**Status:** Available via The Odds API (already scraped for game-level odds).

**Features to extract:**
- `game_total_line` -- direct feature for expected scoring environment
- `spread` -- blowout risk indicator
- `implied_team_total` = `(game_total +/- spread) / 2` -- expected scoring for player's team specifically

**Implementation priority:** MEDIUM -- simple to add, provides game-level context that player-level features miss.

### 4.4 Teammate Injury/Absence Data

**Status:** Injury data in BigQuery. Player registry operational.

**Features to extract:**

```python
# For each player's upcoming game:
# 1. Get team roster and injury report
# 2. Identify inactive players
# 3. Calculate "usage vacuum" -- sum of usage rates of inactive teammates
# 4. Flag if top-1 or top-2 scorer (by season avg) is out

features = {
    'star_teammate_out': 1 if top_scorer_inactive else 0,
    'teammate_usage_vacuum': sum(usage_rate for p in inactive_teammates),
    'expected_usage_increase': player_usage_rate * (1 + vacuum_factor),
}
```

**Implementation priority:** MEDIUM -- requires connecting injury reports to usage rate data, but the signal is strong. When a team's #1 option sits, the #2 and #3 see measurable usage/scoring bumps.

**Note on prior dead end:** The briefing doc says V11 features `star_teammates_out` had "near-zero importance." The likely issue was the implementation -- a binary flag doesn't capture the magnitude of the opportunity. `teammate_usage_vacuum` (continuous, quantifying HOW MUCH usage is available) should perform better. Claude Code should verify the V11 implementation before rebuilding.

---

## 5. Training & Evaluation Strategy

### 5.1 Training Data Philosophy

**Current problem:** The model was trained on 60-90 day windows, and experiments showed more data made it worse. This is because the model was learning "current Vegas calibration patterns" which shift over time.

**New approach for Model 1 (Points Predictor):**
- Train on 2+ seasons of data with **exponential decay weighting**
- More recent games have higher weight, but historical games still inform baseline patterns
- Weight formula: `weight = exp(-lambda * days_ago)` where `lambda` controls decay rate
- Tune `lambda` via cross-validation (likely 0.003-0.01 range, meaning games from 6+ months ago have ~15-50% weight)
- **Key advantage:** Model 1 doesn't include Vegas features, so multi-season data teaches basketball fundamentals (matchup effects, fatigue patterns, pace relationships) that are stable across seasons

**New approach for Model 2 (Market Inefficiency Detector):**
- Train on current season only (market dynamics change year to year)
- Use rolling 90-120 day window
- Retrain frequently (weekly or bi-weekly)

**New approach for Model 3 (Bet Selector):**
- Requires backtested outputs from Models 1 & 2
- Train on the most recent 60-90 days of Model 1 & 2 predictions vs actuals
- Retrain frequently (weekly)

### 5.2 Evaluation Protocol

**Critical change: Expand the evaluation window.** Feb 1-11 is only 11 days and may represent an anomaly. Any new architecture should be validated on:

1. **October-November (early season):** Markets are least efficient, models should find more edges
2. **December-January (mid-season):** Stable period, baseline expected performance
3. **February (trade deadline + ASB):** Known difficult regime, test regime-change handling
4. **March-April (playoff push):** Teams changing behavior, testing adaptability

**Minimum eval set:** 200+ edge-3+ picks per test window (currently Feb 2026 has only 24-170 depending on config -- too few for reliable conclusions).

**Backtesting procedure:**
```
For each eval month:
  1. Train Models 1 & 2 on all available data BEFORE eval period
  2. Generate predictions for each game day in eval period
  3. Run Model 3 to select bets
  4. Calculate:
     - Hit rate on edge 3+ picks (target: 55%+)
     - Hit rate on edge 5+ picks (target: 60%+)
     - OVER hit rate (target: balanced with UNDER)
     - UNDER hit rate (target: balanced with OVER)
     - Directional balance ratio (OVER picks / total picks -- target: 30-70%)
     - ROI assuming -110 vig
     - Volume (picks per day)
```

### 5.3 Regime Change Handling

**The trade deadline and All-Star break are recurring, predictable events.** The model should handle them explicitly, not as surprises.

**Approach 1: Feature-based (recommended):**
- `days_since_trade` feature handles traded players (their rolling averages are stale -> model should learn to trust them less)
- `days_since_allstar_break` feature -- post-break games are systematically different (rusty players, changed rotations)
- `games_played_with_current_team` -- for traded players, how many games in new context

**Approach 2: Windowed averages (complement to Approach 1):**
- Compute `points_avg_last_3_current_team` -- only games since joining current team
- When `games_played_with_current_team < 5`, rely more heavily on season averages weighted by team offensive context

**Approach 3: Model retraining cadence:**
- Increase retraining frequency around trade deadline (daily retrain for 2 weeks post-deadline)
- Model 2 especially should be retrained post-deadline as market pricing patterns shift

### 5.4 Loss Function Design

**Model 1:** Huber loss (delta=1.0, robust to outliers). MAE is also acceptable. Avoid RMSE -- it overpenalizes outlier games (injuries, ejections, blowouts) which distorts the learning signal.

**Model 2 -- Two options to test:**

Option A: MAE on residuals (predict `actual - vegas_line`)
- Pro: Continuous output, captures magnitude of mispricing
- Con: The failed "residual mode" used this approach

Option B: Binary classification (OVER=1, UNDER=0) with log-loss
- Pro: Directly aligned with the betting task
- Con: Loses magnitude information
- **Recommended starting point** -- simpler, more directly aligned with the bet

**Model 3:** Binary classification with custom weighting:
```python
# Weight correct predictions by edge size (bigger edges are more profitable)
sample_weights = edge_magnitude * outcome_binary
# Or use log-loss with class weights based on expected ROI
```

---

## 6. Implementation Tiers

### Tier 1: Foundation (Weeks 1-3)

**Goal:** Build Model 1 (Vegas-free points predictor) and establish the new feature pipeline.

**Tasks:**

1. **Feature pipeline construction**
   - Extract play-by-play features (shot quality, clutch performance, garbage time %)
   - Compute streak features (consecutive overs/unders vs own average)
   - Build fatigue features (cumulative minutes last 7d, spike detection)
   - Extract multi-book odds features (consensus, spread, outlier detection)
   - Add game total line and spread as features
   - Build teammate absence features (usage vacuum calculation)
   - Add regime change features (days since trade, games with current team)

2. **Model 1 training and validation**
   - Train CatBoost/LightGBM on 2+ seasons with exponential decay weighting
   - Validate on held-out months (Dec 2024, Jan 2025, Feb 2025, etc.)
   - Confirm balanced OVER/UNDER predictions (no directional bias)
   - Tune hyperparameters via time-series cross-validation
   - Generate prediction intervals (Q25/Q50/Q75 via quantile regression)

3. **Baseline comparison**
   - Compare Model 1 accuracy (MAE, hit rate vs Vegas line) to current CatBoost
   - Specifically check: does Model 1 generate OVER picks at reasonable volume?

**Success gate for Tier 1:**
- Model 1 MAE within 0.5 points of current model (Vegas-free will be slightly less accurate on raw MAE -- that's expected and okay)
- Directional balance: 30-70% of picks are OVER (not the current ~0%)
- Backtest hit rate on edge 3+ picks: 52%+ across multiple eval months

### Tier 2: Edge Detection (Weeks 3-5)

**Goal:** Build Model 2 and the meta-model (Model 3).

**Tasks:**

1. **Model 2 training**
   - Build market-focused feature set
   - Train on current season data (residual prediction or OVER/UNDER classification)
   - Validate against known mispricing patterns (post-cold-streak, traded players, outlier book lines)

2. **Model 3 construction**
   - Generate backtested Model 1 & 2 outputs for training data
   - Build meta-features (edge, agreement, uncertainty)
   - Train bet selector on historical prediction accuracy
   - Optimize for ROI, not just hit rate

3. **Full pipeline integration**
   - Three-model daily execution flow
   - Output: ranked list of bets with confidence scores

**Success gate for Tier 2:**
- Combined system hit rate on edge 3+ picks: 55%+ on backtest
- Profitable ROI on backtest (positive after -110 vig)
- Reasonable volume: 3-15 picks per day

### Tier 3: Optimization & Hardening (Weeks 5-7)

**Goal:** Optimize, monitor, and production-harden.

**Tasks:**

1. **Feature importance analysis on new architecture**
   - Identify which new features are pulling weight
   - Prune any zero-importance features
   - Investigate feature interactions

2. **Retraining automation**
   - Model 1: Weekly retrain with expanding window
   - Model 2: Weekly retrain with rolling window
   - Model 3: Weekly retrain
   - Monitoring: track daily hit rate with 7-day rolling window, alert if below 50%

3. **Regime change hardening**
   - Test specifically around trade deadline and All-Star break
   - Implement automatic retraining triggers for major events
   - Build "confidence dampening" for first 5 games post-trade-deadline

4. **Bet sizing strategy**
   - Implement Kelly criterion or fractional Kelly for position sizing
   - Scale bet confidence by Model 3 output and historical calibration

---

## 7. Dead End Avoidance Guide

These approaches have been tried and failed. **Do not re-implement them without understanding specifically why and confirming the new approach is materially different.**

| Dead End | What Was Tried | Why It Failed | How Our Approach Differs |
|----------|---------------|---------------|------------------------|
| Monotonic constraints | Forced prediction to increase with Vegas line | +15-27pp Vegas dependency, locked model into echo mode | We remove Vegas from Model 1 entirely |
| V10 features (opp_defense, days_rest, line_movement) | Added 3 general features | 2-3% importance, redundant | We add more specific versions (position-level defense, continuous rest days, multi-book spread) |
| V11 features (star_teammates_out, game_total_line) | Binary star out flag, game total | Near-zero importance | We use continuous `teammate_usage_vacuum` and pair game total with spread for implied team totals |
| Multi-quantile ensemble (Q40+Q43+Q45) | Combined 3 quantile models | Volume collapse, biases canceled out | Model 3 is a learned meta-model, not a naive average of quantile outputs |
| Alpha fine-tuning | Tested Q42 vs Q43 vs Q44 | Marginal differences | Model 1 predicts Q50 (median); directional bias is eliminated by design |
| Residual mode | Single model predicting actual - vegas | Poor calibration | Model 2 uses market-focused features and runs alongside (not instead of) an independent basketball model |
| Two-stage pipeline | Sequential models feeding into each other | Added noise at each stage | Models 1 and 2 are parallel, not sequential; Model 3 combines outputs without cascading error |
| Grow policy changes | Adjusted CatBoost tree growth | Marginal | We're changing the fundamental architecture, not tuning tree hyperparameters |

---

## 8. Open Questions & Assumptions

### Questions for Claude Code to Validate

1. **Training cycle time:** How long does a full train + eval cycle take? This determines how many experiments can run in parallel during development. *Assumption if unknown: ~5-15 minutes per full cycle. If it's significantly longer, Tier 1 timeline extends.*

2. **Evaluation window extent:** Is data available through end of February 2026, or only through Feb 11? More eval data strengthens conclusions about whether Feb 2026 is an anomaly or regime change. *Assumption: We'll backtest across multiple months regardless, so Feb 2026 is just one eval window.*

3. **Prior dead end implementations:**
   - What exactly was the "Residual mode" configuration? Specifically: what features were used, was it a standalone model or paired with another model, and what was the training window?
   - What was the "Two-stage pipeline" architecture? Was it sequential (model A feeds model B) or parallel (like our proposed approach)?
   - **This is critical -- if the prior two-stage pipeline was architecturally identical to our proposal, we need to understand the specific failure mode before rebuilding.**

4. **Play-by-play data granularity:** Does the PBP data in BigQuery include shot coordinates/distances, or only shot types? This determines whether we can compute shot quality metrics or only shot zone distributions.

5. **Multi-book odds storage:** Are all 10+ sportsbook lines stored in BigQuery with timestamps, or only a single book's line? This determines the complexity of building multi-book features.

6. **Trade transaction data:** Is there a table tracking player trades with dates? Needed for `days_since_trade` feature.

7. **Injury report timing:** When are injury reports scraped relative to game time? Features like `star_teammate_out` need to reflect gameday status, not morning status (players can be ruled in/out late).

### Key Assumptions in This Plan

- **CatBoost/LightGBM remains appropriate** for Models 1 and 2. Neural networks are not recommended at this data scale (~10K-40K training rows per season). GBDTs handle tabular data and this volume better.
- **Market inefficiency exists** in NBA player props. If sportsbooks are perfectly efficient, no model architecture will achieve 55%+. The Feb 2025 results (79.5%) and the general sports betting literature suggest inefficiency exists, especially in player props which are less liquid than game lines.
- **Feature engineering matters more than model architecture** at this stage. The current model's failure is due to what it learned (Vegas dependence) not how it learned (CatBoost is fine).

---

## 9. Success Criteria & Monitoring

### 9.1 Minimum Viable Performance

| Metric | Minimum | Target | Stretch |
|--------|---------|--------|---------|
| Edge 3+ hit rate (backtest avg) | 55% | 58% | 62%+ |
| Edge 5+ hit rate (backtest avg) | 57% | 62% | 70%+ |
| OVER hit rate | 50%+ | 55%+ | 60%+ |
| UNDER hit rate | 50%+ | 55%+ | 60%+ |
| Directional balance (OVER % of picks) | 25-75% | 35-65% | 40-60% |
| Daily pick volume | 3+ | 5-10 | 10-15 |
| Monthly ROI (after -110 vig) | +2% | +5% | +10%+ |

### 9.2 Monitoring Dashboard Metrics

**Daily:**
- Hit rate (7-day rolling)
- OVER vs UNDER hit rate split
- Average edge on selected picks
- Model agreement rate (Models 1 & 2 agree)
- Volume of picks

**Weekly:**
- Feature importance stability (flag if rankings shift dramatically)
- Model calibration (predicted probability vs actual hit rate)
- Comparison to "just fade Vegas" baseline

**Monthly:**
- Full backtest on prior month
- ROI calculation
- Regime change impact assessment

### 9.3 Kill Criteria

If the new architecture fails to meet minimum criteria after Tier 2 completion (full backtesting across 3+ months):

- **Below 52.4% on edge 3+**: The system is not profitable after vig. Investigate whether the market is truly efficient or if feature engineering needs further work.
- **Persistent OVER collapse**: If OVER hit rates remain below 45% despite removing Vegas dependency, there may be a systematic data issue (e.g., points averages are consistently stale).
- **Volume below 2 picks/day**: The models are too conservative. Relax Model 3 confidence thresholds or investigate whether edge calculations are miscalibrated.

---

## Appendix A: Implementation Checklist for Claude Code

```
Phase 1: Feature Pipeline
[ ] Extract play-by-play features (shot quality, clutch, garbage time, assisted %)
[ ] Compute streak features (consecutive over/under vs own avg, scoring trend slope)
[ ] Build fatigue features (cumulative minutes 7d, spike detection, minutes load ratio)
[ ] Extract multi-book odds features (consensus, spread, outlier, book count)
[ ] Add game total line and spread features
[ ] Build teammate absence features (usage vacuum from injury reports)
[ ] Add regime change features (days since trade, games with current team)
[ ] Remove dead features (injury_risk, back_to_back, playoff_game, rest_advantage, has_vegas_line)

Phase 2: Model 1 (Points Predictor)
[ ] Build training pipeline with exponential decay weighting
[ ] Train on 2+ seasons (no Vegas features)
[ ] Validate MAE across multiple eval months
[ ] Confirm directional balance (30-70% OVER picks)
[ ] Generate prediction intervals (Q25/Q50/Q75)
[ ] Compare to current model on same eval windows

Phase 3: Model 2 (Market Inefficiency Detector)
[ ] Build market-focused feature set
[ ] Train on current season (OVER/UNDER classification to start)
[ ] Validate mispricing detection on known patterns
[ ] If classification underperforms, test residual regression variant

Phase 4: Model 3 (Bet Selector)
[ ] Generate backtested Model 1 & 2 outputs as training data
[ ] Build meta-features (edge, agreement, uncertainty, historical accuracy)
[ ] Train bet selector
[ ] Optimize threshold for confidence cutoff
[ ] Full backtest across Oct-Feb eval windows

Phase 5: Integration & Hardening
[ ] Daily execution flow (Model 1 -> Model 2 -> Model 3 -> output)
[ ] Automated retraining pipeline (weekly)
[ ] Monitoring dashboard
[ ] Regime change handling (trade deadline, ASB triggers)
[ ] Bet sizing logic (Kelly criterion)
```

---

## Appendix B: Feature Derivation SQL Examples

### Streak Features

```sql
-- Consecutive games over/under player's own season average
WITH game_sequence AS (
  SELECT
    player_id,
    game_date,
    points,
    AVG(points) OVER (
      PARTITION BY player_id, season
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as running_season_avg,
    CASE
      WHEN points > AVG(points) OVER (
        PARTITION BY player_id, season
        ORDER BY game_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
      ) THEN 'OVER'
      ELSE 'UNDER'
    END as direction
  FROM player_game_logs
)
-- Then use a gaps-and-islands approach to count consecutive streaks
```

### Teammate Usage Vacuum

```sql
-- Calculate usage vacuum when teammates are out
WITH team_usage AS (
  SELECT
    player_id,
    team_id,
    season,
    AVG(usage_rate) as avg_usage_rate
  FROM player_game_logs
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY player_id, team_id, season
),
inactive_players AS (
  SELECT
    game_id,
    team_id,
    player_id,
    status  -- OUT, DOUBTFUL treated as out
  FROM injury_reports
  WHERE status IN ('OUT', 'DOUBTFUL')
    AND report_date = game_date  -- Gameday report
)
SELECT
  g.game_id,
  g.player_id,
  COALESCE(SUM(tu.avg_usage_rate), 0) as teammate_usage_vacuum
FROM upcoming_games g
LEFT JOIN inactive_players ip
  ON g.game_id = ip.game_id AND g.team_id = ip.team_id AND g.player_id != ip.player_id
LEFT JOIN team_usage tu
  ON ip.player_id = tu.player_id AND ip.team_id = tu.team_id
GROUP BY g.game_id, g.player_id
```

### Multi-Book Spread

```sql
-- Calculate market disagreement across sportsbooks
SELECT
  player_id,
  game_id,
  prop_type,
  COUNT(DISTINCT sportsbook) as num_books,
  MAX(line) - MIN(line) as line_spread,
  APPROX_QUANTILES(line, 2)[OFFSET(1)] as consensus_line,
  STDDEV(line) as line_std
FROM player_prop_odds
WHERE game_date = target_date
  AND prop_type = 'player_points'
GROUP BY player_id, game_id, prop_type
```
