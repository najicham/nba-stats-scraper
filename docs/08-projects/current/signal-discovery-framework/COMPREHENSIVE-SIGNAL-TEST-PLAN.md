# Comprehensive Signal Testing Plan — Test Everything!

**Date:** 2026-02-14
**Philosophy:** Test every possible angle. We have 328k graded predictions, 4 eval windows, and a production-ready backtest harness. Let's find every edge.

---

## Executive Summary

**Goal:** Test 60+ signal variations across 8 grouping dimensions to find hidden edges

**Groupings:**
1. Player Type (stars, starters, role players, bench)
2. Time Period (month, week, day of week)
3. Game Context (home/away, rest, blowout/close)
4. Opponent Quality (defense rating, pace)
5. Team Context (win/loss streaks)
6. Market Context (spread, total, line movement)
7. Prop Type (points only for now, but ready for rebounds/assists)
8. Model Behavior (high confidence, edge tiers, prediction patterns)

**Test Strategy:**
- Run backtest with ALL signals enabled
- Post-process results to segment by each dimension
- Identify which signals work for which contexts
- Build context-aware signal rules

---

## Part 1: Signal Inventory (60+ Signals)

### **Category 1: Streak Signals** (15 signals)

#### 1.1 Prop Line Streaks
- **hot_streak_2** — 2+ consecutive line beats → continuation
- **hot_streak_3** — 3+ consecutive line beats → strong continuation
- **hot_streak_5** — 5+ consecutive line beats → extreme momentum
- **cold_continuation_2** — 2+ consecutive misses → continue betting against (UNDER if they've gone under)
- **cold_continuation_3** — 3+ consecutive misses → strong continuation
- **mixed_streak_break** — Alternating results (OVER, UNDER, OVER) → bet against pattern

#### 1.2 Scoring Streaks
- **points_surge_3** — Points last 3 > season avg + 5 → OVER
- **points_surge_5** — Points last 5 > season avg + 5 → OVER
- **points_slump_3** — Points last 3 < season avg - 5 → UNDER
- **scoring_acceleration** — Points trending up (last 3 > last 5 > season) → OVER
- **scoring_deceleration** — Points trending down (last 3 < last 5 < season) → UNDER

#### 1.3 Shooting Efficiency Streaks
- **fg_hot_streak** — FG% last 3 > season + 1 std → OVER
- **fg_cold_continuation** — FG% last 3 < season - 1 std → UNDER (continuation, not reversion)
- **three_pt_hot** — 3PT% last 3 > season + 1 std → OVER
- **three_pt_ice_cold** — 3PT% last 3 < 25% AND 3PA > 4/game → regression potential (experiment)

---

### **Category 2: Rest & Fatigue Signals** (10 signals)

- **rest_advantage_2d** — Player 2+ rest days, opponent 0-1 days → OVER
- **rest_advantage_3d** — Player 3+ rest days, opponent B2B → strong OVER
- **b2b_fatigue_under** — Player on B2B, high minutes (> 35 avg) → UNDER
- **b2b_second_night_stars** — Stars (ppg > 25) on B2B second game → UNDER
- **b2b_role_player_opportunity** — Role player (ppg 10-20) on B2B, starter out → OVER
- **three_in_four** — 3 games in 4 days, high minutes → UNDER
- **long_rest_rust** — 5+ days rest (unusual) → UNDER first game back
- **minutes_load_heavy** — Minutes last 5 > 38/game → fatigue UNDER signal
- **minutes_restriction** — Minutes last 3 < 25/game AND season avg > 30 → injury/rest UNDER
- **fourth_game_week** — 4th game in 7 days → fatigue check

---

### **Category 3: Matchup & Opponent Signals** (12 signals)

- **pace_up_extreme** — Opponent top-5 pace + team bottom-10 pace → OVER
- **pace_down_grind** — Opponent bottom-5 pace + player high-usage → UNDER
- **defense_elite_matchup** — Opponent top-5 defense rating → UNDER
- **defense_weak_matchup** — Opponent bottom-5 defense rating → OVER
- **revenge_game** — Facing former team within 1 year → narrative OVER
- **division_rival** — Division game, playoff implications → intensity boost
- **zone_advantage_paint** — Player paint% > 50% + opponent weak paint defense → OVER
- **zone_advantage_three** — Player 3PT% > 38% + opponent weak perimeter defense → OVER
- **size_mismatch** — Big man vs small-ball lineup → OVER
- **historical_dominance** — Player career avg vs this opponent > season avg + 5 → OVER
- **opponent_missing_defender** — Primary defender OUT → OVER
- **blowout_revenge** — Lost to this opponent by 20+ earlier in season → motivated OVER

---

### **Category 4: Team Context Signals** (10 signals)

- **win_streak_3** — Team on 3+ win streak, home game → OVER for stars
- **loss_streak_3** — Team on 3+ loss streak → usage concentration (stars OVER, role players UNDER)
- **team_shorthanded** — 2+ rotation players OUT → usage spike for available players
- **injury_opportunity_starter** — Starter OUT, backup gets minutes → OVER for backup
- **injury_opportunity_usage** — Star OUT, secondary scorer gets usage → OVER
- **blowout_recovery** — Player <20 min in blowout loss (margin > 20), normally plays 30+ → OVER next game
- **close_game_expected** — Spread < 5, player is closer → OVER (4th quarter usage)
- **home_dog** — Home underdog + high edge → motivated OVER
- **road_favorite_letdown** — Road heavy favorite (spread > 10) → letdown risk UNDER
- **back_to_back_road** — B2B both road games → extreme fatigue UNDER

---

### **Category 5: Market & Line Signals** (8 signals)

- **line_move_fade** — Line moved against our rec (opened higher, we say OVER) → fade public
- **line_move_steam** — Line moved with our rec (opened lower, we say OVER) → follow steam
- **prop_value_gap_extreme** — Edge >= 10 points → extreme conviction
- **prop_value_gap_high** — Edge >= 7 points → high conviction
- **prop_value_gap_moderate** — Edge >= 5 points (current high_edge)
- **total_correlation_over** — Game total high (> 235) + player OVER rec → pace boost
- **total_correlation_under** — Game total low (< 215) + player UNDER rec → grind game
- **spread_blowout_risk** — Spread > 12, player on favorite → garbage time risk UNDER

---

### **Category 6: Model Behavior Signals** (10 signals)

- **edge_spread_optimal** — Edge >= 5 + confidence 70-88% (exclude problem tier)
- **high_confidence_pure** — Confidence >= 90% (no tier exclusion)
- **medium_confidence_safe** — Confidence 75-85% + edge >= 3
- **model_consensus_v9_v12** — V9 + V12 same direction + both edge >= 3
- **model_consensus_strong** — V9 + V12 same direction + both edge >= 5
- **model_disagreement_fade** — V9 says OVER, V12 says UNDER (or vice versa) → skip
- **vegas_deviation_extreme** — Predicted points > vegas line by 8+ → model sees something
- **vegas_alignment** — Predicted points within 2 of vegas → market efficiency, fade
- **confidence_edge_product** — confidence * edge >= 4.0 → composite strength
- **low_confidence_high_edge** — Confidence < 70% but edge >= 8 → model unsure but big difference

---

### **Category 7: Minutes & Usage Signals** (8 signals)

- **minutes_surge_3** — Minutes last 3 > season + 3 (current production signal)
- **minutes_surge_5** — Minutes last 5 > season + 3 → sustained increase
- **minutes_volatility_high** — Minutes std dev > 8 → unpredictable, skip
- **minutes_consistent** — Minutes std dev < 3 → predictable, boost confidence
- **usage_spike_recent** — Usage rate last 3 > season + 5% → more shots
- **usage_spike_injury** — Teammate OUT + usage spike → structural change
- **minutes_ceiling** — Player approaching minutes max (40+ in game) → hard cap UNDER
- **minutes_floor** — Player benched last game (<15 min), coach pattern → UNDER

---

### **Category 8: Advanced & Combo Signals** (7 signals)

- **triple_stack** — Any 3+ signals qualify → exponential overlap
- **golden_quad** — high_edge + minutes_surge + 3pt_bounce + hot_streak → ultimate combo
- **star_surge** — Player type = star + points_surge_3 + home game → narrative
- **role_player_breakout** — Role player + minutes_surge + usage_spike + starter OUT → opportunity
- **clutch_closer** — 4Q points > 30% of total + close game expected → closer role
- **heat_check** — Points last game > line + 10 + hot_streak_2 → on fire
- **regression_to_mean_qualified** — Only after 5+ consecutive same result + extreme deviation (2+ std)

---

## Part 2: Grouping Dimensions (8 Dimensions)

### **Dimension 1: Player Type**

**Tiers:**
- **Elite (ppg > 25):** LeBron, Giannis, Luka, SGA, Tatum, etc.
- **Stars (ppg 20-25):** Secondary all-stars
- **Starters (ppg 15-20):** Solid rotation starters
- **Role Players (ppg 10-15):** Key bench/role players
- **Bench (ppg 5-10):** Deep bench
- **Deep Bench (ppg < 5):** Rarely plays

**Hypotheses:**
- Stars: Momentum signals (hot_streak, win_streak) work better
- Role players: Opportunity signals (injury_opportunity, minutes_surge) work better
- Bench: High volatility, skip or use only high-edge signals

**Backtest Segmentation:**
```python
# In post-processing
player_tiers = {
    'elite': players with season_ppg > 25,
    'stars': players with 20 <= season_ppg <= 25,
    'starters': players with 15 <= season_ppg < 20,
    'role': players with 10 <= season_ppg < 15,
    'bench': players with season_ppg < 10
}

for tier, players in player_tiers.items():
    tier_results = filter_results(all_results, player_lookup in players)
    compute_signal_performance(tier_results)
```

---

### **Dimension 2: Time Period**

**Segments:**
- **Month:** Nov, Dec, Jan, Feb, Mar, Apr
- **Week of Season:** Early (weeks 1-8), Mid (weeks 9-16), Late (weeks 17-24), Playoff Push (weeks 25+)
- **Day of Week:** Mon, Tue, Wed, Thu, Fri, Sat, Sun
- **Schedule Density:** Light week (<3 games), Normal (3-4 games), Heavy (5+ games)

**Hypotheses:**
- Early season: More volatility, rest signals matter less
- Mid season: Patterns stabilize, momentum signals peak
- Late season: Fatigue signals matter more, load management
- Sunday: Players rested, OVER bias
- Friday: End of week fatigue
- Heavy schedule weeks: Fatigue signals activate

**Backtest Segmentation:**
```python
# Group by month
monthly_results = {}
for month in ['2025-11', '2025-12', '2026-01', '2026-02']:
    monthly_results[month] = filter_results(all_results, game_date.startswith(month))

# Group by day of week
dow_results = {}
for dow in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
    dow_results[dow] = filter_results(all_results, game_date.weekday() == dow_map[dow])
```

---

### **Dimension 3: Game Context**

**Segments:**
- **Location:** Home, Away, Neutral (rare)
- **Rest Days:** 0 (B2B), 1, 2, 3, 4+
- **Game Margin (Final):** Blowout win (> +15), Close win (0 to +15), Close loss (0 to -15), Blowout loss (< -15)
- **Expected Competitiveness:** Spread < 3 (toss-up), 3-7 (moderate), 7-12 (likely), > 12 (blowout expected)

**Hypotheses:**
- Home: OVER bias for stars (crowd energy)
- B2B: UNDER for high-minute players, OVER for bench getting run
- Close expected: OVER for closers (4Q usage)
- Blowout expected: UNDER for starters (garbage time)

**Backtest Segmentation:**
```python
game_contexts = {
    'home': is_home == True,
    'away': is_home == False,
    'b2b': rest_days == 0,
    'rested': rest_days >= 2,
    'close_expected': abs(spread) < 3,
    'blowout_expected': abs(spread) > 12
}
```

---

### **Dimension 4: Opponent Quality**

**Segments:**
- **Defense Rating:** Top 5, Top 10, Middle, Bottom 10, Bottom 5
- **Pace:** Top 5 (fast), Middle, Bottom 5 (slow)
- **Defensive Style:** Switch-heavy, Zone, Man, Drop coverage
- **Record:** Elite (> .650), Good (.550-.650), Average (.450-.550), Poor (.350-.450), Tanking (< .350)

**Hypotheses:**
- Elite defense: UNDER bias, only high-edge OVER signals
- Weak defense: OVER bias, most signals work
- Fast pace: OVER bias for high-usage players
- Slow pace: UNDER bias, grind games

**Backtest Segmentation:**
```python
opponent_tiers = {
    'elite_defense': opponent_def_rating <= top_5_cutoff,
    'weak_defense': opponent_def_rating >= bottom_5_cutoff,
    'fast_pace': opponent_pace >= top_5_pace,
    'slow_pace': opponent_pace <= bottom_5_pace
}
```

---

### **Dimension 5: Team Context**

**Segments:**
- **Team Form:** Win streak (3+), Loss streak (3+), Neutral
- **Injury Status:** Shorthanded (2+ key players out), Full strength
- **Playoff Position:** Locked in, Fighting for seed, Play-in race, Eliminated
- **Travel:** Back-to-back road, 3rd road game in 4 days, Home stand

**Hypotheses:**
- Win streak + home: Stars OVER (confidence)
- Loss streak: Usage concentration (stars up, role players down)
- Shorthanded: Available players OVER (opportunity)
- Heavy travel: Fatigue UNDER

---

### **Dimension 6: Market Context**

**Segments:**
- **Public Betting:** Heavy public (> 70% of bets one side)
- **Line Movement:** Moved with us (steam), Moved against us (fade), No move
- **Closing Line Value:** Our rec aligned with close vs open
- **Vig/Juice:** High juice (> -120), Standard (-110), Low juice (< -105)

**Hypotheses:**
- Fade heavy public when we disagree
- Follow steam when line moves our direction
- Closing line value = market validation

---

### **Dimension 7: Prop Type** (Future)

**For now: Points only**
**Future:** Rebounds, Assists, 3PT Made, Pts+Rebs+Asts, Double-Double

**Hypotheses:**
- Different signals work for different prop types
- Rebounds: Size/matchup signals matter more
- Assists: Pace/tempo signals matter more
- 3PT: Shooting efficiency signals critical

---

### **Dimension 8: Model Behavior**

**Segments:**
- **Edge Tiers:** 0-3, 3-5, 5-7, 7-10, 10+
- **Confidence Tiers:** < 70%, 70-80%, 80-88%, 88-90% (problem tier), 90%+
- **Direction:** OVER vs UNDER
- **Agreement:** V9+V12 agree, disagree, V12 not available

**Hypotheses:**
- Edge 5-7: Sweet spot (not too aggressive, not weak)
- Confidence 88-90%: Problem tier, skip
- OVER bias: Check if signals work equally for UNDER
- V9+V12 agree: Validation boost

---

## Part 3: Implementation Strategy

### **Phase 1: Expand Backtest Query** (Data Collection)

Add these fields to the BigQuery query in `ml/experiments/signal_backtest.py`:

```sql
-- Add to existing query:

-- Player tier classification
CASE
  WHEN points_avg_season > 25 THEN 'elite'
  WHEN points_avg_season >= 20 THEN 'stars'
  WHEN points_avg_season >= 15 THEN 'starters'
  WHEN points_avg_season >= 10 THEN 'role'
  ELSE 'bench'
END as player_tier,

-- Time context
EXTRACT(MONTH FROM game_date) as game_month,
EXTRACT(DAYOFWEEK FROM game_date) as day_of_week,
FLOOR((DATE_DIFF(game_date, '2025-10-22', DAY)) / 7) as season_week,

-- Game context
is_home_game,
rest_days,  -- need to calculate from schedule
opponent_spread,  -- from odds_api_game_lines
game_total,  -- from odds_api_game_lines
final_margin,  -- actual_team_score - actual_opponent_score

-- Opponent quality
opponent_def_rating,  -- from team_defense_game_summary
opponent_win_pct,  -- from schedule

-- Team context
team_wins_last_3,  -- need to calculate
team_injuries_count,  -- from injury report

-- Streak data (most important!)
consecutive_line_beats,  -- WINDOW function
consecutive_line_misses,
points_last_3_avg,
points_last_5_avg,
fg_pct_last_3,
three_pct_last_3,
minutes_last_3_avg,
minutes_last_5_avg,
minutes_std_dev_season,

-- Market data
opening_line,  -- from odds_api (need to add)
closing_line,  -- current line_value
line_movement  -- closing - opening
```

This is a BIG query expansion. Might need to break into multiple supplemental queries.

---

### **Phase 2: Implement 60+ Signals**

Create signal classes in `ml/signals/`:

**Batch 1 (Streak Signals - 15 files):**
- `hot_streak_2.py`, `hot_streak_3.py`, `hot_streak_5.py`
- `cold_continuation_2.py`, `cold_continuation_3.py`
- `points_surge_3.py`, `points_surge_5.py`, `points_slump_3.py`
- `fg_hot_streak.py`, `fg_cold_continuation.py`
- `three_pt_hot.py`, `three_pt_ice_cold.py`
- `scoring_acceleration.py`, `scoring_deceleration.py`
- `mixed_streak_break.py`

**Batch 2 (Rest & Fatigue - 10 files):**
- `rest_advantage_2d.py`, `rest_advantage_3d.py`
- `b2b_fatigue_under.py`, `b2b_second_night_stars.py`, `b2b_role_player_opportunity.py`
- `three_in_four.py`, `long_rest_rust.py`
- `minutes_load_heavy.py`, `minutes_restriction.py`, `fourth_game_week.py`

**Batch 3 (Matchup & Opponent - 12 files):**
- All 12 matchup signals

**Batch 4 (Team Context - 10 files):**
- All 10 team context signals

**Batch 5 (Market & Line - 8 files):**
- All 8 market signals

**Batch 6 (Model Behavior - 10 files):**
- All 10 model behavior signals

**Batch 7 (Minutes & Usage - 8 files):**
- All 8 minutes/usage signals

**Batch 8 (Advanced & Combo - 7 files):**
- All 7 combo signals

**Total: 80 signal class files**

---

### **Phase 3: Batch Testing Approach**

Rather than run backtest 80 times, we'll:

1. **Enable all signals in registry** (build_default_registry)
2. **Run backtest ONCE** with all signals
3. **Post-process results** to segment by dimensions

**Enhanced backtest output:**
```python
# Save detailed results with ALL context
{
    'timestamp': '...',
    'predictions': [
        {
            'player_lookup': '...',
            'game_id': '...',
            'game_date': '...',
            'player_tier': 'elite',
            'day_of_week': 'Sunday',
            'is_home': True,
            'rest_days': 2,
            'opponent_def_rating': 110.5,
            'qualifying_signals': ['high_edge', 'hot_streak_3', 'minutes_surge'],
            'edge': 6.2,
            'confidence': 0.82,
            'prediction_correct': True,
            # ... all context fields
        },
        # ... 555 predictions across W2-W4
    ],
    'signal_performance': { ... },
    'overlap_analysis': { ... }
}
```

---

### **Phase 4: Segmented Analysis Script**

Create `ml/experiments/signal_segment_analysis.py`:

```python
"""
Analyze signal performance across all 8 dimensions.

Reads backtest JSON output, segments results, identifies patterns.
"""

def analyze_by_player_tier(results):
    """Break down each signal by elite/stars/starters/role/bench."""
    tiers = ['elite', 'stars', 'starters', 'role', 'bench']
    for signal_tag in all_signal_tags:
        for tier in tiers:
            tier_picks = filter(results, player_tier=tier, signal=signal_tag)
            hr = compute_hit_rate(tier_picks)
            print(f"{signal_tag} on {tier}: {hr}% (N={len(tier_picks)})")

def analyze_by_time_period(results):
    """Break down by month, week, day of week."""
    # Monthly
    for month in ['11', '12', '01', '02']:
        month_picks = filter(results, game_month=month)
        # ... compute per-signal HR

    # Day of week
    for dow in range(7):
        dow_picks = filter(results, day_of_week=dow)
        # ... compute per-signal HR

def analyze_by_game_context(results):
    """Break down by home/away, rest, spread, etc."""
    # Home vs away
    home_picks = filter(results, is_home=True)
    away_picks = filter(results, is_home=False)

    # Rest tiers
    b2b_picks = filter(results, rest_days=0)
    rested_picks = filter(results, rest_days>=2)

    # ... etc

def find_hidden_edges(results):
    """Identify signal + context combos with exceptional performance."""
    # Example: "hot_streak_3 works at 85% for elite players on Sundays"
    combos = []
    for signal in signals:
        for tier in tiers:
            for dow in days:
                combo_picks = filter(results, signal=signal, tier=tier, dow=dow)
                if len(combo_picks) >= 10 and hit_rate(combo_picks) >= 75:
                    combos.append({
                        'signal': signal,
                        'tier': tier,
                        'dow': dow,
                        'hr': hit_rate(combo_picks),
                        'n': len(combo_picks),
                        'roi': compute_roi(combo_picks)
                    })
    return sorted(combos, key=lambda x: x['hr'], reverse=True)
```

---

### **Phase 5: Results Matrix**

Output format (example for `hot_streak_3`):

```
SIGNAL: hot_streak_3 (3+ consecutive line beats)
Overall: 68.2% HR (N=127)

By Player Tier:
  Elite:    72.3% HR (N=47)   ← Works best for stars!
  Stars:    69.1% HR (N=34)
  Starters: 64.2% HR (N=28)
  Role:     58.3% HR (N=12)
  Bench:    50.0% HR (N=6)    ← Doesn't work for bench

By Time Period:
  November:  62.1% HR (N=29)
  December:  71.4% HR (N=35)  ← Peak month
  January:   69.2% HR (N=39)
  February:  60.0% HR (N=24)

By Day of Week:
  Sunday:    78.6% HR (N=28)  ← Best day! (rested)
  Monday:    65.2% HR (N=23)
  Tuesday:   63.3% HR (N=18)
  Wednesday: 70.0% HR (N=20)
  Thursday:  64.7% HR (N=17)
  Friday:    58.3% HR (N=12)  ← Worst day (fatigue?)
  Saturday:  72.7% HR (N=11)

By Game Context:
  Home:      73.5% HR (N=68)  ← Home advantage confirmed
  Away:      62.7% HR (N=59)

  B2B:       55.6% HR (N=18)  ← Momentum interrupted by fatigue
  Rested:    71.4% HR (N=84)  ← Works best with rest

By Opponent Quality:
  Elite Def:  58.3% HR (N=12) ← Tough matchup limits streak
  Weak Def:   75.0% HR (N=32) ← Feast on weak defenses

VERDICT: SHIP with context rules
  ✅ Use for Elite/Stars on Sunday/Saturday, Home, Rested (2+ days)
  ✅ Boost confidence vs weak defense
  ❌ Skip on B2B or vs elite defense
  ❌ Skip for bench players
```

---

## Part 4: Expected Insights & Discoveries

### **High-Probability Discoveries:**

1. **Player Tier Segmentation:**
   - Stars: Momentum signals (streaks, win streaks) work best
   - Role players: Opportunity signals (minutes surge, injury replacement) dominate
   - Bench: Only extreme edge signals (10+) work

2. **Day of Week Patterns:**
   - Sunday: Players rested, OVER bias expected
   - Friday: End-of-week fatigue, UNDER bias expected
   - Wednesday: Mid-week, neutral

3. **Rest Day Sweet Spot:**
   - B2B: Fatigue signals activate, UNDER for high-minute players
   - 2-3 days rest: Optimal, most signals work
   - 4+ days: Rust effect possible, first game back UNDER risk

4. **Home/Away Split:**
   - Home: OVER bias for stars (crowd, routine)
   - Away: UNDER bias (travel, schedule)

5. **Opponent Defense Tiers:**
   - Elite defense (top 5): Only high-edge (7+) OVER signals work
   - Weak defense (bottom 5): Most OVER signals work

6. **Month/Season Stage:**
   - Early season (Nov-Dec): High volatility, use only strong signals
   - Mid season (Jan-Feb): Patterns stable, peak signal performance
   - Late season (Mar-Apr): Fatigue/load management dominates

7. **Spread Context:**
   - Close games (spread < 3): 4Q usage matters, closers OVER
   - Blowouts expected (spread > 12): Garbage time risk, starters UNDER

### **Medium-Probability Discoveries:**

8. **Streak Length Thresholds:**
   - 2-game streaks: Noisy, 55-60% continuation
   - 3-game streaks: Strong, 65-70% continuation
   - 5-game streaks: Extreme, 75%+ but rare (N < 20)

9. **Team Context Interactions:**
   - Win streak + home + star = narrative stack (80%+ expected)
   - Loss streak + away + role player = usage collapse (UNDER)

10. **Market Inefficiencies:**
    - Line moves against us: Public wrong, fade them (65%+ expected)
    - No line movement: Market agrees, lower edge

### **Low-Probability But High-Value Discoveries:**

11. **Hidden Edge Combos:**
    - Specific signal + tier + day + context combo hits 85%+
    - Example: "role_player_breakout on Sunday home games vs weak defense"

12. **Anti-Signals (When NOT to Bet):**
    - Signals that predict WORSE than baseline in certain contexts
    - Use to filter out picks, not just add picks

13. **Prop Type Specialization:**
    - When we expand to rebounds/assists, certain signals only work for certain props

---

## Part 5: Execution Roadmap

### **Week 1: Infrastructure** (Days 1-2)
- [ ] Expand backtest query with all context fields
- [ ] Add streak calculations (consecutive_line_beats, etc.)
- [ ] Test query on small date range
- [ ] Verify all fields populate correctly

### **Week 1: Signal Implementation** (Days 3-7)
- [ ] Implement Batch 1: Streak signals (15 signals)
- [ ] Implement Batch 2: Rest & Fatigue (10 signals)
- [ ] Register all 25 signals
- [ ] Run mini-backtest on W2 only (validation)

### **Week 2: More Signals** (Days 8-14)
- [ ] Implement Batch 3: Matchup & Opponent (12 signals)
- [ ] Implement Batch 4: Team Context (10 signals)
- [ ] Implement Batch 5: Market & Line (8 signals)
- [ ] Run full backtest with 55 signals (W1-W4)
- [ ] Save detailed JSON output

### **Week 3: Analysis** (Days 15-21)
- [ ] Implement Batch 6-8: Model + Minutes + Combo (25 signals)
- [ ] Run FINAL backtest with all 80 signals
- [ ] Build `signal_segment_analysis.py` script
- [ ] Generate per-signal performance matrices
- [ ] Identify top 20 context-aware rules

### **Week 4: Production Promotion** (Days 22-28)
- [ ] Select top 15-20 signals for production
- [ ] Implement context-aware filtering (e.g., "hot_streak_3 only for elite players on Sunday")
- [ ] Update aggregator with new signals + context rules
- [ ] Shadow mode testing (1 week)
- [ ] Production launch

---

## Part 6: Success Criteria

**Tier 1 (Must Achieve):**
- At least 10 new signals with HR >= 65% overall
- At least 3 new signals with HR >= 70% in specific contexts
- Identify at least 5 context rules that boost HR by 5+ pp
- Aggregator improves from 60.8% to 67%+ avg HR

**Tier 2 (Stretch Goals):**
- Find 1 signal with HR >= 80% in specific context
- Find 1 hidden edge combo (signal + tier + day + context) >= 85%
- Identify anti-signals that prevent losses (skip picks that would lose)
- Build dynamic context-aware aggregator (different signals for different contexts)

**Tier 3 (Moonshots):**
- Find signals that work for UNDER (current signals are OVER-biased)
- Find bench player signals (currently impossible)
- Find signals that predict 90%+ in ultra-specific contexts (N >= 10)

---

## Part 7: Risk Management

**Overfitting Prevention:**
- Require N >= 20 picks in any segment before trusting HR
- Test across 4 independent windows (W1-W4)
- Validate on W1 (held out from previous signal development)
- Require context rules to work in at least 3 of 4 windows

**Sample Size Warnings:**
- Flag any segment with N < 10 as "insufficient data"
- Combine similar contexts if N too small (e.g., Sat+Sun = "weekend")

**Baseline Comparisons:**
- Every signal must beat V9 edge 3+ baseline (59.1%) in its context
- Context rules must beat signal's overall performance

---

## Part 8: Deliverables

1. **Comprehensive Signal Performance Report** (200+ page PDF)
   - Per-signal overall metrics
   - Per-signal segmented by 8 dimensions
   - Top 50 context-aware rules
   - Anti-signal findings (when to skip)

2. **Production Signal Registry** (Code)
   - 15-20 promoted signals
   - Context-aware evaluator
   - Dynamic aggregator

3. **Interactive Dashboard** (Future)
   - Query signal performance by any dimension
   - Visualize HR by player tier, day, month, etc.

4. **Research Findings Document**
   - Novel discoveries (e.g., "Sunday OVER bias")
   - Market inefficiencies identified
   - Recommendations for future signal development

---

## Part 9: Example Signal Implementations

### Example 1: hot_streak_3.py
```python
from typing import Dict, Optional
from ml.signals.base_signal import BaseSignal, SignalResult

class HotStreak3Signal(BaseSignal):
    tag = "hot_streak_3"
    description = "Player beat line in 3+ consecutive games"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        if not supplemental or 'streak_data' not in supplemental:
            return self._no_qualify()

        streak = supplemental['streak_data'].get('consecutive_line_beats', 0)

        if streak < 3:
            return self._no_qualify()

        # Context-aware confidence (higher for elite players, home games, rested)
        base_confidence = min(1.0, streak / 5.0)

        # Boost confidence for favorable contexts
        tier = prediction.get('player_tier', 'unknown')
        is_home = prediction.get('is_home', False)
        rest_days = prediction.get('rest_days', 0)

        context_boost = 0.0
        if tier == 'elite':
            context_boost += 0.1
        if is_home:
            context_boost += 0.05
        if rest_days >= 2:
            context_boost += 0.05

        confidence = min(1.0, base_confidence + context_boost)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'streak': streak,
                'tier': tier,
                'is_home': is_home,
                'rest_days': rest_days,
                'context_boost': context_boost
            }
        )
```

### Example 2: b2b_fatigue_under.py
```python
class B2BFatigueUnderSignal(BaseSignal):
    tag = "b2b_fatigue_under"
    description = "High-minute player on back-to-back, predict UNDER"

    MIN_MINUTES_AVG = 35.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> SignalResult:

        # Must be B2B
        if prediction.get('rest_days', 1) != 0:
            return self._no_qualify()

        # Must be UNDER recommendation
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        # Must be high-minute player
        if not supplemental or 'minutes_stats' not in supplemental:
            return self._no_qualify()

        minutes_avg = supplemental['minutes_stats'].get('minutes_avg_season', 0)

        if minutes_avg < self.MIN_MINUTES_AVG:
            return self._no_qualify()

        # Confidence scales with minutes load
        confidence = min(1.0, (minutes_avg - self.MIN_MINUTES_AVG) / 5.0)

        return SignalResult(
            qualifies=True,
            confidence=confidence,
            source_tag=self.tag,
            metadata={
                'minutes_avg_season': minutes_avg,
                'rest_days': 0
            }
        )
```

---

## Summary

**This is a comprehensive, no-stone-unturned approach to signal discovery.**

We're testing:
- **80+ signal variations**
- **8 segmentation dimensions**
- **328k+ graded predictions**
- **4 independent eval windows**
- **Hundreds of context-specific rules**

**Expected outcome:**
- 15-20 production signals (vs 6 current)
- Context-aware aggregator (different signals for stars vs role players, home vs away, etc.)
- 67%+ avg HR (vs 60.8% current)
- Complete understanding of what works when

**Timeline:** 4 weeks from backtest query expansion to production launch

**Let's test EVERYTHING and find every edge!** 🚀
