# Session 270 Prompt — Remove Health Gate from Signal Best Bets

## Context

Session 269 built a steering replay system (`ml/analysis/steering_replay.py`) that backtested the full signal + steering pipeline from Jan 9 – Feb 12. Results:

| Strategy | Picks | W-L | HR% | P&L | ROI |
|----------|-------|-----|-----|-----|-----|
| **With health gate (production)** | 93 | 53-40 | 57.0% | $+900 | +8.8% |
| **Without health gate** | 165 | 96-69 | 58.2% | $+2,010 | +11.1% |

The health gate (model_health signal blocking picks when 7d HR < 52.4%) cost $1,110 in profit. The signal system's 2-signal minimum filter already kept quality high even during BLOCKED days (62% HR in February decay period). We're early and learning — more picks means more data.

## Task

Remove the model health gate so signal best bets are produced every game day regardless of model decay state. Specifically:

1. **In `ml/signals/aggregator.py`**: The `BestBetsAggregator` doesn't enforce the gate itself — it relies on the `model_health` signal returning `qualifies=False` which prevents it from counting toward the 2-signal minimum. The gate is actually in the signal evaluation layer.

2. **In `ml/signals/model_health.py`**: The `ModelHealthSignal.evaluate()` returns `qualifies=False` when HR < 52.4% (BREAKEVEN_HR). Change this so it always returns `qualifies=True` but with metadata indicating the health state. This way:
   - Signal still evaluates and reports health status (we can see it in tags)
   - It no longer blocks picks from being produced
   - The 2-signal minimum and combo registry still do quality filtering

3. **In `ml/experiments/signal_backfill.py` line ~286**: The `evaluate_and_build()` function has `if health_status != 'blocked':` guard before building best bets. Remove this guard so best bets are always built.

4. **Update the steering replay** to reflect this change (the `--no-health-gate` flag should become the default behavior).

5. **Update `model-health.json` export**: Keep `show_blocked_banner` in the JSON so the website can still show "model struggling" messaging, but don't let it prevent picks from being shown.

6. **Run the steering replay** after making changes to verify the no-gate results still hold.

## What NOT to change

- Keep the `model_performance_daily` computation as-is (states still tracked)
- Keep the `decay-detection` CF and Slack alerts (monitoring is separate from blocking)
- Keep the `--no-health-gate` CLI flag in steering_replay.py (useful for A/B comparison)
- Don't change the signal health weighting (HOT/COLD multipliers still apply)

## Verification

```bash
# 1. Run steering replay — should now match the "no health gate" numbers
PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12

# 2. Verify model_health signal still evaluates (just doesn't block)
PYTHONPATH=. python -c "
from ml.signals.model_health import ModelHealthSignal
s = ModelHealthSignal()
# Should qualify=True even with low HR
r = s.evaluate({'player_lookup': 'test', 'game_id': 'test'}, supplemental={'model_health': {'hit_rate_7d_edge3': 40.0}})
assert r.qualifies == True, f'Should qualify: {r}'
print(f'Low HR result: qualifies={r.qualifies}, metadata={r.metadata}')
"

# 3. Deploy (auto-deploys on push to main)
```

## Handoff + docs

- Update `docs/09-handoff/START-NEXT-SESSION-HERE.md` to note gate removal
- Update `CLAUDE.md` if any instructions reference the health gate blocking behavior
- Write handoff at `docs/09-handoff/2026-02-15-SESSION-270-HANDOFF.md`
