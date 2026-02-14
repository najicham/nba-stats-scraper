# Master Implementation Plan: V2 Model Architecture

**Date:** 2026-02-12
**Status:** Ready for implementation
**Based on:** 9 experiments + 3 independent expert reviews (Chats 1-3)

---

## Consensus Across All 3 Reviews

All three independent reviews converged on the same diagnosis and solution:

| Topic | Chat 1 | Chat 2 | Chat 3 | Consensus |
|-------|--------|--------|--------|-----------|
| Root cause | Vegas dependency + OVER collapse | Vegas echo, not basketball predictor | Vegas dependency + structural breaks | **Vegas dependency is THE problem** |
| #1 priority | Vegas-free points predictor | Vegas-free points predictor (Model 1) | Vegas-free points predictor | **Unanimous: build Vegas-free model FIRST** |
| Architecture | 2-model (points + edge) | 3-model (points + market + bet selector) | 2-model (points + edge classifier) | **2-model minimum, 3rd model optional** |
| Diagnostics first? | Yes (5 analyses) | Mentioned | Yes (5 queries, before building) | **Run diagnostics before any model changes** |
| Kill quantile regression | Yes | Yes (predict Q50/median) | Yes (source of UNDER bias) | **Unanimous: no more Q43** |
| Features to drop | 5 dead features | Same 5 | Same 5 + more aggressive pruning | **Drop: injury_risk, back_to_back, playoff_game, rest_advantage, has_vegas_line** |
| Streak features | Yes (3-4 features) | Yes (4 features) | Yes (3 features, detailed specs) | **Unanimous: add streak/pattern features** |
| Teammate context | Usage vacuum (continuous) | Usage vacuum + lineup stability | Usage available + primary scorer flag | **Continuous usage metric, not binary flag** |
| Game environment | implied_team_total, pace_diff | game_total + spread + implied team total | game_total + spread_magnitude | **Game total line + spread** |
| Fatigue rethink | Cumulative minutes, spike detection | 5 new fatigue features | minutes_load_7d + days_since_last_game | **Replace composite with direct measurements** |
| Structural breaks | days_since_last_game, trade detection | days_since_trade, ASB awareness | games_since_structural_change | **Must handle trades + ASB explicitly** |
| Loss function | MAE for points, classification for edge | Huber for points, log-loss for edge | MAE for points, log-loss for edge | **MAE/Huber for Model 1, log-loss for Model 2** |
| Training window | Multi-season may help Vegas-free | 2+ seasons with decay weighting | 60-90d (but test longer for Vegas-free) | **Start 90d, test longer since no Vegas** |

---

## Implementation Plan

### Phase 0: Diagnostics (BLOCKING — do before any model changes)

Run 5 diagnostic queries to understand WHY February 2026 fails. Results determine priorities.

**Query 1: Vegas Line Sharpness** — Has Vegas MAE decreased in Feb 2026 vs Feb 2025? (determines if edges still exist)

**Query 2: Trade Deadline Impact** — What % of edge 3+ misses involve traded/affected players? (determines if roster instability is the cause)

**Query 3: Miss Clustering** — Are misses uniform or clustered by player tier, direction, date, or game context? (determines what's specifically broken)

**Query 4: OVER/UNDER Asymmetry** — Distribution of `model_prediction - vegas_line` for Feb 2025 vs Feb 2026. (confirms OVER collapse mechanism)

**Query 5: Feature Drift** — Have top features shifted distribution between training and eval periods? (determines if model is extrapolating)

**Decision gate after diagnostics:**

| Finding | Action |
|---------|--------|
| Vegas MAE dropped significantly | Lower volume expectations, focus on larger edges only |
| Trade deadline explains >30% of misses | Prioritize structural break features (Phase 2C) |
| Misses cluster on stars | Consider tier-specific models or star-avoidance filter |
| OVER collapse confirmed as Q43 artifact | Confirms Vegas-free + MAE loss approach |
| Feature drift detected | Shorter training window or feature normalization |

### Phase 1: Vegas-Free Points Predictor (Model 1)

**This is the single most impactful change.** All 3 reviews agree.

**Step 1A: Quick baseline** — Train existing CatBoost with features 25-28 (Vegas) removed, MAE loss, no quantile. Evaluate on Feb 2025 AND Feb 2026. This takes ~30 minutes and validates the approach before any feature engineering.

**Step 1B: Implement P0 new features** (low complexity, high signal):
- `game_total_line` — from Odds API (already scraped)
- `days_since_last_game` — date arithmetic on game logs
- `minutes_load_last_7_days` — rolling sum of minutes
- `spread_magnitude` — from Odds API

**Step 1C: Implement P1 new features** (medium complexity):
- `scoring_trend_slope` — OLS regression slope over last 7 games
- `teammate_usage_available` — sum of usage rates for OUT teammates
- `usage_rate_last_5` — from play-by-play or analytics
- `deviation_from_avg_last_3` — (avg_last_3 - season_avg) / std

**Step 1D: Implement P2 new features** (higher complexity):
- `games_since_structural_change` — trade/injury/ASB event detection
- `opp_pts_allowed_to_position` — position-level defensive stats
- `primary_scorer_present` — binary flag for team's top scorer

**Evaluation after each step:** Train, evaluate on Feb 2025 + Feb 2026, compare MAE and directional accuracy to baseline. Only keep features that improve performance.

**Model 1 feature set (target: ~25 features, 0 Vegas):**

```
KEPT (12): points_avg_season, points_std_last_10, opponent_def_rating,
  opponent_pace, home_away, team_pace, team_off_rating, games_in_last_7_days,
  pct_paint, pct_three, pct_free_throw, ppm_avg_last_10

MODIFIED (3): points_avg_last_5→last_3+last_7, points_avg_last_10→last_15,
  minutes_avg_last_10→last_5

NEW (8-10): game_total_line, spread_magnitude, days_since_last_game,
  minutes_load_last_7_days, scoring_trend_slope, teammate_usage_available,
  usage_rate_last_5, games_since_structural_change,
  [opp_pts_allowed_to_position, primary_scorer_present]

REMOVED (13): vegas_points_line, vegas_opening_line, vegas_line_move,
  has_vegas_line, fatigue_score, shot_zone_mismatch_score, injury_risk,
  playoff_game, rest_advantage, pct_mid_range, recent_trend, minutes_change,
  [avg_points_vs_opponent or games_vs_opponent if noisy]
```

**Success criteria for Model 1:**
- MAE within 0.5 of Vegas MAE (acceptable: 5.5 if Vegas is 5.0)
- Directional balance: 30-70% OVER picks (not the current ~0%)
- Edge 3+ HR > 52% across multiple eval months
- Generates BOTH over AND under signals naturally

### Phase 2: Edge Finder (Model 2)

**Only build after Model 1 is validated.**

Model 2 is a binary classifier: "Given that Model 1 disagrees with Vegas by X points, will the edge hit?"

**Feature set (~10-12 features):**
- `raw_edge_size` — |model1_prediction - vegas_line|
- `edge_direction` — +1 (OVER) or -1 (UNDER)
- `vegas_line_move` — opening to current line movement
- `line_vs_season_avg` — vegas_line - player_season_avg
- `multi_book_consensus` — std dev across sportsbooks
- `player_volatility` — points_std_last_10
- `streak_indicator` — consecutive overs/unders vs own average
- `roster_stability` — games_since_structural_change
- `game_total_line` — high-total games have more variance

**Training approach:**
- Only train on rows where Model 1 edge >= 2 points
- Target: 1 if edge hit, 0 if miss
- Loss: binary cross-entropy (log-loss)
- Algorithm: Logistic regression first, CatBoost classifier if needed
- Calibrate probabilities (Platt scaling)

**Decision rules:**
```
IF raw_edge >= 3 AND model2_confidence >= 0.60: BET
ELIF raw_edge >= 5 AND model2_confidence >= 0.55: BET
ELSE: SKIP
```

### Phase 3: Integration & Backtesting

Wire Models 1+2 together. Backtest on:
- **Feb 2025** (known good — should hit ~70%+)
- **Jan 2026** (recent pre-decay)
- **Feb 2026** (the problem period)
- **Dec 2025** (additional validation)

Compare to current single-model results on same eval windows.

### Phase 4: Production Integration (only after backtesting passes)

- Wire into existing prediction pipeline
- Shadow test alongside current champion
- Monitor for 2+ weeks before any promotion decisions
- Follow existing governance gates

---

## Features NOT to Build (Dead Ends)

| Approach | Why Not |
|----------|---------|
| Monotonic constraints | Increases Vegas dependency |
| Multi-quantile ensemble | Volume collapse, opposing biases |
| Alpha fine-tuning (Q42/Q43/Q44) | Marginal, wrong lever |
| Residual mode (single model) | Already tried, poor calibration |
| Two-stage sequential pipeline | Cascading errors |
| More training data (3+ seasons) | Makes current model worse |
| Neural networks | Wrong tool for this data volume, CatBoost works fine |
| V10/V11 features as-is | Near-zero importance, need rethinking not recycling |

---

## Success Criteria

| Metric | Minimum | Target | Stretch |
|--------|---------|--------|---------|
| Edge 3+ HR (backtest avg) | 55% | 58% | 62%+ |
| Edge 5+ HR | 57% | 62% | 70%+ |
| OVER hit rate | 50%+ | 55%+ | 60%+ |
| UNDER hit rate | 50%+ | 55%+ | 60%+ |
| Directional balance | 25-75% | 35-65% | 40-60% |
| Daily pick volume | 3+ | 5-10 | 10-15 |
| Model 1 MAE | <= 6.0 | <= 5.5 | <= 5.0 |

## Kill Criteria

- Below 52.4% on edge 3+ after Phase 2 → system not profitable
- Persistent OVER collapse despite removing Vegas → data-level issue
- Volume below 2 picks/day → models too conservative

---

## Files Reference

| Document | Path |
|----------|------|
| Experiment results (9 experiments) | `11-SESSION-226B-FEATURE-RETHINK.md` |
| Web chat briefing (sent to reviewers) | `12-WEB-CHAT-BRIEFING.md` |
| Chat 1: Diagnostic-first analysis | `13-OPUS-CHAT-1-ANALYSIS.md` |
| Chat 2: Three-model architecture | `14-OPUS-CHAT-2-ARCHITECTURE.md` |
| Chat 3: Strategic roadmap | `15-OPUS-CHAT-3-STRATEGY.md` |
| This master plan | `16-MASTER-IMPLEMENTATION-PLAN.md` |
