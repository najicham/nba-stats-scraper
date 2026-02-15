# Signal Testing Coverage Map

**Last Updated:** 2026-02-14 (Session 257)
**Purpose:** Track what's been tested, what hasn't, and prioritize future testing

---

## Completed Tests (Session 256-257)

### Session 256: Signal Discovery (4 agents)

| Test | What Was Tested | Key Result |
|------|----------------|------------|
| Intersection Analysis | Synergistic vs parasitic combos for top 5 | Combo-only filters are real (not harmful) |
| Segmentation Analysis | Profitable niches (tier, edge, OVER/UNDER) | 89.3% HR for stars OVER (line < 15) |
| Interaction Matrix | 7x7 pairwise combinations (21 pairs) | HE+MS 79.4% HR; HE+ES 31.3% anti-pattern |
| Zero-Pick Prototypes | Root cause for 13 non-firing signals | 6 HIGH priority need supplemental data |

### Session 257: Comprehensive Validation (9 agents)

| # | Dimension | Signals Tested | Segments | Status |
|---|-----------|---------------|----------|--------|
| 1A | **Temporal windows** | 8 combos x 2 windows (W3, W4) | 16 cells | COMPLETE |
| 1B | **Home vs Away** | 7 combos x 2 locations | 14 cells | COMPLETE |
| 1C | **Model staleness** | 6 combos x 5 age buckets | 30 cells | COMPLETE |
| 1D | **Position groups** | 6 combos x 3 positions (G/F/C) | 18 cells | COMPLETE |
| 2A | **3-way combos** | 35 possible combinations | 10 with data | COMPLETE |
| 2B | **Rest/B2B** | 5 combos x 4 rest categories | 11 cells w/ data | COMPLETE |
| 2C | **Team strength** | 6 combos x 3 tiers | 18 cells | COMPLETE |
| 3A | **Prop type** | N/A (points-only system) | N/A | COMPLETE (N/A) |
| 3B | **OVER vs UNDER** | 6 combos x 2 directions | 11 cells w/ data | COMPLETE |
| 3C | **Conference/matchup** | 4 combos x 2-3 matchup types | 8 cells | COMPLETE |

**Total tested cells: ~146 unique signal x segment combinations**

---

## Untested Angles — Prioritized

### Tier A: High-Value (Most Likely to Yield Actionable Filters)

| # | Angle | Why It Matters | Expected Effort | Data Available? |
|---|-------|---------------|-----------------|-----------------|
| A1 | **Line size buckets** (low <15, mid 15-25, high 25+) | Different line ranges may have different accuracy; stars (low lines) vs role players (high lines) | 30 min | Yes — `current_points_line` in `player_prop_predictions` |
| A2 | **Edge magnitude buckets** (3-5, 5-7, 7-10, 10+) | Are monster edges (10+) more reliable than moderate edges? Or is there diminishing returns? | 30 min | Yes — `predicted_points - current_points_line` |
| A3 | **Player recurrence** — how many times has this player been picked by this combo? | Frequent flyers vs one-time picks. Are combos better on fresh players or recurring ones? | 1 hour | Yes — count distinct game_dates per player per combo |
| A4 | **Opponent defensive rating** (top 10, middle 10, bottom 10 defenses) | Are combos better against weak defenses (more scoring = easier OVER)? | 1 hour | Partial — need to compute team defensive rating from `team_game_summary` |
| A5 | **Game total (O/U)** — predicted high-scoring vs low-scoring games | High-total games have more variance = more mispricing opportunities? | 45 min | Partial — need game totals from odds data |

### Tier B: Medium-Value (Interesting but Smaller Expected Impact)

| # | Angle | Why It Matters | Expected Effort | Data Available? |
|---|-------|---------------|-----------------|-----------------|
| B1 | **Day-of-week** (Mon-Thu vs Fri-Sun) | Weekend slates are bigger, more public money = different line efficiency | 30 min | Yes — `EXTRACT(DAYOFWEEK FROM game_date)` |
| B2 | **Slate size** (1-4 games vs 5-8 vs 9+) | Bigger slates = more options = potentially more mispricing | 30 min | Yes — count games per date from schedule |
| B3 | **Month-by-month breakdown** (Oct through Feb) | More granular than temporal windows; see exactly when signals turn on/off | 45 min | Yes — `FORMAT_DATE('%Y-%m', game_date)` |
| B4 | **Vegas line movement** — did the line move toward or away from our prediction? | Line movement = market information. Do combos perform differently when market agrees? | 1.5 hours | Partial — need early vs final lines from odds data |
| B5 | **Player minutes played** — actual minutes vs projected | When minutes_surge fires, how much did minutes actually increase? Does magnitude matter? | 1 hour | Yes — `player_game_summary.minutes` vs projected |
| B6 | **Prediction confidence** — model's raw confidence/probability | Are high-confidence model predictions better combo partners? | 30 min | Partial — may not be stored separately from edge |

### Tier C: Exploratory (Low Confidence in Payoff)

| # | Angle | Why It Matters | Expected Effort | Data Available? |
|---|-------|---------------|-----------------|-----------------|
| C1 | **4-way combos** | Do any 4-signal combinations have enough data? (Probably not) | 30 min | Yes but likely <3 picks per combo |
| C2 | **Team win/loss streak** | Are combos better when team is on a winning streak? | 1 hour | Need to compute from schedule |
| C3 | **Player streak** (last 3-5 games OVER/UNDER) | Is there momentum? Do cold players stay cold? | 1 hour | Need to compute from player_game_summary |
| C4 | **Time of day** — early vs late games | Fatigue, travel, primetime national TV effect | 30 min | Partial — need game start times |
| C5 | **Injury context** — key teammate out | When a star is out, do role player combos improve (more opportunity)? | 2 hours | Need injury data JOIN |
| C6 | **Line source** — ACTUAL_PROP vs ODDS_API vs BETTINGPROS | Does combo performance vary by where the line came from? | 30 min | Yes — `line_source` in `prediction_accuracy` |
| C7 | **Score differential in combo games** — how close were the games? | Do combos work in blowouts or close games? | 45 min | Yes — final scores in schedule |

---

## Coverage Visualization

### What We Know (Tested Dimensions)

```
                    ┌─────────────────────────────────────────────┐
                    │         TESTED DIMENSIONS (9/9)             │
                    ├─────────────────────────────────────────────┤
                    │ Temporal       ████████████████████  DONE   │
                    │ Home/Away      ████████████████████  DONE   │
                    │ Staleness      ████████████████████  DONE   │
                    │ Position       ████████████████████  DONE   │
                    │ 3-Way Combos   ████████████████████  DONE   │
                    │ Rest/B2B       ████████████████████  DONE   │
                    │ Team Strength  ████████████████████  DONE   │
                    │ OVER/UNDER     ████████████████████  DONE   │
                    │ Conference     ████████████████████  DONE   │
                    └─────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────┐
                    │      UNTESTED DIMENSIONS (17 identified)    │
                    ├─────────────────────────────────────────────┤
  Tier A (High):    │ Line Size      ░░░░░░░░░░░░░░░░░░░░        │
                    │ Edge Magnitude ░░░░░░░░░░░░░░░░░░░░        │
                    │ Player Recurr. ░░░░░░░░░░░░░░░░░░░░        │
                    │ Opp Defense    ░░░░░░░░░░░░░░░░░░░░        │
                    │ Game Total     ░░░░░░░░░░░░░░░░░░░░        │
                    ├─────────────────────────────────────────────┤
  Tier B (Med):     │ Day of Week    ░░░░░░░░░░░░░░░░░░░░        │
                    │ Slate Size     ░░░░░░░░░░░░░░░░░░░░        │
                    │ Monthly        ░░░░░░░░░░░░░░░░░░░░        │
                    │ Line Movement  ░░░░░░░░░░░░░░░░░░░░        │
                    │ Actual Minutes ░░░░░░░░░░░░░░░░░░░░        │
                    │ Model Confid.  ░░░░░░░░░░░░░░░░░░░░        │
                    ├─────────────────────────────────────────────┤
  Tier C (Low):     │ 4-Way Combos   ░░░░░░░░░░░░░░░░░░░░        │
                    │ Team Streak    ░░░░░░░░░░░░░░░░░░░░        │
                    │ Player Streak  ░░░░░░░░░░░░░░░░░░░░        │
                    │ Time of Day    ░░░░░░░░░░░░░░░░░░░░        │
                    │ Injury Context ░░░░░░░░░░░░░░░░░░░░        │
                    │ Line Source    ░░░░░░░░░░░░░░░░░░░░        │
                    └─────────────────────────────────────────────┘
```

### Per-Signal Coverage

| Signal | Temporal | H/A | Stale | Position | 3-Way | Rest | Team | O/U | Conf | Line Size | Edge Mag | Opp Def |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 3way_combo | Y | Y | Y | Y | Y | Y | Y | Y | - | - | - | - |
| HE+MS | Y | Y | Y | Y | Y | Y | Y | Y | Y | - | - | - |
| HE+PV | Y | Y | Y | Y | Y | Y | Y | Y | Y | - | - | - |
| cold_snap | Y | Y | Y | Y | - | Y | Y | Y | Y | - | - | - |
| 3pt_bounce | Y | Y | Y | Y | Y | Y | Y | Y | - | - | - | - |
| blowout_recovery | Y | Y | Y | Y | Y | Y | Y | Y | Y | - | - | - |

**Y** = Tested | **-** = Not tested

---

## Recommended Testing Plan for Tomorrow

### Quick Wins (30 min each, run in parallel — 5 agents)

**Agent 1: Line Size Buckets**
```sql
-- Test HE+MS and 3way_combo across line sizes
-- Buckets: <15, 15-20, 20-25, 25+
-- Join player_prop_predictions.current_points_line
```

**Agent 2: Edge Magnitude Buckets**
```sql
-- Test all combos across edge sizes
-- Buckets: 3-5, 5-7, 7-10, 10+
-- Use predicted_points - current_points_line
```

**Agent 3: Day of Week**
```sql
-- Test combos on weekday vs weekend
-- EXTRACT(DAYOFWEEK FROM game_date)
-- 1=Sun, 7=Sat → Weekend = 1,6,7
```

**Agent 4: Slate Size**
```sql
-- Count games per date, bucket into small/medium/large
-- Test if combos work differently on big vs small slates
```

**Agent 5: Monthly Breakdown**
```sql
-- FORMAT_DATE('%Y-%m', game_date) as month
-- See exact month each combo turns on/off
-- More granular than W1-W4 temporal windows
```

### Medium Effort (1 hour each — 3 agents)

**Agent 6: Player Recurrence**
```sql
-- For each combo, count how many times each player appears
-- Bucket: 1st time, 2nd time, 3rd+ time
-- Are combos better on fresh players or recurring picks?
```

**Agent 7: Opponent Defensive Rating**
```sql
-- Compute team defensive rating (points allowed per game)
-- Bucket into top 10, middle 10, bottom 10
-- Test combos against each bucket
```

**Agent 8: Line Source Split**
```sql
-- Split by line_source: ACTUAL_PROP vs ODDS_API vs BETTINGPROS
-- Different sources may have different accuracy
```

### Estimated Total: ~3-4 hours with parallelization

---

## Questions for the Human

Before running tomorrow's tests, consider:

1. **Are there any betting-specific angles you care about?** (e.g., specific sportsbook, bet size optimization, parlay vs straight bets)
2. **Is there external data we could join?** (e.g., social media sentiment, weather for outdoor... wait, NBA is indoor)
3. **Should we test signal COMBINATIONS with the new filters?** (e.g., cold_snap HOME + top team + extra rest — stacking multiple filters)
4. **Any signals from your own experience that we haven't quantified?** (e.g., "I always do well betting on guards on Fridays" — we can test that)
5. **Should we test the anti-patterns more deeply?** (e.g., are there conditions where HE+ES 2-way actually works? Maybe fresh model + away + OVER?)
