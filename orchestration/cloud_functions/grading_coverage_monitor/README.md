# Grading Coverage Monitor

Post-grading self-healing Cloud Function that validates grading coverage and automatically triggers re-grading if coverage is insufficient.

## Overview

This function is **Layer 3** of the grading prevention system. It runs after grading completes and verifies that a sufficient percentage of predictions were actually graded. If coverage is too low, it automatically triggers re-grading up to a maximum number of attempts.

## Trigger

- **Pub/Sub Topic**: `nba-grading-complete`
- **Source**: Published by the grading function after each grading run

## Self-Healing Logic

```
1. Receive grading completion event
2. Query BigQuery for:
   - Gradable predictions (matching grading filter criteria)
   - Graded predictions (in prediction_accuracy table)
3. Calculate coverage = graded / gradable
4. If coverage < 70%:
   - Check Firestore for regrade attempts
   - If attempts < 2:
     - Trigger re-grading via nba-grading-trigger
     - Increment attempt counter
     - Send WARNING alert to Slack
   - If attempts >= 2:
     - Send CRITICAL alert (needs manual investigation)
     - Do NOT trigger more re-grades
5. If coverage >= 70%:
   - Log success, no action needed
```

## Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| `COVERAGE_THRESHOLD` | 70% | Minimum acceptable coverage |
| `MAX_REGRADE_ATTEMPTS` | 2 | Max auto-regrade attempts |
| `REGRADE_ATTEMPTS_COLLECTION` | `grading_regrade_attempts` | Firestore collection |
| `GRADING_TRIGGER_TOPIC` | `nba-grading-trigger` | Pub/Sub topic for regrade |

## Firestore Schema

Collection: `grading_regrade_attempts`
Document ID: `{game_date}` (e.g., "2026-02-03")

```json
{
  "attempts": 1,
  "last_attempt": "2026-02-04T07:30:00.000Z",
  "reasons": [
    "Coverage 45.2% below 70% threshold"
  ],
  "target_date": "2026-02-03"
}
```

## Alerting

### Warning Alert (Will Regrade)
- Sent when coverage < 70% and attempts < max
- Includes coverage metrics and regrade status
- Color: Orange

### Critical Alert (Max Attempts)
- Sent when coverage < 70% and attempts >= max
- Requires manual investigation
- Includes troubleshooting steps
- Color: Red

## Deployment

```bash
gcloud functions deploy grading-coverage-monitor \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/grading_coverage_monitor \
  --entry-point=main \
  --trigger-topic=nba-grading-complete \
  --timeout=60s \
  --memory=256MB \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform"
```

## HTTP Endpoints

### Health Check
```bash
curl https://<function-url>/health
```

### Manual Coverage Check
```bash
curl "https://<function-url>/check-coverage?date=2026-02-03"
```

## Local Testing

```bash
# Check coverage for a specific date
cd orchestration/cloud_functions/grading_coverage_monitor
PYTHONPATH=../../.. python main.py 2026-02-03
```

## Test Scenarios

### 1. Synthetic Low Coverage (Trigger Regrade)
```bash
# Simulate low coverage by checking a date with incomplete grading
python main.py 2026-02-03
# If coverage < 70%, follow prompt to trigger regrade
```

### 2. Max Attempts Exceeded (Alert Only)
```bash
# Manually set attempts in Firestore to MAX_REGRADE_ATTEMPTS
# Then run monitor - should send critical alert, not regrade
```

### 3. Normal Coverage (No Action)
```bash
# Check a date with good coverage
python main.py 2026-02-02
# Should report coverage >= 70%, no action taken
```

## Troubleshooting

### Low Coverage Causes

1. **Phase 3 Analytics Missing**
   - Check if `player_game_summary` has data for the date
   - Verify Phase 3 completed successfully

2. **Grading Query Timeout**
   - Check Cloud Function logs for timeout errors
   - May need to increase function timeout

3. **Data Quality Issues**
   - Predictions may have invalid line values
   - Check for `line_source` mismatches

### Manual Regrade Command

```bash
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date": "2026-02-03", "trigger_source": "manual"}'
```

### Clear Regrade Attempts (Reset)

```bash
# Use Firebase console or:
python -c "
from google.cloud import firestore
db = firestore.Client()
db.collection('grading_regrade_attempts').document('2026-02-03').delete()
print('Cleared regrade attempts for 2026-02-03')
"
```

## Related Components

- **Grading Function**: `orchestration/cloud_functions/grading/main.py`
- **Grading Readiness Monitor**: `orchestration/cloud_functions/grading_readiness_monitor/main.py`
- **Prediction Accuracy Processor**: `data_processors/grading/prediction_accuracy/`

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-04 | Initial implementation |
