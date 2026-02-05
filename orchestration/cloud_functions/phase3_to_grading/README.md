# Phase 3 -> Grading Orchestrator

Cloud Function that listens to Phase 3 completion events and triggers grading when sufficient data coverage is achieved.

## Purpose

Acts as a **grading readiness gate** to:
1. Prevent premature grading that would produce incomplete/inaccurate results
2. Enable faster grading when data arrives early (event-driven vs polling)
3. Track coverage metrics for debugging and monitoring

## Architecture

```
nba-phase3-analytics-complete (Pub/Sub)
            │
            ├── phase3_to_phase4 (existing - triggers Phase 4)
            │
            └── phase3_to_grading (NEW - triggers grading)
                    │
                    ├── Check Firestore: phase3_completion/{game_date}
                    ├── Query BigQuery: player_game_summary, predictions
                    ├── Calculate coverage metrics
                    │
                    ├── If coverage ≥ thresholds:
                    │       └── Publish to: nba-grading-trigger
                    │
                    └── If coverage < thresholds:
                            └── Log and wait (scheduled grading is fallback)
```

## Coverage Thresholds

| Metric | Threshold | Description |
|--------|-----------|-------------|
| Player Coverage | ≥80% | % of predictions with corresponding actuals |
| Game Coverage | ≥90% | % of scheduled games with actuals |

## Message Format

### Input (from Phase 3 completion)
```json
{
  "processor_name": "player_game_summary",
  "game_date": "2026-02-03",
  "status": "success",
  "record_count": 150
}
```

### Output (to grading trigger)
```json
{
  "target_date": "2026-02-03",
  "trigger_source": "phase3_to_grading_player_game_summary",
  "run_aggregation": true,
  "triggered_at": "2026-02-04T07:15:00Z",
  "coverage_metrics": {
    "player_coverage_pct": 92.5,
    "game_coverage_pct": 100.0,
    "predictions_count": 450,
    "actuals_count": 416
  },
  "correlation_id": "p3g_2026-02-03_071500"
}
```

## Deployment

### Prerequisites
1. Pub/Sub topic `nba-grading-trigger` exists
2. Service account has BigQuery and Firestore access
3. Phase 3 processors are publishing to `nba-phase3-analytics-complete`

### Deploy Command
```bash
cd /home/naji/code/nba-stats-scraper

gcloud functions deploy phase3-to-grading \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase3_to_grading \
  --entry-point=main \
  --trigger-topic=nba-phase3-analytics-complete \
  --memory=256MB \
  --timeout=60s \
  --service-account=nba-pipeline@nba-props-platform.iam.gserviceaccount.com \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform"
```

### Deploy Health Check Endpoint (Optional)
```bash
gcloud functions deploy phase3-to-grading-health \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase3_to_grading \
  --entry-point=health \
  --trigger-http \
  --allow-unauthenticated \
  --memory=128MB \
  --timeout=10s
```

### Deploy Manual Check Endpoint (Optional)
```bash
gcloud functions deploy phase3-to-grading-check \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase3_to_grading \
  --entry-point=check_readiness \
  --trigger-http \
  --memory=256MB \
  --timeout=30s \
  --service-account=nba-pipeline@nba-props-platform.iam.gserviceaccount.com
```

## Testing

### 1. Local Testing
```bash
cd /home/naji/code/nba-stats-scraper

# Check readiness for yesterday
PYTHONPATH=. python orchestration/cloud_functions/phase3_to_grading/main.py

# Check readiness for specific date
PYTHONPATH=. python orchestration/cloud_functions/phase3_to_grading/main.py --date 2026-02-03

# Check and trigger if ready
PYTHONPATH=. python orchestration/cloud_functions/phase3_to_grading/main.py --date 2026-02-03 --trigger
```

### 2. Synthetic Event Testing
```bash
# Simulate Phase 3 completion event
gcloud pubsub topics publish nba-phase3-analytics-complete \
  --message='{
    "processor_name": "player_game_summary",
    "game_date": "2026-02-03",
    "status": "success",
    "record_count": 150,
    "correlation_id": "test_123"
  }'
```

### 3. HTTP Endpoint Testing
```bash
# Check readiness via HTTP
curl -X GET "https://FUNCTION_URL/check_readiness?game_date=2026-02-03"

# Manual trigger via HTTP
curl -X POST "https://FUNCTION_URL/manual_trigger" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-02-03"}'
```

### 4. Verify in Logs
```bash
# Watch function logs
gcloud functions logs read phase3-to-grading \
  --region=us-west2 \
  --limit=50

# Filter for specific date
gcloud functions logs read phase3-to-grading \
  --region=us-west2 \
  --filter="textPayload:2026-02-03"
```

### 5. Verify Firestore State
```python
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('grading_readiness').document('2026-02-03').get()
print(doc.to_dict())
```

## Monitoring

### Key Metrics to Watch
1. **Decision distribution**: How often trigger vs wait vs skip?
2. **Coverage trends**: Are coverage levels improving over time?
3. **Trigger latency**: Time from Phase 3 completion to grading trigger

### Cloud Logging Query
```
resource.type="cloud_function"
resource.labels.function_name="phase3-to-grading"
severity>=INFO
```

### Alerting Recommendations
1. Alert if coverage < 50% for dates older than 24 hours
2. Alert if grading trigger fails (message_id is null after decision=trigger)
3. Alert if function errors exceed threshold

## Safety Features

| Feature | Description |
|---------|-------------|
| Idempotency | Firestore `_triggered` flag prevents duplicate triggers |
| Fallback | Scheduled grading (2:30/6:30/11 AM ET) still runs |
| Manual override | HTTP endpoint allows manual trigger bypassing coverage |
| State tracking | Full assessment saved to Firestore for debugging |

## Related Components

| Component | Purpose |
|-----------|---------|
| `phase3_to_phase4` | Triggers Phase 4 precompute on Phase 3 completion |
| `grading_readiness_monitor` | Polls for boxscore completion (polling approach) |
| `grading` | Actual grading function (receives trigger) |

## Troubleshooting

### Function not triggering
1. Check Phase 3 is publishing to `nba-phase3-analytics-complete`
2. Verify `player_game_summary` processor is included in messages
3. Check Firestore for `_triggered` flag already set

### Coverage always below threshold
1. Query BigQuery directly to verify data counts
2. Check `player_game_summary` has data for the date
3. Verify predictions exist and `is_active=TRUE`

### Grading triggered but not running
1. Check `nba-grading-trigger` topic subscription
2. Verify grading function is healthy
3. Check grading function logs for errors

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial implementation |
