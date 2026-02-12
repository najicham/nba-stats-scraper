# Session 211 Handoff — Model Decay Protective Filters

**Date:** 2026-02-11
**Focus:** Bridge filters to stop bleeding while Q43 quantile model matures

## Executive Summary

Champion `catboost_v9` has been stale 34+ days with UNDER HR collapsing to 27.5%. Implemented 3 protective filters as a bridge until Q43 promotion (~Feb 19-23).

## What Changed

### Files Modified

| File | Change |
|------|--------|
| `predictions/coordinator/signal_calculator.py` | Added light slate (<=4 games) RED signal override with `slate_size` from schedule CROSS JOIN |
| `predictions/worker/worker.py` | Added `stale_model_under_dampening` filter (champion UNDER edge<5). Modified `star_under_bias_suspect` to exempt quantile models (`_q4` in system_id) |

### Schema Change

- Added `slate_size INT64` column to `nba_predictions.daily_prediction_signals`

### New Filter: `stale_model_under_dampening`

- Applies ONLY to champion model (`catboost_v9`)
- Applies ONLY to UNDER recommendations
- Filters picks with edge < 5 (previously threshold was 3)
- Does NOT affect Q43/Q45 quantile models or OVER picks

### Modified Filter: `star_under_bias_suspect`

- Now exempts quantile models (system_id containing `_q4`)
- Quantile models don't exhibit the same star UNDER bias

## Deployment

1. Schema ALTER TABLE already run
2. Push to main auto-deploys prediction-coordinator + prediction-worker
3. Verify with `./bin/check-deployment-drift.sh --verbose`

## What to Monitor

```sql
-- After next prediction run, check filter distribution
SELECT filter_reason, COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY 1;

-- Check slate_size in signals
SELECT game_date, daily_signal, slate_size, signal_explanation
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= CURRENT_DATE() - 1;
```

## Q43 Promotion Timeline

- Q43 shadow started ~Feb 9
- Needs 10+ days of shadow grading data
- Target promotion window: Feb 19-23
- When promoted: remove `stale_model_under_dampening` filter (no longer needed)

## Documentation

- Project docs: `docs/08-projects/current/model-decay-protective-filters/`
