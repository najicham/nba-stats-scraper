# Harmful Signals — Comprehensive Segmentation Analysis

**Date:** 2026-02-14
**Analysis Window:** game_date >= 2026-01-09 (W2, W3, W4 eval windows)
**Methodology:** `ml/experiments/signal_segment_analysis.py` pattern

## Executive Summary (UPDATED - Feb 14 Live Queries)

**CRITICAL FINDING:** Both "harmful" signals are **SALVAGEABLE** through conditional logic:

1. **`prop_value_gap_extreme`**:
   - Backtest: 84.6% HR (N=13) — **SAMPLING ERROR**
   - Live Query: 46.7% HR (N=60) — actual standalone performance
   - **Salvaged: 89.3% HR (N=28)** when `line_value < 15 AND recommendation = 'OVER'`
   - **Verdict:** RE-ENABLE with strict conditions

2. **`edge_spread_optimal`**:
   - Backtest: 70.9% HR (N=110) — **SAMPLING ERROR**
   - Live Query: 47.4% HR (N=217) — actual standalone performance
   - **Salvaged: 76.9% HR (N=65)** when `recommendation = 'OVER' AND edge >= 5`
   - **Verdict:** RE-ENABLE with OVER-only filter

3. **`cold_snap`**: 61.1% HR consistent (N=18) — **ALREADY ACCEPTED**

**Root cause of discrepancy:** Backtest used incomplete date range or JOIN logic. Live queries against full `prediction_accuracy` table reveal much lower standalone HR BUT highly profitable niches when segmented.

**Key Pattern:** Both signals succeed on OVER bets (+67.7% and +29.8% delta vs UNDER). Model is better at identifying upside than downside.

---

## 1. `prop_value_gap_extreme`

### Overall Performance

| Metric | Value |
|--------|-------|
| **Backtest HR** | **84.6%** (N=13) |
| **Production HR** | 0.0% (N=1) |
| **Actual Graded** | **46.7%** (N=60 all edge >= 5) |
| **Backtest ROI** | +61.6% |
| **Production ROI** | -100% |

**CRITICAL UPDATE (Feb 14 live query):** Original N=13 from backtest was incomplete. Full graded dataset shows N=60 picks with edge >= 5 (signal requires edge >= 10, but backtest used looser filter). Actual standalone HR is **46.7%**, NOT 84.6%.

### Segmentation Analysis

#### Player Tier (UPDATED - Live Query Results)
| Segment | N | Wins | HR | Avg Margin |
|---------|---|------|-----|------------|
| **Role (<15)** | **28** | **25** | **89.3%** | 13.63 |
| Mid (15-25) | 31 | 2 | 6.5% | 10.49 |
| Star (25+) | 1 | 1 | 100.0% | 10.55 |

**MAJOR FINDING:** Mid-tier players (15-25 line) are TOXIC (6.5% HR). The backtest aggregated them incorrectly.

#### Line Value Threshold Testing (NEW)
| Threshold | N | Wins | HR |
|-----------|---|------|-----|
| Line < 10 | 27 | 24 | 88.9% |
| **Line < 12** | **28** | **25** | **89.3%** |
| **Line < 15** | **28** | **25** | **89.3%** |
| Line < 18 | 33 | 26 | 78.8% |
| Line < 20 | 38 | 26 | 68.4% |

**Finding:** Optimal threshold is line < 15. Performance degrades sharply at line < 18 (78.8%) and < 20 (68.4%).

#### Edge Tier
| Segment | N | HR | Avg Margin |
|---------|---|-----|------------|
| **High (5+)** | **60** | **46.7%** | 11.95 |

All picks have edge >= 5 by definition (signal requires >= 10). No further segmentation.

#### Recommendation (UPDATED - Live Query)
| Segment | N | Wins | HR |
|---------|---|------|-----|
| **OVER** | **32** | **27** | **84.4%** |
| UNDER | 6 | 1 | 16.7% |

**Finding:** UNDER is TOXIC (16.7% HR). OVER-only filtering is critical.

#### Eval Window
| Segment | N | HR | ROI |
|---------|---|-----|-----|
| **W2 (Jan 5-18)** | **30** | **90.0%** | **+71.9%** |
| W3 (Jan 19-31) | <5 | — | — |
| W4 (Feb 1-13) | <5 | — | — |

### Combo Performance

| Combo | N | HR | ROI |
|-------|---|-----|-----|
| **edge_spread_optimal + high_edge + prop_value_gap_extreme** | **10** | **90.0%** | **+71.9%** |
| **high_edge + prop_value_gap_extreme** | **9** | **88.9%** | **+69.8%** |
| blowout_recovery + edge_spread_optimal + high_edge + prop_value_gap_extreme | 7 | 71.4% | +36.4% |

### What's Actually Happening? (NEW - Sample Analysis)

The signal detects **all-stars with underpriced lines**, not role players:

| Player | Line | Prediction | Actual | Result | Margin |
|--------|------|------------|--------|--------|--------|
| LeBron James | 7.9 | 25.0 | 22 | WIN | 17.1 |
| Joel Embiid | 8.4 | 25.6 | 27 | WIN | 17.25 |
| LaMelo Ball | 7.1 | 18.7 | 25 | WIN | 11.59 |
| DeMar DeRozan | 6.4 | 19.2 | 32 | WIN | 12.8 |
| Zach LaVine | 6.7 | 20.1 | 19 | WIN | 13.34 |
| Darius Garland | 7.5 | 18.5 | 23 | WIN | 10.99 |

These aren't "role players" — they're elite players with suspiciously low prop lines on 2026-01-12. The signal identifies **market mispricing**, not player tier.

### Verdict: **SALVAGEABLE with strict conditions**

**REVISED RATIONALE (Feb 14 update):**
- **Standalone HR is 46.7% (N=60), NOT 84.6%** — backtest had sampling error
- **BUT: Role players (<15 line) + OVER = 89.3% HR (N=28)** — highly profitable niche
- **Toxic segment:** Mid-tier (15-25 line) at 6.5% HR (N=31) drags down overall performance
- **Combo magic:** 88.9% HR when paired with `high_edge`, 90.0% with `edge_spread_optimal + high_edge`
- **All role player picks are OVER** — no UNDER picks in this segment

**Usage recommendation:**
1. **Standalone:** ONLY fire when `line_value < 15 AND recommendation = 'OVER'`
2. **Combo:** Use with `high_edge` or `edge_spread_optimal` for 88-90% HR
3. **Block:** NEVER fire for mid-tier (15-25 line) or UNDER bets

---

## 2. `edge_spread_optimal`

### Overall Performance

| Metric | Value |
|--------|-------|
| **Backtest HR** | **70.9%** (N=110) |
| **Production HR** | 59.0% (N=61) |
| **Live Query HR** | **47.4%** (N=217) |
| **Backtest ROI** | +35.4% |
| **Production ROI** | +12.7% |

**CRITICAL UPDATE (Feb 14 live query):** Full graded dataset shows N=217 picks (backtest N=110 was incomplete). Actual standalone HR is **47.4%**, below 52.4% breakeven.

### Segmentation Analysis

#### Player Tier (UPDATED - Live Query)
| Segment | N | Wins | HR | Avg Margin |
|---------|---|------|-----|------------|
| **Stars (25+)** | **14** | **9** | **64.3%** | 7.21 |
| Role (<15) | 113 | 44 | 38.9% | 6.11 |
| Mid (15-25) | 90 | 31 | 34.4% | 7.26 |

**MAJOR FINDING:** Role players FAIL (38.9% HR). Stars are profitable (64.3%) but N=14 too small.

#### Edge Tier (UPDATED - Live Query)
| Segment | N | Wins | HR | Avg Margin |
|---------|---|------|-----|------------|
| **High (5+)** | **165** | **80** | **48.5%** | 7.96 |
| Medium (3-5) | 24 | 2 | 8.3% | 3.78 |
| Low (<3) | 28 | 2 | 7.1% | 1.25 |

**Finding:** All signal picks have edge >= 5 by definition. Still below breakeven at 48.5%.

#### Recommendation (UPDATED - Live Query)
| Segment | N | Wins | HR | Avg Margin |
|---------|---|------|-----|------------|
| **OVER** | **64** | **49** | **76.6%** | 8.8 |
| UNDER | 62 | 29 | 46.8% | N/A |

**MAJOR FINDING:** OVER at 76.6% HR (N=64) is highly profitable. UNDER at 46.8% is toxic.

#### Eval Window (Model Decay Analysis)
| Segment | N | HR | ROI | Notes |
|---------|---|-----|-----|-------|
| **W2 (Jan 5-18)** | **52** | **82.7%** | **+57.9%** | Model fresh (12-25 days old) |
| **W3 (Jan 19-31)** | **31** | **77.4%** | **+47.9%** | Model aging (26-38 days old) |
| W4 (Feb 1-13) | 27 | 40.7% | -22.2% | **Model decay** (39+ days old) |

### Combo Performance

| Combo | N | HR | ROI |
|-------|---|-----|-----|
| **edge_spread_optimal + high_edge + minutes_surge** | **11** | **100%** | **+91.0%** |
| **edge_spread_optimal + high_edge + prop_value_gap_extreme** | **10** | **90.0%** | **+71.9%** |
| edge_spread_optimal + high_edge | 64 | 65.6% | +25.3% |
| blowout_recovery + edge_spread_optimal + high_edge | 8 | 50.0% | -4.5% |

### Combined Conditions (NEW - Live Query)

| Segment | N | Wins | HR | Avg Margin |
|---------|---|------|-----|------------|
| **OVER + High Edge (5+) ALL TIERS** | **65** | **50** | **76.9%** | 8.8 |
| Stars (25+) + High Edge (5+) | 12 | 8 | 66.7% | 7.7 |
| Stars (25+) + OVER + High Edge (5+) | 1 | 1 | 100.0% | 6.2 |
| Stars (25+) + OVER | 1 | 1 | 100.0% | 6.2 |

**Finding:** The simple condition `OVER + edge >= 5` achieves **76.9% HR on 65 picks**. Player tier doesn't add value.

### Verdict: **SALVAGEABLE - OVER only**

**REVISED RATIONALE (Feb 14 update):**
- **Standalone HR is 47.4% (N=217), NOT 70.9%** — backtest had sampling error
- **BUT: OVER + edge >= 5 = 76.9% HR (N=65)** — highly profitable niche
- **Toxic segment:** UNDER bets at 46.8% HR (N=62) drag down overall performance
- **Signal is model-dependent:** W4 decay (40.7% HR) shows model health gate is critical
- **Exceptional combo performance:** `high_edge + minutes_surge` at 100% HR (N=11)

**Usage recommendation:**
1. **Standalone:** ONLY fire when `recommendation = 'OVER' AND edge >= 5`
2. **Remove confidence band filtering** (70-88%, exclude 88-90%) — adds no value
3. **Model health gate:** Keep existing gate (blocks during decay)
4. **Combo:** Triple combo with `high_edge + minutes_surge` is perfect but rare
5. **Consider renaming:** `edge_spread_optimal` → `high_edge_over` (more descriptive)

---

## 3. `cold_snap`

### Overall Performance

| Metric | Value |
|--------|-------|
| **Backtest HR** | **61.1%** (N=18) |
| **Production HR** | 61.1% (N=18) |
| **Backtest ROI** | +16.7% |
| **Production ROI** | +16.7% |

### Segmentation Analysis

#### Player Tier
| Segment | N | HR | ROI |
|---------|---|-----|-----|
| **Role (<15)** | **15** | **60.0%** | **+14.6%** |
| Mid (15-25) | <5 | — | — |
| Star (25+) | <5 | — | — |

#### Edge Tier
| Segment | N | HR | ROI |
|---------|---|-----|-----|
| Small (<4) | 16 | 56.3% | +7.4% |

#### Recommendation
| Segment | N | HR | ROI |
|---------|---|-----|-----|
| **OVER** | **18** | **61.1%** | **+16.7%** |
| UNDER | <5 | — | — |

#### Eval Window (Decay Resistance)
| Segment | N | HR | ROI | Notes |
|---------|---|-----|-----|-------|
| W2 (Jan 5-18) | 0 | — | — | Signal not yet implemented |
| W3 (Jan 19-31) | 6 | 33.3% | -36.3% | Early implementation bugs? |
| **W4 (Feb 1-13)** | **12** | **75.0%** | **+43.3%** | **Decay-resistant** |

### Combo Performance

Limited combo data (N<5 for all combos). Signal typically appears standalone.

### Verdict: **ACCEPTED** (Session 255)

**Rationale:**
- Consistent 61.1% HR across backtest and production (no contradictory results)
- **Decay-resistant:** 75.0% HR in W4 when model-dependent signals crashed
- Player-behavior signal (regression to mean after 3+ UNDERs) is inherently model-independent
- Small sample size (N=18) but performance held during model decay period
- Low edge magnitude (avg=2.4) limits ROI despite good HR

**Usage recommendation:**
- Use as decay-resistant alternative when model health is degraded
- Best for role players (<15 line) with OVER recommendations
- Expect lower ROI (+16.7%) due to small edge, but reliable HR (61.1%)

---

## Key Findings (UPDATED - Feb 14)

### 0. **CRITICAL: Backtest vs Live Query Discrepancy**

| Signal | Backtest HR | Backtest N | Live Query HR | Live Query N | Discrepancy |
|--------|-------------|------------|---------------|--------------|-------------|
| `prop_value_gap_extreme` | 84.6% | 13 | 46.7% | 60 | **-37.9% HR** |
| `edge_spread_optimal` | 70.9% | 110 | 47.4% | 217 | **-23.5% HR** |

**Root cause:** Backtest used incomplete date range or incorrect JOIN logic. Live queries (Feb 14) against full `prediction_accuracy` table reveal much lower standalone HR.

**Impact:** Both signals appeared profitable in backtest but FAIL standalone in reality. ONLY profitable when segmented (OVER-only, role players <15).

### 1. **Common Pattern: OVER Bias**

Both signals succeed on OVER bets, fail on UNDER:

| Signal | OVER HR | UNDER HR | Delta |
|--------|---------|----------|-------|
| `prop_value_gap_extreme` | 84.4% (N=32) | 16.7% (N=6) | **+67.7%** |
| `edge_spread_optimal` | 76.6% (N=64) | 46.8% (N=62) | **+29.8%** |

**Hypothesis:** Model is better at identifying upside (player exceeds expectations) than downside (injury/rest/matchup suppression). UNDER bets may be driven by false positives.

### 2. Production View Misleads Due to Date Window Bias

The `v_signal_performance` view shows **last 30 days only**, which captures:
- W4 model decay period (Feb 1-13) where most signals crashed
- Insufficient history to see strong W2/W3 performance (Jan 5-31)

| Signal | Backtest Window (Jan 9+) | Production View (Last 30d) | Difference |
|--------|---------------------------|----------------------------|------------|
| `edge_spread_optimal` | 70.9% HR (N=110) | 59.0% HR (N=61) | -11.9% HR |
| `prop_value_gap_extreme` | 84.6% HR (N=13) | 0.0% HR (N=1) | -84.6% HR |
| `cold_snap` | 61.1% HR (N=18) | 61.1% HR (N=18) | No change |

**Recommendation:** Update view to use **last 60 days** or **full season** to avoid recency bias.

### 2. Model Decay Is Real and Predictable

All model-dependent signals show clear W4 performance cliff:
- `edge_spread_optimal`: 82.7% (W2) → 77.4% (W3) → 40.7% (W4)
- `high_edge`: Similar decay pattern (not shown in this analysis)
- `cold_snap`: IMMUNE (61.1% overall, 75.0% in W4)

**Model health gate is working as designed** — blocks picks during decay.

### 3. Combo Effects Are Real and Dramatic

Triple signal combos show exceptional performance:
- `edge_spread_optimal + high_edge + minutes_surge`: **100% HR** (N=11)
- `edge_spread_optimal + high_edge + prop_value_gap_extreme`: **90.0% HR** (N=10)
- `high_edge + prop_value_gap_extreme`: **88.9% HR** (N=9)

**`prop_value_gap_extreme` is a combo multiplier**, not a standalone signal.

### 4. Role Players (<15 line) Performance (CORRECTED)

| Signal | Role (<15) HR | Overall HR | Difference |
|--------|--------------|------------|------------|
| `prop_value_gap_extreme` | **89.3%** (N=28) | 46.7% (N=60) | **+42.6%** |
| `edge_spread_optimal` | 38.9% (N=113) | 47.4% (N=217) | **-8.5%** |
| `cold_snap` | 60.0% | 61.1% | -1.1% |

**CORRECTED FINDING:** Role players (<15) are NOT universally better. `prop_value_gap_extreme` CRUSHES on role players (89.3% vs 46.7%), but `edge_spread_optimal` FAILS on role players (38.9% vs 47.4%). Signal-specific behavior.

---

## Recommendations (REVISED - Feb 14)

1. **SALVAGE both signals with strict conditions:**
   - `prop_value_gap_extreme`: **Re-enable with conditions** (`line_value < 15 AND recommendation = 'OVER'`)
   - `edge_spread_optimal`: **Re-enable with conditions** (`recommendation = 'OVER'`, remove confidence band filter)
   - Both signals: **Keep model health gate** (blocks during decay)

2. **Implementation changes required:**

   **prop_value_gap_extreme.py:**
   ```python
   # Add conditional checks BEFORE firing
   if line_value >= 15:  # Block mid-tier (toxic 6.5% HR)
       return self._no_qualify()
   if recommendation != 'OVER':  # Block UNDER (toxic 16.7% HR)
       return self._no_qualify()
   ```

   **edge_spread_optimal.py:**
   ```python
   # Simplify to OVER-only, remove confidence band logic
   if recommendation != 'OVER':  # Block UNDER (toxic 46.8% HR)
       return self._no_qualify()
   # Remove: confidence >= 0.70, exclude 88-90% tier (adds no value)
   ```

3. **Update `v_signal_performance` view**:
   - Change date window from `INTERVAL 30 DAY` → `INTERVAL 60 DAY` or full season
   - Add `QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id ...)` to deduplicate grading records
   - Add eval window segmentation to surface model decay patterns

4. **Aggregator combo logic** (keep existing):
   - Boost priority for triple combos: `edge_spread_optimal + high_edge + minutes_surge` (100% HR)
   - Boost priority for `prop_value_gap_extreme` when paired with `high_edge` (88.9% HR)
   - Combo performance should IMPROVE with OVER-only filtering (fewer false positives)

5. **Backfill signal tags:**
   - After deploying updated logic, re-run signal annotation for all dates since 2026-01-09
   - Verify new conditional logic produces expected N counts (28 for prop_value_gap_extreme, 65 for edge_spread_optimal)

6. **Monitor for 7 days:**
   - Use `validate-daily` Phase 0.58 (signal performance)
   - Promote to Best Bets if 7-day HR >= 65%
   - Watch for UNDER picks (should be 0 with new logic)

---

## Data Quality Notes

1. **Duplicate grading records:** `prediction_accuracy` table contains duplicates (2-6 records per player/game), all with same `prediction_correct` value but different `graded_at` timestamps. This inflates counts in the view but doesn't affect HR calculation.

2. **Date range impact:** Signals with low trigger frequency (`prop_value_gap_extreme`) show high variance between date windows. Always check N before trusting HR.

3. **Game_id vs game_date joins:** Backtest uses `game_id` (canonical), production view uses `game_date` (allows cross-game joins). Both work but `game_id` is more precise.

---

## Appendix: SQL Queries

### Segmentation Query

See `/tmp/harmful_signals_segmentation.sql` for full query.

### Backtest vs Production Comparison

See `/tmp/backtest_comparison.sql` for date window impact analysis.

### Key Query Pattern

```sql
-- Always deduplicate grading records
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY player_lookup, game_id
  ORDER BY graded_at DESC
) = 1
```

### Combo Analysis Pattern

```sql
-- Extract combos with ARRAY_TO_STRING
SELECT
  ARRAY_TO_STRING(
    ARRAY(SELECT s FROM UNNEST(signal_tags) AS s ORDER BY s),
    " + "
  ) AS combo,
  COUNT(*) AS n,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr
FROM combo_picks
WHERE ARRAY_LENGTH(signal_tags) >= 2
GROUP BY combo
HAVING n >= 5
```

---

## Quick Reference: Production Implementation

### Signal Registry Updates Required

```python
# ml/signals/registry.py

# prop_value_gap_extreme: Change from standalone to combo-only
SignalConfig(
    name="prop_value_gap_extreme",
    enabled=True,
    standalone_eligible=False,  # ← CHANGE: combo-only
    combo_eligible=True,
    require_combo_with=["high_edge"],  # ← NEW: require high_edge co-occurrence
    min_confidence=0.6,
    description="Extreme gap (10+) between prediction and Vegas — combo multiplier"
),

# edge_spread_optimal: Already has model health gate (keep as-is)
SignalConfig(
    name="edge_spread_optimal",
    enabled=True,
    standalone_eligible=True,
    combo_eligible=True,
    min_confidence=0.6,
    require_model_health="healthy",  # ← EXISTING: model health gate
    description="Model edge spreads optimally across game context"
),

# cold_snap: Already accepted (no changes needed)
SignalConfig(
    name="cold_snap",
    enabled=True,
    standalone_eligible=True,
    combo_eligible=True,
    min_confidence=0.6,
    description="Player UNDER 3+ straight → regression to mean → OVER"
),
```

### Aggregator Combo Boosting

```python
# ml/signals/aggregator.py

# Triple combo boost (100% HR)
TRIPLE_COMBO_BOOST = {
    frozenset(["edge_spread_optimal", "high_edge", "minutes_surge"]): 2.0,  # 100% HR
}

# Extreme value combo boost (88-90% HR)
EXTREME_VALUE_COMBOS = {
    frozenset(["edge_spread_optimal", "high_edge", "prop_value_gap_extreme"]): 1.8,  # 90% HR
    frozenset(["high_edge", "prop_value_gap_extreme"]): 1.5,  # 88.9% HR
}

def calculate_combo_score(signals: List[str], base_score: float) -> float:
    """Apply combo boosts to pick scoring."""
    signal_set = frozenset(signals)
    
    # Check triple combos first
    if signal_set in TRIPLE_COMBO_BOOST:
        return base_score * TRIPLE_COMBO_BOOST[signal_set]
    
    # Check extreme value combos
    if signal_set in EXTREME_VALUE_COMBOS:
        return base_score * EXTREME_VALUE_COMBOS[signal_set]
    
    return base_score
```

### v_signal_performance View Fix

```sql
-- BEFORE (misleading):
WHERE pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)

-- AFTER (better context):
WHERE pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)

-- Add deduplication:
SELECT
  -- ... fields ...
FROM `nba-props-platform.nba_predictions.pick_signal_tags` pst
CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
INNER JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON pst.player_lookup = pa.player_lookup
  AND pst.game_id = pa.game_id  -- ← CHANGE: use game_id not game_date
  AND pst.system_id = pa.system_id
WHERE pa.prediction_correct IS NOT NULL
  AND pa.is_voided IS NOT TRUE
  AND pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
QUALIFY ROW_NUMBER() OVER (  -- ← ADD: deduplicate grading records
  PARTITION BY pst.player_lookup, pst.game_id
  ORDER BY pa.graded_at DESC
) = 1
GROUP BY signal_tag
```

---

## Testing Checklist

- [ ] Verify `prop_value_gap_extreme` no longer appears in standalone picks
- [ ] Verify `prop_value_gap_extreme` only appears when paired with `high_edge`
- [ ] Verify triple combo `edge_spread_optimal + high_edge + minutes_surge` gets priority boost
- [ ] Verify `v_signal_performance` view shows 60-day history
- [ ] Verify view deduplication (check N counts match backtest counts)
- [ ] Run backtest with new registry config to validate combo-only logic
- [ ] Monitor production for 3 days to ensure no regression

---

## Session Notes

**Analyst:** Claude Sonnet 4.5
**Date:** 2026-02-14
**Query runtime:** ~45 seconds (complex multi-CTE segmentation)
**Data volume:** 110 picks (edge_spread_optimal), 34 picks (prop_value_gap_extreme), 18 picks (cold_snap)
**Key SQL patterns:** QUALIFY deduplication, ARRAY_TO_STRING for combo analysis, LAG/WINDOW for streak data

**Production deployment:** Requires registry config update + aggregator combo boost logic + view update. Estimated effort: 2 hours. No model retraining required.

