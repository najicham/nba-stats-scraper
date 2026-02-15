# Signal Analysis Testing Coverage — Gaps and Recommendations

**Date:** 2026-02-14
**Session:** 256
**Status:** Initial analysis complete, significant gaps identified

---

## Executive Summary

**What we tested:** Top 5 combos, 21 pairwise combinations (7 signals), 4 basic segments
**What we DIDN'T test:** 99%+ of possible combinations, most temporal/contextual filters
**Confidence level:** MODERATE for tested combos, LOW for untested segments
**Recommendation:** Strategic additional testing (not exhaustive) based on hypothesis strength

---

## What We Actually Tested

### 1. Combination Testing ✅ Partial Coverage

**Tested:**
- Top 5 performing combos from initial backtest (intersection analysis)
- 21 pairwise combinations for 7 signals with picks (7x7 matrix)
- Some 3-way combos mentioned in top 5

**Coverage:**
- 7 signals out of 23 total (30% of signals)
- ~26 combinations tested out of possible combinations
- 2-way combos: 21 tested (for 7 signals only)
- 3-way combos: ~3 tested
- 4-way+ combos: 0 tested

**Gaps:**
- 16 signals not in combination matrix (the zero-pick prototypes + dual_agree + pace_mismatch)
- Systematic 3-way combo testing (7 choose 3 = 35 combos, we tested ~3)
- Systematic 4-way combo testing (7 choose 4 = 35 combos, tested 0)
- 5-way+ combos (210+ combinations, tested 0)

**Total possible combinations for 7 signals:** 2^7 - 1 = 127 combinations
**Actually tested:** ~26 combinations (~20% coverage)

### 2. Segmentation Testing ✅ Minimal Coverage

**Tested (4 segments):**
- Player tier (by line value: <15, 15-25, 25+)
- Edge magnitude (<3, 3-5, 5+)
- Prediction direction (OVER vs UNDER)
- Minutes tier (implied in some analysis)

**Coverage:** 4 out of 50+ possible segments (~8% coverage)

**Gaps (46+ segments NOT tested):**

#### Temporal Segments
- ❌ Early season (Oct-Nov) vs mid (Dec-Jan) vs late (Feb-Mar) vs playoff push (Mar-Apr)
- ❌ Pre vs post All-Star break
- ❌ Month of season (performance drift over time)
- ❌ Day of week (Tuesday games vs Sunday games)
- ❌ Time since model training (fresh model vs 30+ days stale)

#### Game Context Segments
- ❌ Home vs away
- ❌ Back-to-back games vs rested
- ❌ Days of rest (0, 1, 2, 3+)
- ❌ Blowout (15+ margin) vs close games (<5 margin)
- ❌ National TV games vs regular games
- ❌ Divisional games vs conference vs cross-conference
- ❌ Second night of back-to-back vs first night
- ❌ Third game in 4 nights (fatigue)
- ❌ After overtime game (fatigue)

#### Team Context Segments
- ❌ Team strength (top 10 vs middle vs bottom 10 by record)
- ❌ Opponent strength
- ❌ Team pace (top 10 pace vs bottom 10)
- ❌ Team offensive rating (top vs bottom)
- ❌ Team defensive rating
- ❌ Team on win streak vs loss streak
- ❌ Conference (East vs West)
- ❌ Home team favored vs underdog
- ❌ Spread size (<3 vs 3-7 vs 7+)

#### Player Context Segments
- ❌ Player position (Guard vs Forward vs Center)
- ❌ Player age (<25 vs 25-30 vs 30+)
- ❌ Player usage rate (high vs medium vs low)
- ❌ Starter vs bench player
- ❌ Player minutes trend (increasing vs decreasing vs stable)
- ❌ Player points trend (hot vs cold streak)
- ❌ Injury status (recent return vs healthy vs DTD)
- ❌ Player trade impact (new team vs established)

#### Market Context Segments
- ❌ Line movement (sharp money vs public money)
- ❌ Opening line vs closing line
- ❌ Consensus vs contrarian plays
- ❌ Line value (common number like 20.5 vs uncommon like 18.7)
- ❌ Sportsbook (FanDuel vs DraftKings vs consensus)
- ❌ Market efficiency (widely available line vs niche)

#### Prop Type Segments
- ❌ Points vs rebounds vs assists (different prop types)
- ❌ Combo props (pts+reb+ast) vs single stat
- ❌ Alternative lines (player over 25.5 vs 20.5)

### 3. Signal Testing ✅ Partial Coverage

**Tested:**
- 7 signals with qualifying picks (interaction matrix)
- 2 removed signals (comprehensive analysis)
- 13 zero-pick prototypes (root cause only, not performance)

**Coverage:** 9 out of 23 signals tested for performance (~39%)

**Gaps:**
- `dual_agree` not tested (mentioned as insufficient V12 data)
- `pace_mismatch` not tested (possibly 0 picks?)
- 13 prototypes not tested for performance (just root cause investigation)

---

## Statistical Rigor Assessment

### Sample Sizes

**Tested combinations with adequate sample (N >= 30):**
- `high_edge + minutes_surge`: 34 picks ✅ ADEQUATE
- `high_edge + edge_spread` (2-way): 179 picks ✅ HIGHLY ADEQUATE
- `blowout_recovery` standalone: 100 picks ✅ HIGHLY ADEQUATE

**Tested combinations with small sample (N < 30):**
- `high_edge + prop_value_gap_extreme`: 38 picks ⚠️ MARGINAL
- `edge_spread + high_edge + minutes_surge` (3-way): 17 picks ⚠️ SMALL
- `3pt_bounce + blowout_recovery`: 2 picks ❌ TOO SMALL
- `cold_snap + blowout_recovery`: 3 picks ❌ TOO SMALL
- `minutes_surge + cold_snap`: 5 picks ❌ TOO SMALL

**Guideline:**
- N >= 50: High confidence
- N = 30-50: Moderate confidence
- N = 15-30: Low confidence (wide confidence intervals)
- N < 15: Too unreliable for production

**Current confidence:**
- High confidence: 2 combos
- Moderate confidence: 2 combos
- Low confidence: 1 combo
- Too unreliable: 3 combos

### Temporal Coverage

**Date range tested:** 2026-01-09 to 2026-02-14 (36 days)

**Coverage issues:**
- Single evaluation window (no cross-validation across seasons)
- Doesn't cover early season (Oct-Dec)
- Doesn't cover playoff push (March-April)
- Model decay period (champion 35+ days stale during W4)
- Only 36 days = ~36 game dates = ~180-200 total games

**Recommendation:** Test across multiple 30-day windows:
- W1: Oct 22 - Nov 20 (early season, fresh model)
- W2: Nov 21 - Dec 20 (model aging)
- W3: Dec 21 - Jan 20 (mid-season)
- W4: Jan 21 - Feb 20 (model stale, current analysis)
- W5: Feb 21 - Mar 20 (late season)

### Multiple Comparisons Problem

**Issue:** Testing 26 combinations means ~1-2 will appear significant by chance (5% false positive rate).

**Mitigation:**
- Bonferroni correction: p < 0.05/26 = p < 0.0019 (very strict)
- Benjamini-Hochberg: Control false discovery rate at 5%
- Use Wilson score confidence intervals (already doing this)

**Current approach:** Using large effect sizes (+10% HR minimum) reduces false positives, but still no formal multiple comparison correction.

---

## Priority Additional Testing

### Tier 1: CRITICAL (High Impact, Low Effort) — 2-3 hours

These tests could invalidate or strengthen current decisions:

**1. Temporal Robustness (1 hour)**
```sql
-- Test top 3 combos across 5 evaluation windows
-- Check if performance holds in early/mid/late season
SELECT
  CASE
    WHEN game_date BETWEEN '2025-10-22' AND '2025-11-20' THEN 'W1_Early'
    WHEN game_date BETWEEN '2025-11-21' AND '2025-12-20' THEN 'W2_Model_Aging'
    WHEN game_date BETWEEN '2025-12-21' AND '2026-01-20' THEN 'W3_Mid'
    WHEN game_date BETWEEN '2026-01-21' AND '2026-02-20' THEN 'W4_Stale'
  END as window,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combo_picks
WHERE combo IN ('high_edge+minutes_surge', 'high_edge+prop_value', '3way')
GROUP BY 1
```

**Expected:** If HR drops >10% in any window → combo is unstable

**2. Home vs Away Split (30 min)**
```sql
-- Test if combos work better home or away
SELECT
  is_home_team,
  combo,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combo_picks
JOIN nba_reference.nba_schedule USING (game_id)
GROUP BY 1, 2
HAVING COUNT(*) >= 10
```

**Expected:** If HR delta >15% → add home/away filter

**3. Model Staleness Test (30 min)**
```sql
-- Test if combos hold when model is fresh vs stale
SELECT
  DATE_DIFF(game_date, '2026-01-08', DAY) as days_since_training,
  CASE
    WHEN DATE_DIFF(game_date, '2026-01-08', DAY) <= 7 THEN 'Fresh (<7d)'
    WHEN DATE_DIFF(game_date, '2026-01-08', DAY) <= 21 THEN 'Aging (7-21d)'
    ELSE 'Stale (21+d)'
  END as model_age,
  combo,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combo_picks
WHERE game_date >= '2026-01-09'
GROUP BY 1, 2, 3
```

**Expected:** If stale model HR drops >10% → model_health gate is critical

**4. Position Split (30 min)**
```sql
-- Test if combos work for all positions or specific ones
SELECT
  player_position,
  combo,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combo_picks
JOIN nba_reference.player_info USING (player_name)
GROUP BY 1, 2
HAVING COUNT(*) >= 10
```

**Expected:** If guards dominate → add position filter

### Tier 2: IMPORTANT (Medium Impact, Medium Effort) — 4-6 hours

**5. Systematic 3-Way Combo Testing (3-4 hours)**

Test all 35 possible 3-way combinations for the 7 signals:

```python
from itertools import combinations

signals = ['high_edge', 'minutes_surge', '3pt_bounce', 'blowout_recovery',
           'cold_snap', 'edge_spread_optimal', 'prop_value_gap_extreme']

for combo in combinations(signals, 3):
    # Query performance
    # Track N, HR, ROI
    # Identify synergistic 3-way patterns
```

**Expected findings:**
- 3-5 strong 3-way combos (HR >= 70%, N >= 15)
- Identify which signals are "universal connectors" (appear in most strong combos)

**6. Back-to-Back and Rest Analysis (1-2 hours)**

```sql
SELECT
  rest_days,
  combo,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combo_picks
JOIN player_game_summary USING (player_lookup, game_date)
GROUP BY 1, 2
HAVING COUNT(*) >= 10
```

**Expected:** If B2B (rest_days=0) has HR delta >15% → critical filter

**7. Team Strength Split (1 hour)**

```sql
WITH team_strength AS (
  SELECT team_tricode,
    PERCENT_RANK() OVER (ORDER BY win_pct) as strength_pct
  FROM team_standings
)
SELECT
  CASE
    WHEN strength_pct >= 0.7 THEN 'Top Teams'
    WHEN strength_pct >= 0.3 THEN 'Middle Teams'
    ELSE 'Bottom Teams'
  END as team_tier,
  combo,
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM combo_picks
JOIN team_strength ON team_tricode = player_team
GROUP BY 1, 2
```

**Expected:** If top teams significantly different → add team_tier filter

### Tier 3: NICE-TO-HAVE (Low Impact, High Effort) — 8-12 hours

**8. All Pairwise Combos for All 23 Signals (4-6 hours)**

Extend 7x7 matrix to 23x23 matrix:
- 253 pairwise combinations (23 choose 2)
- Most will have N < 10 (insufficient data)
- But might discover hidden gems

**9. Prop Type Analysis (2-3 hours)**

Test if combos work for all prop types or specific ones:
- Points props
- Rebounds props
- Assists props
- 3-pointers props
- Blocks/steals props

**10. Sportsbook Line Analysis (1-2 hours)**

Test if combos work better with certain sportsbooks:
- FanDuel lines
- DraftKings lines
- Consensus lines
- Sharp vs public lines

**11. Market Efficiency Test (2-3 hours)**

Test if combos exploit inefficiencies in:
- Widely bet markets (efficient)
- Niche markets (inefficient)
- Alternative lines (less efficient)

---

## Recommended Testing Strategy

### Don't Test Everything (Diminishing Returns)

**Why not exhaustive testing:**
1. **Combinatorial explosion:** 23 signals = 8,388,607 possible combinations
2. **Sample size problem:** Most combos will have N < 10 (unreliable)
3. **Overfitting risk:** With 8M combos, you'll find 400K that are "significant" by chance (5% false positive)
4. **Time cost:** 8M combinations at 10 seconds each = 277 days of compute

**Smart approach: Hypothesis-driven testing**
- Test high-impact segments first (Tier 1)
- Test based on domain knowledge (home/away, rest, position)
- Test when combo has adequate sample size (N >= 30)
- Stop when additional tests don't change decisions

### Proposed Testing Plan

**Phase 1: Validate Current Decisions (2-3 hours, THIS SESSION)**
- Temporal robustness (5 windows)
- Home vs away
- Model staleness
- Position split

**Phase 2: Expand Combo Discovery (4-6 hours, NEXT SESSION)**
- Systematic 3-way combos for 7 signals
- Rest/B2B analysis
- Team strength split

**Phase 3: Production Monitoring (ONGOING)**
- Track deployed combo performance daily
- A/B test variations (e.g., "high_edge+minutes_surge on home games only")
- Iterate based on real-world results

**Phase 4: Deep Dives (AS NEEDED)**
- If Tier 1/2 tests reveal promising patterns, drill deeper
- If production monitoring shows drift, investigate root cause
- If new signals added, test interactions with existing combos

---

## Confidence Levels by Decision

### HIGH CONFIDENCE (>80%)

**Decisions we're confident in:**
- ✅ `high_edge + edge_spread` 2-way is anti-pattern (179 picks, large sample)
- ✅ `blowout_recovery` is profitable standalone (100 picks)
- ✅ `triple_stack` should be removed (meta-signal, broken logic)
- ✅ Combo-only signals are a real pattern (strict subset relationships observed)

### MODERATE CONFIDENCE (50-80%)

**Decisions that could change with more data:**
- ⚠️ `high_edge + minutes_surge` production-ready (34 picks, needs temporal validation)
- ⚠️ `prop_value_gap_extreme` combo-only (38 picks, marginal sample)
- ⚠️ OVER bias pattern (could be sample artifact, needs cross-validation)

### LOW CONFIDENCE (<50%)

**Decisions that are speculative:**
- ❌ All 100% HR combos with N < 10 (cold_snap combos, 3pt_bounce combos)
- ❌ 3-way combo (edge+high+minutes) at 88.2% HR (N=17, small sample)
- ❌ Signal family classifications (needs validation across more combos)
- ❌ Zero-pick prototype verdicts (not tested for performance yet)

---

## What Should We Test Now?

### Immediate Action: Tier 1 Tests (2-3 hours)

**Validate top combo across multiple dimensions:**

1. **Temporal robustness** (high_edge + minutes_surge across 5 windows)
2. **Home/away split** (is it better at home or away?)
3. **Model staleness** (does it hold when model is fresh vs stale?)
4. **Position split** (guards vs forwards vs centers?)

**Output:** If any test shows >15% HR drop in a segment → add conditional filter

### Document Current Gaps

Create testing roadmap:
- What we tested (26 combos, 4 segments)
- What we didn't test (46+ segments, 100+ combos)
- What we recommend testing (Tier 1-3 priorities)
- When to stop testing (decision doesn't change)

---

## Stopping Criteria

**When to stop testing:**
1. **Decision doesn't change:** Additional tests don't affect KEEP/REMOVE/COMBO-ONLY verdict
2. **Insufficient sample:** Segment has N < 10 (unreliable)
3. **Low prior probability:** Hypothesis is weak (e.g., "does it work better on Tuesdays?")
4. **Production monitoring ready:** Can test in production with A/B test instead

**When to keep testing:**
1. **Decision on the fence:** HR near 52.4% breakeven, additional tests could swing it
2. **Large effect observed:** >15% HR difference in preliminary test
3. **High stakes:** Production deployment of combo with $1,000+ monthly EV
4. **Cheap to test:** Query takes <5 min, might reveal important pattern

---

## Recommendation

**For this session (document goal):**
- ✅ Run Tier 1 tests (2-3 hours) to validate top combo
- ✅ Document all gaps and confidence levels
- ✅ Create testing roadmap for future sessions
- ❌ Don't try to test everything (diminishing returns)

**Specific action:**
1. Run 4 Tier 1 queries (temporal, home/away, staleness, position)
2. Update COMPREHENSIVE-SIGNAL-ANALYSIS.md with confidence levels
3. Create TESTING-ROADMAP.md with Tier 2-3 plans
4. Add caveats to combo recommendations ("validated on 36-day window, needs cross-validation")

**Output:** Honest assessment of what we know (moderate confidence) vs what we're guessing (low confidence).

Would you like me to run the Tier 1 validation tests now?
