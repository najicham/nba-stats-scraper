# Signal Cleanup Analysis Plan

**Date:** 2026-02-14
**Session:** 256
**Goal:** Determine which signals to keep/remove through comprehensive combination and segmentation testing

---

## Problem Statement

Registry has 23 signals (8 core + 15 prototypes). Initial standalone performance analysis showed:
- 4 signals profitable standalone (3pt_bounce, cold_snap, blowout_recovery, minutes_surge)
- 3 signals harmful standalone (prop_value_gap_extreme 12.5% HR, edge_spread_optimal 47.4%, high_edge 50.8%)
- 13 prototype signals with 0 picks (never qualified)

**BUT:** Combination analysis revealed that "harmful" standalone signals perform EXCELLENTLY in combos:
- `high_edge + prop_value_gap_extreme`: 88.9% HR (vs prop_value alone: 12.5%)
- `high_edge + minutes_surge + edge_spread_optimal`: 100% HR (vs edge_spread alone: 47.4%)

**Key Question:** Are these signals adding value or just riding high_edge's coattails?

---

## Analysis Framework

### 1. Combination Mechanics Analysis
**Goal:** Understand if signals are additive or overlapping

**Tests:**
- For each combo (e.g., `high_edge + prop_value_gap`), partition picks into:
  - Picks that qualify for BOTH signals (intersection)
  - Picks that qualify for ONLY signal A (A - B)
  - Picks that qualify for ONLY signal B (B - A)
- Compare performance: Does the intersection perform better than either alone?
- Statistical significance: Use confidence intervals for small samples

**Specific combos to test:**
```
high_edge + prop_value_gap_extreme (9 picks, 88.9% HR)
high_edge + minutes_surge + edge_spread_optimal (11 picks, 100% HR)
high_edge + edge_spread_optimal (76 picks, 55.3% HR)
high_edge + minutes_surge (12 picks, 75% HR)
3pt_bounce + blowout_recovery (from backtest doc: 7 picks, 100% HR)
cold_snap + blowout_recovery (from backtest doc: 10 picks, 70% HR)
```

### 2. Segmentation Analysis for All Signals
**Goal:** Discover if "bad" standalone signals work in specific contexts

**Segments to test:**
- **Player tier** (line value): Stars (25+), Mid (15-25), Role (<15)
- **Minutes tier**: Heavy (32+), Starter (25-32), Bench (<25)
- **Team context**: Home/Away, Favored/Underdog (if spread data available)
- **Temporal**: Day of week, rest days, back-to-back
- **Edge magnitude**: Small edge (<4), Medium (4-6), Large (6+)

**Signals to segment:**
- All 7 signals with picks (including the "harmful" ones)
- Especially: `prop_value_gap_extreme`, `edge_spread_optimal`, `cold_snap` (contradictory results)

### 3. Statistical Rigor
**Goal:** Avoid false positives from small samples

**Methods:**
- Binomial confidence intervals (Wilson score)
- Minimum sample size thresholds (N >= 20 for conclusions, flag 5-19 as "promising but needs data")
- Multiple comparison correction (Bonferroni or FDR) when testing many segments

### 4. Signal Interaction Patterns
**Goal:** Build interaction matrix to understand which signals amplify each other

**Approach:**
- Create NxN matrix where N = number of signals with picks
- Cell (i,j) = performance when signals i and j overlap
- Identify synergistic pairs (combo >> individual) vs redundant pairs (combo ≈ individual)

**Expected outputs:**
```
              high_edge  minutes_surge  3pt_bounce  blowout_recovery  ...
high_edge         62.5%          75.0%       ???%             ???%
minutes_surge     75.0%          50.5%       40.0%            60.0%
3pt_bounce        ???%           40.0%       70.0%            100%
blowout_recovery  ???%           60.0%       100%             51.1%
...
```

### 5. Standalone vs Combo-Only Classification
**Goal:** Categorize signals by their role

**Categories:**
- **Standalone strong**: Profitable alone and in combos (e.g., 3pt_bounce)
- **Combo booster**: Weak alone but amplifies other signals (e.g., prop_value_gap_extreme?)
- **Overlap filter**: Only valuable when overlapping specific signals
- **Dead weight**: Harmful in all contexts (remove)

---

## Execution Plan

### Agent 1: Combination Mechanics Deep Dive
**Task:** Analyze top 10 signal combinations to determine if signals are additive

**Deliverables:**
- Table showing intersection vs union performance
- Statistical significance tests (binomial CI)
- Recommendation: which combo signals add value vs ride coattails

### Agent 2: Segmentation Analysis - "Harmful" Signals
**Task:** Run segmentation (player tier, minutes, edge) on `prop_value_gap_extreme`, `edge_spread_optimal`, `cold_snap`

**Deliverables:**
- Per-segment performance tables
- Identify any profitable segments
- Explain contradictory results (e.g., cold_snap 61% vs 46%)

### Agent 3: Signal Interaction Matrix
**Task:** Build complete interaction matrix for all 7 signals with picks

**Deliverables:**
- NxN matrix with HR/ROI for each pair
- Heatmap visualization (if feasible in markdown/CSV)
- Top 10 synergistic pairs

### Agent 4: Zero-Pick Prototype Investigation
**Task:** Examine why 13 prototypes had 0 picks

**Deliverables:**
- For each prototype: read the code, understand thresholds/logic
- Run counterfactual: "how many picks if we relaxed threshold by X%?"
- Categorize: too restrictive vs fundamentally broken

### Agent 5: v_signal_performance Validation
**Task:** Understand discrepancies between v_signal_performance and manual calculations

**Deliverables:**
- Read view definition SQL
- Explain why cold_snap shows 61% vs 46%, high_edge 50.8% vs 62.5%
- Validate which calculation is correct

---

## Decision Criteria

After all analyses complete, apply these rules:

### Keep Signal If:
- Standalone HR >= 52.4% AND N >= 20, OR
- Combo HR >= 60% when paired with >= 2 other signals AND statistically significant, OR
- Has profitable segment (HR >= 55%) AND N >= 30 in that segment

### Mark as "Combo-Only" If:
- Standalone HR < 52.4% BUT
- Consistently boosts combo performance (average lift >= +5% HR) AND
- Statistical significance in >= 2 different combos

### Remove If:
- Standalone HR < 50% AND
- No profitable segments AND
- Doesn't boost any combos (lift < +3% HR)

### Defer Decision If:
- Total picks < 20 (insufficient data)
- Contradictory results across windows (needs temporal analysis)

---

## Expected Outcomes

1. **Classification of all 23 signals** into: Keep / Combo-only / Remove / Defer
2. **Interaction matrix** showing which signals synergize
3. **Segmentation insights** for targeted signal application
4. **Updated registry** with only value-adding signals
5. **Documentation** of all tested signals (even rejected ones) for future reference

---

## Open Questions

1. Should we implement combo-only signals differently in the aggregator?
2. How to handle signals that only work in specific segments? (conditional logic in signal class?)
3. What's the right balance between combo diversity vs combo performance?
4. Should we weight combo scores differently than standalone scores?

---

## Next Steps After Analysis

1. Review all agent deliverables
2. Apply decision criteria to each signal
3. Update registry with consensus decisions
4. Annotate removed signal files with STATUS: REJECTED + data
5. Consider reorganization: ml/signals/active/, ml/signals/combo_only/, ml/signals/rejected/
6. Update COMPREHENSIVE-SIGNAL-TEST-PLAN.md with learnings
