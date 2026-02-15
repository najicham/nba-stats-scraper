# Session 264: COLD Model-Dependent Signals at 0.0x

## Context

Sessions 259-262 built signal health weighting: HOT signals get 1.2x, NORMAL 1.0x, COLD 0.5x. An external review (Session 263) identified that 0.5x for COLD model-dependent signals is too generous — Feb 2 data shows model-dependent signals (high_edge, edge_spread_optimal) hit 5.9-8.0% during model decay, while behavioral signals (minutes_surge) went 3/3 (100%).

The key insight: model-dependent signals are downstream of model predictions. When the model is broken, these signals are broken by definition. Behavioral signals (minutes_surge, cold_snap, 3pt_bounce, blowout_recovery) are computed from player behavior patterns independent of model accuracy.

## What to Do

1. **Add `is_model_dependent` classification to signals.** Check `ml/signals/` for where signal tags are defined. Model-dependent signals: `high_edge`, `edge_spread_optimal`, `edge_spread_confident`. Behavioral signals: `minutes_surge`, `cold_snap`, `3pt_bounce`, `blowout_recovery`.

2. **Modify COLD weight logic in `ml/signals/aggregator.py`.** In the `_weighted_signal_count()` method, when a signal's regime is COLD:
   - Model-dependent signals: 0.0x weight (effectively ignored)
   - Behavioral signals: 0.5x weight (current behavior)

3. **Update `ml/signals/signal_health.py`** to include `is_model_dependent` in the health computation output so the aggregator can distinguish them.

4. **Verify the signal_health_daily BQ table** has (or can have) a field indicating model-dependency. If not, the classification can be done in code using a simple lookup dict.

5. **Test:** Run the scoring formula mentally against the Feb 2 data — with 0.0x for COLD model-dependent signals, picks that were boosted by high_edge during decay would lose their signal count boost, potentially dropping below the MIN_SIGNAL_COUNT=2 floor and being excluded.

## Key Files

- `ml/signals/aggregator.py` — scoring formula, `_weighted_signal_count()`
- `ml/signals/signal_health.py` — regime classification
- `ml/signals/combo_registry.py` — combo matching (may need awareness of this change)
- `data_processors/publishing/signal_annotator.py` — uses health weighting

## Constraints

- Do NOT change the HOT (1.2x) or NORMAL (1.0x) weights
- Do NOT modify the combo registry classifications
- Non-breaking: if signal_health_daily is missing, default to 1.0x for all signals (existing fail-safe)
- Commit and push when done
