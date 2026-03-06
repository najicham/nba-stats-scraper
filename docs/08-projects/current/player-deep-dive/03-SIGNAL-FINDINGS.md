# Player Profile Signal Findings

*Session 417, March 5 2026*

## Overview

While player-specific over/under rates don't persist across seasons (r=0.14), we found that **structural properties of player scoring distributions interact with our model predictions in exploitable ways.** These are not player-specific directional biases — they're about how scoring shape, momentum, and variance affect prediction reliability.

---

## Finding 1: Bounce-Back OVER Signal

**The strongest finding.** When a player badly misses their line and our model predicts OVER next game, we hit at 60%+.

### Raw Data

| Scenario | HR | N | vs Baseline |
|----------|-----|------|------------|
| After bad miss (<70% of line) + model OVER + edge 3+ | **61.8%** | 178 | +3.2pp |
| After bad miss + model OVER + any edge | **59.8-61.8%** | 696 | +5-7pp |
| After bad miss + model UNDER + edge 3+ | **45.2%** | 334 | **-8.9pp** |
| Normal + model OVER + edge 3+ | 58.6% | 616 | baseline |
| Normal + model UNDER + edge 3+ | 54.1% | 1233 | baseline |

### Key Insights
- OVER after bad miss = strong positive signal (+5-7pp)
- UNDER after bad miss = **anti-signal** (-8.9pp vs normal UNDER). These are LOSING bets.
- The bounce-back overwhelms UNDER signals — should suppress UNDER picks after bad misses
- N=700 for OVER, N=334 for UNDER — excellent sample sizes

### Proposed Signal: `bounce_back_over`
- **Type:** Active signal (positive) + negative filter (suppress UNDER)
- **Trigger:** Player scored <70% of their prop line in previous game
- **Action:** Boost OVER confidence; suppress/block UNDER picks
- **Rescue eligible:** Yes (60%+ HR)

---

## Finding 2: Scoring Shape x Direction

Player scoring distribution shape predicts which direction works better.

| Scoring Shape | OVER HR | UNDER HR | N (OVER) | N (UNDER) | Insight |
|--------------|---------|----------|----------|-----------|---------|
| Left-skewed (dud-prone, mean < median) | **45.3%** | 55.1% | 172 | 374 | OVER is toxic |
| Right-skewed (explosion-prone, mean > median) | 51.7% | **56.4%** | 2,875 | 5,731 | UNDER preferred |
| Symmetric (predictable) | **54.8%** | 53.4% | 6,936 | 12,854 | OVER slightly better |

### Key Insights
- Left-skewed players going OVER = 45.3%. Actively harmful to portfolio.
- Symmetric players = OVER is our better direction (54.8% vs 53.4%)
- Right-skewed = UNDER is better (56.4%). These players occasionally explode but usually underperform.
- Skew is computed as (mean - median): positive = right-skew, negative = left-skew

### Proposed Signal: Scoring shape modifier
- Compute rolling 30-game skewness per player
- Left-skew: suppress OVER, boost UNDER confidence
- Symmetric: slight OVER boost
- Could be a signal modifier rather than standalone signal

---

## Finding 3: Volatile Players + High Edge = Gold

Counter-intuitive: our high-edge predictions on volatile players are MORE reliable.

| Player Type | Low Edge (<3) HR | Med Edge (3-5) HR | High Edge (5+) HR | N (5+) |
|-------------|-----------------|-------------------|-------------------|--------|
| Consistent (CoV < 0.35) | 52.4% | 59.2% | 56.1% | 1,032 |
| Volatile (CoV > 0.35) | 51.8% | 57.0% | **61.9%** | 3,005 |

### Key Insights
- At high edge, volatile > consistent by **5.8pp**
- Volatile players' natural variance helps — when the model spots a big gap, their tendency to have extreme outcomes lands them where predicted
- Consistent players at high edge: the model sees a gap, but the player's consistency limits how far they actually deviate
- At low edge, both are ~52% (no difference)

### Proposed: Confidence boost for volatile + high edge
- When CoV > 0.35 AND edge >= 5: boost confidence score
- These 3,005 predictions at 61.9% are among our most accurate

---

## Finding 4: Consecutive Misses Compound

The bounce-back effect intensifies with consecutive bad games.

| Previous Context | Over Rate | vs Normal | N |
|-----------------|-----------|-----------|---|
| 2 consecutive bad misses (<80% of line) | 52.6% | **+2.5pp** | 268 |
| 1 bad miss | 51.4% | +1.3pp | 589 |
| Normal | 50.1% | baseline | 976 |
| 1 big hit (>120% of line) | 47.3% | -2.8pp | 584 |
| 2 consecutive big hits | 48.5% | -1.6pp | 291 |

### Key Insights
- Bounce-back is cumulative — 2 misses = stronger bounce than 1
- After hot streaks: players trend UNDER (47.3% over rate)
- The symmetric effect (hot → UNDER) is slightly weaker than (bad → OVER)

### Proposed Signal: `hot_streak_under`
- **Trigger:** Player exceeded line by 20%+ in last 2 consecutive games
- **Action:** Boost UNDER confidence
- Works as mirror image of bounce-back signal

---

## Finding 5: Player Consistency Tiers

Scoring consistency (CoV) is stable across seasons (r=0.64) and modestly predicts model accuracy.

| Consistency Tier | Avg CoV | Model HR | Players | Avg Preds |
|-----------------|---------|----------|---------|-----------|
| Very consistent | 0.276 | 56.6% | 14 | 121 |
| Consistent | 0.353 | 55.4% | 58 | 111 |
| Moderate | 0.454 | 54.1% | 84 | 104 |
| Volatile | 0.590 | 53.3% | 134 | 83 |

### Key Insights
- 3.3pp spread between most and least consistent
- But volatile + high edge flips this (Finding 3)
- Consistency is the ONE player trait stable across seasons

### Examples
- **Very consistent:** Kevin Durant (0.262), Kawhi Leonard (0.270)
- **Volatile:** Cason Wallace (0.690), Brice Sensabaugh (0.673)
- **Curry:** ~0.38 (moderate-volatile)

---

## Strongest Bounce-Back Players (Season 2025-26)

Players with the strongest structural bounce-back after bad games:

| Player | Avg Pts | After Bad Game | Bounce Delta | N |
|--------|---------|---------------|-------------|---|
| Stephen Curry | 27.3 | 33.0 | **+5.7** | 7 |
| PJ Washington | 14.4 | 20.0 | **+5.6** | 6 |
| Jamal Murray | 25.9 | 31.1 | **+5.3** | 7 |
| Andrew Nembhard | 17.2 | 22.2 | **+5.1** | 9 |
| Payton Pritchard | 17.5 | 21.5 | **+3.9** | 15 |
| KAT | 19.6 | 23.6 | **+3.9** | 9 |

---

## Implementation Priority

| Signal | HR | N | Effort | Priority |
|--------|-----|------|--------|----------|
| `bounce_back_over` | 60-62% | 700 | LOW | **P0 — implement first** |
| UNDER suppression after bad miss | 45.2% (anti) | 334 | LOW | **P0 — implement with bounce-back** |
| `hot_streak_under` | ~53-55% | 584 | LOW | P1 |
| Scoring shape modifier | varies | 20K+ | MEDIUM | P1 |
| Volatile + high edge boost | 61.9% | 3,005 | LOW | P1 |
| Player consistency tier | 56.6% top | 290 | MEDIUM | P2 |

---

## Finding 6: Bounce-Back is an AWAY Phenomenon (Agent Research)

The strongest interaction found across all research. The bounce-back completely disappears at home.

| Context | Over % | N | vs Baseline |
|---------|--------|---|-------------|
| Bad miss + **AWAY** | **56.2%** | 379 | **+6.1pp** |
| Bad miss + HOME | 47.8% | 360 | -0.5pp |
| Normal + AWAY | 50.1% | 1,194 | baseline |
| Normal + HOME | 48.3% | 1,098 | baseline |

**Why:** The market over-corrects the line downward for road games after a bad miss. At home, the adjustment is well-calibrated.

### Proposed: Enhance bounce_back_over to require AWAY
- OVER after bad miss + AWAY = 56.2% over rate, boosted further by model OVER confirmation
- SUPPRESS bounce-back logic at HOME (it doesn't work)

---

## Finding 7: Over-Streak Reversion is Progressive (Agent Research)

Over-streaks produce stronger and stronger UNDER lean the longer they go.

| Streak | Over % Next Game | N |
|--------|-----------------|---|
| 3 overs in last 5 | 55.1% | 706 |
| 4-5 overs in last 5 | **44.0%** | 366 |
| 3+ consecutive overs | **46.8%** | 297 |

**At 4+ overs in last 5 games, the UNDER rate is 56%.** N=366.

Counterpart: 4-5 unders in last 5 does NOT produce a bounce (46.5% over). Under-streaks persist — the bounce-back only works game-to-game, not at 5-game scale.

### Proposed Signal: `over_streak_reversion_under`
- **Trigger:** 4+ overs in last 5 games (or 3+ consecutive overs)
- **Action:** Boost UNDER confidence
- **HR:** ~53-56% UNDER at these streaks

---

## Finding 8: Model Has a Blind Spot on Streak Players (Agent Research)

After 3 consecutive unders, our model calls UNDER 2.4x more than OVER (515 vs 219). But those UNDER calls are terrible.

| Streak Context | Model Direction | N | HR |
|---------------|----------------|---|-----|
| 3 consecutive unders | OVER | 219 | **58.9%** |
| 3 consecutive unders | UNDER | 515 | **44.7%** |
| Normal | OVER | 2,645 | 54.9% |
| Normal | UNDER | 4,871 | 53.2% |

The model sees a player trending down and predicts more UNDER — but the bounce-back makes those UNDER calls lose money. **This is a clear model weakness that a filter can fix.**

### Proposed: Negative filter `under_after_streak`
- **Trigger:** 3+ consecutive unders AND model recommends UNDER
- **Action:** Block/suppress the UNDER pick (44.7% HR = losing)
- **Impact:** Would suppress ~515 bad UNDER picks per season

---

## Finding 9: Bad Shooting Bounces Harder Than Low Minutes (Agent Research)

Not all bad games are equal. Shooting slumps bounce back harder than blowout-minutes games.

| Bad Game Reason | Next Game Over % | N | Bounce |
|----------------|-----------------|---|--------|
| **Bad shooting (FG% < 35%)** | **54.5%** | 220 | **+5.3pp** |
| Low minutes (pulled/blowout) | 52.1% | 403 | +2.9pp |
| Bad miss other | 47.8% | 115 | -1.4pp |

**Shooting is noisy and reverts strongly. Minutes-based misses are partially structural (blowout = may happen again).**

Also: Minutes CV correlates with scoring CV at r=0.693 — players with unstable minutes have the most volatile scoring.

---

## Finding 10: Star vs Starter vs Role Player Tier Effects (Agent Research)

Different tiers have fundamentally different optimal strategies.

### Model Accuracy by Tier

| Tier | Best Strategy | HR | N |
|------|--------------|-----|---|
| Star | UNDER + edge 3+ | 59.2% | 1,022 |
| **Starter** | **OVER + edge 3+** | **61.1%** | **1,050** |
| Role Player | UNDER + edge 3+ | 60.0% | 4,041 |

- **Stars are overpriced** — UNDER is the play (59.2% at edge 3+). Star OVER is flat at 56% regardless of edge.
- **Starters are the OVER sweet spot** — 61.1% HR at edge 3+ (N=1,050), strongest bounce-back (+6.0pp)
- **Role players dominate UNDER** — 60.0% at edge 3+ with the largest volume (4,041)

### Scoring Shape by Tier

| Tier | Players | Avg CoV | Right-Skewed | Symmetric |
|------|---------|---------|-------------|-----------|
| Star | 28 | 0.312 | 21% | 68% |
| Starter | 78 | 0.404 | 21% | 78% |
| Role Player | 276 | 0.572 | 41% | 59% |

Stars are mostly symmetric (predictable). Role players are heavily right-skewed (occasional explosion games inflate their averages, creating natural UNDER lean).

---

## Revised Implementation Priority

| Signal | HR | N | Key Detail | Priority |
|--------|-----|------|-----------|----------|
| `bounce_back_over` (AWAY only) | 56.2% raw, 60%+ with model | 379-700 | HOME bounce doesn't work | **P0** |
| `under_after_streak` (negative filter) | 44.7% (anti) | 515 | Model blind spot — block these | **P0** |
| `over_streak_reversion_under` | ~56% UNDER | 366 | 4+ overs in last 5 | **P1** |
| `bad_shooting_bounce_over` | 54.5% | 220 | FG% < 35% last game | **P1** |
| Tier-based direction preference | 59-61% | 1K-4K | Star=UNDER, Starter=OVER, Role=UNDER | **P1** |
| Scoring shape modifier | varies | 20K+ | Skew x direction interaction | **P2** |
| Volatile + high edge boost | 61.9% | 3,005 | CoV > 0.35 + edge 5+ | **P2** |
| Player variance tier | 56.6% top | 290 | Ultra bets + confidence calibration | **P2** |

---

## Deep Dive Coverage Decision

### Run for ALL players with 50+ graded predictions (262 players)
- The tool is automated and fast (~30s per player)
- Role players show the strongest patterns (right-skew, high variance, UNDER lean)
- Starters show the best OVER opportunities
- Stars have different dynamics but still valuable

### Batch run approach
```bash
# Generate player list from BQ, run deep dives for all
bq query --format=csv "SELECT player_lookup FROM (
  SELECT player_lookup, COUNT(*) as n
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= '2025-10-01' AND has_prop_line = TRUE AND prediction_correct IS NOT NULL
  GROUP BY 1 HAVING COUNT(*) >= 50
) ORDER BY n DESC" | tail -n +2 | while read player; do
  python bin/analysis/player_deep_dive.py "$player" --output "results/player_profiles/${player}.md"
done
```

### Monthly refresh
- Re-run all deep dives monthly (1st of month)
- Player profiles change within a season — 30-game rolling window captures this
- Store in `results/player_profiles/` for reference

---

## Next Steps

1. Implement P0 signals: `bounce_back_over` (away-only) + `under_after_streak` filter
2. Implement P1 signals: `over_streak_reversion_under`, `bad_shooting_bounce_over`, tier preferences
3. Build player profile computation infrastructure (CoV, skewness, streak tracking)
4. Run batch deep dives for all 262 players
5. Validate signals on held-out data before promoting to production
