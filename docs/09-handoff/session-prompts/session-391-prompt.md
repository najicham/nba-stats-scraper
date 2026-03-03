# Session 391 Prompt — Fleet Health Investigation: Low N & Signal Drought

## Context

Session 390 ran daily validation on 2026-03-03. Pipeline is healthy, but two related concerns:

1. **All models have dangerously low N** (7-24 graded edge 3+ picks in 7-day window). No model has enough data for confident evaluation.
2. **0 best bets on a 10-game slate** — signals aren't firing on enough picks to cross the SC>=3 threshold.

Root cause: massive fleet turnover in Session 383B (Feb 26-27). Old fleet disabled, 11 of 16 new models only started producing on Mar 2 (2 days ago).

## Investigation Tasks

### 1. Signal Drought Analysis (P1)

0 best bets on a 10-game slate is unusual. Of 55 edge 3+ picks today, 42 have **zero signals**. Why?

```bash
# What signals are firing today?
bq query --use_legacy_sql=false "
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags,
  UNNEST(signal_tags) as signal_tag
WHERE game_date = '2026-03-03'
GROUP BY 1 ORDER BY 2 DESC"

# Signal health regime
bq query --use_legacy_sql=false "
SELECT * FROM nba_predictions.signal_health_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily)
ORDER BY signal_name"

# Is supplemental_data populating correctly?
bq query --use_legacy_sql=false "
SELECT player_lookup,
  prop_line_delta,
  dk_line_movement,
  self_creation_rate_last_10,
  opponent_pace_normalized,
  implied_team_total
FROM nba_predictions.pick_supplemental_data
WHERE game_date = '2026-03-03'
LIMIT 10"
```

Check if signals fixed in Session 387 (`line_rising_over`, `fast_pace_over`, `prop_line_delta`-dependent signals) are actually firing now. Session 387 fixed the code but may not have been deployed when the old fleet was disabled.

### 2. Registry Inconsistencies (P2)

Three issues found in the model registry:

**A. `lgbm_v12_noveg_train1201_0209`** — `enabled=false` in registry but shows as HEALTHY with 71.4% HR 7d in model_performance_daily. Is this:
- A model that was accidentally disabled during Session 383B cleanup?
- A model that should be re-enabled given its performance?
- Performance data from before it was disabled?

```bash
bq query --use_legacy_sql=false "
SELECT model_id, enabled, status, registered_at
FROM nba_predictions.model_registry
WHERE model_id LIKE 'lgbm%'"
```

**B. `catboost_v9_low_vegas_train0106_0205`** — `enabled=false` but still producing predictions (active through Mar 3). The worker caches the registry at startup. Worker was redeployed Mar 2 at 15:55 UTC. Was this model disabled before or after that redeploy?

**C. ~20 disabled models with `status=active`** — these should be `blocked` or `disabled` for consistency. Run `python bin/deactivate_model.py` or update status manually.

### 3. Fleet Ramp-Up Timeline (P2)

The current fleet needs time to accumulate graded data. Calculate:
- How many game days until each model reaches N=50 edge 3+ (governance gate)?
- Should any promising disabled models be re-enabled to accelerate coverage?

```bash
# Current edge 3+ graded count per enabled model
bq query --use_legacy_sql=false "
SELECT pa.system_id,
  COUNT(*) as graded_edge3,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  r.enabled
FROM nba_predictions.prediction_accuracy pa
LEFT JOIN nba_predictions.model_registry r ON pa.system_id = r.model_id
WHERE pa.game_date >= '2026-02-28'
  AND ABS(pa.predicted_points - pa.line_value) >= 3.0
  AND pa.prediction_correct IS NOT NULL
GROUP BY 1, 4
ORDER BY graded_edge3 DESC"
```

### 4. Best Bets Continuity Assessment (P3)

The system went from producing daily best bets to 0 picks. How many consecutive days has this happened?

```bash
# Best bets pick count by day
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-02-25'
GROUP BY 1 ORDER BY 1 DESC"
```

If 0 picks for 3+ consecutive game days, consider whether the MIN_SIGNAL_COUNT=3 threshold should be temporarily relaxed to SC=2, or if the issue is purely signal infrastructure (signals not computing/firing).

## What NOT to Do

- **Don't retrain models** — the fleet is too new, needs data accumulation
- **Don't change MIN_SIGNAL_COUNT without evidence** — verify signal infrastructure first
- **Don't disable DEGRADING models** — they have the most data (N=15-24), removing them would worsen the low-N problem
- **Don't deploy prediction-worker** — latest revision already correctly filters disabled models

## Key Files

- `ml/signals/signal_annotator.py` — where signals are computed and attached to picks
- `ml/signals/supplemental_data.py` — data signals depend on (prop_line_delta, dk_line_movement, etc.)
- `ml/signals/signal_health.py` — ACTIVE_SIGNALS list and signal definitions
- `bin/deactivate_model.py` — model deactivation CLI
- `bin/monitoring/model_profile_monitor.py` — per-model performance profiling

## Reference

- Session 390 handoff: `docs/09-handoff/2026-03-03-SESSION-390-HANDOFF.md`
- Session 387 (signal fixes): `line_rising_over`, `fast_pace_over`, `prop_line_delta` fixes
- Session 383B (fleet turnover): disabled old fleet, deployed new models
