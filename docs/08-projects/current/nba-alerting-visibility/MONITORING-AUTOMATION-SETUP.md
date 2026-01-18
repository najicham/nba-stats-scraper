# Monitoring Automation Setup

**Status**: ✅ FULLY AUTOMATED - Cloud Scheduler active
**Created**: 2026-01-17 (Session 83)
**Completed**: 2026-01-17 (Session 83 continuation)

---

## ✅ Current Status: FULLY AUTOMATED

**Cloud Scheduler is now active and running automatically!**

### What's Running

**Feature Staleness Monitor**:
- **Schedule**: Hourly (top of every hour)
- **Job**: `nba-monitor-feature-staleness`
- **Scheduler**: `nba-feature-staleness-monitor`
- **Status**: ✅ ENABLED and running

**Confidence Drift Monitor**:
- **Schedule**: Every 2 hours (top of even hours)
- **Job**: `nba-monitor-confidence-drift`
- **Scheduler**: `nba-confidence-drift-monitor`
- **Status**: ✅ ENABLED and running

### Verify Automation is Working

```bash
# Check scheduler status
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep nba-

# Check recent job executions
gcloud run jobs executions list --job=nba-monitor-feature-staleness --region=us-west2 --project=nba-props-platform --limit=3

gcloud run jobs executions list --job=nba-monitor-confidence-drift --region=us-west2 --project=nba-props-platform --limit=3

# Check logs
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="nba-monitor-feature-staleness"' --project=nba-props-platform --limit=5
```

---

## Overview

Two monitoring scripts have been created to automate Feature Pipeline Staleness and Confidence Distribution Drift checks:

1. **`bin/alerts/monitor_feature_staleness.sh`** - Checks if ml_feature_store_v2 is updating
2. **`bin/alerts/monitor_confidence_drift.sh`** - Checks for unusual confidence patterns

These scripts:
- Run BigQuery queries to check system health
- Write structured logs to Cloud Logging
- Trigger alerts via log-based metrics
- Can run manually or via Cloud Scheduler

---

## Alert Infrastructure (Already Created)

### Log-Based Metrics
- ✅ `nba_feature_pipeline_stale` - Detects stale feature warnings
- ✅ `nba_confidence_drift` - Detects confidence drift warnings

### Alert Policies
- ✅ `[WARNING] NBA Feature Pipeline Stale` (Policy ID: 16018926837468712704)
- ✅ `[WARNING] NBA Confidence Distribution Drift` (Policy ID: 5839862583446976986)

### Monitoring Scripts
- ✅ `/bin/alerts/monitor_feature_staleness.sh`
- ✅ `/bin/alerts/monitor_confidence_drift.sh`

---

## Manual Execution

You can run these scripts manually anytime:

```bash
# Check feature pipeline freshness
./bin/alerts/monitor_feature_staleness.sh

# Check confidence distribution
./bin/alerts/monitor_confidence_drift.sh
```

**Output**:
- `OK`: System is healthy (INFO log written)
- `WARNING`: Issue detected (WARNING log written, alert will fire)
- `CRITICAL`: Severe issue (ERROR log written, alert will fire immediately)

---

## Automated Execution via Cloud Scheduler (Optional)

To fully automate these checks, set up Cloud Scheduler jobs.

### Option 1: Quick Setup via gcloud (Recommended)

```bash
# Set variables
PROJECT="nba-props-platform"
REGION="us-west2"
SERVICE_ACCOUNT="nba-monitoring@nba-props-platform.iam.gserviceaccount.com"

# Create scheduler jobs that run the scripts via Cloud Run Jobs
# (Requires wrapping scripts in Docker containers - see Option 2)
```

### Option 2: Deploy as Cloud Run Jobs

**Step 1: Create Dockerfile for monitoring**

Create `monitoring/Dockerfile`:
```dockerfile
FROM google/cloud-sdk:slim

# Install bc for floating point comparisons
RUN apt-get update && apt-get install -y bc && rm -rf /var/lib/apt/lists/*

# Copy monitoring scripts
COPY bin/alerts/monitor_feature_staleness.sh /monitor_feature_staleness.sh
COPY bin/alerts/monitor_confidence_drift.sh /monitor_confidence_drift.sh

# Make scripts executable
RUN chmod +x /monitor_feature_staleness.sh /monitor_confidence_drift.sh

# Default command
ENTRYPOINT ["/bin/bash"]
```

**Step 2: Build and deploy**

```bash
# Build image
gcloud builds submit --tag gcr.io/nba-props-platform/nba-monitoring \
  --project=nba-props-platform

# Create Cloud Run Job for feature staleness
gcloud run jobs create nba-monitor-feature-staleness \
  --image gcr.io/nba-props-platform/nba-monitoring \
  --region=us-west2 \
  --project=nba-props-platform \
  --command="/monitor_feature_staleness.sh" \
  --max-retries=2 \
  --task-timeout=5m

# Create Cloud Run Job for confidence drift
gcloud run jobs create nba-monitor-confidence-drift \
  --image gcr.io/nba-props-platform/nba-monitoring \
  --region=us-west2 \
  --project=nba-props-platform \
  --command="/monitor_confidence_drift.sh" \
  --max-retries=2 \
  --task-timeout=5m
```

**Step 3: Create Cloud Scheduler jobs**

```bash
# Schedule feature staleness check (every hour)
gcloud scheduler jobs create http nba-feature-staleness-monitor \
  --location=us-west2 \
  --project=nba-props-platform \
  --schedule="0 * * * *" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/nba-monitor-feature-staleness:run" \
  --http-method=POST \
  --oauth-service-account-email="nba-monitoring@nba-props-platform.iam.gserviceaccount.com" \
  --time-zone="America/Los_Angeles"

# Schedule confidence drift check (every 2 hours)
gcloud scheduler jobs create http nba-confidence-drift-monitor \
  --location=us-west2 \
  --project=nba-props-platform \
  --schedule="0 */2 * * *" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/nba-monitor-confidence-drift:run" \
  --http-method=POST \
  --oauth-service-account-email="nba-monitoring@nba-props-platform.iam.gserviceaccount.com" \
  --time-zone="America/Los_Angeles"
```

### Option 3: Simple Cron on a VM

If you have a VM that's always running:

```bash
# Add to crontab
crontab -e

# Add these lines:
0 * * * * /path/to/nba-stats-scraper/bin/alerts/monitor_feature_staleness.sh >> /var/log/nba-monitoring.log 2>&1
0 */2 * * * /path/to/nba-stats-scraper/bin/alerts/monitor_confidence_drift.sh >> /var/log/nba-monitoring.log 2>&1
```

---

## How the Automation Works

### Architecture

```
Cloud Scheduler (hourly)
  ↓
Trigger monitoring script
  ↓
Run BigQuery query
  ↓
Check if metrics are healthy
  ↓
Write structured log to Cloud Logging
  ↓
Log-based metric increments (if WARNING/ERROR)
  ↓
Alert policy triggers
  ↓
Slack notification sent
```

### Log Structure

**Feature Staleness OK Log**:
```json
{
  "severity": "INFO",
  "message": "NBA_FEATURE_PIPELINE_HEALTHY",
  "hours_ago": 2,
  "player_count": 147,
  "status": "OK",
  "last_update": "2026-01-17 17:52:02"
}
```

**Feature Staleness WARNING Log**:
```json
{
  "severity": "WARNING",
  "message": "NBA_FEATURE_PIPELINE_STALE",
  "hours_ago": 5,
  "player_count": 147,
  "status": "WARNING",
  "reason": "Features are 5 hours old (threshold: 4 hours)",
  "last_update": "2026-01-17 14:52:02"
}
```

**Confidence Drift WARNING Log**:
```json
{
  "severity": "WARNING",
  "message": "NBA_CONFIDENCE_DRIFT_HIGH",
  "total_predictions": 150,
  "drift_pct": 35.0,
  "avg_confidence": 72.5,
  "min_confidence": 50.0,
  "max_confidence": 95.0,
  "fallback_count": 45,
  "status": "WARNING",
  "reason": "High drift: 35% outside normal range (threshold: 30%)"
}
```

---

## Testing the Automation

### Test Manually

```bash
# Run scripts manually to verify they work
./bin/alerts/monitor_feature_staleness.sh
./bin/alerts/monitor_confidence_drift.sh

# Check logs were written
gcloud logging read 'logName="projects/nba-props-platform/logs/nba-feature-staleness-monitor"' \
  --project=nba-props-platform \
  --limit=5

gcloud logging read 'logName="projects/nba-props-platform/logs/nba-confidence-drift-monitor"' \
  --project=nba-props-platform \
  --limit=5
```

### Test Cloud Scheduler (if set up)

```bash
# Trigger jobs manually
gcloud scheduler jobs run nba-feature-staleness-monitor \
  --location=us-west2 \
  --project=nba-props-platform

gcloud scheduler jobs run nba-confidence-drift-monitor \
  --location=us-west2 \
  --project=nba-props-platform

# Check job execution history
gcloud scheduler jobs describe nba-feature-staleness-monitor \
  --location=us-west2 \
  --project=nba-props-platform \
  --format="value(state,status.lastAttemptTime)"
```

---

## Monitoring the Monitors

### Check Script Execution Logs

```bash
# Feature staleness monitor logs
gcloud logging read 'logName="projects/nba-props-platform/logs/nba-feature-staleness-monitor"
  AND timestamp>="-24h"' \
  --project=nba-props-platform \
  --limit=20

# Confidence drift monitor logs
gcloud logging read 'logName="projects/nba-props-platform/logs/nba-confidence-drift-monitor"
  AND timestamp>="-24h"' \
  --project=nba-props-platform \
  --limit=20
```

### Check Alert Status

```bash
# List all NBA alerts
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter='displayName:"NBA"' \
  --format="table(displayName,enabled,conditions[0].displayName)"
```

---

## Cost Estimation

### Without Cloud Scheduler (Manual Only)
- **Cost**: $0/month
- **Effort**: Run scripts manually as needed

### With Cloud Scheduler + Cloud Run Jobs
- **Cloud Scheduler**: $0.10/month (2 jobs × $0.10/job)
- **Cloud Run Jobs**: ~$0.01/month (minimal execution time)
- **BigQuery**: ~$0.05/month (tiny queries, 60+ runs/day)
- **Cloud Logging**: ~$0.05/month (minimal log volume)
- **Total**: ~$0.21/month

**ROI**: Detecting a 4-hour-stale feature pipeline saves hours of debugging time.

---

## Troubleshooting

### Scripts Return Errors

**"bq: command not found"**:
```bash
# Install gcloud SDK and bq
# Already installed in Cloud Shell and Cloud Run with google/cloud-sdk image
```

**"Permission denied" when writing logs**:
```bash
# Ensure service account has roles/logging.logWriter
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:nba-monitoring@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"
```

### Alerts Not Firing

**Check metric is incrementing**:
```bash
# View metric values
gcloud monitoring time-series list \
  --filter='metric.type="logging.googleapis.com/user/nba_feature_pipeline_stale"' \
  --project=nba-props-platform
```

**Check alert policy**:
```bash
gcloud alpha monitoring policies describe <POLICY_ID> \
  --project=nba-props-platform
```

### Cloud Scheduler Jobs Failing

**Check job logs**:
```bash
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND resource.labels.job_id="nba-feature-staleness-monitor"' \
  --project=nba-props-platform \
  --limit=10
```

---

## Maintenance

### Update Thresholds

Edit the scripts directly:

```bash
# bin/alerts/monitor_feature_staleness.sh
THRESHOLD_HOURS=4  # Change to 6 for more lenient threshold

# bin/alerts/monitor_confidence_drift.sh
DRIFT_THRESHOLD=30  # Change to 40 for higher tolerance
LOOKBACK_HOURS=2    # Change to 4 for longer lookback window
```

### Disable Monitoring (Temporarily)

```bash
# Pause Cloud Scheduler jobs
gcloud scheduler jobs pause nba-feature-staleness-monitor \
  --location=us-west2 --project=nba-props-platform

gcloud scheduler jobs pause nba-confidence-drift-monitor \
  --location=us-west2 --project=nba-props-platform

# Or disable the alert policies
gcloud alpha monitoring policies update <POLICY_ID> \
  --no-enabled \
  --project=nba-props-platform
```

---

## Current Status

**As of 2026-01-17**:

- ✅ Monitoring scripts created and tested
- ✅ Log-based metrics created
- ✅ Alert policies created and enabled
- ⏳ Cloud Scheduler automation (optional - not yet set up)

**Recommendation**: Start with manual execution or set up Cloud Scheduler automation for hands-off monitoring.

---

**Last Updated**: 2026-01-17 (Session 83)
**Next Steps**: Optionally set up Cloud Scheduler automation using Option 2
