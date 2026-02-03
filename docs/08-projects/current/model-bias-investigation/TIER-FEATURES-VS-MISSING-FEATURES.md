# Model Bias: Tier Features vs Missing Features

**Date:** 2026-02-03
**Status:** Analysis document for review
**Context:** CatBoost V9 has -9.3 point bias on stars, +5.6 on bench

---

## The Question

Should we fix the regression-to-mean bias by:
- **Option A:** Adding explicit tier features (`is_star`, `player_volume_tier`)
- **Option B:** Finding and adding the missing features that would naturally capture this

This document explores both approaches critically.

---

## Current State

### The Bias
```
Tier            | Bias     | Model Behavior
----------------|----------|----------------
Stars (25+)     | -9.3 pts | Predicts 28 when actual is 37
Starters (15-24)| -2.1 pts | Slight underestimate
Role (5-14)     | +1.5 pts | Slight overestimate
Bench (<5)      | +5.6 pts | Predicts 8 when actual is 2
```

### Current Features (37 total)
The model already has signals about player scoring level:
- `points_avg_last_5` (index 0)
- `points_avg_last_10` (index 1)
- `points_avg_season` (index 2)
- `vegas_points_line` (index 25)

**Question:** If the model has these, why does it still regress to the mean?

---

## Option A: Add Tier Features

### Proposed Features
```python
'player_volume_tier',    # Categorical: 0=bench, 1=role, 2=starter, 3=star
'is_high_volume_scorer', # Binary: season_avg >= 20
```

### Arguments For
1. CatBoost handles categoricals well - can learn tier-specific interactions
2. Quick to implement (derive from existing `points_avg_season`)
3. Explicit signal that says "treat this player differently"
4. Allows model to learn "stars on back-to-backs behave differently than role players"

### Arguments Against
1. **Circular logic**: Tier is derived from `points_avg_season` which model already has
2. **Doesn't explain variance**: Knowing someone is a "star" doesn't explain why they score 40 one night and 25 another
3. **Same as calibration**: Essentially telling model "adjust by tier" - which is what post-prediction calibration does
4. **Masks the real problem**: We should understand WHY the model regresses, not just patch it

### Verdict: Band-aid
Tier features are a **useful band-aid** but don't address root cause. They're equivalent to building calibration INTO the model rather than applying it after.

---

## Option B: Find Missing Features

### The Real Question
What information would help the model predict that LeBron scores 38 tonight vs his 28 average?

### Currently Missing Features

| Feature | Why It Matters | Data Source |
|---------|----------------|-------------|
| **Usage rate** | Stars have 30%+ usage - more opportunities | player_game_summary? |
| **Shot attempts (FGA)** | Volume of shots, not just made | player_game_summary |
| **Free throw attempts** | Stars get to line more, low variance points | player_game_summary |
| **Teammate availability** | When #2 option is out, star's usage spikes | Would need roster/injury data |
| **Game total (O/U)** | High totals = more scoring opportunities | odds_api (we have this) |
| **Spread/game script** | Close games = more star minutes | odds_api (we have this) |
| **Minutes projection** | Stars in blowouts get benched | Derived from spread? |
| **Historical max (L20)** | Captures upside/ceiling potential | player_game_summary |
| **Scoring consistency** | Std dev - some players have high variance | We have `points_std_last_10` |

### The Mechanism
Stars score more because:
1. They **get more opportunities** (usage, shot attempts)
2. They **play more minutes** (especially in close games)
3. They **get to the free throw line** more
4. Their **teammates defer** to them

Our model knows the OUTCOME (averages 28) but not the MECHANISM (high usage, more minutes, more FTA).

---

## Session 103 Insight: Vegas Line Bias

Another chat discovered something important about Vegas lines:

### Vegas Coverage by Tier
```
Tier    | Vegas Coverage | Implication
--------|----------------|-------------
Star    | ~95%           | Almost all have lines
Starter | ~90%           | Most have lines
Role    | ~40%           | Less than half
Bench   | ~15%           | Rarely have lines
```

### Vegas Lines Are Themselves Biased
```
Tier    | Avg Vegas Line | Avg Actual | Vegas Bias
--------|----------------|------------|------------
Star    | ~26            | ~32        | -6 (under)
Starter | ~18            | ~19        | -1 (slight under)
Role    | ~11            | ~9         | +2 (over)
Bench   | ~7             | ~3         | +4 (over)
```

### Why This Matters
1. **Sportsbooks are conservative** - they under-predict stars intentionally
2. **Our model learns from Vegas** - `vegas_points_line` is a strong feature
3. **Model inherits Vegas bias** - if Vegas says 26 and we trust Vegas, we predict ~27
4. **Missing Vegas = missing signal** - bench players without lines have no Vegas signal

**Key insight:** The model might be learning "follow Vegas closely" which inherits sportsbook bias.

---

## Deeper Analysis Needed

### Question 1: How much does the model rely on Vegas?

```sql
-- Check feature importance or correlation
-- If vegas_points_line has >30% importance, model is Vegas-following
```

We should examine:
- Feature importance of `vegas_points_line` in current model
- What happens when we remove Vegas features entirely?
- Does bias persist without Vegas?

### Question 2: What predicts deviation from average?

For star players who scored 10+ above their average:
- What was different about that game?
- Opponent? Teammate injuries? Game script?

```sql
-- Find star games with big over-performance
SELECT
  pgs.player_lookup,
  pgs.game_date,
  pgs.points,
  pdc.points_avg_season,
  pgs.points - pdc.points_avg_season as over_avg,
  -- What was different?
  pgs.minutes_played,
  pgs.fga,
  pgs.usage_pct,
  -- Opponent?
  pgs.opponent_team_abbr
FROM nba_analytics.player_game_summary pgs
JOIN nba_precompute.player_daily_cache pdc
  ON pgs.player_lookup = pdc.player_lookup AND pgs.game_date = pdc.cache_date
WHERE pdc.points_avg_season >= 25  -- Stars
  AND pgs.points >= pdc.points_avg_season + 10  -- Big over-performance
  AND pgs.game_date >= '2025-11-01'
ORDER BY over_avg DESC
LIMIT 50
```

### Question 3: Is the problem in training or inference?

- **Training data bias**: Model trained on data where Vegas exists = trained on stars
- **Inference issue**: Model works fine on stars (follows Vegas) but fails on others

---

## Proposed Investigation Path

### Phase 1: Understand the Current Model
1. Extract feature importance from CatBoost V9
2. Calculate correlation between `vegas_points_line` and predictions
3. Segment accuracy by "has Vegas line" vs "no Vegas line"

### Phase 2: Analyze What Drives Variance
1. For stars, what predicts over/under-performance vs average?
2. Are there patterns in the data we're not capturing?
3. Query games where stars scored 10+ above average - what's common?

### Phase 3: Feature Audit
1. List ALL available columns in player_game_summary
2. Identify which could explain variance: usage_pct, fga, fta, minutes
3. Check data availability and quality

### Phase 4: Experiment Design
Based on findings:
- If Vegas-following: Try model without Vegas features, or with Vegas-deviation feature
- If missing volume features: Add usage_rate, fga_avg
- If training data bias: Rebalance or weight by tier
- If fundamental: Consider tier-specific models

---

## Recommendation

**Don't rush to add tier features.**

The tier feature is a shortcut that says "adjust predictions by player class" without understanding why. It's the same as calibration, just implemented inside the model.

**Instead, investigate:**
1. How much is the model following Vegas? (Feature importance)
2. What actually predicts variance from average? (Analysis)
3. What features do we have that we're not using? (Audit)

**Then decide:**
- If the problem is Vegas-following → change how we use Vegas features
- If the problem is missing volume features → add usage_rate, fga
- If the problem is fundamental → then consider tier features or separate models

---

## Questions for Reviewer

1. Do we have `usage_pct` in player_game_summary? Is it populated?

2. Can we extract feature importance from the current CatBoost V9 model file?

3. Should we run the "big over-performance" query to see what drives variance?

4. Is there a concern that adding more features increases overfitting risk?

5. The Session 103 insight about Vegas coverage by tier is important - should we investigate training data composition (what % of training samples are stars with Vegas lines)?

---

## Related Documents

- `docs/09-handoff/2026-02-03-SESSION-104-MODEL-QUALITY-HANDOFF.md` - Session 104 fixes
- `docs/08-projects/current/feature-mismatch-investigation/MODEL-BIAS-INVESTIGATION.md` - Session 101 analysis
- `.claude/skills/spot-check-features/SKILL.md` - Vegas coverage queries (Session 103)

---

**End of Document**
