# Results Report: Focused Signal Backtest (Cross-Model + Vegas)

Copy everything below the line into the review chat.

---

## Results from your recommended focused test

You asked us to test only signals 21-23 (cross-model) and signal 9 (vegas line movement), then report back with per-window HR breakdowns and sample sizes. We did. Here's what happened.

## Per-Window Breakdown

| Signal | W1 (Jan 2-15) | W2 (Jan 16-31) | W3 (Feb 1-8) | W4 (Feb 9-14) | TOTAL |
|--------|---------------|-----------------|--------------|---------------|-------|
| `vegas_line_move_with` | 100% N=1 | 50.0% N=6 | -- N=0 | -- N=0 | **57.1% N=7** |
| `v9_v12_both_high_edge` | -- N=0 | -- N=0 | 100% N=1 | -- N=0 | **100% N=1** |
| `v9_v12_disagree_strong` | -- N=0 | -- N=0 | 40.0% N=5 | 33.3% N=3 | **37.5% N=8** |
| `v9_confident_v12_edge` | -- N=0 | -- N=0 | 52.2% N=23 | 40.0% N=5 | **50.0% N=28** |

## Detailed Splits

**vegas_line_move_with** (N=7, 57.1% HR, +9.1% ROI):
- OVER: 2/4 = 50.0% | UNDER: 2/3 = 66.7%
- Home: 3/4 = 75.0% | Away: 1/3 = 33.3%
- Avg edge: 4.2

**v9_v12_both_high_edge** (N=1, meaningless):
- Single qualifying pick in entire dataset

**v9_v12_disagree_strong** (N=8, 37.5% HR, -28.4% ROI):
- OVER: 3/5 = 60.0% | UNDER: 0/3 = 0.0%
- This is a *skip* signal — when V12 vetoes V9, V9 wins only 37.5% of the time
- UNDER direction where models disagree: 0 for 3 (small but striking)

**v9_confident_v12_edge** (N=28, 50.0% HR, -4.5% ROI):
- OVER: 1/3 = 33.3% | UNDER: 13/25 = 52.0%
- Home: 6/12 = 50.0% | Away: 8/16 = 50.0%
- Dead flat coin flip. No alpha.

## The Real Problem: Data Coverage

| Data Source | Coverage | Impact |
|-------------|----------|--------|
| V12 predictions | **0% before Feb 1**, 46-57% after | Cross-model signals only have 2 windows of data (12 days total) |
| Vegas line move (feature_27) | **93% NULL**, 2.5% non-zero movement | Signal can only fire on ~2% of predictions |
| V9 graded predictions | 2,121 total across all windows | Baseline is fine |

**V12 only started generating graded predictions on Feb 1, 2026.** Signals 21-23 have at most 12 days of data. There's no way to get a reliable read with N=1, N=8, and N=28.

**Vegas line move** is populated for only 1-4% of feature store rows, and of those, 65% are zero (no movement). The feature pipeline barely populates this field. With N=7 qualifying picks across 6 weeks, the signal is untestable.

## What About Last Season?

We checked — there are **17,455 graded predictions from 2024-25** (catboost_v8), plus full player_game_summary and feature store coverage. We considered running signals against it but decided against it because:

1. **Different model**: V8 had 74.2% overall HR vs V9's ~55%. Edge distributions, confidence bands, and systematic biases are completely different. A signal calibrated on "V9 edge >= 5" means something different on V8.
2. **Transfer risk**: Good results on V8 wouldn't validate V9 signals. Bad results wouldn't invalidate them either. We'd be measuring the wrong thing.
3. **Better use of last season**: Raw basketball hypothesis testing (e.g., "do players bounce back after blowout-minutes games?") using player_game_summary independent of any model. That tests the underlying pattern, not the signal implementation.

## One Actionable Finding

**`v9_v12_disagree_strong` as a VETO filter** is the most interesting result. When V9 has high edge (>=5) but V12 disagrees on direction, V9 only wins 37.5% (3/8). That's well below breakeven. If this holds with more data, it's a simple "if V12 disagrees, don't bet" filter that could prevent ~8 bad picks per month.

But N=8 is not enough to act on. We need V12 running for at least another month before this is testable.

## Recommendation

These 4 signals are **blocked by data coverage**, not by flawed logic. Two paths forward:

1. **Wait**: Let V12 accumulate 2+ months of graded data, then re-test cross-model signals with real sample sizes (target N >= 50)
2. **Fix vegas coverage**: Investigate why feature_27 is 93% NULL. If the upstream pipeline can be fixed to populate line movement for all players with prop lines, the vegas signal becomes testable immediately.
3. **Pivot to high-data signals**: Our existing 23 signals have 2,121 graded V9 predictions to work with. The dimensional filtering work (testing each signal across home/away, position, rest, etc.) showed massive improvements with current data — cold_snap went from 61% to 93% with a single filter. More value there than chasing data-starved signals.

What's your call — wait for data, fix the pipeline, or redirect to dimensional filtering on existing signals?
