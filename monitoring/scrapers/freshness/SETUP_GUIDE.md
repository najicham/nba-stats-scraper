# Freshness Monitoring - Quick Setup Guide

## Prerequisites

- Google Cloud SDK installed and configured
- Python 3.11+
- Access to your GCP project
- Ball Don't Lie API key
- Slack webhooks (optional)
- Email credentials (optional)

## Step-by-Step Setup

### 1. Create Required Files

All the artifact files have been created. Now create the empty `__init__.py` files:

```bash
cd monitoring/scrapers/freshness

# Create __init__.py files
echo '"""Configuration module."""' > config/__init__.py
echo '"""Core monitoring logic."""' > core/__init__.py
echo '"""Utility functions."""' > utils/__init__.py
echo '"""Runner scripts."""' > runners/__init__.py
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example ../../.env  # Copy to project root

# Edit .env and add your actual values
vim ../../.env
```

**Required values:**
- `GCP_PROJECT_ID` - Your Google Cloud project ID
- `BALL_DONT_LIE_API_KEY` - Your Ball Don't Lie API key
- `SLACK_WEBHOOK_URL` - Your Slack webhook URL
- `EMAIL_ALERTS_TO` - Your email address for alerts

### 3. Review Configuration

Edit `config/monitoring_config.yaml` to match your scraper schedules:

```bash
vim config/monitoring_config.yaml
```

Key things to check:
- Scraper `enabled` flags
- `schedule.cron` matches your actual scraper schedules
- `path_pattern` matches your GCS structure
- `max_age_hours` thresholds are appropriate

### 4. Update Season Configuration

Edit `config/nba_schedule_config.yaml` for the current season:

```bash
vim config/nba_schedule_config.yaml
```

Update:
- Season dates for current year
- Special dates (All-Star break, etc.)

### 5. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Also install shared dependencies
pip install PyYAML requests google-cloud-storage
```

### 6. Test Locally

```bash
# Make scripts executable
chmod +x test-local.sh
chmod +x deploy.sh
chmod +x setup-scheduler.sh

# Run local tests
./test-local.sh
```

This will:
- Validate configuration files
- Check Python dependencies
- Run a dry-run test
- Validate YAML syntax

### 7. Deploy to Cloud Run

```bash
# Deploy the Cloud Run job
./deploy.sh
```

This will:
- Build Docker image
- Push to Container Registry
- Create/update Cloud Run job
- Set environment variables

### 8. Test Cloud Run Job

```bash
# Manually trigger the job
gcloud run jobs execute freshness-monitor --region=us-west2

# Watch the logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=freshness-monitor" \
  --limit=50 \
  --format=json
```

### 9. Set Up Scheduler

```bash
# Configure Cloud Scheduler to run hourly
./setup-scheduler.sh
```

This creates a Cloud Scheduler job that triggers the monitor every hour.

### 10. Verify Alerts

Wait for the next scheduled run (or trigger manually) and verify:

1. **Check Slack** - Should receive alerts in configured channel
2. **Check Email** - Should receive email alerts (if configured)
3. **Check Logs** - Review Cloud Run logs for any errors

### 11. Monitor Performance

```bash
# View recent runs
gcloud run jobs executions list freshness-monitor --region=us-west2

# View specific execution logs
gcloud logging read \
  "resource.type=cloud_run_job" \
  --limit=100 \
  --format='table(timestamp,jsonPayload.message)'
```

## Common Issues

### Issue: "No files found"

**Cause:** GCS path pattern doesn't match actual files

**Fix:** 
1. Check your GCS bucket structure
2. Update `path_pattern` in `monitoring_config.yaml`
3. Verify date formatting in paths

### Issue: "Configuration not found"

**Cause:** Config files not in expected location

**Fix:**
```bash
# Verify files exist
ls -la config/
```

### Issue: "API authentication failed"

**Cause:** Missing or invalid API credentials

**Fix:**
```bash
# Check environment variables
gcloud run jobs describe freshness-monitor \
  --region=us-west2 \
  --format='value(template.template.containers[0].env)'
```

### Issue: "No alerts received"

**Cause:** Notification system not configured

**Fix:**
1. Verify Slack webhooks are correct
2. Test webhooks manually:
   ```bash
   curl -X POST YOUR_WEBHOOK_URL \
     -H 'Content-Type: application/json' \
     -d '{"text":"Test message"}'
   ```

## Configuration Tips

### Adjusting Check Frequency

Edit `job-config.env`:

```bash
# Every hour (default)
SCHEDULE="0 * * * *"

# Every 30 minutes (more frequent)
SCHEDULE="*/30 * * * *"

# Specific times (6 AM, 9 AM, 12 PM, 3 PM, 6 PM)
SCHEDULE="0 6,9,12,15,18 * * *"
```

Then redeploy:
```bash
./setup-scheduler.sh
```

### Adding a New Scraper

1. Add to `config/monitoring_config.yaml`:
```yaml
scrapers:
  my_new_scraper:
    enabled: true
    gcs:
      bucket: "nba-raw-data"
      path_pattern: "my-data/{date}/*.json"
    schedule:
      cron: "0 6 * * *"
    freshness:
      max_age_hours:
        regular_season: 24
    validation:
      min_file_size_mb: 0.1
    seasonality:
      active_during: ["regular_season"]
      requires_games_today: false
    alerting:
      severity_missing: "warning"
```

2. No code changes needed!

3. Test locally:
```bash
./test-local.sh
```

4. Deploy:
```bash
./deploy.sh
```

### Season-Specific Thresholds

Different thresholds for different seasons:

```yaml
freshness:
  max_age_hours:
    regular_season: 24   # Strict during season
    preseason: 48        # More lenient in preseason
    playoffs: 12         # Very strict in playoffs
    offseason: 168       # 1 week OK in offseason
```

### Game-Day Only Scrapers

For scrapers that only run on game days:

```yaml
seasonality:
  requires_games_today: true  # Only check when games scheduled
```

## Maintenance

### Weekly Tasks

```bash
# Check recent alerts
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=WARNING" \
  --limit=50

# Review health scores
gcloud logging read \
  "resource.type=cloud_run_job AND jsonPayload.message:\"Health Score\"" \
  --limit=10
```

### Before Each Season

1. Update `config/nba_schedule_config.yaml` with new season dates
2. Review and update scraper schedules if changed
3. Test with dry-run
4. Deploy updates

## Support

- Check README.md for detailed documentation
- Review Cloud Run logs for errors
- Test locally before deploying
- Verify GCS paths match configuration

## Next Steps

After setup is complete:

1. **Monitor for a few days** - Watch for false positives
2. **Adjust thresholds** - Fine-tune based on actual behavior
3. **Add more scrapers** - As you add new data sources
4. **Set up dashboard** - Consider Looker Studio for visualization

## Success Criteria

✅ Cloud Run job runs successfully  
✅ Alerts arrive in Slack/Email  
✅ No false positives for 3 days  
✅ All critical scrapers monitored  
✅ Proper alerts for actual issues  

Congratulations! Your freshness monitoring is now live. 🎉
