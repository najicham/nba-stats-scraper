# Session 256 Handoff — Signal Cleanup Investigation

**Date:** 2026-02-14
**Model:** Claude Sonnet 4.5
**Status:** Investigation complete, comprehensive analysis plan ready for fresh session

---

## What Was Done

### 1. Signal Registry Cleanup - Started but PAUSED

Began cleaning up 23 signals in registry (8 core + 15 prototypes). Initial standalone performance query showed:

| Signal | Picks | HR | ROI | Initial Verdict |
|--------|-------|----|----|-----------------|
| `3pt_bounce` | 16 | 62.5% | +19.3% | ✅ Keep |
| `cold_snap` | 18 | 61.1% | +16.7% | ✅ Keep |
| `blowout_recovery` | 97 | 54.6% | +4.3% | ✅ Keep |
| `minutes_surge` | 181 | 53.0% | +1.3% | ⚠️ Marginal |
| `high_edge` | 120 | 50.8% | -3.0% | ⚠️ Decayed |
| `edge_spread_optimal` | 78 | **47.4%** | **-9.4%** | ❌ Remove |
| `prop_value_gap_extreme` | 8 | **12.5%** | **-76.1%** | ❌ Remove |

Removed `prop_value_gap_extreme` and `edge_spread_optimal` from registry and marked files as STATUS: REJECTED.

### 2. Critical Discovery - Harmful Signals Excel in Combos

Before finalizing removals, queried signal combinations and found **stunning results**:

| Combo | Picks | HR | ROI | vs Best Individual |
|-------|-------|----|----|-------------------|
| `high_edge + minutes_surge + edge_spread_optimal` | 11 | **100%** | **+90.9%** | +37.5% |
| `high_edge + prop_value_gap_extreme` | 9 | **88.9%** | **+69.7%** | +26.4% |
| `3pt_bounce + blowout_recovery` | 7 | **100%** | **+90.9%** | +37.5% |
| `high_edge + minutes_surge` | 12 | **75.0%** | **+43.2%** | +12.5% |
| `cold_snap + blowout_recovery` | 10 | **70.0%** | **+33.6%** | +8.9% |

**The two "removed" signals perform BEST in combinations!**

This raises critical question: Are they synergistic (adding predictive value) or parasitic (riding high_edge's coattails)?

### 3. Investigation Halt - Need Comprehensive Analysis

**PAUSED registry cleanup** pending deep analysis of:
- Intersection mechanics (do combos outperform A-only and B-only?)
- Segmentation (do "harmful" signals work in specific player/edge niches?)
- Signal interactions (full 7x7 matrix showing all pairwise effects)
- Zero-pick prototypes (why 13 signals had 0 qualifying picks)

### 4. Comprehensive Analysis Plan Created

Created detailed roadmap docs:
- `COMBO-MECHANICS-ANALYSIS.md` - Full analysis plan with agent tasks
- `SIGNAL-CLEANUP-ANALYSIS-PLAN.md` - Detailed methodology and decision criteria
- `NEW-SESSION-SIGNAL-ANALYSIS-PROMPT.md` - Ready-to-copy prompt for fresh session
- `PERFORMANCE-VIEW-VALIDATION.md` - Explains v_signal_performance discrepancies (completed by Agent ab9fee6)

### 5. v_signal_performance Validation Completed

Agent validated the view is correct. Discrepancies were due to:
- Comparing 30-day rolling (production) vs fixed windows (backtest)
- Model decay affecting recent performance
- Different date ranges

**Recommendation:** Use backtest results for keep/remove decisions, not 30-day view.

---

## What's NOT Done

### Comprehensive Signal Analysis (READY TO RUN)

**Next session should:**
1. Start fresh chat (clean context)
2. Copy `NEW-SESSION-SIGNAL-ANALYSIS-PROMPT.md` as starting prompt
3. Spawn 4 agents in PARALLEL:
   - Agent 1: Intersection analysis (synergistic vs parasitic)
   - Agent 2: Segmentation analysis (profitable niches)
   - Agent 3: Signal interaction matrix (7x7 pairwise)
   - Agent 4: Zero-pick prototypes (why 0 picks?)

**Expected time:** 90-120 min total (45-90 min agents in parallel, 30-45 min review/updates)

### Registry Updates Pending Analysis Results

Potential outcomes:
- **Restore** `prop_value_gap_extreme` and `edge_spread_optimal` if synergistic
- **Mark as COMBO_ONLY** if they only work in combinations
- **Keep removed** if parasitic (riding coattails)
- **Classify** 13 zero-pick prototypes (missing data vs broken logic)
- **Update** supplemental_data.py if prototypes need feasible data

### Cloud Function Redeploy (from Session 255)

Still pending (not blocking):
- `post-grading-export` - backfills actuals into signal_best_bets_picks
- `phase5-to-phase6-orchestrator` - added signal-best-bets export

---

## Key Numbers (Current State)

| Metric | Value |
|--------|-------|
| Registry signals | 21 (was 23, removed 2) |
| Signals with picks | 7 |
| Zero-pick prototypes | 13 |
| Best Bets overall HR (30d) | 67.8% (80/118) |
| Removed signals | 2 (may restore) |

---

## Files Changed This Session

### Modified
| File | Change |
|------|--------|
| `ml/signals/registry.py` | Removed PropValueGapExtremeSignal, EdgeSpreadOptimalSignal |
| `ml/signals/prop_value_gap_extreme.py` | Added STATUS: REJECTED header |
| `ml/signals/edge_spread_optimal.py` | Added STATUS: REJECTED header |
| `docs/09-handoff/2026-02-14-SESSION-255-HANDOFF.md` | Updated "What's NOT Done" section |

### Created
| File | Purpose |
|------|---------|
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-CLEANUP-ANALYSIS-PLAN.md` | Detailed analysis plan |
| `docs/08-projects/current/signal-discovery-framework/COMBO-MECHANICS-ANALYSIS.md` | Comprehensive roadmap for combo analysis |
| `docs/08-projects/current/signal-discovery-framework/PERFORMANCE-VIEW-VALIDATION.md` | View validation (Agent ab9fee6) |
| `NEW-SESSION-SIGNAL-ANALYSIS-PROMPT.md` | Ready-to-copy prompt for fresh session |

---

## Decision Criteria for Next Session

### KEEP Signal If:
- Standalone HR >= 52.4% AND N >= 20, **OR**
- Synergistic combo (intersection >> A-only AND B-only) AND N >= 10, **OR**
- Profitable segment (HR >= 55%, N >= 20) with clear conditional logic

### Mark COMBO-ONLY If:
- Standalone HR < 50% BUT consistently boosts combos (avg lift >= +10% HR)
- Never qualifies standalone (B-only = 0 picks)
- Statistical significance in >= 2 different combos

### DEFER If:
- Total picks < 10 (insufficient data for decision)
- Needs supplemental data that's feasible to add

### REMOVE If:
- Standalone HR < 50% AND no combo lift AND no profitable segments
- Parasitic (combos perform worse than A-only baseline)
- Requires infeasible data (external APIs, etc.)

---

## Key Insights

### 1. Standalone Performance is Misleading
Signals that are catastrophic alone (12.5% HR) can be stellar in combos (88.9% HR). Need intersection analysis to determine if value is real or illusory.

### 2. Sample Size Matters
Many combos have N < 20. Must use binomial confidence intervals to avoid false positives.

### 3. Model Decay Affects Recent Performance
30-day rolling view shows `high_edge` at 50.8% (decayed), but backtest avg is 66.7% (healthy model). Use backtest for decisions.

### 4. Zero-Pick Prototypes Likely Missing Data
13 prototypes had 0 picks during 35-day backfill. Likely causes:
- Missing supplemental data (player_tier, is_home, FG% stats)
- Overly restrictive thresholds
- Broken logic

Need systematic investigation before discarding.

### 5. Combo Diversity vs Performance Trade-off
Some prototypes might not qualify many picks but could add diversity to Best Bets list. Balance performance with variety.

---

## Recommended Next Steps

1. **Start fresh session** with `NEW-SESSION-SIGNAL-ANALYSIS-PROMPT.md`
2. **Run 4 agents in parallel** (single message with 4 Task calls)
3. **Review agent deliverables** (4 markdown docs in signal-discovery-framework/)
4. **Apply decision criteria** to each signal
5. **Update registry** based on evidence
6. **Annotate signal files** with STATUS tags
7. **Update backtest results doc** with final verdicts
8. **Create Session 257 handoff** with final registry state
9. **(Optional)** Reorganize signals into folders: active/, combo_only/, prototypes/, rejected/

---

## Critical Questions for Next Session

1. **Are `prop_value_gap_extreme` and `edge_spread_optimal` synergistic or parasitic?**
   - If synergistic → restore to registry (possibly as COMBO_ONLY)
   - If parasitic → keep removed

2. **Which zero-pick prototypes are salvageable?**
   - Missing data → add to supplemental_data.py and defer
   - Too restrictive → tune thresholds and re-test
   - Broken logic → remove permanently

3. **Should we implement combo-only signals differently?**
   - Option A: `combo_only: bool` attribute
   - Option B: Separate combo-specific signals (e.g., `high_edge_strict`)
   - Option C: Weight combos higher in aggregator scoring

4. **How to organize rejected/untested signals?**
   - Current: all in `ml/signals/` with STATUS annotations
   - Alternative: separate folders (active/, rejected/, prototypes/)

---

## Agent Resume IDs

- `ab9fee6` - v_signal_performance validation (COMPLETED)

---

## Notes for Future Sessions

### Pattern: Combo-Only Signals

If analysis confirms signals that only work in combos, establish pattern:
```python
class PropValueGapExtremeSignal(BaseSignal):
    tag = "prop_value_gap_extreme"
    combo_only = True  # Never use standalone, only in Best Bets aggregation

    def __init__(self):
        super().__init__(min_sample_size=0)  # Don't require standalone picks
```

### Pattern: Conditional Signals

If segmentation finds profitable niches:
```python
class PropValueGapStarsSignal(BaseSignal):
    tag = "prop_value_gap_stars"

    def evaluate(self, prediction: Dict, supplemental: Dict) -> SignalResult:
        if supplemental.get('player_tier') != 'STAR':
            return SignalResult.no_qualify("Not a star player")
        # ... rest of logic
```

### Missing Supplemental Data to Add

Based on prototype signal requirements (pending Agent 4 investigation):
- `player_tier` (STAR/MID/ROLE from season averages)
- `is_home` (boolean, from schedule)
- `fg_pct_last_3` (rolling 3-game FG%)
- `team_record` (W-L record, calculate SRS if needed)
- `pace_differential` (team pace vs opponent pace)

---

## Dead Ends (Don't Revisit)

| Item | Why | Session |
|------|-----|---------|
| Removing signals based on standalone HR alone | Combos perform differently | 256 |
| Using 30-day v_signal_performance for decisions | Model decay skews recent data | 256 |

---

## Success Metrics for Next Session

- [ ] All 23 signals classified (Keep / Combo-only / Defer / Remove)
- [ ] Evidence-based decision for each (not intuition)
- [ ] Interaction matrix complete (7x7 pairwise)
- [ ] Zero-pick prototypes categorized (missing data / broken logic)
- [ ] Registry updated with final decisions
- [ ] All signal files annotated with STATUS
- [ ] Documentation updated (backtest results, architecture)
- [ ] (Stretch) Reorganize signals into folders
- [ ] (Stretch) Re-run backfill if supplemental data added

---

**Next session:** Copy `NEW-SESSION-SIGNAL-ANALYSIS-PROMPT.md` and run parallel agent analysis! 🚀
