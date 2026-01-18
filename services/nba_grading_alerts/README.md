# NBA Grading Alerts Service

Cloud Function that monitors NBA prediction grading and sends Slack alerts.

## What It Does

Runs daily at 12:30 PM PT to check:
1. **Grading failures**: No grades generated for yesterday
2. **Accuracy drops**: System accuracy below 55% (7-day average)
3. **Data quality**: >20% of predictions ungradeable
4. **Daily summary** (optional): Overall grading stats

## Deployment

```bash
# From repo root
./bin/alerts/deploy_nba_grading_alerts.sh
```

## Local Testing

```bash
cd services/nba_grading_alerts

# Install dependencies
pip install -r requirements.txt

# Set webhook URL
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Run locally
python main.py
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | ✅ Yes | - | Slack incoming webhook URL |
| `ALERT_THRESHOLD_ACCURACY_MIN` | No | 55.0 | Min accuracy before alert (%) |
| `ALERT_THRESHOLD_UNGRADEABLE_MAX` | No | 20.0 | Max ungradeable rate before alert (%) |
| `ALERT_THRESHOLD_DAYS` | No | 7 | Days to check for accuracy trend |
| `SEND_DAILY_SUMMARY` | No | false | Send daily summary (true/false) |

## Alert Types

### 🚨 Critical: Grading Failure
Sent when no grades are generated for yesterday.

**Possible causes**:
- Scheduled query failed
- No predictions exist
- Boxscores not ingested

### ⚠️ Warning: Accuracy Drop
Sent when system accuracy drops below threshold.

**Example**: ensemble_v1 at 52% (threshold: 55%)

### ⚠️ Warning: Data Quality
Sent when >20% predictions are ungradeable.

**Causes**: Missing boxscores, DNP players

### ℹ️ Info: Daily Summary
Optional daily report with all system stats.

## Monitoring

**Cloud Function Logs**:
```bash
gcloud functions logs read nba-grading-alerts --region=us-west2 --limit=50
```

**Scheduler Status**:
```bash
gcloud scheduler jobs describe nba-grading-alerts-daily --location=us-west2
```

**Manually Trigger**:
```bash
gcloud scheduler jobs run nba-grading-alerts-daily --location=us-west2
```

## Troubleshooting

**No alerts received**:
1. Check function logs for errors
2. Verify webhook URL is correct
3. Test webhook with curl (see SLACK-SETUP-GUIDE.md)

**Too many alerts**:
- Increase thresholds via environment variables
- Disable daily summary: `SEND_DAILY_SUMMARY=false`

**Alert shows wrong data**:
- Check BigQuery views exist and have data
- Verify scheduled query is running
- Check date math (timezone issues?)

## Files

- `main.py` - Cloud Function code
- `requirements.txt` - Python dependencies
- `.gcloudignore` - Files to exclude from deployment
- `README.md` - This file

## Related

- **Deployment**: `bin/alerts/deploy_nba_grading_alerts.sh`
- **Setup Guide**: `docs/08-projects/current/nba-grading-system/SLACK-SETUP-GUIDE.md`
- **Main Docs**: `docs/08-projects/current/nba-grading-system/`
