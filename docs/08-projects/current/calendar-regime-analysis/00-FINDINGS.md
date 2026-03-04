# Calendar Regime Analysis — Session 395 Findings

**Date:** 2026-03-03
**Status:** Research complete, implementation pending
**Scope:** Why models degrade during trade deadline / All-Star break, what patterns exist, and what to do about it

## Executive Summary

The **Jan 30 → Feb 25 toxic window** causes a 10-15pp HR drop across all models. The root cause is the model systematically under-predicting during this period (residual doubles from +1.5 to +2.7 pts) while actual player scoring remains unchanged. This creates a flood of false UNDER signals.

The pattern is **structural and repeatable** — it also appears in the 2024-25 season at a smaller magnitude (2-4pp dip). The 2025-26 amplification is compounded by model staleness and `usage_spike_score` drift (1.14→0.28).

## Key Calendar Dates (2025-26)

| Event | Date(s) |
|-------|---------|
| Trade Deadline | February 6, 2026 (3 PM ET) |
| All-Star Weekend | February 13-15, 2026 (Los Angeles) |
| Last game before ASB | February 12 |
| Games resume after ASB | February 19 |
| Toxic window | Jan 30 → Feb 25 (~27 days) |
| Recovery begins | Feb 26+ (64.9% HR) |

## Root Cause: Model Under-Prediction Bias

**Actual points barely change between regimes:**
- Bench: 7.2 normal vs 7.5 toxic (+0.3)
- Role: 11.8 vs 11.8 (identical)
- Star: 27.1 vs 27.2 (+0.1)
- Starter: 18.4 vs 18.7 (+0.3)

**The model predicts lower, but reality doesn't change:**
- Bench residual: +1.5 normal → +2.5 toxic
- Role residual: +1.8 → +2.7
- Star residual: +1.5 → +2.4
- Starter residual: +1.0 → +2.3

**Why?** As rotations stabilize post-trade-deadline and post-ASB, `usage_spike_score` collapses (Session 370 found it explains 47% of Dec-Jan vs Feb drift with AUC=0.99). The model reads this as bearish, predicts lower, but players score the same.

## Regime-Level Prediction Accuracy (Edge 3+)

### 2025-26 Season (Raw Predictions)

| Regime | N | HR% | OVER HR% | UNDER HR% |
|--------|---|-----|----------|-----------|
| Normal (all other dates) | 6,004 | **62.2** | 63.5 | 61.6 |
| Pre-trade deadline (Jan 30-Feb 5) | 1,016 | **46.6** | 57.6 | 43.1 |
| Trade deadline day (Feb 6) | 111 | **43.2** | 33.3 | 50.0 |
| Post-deadline → ASB (Feb 7-12) | 772 | **49.1** | 45.9 | 50.3 |
| Post-ASB week (Feb 19-25) | 906 | **50.7** | 48.4 | 51.4 |

### 2024-25 Season (Cross-Validation)

| Regime | N | HR% | vs Normal Delta |
|--------|---|-----|----------------|
| Normal | 10,233 | 66.5 | baseline |
| Pre-deadline (Jan 30-Feb 6) | 1,215 | 62.1 | -4.4pp |
| Post-deadline (Feb 7-12) | 1,148 | 63.6 | -2.9pp |
| Post-ASB (Feb 20-26) | 759 | 65.7 | -0.8pp |

**Pattern holds across seasons but magnitude varies.** 2024-25 had 2-4pp dips vs 2025-26's 10-15pp crash. The difference is likely model staleness compounding the structural effect.

### Recovery Timeline (2025-26)

| Period | N | HR% |
|--------|---|-----|
| Pre-toxic (before Jan 30) | 5,813 | 62.1 |
| Trade deadline zone (Jan 30-Feb 12) | 1,899 | 47.4 |
| First 3 days post-ASB (Feb 19-21) | 212 | 52.4 |
| 4-7 days post-ASB (Feb 22-25) | 694 | 50.1 |
| **8+ days post-ASB (Feb 26+)** | **191** | **64.9** |

Recovery takes ~8 days post-ASB in 2025-26. In 2024-25, recovery was faster (~4 days).

## Tier x Direction Impact (Normal → Toxic)

| Combo | Normal HR | Toxic HR | Delta | N (toxic) | Verdict |
|-------|-----------|----------|-------|-----------|---------|
| Star OVER | 61.8% | 33.3% | **-28.5pp** | 33 | **Block during toxic** |
| Bench UNDER | 65.5% | 46.3% | -19.2pp | 270 | Below breakeven |
| Role UNDER | 59.0% | 41.8% | -17.2pp | 777 | Highest-volume loser |
| Star UNDER | 64.8% | 49.5% | -15.2pp | 313 | Below breakeven |
| Role OVER | 63.9% | 49.4% | -14.5pp | 348 | Below breakeven |
| Starter OVER | 59.4% | 47.2% | -12.2pp | 195 | Below breakeven |
| Bench OVER | 69.7% | **58.8%** | -10.9pp | 136 | **Still profitable** |
| Starter UNDER | 61.7% | **54.4%** | -7.3pp | 733 | **Still profitable** |

**Only 2 of 8 combos survive the toxic window:** Bench OVER and Starter UNDER.

## Best Bets Filter Stack Impact

The filter stack already absorbs much of the damage:

| Scenario | Picks | HR% | P&L |
|----------|-------|-----|-----|
| All picks (with toxic) | 118 | 66.9 | +32.81 |
| Normal only (block toxic) | 77 | 70.1 | +26.09 |
| Toxic window picks only | 41 | 65.9 | **+6.72** |

**Toxic window best bets picks are still profitable** (65.9%, +6.72 units). A blanket block would sacrifice profit. The filter stack is working — it just can't fully compensate at the raw prediction level.

### Best Bets by Regime

| Regime | Picks | HR% | P&L |
|--------|-------|-----|-----|
| Normal | 77 | 70.1 | +26.09 |
| Pre-deadline | 11 | 63.6 | +2.36 |
| Post-deadline → ASB | 18 | 55.6 | +1.09 |
| Post-ASB | 12 | 66.7 | +3.27 |

## Additional Pattern Discoveries

### Day of Week (Edge 3+)

| Day | OVER HR% | OVER N | UNDER HR% | UNDER N |
|-----|----------|--------|-----------|---------|
| Monday | **70.2** | 315 | 59.3 | 700 |
| Saturday | **67.1** | 362 | 57.6 | 755 |
| Thursday | **64.3** | 401 | 56.6 | 816 |
| Sunday | 55.8 | 484 | 57.0 | 1,217 |
| Tuesday | 56.9 | 327 | 52.7 | 792 |
| Friday | 53.5 | 387 | 57.3 | 1,063 |
| Wednesday | **53.3** | 353 | 58.5 | 837 |

OVER varies 16.9pp by day (Monday 70.2% vs Wednesday 53.3%). UNDER is stable (6.6pp spread). Lighter slate days (Monday, Saturday) favor OVER.

### Slate Size (Edge 3+)

| Slate | OVER HR% | OVER N | UNDER HR% | UNDER N |
|-------|----------|--------|-----------|---------|
| Light (1-3 games) | 56.1 | 107 | **67.7** | 266 |
| Medium (4-6) | 59.1 | 653 | 56.2 | 1,402 |
| Heavy (7-9) | 58.9 | 1,072 | 58.2 | 2,505 |
| Mega (10+) | 62.2 | 797 | 54.6 | 2,007 |

Clear inverse for UNDER: fewer games = better HR (67.7% light → 54.6% mega).

### Home/Away x Regime (Edge 3+)

| Regime | Home/Away | OVER HR | UNDER HR | UNDER N |
|--------|-----------|---------|----------|---------|
| Normal | HOME | 63.3% | 63.4% | 1,779 |
| Normal | AWAY | 63.8% | 60.2% | 2,308 |
| Toxic | HOME | 47.9% | 52.3% | 904 |
| Toxic | AWAY | 53.3% | **44.7%** | 1,189 |

AWAY UNDER is the worst toxic combo at 44.7% (N=1,189).

### Back-to-Back (Edge 3+)

| Rest Status | OVER HR% | OVER N | UNDER HR% | UNDER N |
|-------------|----------|--------|-----------|---------|
| B2B | **63.4** | 112 | **63.6** | 198 |
| Rested | 59.4 | 2,473 | 56.6 | 5,857 |

B2B predictions are BETTER than rested (+4-7pp). The `b2b_fatigue_under` signal was disabled (Session 373) based on Feb performance, but overall B2B is a positive signal. Lines may overadjust for fatigue.

### Edge Compression During Toxic Window

| Regime | Avg Edge | Std Edge | Avg MAE |
|--------|----------|----------|---------|
| Normal | 5.85 | 3.48 | 6.16 |
| Toxic | 4.63 | **1.72** | 6.62 |

Edge std halves — the model loses ability to differentiate high vs low confidence picks. Produces uniform mediocre-confidence predictions.

### Implied Team Total Drop

| Regime | Avg Implied Team Total |
|--------|-----------------------|
| Normal | 115.9 |
| Toxic | 113.6 (-2.3 pts) |

Vegas expects less scoring during the toxic window. If models are calibrated on a higher-scoring environment, OVER predictions overshoot.

### Weekly MAE and HR Trend

| Week | N | MAE | Avg Edge | HR% |
|------|---|-----|----------|-----|
| Dec 21 | 340 | **4.82** | 6.43 | **79.1** |
| Dec 28 | 376 | 4.90 | 5.83 | 74.7 |
| Jan 4 | 990 | 6.15 | 5.76 | 59.8 |
| Jan 11 | 890 | 6.89 | 5.25 | 50.0 |
| Jan 18 | 614 | 5.62 | 5.01 | 60.1 |
| Jan 25 | 492 | 6.09 | 5.01 | 57.7 |
| Feb 1 | 1,316 | **7.26** | 4.92 | **46.8** |
| Feb 8 | 424 | 6.01 | 4.33 | 46.7 |
| Feb 15* | 212 | 6.13 | 4.14 | 52.4 |
| Feb 22 | 819 | 5.79 | 4.33 | 52.3 |
| Mar 1 | 66 | **4.81** | 3.92 | **66.7** |

*Feb 15 week = post-ASB only (Feb 19-21). Edge has been steadily declining all season (7.39 → 3.92).

## Catastrophic Days (HR < 40%, Edge 3+)

| Date | N | HR% | OVER HR% | UNDER HR% | Context |
|------|---|-----|----------|-----------|---------|
| Jan 27 | 50 | 30.0 | 14.3 | 41.4 | Pre-deadline ramp |
| Feb 2 | 137 | 30.7 | 58.3 | **28.0** | Full toxic |
| Feb 10 | 38 | 26.3 | 61.5 | **8.0** | Post-deadline |
| Feb 20 | 76 | 38.2 | 18.8 | 43.3 | First full day post-ASB |
| Feb 25 | 94 | 38.3 | 57.1 | **35.0** | End of toxic window |

UNDER is the primary damage vector on catastrophic days. OVER can sometimes hold (Feb 2 OVER 58.3%, Feb 10 OVER 61.5%).

## Recommendations

### Immediate (Filter-Level)

These are implementable as aggregator filters now:

1. **Block Star OVER during toxic window** — 33.3% HR, -28.5pp delta. Tiny volume (N=33), massive losses. This is the clearest single filter.

2. **Raise UNDER edge floor during toxic** — e.g., require edge 5+ instead of 3+ when in toxic regime. Role UNDER at edge 3-5 is where the biggest volume of losses occurs.

3. **Consider allowing only Bench OVER and Starter UNDER during toxic** — the only 2 of 8 tier x direction combos that stay above breakeven.

### Medium-Term (Tooling)

4. **Build `bin/regime_analyzer.py`** — Standardized tool that:
   - Detects current calendar regime (normal, pre-deadline, post-deadline, post-ASB, recovery)
   - Reports current tier x direction HR vs historical norms
   - Flags edge compression (std_edge drop)
   - Integrates with daily steering report
   - Takes configurable calendar dates (trade deadline, ASB start/end)

5. **Build analysis template library** in `bin/analysis/`:
   - `tier_direction_regime.sql` — tier x direction x regime breakdown
   - `day_of_week.sql` — day of week patterns
   - `slate_size.sql` — slate size effects
   - `b2b_patterns.sql` — back-to-back patterns
   - `feature_drift.sql` — feature value shifts by regime

### Deferred (Needs More Data)

6. **Calendar regime feature for model training** — Only ~2 trade deadlines and ~2 ASBs per training window. The model can't learn from this. Would need multi-season training data. **Not recommended as a training feature until we have 3+ seasons.**

7. **Day-of-week signal** — Monday OVER 70.2% vs Wednesday OVER 53.3% is a 16.9pp spread. Needs cross-season validation before implementing.

8. **B2B signal re-evaluation** — B2B predictions are +4-7pp better than rested. The disabled `b2b_fatigue_under` signal was evaluated only on Feb data (39.5% HR). Full-period B2B is 63.6%. Needs careful re-analysis separating the toxic window effect.

9. **Slate size signal** — Light slate UNDER 67.7% vs mega 54.6%. Interesting but small N for light slates (N=266). Needs more data.

## Key Insight for Next Session

**The model's February degradation is NOT random — it's a predictable, calendar-driven regime change where the model under-predicts by ~1 point while actual scoring is unchanged.** The fix is NOT a better model (all models have this problem). The fix is either:
- **Calendar-aware filters** that block the worst-performing tier x direction combos during the toxic window
- **Faster retraining** that includes toxic-window data so the model recalibrates (but this requires data from the toxic window itself — a chicken-and-egg problem)
- **A fundamentally different model architecture** that doesn't rely on features that drift mid-season (e.g., usage_spike_score)

## Files Referenced

- `ml/signals/aggregator.py` — where filters live
- `bin/simulate_best_bets.py` — for testing filter changes
- `shared/config/calendar_regime.py` — does not exist yet, proposed
- `bin/regime_analyzer.py` — does not exist yet, proposed
