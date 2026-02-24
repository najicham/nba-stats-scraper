# Player Profiles — Complete Controlled Validation

**Date:** 2026-02-23
**Method:** All dimensions stratified by prop line tier to control for player quality confound. All models combined, edge 3+, graded, not voided, has prop line.

---

## Dimension Scorecard

| # | Dimension | Signal? | Survives Control? | Actionable? |
|---|-----------|---------|-------------------|-------------|
| 1 | **FT Rate x Direction** | STRONG | YES — strongest at bench OVER | YES |
| 2 | **Zone Archetype** | MODERATE | YES — mid-range consistent edge | MAYBE (as feature) |
| 3 | **Starter Flag** | SURPRISING | YES — bench scorers beat starters at same line tier | YES |
| 4 | **FT Rate x Zone** | MODERATE | YES — FT boost is zone-independent | Confirms FT signal |
| 5 | Minutes Stability | WEAK | NO — reversed at role/starter tiers | NO |
| 6 | Role Clarity | NONE | NO — no consistent pattern | NO |
| 7 | Bust Rate | CONFOUND | NO — collapsed once controlled | NO |
| 8 | Game Script | INSUFFICIENT | Too few players in extremes | NO |

---

## 1. FT Rate x Direction x Line Tier (CONFIRMED)

Full results in `07-CONTROLLED-VALIDATION-RESULTS.md`. Summary:

**OVER predictions — FT rate gradient:**
```
Bench (<15):   High FT 72.5% → Mod 68.6% → Low 66.9%  (5.6pp, same edge)  ✓ STRONG
Star (25+):    High FT 73.9% → Mod 69.8% → Low 72.5%  (mixed, edge varies) ~ MODERATE
Role (15-20):  Flat at ~68.5% across all FT tiers                           ✗ NONE
Starter (20-25): Reversed (low FT wins, but higher edge)                    ✗ CONFOUNDED
```

**UNDER predictions — reverse FT gradient at higher tiers:**
```
Role UNDER:    Low FT 66.1% > Mod 63.6% > High 62.8%    ✓ Low FT helps UNDER
Starter UNDER: Low FT 66.9% > Mod 65.9% > High 65.6%    ✓ Low FT helps UNDER
Star UNDER:    Low FT 69.1% > Mod 66.5% > High 67.3%    ✓ Low FT helps UNDER
Bench UNDER:   Flat at ~62-63%                            ✗ NONE
```

**Conclusion:** FT rate is a real, direction-dependent, tier-specific signal. Best expressed as a continuous ML feature — let CatBoost learn the interactions.

---

## 2. Zone Archetype (SURVIVES CONTROL)

**Within each tier, mid-range consistently leads:**

| Line Tier | Interior | Perimeter | Mid-Range | Balanced | Spread |
|-----------|----------|-----------|-----------|----------|--------|
| Bench (<15) | 64.0% | 63.3% | **66.0%** | 64.5% | 2.7pp |
| Role (15-20) | 64.8% | 66.2% | **66.4%** | 64.9% | 1.6pp |
| Starter (20-25) | 66.1% | 66.8% | **67.7%** | 65.1% | 2.6pp |
| Star (25+) | 68.5% | 68.3% | **68.9%** | 68.1% | 0.8pp |

Mid-range wins at every tier. Perimeter is generally worst at bench, catches up at higher tiers. The effect is modest (1-3pp) but consistent across tiers — **this is not a player quality confound**.

**Zone x Direction (star tier, most striking):**
```
Star Interior OVER:  75.8%  (396 picks, edge 6.1, 13 players)  ← BEST
Star Mid-Range OVER: 71.7%  (842 picks, edge 6.5, 19 players)
Star Balanced OVER:  70.6%  (293 picks, edge 7.0, 12 players)
Star Perimeter OVER: 66.7%  (162 picks, edge 7.9, 18 players)  ← WORST despite highest edge
```

Star interior scorers OVER is 75.8% at only 6.1 edge. Star perimeter OVER is 66.7% despite 7.9 edge. **The model is significantly better at predicting interior stars going over than perimeter stars.** This likely overlaps with the FT rate finding (interior scorers draw more fouls).

**Mid-range UNDER is the best UNDER zone** across most tiers (64.7% at bench, 65.6% at role, 67.4% at starter, 67.5% at star).

**Verdict:** Zone archetype is a moderate but consistent signal. Worth adding as a continuous feature (paint_rate, three_pt_rate already exist as features 18-20, but mid_range_rate deserves attention). The directional interaction (interior OVER, perimeter caution) is the real value.

---

## 3. Starter Flag (SURPRISING FINDING)

**Within each line tier, bench scorers predict BETTER than starters:**

| Line Tier | Always Starts | Usually Bench | Always Bench | Spread |
|-----------|---------------|---------------|--------------|--------|
| Bench (<15) | **65.2%** | 63.8% | 63.9% | Starters +1.3pp |
| Role (15-20) | 64.9% | **67.7%** | **67.8%** | Bench +2.9pp |
| Starter (20-25) | 65.9% | **68.4%** | **69.8%** | Bench +3.9pp |
| Star (25+) | 67.5% | **69.9%** | **69.6%** | Bench +2.4pp |

At bench tier, starters are slightly better (makes sense — they have defined roles). But at every higher tier, **non-starters with high lines outperform starters with the same lines** by 2-4pp.

**Why this makes sense:**
- "Sixth man" types (bench players scoring 15-25+ points) have defined, specialized roles
- Their minutes are often more consistent (coach gives them a set rotation)
- They face weaker second-unit defenders, making scoring more predictable
- The market may misprice them because they're "bench players" despite being prolific scorers

**This is NOT currently in the feature vector.** `starter_flag` exists in `player_game_summary` and flows to supplemental data but is never used as an ML feature. This is low-hanging fruit.

**Verdict:** ACTIONABLE. The finding is robust (large samples, consistent across tiers, same edge levels) and the feature already exists — just needs to be promoted to the feature vector.

---

## 4. FT Rate x Zone Archetype Cross-Dimension

**Does FT rate compound with zone archetype?**

OVER predictions:
| Zone | High FT HR | Low/Mod FT HR | FT Boost |
|------|-----------|---------------|----------|
| Balanced | 70.9% | 68.5% | +2.4pp |
| Mid-Range | 70.5% | 68.6% | +1.9pp |
| Interior | 70.1% | 68.6% | +1.5pp |
| Perimeter | 69.0% | 67.1% | +1.9pp |

High FT adds ~1.5-2.4pp across ALL zone types for OVER. The FT effect is **zone-independent** — it's not just that interior scorers draw fouls. Even perimeter players with high FT rates get a boost on OVER.

UNDER predictions:
| Zone | High FT HR | Low/Mod FT HR |
|------|-----------|---------------|
| Mid-Range | 66.1% | 65.7% |
| Balanced | 62.4% | 63.5% |
| Interior | 62.7% | 63.3% |
| Perimeter | 62.3% | 63.0% |

High FT slightly hurts UNDER at most zones. Mid-range UNDER is the exception (strong regardless of FT).

**Best single combo:** Mid-range + High FT + OVER = 70.5% (1,091 picks, 13 players).

**Verdict:** FT rate and zone are independent signals — they don't compound but they don't cancel either. Both are worth adding as features.

---

## 5. Minutes Stability (DOES NOT SURVIVE)

**Bench (<15) — only tier with gradient:**
```
Stable (10-20% CV):  64.9%  (14,390 picks)
Moderate (20-30%):   64.3%  (11,327 picks)
Unstable (30%+):     63.1%  (14,934 picks)
→ 1.8pp spread, same edge. Modest but real at bench tier.
```

**All higher tiers — reversed or flat:**
```
Role:    Unstable 67.3% > Stable 65.1%  (REVERSED)
Starter: Unstable 71.2% > Stable 66.0%  (REVERSED, edge-confounded)
Star:    Flat at 68-69%
```

**Minutes x Direction** does not reveal strong patterns beyond what's already captured.

**Why reversal at higher tiers?** Minutes instability at role/starter level often means a player has high variance in playing time due to game flow — they play more in close games (where they're needed) and less in blowouts. This actually makes them MORE predictable in a typical game, not less. The bench-tier gradient is the only real signal (bench players with stable minutes have defined roles).

**Verdict:** DROP. Not worth adding as a feature. The bench effect is modest (1.8pp) and the reversal at higher tiers would confuse a model.

---

## 6. Role Clarity (NO PATTERN)

**Distance from 50% assisted rate, by line tier:**

| Line Tier | Very Defined (25+) | Defined (15-25) | Moderate (5-15) | Unclear (<5) |
|-----------|--------------------|-----------------|-----------------|--------------|
| Bench | 65.2% | 63.5% | 64.1% | 64.3% |
| Role | 64.2% | **67.0%** | 65.8% | 65.1% |
| Starter | 63.9% | **67.7%** | 67.4% | 67.2% |
| Star | 69.1% | 67.8% | 69.3% | 63.6% |

Non-monotonic, no consistent pattern across tiers. The "defined" bucket (15-25% distance) seems best at role/starter, but "very defined" (25+%) is worst at starter tier. The reviewer's suggestion that "role clarity" matters was a reasonable hypothesis but it doesn't hold up in the data.

**Verdict:** DROP. Not actionable.

---

## 7. Game Script Sensitivity (INSUFFICIENT DATA)

Most players cluster in the "script neutral" category (correlation between -0.15 and +0.15). The extreme buckets had almost no qualifying players:
- "More in blowouts" bench: 65 picks, 1 player
- "Less in blowouts" at each tier: 1-5 players each

The dimension is conceptually interesting but the NBA doesn't produce enough blowout variance per player to create meaningful samples.

**Verdict:** DROP. Insufficient data to evaluate.

---

## Final Ranking of Profile Dimensions

**Tier 1 — Confirmed Actionable (add as ML features):**
1. **FT Rate (FTA/FGA)** — Strong directional signal, tier-specific, robust samples
2. **Starter Rate** — Surprising 2-4pp edge for bench scorers at role+ lines, large samples, already exists in BQ
3. **Zone Archetype (continuous rates)** — Mid-range 1-3pp edge across tiers, consistent, zone-independent

**Tier 2 — Worth Monitoring But Not Prioritized:**
4. Minutes stability — Only works at bench tier (1.8pp), reverses elsewhere
5. Role clarity — No consistent pattern

**Tier 3 — Debunked:**
6. Bust rate — Confound with player quality
7. Raw CV — Weak and redundant
8. Game script sensitivity — Insufficient data

---

## Revised Implementation Recommendation

Given these results, the full 40-field profile table is overkill. The three actionable dimensions can be added directly to the feature store:

1. **`ft_rate_season`** (FTA / FGA, season-level) → new feature index 55
2. **`starter_rate_season`** (% games started) → new feature index 56
3. Zone rates already exist as features 18-20 (`pct_paint`, `pct_mid_range`, `pct_three`)

The first two are simple SQL computations on `player_game_summary` during feature store extraction. No new table, no new processor needed.

A targeted retrain with features 55-56 added would test whether CatBoost can learn the tier-direction interactions we found in these queries. If it can, we're done. If it can't learn them from features alone, THEN consider signal-level integration (e.g., "high FT bench OVER boost" signal).
