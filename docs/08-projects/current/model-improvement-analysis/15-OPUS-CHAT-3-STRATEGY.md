# NBA Player Props Model — Expert Review Response & Strategic Roadmap

**Date:** February 12, 2026
**Context:** Response to the Expert Review Briefing, intended as a handoff document for Claude Code implementation.

---

## Executive Summary

The NBA Props prediction system achieved 71.2% hit rate at launch but has decayed to ~40%. After reviewing all 9 experiments, 33 features, feature importance rankings, and dead ends, this document provides:

1. A diagnostic investigation plan to understand February 2026 failures before building anything new
2. A two-model architecture redesign separating point prediction from edge-finding
3. New feature engineering specifications for streaks, teammate context, game environment, and fatigue
4. A classification vs. regression analysis with concrete recommendations on loss functions

**Core thesis:** The model's decay is not a model architecture failure -- it's a feature dependency problem (Vegas lines) compounded by a structural regime change (trade deadline, All-Star break, market tightening). The fix requires both investigation and architectural changes, in that order.

**Priority order:**
1. Diagnose February 2026 (1-2 days) -- before building anything
2. Build Vegas-free Points Predictor (3-5 days)
3. Add new features: streaks, teammate context, game totals (2-3 days)
4. Experiment with classification approach (1-2 days)
5. Build Edge Finder model and combine (2-3 days)

---

## Part 1: February 2026 Diagnostic Investigation

### Why Investigate First

The February 2025 backtest hit 79.5% with the exact same architecture. February 2026 hits ~40-57% depending on configuration. Before rebuilding anything, we need to know WHY.

### 5 Diagnostic Queries

**Diagnostic 1: Trade Deadline Impact Analysis**
- What % of edge 3+ misses involved traded/affected players?
- Stable roster hit rate vs affected player hit rate?
- If stable roster HR > 55%, trade deadline IS the primary cause
- If stable roster HR ~ 40%, look elsewhere

**Diagnostic 2: All-Star Break Stale Average Detection**
- Pre-break avg vs post-break actual for each player
- Model error vs Vegas error post-break
- If model_error >> vegas_error post-break, our rolling averages are stale

**Diagnostic 3: Miss Clustering Analysis**
- By player tier (star/mid/role), direction (OVER/UNDER miss), date, game context
- By Vegas accuracy on same bets (was Vegas also wrong, or only us?)
- The clustering pattern tells us exactly what's broken

**Diagnostic 4: Vegas Calibration Shift**
- Feb 2025 Vegas MAE vs Feb 2026 Vegas MAE
- If Vegas MAE dropped significantly, less edge exists -- adjust expectations

**Diagnostic 5: Feature Drift Detection**
- Distribution comparison for top 10 features: training period vs eval period
- Flag features where |eval_mean - train_mean| > 1 * train_std

### Diagnostic Decision Tree

| Finding | Primary Action |
|---------|---------------|
| Trade deadline >30% of misses | Add roster stability features |
| Rolling averages stale post-break | Break-aware windowing |
| Misses cluster on stars/role players | Tier-specific calibration |
| Vegas got materially more accurate | Shift to Vegas-free predictor, lower volume |
| Feature distributions drifted | Shorter training windows or normalization |
| OVER collapse universal | Architectural fix (remove Q43, go Vegas-free) |

---

## Part 2: Two-Model Architecture

### Model 1: Vegas-Free Points Predictor

**Objective:** Predict actual points scored without any knowledge of the betting line.

**Feature set (25 features, ZERO Vegas inputs):**

```
PLAYER RECENT PERFORMANCE (7)
  points_avg_last_3, points_avg_last_7, points_avg_last_15,
  points_avg_season, points_std_last_10, minutes_avg_last_5, ppm_avg_last_10

MATCHUP CONTEXT (5)
  opponent_def_rating, opponent_pace, opp_pts_allowed_to_position,
  home_away, game_total_line

TEAM CONTEXT (4)
  team_pace, team_off_rating, usage_rate_last_5, teammate_usage_available

FATIGUE & SCHEDULE (4)
  minutes_load_last_7_days, back_to_back, games_in_last_7_days,
  days_since_last_game

SHOT PROFILE (3)
  pct_paint, pct_three, pct_free_throw

TREND & STREAK (2)
  scoring_trend_slope, games_since_structural_change
```

**Training:** MAE loss (not quantile), 60-90 day window (test longer since no Vegas dependency).

**Critical success metric:** Model 1 doesn't need to beat Vegas on average. It needs to disagree with Vegas in informative ways. Track: "When Model 1 and Vegas disagree by 3+ points, who is right more often?"

### Model 2: Edge Finder (Binary Classifier)

**Objective:** Given Model 1 disagrees with Vegas, predict whether the edge is real.

**Feature set (~10-12 features):**
```
  raw_edge_size, edge_direction, model1_confidence,
  vegas_line_move, line_vs_season_avg, multi_book_consensus,
  line_move_direction_vs_edge, player_volatility, streak_indicator,
  roster_stability, edge_historical_hit_rate, game_total_line
```

**Algorithm:** Start with logistic regression, graduate to CatBoost if needed.

**Decision rules:**
```
IF raw_edge >= 3 AND model2_confidence >= 0.60: BET
ELIF raw_edge >= 5 AND model2_confidence >= 0.55: BET
ELSE: SKIP
```

---

## Part 3: New Feature Engineering Specifications

### Category A: Streak & Pattern Features

**`consecutive_unders` / `consecutive_overs`** — Games in a row under/over their Vegas line. After 3+ consecutive unders, Vegas drops line. If true ability unchanged, this is a buy-low signal.

**`line_vs_season_avg`** — `vegas_line - season_avg_points`. Negative = Vegas pricing below baseline. For Model 2 only (uses Vegas data). For Model 1, use `deviation_from_own_avg = avg_last_3 - season_avg`.

**`scoring_trend_slope`** — OLS regression slope over last 7 games. Captures rate of change, not just direction. More robust to outlier games than `recent_trend`.

### Category B: Teammate Context Features

**`teammate_usage_available`** — Sum of usage rates of all OUT teammates. Continuous metric capturing HOW MUCH opportunity is freed up, not just binary in/out. Key improvement over failed V11 `star_teammates_out`.

**`primary_scorer_present`** — Binary flag for team's top scorer by usage. The #1 scorer being out has outsized, non-linear effects on other players.

### Category C: Game Environment Features

**`game_total_line`** — Game O/U total from sportsbooks. Strong proxy for scoring environment. Captures pace, defensive quality, and game script simultaneously.

**`spread_magnitude`** — abs(point spread). Large spreads indicate expected blowouts where starters play fewer minutes. Affects stars more than role players.

### Category D: Improved Fatigue Features

**`minutes_load_last_7_days`** — Total minutes played in last 7 days. Direct measurement vs generic composite. Model can learn its own thresholds.

**`days_since_last_game`** — Continuous replacement for binary back_to_back. Values >5 signal structural breaks (injury return, ASB).

### Category E: Structural Change Detection

**`games_since_structural_change`** — Games since trade, injury return, or ASB. Value 0-2 = high uncertainty/stale averages. Value 8+ = stable context.

---

## Part 4: Classification vs. Regression Analysis

### The Fundamental Mismatch

Current system optimizes for point prediction (MAE) but the betting decision is directional (OVER/UNDER). A model accurate to +/-2 MAE can still lose money if it's on the wrong side of the line.

### Recommended: Hybrid Approach

- **Model 1:** Regression (predict points, MAE loss, no Vegas)
- **Model 2:** Classification (predict edge hit probability, log-loss)

Each model uses the loss function appropriate to its task.

### Loss Function Recommendations

**Model 1:** MAE (start), Huber delta=4 (test second). Avoid RMSE (outlier-sensitive) and quantile (creates directional bias).

**Model 2:** Binary cross-entropy (start), focal loss gamma=2 (test second for hard cases near the line).

**Kill quantile regression for Model 1.** Q43 was the source of systematic UNDER bias. Bias should come from Model 2's decision threshold, not point prediction.

---

## Part 5: Implementation Sequencing

### Phase 1: Diagnostics (Days 1-2)
Run all 5 diagnostic queries. Document findings. Decision gate.

### Phase 2: Quick Classification Test (Day 3)
Train classifier on existing features with binary OVER/UNDER target. Compare to current regressor. Takes 1-2 hours, validates loss function change.

### Phase 3: Build Vegas-Free Points Predictor (Days 4-8)
Implement P0 features (game_total, days_rest, minutes_load), then P1 (trend_slope, teammate_usage), then P2 (structural_change, position_defense).

### Phase 4: Build Edge Finder (Days 9-11)
Only after Model 1 validated. Start with logistic regression.

### Phase 5: Integration & Backtesting (Days 12-14)
Full pipeline backtest across Feb 2025, Jan 2026, Feb 2026.

---

## Success Criteria

| Metric | Minimum | Target | Stretch |
|--------|---------|--------|---------|
| Edge 3+ HR | 55% | 60% | 65%+ |
| OVER/UNDER Balance | 40/60 to 60/40 | 45/55 to 55/45 | 50/50 |
| Daily Volume | 5+ bets/day | 10+ | 15+ |
| Model 1 MAE | <= 6.0 | <= 5.5 | <= 5.0 |

## Things NOT to Do

1. Don't add monotonic constraints
2. Don't try multi-quantile ensembles
3. Don't add more historical data (without removing Vegas dependency)
4. Don't fine-tune alpha
5. Don't build residual model (single model predicting actual - vegas)
6. Don't over-engineer before diagnostics

---

## Appendix A: Model 1 Feature Changes Summary

```
KEPT (12): points_avg_season, points_std_last_10, opponent_def_rating,
  opponent_pace, home_away, team_pace, team_off_rating, games_in_last_7_days,
  pct_paint, pct_three, pct_free_throw, ppm_avg_last_10

MODIFIED (5): points_avg_last_5->last_3+last_7, points_avg_last_10->last_15,
  minutes_avg_last_10->last_5, back_to_back (keep despite low importance)

NEW (8): game_total_line, opp_pts_allowed_to_position, usage_rate_last_5,
  teammate_usage_available, minutes_load_last_7_days, days_since_last_game,
  scoring_trend_slope, games_since_structural_change

REMOVED (13): vegas_points_line, vegas_opening_line, vegas_line_move,
  has_vegas_line, fatigue_score, shot_zone_mismatch_score, injury_risk,
  playoff_game, rest_advantage, pct_mid_range, recent_trend, minutes_change,
  avg_points_vs_opponent/games_vs_opponent
```

## Appendix B: Key Questions This Document Doesn't Answer

1. Is 55% actually achievable in February 2026's market? (Diagnostics will reveal)
2. What's the right training window for Model 1? (60d? 90d? Season-to-date? Must test)
3. Should Model 1 be player-tier-specific? (Miss clustering diagnostic will inform)
4. How much does the teammate feature actually move the needle? (V11 binary failed; continuous should be better, but needs empirical validation)
5. Is CatBoost still the right algorithm? (Yes for now -- right tool for this data volume)
