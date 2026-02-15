# New Session Prompt - Signal Combination Analysis

**Copy this into a fresh Claude Code session to run comprehensive signal analysis with parallel agents.**

---

## Context

Read these files first (in order):

1. `docs/09-handoff/2026-02-14-SESSION-255-HANDOFF.md` — Latest session handoff
2. `docs/08-projects/current/signal-discovery-framework/01-BACKTEST-RESULTS.md` — Backtest results
3. `docs/08-projects/current/signal-discovery-framework/COMBO-MECHANICS-ANALYSIS.md` — **YOUR ROADMAP**
4. `docs/08-projects/current/signal-discovery-framework/PERFORMANCE-VIEW-VALIDATION.md` — View validation

---

## What Happened in Session 256

Started cleaning signal registry (23 signals total). Initial standalone analysis showed:

| Signal | Standalone HR | ROI | Verdict |
|--------|--------------|-----|---------|
| `prop_value_gap_extreme` | **12.5%** | **-76.1%** | ❌ Catastrophic |
| `edge_spread_optimal` | **47.4%** | **-9.4%** | ❌ Losing |

**BUT** combos are EXCELLENT:

| Combo | HR | ROI |
|-------|----|----|
| `high_edge + prop_value_gap_extreme` | **88.9%** | **+69.7%** |
| `high_edge + minutes_surge + edge_spread_optimal` | **100%** | **+90.9%** |
| `3pt_bounce + blowout_recovery` | **100%** | **+90.9%** |

**Question:** Synergistic signals or riding coattails?

We removed both from registry but may restore if synergistic.

---

## Your Mission

Run **4 agents in PARALLEL** for comprehensive combo analysis.

**DO NOT remove more signals until analysis complete.**

---

## Agent 1: Intersection Analysis ⚡ CRITICAL

**File:** `docs/08-projects/current/signal-discovery-framework/HARMFUL-SIGNALS-ANALYSIS.md`

**Task:** Partition picks for top 5 combos into intersection, A-only, B-only.

**Combos:**
1. `high_edge + prop_value_gap_extreme` (9 picks, 88.9%)
2. `high_edge + minutes_surge + edge_spread_optimal` (11 picks, 100%)
3. `high_edge + minutes_surge` (12 picks, 75%)
4. `3pt_bounce + blowout_recovery` (7 picks, 100%)
5. `cold_snap + blowout_recovery` (10 picks, 70%)

**Decision logic:**
- Intersection >> A-only AND >> B-only → SYNERGISTIC (keep both)
- Intersection ≈ A-only → PARASITIC (B riding A, remove B)
- B-only = 0 → FILTER (combo-only signal)

**Query template:**
```sql
WITH tagged_picks AS (
  SELECT pst.signal_tags, pa.prediction_correct
  FROM nba_predictions.pick_signal_tags pst
  JOIN nba_predictions.prediction_accuracy pa
    ON pa.player_lookup = pst.player_lookup
    AND pa.game_id = pst.game_id
    AND pa.system_id = pst.system_id
  WHERE pst.game_date >= '2026-01-09'
    AND pa.prediction_correct IS NOT NULL
)
SELECT
  CASE
    WHEN 'A' IN UNNEST(signal_tags) AND 'B' IN UNNEST(signal_tags) THEN 'Intersection'
    WHEN 'A' IN UNNEST(signal_tags) THEN 'A only'
    WHEN 'B' IN UNNEST(signal_tags) THEN 'B only'
  END as partition,
  COUNT(*) as picks,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM tagged_picks
WHERE 'A' IN UNNEST(signal_tags) OR 'B' IN UNNEST(signal_tags)
GROUP BY 1
```

**Deliverable:** Intersection table for each combo + recommendation (restore or keep removed)

---

## Agent 2: Segmentation Analysis ⚡ CRITICAL

**File:** `docs/08-projects/current/signal-discovery-framework/HARMFUL-SIGNALS-SEGMENTATION.md`

**Task:** Test if removed signals work in specific niches.

**Signals:** `prop_value_gap_extreme`, `edge_spread_optimal`

**Segments:**
- Player tier: Stars (25+), Mid (15-25), Role (<15)
- Minutes: Heavy (32+), Starter (25-32), Bench (<25)
- Edge: Small (<4), Medium (4-6), Large (6+)
- Recommendation: OVER vs UNDER

**Decision:** If ANY segment HR >= 55% with N >= 20 → salvageable. Else discard.

**Deliverable:** Segmentation tables + salvage recommendation

---

## Agent 3: Signal Interaction Matrix 📊

**File:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INTERACTION-MATRIX.md`

**Task:** Build 7x7 interaction matrix for all signals with picks.

**Signals:** `high_edge`, `minutes_surge`, `3pt_bounce`, `blowout_recovery`, `cold_snap`, `edge_spread_optimal`, `prop_value_gap_extreme`

**Deliverable:**
- Full 7x7 matrix (HR, ROI, N for each pair)
- Diagonal = standalone, off-diagonal = combo
- Top 10 synergistic pairs
- Redundant pairs

---

## Agent 4: Zero-Pick Prototypes 🔍

**File:** `docs/08-projects/current/signal-discovery-framework/ZERO-PICK-PROTOTYPES-ANALYSIS.md`

**Task:** Why did 13 prototypes have 0 picks?

**Prototypes:**
Batch 1: `hot_streak_3`, `cold_continuation_2`, `b2b_fatigue_under`, `rest_advantage_2d`
Batch 2: `hot_streak_2`, `points_surge_3`, `home_dog`, `minutes_surge_5`, `three_pt_volume_surge`, `model_consensus_v9_v12`, `fg_cold_continuation`, `triple_stack`, `scoring_acceleration`

**For each:**
1. Read code in `ml/signals/{name}.py`
2. Identify required data
3. Check if data in `supplemental_data.py`
4. Categorize: MISSING_DATA | TOO_RESTRICTIVE | BROKEN_LOGIC

**Deliverable:** Table + count by category

---

## Decision Criteria

**KEEP if:**
- Standalone HR >= 52.4%, N >= 20, OR
- Synergistic combo (intersection >> A-only AND B-only), N >= 10, OR
- Profitable segment (HR >= 55%, N >= 20)

**COMBO-ONLY if:**
- Standalone < 50% BUT boosts combos (+10% lift)
- B-only = 0 picks
- Significant in >= 2 combos

**DEFER if:**
- Picks < 10 (insufficient data)
- Needs feasible supplemental data

**REMOVE if:**
- Standalone < 50% AND no combo lift AND no segments
- Parasitic (combo < A-only)

---

## After Agents Complete

1. Review all deliverables
2. Apply decision criteria
3. Update registry (restore if synergistic, remove if parasitic)
4. Annotate files (STATUS: COMBO_ONLY / REJECTED / NEEDS_DATA)
5. Update docs
6. Create handoff

---

## Success Criteria

✅ All 23 signals classified
✅ Evidence-based decisions
✅ Interaction matrix complete
✅ Prototypes categorized
✅ Registry updated
✅ Decisions documented

---

**Run all 4 agents in PARALLEL (single message with 4 Task calls)!** 🚀
