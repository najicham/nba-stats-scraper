# Signal Discovery Framework — Master Plan & Brainstorm

**Date:** 2026-02-14
**Status:** Planning
**Goal:** Systematically test new signal ideas to improve hit rate beyond the 66-76% baseline

---

## Executive Summary

Based on comprehensive research of previous experiments, available data sources, and success patterns, we have identified **32 signal candidates** for testing. The backtest harness is production-ready at `ml/experiments/signal_backtest.py`.

**Key findings from research:**
- **Signal overlap is exponential:** Multi-signal picks hit 76.5% vs 59-67% single-signal
- **Continuation beats reversion:** After 2 consecutive unders → 10% over rate (NOT 50%)
- **Edge is king:** High edge (5+) = 66.7% baseline, edge 3+ = breakeven threshold
- **Model health gates prevent disasters:** Would have blocked W4 collapse entirely

---

## Signals Already in Production

| Signal | Type | Performance | Status |
|--------|------|-------------|--------|
| **model_health** | Gate | Blocks when HR < 52.4% | ✅ SHIP |
| **high_edge** | Pick | 66.7% HR avg | ✅ SHIP |
| **3pt_bounce** | Pick | 74.9% HR avg | ✅ SHIP |
| **minutes_surge** | Pick | 53.7% standalone, 87.5% overlap | ✅ SHIP |
| **dual_agree** | Pick | 45.5% (needs more V12 data) | ⏸️ DEFER |
| **pace_up** | Pick | 0 qualifying picks | ❌ DROP |
| **pct_over daily signal** | Meta | 28pp difference RED vs GREEN days | ✅ PRODUCTION |

---

## Signals Already Tested (Dead Ends)

| Signal | Result | Reason |
|--------|--------|--------|
| **Mean reversion** | ❌ DISPROVEN | Continuation effect instead (10% over after 2 unders) |
| **Cold snap bounce** | ❌ DISPROVEN | Same as above — cold streaks persist |
| **Star player FG% reversion** | ❌ INCONSISTENT | Elite players never cold, volume shooters stay cold |

---

## Available Data Sources

### Tier 1: Readily Available (Already in Backtest Query)
- ✅ `prediction_accuracy` — 328k graded predictions, edge, actual_points, prediction_correct
- ✅ `player_game_summary` — Points, minutes, 3PT, FG%, every game since 2025-10-22
- ✅ `ml_feature_store_v2` — 33 pre-engineered features (pace, matchup, rest, etc.)
- ✅ V12 predictions — Vegas-free model for dual-signal
- ✅ Feature store: `opponent_pace`, `team_pace`, `is_home`, `back_to_back`

### Tier 2: Easy to Add (Single JOIN)
- 🟡 `nbac_schedule` — Home/away, rest days, game status
- 🟡 `odds_api_game_lines` — Moneylines, spreads, totals
- 🟡 `player_composite_factors` — Precomputed fatigue, usage spike
- 🟡 `team_defense_zone_analysis` — Defensive strength by zone

### Tier 3: Moderate Effort (Needs Supplemental Query)
- 🟠 `nbac_injury_report` — Teammate injuries
- 🟠 Prop line history — Track line moves over time
- 🟠 Shot zone efficiency — Paint/mid-range/3PT percentages
- 🟠 Play-by-play — 4th quarter scoring, clutch performance

### Tier 4: Complex (Needs New Processing)
- 🔴 Referee assignments — Ref tendencies
- 🔴 Team roster changes — Trades, signings
- 🔴 Historical head-to-head — Player vs specific opponent
- 🔴 Usage rate — Calculated from play-by-play

---

## Signal Candidates — Prioritized

### **Category A: Quick Wins (Tier 1 Data, Low Complexity)**

#### A1. **hot_streak** ⭐ HIGH PRIORITY
- **Hypothesis:** Players who beat their line 3+ consecutive games continue momentum
- **Data:** `prediction_accuracy` (already in backtest)
- **Logic:**
  ```python
  last_3_results = get_player_last_3_graded(player_lookup)
  if all(r['prediction_correct'] for r in last_3_results):
      qualifies = True
  ```
- **Expected:** 60-70% HR (continuation effect from research)
- **Complexity:** 🟢 LOW (just need to look back at prediction_accuracy)
- **Overlaps well with:** high_edge, minutes_surge

#### A2. **cold_continuation** ⭐ HIGH PRIORITY (INVERTED FROM DEAD END)
- **Hypothesis:** After 2+ consecutive UNDER results, predict UNDER (NOT over bounce)
- **Data:** `prediction_accuracy`
- **Logic:** Flip the failed "cold snap" signal — use continuation, not reversion
- **Expected:** 90% HR (research shows 10% over rate = 90% under rate)
- **Complexity:** 🟢 LOW
- **Note:** Only applies to UNDER recommendations

#### A3. **edge_spread** (High edge + narrow confidence band)
- **Hypothesis:** High edge (5+) + confidence 70-88% (excludes problem tier) = safest picks
- **Data:** Already in prediction dict
- **Logic:** `edge >= 5.0 AND 0.70 <= confidence < 0.88`
- **Expected:** 75%+ HR (addresses 88-90% problem tier)
- **Complexity:** 🟢 LOW

#### A4. **v9_v12_edge_agree** (Enhanced dual_agree)
- **Hypothesis:** When V9 and V12 both have edge >= 3.0 (not just same direction)
- **Data:** V12 already in backtest query
- **Logic:** `v9.edge >= 3.0 AND v12.edge >= 3.0 AND v9.recommendation == v12.recommendation`
- **Expected:** 70%+ HR (stricter than current dual_agree)
- **Complexity:** 🟢 LOW

#### A5. **fg_pct_cold** (Shooting efficiency continuation)
- **Hypothesis:** FG% < 40% last 2 games + UNDER = high confidence
- **Data:** `player_game_summary` (need to add FG% to backtest query)
- **Logic:** Mean reversion research showed cold FG% continues (44.4% vs 47% baseline)
- **Expected:** 65%+ HR
- **Complexity:** 🟡 MEDIUM (need to add FG stats to backtest query)

---

### **Category B: Moderate Complexity (Tier 2 Data)**

#### B1. **home_dog** ⭐ HIGH PRIORITY
- **Hypothesis:** Home underdogs with high edge outperform (crowd support + low expectations)
- **Data:** `is_home` (already in features), moneyline from `odds_api_game_lines`
- **Logic:** `is_home AND team_is_underdog AND edge >= 5.0`
- **Expected:** 70%+ HR
- **Complexity:** 🟡 MEDIUM (need to join game_lines for moneyline)

#### B2. **rest_advantage**
- **Hypothesis:** Players on 2+ rest days vs opponent on back-to-back
- **Data:** `nbac_schedule` (rest days between games)
- **Logic:** `player_rest_days >= 2 AND opponent_rest_days == 0`
- **Expected:** 60%+ HR
- **Complexity:** 🟡 MEDIUM (need rest day calculation)

#### B3. **fatigue_score_high**
- **Hypothesis:** Precomputed fatigue score from Phase 4 predicts UNDER
- **Data:** `player_composite_factors.fatigue_score`
- **Logic:** `fatigue_score > 0.7 AND recommendation == 'UNDER'`
- **Expected:** 60%+ HR
- **Complexity:** 🟡 MEDIUM (join precompute table)

#### B4. **usage_spike**
- **Hypothesis:** Usage spike score predicts OVER (more shots = more points)
- **Data:** `player_composite_factors.usage_spike_score`
- **Logic:** `usage_spike_score > 0.6 AND recommendation == 'OVER'`
- **Expected:** 65%+ HR
- **Complexity:** 🟡 MEDIUM

#### B5. **shot_zone_mismatch**
- **Hypothesis:** Player's shot zones vs opponent's defensive weakness
- **Data:** `player_composite_factors.shot_zone_mismatch_score`
- **Logic:** `shot_zone_mismatch_score > 0.7`
- **Expected:** 60%+ HR
- **Complexity:** 🟡 MEDIUM

#### B6. **pace_extremes** (Enhanced pace_up)
- **Hypothesis:** Top-10 opponent pace + bottom-10 team pace = OVER
- **Data:** Feature store (already have pace data)
- **Logic:** Relax pace_up thresholds from top-5/bottom-15 to top-10/bottom-10
- **Expected:** 55%+ HR (better coverage than pace_up which had 0 picks)
- **Complexity:** 🟢 LOW (just adjust thresholds)

---

### **Category C: Complex (Tier 3 Data, Needs Supplemental Queries)**

#### C1. **injury_opportunity**
- **Hypothesis:** Teammate OUT → role player gets more minutes/usage
- **Data:** `nbac_injury_report` + team roster
- **Logic:**
  - Identify OUT players on same team
  - Check if prediction player is role player (ppg 10-20)
  - Check if OUT player is starter (ppg > 20)
- **Expected:** 70%+ HR (structural opportunity)
- **Complexity:** 🟠 HIGH (teammate context needed)

#### C2. **blowout_recovery**
- **Hypothesis:** Player with very low minutes in blowout (< 20 min when avg 30+) → OVER next game
- **Data:** `player_game_summary` (previous game minutes)
- **Logic:**
  - Previous game: `minutes < season_avg - 10 AND game_margin > 20`
  - Current prediction: OVER
- **Expected:** 60%+ HR (coach makes up for rest)
- **Complexity:** 🟠 HIGH (need previous game context + game margin)

#### C3. **line_move_fade**
- **Hypothesis:** When line moves AGAINST our prediction (line drops, we say OVER), fade the public
- **Data:** `odds_api_player_props` (opening vs closing line)
- **Logic:** `opening_line - closing_line > 0.5 AND recommendation == 'OVER'`
- **Expected:** 65%+ HR
- **Complexity:** 🟠 HIGH (need line history)

#### C4. **fourth_quarter_closer**
- **Hypothesis:** Players who score disproportionately in 4Q + close game expected
- **Data:** Play-by-play (need to add 4Q points)
- **Logic:** `pct_points_in_4q > 0.30 AND game_spread < 5`
- **Expected:** 60%+ HR
- **Complexity:** 🟠 HIGH (play-by-play processing)

#### C5. **revenge_game**
- **Hypothesis:** Players facing former teams are motivated
- **Data:** `player_movement` history + schedule
- **Logic:** `opponent_team_abbr IN player_former_teams AND weeks_since_trade <= 52`
- **Expected:** 55%+ HR (narrative-driven, may not be real)
- **Complexity:** 🟠 HIGH (player history tracking)

#### C6. **zone_advantage**
- **Hypothesis:** Player's best zone (paint/mid/3PT) vs opponent's worst defensive zone
- **Data:** `player_shot_zone_analysis` + `team_defense_zone_analysis`
- **Logic:**
  - Player paint% > 0.5 AND opponent paint_defense_rating < 20th percentile
- **Expected:** 60%+ HR
- **Complexity:** 🟠 HIGH (zone-level joins)

---

### **Category D: Experimental (Novel Ideas)**

#### D1. **prop_value_gap**
- **Hypothesis:** When prediction is 10+ points from line, even UNDER recommendations can hit
- **Data:** Already in prediction (edge)
- **Logic:** `ABS(edge) >= 10.0` (regardless of confidence)
- **Expected:** 70%+ HR (extreme divergence signals strong model conviction)
- **Complexity:** 🟢 LOW

#### D2. **minutes_consistency**
- **Hypothesis:** Players with stable minutes (low std dev) are more predictable
- **Data:** `player_game_summary` (minutes std dev)
- **Logic:** `minutes_std_last_10 < 3.0`
- **Expected:** 60%+ HR
- **Complexity:** 🟡 MEDIUM (add std dev to supplemental)

#### D3. **opponent_pace_outlier**
- **Hypothesis:** When opponent pace is 2+ std dev from league avg, it affects scoring
- **Data:** Feature store (opponent_pace)
- **Logic:** `opponent_pace > league_avg + 2*std`
- **Expected:** 55%+ HR
- **Complexity:** 🟡 MEDIUM (need league-wide pace stats)

#### D4. **model_edge_percentile**
- **Hypothesis:** Edge relative to that day's distribution (top 10% of edges)
- **Data:** Daily edge distribution
- **Logic:** `edge >= daily_90th_percentile`
- **Expected:** 70%+ HR (relative strength vs absolute)
- **Complexity:** 🟡 MEDIUM (need daily percentiles)

#### D5. **star_minutes_decline** (Anti-fatigue)
- **Hypothesis:** Stars (ppg > 25) with declining minutes (last 3 < season avg - 5) → UNDER
- **Data:** `player_game_summary`
- **Logic:** `points_avg_season > 25 AND minutes_avg_last_3 < minutes_avg_season - 5 AND recommendation == 'UNDER'`
- **Expected:** 60%+ HR
- **Complexity:** 🟡 MEDIUM

#### D6. **team_win_streak**
- **Hypothesis:** Teams on 3+ game win streak, home favorites → OVER for stars
- **Data:** Schedule (game results)
- **Logic:** `team_wins_last_3 == 3 AND is_home AND team_is_favorite`
- **Expected:** 55%+ HR (momentum effect)
- **Complexity:** 🟠 HIGH (team win tracking)

#### D7. **b2b_second_game_under**
- **Hypothesis:** On 2nd game of back-to-back, even high-edge OVER picks underperform
- **Data:** Feature store (`back_to_back` flag)
- **Logic:** Inverse signal — EXCLUDE from signals when `back_to_back == True AND recommendation == 'OVER'`
- **Expected:** Improves aggregator by filtering out fatigue OVERs
- **Complexity:** 🟢 LOW

#### D8. **three_pt_volume_surge**
- **Hypothesis:** Player's 3PA last 3 > season avg + 2 → more scoring opportunities
- **Data:** Already have 3PT stats in supplemental
- **Logic:** `three_pa_avg_last_3 > three_pa_season + 2.0 AND recommendation == 'OVER'`
- **Expected:** 60%+ HR
- **Complexity:** 🟢 LOW (already have 3PT data)

---

### **Category E: Meta Signals (Multi-Signal Combinations)**

#### E1. **triple_stack** (3+ signals)
- **Logic:** Any pick with 3+ qualifying signals
- **Expected:** 85%+ HR (overlap exponential effect)
- **Complexity:** 🟢 LOW (aggregator already tracks this)

#### E2. **high_edge_minutes_3pt** (Golden trio)
- **Logic:** `high_edge + minutes_surge + 3pt_bounce` all qualify
- **Expected:** 90%+ HR (best known combo from W2-W3)
- **Complexity:** 🟢 LOW

#### E3. **model_consensus** (V9 + V12 + signal)
- **Logic:** `dual_agree + ANY other signal`
- **Expected:** 75%+ HR
- **Complexity:** 🟢 LOW

---

## Implementation Priority

### **Phase 1: Quick Wins (Week 1)**
Test these 5 signals first — all use Tier 1 data already in backtest:

1. ✅ **hot_streak** — continuation signal (expected 60-70% HR)
2. ✅ **cold_continuation** — inverted reversion (expected 90% HR for UNDERs)
3. ✅ **edge_spread** — exclude problem tier (expected 75% HR)
4. ✅ **three_pt_volume_surge** — 3PA spike signal (expected 60% HR)
5. ✅ **prop_value_gap** — extreme edge (expected 70% HR)

**Action items:**
- [ ] Add streak calculation to backtest query (prediction_accuracy history)
- [ ] Add FG% fields to backtest query (player_game_summary)
- [ ] Create 5 signal classes in `ml/signals/`
- [ ] Add to registry
- [ ] Run backtest: `PYTHONPATH=. python ml/experiments/signal_backtest.py --save`
- [ ] Analyze results, publish to docs

---

### **Phase 2: Moderate Complexity (Week 2)**
Add these 6 signals — require Tier 2 data (simple JOINs):

1. ✅ **home_dog** — home underdog signal
2. ✅ **rest_advantage** — rest days vs opponent
3. ✅ **fatigue_score_high** — precompute fatigue
4. ✅ **usage_spike** — precompute usage
5. ✅ **shot_zone_mismatch** — precompute mismatch
6. ✅ **pace_extremes** — relaxed pace_up

**Action items:**
- [ ] Add schedule JOIN to backtest (rest days, home/away, moneyline)
- [ ] Add composite_factors JOIN to backtest (fatigue, usage, mismatch)
- [ ] Create 6 signal classes
- [ ] Run backtest
- [ ] Compare vs Phase 1 results

---

### **Phase 3: Complex Signals (Week 3-4)**
Cherry-pick from Category C based on Phase 1-2 results:

- If overlap is working well → prioritize **injury_opportunity** (structural)
- If continuation is strong → prioritize **blowout_recovery** (rest effect)
- If line-based signals work → prioritize **line_move_fade**

**Action items:**
- [ ] Add injury report data (supplemental query)
- [ ] Add previous game context (blowout detection)
- [ ] Add line history (opening vs closing)
- [ ] Test 3-4 signals
- [ ] Publish findings

---

### **Phase 4: Production Integration (Week 5)**
Promote top performers to production:

**Criteria for promotion:**
- Avg HR across 4 windows >= 60%
- At least 20 qualifying picks per window
- Positive ROI across all windows
- Overlaps well with existing signals (boosts aggregator)

**Action items:**
- [ ] Update `build_default_registry()` with new signals
- [ ] Update `signal_annotator.py` with new supplemental queries
- [ ] Update BigQuery schema if new fields needed
- [ ] Deploy to production (Phase 6 export)
- [ ] Monitor for 1 week in shadow mode
- [ ] Full production launch

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Per-signal HR** | >= 60% avg across windows | Backtest output |
| **Multi-signal HR** | >= 75% (vs 76.5% baseline) | Overlap analysis |
| **Aggregator HR** | >= 65% (vs 60.8% baseline) | Daily top-5 simulation |
| **ROI** | >= +10% per signal | Compute_metrics in backtest |
| **Coverage** | >= 10 picks/window | Ensure not too restrictive |
| **Overlap boost** | >= +5pp when combined | Compare single vs multi |

---

## Risk Mitigation

1. **Model decay protection:** All signals subject to model_health gate (blocks when HR < 52.4%)
2. **Overfitting prevention:** Test on 4 independent time windows (W1-W4)
3. **Sample size threshold:** Require N >= 20 picks per window for valid signal
4. **Baseline comparison:** Every signal compared to V9 edge 3+ baseline (59.1% HR)
5. **Shadow mode:** New signals run in parallel for 1 week before production

---

## Notes

- **Don't revisit dead ends:** Mean reversion, pace_up (too restrictive), dual_agree until V12 has 30+ days data
- **Continuation > reversion:** Build on the 90% continuation finding
- **Overlap is exponential:** Every new signal can boost existing multi-signal combos
- **Data quality first:** Never relax zero-tolerance policy to boost coverage
- **Monthly retrain:** No evidence of decay within 28 days, don't over-retrain

---

## Document History

- 2026-02-14: Initial brainstorm and master plan created (Session 255)
