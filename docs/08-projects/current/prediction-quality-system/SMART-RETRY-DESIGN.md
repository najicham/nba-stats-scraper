# Smart Prediction Retry System - Final Design

**Session 95 - 2026-02-03**
**Status: IMPLEMENTED**

---

## Overview

The smart prediction retry system implements a "Predict Once, Never Replace" strategy that ensures:

1. Predictions are only made when feature quality is sufficient
2. Existing predictions are never replaced
3. All players eventually get predictions (forced at LAST_CALL if necessary)
4. Quality flags provide transparency about prediction confidence

---

## Key Design Decision: Wait, Don't Replace

### Why We Wait Instead of Replace

| Approach | User Experience | Code Complexity | Accuracy |
|----------|-----------------|-----------------|----------|
| Predict early, replace later | Confusing - picks change | High - version tracking | Mixed |
| **Wait for quality, predict once** | Stable - picks don't change | Low - simple logic | Better |

We chose to **wait** because:
- Users trust predictions that don't change
- Most bettors don't place bets until close to game time anyway
- Simpler code is more maintainable

---

## Prediction Modes

| Mode | Schedule (ET) | Quality Threshold | Behavior |
|------|---------------|-------------------|----------|
| FIRST | 8:00 AM | 85% | Only high-quality |
| RETRY | 9-12 PM (hourly) | 85% | Skip if already predicted |
| FINAL_RETRY | 1:00 PM | 80% | Accept medium quality |
| LAST_CALL | 4:00 PM | 0% | Force all remaining |

---

## Quality Gate Logic

```python
def should_predict(player, mode):
    # Rule 1: Never replace existing predictions
    if player.has_active_prediction:
        return False  # SKIP

    # Rule 2: No feature data?
    if player.feature_quality is None:
        if mode == LAST_CALL:
            return True  # FORCE (flagged)
        return False  # WAIT

    # Rule 3: Quality meets threshold?
    threshold = THRESHOLDS[mode]  # 85, 85, 80, 0
    if player.feature_quality >= threshold:
        return True  # PREDICT

    # Rule 4: Below threshold
    if mode == LAST_CALL:
        return True  # FORCE (flagged)
    return False  # WAIT
```

---

## Schedule

### Data Pipeline

```
Time (ET)    Pipeline Stage
---------    --------------
6:00 AM      Phase 4 precompute (uses overnight game data)
7:00 AM      ML Feature Store refresh #1
10:00 AM     ML Feature Store refresh #2
1:00 PM      ML Feature Store refresh #3
```

### Predictions

```
Time (ET)    Mode           Quality Gate    Expected Coverage
---------    ----           ------------    -----------------
8:00 AM      FIRST          >= 85%          60-80% of players
9:00 AM      RETRY          >= 85%          70-85% of players
10:00 AM     RETRY          >= 85%          80-90% of players
11:00 AM     RETRY          >= 85%          85-95% of players
12:00 PM     RETRY          >= 85%          90-97% of players
1:00 PM      FINAL_RETRY    >= 80%          95-99% of players
4:00 PM      LAST_CALL      >= 0%           100% of players
```

### Exports

```
Time (ET)    Export
---------    ------
11:00 AM     phase6-tonight-picks-morning
1:00 PM      phase6-tonight-picks
5:00 PM      phase6-tonight-picks-pregame
```

---

## Alerting

| Alert | Trigger | Action |
|-------|---------|--------|
| LOW_QUALITY_FEATURES | <80% high quality | Check Phase 4 |
| PHASE4_DATA_MISSING | 0 feature rows | Investigate pipeline |
| FORCED_PREDICTIONS | >10 forced | Review data health |
| LOW_COVERAGE | <80% by 1 PM | Investigate blockers |

---

## Files

| File | Purpose |
|------|---------|
| `predictions/coordinator/quality_gate.py` | Core quality gate logic |
| `predictions/coordinator/quality_alerts.py` | Alerting system |
| `predictions/coordinator/coordinator.py` | Integration |

---

## Schema

```sql
-- player_prop_predictions
feature_quality_score FLOAT64   -- Quality at prediction time
low_quality_flag BOOLEAN        -- True if quality < 85%
forced_prediction BOOLEAN       -- True if forced at LAST_CALL
prediction_attempt STRING       -- FIRST, RETRY, FINAL_RETRY, LAST_CALL
```

---

## Monitoring Queries

### Quality Distribution
```sql
SELECT
  prediction_attempt,
  COUNT(*) as total,
  COUNTIF(low_quality_flag) as low_quality,
  COUNTIF(forced_prediction) as forced,
  ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
GROUP BY prediction_attempt;
```

### Coverage by Time
```sql
SELECT
  FORMAT_TIMESTAMP('%H:%M', created_at, 'America/New_York') as time_et,
  COUNT(*) as new_predictions,
  SUM(COUNT(*)) OVER (ORDER BY created_at) as cumulative
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
GROUP BY created_at
ORDER BY created_at;
```

---

## Success Criteria

1. **Quality**: >90% of predictions have quality >= 85%
2. **Timing**: First predictions by 8:30 AM ET
3. **Coverage**: >95% coverage by 1 PM ET
4. **Forced**: <5% of predictions forced at LAST_CALL
5. **Stability**: 0 predictions replaced after creation

---

## Session History

- **Session 94**: Identified problem, created initial design
- **Session 95**: Implemented quality gate, alerting, documentation
