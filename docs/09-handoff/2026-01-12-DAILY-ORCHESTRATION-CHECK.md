# Daily Orchestration Check - January 12, 2026

**Purpose:** Check today's pipeline orchestration health
**Date:** January 12, 2026

---

## Quick Health Check Commands

```bash
# 1. Overall pipeline health
PYTHONPATH=. python tools/monitoring/check_pipeline_health.py

# 2. Check Cloud Run services
curl -s https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health
curl -s https://prediction-worker-756957797294.us-west2.run.app/health

# 3. Check today's predictions
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT
    DATE(created_at) as date,
    COUNT(*) as total_predictions,
    COUNT(DISTINCT player_lookup) as players,
    COUNT(DISTINCT prediction_system) as systems,
    COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable
FROM nba_predictions.player_prop_predictions
WHERE DATE(created_at) = CURRENT_DATE()
GROUP BY 1
'''
for row in client.query(query).result():
    print(f'Date: {row.date}')
    print(f'Total predictions: {row.total_predictions}')
    print(f'Players: {row.players}')
    print(f'Systems: {row.systems}')
    print(f'Actionable: {row.actionable}')
"

# 4. Check Phase 4 completion status (Firestore)
PYTHONPATH=. python -c "
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase4_completion').document('2026-01-12').get()
if doc.exists:
    data = doc.to_dict()
    print('Phase 4 Status for 2026-01-12:')
    for k, v in data.items():
        if not k.startswith('_'):
            print(f'  {k}: completed')
    print(f'  _triggered: {data.get(\"_triggered\", False)}')
else:
    print('No Phase 4 completion record for today')
"

# 5. Check recent orchestrator logs
gcloud functions logs read phase4-to-phase5-orchestrator --region us-west2 --limit 20
gcloud functions logs read phase3-to-phase4-orchestrator --region us-west2 --limit 20

# 6. Check scheduler job runs
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,state)"
```

---

## Key Documents to Read

### Architecture & Flow
1. **Pipeline Design:** `docs/01-architecture/pipeline-design.md`
   - Understand 6-phase pipeline flow

2. **Orchestration v1.0:** `docs/01-architecture/orchestration/v1.0-event-driven-orchestration.md`
   - Pub/Sub topics, Firestore state, orchestrator logic

3. **Phase 4→5 Flow:** `docs/08-projects/current/pipeline-reliability-improvements/2026-01-12-PHASE4-TO-5-TIMEOUT-FIX-PLAN.md`
   - Timeout handling, staleness detection

### Operations
4. **Daily Operations Runbook:** `docs/02-operations/daily-operations-runbook.md`
   - Standard daily checks

5. **Troubleshooting Matrix:** `docs/02-operations/troubleshooting-matrix.md`
   - Common issues and fixes

### Recent Session Context
6. **Session 19 Handoff:** `docs/09-handoff/2026-01-12-SESSION-19-HANDOFF.md`
   - Critical sportsbook bug fix deployed today
   - Slack webhook is invalid (404) - alerts not working

7. **Session 18 Handoff:** `docs/09-handoff/2026-01-12-SESSION-18-HANDOFF.md`
   - Recent deployments context

---

## What to Check

### 1. Did Phase 4 Complete?
- Check Firestore `phase4_completion/2026-01-12`
- Expected processors: `team_defense_zone_analysis`, `player_shot_zone_analysis`, `player_composite_factors`, `player_daily_cache`, `ml_feature_store`

### 2. Did Phase 5 (Predictions) Run?
- Check `nba_predictions.player_prop_predictions` for today's date
- Expected: ~400-500 predictions across 5 systems

### 3. Are Services Healthy?
- `prediction-coordinator` health endpoint
- `prediction-worker` health endpoint

### 4. Any Errors in Logs?
- Check orchestrator function logs
- Check Cloud Run service logs

### 5. Sportsbook Data Collection (NEW - Session 19)
```sql
-- Check if sportsbook tracking is working after today's fix
SELECT
    line_source_api,
    sportsbook,
    COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE DATE(created_at) = CURRENT_DATE()
GROUP BY 1, 2
ORDER BY 3 DESC;
```
- Should now see `ODDS_API` with `DRAFTKINGS`/`FANDUEL` instead of all NULLs

---

## Known Issues (As of Session 19)

1. **Slack Webhook Invalid:** All alerting functions deployed but webhook URL returns 404
   - `daily-health-summary`, `phase4-timeout-check`, `phase4-to-phase5-orchestrator`
   - No alerts will be sent until new webhook is configured

2. **Sportsbook Fix Just Deployed:** `prediction-coordinator-00034-scr`
   - Previous predictions have `sportsbook=NULL`
   - Today's predictions (after fix) should have actual sportsbook values

---

## BigQuery Tables to Query

| Table | Purpose |
|-------|---------|
| `nba_predictions.player_prop_predictions` | Today's predictions |
| `nba_predictions.prediction_accuracy` | Grading results |
| `nba_orchestration.processor_run_history` | Processor execution logs |
| `nba_analytics.player_game_summary` | Phase 3 analytics output |
| `nba_predictions.ml_feature_store_v2` | Phase 4 ML features |

---

## Firestore Collections

| Collection | Purpose |
|------------|---------|
| `phase2_completion/{game_date}` | Phase 2 processor tracking |
| `phase3_completion/{game_date}` | Phase 3 processor tracking |
| `phase4_completion/{game_date}` | Phase 4 processor tracking |
| `prediction_batches/{batch_id}` | Prediction batch state |

---

## Expected Daily Timeline (ET)

| Time | Event |
|------|-------|
| ~6:00 AM | Phase 1-4 processors complete for today |
| ~6:30 AM | Phase 5 predictions triggered |
| 7:00 AM | Daily health summary (if Slack working) |
| Game time | Live scoring updates |
| Post-games | Grading runs |

---

## If Issues Found

1. **No predictions today:**
   - Check Phase 4 completion in Firestore
   - Check orchestrator logs for errors
   - Manually trigger: `curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start -H 'Content-Type: application/json' -d '{"game_date":"2026-01-12"}'`

2. **Phase 4 stuck:**
   - Check `phase4-timeout-check` logs
   - Manually check Firestore state
   - Force trigger if needed

3. **Sportsbook still NULL:**
   - Verify coordinator revision is `00034-scr`
   - Check if odds data exists in `nba_raw.odds_api_player_points_props`

---

*Created: January 12, 2026*
*For: New chat session to check daily orchestration*
