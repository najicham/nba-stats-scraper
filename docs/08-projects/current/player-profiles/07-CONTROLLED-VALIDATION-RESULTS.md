# Player Profiles — Controlled Validation Results

**Date:** 2026-02-23
**Purpose:** Test whether Phase 0 findings survive when controlling for prop line tier (player quality proxy) and edge magnitude, as recommended by independent review.

---

## Controlled Test 1: FT Rate x Direction x Line Tier

### OVER Predictions

| Line Tier | FT Tier | Picks | Wins | Losses | HR% | Avg Edge | Players |
|-----------|---------|-------|------|--------|-----|----------|---------|
| **Bench (<15)** | **high_ft** | **1,548** | **1,123** | **425** | **72.5%** | **5.2** | **58** |
| Bench (<15) | mod_ft | 3,641 | 2,496 | 1,145 | 68.6% | 5.0 | 127 |
| Bench (<15) | low_ft | 7,139 | 4,774 | 2,365 | 66.9% | 5.2 | 211 |
| Role (15-20) | high_ft | 645 | 442 | 203 | 68.5% | 6.0 | 31 |
| Role (15-20) | mod_ft | 1,681 | 1,155 | 526 | 68.7% | 6.0 | 79 |
| Role (15-20) | low_ft | 1,595 | 1,087 | 508 | 68.2% | 6.0 | 98 |
| Starter (20-25) | high_ft | 673 | 442 | 231 | 65.7% | 6.0 | 23 |
| Starter (20-25) | mod_ft | 1,296 | 886 | 410 | 68.4% | 6.5 | 49 |
| Starter (20-25) | low_ft | 645 | 450 | 195 | 69.8% | 6.7 | 37 |
| Star (25+) | high_ft | 783 | 579 | 204 | 73.9% | 6.3 | 20 |
| Star (25+) | mod_ft | 725 | 506 | 219 | 69.8% | 6.7 | 27 |
| Star (25+) | low_ft | 193 | 140 | 53 | 72.5% | 7.3 | 17 |

### UNDER Predictions

| Line Tier | FT Tier | Picks | Wins | Losses | HR% | Avg Edge | Players |
|-----------|---------|-------|------|--------|-----|----------|---------|
| Bench (<15) | high_ft | 4,248 | 2,632 | 1,616 | 62.0% | 5.0 | 53 |
| Bench (<15) | mod_ft | 9,322 | 5,868 | 3,454 | 62.9% | 5.1 | 126 |
| Bench (<15) | low_ft | 17,873 | 11,171 | 6,702 | 62.5% | 5.1 | 232 |
| Role (15-20) | high_ft | 1,281 | 804 | 477 | 62.8% | 5.3 | 35 |
| Role (15-20) | mod_ft | 3,455 | 2,198 | 1,257 | 63.6% | 5.6 | 93 |
| Role (15-20) | low_ft | 4,101 | 2,709 | 1,392 | 66.1% | 5.5 | 124 |
| Starter (20-25) | high_ft | 1,251 | 821 | 430 | 65.6% | 5.5 | 25 |
| Starter (20-25) | mod_ft | 2,755 | 1,816 | 939 | 65.9% | 5.8 | 57 |
| Starter (20-25) | low_ft | 1,726 | 1,155 | 571 | 66.9% | 5.9 | 57 |
| Star (25+) | high_ft | 1,675 | 1,127 | 548 | 67.3% | 5.9 | 20 |
| Star (25+) | mod_ft | 1,671 | 1,112 | 559 | 66.5% | 5.8 | 32 |
| Star (25+) | low_ft | 567 | 392 | 175 | 69.1% | 6.3 | 24 |

### Analysis

**Bench OVER — SIGNAL CONFIRMED AND STRENGTHENED:**
```
High FT + Bench OVER: 72.5%  (edge 5.2)
Mod FT  + Bench OVER: 68.6%  (edge 5.0)
Low FT  + Bench OVER: 66.9%  (edge 5.2)
```
5.6pp gradient at the SAME average edge (5.0-5.2). This is NOT a star-player confound — these are all bench players (line < 15). The FT floor effect is real and strongest where it matters most: low-line players where getting to the FT line 4-6 times provides a meaningful scoring floor relative to their line. **1,548 picks, 58 players — robust.**

**Role OVER — EFFECT DISAPPEARS:**
```
High FT: 68.5%  Mod FT: 68.7%  Low FT: 68.2%  (all ~68.5%, same edge)
```
FT rate is irrelevant for role players on OVER. The scoring floor mechanism doesn't matter when the line is 15-20 — the FT contribution is proportionally smaller.

**Starter OVER — EFFECT REVERSES (edge-confounded):**
```
High FT: 65.7% (edge 6.0)  Low FT: 69.8% (edge 6.7)
```
Low FT starters do better, but they also have 0.7 more points of edge. The reversal may be an edge distribution artifact, not a real anti-FT signal.

**Star OVER — HIGH FT WINS AGAIN:**
```
High FT: 73.9% (edge 6.3)  Mod FT: 69.8% (edge 6.7)  Low FT: 72.5% (edge 7.3)
```
High FT stars have the best HR despite the lowest edge among star sub-groups. The low FT star sample is tiny (193 picks). High FT stars represent the elite scorers who dominate the paint (Giannis, Embiid types) — their OVER predictions are excellent.

**UNDER — FT RATE WORKS IN REVERSE:**
At role, starter, and star tiers, LOW FT players have BETTER UNDER HR:
```
Role UNDER:    Low FT 66.1% > Mod 63.6% > High 62.8%
Starter UNDER: Low FT 66.9% > Mod 65.9% > High 65.6%
Star UNDER:    Low FT 69.1% > Mod 66.5% > High 67.3%
```
Players who don't draw free throws have less scoring floor, making UNDER more likely. This is the mirror image of the OVER effect. The bench tier UNDER is flat (FT floor doesn't matter when the line is very low).

### FT Rate Conclusion

**The signal is REAL but TIER-SPECIFIC:**
- **Bench OVER: STRONG** (72.5% vs 66.9%, 5.6pp, same edge) — FT floor protects low-line overs
- **Star OVER: MODERATE** (73.9% vs 69.8%, 4.1pp, despite LOWER edge)
- **Role OVER: NONE** — FT rate irrelevant at this tier
- **Starter OVER: REVERSED** but edge-confounded
- **Role/Starter/Star UNDER: REVERSE SIGNAL** — low FT players are better UNDER bets

**The reviewer was partially right:** the original 70.9% aggregate masked tier-specific behavior. But the reviewer was wrong that it was entirely a star-player confound — the effect is strongest in bench players, not stars.

---

## Controlled Test 2: Bust Rate x Line Tier

| Line Tier | Bust Tier | Picks | Wins | Losses | HR% | Avg Edge | Players |
|-----------|-----------|-------|------|--------|-----|----------|---------|
| Bench (<15) | high_bust | 16,472 | 10,343 | 6,129 | 62.8% | 5.1 | 149 |
| Bench (<15) | mod_bust | 14,620 | 9,548 | 5,072 | **65.3%** | 5.1 | 129 |
| Bench (<15) | low_bust | 3,673 | 2,354 | 1,319 | 64.1% | 5.1 | 51 |
| Role (15-20) | high_bust | 2,315 | 1,502 | 813 | 64.9% | 6.0 | 80 |
| Role (15-20) | mod_bust | 7,181 | 4,727 | 2,454 | 65.8% | 5.6 | 110 |
| Role (15-20) | low_bust | 2,894 | 1,914 | 980 | **66.1%** | 5.5 | 44 |
| Starter (20-25) | high_bust | 949 | 661 | 288 | **69.7%** | 6.1 | 27 |
| Starter (20-25) | mod_bust | 4,377 | 2,905 | 1,472 | 66.4% | 6.0 | 71 |
| Starter (20-25) | low_bust | 3,016 | 2,005 | 1,011 | 66.5% | 5.8 | 40 |
| Star (25+) | high_bust | 929 | 642 | 287 | 69.1% | 6.2 | 10 |
| Star (25+) | mod_bust | 1,621 | 1,107 | 514 | 68.3% | 6.3 | 36 |
| Star (25+) | low_bust | 3,064 | 2,107 | 957 | 68.8% | 6.0 | 30 |

### Analysis

**Reviewer was RIGHT — bust rate gradient largely disappears when controlling for tier.**

**Bench (<15):**
```
High bust: 62.8%  Mod bust: 65.3%  Low bust: 64.1%
```
Non-monotonic. Moderate bust is best, not low bust. The original clean gradient was a tier-mix artifact.

**Role (15-20):**
```
High bust: 64.9%  Mod bust: 65.8%  Low bust: 66.1%
```
Weak gradient remains (1.2pp) but hardly actionable.

**Starter (20-25):**
```
High bust: 69.7%  Mod bust: 66.4%  Low bust: 66.5%
```
REVERSED. High bust starters predict BEST. Small sample (949 picks, 27 players) but striking.

**Star (25+):**
```
High bust: 69.1%  Mod bust: 68.3%  Low bust: 68.8%
```
Flat. All within 0.8pp.

### Bust Rate Conclusion

**The original 2.7pp gradient was a CONFOUND.** Once you control for player tier, bust rate has no consistent predictive value. The original finding was driven by the fact that low-bust players are disproportionately higher-tier players, who predict better regardless.

**Do NOT add bust_rate as a feature or filter.** It would be redundant with information the model already has via `points_avg_season`, `points_std_last_10`, and implicitly via `line_value`.

---

## Feature 21 (`pct_free_throw`) vs Proposed `ft_rate_season`

**Feature 21 is:** `sum(FT makes) / sum(total points)` over last 10 games — the percentage of a player's scoring that comes from free throws.

**Proposed `ft_rate_season` is:** `sum(FT attempts) / sum(FG attempts)` over the season — how often a player gets to the line relative to field goal attempts.

These measure related but different things:
- `pct_free_throw` = scoring output composition (result)
- `ft_rate` = shot attempt behavior (process)

A player could have high `ft_rate` but moderate `pct_free_throw` if they also take many field goals. Feature 21 is a 10-game rolling window; the proposed metric is season-long. **They are correlated but not redundant.** Adding `ft_rate_season` could still provide incremental value, especially since the rolling L10 window is noisier than a season aggregate.

---

## Revised Recommendations

Based on the controlled analysis:

### Confirmed Actionable
1. **FT Rate x Direction x Tier interaction** — The bench OVER signal (72.5% at 5.6pp gradient) is real and robust. This is the strongest validated finding.
2. **FT Rate reverse for UNDER** — Low FT players are better UNDER bets at role+ tiers. Mirror signal.

### Demoted
1. **Bust rate** — Confound confirmed. Drop from profile priority list.
2. **Raw CV** — Already weak, now further diminished since bust rate (its close cousin) doesn't hold up.

### Still Worth Investigating
1. **Zone archetype** — Not yet controlled. Should run same stratified analysis.
2. **Role clarity (shot creation)** — Too few players in extremes; needs different approach.
3. **Minutes stability** — Reviewer suggested; not yet tested.

### Immediate Action
- The FT rate signal is tier-specific. This is better modeled as an **ML feature** (let CatBoost learn the tier interaction) rather than a **flat signal/filter**. Add `ft_rate_season` as feature index 55 and let the model figure out when it matters.
