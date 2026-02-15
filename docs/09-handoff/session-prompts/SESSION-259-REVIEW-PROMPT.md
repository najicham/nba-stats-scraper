# Review Prompt: Session 258 Implementation + Session 259 Mega Test Plan

Copy everything below the line into a new Claude chat for independent review.

---

You are a senior sports analytics engineer and quantitative betting strategist. I need you to critically review two documents from our NBA player props prediction system and give honest, detailed feedback. Don't be nice — be useful. Tell us what's smart, what's dumb, what we're missing, and what's going to waste our time.

## Context

We run a production NBA player props prediction system (points over/under bets). We have a CatBoost model that generates predictions, and on top of that we've built a **Signal Discovery Framework** — a layer of rule-based signals that filter and rank the model's predictions to find the highest-quality bets.

Key facts:
- Breakeven at -110 odds requires 52.4% hit rate
- We currently have 23 registered signals evaluated against every prediction
- The aggregator selects the top 5 picks per day based on composite scoring
- We have 4 eval windows of historical data (Dec 2025 - Feb 2026, ~4 months)
- The champion CatBoost model is currently stale (35+ days since last training), which means signals relying purely on model edge have decayed significantly
- Our best signals are combo signals (multiple conditions must be true simultaneously)

## Document 1: Session 258 Implementation (what we just built)

### New Combo Signals

| Signal | Tag | Criteria | Backtest HR | N | Confidence |
|--------|-----|----------|------------|---|-----------|
| HighEdgeMinutesSurgeCombo | `combo_he_ms` | Edge >= 5 + minutes surge >= 3 + OVER only | 68.8% | 16 | 0.85 |
| ThreeWayCombo | `combo_3way` | Edge >= 5 + minutes surge >= 3 + confidence >= 70% (exclude 88-90% problem tier) | 88.9% | 17 | 0.95 |

Both check conditions internally — no dependency on other signal instances.

### Signal Filters Added

| Signal | Filter | Before | After | Rationale |
|--------|--------|--------|-------|-----------|
| `cold_snap` (3+ consecutive UNDERs, bet OVER) | HOME-ONLY | 61.1% HR (31 picks) | 93.3% HR (15 picks) | 62-point home/away split |
| `blowout_recovery` (prev game minutes way below avg) | Exclude Centers | 53.1% HR (113 picks) | ~58% HR (98 picks) | Centers 20.0% HR |
| `blowout_recovery` | Exclude B2B (rest_days < 2) | included above | ~58% HR (fewer picks) | B2B is 46.2% HR |

### Anti-Pattern Warning System in Aggregator

After computing base `composite_score = edge_score * signal_multiplier`:

| Pattern | Detection | Action |
|---------|-----------|--------|
| `combo_3way` present | Tag check | +2.5 composite bonus |
| `combo_he_ms` present | Tag check | +2.0 composite bonus |
| high_edge + edge_spread_optimal WITHOUT minutes_surge | `redundancy_trap` warning | -2.0 penalty |
| minutes_surge + blowout_recovery | `contradictory_signals` warning | Neutralize bonus (cap at 0) |

`warning_tags` are surfaced in JSON exports and BigQuery tables.

### Data Pipeline

Added `is_home` (derived from game_id format `YYYYMMDD_AWAY_HOME`) and `player_context.position` (from player_game_summary) to the supplemental data query.

Re-registered `edge_spread_optimal` signal (47.4% standalone HR, below breakeven) purely so its tag appears for anti-pattern detection in the aggregator.

---

## Document 2: Session 259 Mega Test Plan (what we want to do next)

### Part 1: 23 New Signal Candidates

**A. From feature store data (already queryable):**

| # | Signal | Logic | Hypothesis |
|---|--------|-------|-----------|
| 1 | `opponent_def_weak` | Opponent def rating bottom 25% + OVER | Weak defense = more points |
| 2 | `team_hot_offense` | Team off rating top 25% + OVER | Hot team lifts all boats |
| 3 | `team_winning` | Team win% > 60% + home + OVER | Winning teams at home dominate |
| 4 | `points_volatility_high` | points_std > 6 + OVER + edge >= 3 | High variance player + model says OVER = upside |
| 5 | `points_volatility_low` | points_std < 3 + edge >= 3 | Consistent player + edge = reliable |
| 6 | `fatigue_score_high` | Fatigue top 20% + UNDER | Tired players underperform |
| 7 | `usage_spike` | Usage spike score high + OVER | More shots = more points |
| 8 | `matchup_history_good` | avg_points_vs_opponent > season avg + OVER | Historical matchup advantage |
| 9 | `vegas_line_move_with` | Line moved toward our prediction + edge >= 3 | Sharp money agrees |
| 10 | `vegas_line_move_against` | Line moved AGAINST prediction + edge >= 5 | Strong model conviction against market |
| 11 | `ppm_efficient` | Points per minute above avg + minutes surge | Efficient AND getting more time |
| 12 | `scoring_trend_up` | pts_slope_10g > 0 + edge >= 3 + OVER | Mathematical uptrend |
| 13 | `scoring_trend_down` | pts_slope_10g < 0 + edge >= 3 + UNDER | Mathematical downtrend |

**B. Require adding player_game_summary fields to backtest query:**

| # | Signal | Logic | Hypothesis |
|---|--------|-------|-----------|
| 14 | `assist_machine` | Assists last 3 > season avg + 3 + OVER | Playmaker = more scoring opps |
| 15 | `rebound_monster` | Rebounds last 3 > season avg + 3 + OVER | Active on glass = more energy |
| 16 | `foul_trouble_risk` | Fouls last 3 > 4.0 avg + UNDER | Foul-prone = reduced minutes |
| 17 | `ft_volume_surge` | FT attempts last 3 > season + 2 + OVER | Drawing fouls = scoring |
| 18 | `plus_minus_hot` | Plus/minus last 3 > +10 avg + OVER | High-impact player |
| 19 | `starter_promoted` | Moved from bench to starter | Role upgrade = more opportunity |
| 20 | `paint_dominant` | paint_pct > 50% + opponent weak interior | Inside game advantage |

**C. Cross-model signals:**

| # | Signal | Logic | Hypothesis |
|---|--------|-------|-----------|
| 21 | `v9_v12_both_high_edge` | Both V9 and V12 edge >= 5 + same direction | Two independent models very confident |
| 22 | `v9_v12_disagree_strong` | V9 edge >= 5 but V12 says opposite | Model disagreement = uncertainty = skip |
| 23 | `v9_confident_v12_edge` | V9 confidence >= 80% + V12 edge >= 3 | Confidence + independent edge |

### Part 2: Dimensional Filters (test every signal across all of these)

**Player:** Position (PG/SG/SF/PF/C), Player tier (Elite/Star/Starter/Role/Bench), Minutes bucket, Consistency (variance), Experience

**Game:** Home/Away, Rest days (B2B/Short/Normal/Rested), Day of week, Game total (high/med/low), Spread (favored/toss-up/underdog)

**Model/Line:** Edge size, Direction (OVER/UNDER), Confidence bucket, Line level, Line source, Model staleness

**Team:** Team strength, Opponent strength, Pace, Conference

### Part 3: Combo Matrix

- All pairwise combos (prioritizing high_edge + X and minutes_surge + X)
- Three-way combos (extend the proven HE+MS base with every other signal)
- Systematic anti-pattern discovery (flag combos where HR < worst individual HR - 5%)

### Part 4: Composite Filter Stacking ("Golden Path" Discovery)

For each signal, find the best single dimensional filter, then stack a second filter on top. Automated search for the most profitable filter chains.

### Part 5: Execution

6 parallel agents, each assigned a subset. Standardized output format with per-window breakdowns and verdicts (PREMIUM >70%, STRONG >60%, VIABLE >55%, MARGINAL 52.4-55%, SKIP <52.4%).

### Part 6: Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| PREMIUM signals (>70% HR) | 2 | 5+ |
| STRONG signals (>60% HR) | 3 | 8+ |
| Anti-patterns catalogued | 2 | 6+ |
| Dimensional filters validated | 5 | 15+ |
| Best Bets daily HR | ~58% | 65%+ |

### Part 7: Promotion Rules

Signals must pass ALL: HR >= 60% across 2+ eval windows, N >= 15 total, positive ROI, no window below 40% HR, W3->W4 delta < 15 points.

---

## What I Need From You

Please review both documents and provide:

### 1. Implementation Review (Session 258)
- Are the combo signal implementations sound? Any logic flaws?
- Is the anti-pattern warning system well-designed? Missing patterns?
- Is the +2.5/+2.0/-2.0 scoring reasonable, or will it create weird edge cases?
- Is re-registering ESO (a losing signal) just for anti-pattern detection the right call?
- Any concerns about the `is_home` derivation from game_id format?

### 2. Testing Plan Review (Session 259)
- Which of the 23 proposed signals are most promising? Which are likely wastes of time?
- Are there signal ideas we're NOT thinking of that we should be?
- Is the dimensional filter approach sound? Are there dimensions we're missing?
- With only 4 months of data and small sample sizes (many combos have N=5-20), how do we guard against overfitting to noise?
- Is the "Golden Path" stacking approach (best filter, then stack second) going to find real signal or just overfit?
- Are the promotion rules (Part 7) too strict, too lenient, or about right?
- Is testing 2,000+ permutations actually valuable, or should we be more selective?

### 3. Statistical Rigor
- With N=17 picks for our best combo (88.9% HR), how confident should we actually be? What's the confidence interval?
- Are we at risk of data mining bias with this many tests? How should we correct for multiple comparisons?
- Should we be doing any form of out-of-sample hold-out, or is the 4-window temporal validation sufficient?
- At what sample size should we consider a finding "real" vs "noise"?

### 4. Strategic Blind Spots
- What are we not thinking about that could undermine this whole approach?
- Are there well-known pitfalls from sports betting quant research we should be aware of?
- Is the signal framework adding real value, or are we just carving up the same model output in increasingly complex ways?
- Should we be spending this time on model retraining instead?

### 5. Priority Ranking
- If we can only execute 30% of this plan, what's the highest-value 30%?
- What would you cut entirely?
- What would you add that we haven't thought of?

Be blunt. We'd rather hear "this is a waste of time because X" than a polite review that misses real problems.
