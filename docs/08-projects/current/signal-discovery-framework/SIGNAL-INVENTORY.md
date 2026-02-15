# Signal Inventory — Complete List

**Last Updated:** 2026-02-14 (Session 255)
**Total Signals:** 23 (8 existing + 15 new)

---

## Production Signals (8)

These signals are already deployed or in the existing registry:

| # | Signal Tag | Description | Status |
|---|------------|-------------|--------|
| 1 | `model_health` | Gate: blocks when HR < 52.4% | ✅ PRODUCTION |
| 2 | `high_edge` | Edge >= 5.0 points | ✅ PRODUCTION |
| 3 | `dual_agree` | V9 + V12 same direction | ⏸️ NEEDS V12 DATA |
| 4 | `3pt_bounce` | Cold 3PT shooter regression | ✅ PRODUCTION |
| 5 | `minutes_surge` | Minutes last 3 > season + 3 | ✅ PRODUCTION |
| 6 | `pace_mismatch` | Pace-based signal | ⏸️ DEFER (0 picks) |
| 7 | `cold_snap` | Mean reversion signal | ⚠️ DEPRECATED (research disproved) |
| 8 | `blowout_recovery` | Low minutes in blowout → OVER next | ✅ TESTING |

---

## New Signals - Batch 1: Prototype (5)

Implemented Session 255. Core validation signals across key categories.

| # | Signal Tag | Category | Expected HR | Notes |
|---|------------|----------|-------------|-------|
| 9 | `hot_streak_3` | Streak | 65-70% | 3+ consecutive line beats, context-aware |
| 10 | `cold_continuation_2` | Streak | **90%** | 2+ consecutive misses → continuation (research-backed) |
| 11 | `b2b_fatigue_under` | Rest/Fatigue | 65% | High-minute players on B2B → UNDER |
| 12 | `edge_spread_optimal` | Model Behavior | 75% | Edge 5+ excluding 88-90% problem tier |
| 13 | `rest_advantage_2d` | Rest/Fatigue | 60% | Player rested 2+ days vs fatigued opponent |

---

## New Signals - Batch 2: High-Value (10)

Implemented Session 255. High expected value based on research and data availability.

| # | Signal Tag | Category | Expected HR | Notes |
|---|------------|----------|-------------|-------|
| 14 | `hot_streak_2` | Streak | 55-60% | 2-game streak (lighter version) |
| 15 | `points_surge_3` | Streak | 60-65% | Points last 3 > season + 5 → OVER |
| 16 | `home_dog` | Team Context | 70% | Home underdog + edge 5+ (narrative) |
| 17 | `prop_value_gap_extreme` | Model Behavior | 70% | Edge >= 10 points (extreme conviction) |
| 18 | `minutes_surge_5` | Minutes/Usage | 65% | Minutes last 5 > season + 3 (sustained) |
| 19 | `three_pt_volume_surge` | Matchup | 60% | 3PA last 3 > season + 2 |
| 20 | `model_consensus_v9_v12` | Model Behavior | 75% | V9 + V12 agree, both edge >= 3 |
| 21 | `fg_cold_continuation` | Streak | 65% | FG% last 3 < season - 1 std → UNDER |
| 22 | `triple_stack` | Meta | 85% | 3+ signals qualify (overlap) |
| 23 | `scoring_acceleration` | Streak | 65% | Points trending up (L3 > L5 > season) |

---

## Planned Signals - Batch 3: Rest & Fatigue (10)

Next to implement. All designed and documented.

| Signal Tag | Description | Data Needed |
|------------|-------------|-------------|
| `rest_advantage_3d` | Player 3+ rest, opponent B2B | Schedule, rest days |
| `b2b_second_night_stars` | Stars (25+ ppg) on B2B → UNDER | Player tier, rest days |
| `b2b_role_player_opportunity` | Role player B2B, starter OUT | Injury report, roster |
| `three_in_four` | 3 games in 4 days → fatigue | Schedule density |
| `long_rest_rust` | 5+ days rest → UNDER first game | Rest days |
| `minutes_load_heavy` | Minutes last 5 > 38/game → UNDER | Minutes stats |
| `minutes_restriction` | Minutes last 3 < 25, season > 30 | Minutes stats |
| `fourth_game_week` | 4th game in 7 days → fatigue | Schedule density |
| `minutes_consistency` | Low minutes std dev → predictable | Minutes variance |
| `b2b_second_game_under` | Any B2B second game + UNDER | Rest days |

---

## Planned Signals - Batch 4: Matchup & Opponent (12)

| Signal Tag | Description | Data Needed |
|------------|-------------|-------------|
| `pace_up_extreme` | Opp top-5 pace + team bottom-10 | Pace stats |
| `pace_down_grind` | Opp bottom-5 pace + high usage | Pace stats |
| `defense_elite_matchup` | Opp top-5 defense → UNDER | Def rating |
| `defense_weak_matchup` | Opp bottom-5 defense → OVER | Def rating |
| `revenge_game` | Facing former team < 1 year | Player movement |
| `zone_advantage_paint` | Paint player vs weak paint D | Shot zones |
| `zone_advantage_three` | 3PT shooter vs weak perimeter D | Shot zones |
| `size_mismatch` | Big man vs small-ball lineup | Lineup data |
| `historical_dominance` | Career avg vs opp > season + 5 | Historical stats |
| `opponent_missing_defender` | Primary defender OUT → OVER | Injury report |
| `blowout_revenge` | Lost by 20+ earlier → motivated | Schedule history |
| `division_rival` | Division game, playoff race | Schedule, standings |

---

## Planned Signals - Batch 5: Team Context (10)

| Signal Tag | Description | Data Needed |
|------------|-------------|-------------|
| `win_streak_3` | Team 3+ win streak, home → OVER | Team record |
| `loss_streak_3` | Team 3+ loss streak → usage concentration | Team record |
| `team_shorthanded` | 2+ rotation players OUT → usage spike | Injury report |
| `injury_opportunity_starter` | Starter OUT, backup gets minutes | Injury + rotation |
| `injury_opportunity_usage` | Star OUT, secondary gets usage | Injury + usage |
| `close_game_expected` | Spread < 5, closer role → OVER | Game lines |
| `road_favorite_letdown` | Road favorite spread > 10 → letdown | Game lines |
| `back_to_back_road` | B2B both road games → extreme fatigue | Schedule |

---

## Planned Signals - Batch 6: Market & Line (8)

| Signal Tag | Description | Data Needed |
|------------|-------------|-------------|
| `line_move_fade` | Line moved against our rec → fade public | Opening/closing |
| `line_move_steam` | Line moved with our rec → follow steam | Opening/closing |
| `prop_value_gap_high` | Edge >= 7 points | Edge calc |
| `prop_value_gap_moderate` | Edge >= 5 points (enhanced high_edge) | Edge calc |
| `total_correlation_over` | Game total > 235 + OVER rec | Game totals |
| `total_correlation_under` | Game total < 215 + UNDER rec | Game totals |
| `spread_blowout_risk` | Spread > 12, favorite → garbage time | Game spread |
| `vegas_alignment` | Pred within 2 of vegas → fade | Pred vs line |

---

## Planned Signals - Batch 7: Model Behavior (10)

| Signal Tag | Description | Data Needed |
|------------|-------------|-------------|
| `high_confidence_pure` | Confidence >= 90% (no exclusions) | Model conf |
| `medium_confidence_safe` | Confidence 75-85% + edge >= 3 | Model conf |
| `model_consensus_strong` | V9 + V12 same + both edge >= 5 | V9 + V12 |
| `model_disagreement_fade` | V9 says OVER, V12 UNDER → skip | V9 + V12 |
| `vegas_deviation_extreme` | Pred > vegas by 8+ | Pred vs line |
| `confidence_edge_product` | confidence * edge >= 4.0 | Composite |
| `low_confidence_high_edge` | Conf < 70% but edge >= 8 | Model data |
| `model_edge_percentile` | Edge in top 10% of day's distribution | Daily dist |

---

## Planned Signals - Batch 8: Advanced & Combo (7)

| Signal Tag | Description | Data Needed |
|------------|-------------|-------------|
| `golden_quad` | high_edge + minutes_surge + 3pt_bounce + hot_streak | Multi-signal |
| `star_surge` | Elite + points_surge_3 + home | Tier + surge |
| `role_player_breakout` | Role + minutes_surge + usage_spike + starter OUT | Multi |
| `clutch_closer` | 4Q points > 30% + close game | Play-by-play |
| `heat_check` | Points last game > line + 10 + hot_streak_2 | Recent perf |
| `regression_to_mean_qualified` | 5+ streak + 2+ std deviation ONLY | Extreme |

---

## Signal Categories Summary

| Category | Signals Implemented | Signals Planned | Total |
|----------|---------------------|-----------------|-------|
| **Streak** | 5 | 0 | 5 |
| **Rest/Fatigue** | 2 | 10 | 12 |
| **Matchup/Opponent** | 1 | 12 | 13 |
| **Team Context** | 2 | 10 | 12 |
| **Market & Line** | 1 | 8 | 9 |
| **Model Behavior** | 3 | 10 | 13 |
| **Minutes/Usage** | 2 | 1 | 3 |
| **Meta/Combo** | 1 | 7 | 8 |
| **Gate** | 1 | 0 | 1 |
| **TOTAL** | **23** | **58** | **81** |

---

## Signal Performance Tiers (Expected)

### **Tier 1: Elite (HR >= 75%)**
- cold_continuation_2 (90% expected)
- triple_stack (85% from overlap)
- edge_spread_optimal (75%)
- model_consensus_v9_v12 (75%)

### **Tier 2: Strong (HR 65-74%)**
- hot_streak_3 (65-70%)
- home_dog (70%)
- prop_value_gap_extreme (70%)
- minutes_surge_5 (65%)
- fg_cold_continuation (65%)
- scoring_acceleration (65%)
- b2b_fatigue_under (65%)
- points_surge_3 (60-65%)

### **Tier 3: Good (HR 60-64%)**
- three_pt_volume_surge (60%)
- rest_advantage_2d (60%)

### **Tier 4: Baseline+ (HR 55-59%)**
- hot_streak_2 (55-60%)

### **Baseline**
- V9 edge 3+: 59.1% HR

---

## Data Requirements Status

### **✅ Available Now**
- Player tier (elite/stars/starters/role/bench)
- Rest days
- Streak data (consecutive wins/losses)
- 3PT stats (pct, attempts, rolling)
- Minutes stats (rolling averages)
- Pace data (opponent, team)
- V12 predictions
- Edge, confidence, recommendation

### **🟡 Partially Available**
- Home/away flag (not in backtest query yet)
- Points rolling averages (can add from feature store)
- FG% stats (need to add to query)

### **🔴 Not Available**
- Opponent rest days
- Game spread (underdog detection)
- Line movement (opening vs closing)
- Team win/loss streaks
- Injury report (teammate status)
- Play-by-play (4Q scoring)
- Shot zone matchups
- Lineup data

---

## Next Steps

1. **Run backtest** with current 23 signals
2. **Analyze results** — which beat baseline?
3. **Add missing data** to backtest query (home/away, FG%, points rolling)
4. **Implement Batch 3** — Rest/Fatigue (10 signals)
5. **Implement Batch 4** — Matchup/Opponent (12 signals)
6. **Build segmentation analysis** — performance by player tier, day of week, etc.
7. **Production promotion** — top 15-20 signals with context rules

---

## Production Readiness Criteria

For a signal to be promoted to production:

✅ **Performance:**
- HR >= 60% average across all windows
- HR >= baseline (59.1%) in at least 3 of 4 windows
- Positive ROI overall

✅ **Coverage:**
- N >= 20 picks per window (statistical significance)
- Qualifies on at least 10% of applicable game days

✅ **Stability:**
- Doesn't crash in W4 (model decay resilience)
- Works across different player tiers/contexts

✅ **Overlap Value:**
- Boosts existing signals when combined
- Or provides unique coverage (new player pool)

✅ **Technical:**
- No data quality issues
- Runs without errors
- Reasonable compute cost

---

## Signal Testing Checklist

When testing a new signal:

- [ ] Implement signal class
- [ ] Add to registry
- [ ] Run backtest
- [ ] Check HR vs baseline
- [ ] Check sample size (N >= 20?)
- [ ] Analyze overlap with existing signals
- [ ] Segment by player tier
- [ ] Segment by time period
- [ ] Check stability across windows
- [ ] Document findings
- [ ] Decide: SHIP, DEFER, or DROP

---

**Last Updated:** 2026-02-14, Session 255
**Next Review:** After Batch 3-4 implementation
