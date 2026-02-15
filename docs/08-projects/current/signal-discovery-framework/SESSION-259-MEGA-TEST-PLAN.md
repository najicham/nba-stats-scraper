# Session 259: Mega Signal Testing Plan

**Date:** 2026-02-15
**Goal:** Systematically test every signal, combo, and filter permutation across every available dimension. Find the profitable needles in the haystack.

**Status:** PARTIALLY EXECUTED. Cross-model + vegas signals tested first — all blocked by data coverage (see SESSION-259-FOCUSED-BACKTEST-RESULTS.md). Plan revised with data-awareness annotations below.

---

## Lessons Learned from Initial Testing

Before executing any more of this plan, three critical constraints:

1. **V12 predictions only exist from Feb 1, 2026.** Any signal requiring V12 data has at most 12 days of graded predictions. Cross-model signals (21-23) are untestable until late March.
2. **Feature 27 (vegas_line_move) is 93% NULL.** Pipeline barely populates this field. Vegas signals need an upstream fix before testing.
3. **Last season (V8) data cannot validate V9 signals.** V8 had 74.2% HR vs V9's ~55% — different distributions, different edge characteristics. Use last season for basketball hypothesis validation only, not signal calibration.

**Revised priority:** Focus on signals that use well-populated data (features 0-24, player_game_summary stats, streak data). Skip anything dependent on sparse features until pipeline fixes.

---

## Philosophy

Sessions 256-257 proved that **dimensional filtering transforms mediocre signals into premium ones** (cold_snap: 31% -> 93% with home-only filter). We've only scratched the surface. This session exhaustively tests every permutation we can think of.

---

## Part 1: New Signal Candidates (13 signals to create and test)

### A. Untapped Data Signals

These use data already in the backtest query but not yet exploited by any signal:

| # | Signal Name | Logic | Data Source | Hypothesis |
|---|------------|-------|-------------|------------|
| 1 | `opponent_def_weak` | Opponent def rating bottom 25% + OVER | Feature 13 (opponent_def_rating) | Weak defense = more points |
| 2 | `team_hot_offense` | Team offensive rating top 25% + OVER | Feature 23 (team_off_rating) | Hot team lifts all boats |
| 3 | `team_winning` | Team win% > 60% + home + OVER | Feature 24 (team_win_pct) | Winning teams at home dominate |
| 4 | `points_volatility_high` | points_std_last_10 > 6 + OVER + edge >= 3 | Feature 3 (points_std_last_10) | High variance + model says OVER = upside potential |
| 5 | `points_volatility_low` | points_std_last_10 < 3 + edge >= 3 | Feature 3 | Consistent player + edge = reliable |
| 6 | `fatigue_score_high` | Fatigue score top 20% + UNDER | Feature 5 (fatigue_score) | Tired players underperform |
| 7 | `usage_spike` | Usage spike score > threshold + OVER | Feature 7 (usage_spike_score) | More shots = more points |
| 8 | `matchup_history_good` | avg_points_vs_opponent > season avg + OVER | Features 29-30 | Player historically good vs this team |
| 9 | `vegas_line_move_with` | Vegas line moved toward our prediction + edge >= 3 | Feature 27 (vegas_line_move) | Sharp money agrees with model | **BLOCKED: feature 93% NULL. N=7 in backtest. Needs pipeline fix.** |
| 10 | `vegas_line_move_against` | Vegas line moved AGAINST our prediction + edge >= 5 | Feature 27 | Contrarian when model has strong conviction | **BLOCKED: same as signal 9** |
| 11 | `ppm_efficient` | Points per minute last 10 > season avg + minutes surge | Feature 32 (ppm_avg_last_10) | Efficient AND getting more time |
| 12 | `scoring_trend_up` | pts_slope_10g > 0 + edge >= 3 + OVER | Feature 34 | Mathematical uptrend in scoring |
| 13 | `scoring_trend_down` | pts_slope_10g < 0 + edge >= 3 + UNDER | Feature 34 | Mathematical downtrend |

### B. Player Game Summary Signals (require adding fields to backtest query)

| # | Signal Name | Logic | Data Source | Hypothesis |
|---|------------|-------|-------------|------------|
| 14 | `assist_machine` | Assists last 3 > season avg + 3 + OVER | player_game_summary.assists | Playmaker role = more scoring opportunities |
| 15 | `rebound_monster` | Rebounds last 3 > season avg + 3 + OVER | player_game_summary.rebounds | Active on glass = more energy/minutes |
| 16 | `foul_trouble_risk` | Personal fouls last 3 > 4.0 avg + UNDER | player_game_summary.personal_fouls | Foul-prone = reduced minutes |
| 17 | `ft_volume_surge` | FT attempts last 3 > season avg + 2 + OVER | player_game_summary.ft_attempts | Drawing fouls = scoring |
| 18 | `plus_minus_hot` | Plus/minus last 3 > +10 avg + OVER | player_game_summary.plus_minus | Player impact when on court |
| 19 | `starter_promoted` | starter_flag last game = true + was bench | player_game_summary.starter_flag | Role upgrade = more opportunity |
| 20 | `paint_dominant` | paint_pct > 50% + opponent weak interior | player_game_summary shot zones | Inside game vs weak paint defense |

### C. Cross-Model Signals

| # | Signal Name | Logic | Data Source | Hypothesis |
|---|------------|-------|-------------|------------|
| 21 | `v9_v12_both_high_edge` | Both V9 and V12 edge >= 5 + same direction | V9 + V12 predictions | Two independent models very confident | **BLOCKED: N=1 in backtest. V12 only 12 days of data. Re-test April.** |
| 22 | `v9_v12_disagree_strong` | V9 edge >= 5 but V12 says opposite | V12 predictions | Model disagreement = uncertainty = skip | **PROMISING but N=8. 37.5% HR suggests veto value. Re-test April.** |
| 23 | `v9_confident_v12_edge` | V9 confidence >= 80% + V12 edge >= 3 | Both models | Confidence + independent edge | **KILLED: 50.0% HR (N=28). Dead flat coin flip. No alpha.** |

---

## Part 2: Dimensional Filters (12 dimensions x every signal)

Every signal (existing + new) should be tested across ALL of these dimensions:

### A. Player Dimensions

| Dimension | Buckets | Source |
|-----------|---------|--------|
| **Position** | PG, SG, SF, PF, C (+ hybrids) | player_game_summary.position |
| **Player Tier** | Elite (>25ppg), Star (20-25), Starter (15-20), Role (10-15), Bench (<10) | Feature 2 (points_avg_season) |
| **Minutes Bucket** | Heavy (32+), Starter (25-32), Bench (<25) | minutes_avg_season |
| **Consistency** | Low-var (std<3), Mid-var (3-6), High-var (std>6) | Feature 3 (points_std_last_10) |
| **Experience** | Many games this season (50+), moderate (30-50), few (<30) | games played count |

### B. Game Context Dimensions

| Dimension | Buckets | Source |
|-----------|---------|--------|
| **Home/Away** | Home, Away | Derived from game_id |
| **Rest Days** | B2B (0-1), Short (2), Normal (3), Well-rested (4+) | rest_days |
| **Day of Week** | Mon-Thu, Fri, Sat, Sun | game_date |
| **Game Total** | High (>225), Medium (215-225), Low (<215) | Feature 38 (game_total_line) |
| **Spread** | Favored (spread < -3), Toss-up (-3 to +3), Underdog (>+3) | Feature 39 (spread_magnitude) |

### C. Model/Line Dimensions

| Dimension | Buckets | Source |
|-----------|---------|--------|
| **Edge Size** | Moderate (3-5), High (5-7), Extreme (7+) | prediction edge |
| **Direction** | OVER, UNDER | recommendation |
| **Confidence** | Low (<65%), Medium (65-80%), High (80-90%), Elite (>90%) | confidence_score |
| **Line Level** | Low (<15), Medium (15-25), High (>25) | line_value |
| **Line Source** | ACTUAL_PROP, ODDS_API, BETTINGPROS | line_source |
| **Model Staleness** | Fresh (<7d), Aging (7-21d), Stale (>21d) | Days since last model training |

### D. Team Dimensions

| Dimension | Buckets | Source |
|-----------|---------|--------|
| **Team Strength** | Elite (>60% win), Good (50-60%), Bad (<50%) | Feature 24 (team_win_pct) |
| **Opponent Strength** | Elite, Good, Bad | opponent win_pct |
| **Pace** | Fast (top 10), Medium, Slow (bottom 10) | Features 14, 22 |
| **Conference** | East, West | team_abbr lookup |

---

## Part 3: Combo Testing Matrix

### A. All Pairwise Combos (New + Existing)

With 23 existing signals + 13-23 new ones, that's up to ~600 possible pairs. We test the most promising subset:

**Priority Pairs (test these first):**

| Combo | Hypothesis |
|-------|-----------|
| `high_edge` + every new signal | High edge is the universal base — what adds value? |
| `minutes_surge` + every new signal | Minutes surge proved synergistic — what else? |
| `opponent_def_weak` + `team_hot_offense` | Both sides say "more scoring" |
| `usage_spike` + `minutes_surge` | Opportunity + time = more scoring |
| `scoring_trend_up` + `high_edge` | Trend + model agreement |
| `vegas_line_move_with` + `high_edge` | Sharp money + model agreement |
| `points_volatility_low` + `high_edge` | Consistent player + strong edge |
| `fatigue_score_high` + `b2b_fatigue_under` | Double fatigue confirmation for UNDER |
| `matchup_history_good` + `high_edge` | Historical + model |
| `ppm_efficient` + `minutes_surge` | Efficient + more time |

### B. Three-Way Combos

Session 257 showed 3-way combos can reach 88.9%. Extend to all promising triples:

| Combo | Why |
|-------|-----|
| `high_edge` + `minutes_surge` + every other signal | Extend the proven 2-way base |
| `high_edge` + `opponent_def_weak` + `minutes_surge` | Edge + opportunity + weak defense |
| `scoring_trend_up` + `minutes_surge` + `high_edge` | Trend + time + value |
| `vegas_line_move_with` + `high_edge` + `minutes_surge` | Triple confirmation |
| `usage_spike` + `ppm_efficient` + `high_edge` | Usage + efficiency + edge |

### C. Anti-Pattern Discovery

Systematically test 2-signal combos where **combo HR < worst individual HR**:

```
For each pair (A, B):
  combo_hr = HR(picks where both A and B fire)
  min_individual = min(HR(A), HR(B))
  if combo_hr < min_individual - 5%:
    FLAG AS ANTI-PATTERN
```

---

## Part 4: Composite Filter Stacking

Test stacking 2-3 dimensional filters on top of each signal:

### A. "Golden Path" Discovery

For each signal, find the single best dimensional filter, then stack a second:

```
For each signal S:
  For each dimension D with buckets [b1, b2, ...]:
    best_bucket = argmax(HR(S | D=bi))
    if best_bucket.HR > S.HR + 5%:
      For each second dimension D2:
        For each bucket b2j in D2:
          stacked_hr = HR(S | D=best_bucket AND D2=b2j)
          if stacked_hr > best_bucket.HR + 5%:
            RECORD "S + D=best + D2=b2j" as golden path
```

### B. Known High-Value Filters to Test on Every Signal

Based on Sessions 256-257, these filters often help:

| Filter | Who it helped |
|--------|--------------|
| HOME-ONLY | cold_snap (+62pt) |
| No Centers | blowout_recovery (+38pt) |
| No B2B | blowout_recovery (+12pt) |
| OVER-ONLY | Most offensive signals |
| Edge >= 5 | Eliminates low-conviction noise |
| Guards only (PG/SG) | 3pt_bounce, many signals |
| Star tier (20+ ppg) | Higher volume = more reliable |
| Fresh model only (<14d) | Eliminates decay-related failures |

Apply ALL of these filters to ALL signals and see which ones dramatically improve.

---

## Part 5: Execution Architecture

### Backtest Query Enhancements

The current `signal_backtest.py` query needs these additions:

```sql
-- Add to feature_data CTE:
fs.feature_5_value AS fatigue_score,
fs.feature_7_value AS usage_spike_score,
fs.feature_13_value AS opponent_def_rating,
fs.feature_23_value AS team_off_rating,
fs.feature_24_value AS team_win_pct,
fs.feature_27_value AS vegas_line_move,
fs.feature_29_value AS avg_points_vs_opponent,
fs.feature_30_value AS games_vs_opponent,
fs.feature_32_value AS ppm_avg_last_10,
fs.feature_34_value AS pts_slope_10g,
fs.feature_35_value AS pts_vs_season_zscore,
fs.feature_38_value AS game_total_line,
fs.feature_39_value AS spread_magnitude,
fs.feature_16_value AS home_away_flag,
fs.feature_17_value AS back_to_back_flag,

-- Add to game_stats CTE:
position,
assists,
rebounds,
personal_fouls,
ft_attempts,
plus_minus,
starter_flag,
points,
-- Rolling calculations for new signals:
AVG(assists) OVER (...ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS assists_avg_last_3,
AVG(assists) OVER (...ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS assists_avg_season,
AVG(rebounds) OVER (...ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS rebounds_avg_last_3,
AVG(CAST(rebounds AS FLOAT64)) OVER (...UNBOUNDED) AS rebounds_avg_season,
AVG(personal_fouls) OVER (...3 PRECEDING) AS fouls_avg_last_3,
AVG(CAST(ft_attempts AS FLOAT64)) OVER (...3 PRECEDING) AS ft_attempts_avg_last_3,
AVG(CAST(ft_attempts AS FLOAT64)) OVER (...UNBOUNDED) AS ft_attempts_avg_season,
AVG(plus_minus) OVER (...3 PRECEDING) AS plus_minus_avg_last_3,
AVG(points) OVER (...ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_avg_last_5_raw,
```

### Parallel Agent Architecture

Split the testing across 4-6 parallel agents:

| Agent | Scope | Estimated Runtime |
|-------|-------|-------------------|
| Agent 1 | New signals A (1-7): feature store signals | 10-15 min |
| Agent 2 | New signals B (8-13): matchup/vegas/trend signals | 10-15 min |
| Agent 3 | Dimensional analysis: all existing signals x 12 dimensions | 15-20 min |
| Agent 4 | Combo matrix: top 50 pairwise combos | 10-15 min |
| Agent 5 | Three-way combos: top 20 triples | 10-15 min |
| Agent 6 | Anti-pattern discovery: systematic degradation detection | 10-15 min |

### Output Format

Each agent produces a standardized results table:

```
Signal/Combo | Filter | N | HR% | ROI% | W1 HR | W2 HR | W3 HR | W4 HR | Verdict
```

Verdicts: PREMIUM (>70% HR, N>=15), STRONG (>60%, N>=20), VIABLE (>55%, N>=30), MARGINAL (52.4-55%), SKIP (<52.4%)

---

## Part 6: Expected Yield

Based on prior sessions:
- Sessions 256-257 tested ~150 combinations, found 3 production-grade signals and 5 critical filters
- This plan tests ~2,000+ permutations
- **Conservative estimate:** 5-10 new PREMIUM/STRONG signals, 10-20 new dimensional filters
- **Optimistic estimate:** 15-20 actionable findings that collectively improve Best Bets from ~60% HR to 70%+ HR

---

## Part 7: Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| PREMIUM signals (>70% HR) | 2 (combo_3way, cold_snap home) | 5+ |
| STRONG signals (>60% HR) | 3 (combo_he_ms, 3pt_bounce filtered) | 8+ |
| Anti-patterns catalogued | 2 (redundancy_trap, contradictory_signals) | 6+ |
| Dimensional filters validated | 5 (home, no-center, no-B2B, OVER, guards) | 15+ |
| Best Bets daily HR | ~58% estimated | 65%+ |

---

## Part 8: Implementation Priority

After testing, signals are promoted based on:

1. **HR >= 60%** across at least 2 eval windows
2. **N >= 15** total qualifying picks (not just one lucky window)
3. **ROI positive** at -110 standard odds
4. **No catastrophic window** (no single window below 40% HR)
5. **Temporal stability** (W3→W4 delta < 15 points)

Signals meeting all 5 criteria get implemented. Those meeting 4/5 become conditional (with dimensional filters). Those meeting 3/5 go to shadow monitoring.
