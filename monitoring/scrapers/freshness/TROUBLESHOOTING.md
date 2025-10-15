# Freshness Monitoring - Troubleshooting Guide

## Quick Diagnostics

### Check Overall System Status

```bash
./check-status.sh
```

This shows:
- Cloud Run job status
- Scheduler status
- Recent logs
- Configuration files
- Environment variables

### Test Specific Scraper

```bash
./test-scraper.py odds_api_player_props --verbose
```

This shows:
- Scraper configuration
- Current season context
- File freshness details
- Specific recommendations

### List All Scrapers

```bash
./test-scraper.py --list
```

## Common Issues

### Issue 1: "No files found matching pattern"

**Symptoms:**
- Alert: "No files found"
- Scraper shows as CRITICAL or WARNING
- Cloud Run logs show "No files found"

**Causes:**
1. Path pattern doesn't match actual GCS structure
2. Scraper hasn't run yet
3. Wrong bucket name
4. Scraper failed silently

**Diagnosis:**

```bash
# Check actual GCS structure
gsutil ls gs://nba-raw-data/odds-api/events/

# Check if pattern matches
./test-scraper.py odds_api_events --verbose

# Verify path pattern
cat config/monitoring_config.yaml | grep -A 3 "odds_api_events"
```

**Solution:**

1. **Update path pattern:**
   ```yaml
   # In monitoring_config.yaml
   gcs:
     path_pattern: "odds-api/events/{date}/*.json"  # Fix pattern
   ```

2. **Sync paths with GCS Path Builder:**
   ```bash
   ./sync-gcs-paths.py --apply
   ```

3. **Verify scraper is running:**
   - Check scraper Cloud Run logs
   - Manually trigger scraper
   - Verify scraper schedule

---

### Issue 2: "Data stale" false positives

**Symptoms:**
- Getting alerts but data is actually fresh
- Alerts during offseason or preseason
- Alerts for game-day scrapers when no games

**Causes:**
1. Thresholds too strict for season
2. Game-day scraper checked when no games
3. Scraper schedule changed but config not updated

**Diagnosis:**

```bash
# Check season phase and thresholds
./test-scraper.py your_scraper --verbose

# Check if games today
python3 -c "from monitoring.scrapers.freshness.utils.nba_schedule_api import has_games_today; print(has_games_today())"
```

**Solution:**

1. **Adjust season-specific thresholds:**
   ```yaml
   freshness:
     max_age_hours:
       regular_season: 24
       preseason: 48      # More lenient
       playoffs: 12
       offseason: 168     # Much more lenient
   ```

2. **Mark game-dependent scrapers:**
   ```yaml
   seasonality:
     requires_games_today: true  # Only check when games scheduled
   ```

3. **Update season dates:**
   ```bash
   vim config/nba_schedule_config.yaml
   # Update dates for current season
   ```

---

### Issue 3: No alerts received

**Symptoms:**
- Monitor runs successfully in logs
- No Slack or email alerts
- Issues exist but not notified

**Causes:**
1. Notification environment variables not set
2. Webhook URLs incorrect
3. Email credentials wrong
4. All scrapers healthy (nothing to alert)

**Diagnosis:**

```bash
# Check environment variables in Cloud Run
gcloud run jobs describe freshness-monitor \
  --region=us-west2 \
  --format='value(template.template.containers[0].env)'

# Test notification system locally
python3 << 'EOF'
from shared.utils.notification_system import notify_warning
notify_warning(
    title="Test Alert",
    message="Testing freshness monitoring notifications",
    details={'test': True}
)
EOF
```

**Solution:**

1. **Verify environment variables:**
   ```bash
   # In .env file
   SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK"
   EMAIL_ALERTS_TO="your-email@example.com"
   ```

2. **Redeploy with correct variables:**
   ```bash
   ./deploy.sh
   ```

3. **Test webhooks manually:**
   ```bash
   # Test Slack webhook
   curl -X POST $SLACK_WEBHOOK_URL \
     -H 'Content-Type: application/json' \
     -d '{"text":"Test from freshness monitor"}'
   ```

---

### Issue 4: "File too small" warnings

**Symptoms:**
- Alert: "File too small: X MB < Y MB"
- Files exist but flagged as suspicious

**Causes:**
1. Scraper returned empty or partial data
2. API returned minimal response
3. Threshold too high for actual data size

**Diagnosis:**

```bash
# Check actual file size
./test-scraper.py your_scraper --verbose

# Download and inspect file
gsutil cp gs://nba-raw-data/path/to/file.json .
cat file.json | jq '.'
```

**Solution:**

1. **Adjust minimum size threshold:**
   ```yaml
   validation:
     min_file_size_mb: 0.01  # Lower threshold
   ```

2. **Check scraper for errors:**
   - Review scraper logs
   - Verify API is returning data
   - Check API rate limits

---

### Issue 5: Scheduler not triggering job

**Symptoms:**
- No recent executions
- Scheduler exists but job not running
- Expected hourly runs but none happening

**Causes:**
1. Scheduler paused
2. Scheduler misconfigured
3. IAM permissions issue
4. Wrong region

**Diagnosis:**

```bash
# Check scheduler status
gcloud scheduler jobs describe freshness-monitor-hourly \
  --location=us-west2 \
  --format='value(state,schedule)'

# Check recent scheduler runs
gcloud logging read \
  "resource.type=cloud_scheduler_job" \
  --limit=10
```

**Solution:**

1. **Resume scheduler if paused:**
   ```bash
   gcloud scheduler jobs resume freshness-monitor-hourly \
     --location=us-west2
   ```

2. **Manually trigger to test:**
   ```bash
   gcloud scheduler jobs run freshness-monitor-hourly \
     --location=us-west2
   ```

3. **Recreate scheduler:**
   ```bash
   ./setup-scheduler.sh
   ```

---

### Issue 6: "Season phase detection incorrect"

**Symptoms:**
- Monitor thinks it's wrong season
- Thresholds not adjusting correctly
- Offseason alerts during season

**Causes:**
1. Season dates not updated
2. System date/timezone issues
3. Config file corrupted

**Diagnosis:**

```bash
# Check current season detection
python3 << 'EOF'
from monitoring.scrapers.freshness.core.season_manager import SeasonManager
from pathlib import Path
manager = SeasonManager('config/nba_schedule_config.yaml')
print(manager.get_summary())
EOF
```

**Solution:**

1. **Update season configuration:**
   ```bash
   vim config/nba_schedule_config.yaml
   # Update dates for current season
   ```

2. **Verify dates are correct:**
   ```yaml
   "2024-25":
     regular_season:
       start_date: "2024-10-22"  # Verify this is correct
       end_date: "2025-04-13"
   ```

---

### Issue 7: High memory usage or timeouts

**Symptoms:**
- Cloud Run job times out
- Out of memory errors
- Slow execution

**Causes:**
1. Too many scrapers checked at once
2. Large GCS bucket listings
3. Memory leak

**Diagnosis:**

```bash
# Check execution time in logs
gcloud logging read \
  "resource.type=cloud_run_job AND jsonPayload.message:duration" \
  --limit=10

# Check memory usage
gcloud run jobs describe freshness-monitor \
  --region=us-west2 \
  --format='value(template.template.containers[0].resources)'
```

**Solution:**

1. **Increase resources:**
   ```bash
   # Edit job-config.env
   MEMORY="1Gi"     # Increase from 512Mi
   CPU="2"          # Increase from 1
   
   # Redeploy
   ./deploy.sh
   ```

2. **Optimize scraper list:**
   - Disable unused scrapers in config
   - Split into multiple monitoring jobs if needed

---

## Debug Commands

### View Recent Logs

```bash
# Last 50 log entries
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=freshness-monitor" \
  --limit=50 \
  --format='table(timestamp,severity,jsonPayload.message)'

# Follow logs in real-time
gcloud logging tail \
  "resource.type=cloud_run_job" \
  --log-filter='resource.labels.job_name="freshness-monitor"'
```

### Test Individual Components

```bash
# Test season manager
python3 -c "
from monitoring.scrapers.freshness.core.season_manager import SeasonManager
manager = SeasonManager('config/nba_schedule_config.yaml')
print(manager.get_summary())
"

# Test schedule API
python3 -c "
from monitoring.scrapers.freshness.utils.nba_schedule_api import has_games_today
print('Games today:', has_games_today())
"

# Test GCS access
python3 -c "
from google.cloud import storage
client = storage.Client()
bucket = client.bucket('nba-raw-data')
blobs = list(bucket.list_blobs(prefix='odds-api/events/', max_results=5))
print(f'Found {len(blobs)} files')
"
```

### Manual Job Execution

```bash
# Run job manually
gcloud run jobs execute freshness-monitor \
  --region=us-west2 \
  --wait

# Run with dry-run (no alerts)
gcloud run jobs execute freshness-monitor \
  --region=us-west2 \
  --args="--dry-run" \
  --wait
```

### Validate Configuration

```bash
# Check YAML syntax
python3 -c "import yaml; yaml.safe_load(open('config/monitoring_config.yaml'))"

# Count enabled scrapers
grep -c "enabled: true" config/monitoring_config.yaml

# List all scrapers
grep "^  [a-z_]" config/monitoring_config.yaml
```

## Getting Help

### Information to Gather

When reporting issues, include:

1. **Error messages** from Cloud Run logs
2. **Scraper name** that's having issues
3. **Expected vs actual behavior**
4. **Recent changes** to configuration
5. **Output of `./check-status.sh`**
6. **Output of `./test-scraper.py <scraper> --verbose`**

### Useful Log Queries

```bash
# All errors in last hour
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=ERROR" \
  --format=json \
  --limit=100

# All CRITICAL status checks
gcloud logging read \
  "resource.type=cloud_run_job AND jsonPayload.message:CRITICAL" \
  --limit=20

# Execution durations
gcloud logging read \
  "resource.type=cloud_run_job AND jsonPayload.message:complete" \
  --format='table(timestamp,jsonPayload.summary.health_score)'
```

## Prevention

### Regular Maintenance

**Weekly:**
- Review `./check-status.sh` output
- Check for new false positives
- Verify alert delivery

**Monthly:**
- Update season configuration if needed
- Review and adjust thresholds
- Update scraper list as needed

**Before Each Season:**
- Update `nba_schedule_config.yaml` dates
- Test with dry-run
- Verify all scrapers are configured correctly

### Best Practices

1. **Always test locally** before deploying
2. **Use dry-run mode** when testing changes
3. **Keep configuration in version control**
4. **Document custom thresholds**
5. **Monitor false positive rate**
6. **Update paths when scrapers change**

## Emergency Procedures

### Stop All Monitoring

```bash
# Pause scheduler
gcloud scheduler jobs pause freshness-monitor-hourly \
  --location=us-west2
```

### Resume Monitoring

```bash
# Resume scheduler
gcloud scheduler jobs resume freshness-monitor-hourly \
  --location=us-west2
```

### Rollback to Previous Version

```bash
# List recent revisions
gcloud run jobs describe freshness-monitor \
  --region=us-west2 \
  --format='value(template.metadata.name)'

# Deploy previous image
# (Keep previous image tags for rollback)
```

## Still Stuck?

1. Check README.md for architecture overview
2. Review SETUP_GUIDE.md for configuration details
3. Test individual components with test scripts
4. Check Cloud Run logs for detailed errors
5. Verify environment variables are set correctly
