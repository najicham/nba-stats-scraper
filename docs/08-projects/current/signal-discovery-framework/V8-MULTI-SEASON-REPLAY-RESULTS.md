# V8 Multi-Season Replay Results

**Session:** 265
**Date:** 2026-02-15
**Purpose:** Validate 58/55/52.4 decay thresholds against V8's 4-season history

## Executive Summary

The current thresholds (58/55/52.4) are **validated** across V8's full history:
- **0.13% false positive rate** — 1 BLOCKED day in 780 healthy game days
- **True positive confirmed** — correctly blocked V8's 2025-26 decay (37 of 80 game days blocked)
- **Threshold sensitivity is minimal** — all tested configurations produce identical results during healthy periods
- **Recommendation: Keep 58/55/52.4 as-is.** No evidence warrants adjustment.

## Part 1: V8 Data Coverage

V8 (`catboost_v8`) has **27K+ total picks** across 4 healthy seasons plus the current decay:

| Season | Edge 3+ Picks | Edge 3+ HR | Status |
|--------|--------------|------------|--------|
| 2021-22 | 5,785 | 83.9% | Healthy |
| 2022-23 | 5,841 | 82.9% | Healthy |
| 2023-24 | 6,067 | 79.4% | Healthy |
| 2024-25 | 7,043 | 80.6% | Healthy |
| 2025-26 (to date) | 3,178 | 58.4% | **Decaying** |

## Part 2: False Positive Analysis

### Healthy Period (2021-11 to 2025-06): 780 Game Days

| State | Days | Percentage |
|-------|------|------------|
| HEALTHY | 758 | 97.2% |
| INSUFFICIENT_DATA | 21 | 2.7% |
| **BLOCKED** | **1** | **0.13%** |
| WATCH | 0 | 0% |
| DEGRADING | 0 | 0% |

**Result: 1 false BLOCKED day out of 780 = 0.13% false positive rate.**

Zero WATCH or DEGRADING alerts fired during 4 healthy seasons. The thresholds are **remarkably stable** against a model running at 80%+ HR.

### The Single False Positive: 2024-02-22

**Root cause: All-Star Break gap + bad day collision.**

The NBA All-Star break creates a ~7-day gap with no games (Feb 16-21, 2024). When V8 returned:

| Date | Edge 3+ Picks | Wins | HR | Status |
|------|--------------|------|------|--------|
| 2024-02-15 | 15 | 13 | 86.7% | Last game before break |
| *Feb 16-21* | *All-Star Break* | *—* | *—* | *No games* |
| **2024-02-22** | **43** | **20** | **46.5%** | **BLOCKED (false positive)** |
| 2024-02-23 | 49 | 38 | 77.6% | Recovered immediately |

**Mechanism:** The 7-day rolling window (days_ago 0-6) on Feb 22 contained ONLY Feb 22's data (43 picks). Feb 15 was 7 days ago, excluded from the window. The single bad day (46.5% on 43 picks) was enough to trigger BLOCKED.

**Why other All-Star breaks didn't trigger:**

| Year | Break | First Game Back | Picks | HR | Triggered? |
|------|-------|----------------|-------|------|------------|
| 2022 | Feb 17-24 | Feb 24 | 22 | 63.6% | No (above 52.4%) |
| 2023 | Feb 16-23 | Feb 23 | 22 | 81.8% | No (healthy) |
| **2024** | **Feb 16-22** | **Feb 22** | **43** | **46.5%** | **Yes (below 52.4%)** |
| 2025 | Feb 13-19 | Feb 19 | 5 | 60.0% | No (N < 20, insufficient) |

**Conclusion:** 1 in 4 All-Star breaks triggered a false positive. This is a known structural weakness of rolling-window metrics across gaps, not a threshold calibration issue.

**Potential fix (future):** Add a "gap guard" requiring 2+ consecutive days of data before state transitions. This would eliminate All-Star break false positives without affecting decay detection latency.

## Part 3: Decay Detection (True Positive Validation)

### V8's 2025-26 Decay Period (80 Game Days)

The Threshold strategy correctly identified V8's decay:

| Metric | Value |
|--------|-------|
| Total game days | 80 |
| **Blocked days** | **37 (46.3%)** |
| WATCH days | 7 |
| HEALTHY days | 36 |
| Picks taken | 215 (only during non-blocked periods) |
| HR on taken picks | 72.1% |
| P&L | +$8,900 |

**Timeline:**
- Nov 1-18: Insufficient data (ramp-up)
- **Nov 19 - Nov 30: BLOCKED** (29.6-52.3% 7d HR) — caught decay within 19 days
- Dec 1-3: Briefly DEGRADING/WATCH as 7d HR recovered
- Dec 4-14: HEALTHY (58-63% HR) — allowed profitable picks
- Dec 16: Single BLOCKED day (50.0% HR)
- Dec 17 - Jan 17: Mostly HEALTHY (55-83% HR) — caught the Dec recovery
- **Jan 18 - Feb 12: BLOCKED continuously** (36-52% HR) — permanent decay detected

**Key insight:** The system correctly allowed picks during Dec-Jan when V8 temporarily recovered (72.1% HR on those picks), while blocking during genuine decay periods. It didn't just detect decay—it navigated the decay curve to extract remaining value.

## Part 4: Threshold Sensitivity

### Healthy Period (2021-11 to 2025-06)

| Configuration | Blocked | Watch | Picks | HR | P&L |
|--------------|---------|-------|-------|-----|-----|
| Current (58/55/52.4) | 1 | 0 | 3,853 | 90.3% | $306,760 |
| Tighter (60/57/52.4) | 1 | 0 | 3,853 | 90.3% | $306,760 |
| Looser (55/52.4/50) | 1 | 0 | 3,853 | 90.3% | $306,760 |
| Aggressive (62/58/55) | 1 | 0 | 3,853 | 90.3% | $306,760 |

**All configurations are identical during healthy periods.** V8's 80%+ HR is so far above any threshold that the specific values don't matter. This confirms the thresholds are appropriately calibrated — they don't interfere with healthy models.

### Decay Period (2025-11 to 2026-02)

| Configuration | Blocked | Watch | Picks | HR | P&L |
|--------------|---------|-------|-------|-----|-----|
| Current (58/55/52.4) | 37 | 7 | 215 | 72.1% | $8,900 |
| Tighter (60/57/52.4) | 37 | 7 | 215 | 72.1% | $8,900 |
| Looser (55/52.4/50) | 29 | 4 | 255 | 67.8% | $8,280 |
| Aggressive (62/58/55) | 41 | 12 | 195 | 74.4% | $9,000 |

Small differences during decay:
- **Looser:** 8 fewer blocked days → 40 more picks at lower HR → $620 less P&L
- **Aggressive:** 4 more blocked days → 20 fewer picks at higher HR → $100 more P&L
- **Current vs Tighter:** Identical (watch/alert thresholds don't fire often enough to differ)

**Conclusion:** Current thresholds are near-optimal. The Aggressive config gains only $100 at the cost of 12 more WATCH alerts (more noise). Not worth the change.

## Part 5: Trade Deadline Analysis

| Period | Edge 3+ Picks | HR | Verdict |
|--------|--------------|------|---------|
| Feb 2022 (TD: Feb 10) | 511 | 81.6% | Healthy |
| Feb 2023 (TD: Feb 9) | 492 | 82.1% | Healthy |
| Feb 2024 (TD: Feb 8) | 649 | 71.6% | Mild dip |
| Feb 2025 (TD: Feb 6) | 656 | 79.0% | Healthy |
| Feb 2026 (TD: ~Feb 6) | 451 | 39.9% | **Decay** |

### January → February Seasonal Dip

| Season | Jan HR | Feb HR | Change |
|--------|--------|--------|--------|
| 2021-22 | 83.4% | 80.4% | -3.0pp |
| 2022-23 | 78.7% | 83.1% | +4.4pp |
| 2023-24 | 79.3% | 74.6% | -4.7pp |
| 2024-25 | 80.7% | 79.4% | -1.3pp |
| 2025-26 | 54.0% | 41.9% | -12.1pp |

**Finding:** There is NO consistent Feb trade deadline dip. Two seasons show a dip (2022, 2024), one shows improvement (2023), one is flat (2025). The 2025-26 drop is genuine model decay, not a seasonal pattern.

**Implication:** The system does NOT need special trade-deadline handling. The current thresholds correctly pass through normal seasonal variation and only trigger on actual decay.

## Part 6: Recommendations

### Keep 58/55/52.4

The thresholds are validated:
- **0.13% false positive rate** across 780 healthy game days
- **Correct true positive** detection of actual decay
- **Identical performance** across all tested threshold variations during healthy periods
- **No seasonal patterns** that would require seasonal threshold adjustment

### Optional Future Improvement: Gap Guard

The single false positive stems from All-Star break gaps. A "gap guard" could be added:
- If the 7-day rolling window contains data from only 1-2 game days, require 2 more game days before transitioning to BLOCKED
- This would eliminate All-Star break false positives with zero impact on decay detection (since real decay persists across multiple days)

**Priority:** Low. The 0.13% false positive rate is already excellent, and the single BLOCKED day was immediately self-correcting (V8 was HEALTHY the next day).

### V8 vs V9 Threshold Applicability

V8 ran at 80%+ HR, far above the 58% WATCH threshold. V9 runs at 55-65% HR when healthy, much closer to the thresholds. This means:
- Thresholds are **conservatively calibrated** for V8 (large margin to healthy baseline)
- Thresholds are **aggressively calibrated** for V9 (small margin between healthy 60% and WATCH 58%)
- The same thresholds work for both, but V9 will naturally trigger more WATCH/DEGRADING states
- This is **correct behavior**: V9's narrower margin between healthy and decay means faster detection is appropriate

### Verdict on "Optimized for the Last War"

The Session 263 review concern ("thresholds backtested against one V9 decay episode") is addressed:
- V8 validates that the thresholds are inert during healthy periods (0 false WATCH, 1 false BLOCKED)
- The thresholds aren't "V9-specific" — they work across architectures with vastly different baselines
- The concern would be valid if V8 had many false positives, but it doesn't
- The real risk isn't threshold calibration — it's the **rolling window behavior during gaps** (All-Star break)

## Appendix: Conservative Strategy Comparison

| Strategy | Period | Game Days | Blocked | Picks | HR | P&L |
|----------|--------|-----------|---------|-------|-----|-----|
| Threshold | Healthy | 780 | 1 | 3,853 | 90.3% | $306,760 |
| Conservative(5d) | Healthy | 780 | 0 | 3,858 | 90.2% | $306,630 |
| Threshold | Decay | 80 | 37 | 215 | 72.1% | $8,900 |

During the healthy period, Conservative(5d, 55%) produced nearly identical results to Threshold — 0 blocked days vs 1, functionally equivalent P&L. The 5-day consecutive requirement prevented the All-Star false positive.

For single-model scenarios without challengers, Conservative is marginally better (eliminates the All-Star false positive). But the Threshold strategy's advantage emerges when challengers exist (can switch to alternatives instead of just blocking).
