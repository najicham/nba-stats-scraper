# Session 265: V8 Multi-Season Replay Validation

## Context

Sessions 261-262 built a replay engine that backtests model switching strategies against historical graded data. The decay state machine uses thresholds 58% (WATCH), 55% (DEGRADING), 52.4% (BLOCKED) — but these were calibrated against ONE decay event (V9, Jan-Feb 2026).

An external review (Session 263) flagged this as the biggest risk: "Every threshold was backtested against one V9 decay episode. The system is optimized to catch the last war."

## What to Do

### Part 1: V8 Multi-Season Replay

V8 (`catboost_v8`) has 27K+ graded picks across 4 seasons (2021-2025) in `prediction_accuracy`. Run the replay engine across V8's full history to answer:

1. **How many false positives do the current thresholds produce?** If V8 was healthy at 79.7% lifetime HR, WATCH (58%) should rarely fire. Count how many days V8 would have been in WATCH/DEGRADING/BLOCKED state.

2. **What's the optimal threshold set for V8?** Does 58/55/52.4 hold, or does V8's higher baseline suggest different thresholds?

3. **Are there patterns around trade deadline weeks?** V8 data covers 4 trade deadlines. Do we see consistent dips, or is 2025-26 truly an outlier?

```bash
# Run V8 replay across full history
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2021-11-01 --end 2025-06-30 \
    --models catboost_v8 \
    --strategy threshold \
    --champion catboost_v8 \
    --verbose --output /tmp/v8-replay

# Compare strategies across V8 history
PYTHONPATH=. python ml/analysis/replay_cli.py \
    --start 2021-11-01 --end 2025-06-30 \
    --models catboost_v8 \
    --compare --output /tmp/v8-comparison
```

### Part 2: Analyze Results

Key questions:
- How many game days would V8 have been BLOCKED? (Should be very few if model was healthy)
- Does the Threshold strategy still beat Oracle across 4 seasons?
- Are there seasonal patterns (Feb dips, playoff changes)?
- What's the false positive rate for WATCH alerts?

### Part 3: Threshold Recommendations

If V8 data suggests different thresholds:
- Update `ml/analysis/model_performance.py` constants (WATCH_THRESHOLD, ALERT_THRESHOLD, BLOCK_THRESHOLD)
- Update `orchestration/cloud_functions/decay_detection/main.py` matching constants
- Update `ml/analysis/replay_strategies.py` ThresholdStrategy defaults
- Document findings in `docs/08-projects/current/signal-discovery-framework/`

## Important Notes

- V8 is a DIFFERENT model architecture than V9/V12. Thresholds that work for V8 may not transfer directly. But V8 gives us the only multi-season dataset we have.
- The replay engine's `_load_daily_data()` queries `prediction_accuracy` which has V8 data going back years. The `--models catboost_v8` flag should work directly.
- V8 was a single model (no challengers), so BestOfN and Oracle strategies won't be meaningful. Focus on Threshold and Conservative.
- If V8 has >1000 game days of data, the replay may take a while due to the BQ query size. Consider splitting by season if needed.

## Key Files

- `ml/analysis/replay_engine.py` — core engine
- `ml/analysis/replay_cli.py` — CLI interface
- `ml/analysis/replay_strategies.py` — strategy definitions
- `ml/analysis/model_performance.py` — threshold constants

## Expected Output

A document at `docs/08-projects/current/signal-discovery-framework/V8-MULTI-SEASON-REPLAY-RESULTS.md` with:
- False positive analysis
- Season-by-season breakdown
- Trade deadline week analysis
- Threshold recommendations (keep 58/55/52.4 or adjust)
