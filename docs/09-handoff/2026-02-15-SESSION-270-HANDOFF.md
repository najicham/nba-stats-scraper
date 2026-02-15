# Session 270 Handoff — Remove Health Gate from Signal Best Bets

**Date:** 2026-02-15
**Status:** Complete

## What Changed

Removed the model health gate that blocked signal best bets when the champion model's 7-day hit rate dropped below 52.4% breakeven. Signal best bets are now produced every game day regardless of model decay state.

**Why:** Steering replay (Session 269) showed the gate cost $1,110 in profit over Jan 9 – Feb 12. The signal system's 2-signal minimum filter already kept quality high (58.2% HR without gate vs 57.0% with gate, on 165 vs 93 picks).

## Files Changed (7)

### Health gate removal (5 files)

| File | Change |
|------|--------|
| `ml/signals/model_health.py` | `qualifies=False` → `qualifies=True` when HR < breakeven. Metadata preserved. |
| `data_processors/publishing/signal_best_bets_exporter.py` | Removed early return that blocked picks when `health_status == 'blocked'` |
| `data_processors/publishing/signal_annotator.py` | Removed `if health_status != 'blocked':` guard on `_bridge_signal_picks()` |
| `ml/experiments/signal_backfill.py` | Removed `if health_status != 'blocked':` guard on aggregator call |
| `ml/analysis/steering_replay.py` | `--no-health-gate` is now default; added `--with-health-gate` for comparison |

### Signal context in subset picks (2 files + ALTER TABLE)

| File | Change |
|------|--------|
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | Added 7 signal context columns |
| `data_processors/publishing/signal_annotator.py` | `_bridge_signal_picks()` now populates signal_tags, signal_count, matched_combo_id, combo_classification, combo_hit_rate, model_health_status, warning_tags |

**BigQuery ALTER TABLE applied** — `current_subset_picks` now has all signal context columns. Every best bets pick from Feb 19+ will include full "why" provenance.

## What Did NOT Change

- `model_performance_daily` computation (states still tracked: HEALTHY/WATCH/DEGRADING/BLOCKED)
- `decay-detection` Cloud Function and Slack alerts (monitoring is separate from blocking)
- `model-health.json` export (`show_blocked_banner` still set for frontend messaging)
- Signal health weighting (HOT/COLD multipliers still apply)
- `CLAUDE.md` updated to reflect gate removal

## Verification

```bash
# 1. Run steering replay — should now match the "no health gate" numbers by default
PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12

# 2. Compare with gate for A/B
PYTHONPATH=. python ml/analysis/steering_replay.py --start 2026-01-09 --end 2026-02-12 --with-health-gate
```

## Impact on Feb 19+ (Games Resume)

- Signal best bets will be produced every game day, even if model is in BLOCKED state
- The website can still show "model struggling" messaging via `show_blocked_banner` in `model-health.json`
- Expected: ~5 picks per game day (up from 0 on BLOCKED days)
- Quality maintained by 2-signal minimum, combo registry filtering, and signal health weighting
