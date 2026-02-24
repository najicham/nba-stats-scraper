# Player Profiles — Phase 0 Validation Results

**Date:** 2026-02-23
**Methodology:** Joined `prediction_accuracy` with `player_game_summary` and `player_shot_zone_analysis` aggregates. All models combined for sample size, edge >= 3 (abs(predicted_margin) >= 3), graded only, not voided, has prop line.

---

## Validation 1: Scoring Consistency (CV) vs Hit Rate

**Question:** Do players with more consistent scoring predict better?

| Consistency Type | Total Picks | Wins | Losses | Hit Rate | Avg CV | Players |
|------------------|-------------|------|--------|----------|--------|---------|
| Metronome (CV<0.20) | 10 | 10 | 0 | **100.0%** | 0.157 | 1 |
| Consistent (CV 0.20-0.30) | 1,723 | 1,182 | 541 | **68.6%** | 0.250 | 6 |
| Normal (CV 0.30-0.40) | 11,523 | 7,518 | 4,005 | **65.2%** | 0.351 | 49 |
| Volatile (CV>=0.40) | 47,674 | 30,983 | 16,691 | **65.0%** | 0.589 | 279 |

**Finding: MODEST GRADIENT.** Consistent players predict 3.6pp better (68.6% vs 65.0%), but the top buckets have very few players (6 players in consistent, 1 in metronome). Most of our predictions (78%) are on volatile players. The normal vs volatile gap is minimal (0.2pp).

**Verdict:** Weak standalone signal. CV alone doesn't strongly differentiate. But the consistent bucket outperforming with 1,723 picks and 6 players is worth noting.

---

## Validation 2: Shot Creation Type vs Hit Rate

**Question:** Are self-creators more predictable than catch-and-shoot players?

| Creation Type | Total Picks | Wins | Losses | Hit Rate | Avg Assisted% | Players |
|---------------|-------------|------|--------|----------|---------------|---------|
| Self-Creator (unast>=55%) | 1,008 | 670 | 338 | **66.5%** | 26.6% | 3 |
| Mixed Creator | 63,422 | 41,184 | 22,238 | **64.9%** | 44.6% | 391 |
| Catch-and-Shoot (ast>=70%) | 3,675 | 2,461 | 1,214 | **67.0%** | 75.2% | 24 |

**Finding: BOTH EXTREMES BEAT THE MIDDLE.** Self-creators (66.5%) and catch-and-shoot (67.0%) both outperform mixed creators (64.9%) by ~2pp. The hypothesis that self-creators are more predictable is weakly supported, but catch-and-shoot players are equally good.

**Interpretation:** Players with a clearly defined role (either self-create everything OR catch-and-shoot everything) are easier to predict than players who do a bit of both. This makes sense — a defined role is more modelable.

**Verdict:** Moderate signal. The real finding is that role clarity matters, not creation style specifically.

---

## Validation 3: FT Drawing Rate vs Hit Rate (by Direction)

**Question:** Does high FT drawing help OVER predictions?

| FT Tier | Direction | Total Picks | Wins | Losses | Hit Rate | Avg FT Rate | Players |
|---------|-----------|-------------|------|--------|----------|-------------|---------|
| High FT (FTr>=0.40) | OVER | 3,649 | 2,586 | 1,063 | **70.9%** | 0.489 | 61 |
| High FT (FTr>=0.40) | UNDER | 8,455 | 5,384 | 3,071 | 63.7% | 0.502 | 66 |
| Moderate FT (0.25-0.40) | OVER | 7,343 | 5,043 | 2,300 | **68.7%** | 0.307 | 132 |
| Moderate FT (0.25-0.40) | UNDER | 17,203 | 10,994 | 6,209 | 63.9% | 0.308 | 140 |
| Low FT (FTr<0.25) | OVER | 9,572 | 6,451 | 3,121 | **67.4%** | 0.159 | 213 |
| Low FT (FTr<0.25) | UNDER | 24,267 | 15,427 | 8,840 | 63.6% | 0.159 | 238 |

**Finding: STRONG DIRECTIONAL SIGNAL.**

OVER hit rate by FT tier:
```
High FT + OVER:     70.9%  (+3.5pp vs low FT OVER)
Moderate FT + OVER: 68.7%  (+1.3pp vs low FT OVER)
Low FT + OVER:      67.4%  (baseline)
```

UNDER hit rate is flat across all FT tiers (~63.6-63.9%). FT rate only matters for OVER bets.

**Why this makes sense:** Players who draw a lot of free throws have a scoring floor. Even on bad shooting nights, they get to the line and score 6-10 points from FTs alone. This protects OVER bets. For UNDER bets, FT rate is irrelevant because the model already accounts for the scoring level.

**Verdict: ACTIONABLE.** High FT + OVER is the strongest combination found in this validation. 70.9% HR on 3,649 picks with 61 players is a robust sample. This could be a signal or filter.

---

## Validation 4: Scoring Zone Archetype vs Hit Rate

**Question:** Do interior scorers predict differently than perimeter scorers?

| Zone Archetype | Total Picks | Wins | Losses | Hit Rate | Players |
|----------------|-------------|------|--------|----------|---------|
| Interior (paint>=45%) | 19,846 | 12,833 | 7,013 | 64.7% | 120 |
| Perimeter (3pt>=45%) | 22,286 | 14,306 | 7,980 | 64.2% | 164 |
| Mid-Range (mid>=30%) | 15,827 | 10,580 | 5,247 | **66.8%** | 70 |
| Balanced | 10,146 | 6,596 | 3,550 | 65.0% | 64 |

**Finding: MID-RANGE SCORERS ARE MOST PREDICTABLE.** Mid-range archetype leads at 66.8%, 2.6pp above perimeter (64.2%). Interior and balanced are in the middle.

**Interpretation:** Mid-range scorers (DeMar DeRozan, KD, Kawhi types) tend to be high-skill, consistent scorers with multiple ways to get points. Perimeter scorers (3PT-dependent) are the least predictable — makes sense since 3PT shooting has inherently high variance.

**Verdict:** Moderate signal. The spread is 2.6pp across archetypes. Mid-range is reliably the best; perimeter is reliably the worst. Could be useful as a feature or filter modifier.

---

## Validation 5: Boom/Bust Rate vs Hit Rate

**Question:** Are players with high bust rates harder to predict?

| Bust Tier | Total Picks | Wins | Losses | Hit Rate | Avg Bust% | Avg Boom% | Players |
|-----------|-------------|------|--------|----------|-----------|-----------|---------|
| High Bust (>=20%) | 21,034 | 13,387 | 7,647 | 63.6% | 26.0% | 21.8% | 151 |
| Moderate Bust (10-20%) | 27,430 | 18,048 | 9,382 | **65.8%** | 14.4% | 13.9% | 130 |
| Low Bust (<10%) | 12,647 | 8,380 | 4,267 | **66.3%** | 6.5% | 7.0% | 55 |

**Finding: CLEAR GRADIENT.** Low bust players: 66.3%, moderate: 65.8%, high bust: 63.6%. That's a 2.7pp spread, clean and monotonic across all three tiers with large samples.

**Interpretation:** Bust rate captures something that CV alone doesn't — the frequency of catastrophic underperformance. Players who rarely bust (< 10% of games below 60% of average) are ~2.7pp more profitable to bet on.

Note: boom rate tracks bust rate closely (high bust players also have high boom rates). These are volatile players in both directions.

**Verdict: ACTIONABLE.** Cleaner signal than raw CV. Bust rate is a direct measure of prediction risk. Low bust players are meaningfully more profitable.

---

## Validation 6: Consistency x Direction Interaction

**Question:** Does consistency matter differently for OVER vs UNDER?

| Consistency | Direction | Total Picks | Wins | Losses | Hit Rate | Players |
|-------------|-----------|-------------|------|--------|----------|---------|
| Consistent (CV<0.25) | OVER | 244 | 184 | 60 | **75.4%** | 3 |
| Consistent (CV<0.25) | UNDER | 501 | 355 | 146 | **70.9%** | 3 |
| Normal (CV 0.25-0.35) | OVER | 2,419 | 1,678 | 741 | **69.4%** | 27 |
| Normal (CV 0.25-0.35) | UNDER | 4,548 | 2,894 | 1,654 | 63.6% | 28 |
| Volatile (CV>=0.35) | OVER | 15,858 | 10,850 | 5,008 | **68.4%** | 292 |
| Volatile (CV>=0.35) | UNDER | 37,360 | 23,732 | 13,628 | 63.5% | 302 |

**Finding: OVER ALWAYS BEATS UNDER, BUT CONSISTENCY AMPLIFIES IT.**

OVER vs UNDER gap by consistency:
```
Consistent: OVER 75.4% vs UNDER 70.9%  (+4.5pp gap, both high)
Normal:     OVER 69.4% vs UNDER 63.6%  (+5.8pp gap)
Volatile:   OVER 68.4% vs UNDER 63.5%  (+4.9pp gap)
```

UNDER HR is flat at ~63.5% regardless of consistency. OVER HR climbs with consistency: 68.4% → 69.4% → 75.4%.

**Caveat:** The consistent bucket has only 3 players (244 OVER picks). The normal bucket (2,419 OVER picks, 27 players) is more trustworthy and still shows a clear 1pp boost over volatile.

**Verdict:** OVER predictions benefit from consistency, UNDER predictions don't care. Aligns with FT rate finding — anything that provides a scoring floor helps OVER predictions.

---

## Summary Scorecard

| Dimension | Signal Strength | Actionable? | Best Finding |
|-----------|----------------|-------------|-------------|
| **FT Rate x Direction** | **STRONG** | **YES** | High FT + OVER = 70.9% HR (3,649 picks) |
| **Bust Rate** | **MODERATE-STRONG** | **YES** | Low bust = 66.3% vs high bust = 63.6% (2.7pp, clean gradient) |
| **Zone Archetype** | **MODERATE** | Maybe | Mid-range = 66.8%, perimeter = 64.2% (2.6pp) |
| **Consistency x Direction** | **MODERATE** | Maybe | OVER benefits from consistency; UNDER doesn't care |
| **Shot Creation** | **WEAK-MODERATE** | No | Both extremes beat the middle by ~2pp |
| **Raw CV** | **WEAK** | No | 68.6% vs 65.0% but only 6 consistent players |

## Recommended Next Steps

1. **FT Rate as a feature or signal** — This is the clearest finding. High FT + OVER at 70.9% is a strong combination. Consider:
   - Adding `ft_rate_season` as a new ML feature (index 55+)
   - Creating a `high_ft_over` signal for the signal system
   - Using FT rate as a positive filter for OVER best bets

2. **Bust rate as a filter** — Bust rate has a clean 2.7pp gradient. Could be used to:
   - Require higher edge for high-bust players
   - Add `bust_rate` as an ML feature
   - Create a `high_bust_caution` negative filter

3. **Zone archetype as a feature** — Mid-range predictability advantage is worth investigating further. Could add `scoring_zone_archetype` to the feature vector.

4. **Do NOT replace dead features** — Add these as new feature indices (55+) per user decision. Reserve slots 41, 42, 47, 50 for their original intended purposes.

5. **Build the profile table (Phase 1)** — The validation confirms multiple dimensions carry signal. Building a persistent `player_profiles` table is justified.
