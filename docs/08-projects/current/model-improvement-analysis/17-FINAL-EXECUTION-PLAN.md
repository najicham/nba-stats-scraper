# Final Execution Plan: V2 Model Architecture

**Date:** 2026-02-13 (Session 227)
**Status:** Active — executing
**Based on:** 9 experiments, 3 expert reviews, master plan (doc 16), codebase analysis

---

## Critical Evaluation of the Master Plan

### Where the 3 Reviews Agree (and I Concur)

1. **Vegas dependency is the primary structural problem.** Features 25-28 account for 20-45% of importance. Combined with Q43, the model is a "Vegas line minus a discount" machine. When Vegas is well-calibrated mid-season, this produces zero alpha. The evidence is unambiguous.

2. **Kill quantile regression for Model 1.** Q43 creates directional UNDER bias that makes OVER signals invisible. The OVER collapse (0% OVER picks in most experiments) is a direct artifact. Model 1 should predict the expected value (MAE loss), and any directional bias should emerge from the edge calculation, not the point prediction.

3. **Diagnostics before building.** We don't yet know whether Feb 2026 is an anomaly (trade deadline + ASB disruption) or a regime change (permanently tighter market). The diagnostics determine whether we're trying to build a model for a temporarily hostile environment or a permanently harder one.

4. **2-model architecture is the right starting point.** Model 1 (Vegas-free points predictor) + Model 2 (edge classifier) separates concerns correctly. Chat 2's 3-model system is over-engineered for now — the bet selector (Model 3) needs backtested outputs from Models 1 and 2 as training data, making it a Phase 3 optimization.

### Where I Disagree or See Gaps

**1. The "residual model" dead-end might not apply to Model 2.**

The master plan and Chat 3 say "don't build a residual model." But Model 2 in the final architecture IS effectively predicting residuals — "given Model 1 disagrees with Vegas by X, will the edge hit?" The prior dead-end was a *single* model predicting `actual - vegas` with the *same general features*. Model 2 with a *market-focused feature set* running *alongside* an independent Model 1 is architecturally different. I'll use Chat 3's approach (binary classifier: "will this edge hit?") rather than Chat 2's residual regression, since the binary formulation is more directly aligned with the betting decision.

**2. Sample sizes in the evaluation are dangerously small.**

Feb 2026 experiments have N=16-170 at edge 3+. At N=74 (the best experiment), a 56.8% HR has a 95% CI of roughly 45-68%. We cannot distinguish 56.8% from 50% (coin flip) or from 65% (highly profitable) at this sample size. **Critical change:** Every evaluation must report its confidence interval. No go/no-go decisions on fewer than 150 edge 3+ picks.

**3. Nobody asks: "What if the Feb 2025 79.5% was the anomaly?"**

The entire plan assumes Feb 2025 (79.5%) represents achievable steady-state performance. But 79.5% on 415 picks is extraordinary — even sharp bettors rarely sustain 60%. What if the model happened to catch an unusually exploitable market period? If Vegas was systematically too high in Feb 2025 (early-season calibration noise), and Q43's UNDER bias matched perfectly by accident, then 79.5% is unrepeatable regardless of architecture. The diagnostics (Query 1: Vegas sharpness) will reveal this. **Decision gate:** If Vegas MAE in Feb 2025 was >5.5 and in Feb 2026 is <4.5, the edge pool genuinely shrank and 55% is an ambitious target, not a minimum.

**4. `game_total_line` was already tried (V11 feature 38) and had near-zero importance.**

All 3 reviews recommend it again with re-engineering (implied team total, relative to season average). This is reasonable but needs a hard decision gate: if re-engineered game total features STILL show <1% importance, stop pushing this direction. The market may already price game environment into the player prop line.

**5. The plan underweights one critical diagnostic: actual OVER/UNDER outcome rates by month.**

If 65% of actual outcomes were UNDER in Feb 2025 (market genuinely overpricing), then Q43's UNDER bias was capturing a real pattern, not a bug. If outcomes were 50/50 in Feb 2026, the bias became actively harmful. This one measurement explains much of the decay and isn't in the diagnostic list. **Added as Query 0.**

**6. Training window for Vegas-free model may need to be longer.**

The current model performs best on 1-season (91 days) because shorter windows have fresher Vegas calibration relationships. A Vegas-free model learns basketball dynamics (matchups, fatigue, pace) that are more stable across time. Multi-season training may actually help it where it hurt the Vegas-dependent model. **Test explicitly:** 90d vs 180d vs season-to-date for Model 1.

---

## Final Architecture Decision

**Adopt the master plan's 2-model architecture with modifications:**

```
Model 1: Vegas-Free Points Predictor
  - CatBoost, MAE loss, ~25-28 features, ZERO Vegas inputs
  - Predicts actual points scored from basketball context
  - Training: Start with 90d, test longer windows

Model 2: Edge Classifier (only after Model 1 validated)
  - Binary classifier (logistic regression, then CatBoost if needed)
  - Input: Model 1's edge + market signals + context
  - Predicts: Will this edge hit? (probability)
  - Training: Current season only, rolling 90d window

Edge Calculation (post-prediction, not a model):
  - edge = model1_prediction - vegas_line
  - direction = OVER if edge > 0, UNDER if edge < 0

Bet Selection:
  - Phase 1: Simple threshold (edge >= 3 and Model 2 confidence >= 0.6)
  - Phase 3+: Learned meta-model if data supports it
```

---

## Execution Phases

### Phase 0: Diagnostics (BLOCKING)

Run 6 diagnostic queries against BigQuery. Results determine priority ordering.

**Query 0: Actual OVER/UNDER Outcome Rates by Month**
- For each month Oct 2024 - Feb 2026: what % of player-games had actual > vegas_line?
- If Feb 2025 was 40% OVER (UNDER-favorable) and Feb 2026 is 50/50, that explains the Q43 decay

**Query 1: Vegas Line Sharpness Comparison**
- Monthly `abs(actual_points - vegas_line)` MAE: Oct 2024 through Feb 2026
- Segment by player tier (stars 25+ ppg, mid 15-25, role <15)
- If Vegas MAE dropped materially, the edge pool shrunk

**Query 2: Trade Deadline Impact**
- Identify players whose team changed between Jan and Feb 2026
- Compare: stable-roster edge 3+ HR vs traded-player edge 3+ HR
- If stable-roster HR > 55%, trade disruption is the primary cause

**Query 3: Miss Clustering by Player Tier**
- Edge 3+ hit rate by: scoring tier, position, minutes consistency
- Edge 3+ hit rate by: OVER misses vs UNDER misses
- Identify the 10 worst-performing players in Feb 2026

**Query 4: OVER/UNDER Prediction Distribution**
- Distribution of `model_prediction - vegas_line` for Feb 2025 vs Feb 2026
- Mean, median, std of the edge distribution in both periods
- Confirms whether OVER collapse is Q43 artifact or genuine signal loss

**Query 5: Feature Drift Detection**
- For top 10 features by importance: compare mean/std in training window vs Feb 2026 eval
- Flag features where |eval_mean - train_mean| > 1 * train_std

**Decision Gate After Diagnostics:**

| Finding | Action |
|---------|--------|
| Feb 2025 was genuinely UNDER-favorable (>55% unders) | Q43 captured real pattern; Vegas-free model still right, but temper expectations |
| Vegas MAE dropped >1.0 from Feb 2025 to Feb 2026 | Edge pool shrunk; target 53-55%, reduce volume |
| Stable-roster HR > 55% (trade disruption is the cause) | Fast-track structural break features (games_since_trade) |
| Misses cluster on stars (25+ ppg) | Consider tier filtering (only bet mid/role tier) |
| OVER collapse confirmed as Q43 artifact | Proceed with MAE loss (confirmed) |
| Feature drift detected in rolling averages | Shorter averages (last_3, last_7) or feature normalization |

### Phase 1A: Quick Vegas-Free Baseline (~30 min)

**Can run in parallel with diagnostics.**

Train current CatBoost with features 25-28 removed, MAE loss, no quantile. Evaluate on:
- Feb 2025 (DraftKings lines) — expect ~65-75%
- Feb 2026 (production lines) — expect ~50-55%
- Jan 2026 — additional validation

**This is the single most important experiment.** It validates whether removing Vegas + MAE loss is directionally correct before any feature engineering.

**Command:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "VEGASFREE_BASELINE" \
    --no-vegas \
    --loss-function MAE \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-12
```

**Success gate for 1A:**
- OVER picks exist (>10% of edge 3+ picks are OVER) — if yes, Vegas removal fixes directional bias
- Edge 3+ HR > 50% on Feb 2026 — if yes, approach is viable
- Edge 3+ HR > 60% on Feb 2025 — if yes, architecture isn't broken
- Both OVER and UNDER HR > 45% — no catastrophic directional failure

**If 1A fails** (edge 3+ HR < 48% on Feb 2025 AND Feb 2026): The problem is deeper than Vegas dependency. Pivot to investigating whether CatBoost can predict points at all without Vegas as a crutch. May need fundamentally different features before removing Vegas.

### Phase 1B: P0 New Features (Low Complexity, High Signal)

Only proceed after 1A shows promise (>50% edge 3+ on Feb 2026 OR >60% on Feb 2025).

Add these features to the Vegas-free model:

| Feature | Source | Computation |
|---------|--------|-------------|
| `days_since_last_game` | game_date arithmetic | Simple date diff from game logs |
| `scoring_trend_slope` | player_game_summary | OLS slope over last 7 games |
| `minutes_load_last_7d` | player_game_summary | Sum of minutes in last 7 days |
| `deviation_from_avg_last_3` | game logs | (avg_last_3 - season_avg) / std |

**Why these 4 first:** They're all computable from existing BigQuery tables with simple queries, address known gaps (fatigue measurement, trend capture, mean-reversion), and don't require new data sources.

**Evaluation:** Train, evaluate on Feb 2025 + Feb 2026. Compare to 1A baseline. Only keep features that improve or don't hurt.

### Phase 1C: P1 New Features (Medium Complexity)

| Feature | Source | Computation |
|---------|--------|-------------|
| `game_total_line` | odds_api_game_totals | Game O/U total from Odds API |
| `implied_team_total` | odds_api (total + spread) | (game_total +/- spread) / 2 |
| `spread_magnitude` | odds_api | abs(point spread) |
| `teammate_usage_available` | injury_report + game_summary | Sum of usage rates for OUT teammates |

**Decision gate:** If `game_total_line` still shows <1% importance even in Vegas-free context, drop all game-total-derived features and don't revisit.

### Phase 1D: P2 New Features (Higher Complexity)

| Feature | Source | Computation |
|---------|--------|-------------|
| `games_since_structural_change` | roster transactions + schedule | Games since trade/ASB/return from injury |
| `consecutive_games_below_avg` | game logs | Streak of games under season average |

**Evaluation:** Compare full Model 1 (Phase 1B+C+D features) vs 1A baseline. If overall performance improved, lock in feature set. If specific features hurt, drop them.

### Phase 2: Edge Classifier (Model 2)

**Only build after Model 1 is validated (edge 3+ HR > 52% on multi-month backtest).**

Model 2 filters Model 1's edges to identify which ones are more likely to hit.

**Feature set (~10 features):**
- `raw_edge_size` — |model1_pred - vegas_line|
- `edge_direction` — OVER (+1) or UNDER (-1)
- `vegas_line_move` — opening to current line movement
- `line_vs_season_avg` — vegas_line - player_season_avg
- `multi_book_line_std` — std dev of lines across sportsbooks
- `player_volatility` — points_std_last_10
- `consecutive_overs_or_unders` — streak vs own average
- `game_total_line` — scoring environment
- `games_since_structural_change` — roster stability
- `model1_mae_for_player_last_10` — how well Model 1 predicts this specific player

**Training:** Binary cross-entropy, only on rows with Model 1 edge >= 2 points.

**Algorithm:** Start with logistic regression (interpretable, fast). Upgrade to CatBoost classifier if logistic doesn't beat Model 1 alone.

### Phase 3: Integration + Full Backtest

Wire Models 1+2 together. Evaluate on 4 monthly windows:
- Oct-Nov 2025 (early season, markets least efficient)
- Dec 2025-Jan 2026 (mid-season baseline)
- Feb 2025 (known good benchmark)
- Feb 2026 (problem period)

**Minimum 150 edge 3+ picks per window for conclusions.**

### Phase 4: Production Integration (only after backtest passes)

- Shadow test alongside current champion
- Monitor for 2+ weeks
- Follow governance gates
- No deployment without explicit approval

---

## Feature Set Summary

### Model 1: Vegas-Free Points Predictor (~25-28 features)

```
KEPT FROM V9 (12):
  points_avg_season, points_std_last_10, opponent_def_rating,
  opponent_pace, home_away, team_pace, team_off_rating,
  games_in_last_7_days, pct_paint, pct_three, pct_free_throw,
  ppm_avg_last_10

MODIFIED (3):
  points_avg_last_5 -> points_avg_last_5 (keep, add last_3 and last_7)
  points_avg_last_10 -> points_avg_last_10 (keep)
  minutes_avg_last_10 -> minutes_avg_last_10 (keep)

NEW — P0 (4):
  days_since_last_game, scoring_trend_slope,
  minutes_load_last_7d, deviation_from_avg_last_3

NEW — P1 (4):
  game_total_line, implied_team_total, spread_magnitude,
  teammate_usage_available

NEW — P2 (2):
  games_since_structural_change, consecutive_games_below_avg

REMOVED (13):
  vegas_points_line (25), vegas_opening_line (26),
  vegas_line_move (27), has_vegas_line (28),
  fatigue_score (5), shot_zone_mismatch_score (6),
  injury_risk (10), playoff_game (17), rest_advantage (9),
  pct_mid_range (19), recent_trend (11), minutes_change (12),
  back_to_back (16)

KEPT BUT MONITORED (3):
  pace_score (7), usage_spike_score (8), avg_points_vs_opponent (29)
  — Drop if <1% importance in Vegas-free context
```

### Model 2: Edge Classifier (~10 features)

```
  raw_edge_size, edge_direction, vegas_line_move,
  line_vs_season_avg, multi_book_line_std, player_volatility,
  consecutive_overs_or_unders, game_total_line,
  games_since_structural_change, model1_mae_for_player_last_10
```

---

## Dead Ends (Do NOT Revisit)

| Approach | Why Not |
|----------|---------|
| Monotonic constraints | Increases Vegas dependency |
| Multi-quantile ensemble | Volume collapse, opposing biases |
| Alpha fine-tuning (Q42/Q43/Q44) | Marginal, wrong lever |
| Two-stage sequential pipeline | Cascading errors |
| 3+ season training with Vegas features | More data = worse when learning Vegas patterns |
| Neural networks | Wrong tool for <50K rows of tabular data |
| Micro-retraining alone | 14-day window still gets 50% — freshness isn't the issue |
| Play-by-play features (for now) | High engineering cost, uncertain ROI — revisit after Phase 2 if needed |

---

## Success Criteria

| Metric | Minimum | Target | Stretch |
|--------|---------|--------|---------|
| Edge 3+ HR (multi-month backtest avg) | 55% | 58% | 62%+ |
| Edge 5+ HR | 57% | 62% | 70%+ |
| OVER hit rate | 50%+ | 55%+ | 60%+ |
| UNDER hit rate | 50%+ | 55%+ | 60%+ |
| Directional balance (OVER % of picks) | 25-75% | 35-65% | 40-60% |
| Daily pick volume (edge 3+) | 3+ | 5-10 | 10-15 |
| Model 1 MAE | <= 6.0 | <= 5.5 | <= 5.0 |

## Kill Criteria

- Edge 3+ HR < 52.4% on 3+ month backtest after Phase 2 complete: system not profitable
- OVER collapse persists after removing Vegas + Q43: problem is deeper than architecture
- Phase 1A baseline < 48% on both Feb 2025 and Feb 2026: CatBoost can't predict points without Vegas — need to investigate whether independent signal exists at all
