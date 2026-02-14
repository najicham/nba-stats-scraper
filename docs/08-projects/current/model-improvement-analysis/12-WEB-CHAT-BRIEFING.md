# NBA Player Props Model — Expert Review Briefing

## What This Document Is

This is a comprehensive briefing for an external review of our NBA player props prediction system. We're looking for fresh perspectives on our model architecture, feature engineering, and strategy after hitting a performance wall in February 2026. Please review everything below and provide your analysis, critiques, and suggestions.

---

## 1. System Overview

We predict NBA player points scored for over/under prop bets. The goal is 55%+ accuracy on bets with edge >= 3 points (52.4% is breakeven after vig).

**Current model:** CatBoost gradient-boosted decision tree
- 33 features
- Quantile regression (alpha=0.43, biases predictions slightly under median)
- Trained on ~60-90 days of current season data
- At launch: 71.2% hit rate on edge 3+ bets, 79.0% on edge 5+
- **Current state: decayed to ~40% hit rate (39.9%), well below breakeven**

---

## 2. Current Features (33 Total)

### Player Recent Performance (indices 0-4)
| # | Feature | Description |
|---|---------|-------------|
| 0 | `points_avg_last_5` | Average points last 5 games |
| 1 | `points_avg_last_10` | Average points last 10 games |
| 2 | `points_avg_season` | Season scoring average |
| 3 | `points_std_last_10` | Scoring volatility (standard deviation) |
| 4 | `games_in_last_7_days` | Schedule density |

### Composite Factors (indices 5-8)
| # | Feature | Description |
|---|---------|-------------|
| 5 | `fatigue_score` | Generic fatigue composite |
| 6 | `shot_zone_mismatch_score` | How player's shot profile matches vs opponent's defense zones |
| 7 | `pace_score` | Expected pace impact on scoring |
| 8 | `usage_spike_score` | Unusual usage rate changes |

### Derived Context (indices 9-12)
| # | Feature | Description |
|---|---------|-------------|
| 9 | `rest_advantage` | Rest days differential vs opponent |
| 10 | `injury_risk` | Generic injury risk factor |
| 11 | `recent_trend` | Recent scoring trajectory (up/down) |
| 12 | `minutes_change` | Recent minutes change |

### Matchup Context (indices 13-17)
| # | Feature | Description |
|---|---------|-------------|
| 13 | `opponent_def_rating` | Opponent's defensive efficiency |
| 14 | `opponent_pace` | Opponent's pace of play |
| 15 | `home_away` | Home (1) or away (0) |
| 16 | `back_to_back` | Second game of back-to-back (1/0) |
| 17 | `playoff_game` | Playoff game indicator (always 0 in regular season) |

### Shot Zone Tendencies (indices 18-21)
| # | Feature | Description |
|---|---------|-------------|
| 18 | `pct_paint` | % of shots from paint |
| 19 | `pct_mid_range` | % of shots from mid-range |
| 20 | `pct_three` | % of shots from three-point range |
| 21 | `pct_free_throw` | Free throw rate |

### Team Context (indices 22-24)
| # | Feature | Description |
|---|---------|-------------|
| 22 | `team_pace` | Player's team pace |
| 23 | `team_off_rating` | Player's team offensive rating |
| 24 | `team_win_pct` | Player's team win percentage |

### Vegas/Betting Lines (indices 25-28)
| # | Feature | Description |
|---|---------|-------------|
| 25 | `vegas_points_line` | Current sportsbook points prop line |
| 26 | `vegas_opening_line` | Opening points prop line |
| 27 | `vegas_line_move` | Line movement (current - opening) |
| 28 | `has_vegas_line` | Whether a Vegas line exists (1/0) |

### Opponent History (indices 29-30)
| # | Feature | Description |
|---|---------|-------------|
| 29 | `avg_points_vs_opponent` | Historical scoring avg vs this specific opponent |
| 30 | `games_vs_opponent` | Number of games played vs this opponent |

### Minutes/Efficiency (indices 31-32)
| # | Feature | Description |
|---|---------|-------------|
| 31 | `minutes_avg_last_10` | Average minutes last 10 games |
| 32 | `ppm_avg_last_10` | Points per minute last 10 games |

---

## 3. Feature Importance (Observed Across 9 Experiments)

Features consistently ranked by importance:

**Dominant (>5% importance consistently):**
- `vegas_points_line` (15-30%)
- `points_avg_last_5` (6-35%)
- `points_avg_last_10` (8-13%)
- `vegas_opening_line` (4-14%)
- `points_avg_season` (4-15%)
- `ppm_avg_last_10` (2-10%)

**Moderate (1-5%):**
- `minutes_avg_last_10` (2-6%)
- `opponent_def_rating` (1.9-3.1%)
- `points_std_last_10` (1.9-4.1%)
- `usage_spike_score` (0.9-1.9%)
- `vegas_line_move` (1.9-4.0%)

**Near-zero importance (< 0.3% consistently):**
- `injury_risk` (0.00-0.14%)
- `back_to_back` (0.00-0.24%)
- `playoff_game` (0.00-0.10%)
- `rest_advantage` (0.07-0.30%)
- `has_vegas_line` (0.10-0.30%)

---

## 4. Experiment Results

We ran 9 experiments to investigate why the model decayed and whether multi-season training, recency weighting, or micro-retraining could fix it.

### Key Bug Fixed First
We discovered that `--train-start` and `--train-end` parameters were silently ignored unless eval dates were also provided. All previous "multi-season" experiments actually trained on 60-day windows. This was fixed before running these experiments.

### Phase 1: Data Quality Validation
- 2,000-3,000 trainable rows per month during regular season across 3 seasons
- Hidden default contamination < 1.5% (negligible)
- Data quality is not the bottleneck

### Phase 2: Multi-Season Training (All eval on Feb 1-11, 2026)

| Experiment | Training Window | Samples | Edge 3+ HR | N | OVER HR | UNDER HR | MAE | Vegas Bias |
|-----------|----------------|---------|-----------|---|---------|----------|-----|------------|
| 1-season Q43 | Nov'25-Jan'26 (91d) | 9,746 | **56.8%** | 74 | 0% (1) | 57.5% (73) | 5.12 | -1.51 |
| 2-season Q43 + 120d recency | Dec'24-Jan'26 (427d) | 23,826 | 53.3% | 60 | 0% (1) | 54.2% (59) | 5.11 | -1.47 |
| 2-season Baseline (no quantile) | Dec'24-Jan'26 (427d) | 23,826 | 51.9% | 54 | 45.2% (31) | 60.9% (23) | **5.02** | **+0.05** |
| 3-season Q43 | Dec'23-Jan'26 (793d) | 37,824 | 50.0% | 170 | 47.8% (23) | 50.3% (147) | 5.32 | -1.45 |
| 2-season Q43 | Dec'24-Jan'26 (427d) | 23,826 | 49.5% | 91 | 33.3% (3) | 50.0% (88) | 5.12 | -1.35 |

### Phase 3: Cross-Season Backtesting (Is February always bad?)

| Experiment | Training | Eval Period | Edge 3+ HR | N | OVER HR | UNDER HR | Gates |
|-----------|----------|-------------|-----------|---|---------|----------|-------|
| Train → Jan'25, Eval **Feb 2025** | Dec'23-Jan'25 | Feb 1-28, 2025 | **79.5%** | **415** | **82.6%** (86) | **78.7%** (329) | **ALL PASS** |
| Train → Jan'26, Eval **Feb 2026** | Dec'24-Jan'26 | Feb 1-11, 2026 | 53.8% | 132 | 66.7% (6) | 53.2% (126) | FAIL |

### Phase 4: Micro-Retrains (Freshest possible data)

| Experiment | Training | Eval | Edge 3+ HR | N | MAE |
|-----------|----------|------|-----------|---|-----|
| 14-day micro Q43 | Jan 29 - Feb 7 | Feb 8-12 | 50.0% | 24 | 4.68 |
| Hybrid 14d + 2-season | Dec'24 - Feb 7 (14d recency) | Feb 8-12 | 50.0% | 16 | 4.60 |

---

## 5. Key Findings

### Finding 1: The Model Architecture Works
The same Q43 CatBoost approach scored **79.5% edge 3+ HR** on February 2025 with perfect directional balance (82.6% OVER, 78.7% UNDER). The architecture is sound.

### Finding 2: February 2026 Is Uniquely Hostile
Every single configuration — 1-season, 2-season, 3-season, recency-weighted, baseline, micro-retrained — fails on February 2026. The problem is in the eval period, not the training approach.

### Finding 3: More Data Makes It Worse (In Feb 2026)
1-season (56.8%) > 2-season (49.5%) > 3-season (50.0%). Adding historical data dilutes the model's ability to track current dynamics.

### Finding 4: Universal OVER Collapse
Across ALL 9 experiments on Feb 2026 data, the OVER direction is broken:
- Most experiments generate near-zero OVER picks
- When they do generate OVER picks, hit rate is terrible (0-47%)
- UNDER direction is always better (50-61%)
- The Feb 2025 backtest showed perfect OVER (82.6%) — so this isn't structural to the approach

### Finding 5: Vegas Dependence Is the Root Cause
The model's #1 feature is `vegas_points_line` at 15-30% importance. With quantile alpha=0.43, the model learns: "predict slightly below the Vegas line." This creates artificial UNDER bias and makes edge-finding impossible when Vegas is well-calibrated.

### Finding 6: Micro-Retraining Doesn't Help
Even training on just the last 14 days (freshest possible data) gets 50%. The model can't learn from the current regime fast enough because the fundamental approach (Vegas-dependent) doesn't work in this environment.

---

## 6. Hypotheses & Ideas for Discussion

### Hypothesis A: Two-Model Architecture

**Model 1 — Points Predictor (no Vegas input):**
- Predicts actual points scored
- Features: player averages, matchup, fatigue, pace, shot zones
- Excludes Vegas lines entirely
- Trained to minimize MAE on actual points
- This learns "true expected scoring"

**Model 2 — Edge Finder (Vegas-centric):**
- Only trains on players WITH Vegas lines
- Target: `actual_points - vegas_line` (the residual/mispricing)
- Or: binary OVER/UNDER classification
- Learns systematic Vegas biases
- Key question: does Vegas consistently misprice certain situations?

**Combined signal:** Both models agree → high confidence. Disagreement → lower size or skip.

### Hypothesis B: Streak/Pattern Features

We currently have rolling averages but NO streak indicators. Ideas:
- `consecutive_unders` / `consecutive_overs` — games in a row under/over the line
- `deviation_from_avg_last_3` — running hot or cold vs own baseline
- `line_vs_season_avg` — is Vegas pricing below their season average (buy-low signal)
- `post_cold_streak_bounce` — historical bounce-back rate after 2+ unders

**The theory:** When a player goes under 2-3 games in a row, Vegas drops the line. If their true talent hasn't changed, this is a systematic buying opportunity. Is this player-specific or league-wide? Both could be features.

### Hypothesis C: Fatigue Feature Rethink

Current `fatigue_score` is a generic composite with near-zero importance. Ideas:
- Minutes load last 7 days (cumulative minutes, not just game count)
- Travel distance / timezone changes
- Minutes variance (high-minute spikes are more fatiguing than steady high minutes)
- Close-game minutes vs blowout minutes (competitive intensity)

### Hypothesis D: February 2026 Structural Causes

What's special about February 2026?
- **Trade deadline:** Traded players change teams, roles, minutes instantly
- **All-Star break:** ~1 week layoff mid-February, disrupts rhythm and averages
- **Rotation changes:** Teams experimenting with lineups, resting players for playoffs
- **Our rolling averages become stale:** `points_avg_last_5` includes pre-break games that may be irrelevant
- **Vegas may be more accurate in Feb:** Markets tighten as season data accumulates, reducing edges

### Hypothesis E: Feature Reduction vs Expansion

Dead features to consider dropping (near-zero importance across all experiments):
- `injury_risk`, `back_to_back`, `playoff_game`, `rest_advantage`, `has_vegas_line`

This would reduce from 33 to 28 features. Simpler models can sometimes generalize better.

Alternatively, could replace them with higher-signal features:
- Streak indicators (see Hypothesis B)
- Better fatigue metrics (see Hypothesis C)
- Teammate context (star player in/out — affects role/usage)
- Game total line (proxy for expected game pace/scoring environment)

### Hypothesis F: Time-Aware Training

Instead of treating all training data equally:
- Apply exponential decay weighting (recent games worth more)
- Use separate models per season phase (early season, mid-season, post-ASB, playoff push)
- Consider that player roles shift during the season — early-season data may mislead

### Hypothesis G: Different Loss Function for Betting

RMSE/MAE optimizes for point prediction accuracy. But we're betting over/under.

Consider:
- **Classification loss:** Train directly on OVER/UNDER outcome
- **Asymmetric loss:** Penalize wrong-direction errors more than magnitude errors
- **Custom betting loss:** Weight errors by edge size (wrong on high-edge bets is worse)

---

## 7. Available Data Sources We Haven't Fully Exploited

| Data Source | Current Use | Potential Use |
|-------------|-------------|---------------|
| Play-by-play data | Not used in features | Shot quality, clutch performance, garbage time identification |
| Injury reports | Binary injury_risk (low importance) | Teammate injuries (creates opportunity), opponent injuries |
| Line movement data | `vegas_line_move` (opening vs current) | Sharp money detection, reverse line movement |
| Multi-sportsbook odds | Have 10+ books via Odds API | Consensus vs outlier lines, market disagreement signal |
| Game totals (O/U) | Not used | Proxy for expected pace, high-scoring game environment |
| Historical prop line accuracy | Not used | Which sportsbooks are consistently beatable |
| Player minutes projections | Not used | Could use season-average minutes as a feature cap |

---

## 8. Dead Ends (Already Tried, Don't Revisit)

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| Monotonic constraints | +15-27pp Vegas dependency | Forces model to always increase prediction with Vegas line |
| V10 features (opp_defense, days_rest, line_movement) | 2-3% importance | Redundant with existing features |
| V11 features (star_teammates_out, game_total_line) | Near-zero importance | Need better calculation method |
| Multi-quantile ensemble (Q40+Q43+Q45) | Volume collapse | Opposing biases cancel out |
| Alpha fine-tuning (Q42 vs Q43 vs Q44) | Marginal differences | Not the right lever |
| Residual mode (predict actual - vegas) | Poor calibration | Model couldn't learn residuals well |
| Two-stage pipeline | Complexity without benefit | Added noise at each stage |
| Grow policy changes | Marginal | Not addressing root cause |

---

## 9. Questions for the Reviewer

1. **Is our feature set fundamentally wrong for this task?** We have 33 features, but 5-6 of them do nothing. Are we missing critical signals?

2. **Should we be predicting points or predicting over/under directly?** These are different tasks with different optimal features and loss functions.

3. **How should we handle the Vegas line?** It's simultaneously our most informative feature and possibly the reason we can't find edges. What's the right relationship?

4. **Is quantile regression the right approach for betting?** Alpha=0.43 creates systematic UNDER bias. Is there a better way to calibrate for profitable betting?

5. **What features from play-by-play data would be most valuable?** We have every possession logged but haven't extracted features from it.

6. **How should we handle regime changes (trade deadline, All-Star break)?** Our current rolling averages don't account for structural breaks in player situations.

7. **Is there a better model architecture entirely?** We're using CatBoost (gradient-boosted trees). Should we consider neural nets, ensembles of different model types, or something else?

8. **How do professional sports bettors approach feature engineering?** Are there standard features in the literature we're missing?

9. **Given that Feb 2025 scored 79.5% with the same approach, is Feb 2026 just an anomaly?** Should we wait it out, or is this a sign the market has adapted?

10. **What's the minimum viable improvement?** If we can't get back to 70%+, what's the smallest change that could get us above 55% consistently?
