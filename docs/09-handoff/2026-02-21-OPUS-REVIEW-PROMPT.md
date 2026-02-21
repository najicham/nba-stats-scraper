# System Review Prompt for Claude Opus

Copy everything below the line into a new Claude Opus chat.

---

I run a profitable NBA player props prediction system that predicts points scored and bets OVER/UNDER on sportsbook prop lines. I need you to do a comprehensive review and give me recommendations for improvement. I'll share everything about our system — models, signals, filters, retraining, performance, and tools. Please analyze it all and tell me what you'd change.

## Current Performance

**Season (Jan 1 - Feb 20, 2026): 92W-32L, 74.2% hit rate, ~+$6,000 P&L**

But performance collapsed in February:

| Month | Record | HR | Avg Edge | OVER HR | UNDER HR |
|-------|--------|-----|----------|---------|----------|
| January | 74-17 | 81.3% | 8.7 | 84.2% | 66.7% |
| February | 18-15 | 54.5% | 6.6 | 52.4% | 58.3% |

Weekly breakdown shows the decline:

| Week Start | Record | HR | Avg Edge | OVER/UNDER Split |
|------------|--------|-----|----------|------------------|
| Jan 5 | 11-3 | 78.6% | 6.6 | 11O / 3U |
| Jan 12 | 46-10 | 82.1% | 9.8 | 52O / 4U |
| Jan 19 | 11-1 | 91.7% | 6.5 | 8O / 4U |
| Jan 26 | 8-4 | 66.7% | 8.0 | 7O / 5U |
| Feb 2 | 11-6 | 64.7% | 7.0 | 11O / 6U |
| Feb 9 | 3-4 | 42.9% | 5.8 | 6O / 1U |
| Feb 16 | 2-4 | 33.3% | 5.7 | 2O / 4U |

Key observations from this data:
- January averaged 8.7 edge, February only 6.6 — the model is finding fewer high-conviction picks
- OVER dominated January (84.2% HR) but collapsed to 52.4% in February
- UNDER was always weaker (66.7% → 58.3%) but more stable
- The All-Star break (Feb 14-18) created a thin market — only 6 picks in the last 2 weeks
- Week of Jan 12 was an outlier: 56 picks at 9.8 avg edge (normally we get 5-15/week)

## The Models

### Model Architecture: CatBoost Gradient Boosting

We predict raw points scored (regression), then compare to the sportsbook prop line to calculate "edge" (how many points our prediction differs from the line). Higher edge = higher confidence.

**Champion: CatBoost V9 (33 features)**
- Hyperparameters: iterations=1000, learning_rate=0.05, depth=6, l2_leaf_reg=3, early_stopping_rounds=50
- Training window: 42-day rolling (not expanding — Session 284 found rolling +$20,720 P&L vs expanding)
- Loss: MAE (mean absolute error)
- Current model trained Jan 6 - Feb 5 (deployed Feb 18, now 13 days old)
- MAE: 4.83, Vegas bias: -0.14

**Shadow Models (5 active, all running in parallel but not driving picks):**

| Model | Features | Loss | HR (edge 3+) | N |
|-------|----------|------|--------------|---|
| V12 MAE | 50 features | MAE | 69.2% | - |
| V9 Quantile 0.43 | 33 features | Quantile | 62.6% | 115 |
| V9 Quantile 0.45 | 33 features | Quantile | 62.9% | 97 |
| V12 Quantile 0.43 | 50 features | Quantile | 61.6% | 125 |
| V12 Quantile 0.45 | 50 features | Quantile | 61.2% | 98 |

### Feature Differences: V9 (33) vs V12 (50)

**V9 features (33) — the champion:**
- Recent performance: points_avg_last_5, points_avg_last_10, points_avg_season, points_std_last_10, games_in_last_7_days
- Composite factors: fatigue_score, shot_zone_mismatch_score, pace_score, usage_spike_score
- Derived: rest_advantage, injury_risk, recent_trend, minutes_change
- Matchup: opponent_def_rating, opponent_pace, home_away, back_to_back, playoff_game
- Shot zones: pct_paint, pct_mid_range, pct_three, pct_free_throw
- Team context: team_pace, team_off_rating, team_win_pct
- Vegas lines (60% coverage): vegas_points_line, vegas_opening_line, vegas_line_move, has_vegas_line
- Opponent history: avg_points_vs_opponent, games_vs_opponent
- Minutes/efficiency: minutes_avg_last_10, ppm_avg_last_10

**V12 adds 17 more features:**
- DNP risk: dnp_rate
- Player trajectory: pts_slope_10g, pts_vs_season_zscore, breakout_flag
- Injury context: star_teammates_out, game_total_line
- Fatigue/rest: days_rest, minutes_load_last_7d
- Game environment: spread_magnitude, implied_team_total
- Scoring trends: points_avg_last_3, scoring_trend_slope, deviation_from_avg_last3, consecutive_games_below_avg
- Usage/structural: teammate_usage_available, usage_rate_last_5, games_since_structural_change
- Market signal: multi_book_line_std (cross-book line standard deviation)
- Prop line history: prop_over_streak, prop_under_streak, line_vs_season_avg, prop_line_delta

### Quantile vs MAE Loss

- MAE loss predicts the median (point estimate)
- Quantile 0.43 loss predicts the 43rd percentile (biases predictions slightly lower — theoretically better for UNDER picks)
- Quantile 0.45 predicts 45th percentile (slight low bias)
- Quantile models have different edge distributions since they systematically predict lower

### Things We've Tried That Failed
- **Two-stage pipeline (Model 1 → Model 2):** Trained a classifier on Model 1's edge to predict which edges would hit. AUC < 0.50 — the edge classifier adds no value. Pre-game features can't predict which edges hit.
- **Grow policy variations:** Different tree growth strategies — no improvement
- **CHAOS + quantile:** Randomized feature selection with quantile loss — no improvement
- **Residual mode:** Training on (actual - vegas_line) instead of raw points — didn't improve
- **Expanding training window:** Using all data from season start — rolling 42-day window is +$20,720 better
- **Recency weighting:** Exponential decay by training date — no significant improvement
- **V9+V12 consensus as a positive signal:** When both models agree, it's actually ANTI-correlated with winning (OVER + V12 agrees: 33.3% HR vs V12 no pick: 66.8%)

## The Signal System

### Architecture

Signals are NOT used for pick selection — they're used for filtering (removing bad picks) and annotation (explaining why a pick was made). The model's edge IS the primary signal.

**Key insight (Session 297):** When we used signals to score and rank picks (composite scoring), we got 59.8% HR. When we switched to edge-first ranking with signals only for filtering, we got 71.1% HR. The signals were selecting low-edge picks and diluting the model's high-edge winners.

### 18 Active Signals

**Production (always evaluated):**

| Signal | Category | Direction | HR | Notes |
|--------|----------|-----------|------|-------|
| model_health | Meta | BOTH | 52.6% | Always fires, baseline qualifier |
| high_edge | Edge | BOTH | 66.7% | edge >= 5 |
| edge_spread_optimal | Edge | BOTH | 67.2% | Optimal edge/spread combo |
| combo_he_ms | Combo | OVER only | 94.9% | high_edge + minutes_surge together |
| combo_3way | Combo | OVER only | 95.5% | ESO + HE + MS together |
| bench_under | Market-Pattern | UNDER | 76.9% | N=156, top standalone signal |
| prop_line_drop_over | Market-Pattern | OVER | 71.6% | Line dropped 2+ pts from previous game |

**Conditional (require specific context):**

| Signal | Direction | HR | Condition |
|--------|-----------|------|-----------|
| 3pt_bounce | OVER | 74.9% | Guards + Home only |
| b2b_fatigue_under | UNDER | 85.7% | Back-to-back games (N=14, small) |
| high_ft_under | UNDER | 64.1% | FTA >= 7 |
| rest_advantage_2d | BOTH | 64.8% | 2+ days rest, but decays: W6=63.6%, W7=40% |

**Watch (monitoring, not actionable yet):**

| Signal | Direction | HR | Notes |
|--------|-----------|------|-------|
| book_disagreement | BOTH | 93.0% | Cross-book line stddev (very small N) |
| self_creator_under | UNDER | 61.8% | |
| volatile_under | UNDER | 60.0% | |
| high_usage_under | UNDER | 58.7% | |
| blowout_recovery | OVER | 56.9% | Stable 55-58% |
| minutes_surge | BOTH | 53.7% | W4 decay |
| cold_snap | OVER | N/A | N=0 in backtest windows |

**14 signals removed** (below breakeven or never fire): hot_streak_2 (45.8%), hot_streak_3 (47.5%), cold_continuation_2 (45.8%), fg_cold_continuation (49.6%), dual_agree (44.8%), model_consensus_v9_v12 (45.5%), and 8 others that never fired.

### Signal Health Tracking

Each signal has a daily health regime:
- **HOT** (divergence > +10): Signal overperforming, gets 1.2x weight in annotations
- **NORMAL** (-10 to +10): Expected performance, 1.0x weight
- **COLD** (divergence < -10): Signal underperforming
  - Behavioral signals: 0.5x weight
  - Model-dependent signals (high_edge, edge_spread_optimal, combos): 0.0x weight (effectively disabled)

Health is computed from `divergence_7d_vs_season` — how much the 7-day HR deviates from season HR.

### Combo Registry (11 SYNERGISTIC combos)

Validated signal combinations with specific hit rates:
- ESO+HE+MS (3-way): 95.5% HR, OVER only
- HE+MS: 79.4% HR (ROI: 58.8%), OVER only
- cold_snap (HOME): 93.3% HR, OVER only
- bench_under: 76.9% HR (ROI: 46.7%), UNDER only
- 3pt_bounce (Guards+Home): 74.9% HR, OVER only

## The Best Bets Algorithm

### Pick Selection (Edge-First Architecture)

```
1. Start with ALL active predictions for today
2. Query all CatBoost model families (not just champion) — pick highest edge per player
3. Apply negative filters (see below)
4. Require MIN_SIGNAL_COUNT = 2 (model_health + 1 real signal)
5. Rank remaining picks by edge descending
6. Return ALL qualifying picks (natural sizing — no artificial cap)
7. Attach signal annotations (pick angles) for explanations
```

### Negative Filters (12 total, in order)

| # | Filter | Threshold | HR When Triggered | Session |
|---|--------|-----------|-------------------|---------|
| 1 | Player blacklist | <40% HR on 8+ edge-3+ picks | varies | 284 |
| 2 | Edge floor | edge < 5.0 | 57% | 297 |
| 3 | UNDER edge 7+ block | UNDER + edge >= 7 + line < 25 | 40.7% | 297/316 |
| 4 | Avoid familiar | 6+ games vs this opponent | varies | 284 |
| 5 | Feature quality floor | quality < 85 | 24.0% | 278 |
| 6 | Bench UNDER block | UNDER + line < 12 | 35.1% | 278 |
| 7 | Line jumped UNDER | UNDER + prop_line_delta >= 2.0 | 38.2% | 306 |
| 8 | Line dropped UNDER | UNDER + prop_line_delta <= -2.0 | 35.2% | 306 |
| 9 | Neg +/- streak UNDER | UNDER + 3+ consecutive neg +/- games | 13.1% | 294 |
| 10 | Min signal count | < 2 qualifying signals | n/a | 259 |
| 11 | Confidence floor | model-specific minimum | n/a | - |
| 12 | ANTI_PATTERN combos | known bad combos | varies | 259 |

**Star-level exception (Session 316):** UNDER edge 7+ normally 40.7% HR, but when line >= 25 (star players), it's 71.4% HR (N=7). So we allow star UNDERs through.

### Research We Just Did (Session 317)

We ran 5 hypothesis queries on the Jan-Feb data looking for new filters:

1. **blowout_recovery signal as filter:** 65.0% HR with signal (N=20) vs 76.7% without — above 55% threshold, no filter added
2. **prop_line_drop_over + low line (<15):** 86.0% HR (N=57) — excellent, no filter
3. **OVER HR by line tier:** Bench <12 = 85.7% (N=70, best tier), Mid 15-19 = 55.6% (N=9, small N)
4. **UNDER star (line 25+):** 37.5% HR (N=8) — concerning but N too small for filter (threshold N>=20)
5. **rest_advantage_2d decay:** Confirmed W2-W3=83%, W6=63.6%, W7=40% — clear weekly degradation

## Retraining Strategy

### Current Cadence
- **7-day retraining cadence** with 42-day rolling window
- Weekly Monday 9 AM ET reminders via Cloud Function
- Urgency levels: ROUTINE (7-10 days), OVERDUE (11-14), URGENT (15+)
- Current champion is 13 days stale (OVERDUE)

### Governance Gates (all must pass to deploy)
1. Duplicate check: blocks if same training dates exist
2. Vegas bias: within +/- 1.5
3. High-edge (3+) hit rate >= 60%
4. Sample size >= 50 graded edge 3+ bets
5. No critical tier bias (> +/- 5 points)
6. MAE improvement vs baseline

### Key Historical Lessons
- Lower MAE does NOT mean better betting. One retrain with MAE 4.12 (better than 4.83) crashed hit rate to 51.2% due to systematic UNDER bias
- Rolling 42-day window beats expanding window by +$20,720 in P&L
- 7-day cadence with 42-day rolling = optimal (Session 284 backtested)

### Should We Have Retrained Before February?

We just ran a what-if simulation:
- **Fresh retrain (train to Feb 19), eval Feb 20:** MAE 4.39, Vegas bias +0.08 — great stats. But only 4 edge 3+ picks and **0 edge 5+ picks** in 1 game day
- **Current model (train to Feb 5), eval Feb 6-21:** MAE 4.85. Also **0 edge 5+ picks** across 9 game days
- **Conclusion:** The post-ASB market is too thin. Both stale and fresh models produce zero best-bet-quality picks. Retraining wouldn't have helped February — the market itself was the problem.

## Our Tools & Skills

We have ~15 CLI skills that we can run at any time:

| Skill | What It Does |
|-------|------------|
| `/daily-steering` | Morning report: model health, signal health, best bets W-L, action recommendation |
| `/what-if --train-end DATE` | Simulate a retrain — train a new model, grade against actuals, report HR at all edge thresholds with OVER/UNDER breakdown. Can compare two models side-by-side |
| `/model-experiment` | Full model training with governance gates. Can train V9, V12, quantile variants |
| `/replay` | Backtest comparison: stale vs fresh model, any model against historical data |
| `/validate-daily` | 97.5-phase daily validation: data quality, model predictions, grading, pipeline health |
| `/hit-rate-analysis` | Performance breakdown by edge, direction, player tier, time window |
| `/reconcile-yesterday` | Gap detection: who played vs who was predicted, triggers targeted backfills |
| `/daily-steering` | Decay detection, challenger monitoring, signal health regime changes |
| `/spot-check-features` | Feature store quality audit for specific players/dates |
| `/subset-performance` | Compare all 30+ dynamic subsets side-by-side |
| `/backfill-subsets` | Dry-run subset backfill with before/after comparison |
| `/validate-feature-drift` | Feature distribution analysis vs previous periods |

## Questions I Want You to Analyze

Please provide specific, actionable recommendations for each:

1. **Models:** Should we try new model architectures, feature sets, or loss functions? Should V12 (50 features) replace V9 (33 features) as champion? Should we try LightGBM, XGBoost, or ensemble approaches? Are there features we're missing?

2. **Signals:** Should we add new signals? Remove more? Are there signal combinations we haven't explored? Is the signal health tracking regime (HOT/NORMAL/COLD) well-calibrated? Should signals play a bigger role than just filtering?

3. **Best Bets Algorithm:** Is the edge-first architecture optimal? Should we adjust any filter thresholds? Is natural sizing (no cap) the right approach? Should we weight some filters differently?

4. **Retraining:** Is 7-day cadence with 42-day rolling window optimal? Should we retrain more aggressively during cold streaks? Should we have triggered an emergency retrain when February started declining?

5. **Edge Filters:** Are there new filters we should test? The UNDER star 25+ finding (37.5% HR, N=8) is small but concerning. Should we add a blowout_recovery drag filter (65% vs 76.7%)?

6. **February Decline:** What caused it? Was it model staleness, market structure (post-ASB), bad luck / regression to mean, or something else? How can we detect early and respond to declining performance periods?

7. **Early Warning System:** How would you design a system to detect a shift like January → February BEFORE we lose money? We have daily decay detection but it didn't prevent the February slide.

8. **Anything Else:** What patterns do you see that we're missing? What would you prioritize working on next?

Be specific. Reference our actual numbers. Tell me what experiments to run with our `/what-if` and `/model-experiment` tools. If you recommend a new signal or filter, tell me exactly what it should measure, what threshold to use, and what HR improvement to expect.
