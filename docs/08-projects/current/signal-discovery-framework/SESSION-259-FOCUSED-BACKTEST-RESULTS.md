# Session 259: Focused Backtest Results — Cross-Model + Vegas Signals

**Date:** 2026-02-15
**Session:** 259
**Scope:** 4 signals tested per external review recommendation
**Verdict:** All 4 blocked by insufficient data coverage. No signals promoted.

---

## Signals Tested

| # | Signal | Logic | Total N | HR% | ROI% | Verdict |
|---|--------|-------|---------|-----|------|---------|
| 9 | `vegas_line_move_with` | Line moved toward prediction + edge >= 3 | 7 | 57.1% | +9.1% | INCONCLUSIVE |
| 21 | `v9_v12_both_high_edge` | Both models edge >= 5, same direction | 1 | 100% | +90.9% | INCONCLUSIVE |
| 22 | `v9_v12_disagree_strong` | V9 edge >= 5, V12 says opposite (skip signal) | 8 | 37.5% | -28.4% | PROMISING (needs data) |
| 23 | `v9_confident_v12_edge` | V9 confidence >= 80% + V12 edge >= 3 | 28 | 50.0% | -4.5% | SKIP — coin flip |

## Per-Window Breakdown

| Signal | W1 (Jan 2-15) | W2 (Jan 16-31) | W3 (Feb 1-8) | W4 (Feb 9-14) |
|--------|---------------|-----------------|--------------|---------------|
| `vegas_line_move_with` | 100% N=1 | 50.0% N=6 | N=0 | N=0 |
| `v9_v12_both_high_edge` | N=0 | N=0 | 100% N=1 | N=0 |
| `v9_v12_disagree_strong` | N=0 | N=0 | 40.0% N=5 | 33.3% N=3 |
| `v9_confident_v12_edge` | N=0 | N=0 | 52.2% N=23 | 40.0% N=5 |

## Root Cause: Data Coverage

| Data Source | Coverage | Why |
|-------------|----------|-----|
| V12 graded predictions | **0% before Feb 1**, 46-57% after | V12 model deployed Feb 1, 2026. Only 12 days of graded data. |
| Vegas line move (feature 27) | **93% NULL** in feature store | Upstream pipeline barely populates this field. Only 1-4% of rows have a value, and of those 65% are zero. |
| V9 graded predictions | 2,121 across all windows | Adequate baseline but signals can't fire without V12/vegas data. |

**Consequence:** Cross-model signals (21-23) are limited to W3+W4 only (12 days). Vegas signal has N=7 across 6 weeks. No signal has enough data to meet our promotion threshold (N >= 15, HR >= 60% across 2+ windows).

## Detailed Signal Analysis

### `vegas_line_move_with` — INCONCLUSIVE

- 4/7 correct (57.1%), but only 7 picks across entire backtest period
- Home: 3/4 (75%) vs Away: 1/3 (33%) — hint of home bias but N too small
- The signal logic is sound, but the data pipeline doesn't support it
- **Fix required:** Investigate why feature_27 (vegas_line_move) is 93% NULL. If the Odds API scraper captures opening vs current lines, this should be computable for every player with a prop line.

### `v9_v12_both_high_edge` — INCONCLUSIVE

- Exactly 1 qualifying pick in the entire dataset (both models edge >= 5, same direction)
- The threshold may be too strict — V12 edge >= 5 is rare
- **Possible relaxation:** Try edge >= 3 for V12 instead of >= 5

### `v9_v12_disagree_strong` — PROMISING AS VETO

- When V9 has high edge (>= 5) but V12 says the opposite direction, V9 wins only 37.5% (3/8)
- UNDER picks where models disagree: **0 for 3** (small but striking)
- OVER picks where models disagree: 3/5 = 60% (models disagree but V9 still right on OVER)
- **If confirmed with more data:** This becomes a "don't bet" filter — suppress V9 high-edge picks when V12 disagrees
- **Needs:** N >= 30 minimum before acting. At current V12 volume (~5 disagree picks/week), need 6+ more weeks.

### `v9_confident_v12_edge` — SKIP

- Dead flat 50.0% HR (14/28). No signal at all.
- Flat across home/away (50%/50%), OVER slightly worse than UNDER
- V9 high confidence + V12 moderate agreement does not add value
- **Decision:** Do not implement. V9 confidence alone doesn't discriminate.

## Last Season Data Assessment

We investigated using 2024-25 season data (catboost_v8, 17,455 graded predictions) and decided against it:

### Why Not

1. **Different model, different signals.** V8 had 74.2% overall HR vs V9's ~55%. Edge distributions are fundamentally different. "Edge >= 5" on V8 means something completely different than on V9. Signals calibrated for V9 can't be validated on V8 data.

2. **Transfer uncertainty cuts both ways.** If a signal works on V8 but not V9, we've learned nothing. If it fails on V8 but works on V9, we'd incorrectly kill a good signal. There's no clean interpretation.

3. **Survivor bias risk.** V8 had much higher baseline HR. A signal that "works" on V8 might just be riding the baseline, not adding alpha. We can't distinguish signal value from model quality.

### What Last Season IS Useful For

Testing **basketball hypotheses independent of any model**:
- "Do players who had blowout-minutes games (6+ below avg) score more next game?" — Use player_game_summary raw data
- "Do home players on cold streaks (3+ unders) bounce back?" — Use raw actuals
- "Does minutes surge predict higher scoring?" — Use raw minutes vs points

This validates the underlying patterns without model dependency. It's a separate, valuable workstream.

### Data Available

| Source | Rows | Date Range |
|--------|------|-----------|
| prediction_accuracy (V8) | 17,455 graded | Nov 2024 - Jun 2025 |
| player_game_summary | 28,240 | Oct 2024 - Jun 2025 |
| ml_feature_store_v2 | 25,846 | Nov 2024 - Jun 2025 |

---

## Updated Signal Roadmap

### Blocked — Waiting for Data

| Signal | Blocker | When Testable |
|--------|---------|---------------|
| `v9_v12_both_high_edge` | V12 only 12 days of data | Late March 2026 (6+ weeks) |
| `v9_v12_disagree_strong` | V12 only 12 days of data | Late March 2026 |
| `vegas_line_move_with` | Feature 27 is 93% NULL | After pipeline fix |

### Killed

| Signal | Reason |
|--------|--------|
| `v9_confident_v12_edge` | 50.0% HR (N=28), dead flat coin flip, no alpha anywhere |

### Highest-Value Next Steps (in priority order)

1. **Fix feature_27 pipeline** — If we can populate vegas_line_move for all prop-line players, the signal becomes testable immediately with existing V9 data (2,121 predictions)
2. **Dimensional filtering on existing signals** — Already proven to work (cold_snap 61%→93% with one filter). Apply remaining untested dimensions to all 23 signals. High data, high reward.
3. **Basketball hypothesis validation on last season** — Use raw player_game_summary (28K rows) to validate underlying patterns. No model dependency.
4. **Re-test cross-model signals in April** — After V12 has 2+ months of graded data.

---

## Backtest Script

`ml/experiments/signal_backtest_focused.py` — Self-contained, runs all 4 signals with per-window breakdowns, OVER/UNDER splits, home/away splits, and combo analysis.

```bash
PYTHONPATH=. python ml/experiments/signal_backtest_focused.py
```
