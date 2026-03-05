# Session 412 Prompt

## Context
Session 411 added 5 new shadow signals (usage_surge_over, scoring_momentum_over, career_matchup_over, minutes_load_over, blowout_risk_under), re-enabled volatile_scoring_over, and created a signal decay monitor. Model experiments are exhausted — V12_noveg 56d is the ceiling. All future value is in signal quality.

## Priorities

### 1. Check New Shadow Signal Fire Rates
```bash
# Check if new signals are firing in production
bq query --nouse_legacy_sql "
SELECT signal_tag, COUNT(*) as fires,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr
FROM \`nba-props-platform.nba_predictions.pick_signal_tags\` pst
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON pst.player_lookup = pa.player_lookup AND pst.game_id = pa.game_id
WHERE pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND signal_tag IN ('usage_surge_over', 'scoring_momentum_over', 'career_matchup_over',
                      'minutes_load_over', 'blowout_risk_under', 'volatile_scoring_over')
  AND pa.has_prop_line = TRUE AND pa.prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1
"
```

### 2. Run Signal Decay Monitor
```bash
PYTHONPATH=. python bin/monitoring/signal_decay_monitor.py --dry-run
```

### 3. Promote Ready Shadow Signals
Any shadow signal with **HR >= 60% + N >= 30** is ready for production. Wire into aggregator rescue_tags.

Shadow signals approaching promotion threshold (as of Session 411):
- `combo_3way`/`combo_he_ms` already in rescue_tags — check if still performing
- New signals need 7-14 days of data first

### 4. (~Apr 5) Evaluate Accumulated Data Signals
- `projection_delta` — NumberFire will have 30+ days. Create signal for projection-vs-line delta.
- `sharp_money` — VSiN will have 30+ days. Evaluate handle/ticket divergence thresholds.
- `blowout_risk_under` — f57 data should be accumulating. Check if firing.

### 5. Best Bets Performance Check
```bash
/daily-steering
/validate-daily
```
