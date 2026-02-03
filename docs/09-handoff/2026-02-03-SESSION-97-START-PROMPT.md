# Session 97 Start Prompt

Copy everything below this line into a new chat:

---

## Context

This is the NBA Props Prediction system. Read `CLAUDE.md` for full context.

## Session 96 Summary

We investigated why Feb 2 predictions had poor hit rate (49.1%):

**Root Cause:** ML feature store ran BEFORE Phase 4 completed, causing predictions to use default feature values (40 points) instead of real data (100 points). This caused systematic underprediction, creating false high-edge UNDER signals that all missed.

**Timeline Issue:**
- ML Features Feb 2: Created Feb 2, 6:00 AM ET
- Predictions Feb 2: Created Feb 2, 4:38 PM ET (stale features!)
- Phase 4 Feb 2: Created Feb 3, 2:00 AM ET (too late!)

**Session 95's quality gate system** (already deployed) should prevent this by waiting for 85%+ quality features before predicting.

## Deployments Made

- `prediction-worker` deployed (commit b18aa475) - includes model attribution fix
- Deploy script fixed to pass `CATBOOST_V8_MODEL_PATH` in Docker test (commit eec1cf65)

## Today's Priority Tasks

### 1. Verify Quality Gate Working
```bash
# Check quality gate logs from today
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"QUALITY_GATE"' --limit=20

# Check if today's predictions have prediction_attempt populated
bq query --use_legacy_sql=false "
SELECT prediction_attempt, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY 1"

# Check model attribution
bq query --use_legacy_sql=false "
SELECT model_file_name, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions  
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
GROUP BY 1"
```

### 2. Implement P0: Phase 4 Completion Gate

The ML feature store should NOT run until Phase 4 is complete. Options:
1. Add a check in the ML feature store scheduler job
2. Add completion tracking to `nba_orchestration.phase_completions`
3. Use Pub/Sub trigger instead of cron

### 3. Implement P0: Feature Quality Alert

After each ML feature store run, alert if:
- Average feature quality < 80%
- More than 20% of players have low quality (<80%)

Send Slack alert to #nba-alerts.

### 4. Monitor Today's Hit Rates

10 games today. After games finish, check:
```sql
SELECT
  CASE WHEN feature_quality_score >= 85 THEN 'High' ELSE 'Low' END as tier,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy a
JOIN nba_predictions.ml_feature_store_v2 f
  ON a.player_lookup = f.player_lookup AND a.game_date = f.game_date
WHERE a.system_id = 'catboost_v9'
  AND a.game_date = CURRENT_DATE()
  AND a.recommendation IN ('OVER', 'UNDER')
GROUP BY tier;
```

## Active Reminders

| ID | Due | Task |
|----|-----|------|
| rem_008 | Feb 3 | Verify model attribution after prediction run |
| rem_001-004 | Feb 4 | Phase 6 verification tasks |
| rem_007 | Feb 5 | Check new model performance |

## Key Files

- `predictions/coordinator/quality_gate.py` - Quality gate logic
- `predictions/coordinator/quality_alerts.py` - Alerting (needs enhancement)
- `data_processors/precompute/ml_feature_store/quality_scorer.py` - Quality calculation
- `docs/09-handoff/2026-02-03-SESSION-96-HANDOFF.md` - Full investigation

## Quick Health Check

```bash
# Run daily validation
/validate-daily

# Check deployment drift
./bin/check-deployment-drift.sh

# Check today's predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions,
       COUNTIF(recommendation IN ('OVER','UNDER')) as actionable
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
GROUP BY 1"
```

---

Start by running `/validate-daily` to check system health, then work through the priority tasks above.
