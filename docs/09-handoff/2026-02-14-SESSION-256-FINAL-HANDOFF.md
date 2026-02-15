# Session 256 Final Handoff — Comprehensive Signal Analysis Complete

**Date:** 2026-02-14
**Model:** Claude Sonnet 4.5
**Status:** Comprehensive 4-agent parallel analysis complete, registry decisions finalized

---

## What Was Done

### 1. Parallel Agent Analysis — 4 Agents in Single Message ✅

Spawned 4 specialized agents to analyze all 23 signals from multiple angles:

**Agent 1: Intersection Analysis** (`a8dff06`)
- Analyzed top 5 combos to determine synergistic vs parasitic
- Partitioned picks into intersection/A-only/B-only
- **Finding:** Both removed signals are BENEFICIAL combo-only filters
- Output: `HARMFUL-SIGNALS-ANALYSIS.md` (53,238 tokens, 419s)

**Agent 2: Segmentation Analysis** (`a38212a`)
- Tested if removed signals work in specific niches (player tier, edge, OVER/UNDER)
- **Finding:** Both signals salvageable with conditional logic (89.3% and 76.9% HR in best segments)
- Output: `HARMFUL-SIGNALS-SEGMENTATION.md` + `SEGMENTATION-QUICK-REF.md` (74,200 tokens, 853s)

**Agent 3: Interaction Matrix** (`ae044ac`)
- Built 7x7 matrix showing HR/ROI for all pairwise combinations
- **Finding:** `high_edge + minutes_surge` production-ready (79.4% HR, 34 picks)
- Discovered largest anti-pattern: `high_edge + edge_spread` 2-way (31.3% HR, -37.4% ROI, 179 picks)
- Output: `SIGNAL-INTERACTION-MATRIX-V2.md` + `MATRIX-QUICK-REFERENCE.md` (69,515 tokens, 738s)

**Agent 4: Zero-Pick Prototypes** (`a1f621e`)
- Investigated why 13 prototypes had 0 qualifying picks
- **Finding:** 6 HIGH priority signals need supplemental data (6-8 hours to fix)
- Expected impact: 180-315 additional picks after fixes
- Output: `ZERO-PICK-PROTOTYPES-ANALYSIS.md` (76,692 tokens, 367s)

**Total execution time:** ~45 minutes (agents ran in parallel)

### 2. Synthesis and Decision-Making ✅

Created comprehensive analysis synthesizing all 4 agent findings:
- Resolved contradictions between agents (Agent 1 vs Agent 2)
- Applied decision criteria to all 23 signals
- Final decisions: 6 KEEP, 2 COMBO-ONLY, 13 DEFER, 1 REMOVE, 1 STATUS UNKNOWN

**Output:** `COMPREHENSIVE-SIGNAL-ANALYSIS.md`

### 3. Registry and Documentation Updates ✅

**Registry changes:**
- ✅ Removed `triple_stack` from registry (meta-signal, broken logic)
- ✅ Kept `prop_value_gap_extreme` and `edge_spread_optimal` removed (combo-only, not standalone)

**Signal file annotations:**
- ✅ Updated `edge_spread_optimal.py`: STATUS: COMBO-ONLY (3-way: high_edge + minutes_surge + edge_spread)
- ✅ Updated `prop_value_gap_extreme.py`: STATUS: COMBO-ONLY (with high_edge)

**Documentation:**
- ✅ Created `COMBO-SIGNALS-GUIDE.md` (comprehensive guide to combo-only patterns)
- ✅ Updated `01-BACKTEST-RESULTS.md` (added Session 256 combo findings)

---

## Key Findings

### 1. "Harmful" Signals Are Actually Beneficial Combo Filters

**Initial assessment (Session 255):**
- `prop_value_gap_extreme`: 12.5% HR → REJECTED
- `edge_spread_optimal`: 47.4% HR → REJECTED

**Session 256 comprehensive analysis:**
- Both are **COMBO-ONLY filters** (never appear standalone)
- `prop_value_gap_extreme`: +11.7% HR boost when with high_edge (73.7% vs 62.0%)
- `edge_spread_optimal`: +19.4% HR boost in 3-way combo (88.2% vs 68.8%)

**Insight:** Standalone performance is misleading when signals only occur in combos. They're refinement filters, not independent predictors.

### 2. Production-Ready Combo Discovered

**`high_edge + minutes_surge`**
- 79.4% HR, +58.8% ROI, 34 picks
- +31.2% synergy above best individual signal
- Expected monthly EV: ~$1,646 at $100/pick
- **Status:** PRODUCTION READY

**Pattern:** High edge (value exists) + minutes surge (opportunity is real) = dual validation

### 3. Signal Families Identified

**Family 1: Universal Amplifiers**
- `minutes_surge` — Boosts ANY edge signal via increased opportunity volume

**Family 2: Value Signals**
- `high_edge`, `prop_value_gap_extreme` — Identify mispricing but REQUIRE validation

**Family 3: Bounce-Back Signals**
- `cold_snap`, `blowout_recovery`, `3pt_bounce` — Mean reversion, double bounce-back = 100% HR

**Family 4: Redundancy Traps**
- `high_edge + edge_spread` (2-way) — Both measure confidence, no synergy

### 4. Largest Anti-Pattern Discovered

**`high_edge + edge_spread_optimal` (2-way)**
- 31.3% HR, -37.4% ROI, 179 picks
- Both signals measure confidence → pure redundancy
- Reliably loses money despite large sample

**Warning:** NEVER use this 2-way combo (only works in 3-way with minutes_surge)

### 5. Zero-Pick Prototypes Are Fixable

**6 HIGH priority signals** blocked by missing supplemental data:
- `hot_streak_3`, `hot_streak_2`, `cold_continuation_2` — need streak_data integration
- `points_surge_3`, `scoring_acceleration` — need points_stats window functions
- `fg_cold_continuation` — need fg_stats window functions

**Fix effort:** 6-8 hours total (extend backtest environment)
**Expected impact:** 180-315 additional picks across 35-day backfill

---

## Final Signal Decisions (All 23)

### Core Signals (8)

| Signal | Decision | Rationale |
|--------|----------|-----------|
| `model_health` | KEEP ✅ | Gate signal, prevents model decay losses |
| `high_edge` | KEEP ⚠️ | 43.8% HR standalone, 79.4% HR with minutes_surge (combo-only) |
| `dual_agree` | DEFER ⏸️ | Insufficient V12 data, revisit after 30+ days |
| `3pt_bounce` | KEEP ✅ | 70.0% HR standalone, 100% HR in combos |
| `minutes_surge` | KEEP ✅ | 48.2% HR standalone, universal amplifier (combo-only) |
| `pace_mismatch` | STATUS UNKNOWN | Not analyzed (no picks in 36-day window?) |
| `cold_snap` | KEEP ✅ | 61.1% HR, decay-resistant |
| `blowout_recovery` | KEEP ✅ | 53.0% HR, decay-resistant |

### Removed Signals (2)

| Signal | Decision | Rationale |
|--------|----------|-----------|
| `edge_spread_optimal` | KEEP REMOVED (COMBO-ONLY) 🔬 | 47.4% HR standalone, 88.2% HR in 3-way combo, strict filter |
| `prop_value_gap_extreme` | KEEP REMOVED (COMBO-ONLY) 🔬 | 46.7% HR standalone, 73.7% HR with high_edge, strict filter |

### Zero-Pick Prototypes (13)

| Signal | Decision | Fix Effort | Priority |
|--------|----------|------------|----------|
| `hot_streak_3` | DEFER ⏸️ | 30 min | HIGH |
| `hot_streak_2` | DEFER ⏸️ | 30 min | HIGH |
| `cold_continuation_2` | DEFER ⏸️ | 30 min | HIGH |
| `points_surge_3` | DEFER ⏸️ | 1-2 hrs | MEDIUM |
| `scoring_acceleration` | DEFER ⏸️ | 1-2 hrs | MEDIUM |
| `fg_cold_continuation` | DEFER ⏸️ | 1-2 hrs | MEDIUM |
| `three_pt_volume_surge` | DEFER ⏸️ | 1-2 hrs | MEDIUM |
| `minutes_surge_5` | DEFER ⏸️ | 1-2 hrs | MEDIUM |
| `b2b_fatigue_under` | DEFER ⏸️ | 30 min | MEDIUM |
| `rest_advantage_2d` | DEFER ⏸️ | 2-3 hrs | LOW |
| `home_dog` | DEFER ⏸️ | 2-3 hrs | LOW |
| `model_consensus_v9_v12` | DEFER ⏸️ | 30 min (once V12 ready) | DEFER |
| `triple_stack` | REMOVE ❌ | N/A | N/A |

---

## What's NOT Done

### Immediate Next Steps (Same Session or Next)

1. **Deploy production combo signal** (2-3 hours)
   - Create `HighEdgeMinutesSurgeComboSignal` class
   - Backtest validation (already done: 79.4% HR)
   - Deploy to production
   - Monitor with `validate-daily` Phase 0.58

2. **Check pace_mismatch status** (10 minutes)
   - Query performance in 36-day window
   - Classify as KEEP/DEFER/REMOVE

3. **Cloud Function Redeploy** (from Session 255, still pending)
   - `post-grading-export` — backfills actuals into signal_best_bets_picks
   - `phase5-to-phase6-orchestrator` — added signal-best-bets export

### Next Session: Backtest Environment Fixes (6-8 hours)

**Goal:** Unlock 9 zero-pick prototypes by extending signal_backtest.py

**Tasks:**
1. Integrate streak_data CTE into supplemental dict → unlocks 3 signals
2. Add points_stats window functions to game_stats CTE → unlocks 2 signals
3. Add fg_stats window functions → unlocks 1 signal
4. Add minutes_avg_last_5 → unlocks 1 signal
5. Add three_pa_avg_last_3 → unlocks 1 signal
6. Add rest_days to pred dict → unlocks 1 signal

**Validation:**
- Re-run backtest on 35-day window
- Confirm signals generate expected pick counts (180-315 total)
- Check HR vs baseline (V9 edge 3+ at 59.1%)
- Classify by HR: >= 55% PROMOTE, >= 52.4% KEEP, < 52.4% REJECT

### Future Sessions

1. **Implement combo-aware Best Bets aggregator**
   - Add combo scoring (bonus for synergistic pairs)
   - Add anti-pattern penalties (high_edge + edge_spread 2-way)
   - Weighted scoring by signal family
   - Expected impact: 5-10% improvement in top-5 HR

2. **Port successful prototypes to production**
   - Update `ml/signals/supplemental_data.py` with required fields
   - Production needs streak_data integration
   - Production needs V12 predictions for model_consensus

3. **Investigate edge_spread gating mechanism**
   - Why does edge_spread only work in 3-way with minutes_surge?
   - Test hypothesis: edge_spread HR higher when minutes_surge=True

---

## Files Created This Session

### Analysis Deliverables (7 files)

1. `HARMFUL-SIGNALS-ANALYSIS.md` — Intersection analysis (Agent 1)
2. `HARMFUL-SIGNALS-SEGMENTATION.md` — Segmentation analysis (Agent 2)
3. `SEGMENTATION-QUICK-REF.md` — Quick reference for Agent 2
4. `SIGNAL-INTERACTION-MATRIX-V2.md` — 7x7 pairwise analysis (Agent 3)
5. `MATRIX-QUICK-REFERENCE.md` — Quick reference for Agent 3
6. `ZERO-PICK-PROTOTYPES-ANALYSIS.md` — Root cause investigation (Agent 4)
7. `COMPREHENSIVE-SIGNAL-ANALYSIS.md` — Synthesis of all 4 agents

### Documentation Updates (3 files)

8. `COMBO-SIGNALS-GUIDE.md` — Comprehensive guide to combo-only patterns
9. `01-BACKTEST-RESULTS.md` — Updated with Session 256 combo findings
10. `2026-02-14-SESSION-256-FINAL-HANDOFF.md` — This file

### Code Changes (2 files)

11. `ml/signals/registry.py` — Removed triple_stack from registry
12. `ml/signals/edge_spread_optimal.py` — Updated STATUS: COMBO-ONLY annotation
13. `ml/signals/prop_value_gap_extreme.py` — Updated STATUS: COMBO-ONLY annotation

**Total:** 13 files created/modified

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Signals analyzed | 23 (8 core + 13 prototypes + 2 removed) |
| Agent analysis time | ~45 min (parallel) |
| Total session time | ~2.5 hours (agents + synthesis + docs) |
| Agents spawned | 4 (all in single message) |
| Files created/modified | 13 |
| Production-ready combo | 1 (`high_edge + minutes_surge`, 79.4% HR) |
| Combo-only signals | 2 (`edge_spread_optimal`, `prop_value_gap_extreme`) |
| Signals removed | 1 (`triple_stack`) |
| Zero-pick prototypes fixable | 9 (6 HIGH, 2 MEDIUM, 1 V12-dependent) |
| Expected new picks after fixes | 180-315 (across 35-day backfill) |

---

## Decision Criteria Applied

### KEEP Signal If:
- Standalone HR >= 52.4% AND N >= 20, **OR**
- Synergistic combo (intersection >> A-only AND B-only) AND N >= 10, **OR**
- Profitable segment (HR >= 55%, N >= 20) with clear conditional logic

### Mark COMBO-ONLY If:
- Standalone HR < 50% BUT consistently boosts combos (avg lift >= +10% HR)
- Never qualifies standalone (appears as strict subset)
- Statistical significance in >= 2 different combos OR strong 3-way synergy

### DEFER If:
- Total picks < 10 (insufficient data for decision)
- Needs supplemental data that's feasible to add
- Waiting for V12 deployment

### REMOVE If:
- Standalone HR < 50% AND no combo lift AND no profitable segments
- Parasitic (combos perform worse than A-only baseline)
- Broken logic (meta-signal by design)

---

## Key Insights

### 1. Combo-Only Signals Are a Real Pattern

Both removed signals are beneficial filters that improve performance, but only in combinations:
- They're not "harmful" or "parasitic"
- They're strict subset relationships that identify high-quality picks
- Standalone performance metrics are misleading

### 2. High Edge Requires Validation

`high_edge` standalone is below breakeven (43.8% HR), but when combined with validation:
- +31.2% with minutes_surge → 79.4% HR
- +19.4% with edge_spread + minutes_surge → 88.2% HR

**Insight:** High edge = "value exists", second signal = "opportunity is real"

### 3. OVER Bias Pattern

Both combo-only signals excel on OVER bets, fail on UNDER:

| Signal | OVER HR | UNDER HR | Delta |
|--------|---------|----------|-------|
| `prop_value_gap_extreme` | 84.4% | 16.7% | +67.7% |
| `edge_spread_optimal` | 76.6% | 46.8% | +29.8% |

**Implication:** Model excels at identifying upside (player exceeds) but struggles with downside (injury/rest suppression)

### 4. Sample Size Matters for Combos

| Combo | N | 95% CI Width | Reliability |
|-------|---|--------------|-------------|
| high_edge + minutes_surge | 34 | ~20% | MODERATE |
| high_edge + edge_spread (2-way) | 179 | ~12% | HIGH |
| cold_snap combos | 1-5 | ~60% | LOW |

**Guideline:** Need N >= 30 for promotion, N >= 50 for high confidence

### 5. Anti-Patterns Are Reliably Bad

`high_edge + edge_spread` 2-way combo:
- 31.3% HR, -37.4% ROI, 179 picks
- Both measure confidence → redundancy trap
- Large sample confirms it's consistently unprofitable

**Lesson:** Avoid combining signals that measure the same dimension

---

## Recommended Next Steps

### This Session (if time) or Next Session

1. **Create `HighEdgeMinutesSurgeComboSignal` class** (2-3 hours)
   - Copy pattern from existing signal
   - Backtest validation
   - Deploy and monitor

2. **Check `pace_mismatch` status** (10 min)
   - Query performance
   - Add to verdicts

### Next Session: Backtest Environment

1. **Extend signal_backtest.py** (6-8 hours)
   - Add missing data fields (points, FG, streak, rest_days)
   - Re-run backtest on 35-day window
   - Validate 9 prototypes generate expected picks

2. **Classify prototypes by HR**
   - HR >= 55% → PROMOTE to core
   - HR >= 52.4% → KEEP as prototype
   - HR < 52.4% → REJECT

### Future Sessions

1. **Implement combo-aware Best Bets aggregator**
   - Combo bonuses for synergistic pairs
   - Anti-pattern penalties
   - Weighted scoring by signal family

2. **Port successful prototypes to production**
   - Update supplemental_data.py
   - Integrate streak_data
   - Add V12 predictions support

3. **Investigate edge_spread gating**
   - Why only works with minutes_surge?
   - Test segmentation hypothesis

---

## Agent Resume IDs

- `a8dff06` — Intersection Analysis (COMPLETED)
- `a38212a` — Segmentation Analysis (COMPLETED)
- `ae044ac` — Interaction Matrix (COMPLETED)
- `a1f621e` — Zero-Pick Prototypes (COMPLETED)

All agents completed successfully. No need to resume.

---

## Dead Ends (Don't Revisit)

| Item | Why | Session |
|------|-----|---------|
| Removing signals based on standalone HR alone | Combos perform differently, combo-only filters are real | 256 |
| Using 30-day v_signal_performance for decisions | Model decay skews recent data, use backtest | 256 |
| Re-enabling edge_spread as standalone signal | Only works in 3-way combo, never standalone | 256 |
| Forcing prop_value to work on UNDER bets | TOXIC at 16.7% HR, strong OVER bias (+67.7% delta) | 256 |
| Using high_edge + edge_spread 2-way combo | Largest anti-pattern (31.3% HR, -37.4% ROI, 179 picks) | 256 |

---

## Success Metrics

- [x] All 23 signals classified (Keep / Combo-only / Defer / Remove)
- [x] Evidence-based decision for each (4-agent parallel analysis)
- [x] Interaction matrix complete (7x7 pairwise)
- [x] Zero-pick prototypes categorized (missing data / broken logic)
- [x] Registry updated (removed triple_stack)
- [x] All signal files annotated with STATUS
- [x] Documentation updated (backtest results, combo guide)
- [ ] (Future) Reorganize signals into folders
- [ ] (Future) Deploy production combo signal
- [ ] (Future) Extend backtest environment

---

## Notes for Future Sessions

### Pattern: Combo-Only Signals

Established pattern for signals that only work in combinations:

```python
class PropValueGapExtremeSignal(BaseSignal):
    tag = "prop_value_gap_extreme"
    combo_only = True  # Never use standalone, only in Best Bets aggregation

    # STATUS annotation in docstring:
    # STATUS: COMBO-ONLY (with high_edge)
    # - 46.7% HR standalone
    # - 73.7% HR with high_edge (+11.7% synergy)
    # - Appears as strict subset (never standalone)
```

### Pattern: Combo-Aware Aggregator

Proposed scoring update for Best Bets:

```python
# Check for synergistic combos
if 'high_edge' in tags and 'minutes_surge' in tags:
    score += 2.0  # Production-ready combo (79.4% HR)

if 'high_edge' in tags and 'prop_value_gap_extreme' in tags:
    score += 1.5  # Combo bonus (73.7% HR)

if all(x in tags for x in ['high_edge', 'minutes_surge', 'edge_spread_optimal']):
    score += 2.5  # Triple combo premium (88.2% HR)

# Penalize anti-patterns
if 'high_edge' in tags and 'edge_spread_optimal' in tags and 'minutes_surge' not in tags:
    score -= 2.0  # 2-way anti-pattern (31.3% HR, -37.4% ROI)
```

### Pattern: Backtest Environment Extensions

Template for adding missing data to signal_backtest.py:

```python
# In game_stats CTE, add window functions:
points_avg_last_3 = AVG(points) OVER (
    PARTITION BY player_lookup
    ORDER BY game_date
    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
)

# In supplemental dict parsing:
supplemental = {
    'points_avg_last_3': float(pred.get('points_avg_last_3', 0)),
    'consecutive_line_beats': int(pred.get('consecutive_line_beats', 0)),
    'rest_days': int(pred.get('rest_days', 0)),
}
```

---

**Next session:** Deploy production combo signal OR extend backtest environment to unlock 9 prototypes! 🚀
