# Data Quality Alerts Cloud Function

Monitors critical data quality metrics and sends alerts when issues are detected.

## Purpose

This Cloud Function runs daily quality checks on the NBA predictions pipeline and alerts when issues are found. It was created in response to the 2026-01-26 incident where multiple data quality issues went undetected:
- 0 predictions generated
- 71% NULL usage_rate
- 93 duplicate records
- Betting lines arrived after Phase 3 processed

## Checks Performed

### 1. Zero Predictions Check (P0)
- **What:** Detects when no predictions are generated for a game day
- **Trigger:** players_predicted = 0 AND games_today > 0
- **Alert Level:** CRITICAL
- **Channel:** #app-error-alerts

### 2. Usage Rate Coverage Check (P1)
- **What:** Detects when player_game_summary has low usage_rate coverage
- **Trigger:** coverage < 80% after all games complete
- **Alert Level:** WARNING (< 80%), CRITICAL (< 50%)
- **Channel:** #nba-alerts or #app-error-alerts

### 3. Duplicate Detection Check (P2)
- **What:** Detects duplicate records in player_game_summary
- **Trigger:** Any (player_lookup, game_id) with count > 1
- **Alert Level:** INFO (≤5), WARNING (≤20), CRITICAL (>20)
- **Channel:** #nba-alerts or #app-error-alerts

### 4. Prop Lines Check (P1)
- **What:** Detects when players are missing betting lines
- **Trigger:** has_prop_line = FALSE for most/all players
- **Alert Level:** CRITICAL (0%), WARNING (<50%), INFO (<80%)
- **Channel:** #nba-alerts or #app-error-alerts

## Deployment

### Prerequisites

1. Set environment variables:
   ```bash
   export SLACK_WEBHOOK_URL_ERROR="https://hooks.slack.com/services/..."  # #app-error-alerts
   export SLACK_WEBHOOK_URL_WARNING="https://hooks.slack.com/services/..." # #nba-alerts
   ```

2. Ensure GCP project is set:
   ```bash
   gcloud config set project nba-props-platform
   ```

### Deploy Function

```bash
# Make deploy script executable
chmod +x deploy.sh

# Deploy to production
./deploy.sh prod

# Or deploy to dev
./deploy.sh dev
```

### Manual Deployment

```bash
gcloud functions deploy data-quality-alerts \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source . \
    --entry-point check_data_quality \
    --trigger-http \
    --allow-unauthenticated \
    --timeout=540 \
    --memory=512MB \
    --set-env-vars GCP_PROJECT_ID=nba-props-platform,SLACK_WEBHOOK_URL_ERROR=...,SLACK_WEBHOOK_URL_WARNING=... \
    --project nba-props-platform
```

### Setup Cloud Scheduler

```bash
# Get function URL
FUNCTION_URL=$(gcloud functions describe data-quality-alerts --gen2 --region us-west2 --format="value(serviceConfig.uri)")

# Create scheduler job (runs daily at 7 PM ET)
gcloud scheduler jobs create http data-quality-alerts-job \
    --schedule "0 19 * * *" \
    --time-zone "America/New_York" \
    --uri $FUNCTION_URL \
    --http-method GET \
    --location us-west2 \
    --description "Daily data quality checks for NBA predictions pipeline"

# Test the job
gcloud scheduler jobs run data-quality-alerts-job --location=us-west2
```

## Usage

### Test with Dry Run

```bash
# Get function URL
FUNCTION_URL=$(gcloud functions describe data-quality-alerts --gen2 --region us-west2 --format="value(serviceConfig.uri)")

# Test all checks (no alerts sent)
curl "$FUNCTION_URL?game_date=2026-01-26&dry_run=true"

# Test specific checks
curl "$FUNCTION_URL?checks=zero_predictions,prop_lines&dry_run=true"

# Test with today's data
curl "$FUNCTION_URL?dry_run=true"
```

### Run for Real

```bash
# Run all checks and send alerts
curl "$FUNCTION_URL?game_date=2026-01-26"

# Run for today
curl "$FUNCTION_URL"
```

### Query Parameters

- `game_date` (optional): Date to check in YYYY-MM-DD format. Default: today
- `dry_run` (optional): If 'true', run checks but don't send alerts. Default: false
- `checks` (optional): Comma-separated list of checks to run. Default: all
  - Valid values: `zero_predictions`, `usage_rate`, `duplicates`, `prop_lines`

### Response Format

```json
{
  "game_date": "2026-01-26",
  "timestamp": "2026-01-27T12:00:00Z",
  "overall_status": "CRITICAL",
  "checks_run": 4,
  "critical_issues": 2,
  "warnings": 1,
  "results": {
    "zero_predictions": {
      "level": "CRITICAL",
      "message": "ZERO PREDICTIONS: No predictions generated...",
      "details": {
        "players_predicted": 0,
        "eligible_players": 180,
        "games_today": 6
      }
    },
    "usage_rate": {
      "level": "WARNING",
      "message": "LOW COVERAGE: Only 71.3% of records have usage_rate...",
      "details": {
        "total_records": 320,
        "with_usage_rate": 228,
        "coverage_percent": 71.25
      }
    }
  },
  "alerts_sent": ["zero_predictions", "prop_lines"],
  "dry_run": false
}
```

## Monitoring

### View Function Logs

```bash
# Recent logs
gcloud functions logs read data-quality-alerts --gen2 --region us-west2 --limit 50

# Follow logs
gcloud functions logs read data-quality-alerts --gen2 --region us-west2 --limit 50 --follow

# Filter errors
gcloud functions logs read data-quality-alerts --gen2 --region us-west2 --limit 50 | grep ERROR
```

### Check Function Status

```bash
# Describe function
gcloud functions describe data-quality-alerts --gen2 --region us-west2

# Check recent invocations
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=data-quality-alerts" --limit 10
```

### View Scheduler Jobs

```bash
# List jobs
gcloud scheduler jobs list --location=us-west2

# Describe job
gcloud scheduler jobs describe data-quality-alerts-job --location=us-west2

# View recent runs
gcloud scheduler jobs describe data-quality-alerts-job --location=us-west2 --format="table(status.code,status.message,status.time)"
```

## Testing

### Test with Known Issues (2026-01-26)

```bash
# Should trigger multiple alerts
curl "$FUNCTION_URL?game_date=2026-01-26&dry_run=true"
```

Expected results:
- Zero Predictions: CRITICAL
- Usage Rate: WARNING
- Duplicates: WARNING
- Prop Lines: CRITICAL

### Test with Recent Good Data

```bash
# Should be all OK
curl "$FUNCTION_URL?game_date=2026-01-25&dry_run=true"
```

### Test Individual Checks

```bash
# Test only zero predictions check
curl "$FUNCTION_URL?checks=zero_predictions&dry_run=true"

# Test only duplicates check
curl "$FUNCTION_URL?checks=duplicates&dry_run=true"
```

### Run SQL Queries Manually

```bash
cd ../../../monitoring/queries

# Test zero predictions query
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < zero_predictions.sql

# Test low usage coverage query
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < low_usage_coverage.sql

# Test duplicate detection query
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < duplicate_detection.sql

# Test prop lines query
bq query --use_legacy_sql=false \
  --parameter=game_date:DATE:2026-01-26 \
  < prop_lines_missing.sql
```

## Troubleshooting

### Function Not Sending Alerts

1. Check environment variables:
   ```bash
   gcloud functions describe data-quality-alerts --gen2 --region us-west2 --format="value(serviceConfig.environmentVariables)"
   ```

2. Verify Slack webhooks are configured:
   - SLACK_WEBHOOK_URL_ERROR should be set
   - SLACK_WEBHOOK_URL_WARNING should be set

3. Test with dry_run=false to confirm alerts work

### Queries Timing Out

1. Check BigQuery quota:
   ```bash
   gcloud alpha billing quotas list --consumer="projects/nba-props-platform" | grep bigquery
   ```

2. Optimize queries if needed (add table partitioning filters)

3. Increase function timeout (max 540s)

### False Positives

1. Review alert thresholds in code
2. Adjust thresholds based on historical data
3. Add timing checks (e.g., don't alert if games just finished)

### Scheduler Not Triggering

1. Check scheduler job status:
   ```bash
   gcloud scheduler jobs describe data-quality-alerts-job --location=us-west2
   ```

2. Manually trigger job:
   ```bash
   gcloud scheduler jobs run data-quality-alerts-job --location=us-west2
   ```

3. Check scheduler logs:
   ```bash
   gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=data-quality-alerts-job" --limit 10
   ```

## Cost Estimate

- **BigQuery:** ~400 MB scanned per day = $0.002/day = $0.73/year
- **Cloud Function:** 1 invocation per day × 10 seconds = Free (within free tier)
- **Cloud Scheduler:** 1 job = $0.10/month = $1.20/year
- **Total:** ~$2/year

ROI: One prevented incident saves hours of investigation time and prevents user impact.

## Related Documentation

- [Monitoring Plan](../../../docs/08-projects/current/2026-01-27-data-quality-investigation/MONITORING-PLAN.md)
- [Root Cause Analysis](../../../docs/08-projects/current/2026-01-27-data-quality-investigation/2026-01-27-root-cause-analysis.md)
- [SQL Queries](../../../monitoring/queries/)

## Changelog

- **2026-01-27:** Initial version
  - Created function with 4 quality checks
  - Added Slack alerting
  - Configured scheduler for daily runs

## Future Enhancements

- [ ] Auto-remediation (e.g., re-trigger Phase 3 when prop lines missing)
- [ ] Historical alert tracking in BigQuery
- [ ] Dashboard for alert trends
- [ ] Coordinator stuck detection
- [ ] Processing order violation detection
- [ ] Integration with existing prediction_health_alert
