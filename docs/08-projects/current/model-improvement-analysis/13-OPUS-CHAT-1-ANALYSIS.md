# NBA Props Model — Analysis & Improvement Recommendations

`path: docs/model-improvement-plan.md`

**Prepared for:** Claude Code implementation review
**Context:** The prediction system hit 71.2% at launch, decayed to ~40%, and 9 experiments have been run to diagnose the issue. This document analyzes findings from those experiments, identifies root causes, and recommends a prioritized path forward.

---

## Part 1: Diagnostic Analyses (Run These First)

Before changing the model, we need data to validate hypotheses. These analyses use existing data in BigQuery and the per-player prediction logs. Each analysis directly informs a decision point in the recommendations below.

### 1.1 Vegas Line Sharpness Analysis

**Purpose:** Determine whether February 2026's edge pool has genuinely shrunk, or whether our model just can't find it anymore.

**What to measure:**
- `abs(actual_points - vegas_points_line)` aggregated monthly from October 2024 through February 2026
- Report: mean absolute error, median absolute error, and standard deviation per month
- Additionally segment by player tier (top-20 usage, mid-tier, low-usage role players) to see if sharpness varies by player type

**What this tells us:**
- If Vegas MAE dropped from ~5.5 to ~4.0 in Feb 2026, the edge pool literally shrunk and we need to adjust expectations
- If Vegas MAE is stable, the edges still exist and our model is failing to find them
- If sharpness varies by player tier, we can focus on the tier with the most remaining edge

**Data source:** Both `vegas_points_line` and `actual_points` exist in a queryable BigQuery table already.

### 1.2 Per-Player Prediction Breakdown

**Purpose:** Determine whether model decay is uniform or concentrated in specific player archetypes.

**What to measure using per-player prediction logs:**
- Hit rate by player scoring tier (25+ ppg, 18-25, 12-18, under 12)
- Hit rate by position
- Hit rate by minutes consistency (low variance in minutes vs high variance)
- Identify the 10 players the model gets most wrong in February 2026 and look for commonalities

**What this tells us:**
- If decay is concentrated in high-usage stars, Vegas may be sharper on marquee players (more market attention) — we should focus on mid-tier players
- If decay is concentrated in role players, minute volatility and lineup changes are likely the driver
- If it's uniform across tiers, the problem is more fundamental (Vegas dependency, feature staleness)

### 1.3 Calibration Analysis

**Purpose:** Understand whether the model is directionally wrong or poorly calibrated.

**What to measure:**
- For each prediction, compute: `model_prediction - vegas_line` (our implied edge) and `actual_points - vegas_line` (actual outcome relative to line)
- Bin predictions by implied edge size (1-2 pts, 2-3 pts, 3-5 pts, 5+) and compute mean actual outcome in each bin
- Plot predicted vs actual points directly (not just hit rate)

**What this tells us:**
- If the model consistently predicts 22 when the line is 25 and actual is 24, the model is directionally right but under-predicting magnitude — a calibration fix could help
- If the model predicts 22 when the line is 25 and actual is 27, the model is fundamentally wrong — feature/architecture changes needed
- The directional accuracy vs magnitude accuracy split is critical for choosing between calibration tuning vs structural changes

### 1.4 OVER/UNDER Asymmetry Deep Dive

**Purpose:** Understand exactly why OVER predictions collapsed.

**What to measure:**
- Distribution of `model_prediction - vegas_line` for Feb 2025 vs Feb 2026
- In Feb 2025 (when OVER worked), how far above the line were OVER predictions on average?
- In Feb 2026, is the model generating predictions that are close-to-but-below the line (near misses) or far below (systematic under-prediction)?
- For the rare Feb 2026 OVER picks, what distinguished those players?

**What this tells us:**
- If predictions cluster just below the line in 2026 (mean offset of -1 to -2 from the line), Q43 is pulling everything under and a calibration shift might recover OVER picks
- If predictions are far below lines (mean offset of -4 to -5), the underlying point predictions are broken, not just the quantile bias
- The Feb 2025 comparison gives us a "healthy" baseline distribution

### 1.5 Post-Trade/Post-Break Impact Assessment

**Purpose:** Quantify how much the All-Star break and trade deadline are contaminating rolling averages.

**What to measure:**
- Identify all traded players in February 2026 (team changed mid-season)
- For traded players: hit rate before vs after trade
- Compare `points_avg_last_5` relevance for players whose last 5 games span the All-Star break vs those who played all 5 games post-break
- Count how many of the Feb 2026 evaluation games involve players with "contaminated" rolling averages (pre-break games in their window)

**What this tells us:**
- If a significant percentage of evaluation games involve contaminated averages, this alone could explain the decay
- If traded players have dramatically worse hit rates, we need structural break handling urgently
- Quantifies how many predictions are affected, informing whether this is a niche fix or a core issue

---

## Part 2: Root Cause Analysis

Based on the 9-experiment findings and the system architecture, there are three interacting root causes. They're listed in order of impact.

### Root Cause 1: Vegas Line Dependency (Structural)

The model's #1 feature (`vegas_points_line`, 15-30% importance) combined with Q43 quantile regression creates a system that approximates: `prediction ≈ vegas_line * 0.97 - small_adjustment`. This isn't finding edges — it's agreeing with Vegas and shading under.

**Why this worked initially:** In December-January, the model launched into a period where Vegas lines were systematically too high (likely due to early-season small sample sizes, lineup experimentation, and incomplete market data). The UNDER bias accidentally aligned with a real market inefficiency. When that inefficiency corrected, the model had nothing else to fall back on.

**Evidence:**
- Feature importance: `vegas_points_line` at 15-30% dominates everything
- Removing quantile bias (baseline experiment) improved MAE to 5.02 and achieved balanced directional accuracy (45.2% OVER / 60.9% UNDER) — but still only 51.9% edge 3+ HR
- The OVER collapse across all 9 experiments confirms the model can't generate OVER signals independently of Vegas

### Root Cause 2: Missing Structural Break Handling (Temporal)

Rolling averages (`points_avg_last_5`, `points_avg_last_10`) are the #2 and #3 features. They assume continuity — that the last 5 games predict the next one. This assumption breaks at:

- **Trade deadline:** Player changes team, role, minutes, usage, teammates — all overnight
- **All-Star break:** 7-10 day layoff, rust/rhythm disruption, potential lineup changes announced during break
- **Rotation changes:** February is when playoff-bound teams start resting players and experimenting

The model has zero awareness of these structural breaks. Currently rolling averages use the last N games regardless.

### Root Cause 3: Insufficient Independent Signal (Feature Gap)

Stripping away Vegas-derived features and near-zero-importance features, the model's independent signal comes from:
- Rolling scoring averages (stale in February, see above)
- Shot zone percentages (stable but slow-changing)
- `opponent_def_rating` and `opponent_pace` (moderate importance, 2-3%)
- Team context (pace, offensive rating, win%) — slow-changing

There's no feature capturing:
- How the scoring environment of *this specific game* differs from average (game total line)
- Whether teammates who affect this player's usage are available
- Mean-reversion signals (player running hot/cold relative to line)
- Minutes projection confidence (is this player's minute floor stable?)

The model lacks enough independent signal to disagree with Vegas when Vegas is wrong.

---

## Part 3: Strategic Recommendations

### Recommendation 1: Build a Vegas-Free Points Predictor

**Priority: Critical — this is the single most impactful change**

Train a separate CatBoost model that predicts actual points scored without any Vegas features (indices 25-28 removed entirely). This model answers: "Based on everything we know about this player, matchup, and context, how many points should they score?"

**Why this matters:**
- The edge IS the disagreement between an independent points estimate and the Vegas line
- Currently the model can't disagree with Vegas because Vegas is its primary input
- A Vegas-free model with MAE of 5.5 would still find exploitable disagreements when Vegas has MAE of 5.0 — the disagreements ARE the edges
- Feb 2025's 79.5% success proves edges exist to be found

**Training approach:**
- Same CatBoost architecture, same training data
- Remove features 25-28 (vegas_points_line, vegas_opening_line, vegas_line_move, has_vegas_line)
- Train on MAE/RMSE loss (predict actual points, not over/under)
- No quantile regression — predict the true expected value

**Edge calculation:**
- `edge = model_prediction - vegas_line`
- Positive edge → OVER signal, negative edge → UNDER signal
- Apply minimum edge threshold (e.g., 3+ points) for bet selection
- This naturally generates both OVER and UNDER picks based on where the model disagrees with Vegas

**Expected impact:** This won't immediately be more accurate than the current model. The point isn't accuracy — it's independence. An independent model with 5.5 MAE that disagrees with Vegas on 15% of games gives you 15% of games where you have a genuine signal. The current model agrees with Vegas on ~95% of games and just shades under.

### Recommendation 2: Add Game Environment Features

**Priority: High — addresses the #1 feature gap**

These features capture the expected scoring environment of each specific game, which current features miss entirely:

**2a. Game Total Line (retry with different engineering)**

The raw O/U game total from the sportsbook was tried and had near-zero importance. This is likely because the raw number (e.g., 224.5) doesn't tell the model much without context. Re-engineer it as:

- `game_total_vs_season_avg`: How this game's total compares to the league average game total. A game with total 235 when league average is 225 is a +10 environment — this player's scoring opportunity is elevated.
- `game_total_rank_percentile`: Where this game total falls in the season distribution (0-1 scale). Top 10% game = high-scoring environment.
- `implied_team_total`: `(game_total + spread) / 2` for the player's team — estimates how many points their specific team is expected to score.

The implied team total is probably the most useful of these three. If a team is expected to score 118 vs their season average of 112, that's a meaningful signal about opportunity.

**2b. Expected Pace Impact**

We have `opponent_pace` and `team_pace` but not the interaction:
- `pace_differential`: `game_pace_estimate - player_team_season_avg_pace`
- This captures "is this game expected to have more possessions than this player usually gets?"

### Recommendation 3: Add Teammate Context Features

**Priority: High — addresses the biggest unexploited data source**

We have injury reports, box scores showing who played, and usage rate data per player per game. This is enough to build:

**3a. Usage Redistribution Signal**

When a team's #2 or #3 scorer is out, the remaining players' usage increases. This is one of the most well-documented effects in NBA analytics.

- For each player, identify their team's top 3-4 scorers by season average
- `top_teammate_out`: Binary flag — is any of the team's other top-3 scorers listed as OUT in the injury report?
- `expected_usage_boost`: Estimated usage increase based on the missing player's usage share. If a teammate who takes 25% of shots is out, roughly that 25% redistributes to remaining players weighted by their normal usage.

**Note on the previous V11 attempt:** `star_teammates_out` was tried and had near-zero importance. The difference here is:
- V11 likely used a binary flag without weighting by the missing player's impact
- The `expected_usage_boost` is a continuous value that captures *magnitude* of impact
- Combined with the Vegas-free model (Rec 1), this signal has room to matter because it's not competing with Vegas for importance

**3b. Lineup Stability**

- `starter_consistency_last_5`: What percentage of the team's starting 5 has been consistent over the last 5 games? High consistency = predictable role. Low consistency = volatile minutes.
- This is calculable from box scores (who played, minutes played per game)

### Recommendation 4: Add Mean-Reversion / Streak Features

**Priority: Medium-High — captures a known betting market inefficiency**

Vegas adjusts lines based on recent performance, but tends to overweight short streaks. If a 25 ppg scorer has 3 games of 18 points, Vegas might drop the line to 22.5. If the underlying talent hasn't changed (no injury, no role change), this is a buying opportunity.

- `games_under_line_streak`: Consecutive games scoring under the Vegas line (0 if last game was over)
- `games_over_line_streak`: Same for over direction
- `actual_vs_line_last_3`: Average of `(actual_points - vegas_line)` over last 3 games. Negative = running cold vs line, positive = running hot
- `line_vs_season_avg`: `vegas_line - points_avg_season`. When the line is significantly below a player's season average, it may be a buy-low signal.

**Important:** These features are most valuable in the Vegas-free model context (Rec 1). In the current Vegas-dependent model, they'd likely have low importance because the model already gets this info implicitly from the Vegas line itself. In a Vegas-free model, these become the mechanism for capturing "is the market undervaluing this player right now?"

Wait — there's a subtlety. For the Vegas-free model, `line_vs_season_avg` and `actual_vs_line_last_3` use the Vegas line as input. That reintroduces Vegas dependency. For the Vegas-free model, use only:
- `games_below_season_avg_streak`: Consecutive games below their own season scoring average (independent of Vegas)
- `deviation_from_avg_last_3`: `mean(last_3_actual) - season_avg` (how hot/cold vs own baseline)
- `scoring_trend_slope`: Linear regression slope over last 5 games (directional momentum)

Then at the *edge calculation* stage (not the model stage), compare the Vegas-free prediction to the Vegas line. The streak/reversion features help the model predict actual points more accurately, and the edge naturally emerges from comparison with Vegas.

### Recommendation 5: Handle Structural Breaks

**Priority: Medium-High — directly addresses the February failure mode**

Two specific interventions:

**5a. Trade Detection and Average Reset**

- Detect when a player's team changes mid-season (compare team in game N vs game N-1 in box score data)
- For traded players, discount or exclude pre-trade games from rolling averages
- Options: (a) hard reset — only use post-trade games, (b) decay — weight pre-trade games at 0.3x, post-trade at 1.0x
- Add a `games_with_current_team` feature so the model knows how much to trust the rolling averages

**5b. All-Star Break Awareness**

- Add `days_since_last_game` as a feature. Under normal circumstances this is 1-2. During ASB it's 7-10. The model can learn that long gaps affect performance.
- Consider: for the first 2-3 games after ASB, weight the pre-break games in rolling averages at 0.5x to account for rhythm disruption
- This is simple to implement since game dates are already in the data

### Recommendation 6: Drop Dead Features, Clean Up Feature Set

**Priority: Medium — reduces noise, marginally improves generalization**

Remove features with consistent near-zero importance across all 9 experiments:
- `injury_risk` (0.00-0.14%) — replace with the teammate context features from Rec 3
- `back_to_back` (0.00-0.24%) — redundant with `games_in_last_7_days`
- `playoff_game` (0.00-0.10%) — always 0 in regular season, useless
- `rest_advantage` (0.07-0.30%) — replace with `days_since_last_game` from Rec 5b
- `has_vegas_line` (0.10-0.30%) — nearly always 1 for players we bet on

Net change: Remove 5 dead features, add ~8-10 new features from Recs 2-5. Total feature count goes from 33 to ~36-38, but with much higher signal density.

### Recommendation 7: Explore Classification as a Parallel Approach

**Priority: Medium — worth testing but not the first thing to do**

After building the Vegas-free points predictor (Rec 1), also train a binary classifier that directly predicts OVER/UNDER. Compare:

- **Points regression:** Predict actual points → compare to line → derive over/under
- **Binary classification:** Predict OVER/UNDER directly with log-loss

The classification approach loses magnitude information (can't size bets by confidence) but may find different patterns. Specifically, it can learn "this player goes over in this type of game" without needing to get the exact point total right.

If both models agree (regression says over AND classifier says over), that's a high-confidence signal. Disagreement = lower confidence or skip.

**Loss function consideration:** If going the classification route, use a custom loss that weights by edge size. A wrong prediction on a 5-point edge should penalize more than on a 3-point edge, because the larger the edge, the more confident we should have been.

---

## Part 4: Implementation Priority & Sequencing

### Phase A: Diagnostics (before any model changes)

Run analyses 1.1 through 1.5 from Part 1. These take hours, not days, and directly inform every decision below. Specifically:

- If **1.1 (line sharpness)** shows Vegas MAE dropped significantly → edges may be structurally smaller, adjust expectations from 55% to perhaps 53-54%
- If **1.2 (per-player)** shows concentrated failure in specific tiers → target those tiers with feature engineering
- If **1.3 (calibration)** shows directional accuracy is preserved but magnitude is off → prioritize calibration over architecture changes
- If **1.5 (structural breaks)** shows widespread contaminated averages → prioritize Rec 5 before anything else

### Phase B: Vegas-Free Model (Rec 1)

Build this immediately after diagnostics. It's the foundation for everything else. Steps:
1. Train CatBoost on current features minus Vegas features (indices 25-28)
2. Evaluate on Feb 2025 (expect ~75%+ if architecture works) AND Feb 2026
3. Compute edge as `prediction - vegas_line`
4. Evaluate edge-based bet selection at thresholds 2, 3, 4, 5

This alone might get us back above 55%. If it does, all subsequent changes are incremental improvements. If it doesn't, diagnostics from Phase A will tell us what to prioritize next.

### Phase C: Feature Engineering (Recs 2-5)

Add features in this order, retraining and evaluating after each batch:

1. **Game environment** (Rec 2): `implied_team_total`, `game_total_vs_season_avg`, `pace_differential`
2. **Structural breaks** (Rec 5): `games_with_current_team`, `days_since_last_game`, average decay for traded players
3. **Teammate context** (Rec 3): `top_teammate_out`, `expected_usage_boost`
4. **Streak/reversion** (Rec 4): `games_below_season_avg_streak`, `deviation_from_avg_last_3`, `scoring_trend_slope`

Evaluate each batch independently. If a batch doesn't improve performance, don't keep it — feature bloat is how we got 5 dead features in the first place.

### Phase D: Feature Cleanup + Classification Experiment (Rec 6-7)

After Phase C settles, drop confirmed dead features and run the classification experiment as a parallel signal.

---

## Part 5: What NOT to Do

Based on the dead ends documented in the briefing, avoid these paths:

| Approach | Why to avoid |
|----------|-------------|
| Monotonic constraints | Increases Vegas dependency, opposite of what we need |
| Multi-quantile ensemble | Opposing biases cancel out, volume collapses |
| Alpha fine-tuning (Q42/Q43/Q44) | Marginal differences, not the right lever |
| Residual mode (predict actual - vegas) | Already tried, poor calibration |
| Two-stage pipeline | Added noise at each stage, complexity without benefit |
| Training on more seasons without weighting | 3-season was worse than 1-season in Feb 2026 |
| Micro-retraining alone | 14-day training still gets 50% — data freshness isn't the issue |

Also avoid:
- **Neural networks at this stage.** CatBoost scored 79.5% in Feb 2025. The architecture works. The issue is features and Vegas dependency, not model capacity. Neural nets add complexity without addressing root causes.
- **Expanding to more prop types (assists, rebounds) before fixing points.** Get one prop right first.
- **Feature expansion without evaluation.** Every new feature should be A/B tested. Add, measure, keep or discard.

---

## Part 6: Success Criteria & Evaluation Framework

### Minimum Viable Improvement
- Edge 3+ hit rate consistently above 55% on rolling 2-week evaluation windows
- Balanced directional accuracy: both OVER and UNDER hit rates above 50%
- Model generates at least 5 edge 3+ bets per day on average (sufficient volume)

### Target Performance
- Edge 3+ hit rate of 60%+ (where we were adjusted for sample size)
- Edge 5+ hit rate of 65%+
- Stable performance across calendar periods (no February-style collapses)

### Evaluation Protocol
- Always evaluate on held-out time periods (never in-sample)
- Report hit rate, N (sample size), OVER HR, UNDER HR, MAE, and Vegas bias for every experiment
- Minimum N of 100 before drawing conclusions (many Feb 2026 experiments had N=16-24, which is insufficient)
- Always cross-validate against Feb 2025 as a known-good benchmark period
- Track feature importance shifts between experiments to catch new dependencies

### Red Flags to Watch For
- Any single feature exceeding 25% importance → model is over-reliant on it
- OVER or UNDER hit rate below 40% → directional bias problem
- Hit rate variance > 15pp between consecutive 2-week windows → model instability
- New features showing near-zero importance → don't keep them

---

## Part 7: Open Questions

These are questions where the diagnostic analyses (Part 1) should provide answers, but which might require further investigation:

1. **Is the Feb 2026 market structurally different or temporarily disrupted?** If post-ASB performance recovers (March 2026), February was an anomaly. If it doesn't recover, the market may have permanently tightened.

2. **Should we filter bet selection by player tier?** If diagnostics show edges concentrated in mid-tier players (18-25 ppg), we should only bet on that tier rather than trying to beat Vegas on stars.

3. **How much does game total line add to a Vegas-free model?** In the current model, the raw game total had zero importance. But in a Vegas-free model (where we're trying to predict points independently), the game total is one of the best available proxies for the scoring environment. It may perform very differently.

4. **What's the right training window for the Vegas-free model?** The current model performs best on 1-season (91 days). The Vegas-free model may behave differently — it's learning player scoring patterns rather than Vegas relationships, so more data might actually help.

5. **Is there a play-by-play derived feature worth the engineering cost?** We have every possession logged but haven't extracted features. Candidates: shot quality (expected points per shot attempt), clutch vs garbage time scoring splits, scoring distribution by quarter. These are expensive to compute — only pursue if diagnostics suggest the current feature set can't reach 55%.

---

## Appendix A: Current Feature Set Reference

Organized by recommended action:

**Keep (high importance, useful signal):**
- points_avg_last_5, points_avg_last_10, points_avg_season, points_std_last_10 (core averages)
- ppm_avg_last_10, minutes_avg_last_10 (efficiency + minutes)
- opponent_def_rating, opponent_pace (matchup)
- team_pace, team_off_rating, team_win_pct (team context)
- pct_paint, pct_mid_range, pct_three, pct_free_throw (shot profile)
- home_away (consistent small signal)
- games_in_last_7_days (schedule density)
- fatigue_score, shot_zone_mismatch_score, pace_score, usage_spike_score (composites — moderate signal)
- recent_trend, minutes_change (trajectory)

**Move to edge calculation only (Vegas-free model shouldn't see these):**
- vegas_points_line, vegas_opening_line, vegas_line_move, has_vegas_line

**Drop (near-zero importance):**
- injury_risk, back_to_back, playoff_game, rest_advantage, has_vegas_line

**Keep with modification:**
- avg_points_vs_opponent, games_vs_opponent — keep but add recency weighting (this-season games weighted higher than last season)

## Appendix B: New Features Summary

| Feature | Source Data | Recommendation | Priority |
|---------|-----------|----------------|----------|
| implied_team_total | Game total + spread from odds | Rec 2a | High |
| game_total_vs_season_avg | Game total vs league avg | Rec 2a | High |
| pace_differential | Team/opp pace interaction | Rec 2b | High |
| games_with_current_team | Box scores (team changes) | Rec 5a | High |
| days_since_last_game | Game dates | Rec 5b | High |
| top_teammate_out | Injury reports + season avgs | Rec 3a | High |
| expected_usage_boost | Injury reports + usage data | Rec 3a | High |
| starter_consistency_last_5 | Box scores | Rec 3b | Medium |
| games_below_season_avg_streak | Game logs | Rec 4 | Medium |
| deviation_from_avg_last_3 | Game logs | Rec 4 | Medium |
| scoring_trend_slope | Game logs (regression) | Rec 4 | Medium |
