# Next Steps - Get Freshness Monitoring Running

## 📋 Immediate Actions (30 minutes)

### Step 1: Create Required Files (2 minutes)

```bash
cd monitoring/scrapers/freshness

# Create __init__.py files
echo '"""Configuration module."""' > config/__init__.py
echo '"""Core monitoring logic."""' > core/__init__.py
echo '"""Utility functions."""' > utils/__init__.py
echo '"""Runner scripts."""' > runners/__init__.py

# Make scripts executable
chmod +x *.sh *.py
```

### Step 2: Configure Environment (5 minutes)

```bash
# Copy template to project root
cp .env.example ../../../.env

# Edit with your actual values
vim ../../../.env
```

**Critical values to add:**
```bash
GCP_PROJECT_ID="nba-props-platform"           # Your project ID
REGION="us-west2"                              # Your region

# Ball Don't Lie API
BALL_DONT_LIE_API_KEY="your-api-key-here"     # Required for schedule

# Slack (uses your existing webhooks)
SLACK_ALERTS_ENABLED="true"
SLACK_WEBHOOK_URL="your-default-webhook"
SLACK_WEBHOOK_URL_ERROR="your-error-webhook"
SLACK_WEBHOOK_URL_CRITICAL="your-critical-webhook"

# Email (uses your existing Brevo config)
EMAIL_ALERTS_ENABLED="true"
EMAIL_ALERTS_TO="your-email@example.com"
BREVO_SMTP_HOST="smtp-relay.brevo.com"
BREVO_SMTP_USERNAME="your-username"
BREVO_SMTP_PASSWORD="your-password"
BREVO_FROM_EMAIL="alert@yourdomain.com"
```

### Step 3: Review Configuration (10 minutes)

```bash
# Review scraper definitions
vim config/monitoring_config.yaml
```

**Check for your scrapers:**
- Are all your scrapers listed?
- Do the GCS paths match your actual paths?
- Are the schedules correct?
- Are thresholds appropriate?

**Update paths if needed:**
```bash
# Sync with GCS path builder
python3 sync-gcs-paths.py

# Review suggested changes
python3 sync-gcs-paths.py --apply  # Apply if they look good
```

### Step 4: Update Season Dates (3 minutes)

```bash
vim config/nba_schedule_config.yaml
```

**Verify:**
- Current season label is correct (2024-25)
- Season dates are accurate
- Special dates are current

### Step 5: Install Dependencies (2 minutes)

```bash
# Install Python packages
pip install -r requirements.txt

# Install shared dependencies (if not already)
pip install PyYAML requests google-cloud-storage
```

### Step 6: Test Locally (5 minutes)

```bash
# Run comprehensive tests
./test-local.sh
```

**This will check:**
- Configuration files exist
- Python dependencies installed
- Monitoring can run
- Configuration is valid

**If tests fail:**
- Check error messages
- Fix issues mentioned
- Re-run `./test-local.sh`

### Step 7: Deploy (3 minutes)

```bash
# Deploy to Cloud Run
./deploy.sh
```

**What this does:**
- Builds Docker image
- Pushes to Container Registry
- Creates Cloud Run job
- Sets environment variables

**Watch for errors** - most common issues:
- Missing environment variables
- GCP permissions
- Build failures

### Step 8: Test Cloud Deployment (2 minutes)

```bash
# Manually trigger the job
gcloud run jobs execute freshness-monitor --region=us-west2 --wait

# Check the logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=freshness-monitor" \
  --limit=20 \
  --format='table(timestamp,severity,jsonPayload.message)'
```

**Expected output:**
- Job runs successfully
- Checks all scrapers
- Reports health score
- Sends alerts if any issues

### Step 9: Set Up Scheduler (1 minute)

```bash
# Configure hourly runs
./setup-scheduler.sh
```

**This creates:**
- Cloud Scheduler job
- Runs every hour
- Triggers your monitoring

### Step 10: Verify Everything Works (2 minutes)

```bash
# Check system status
./check-status.sh
```

**Should show:**
- ✅ Job exists
- ✅ Scheduler enabled
- ✅ Recent logs
- ✅ Config files present
- ✅ Environment variables set

---

## ✅ Verification Checklist

After completing setup, verify:

- [ ] Local tests pass (`./test-local.sh`)
- [ ] Cloud Run job deployed successfully
- [ ] Manual job execution works
- [ ] Logs show health score
- [ ] Scheduler is enabled and running
- [ ] Received test alert in Slack/Email
- [ ] `./check-status.sh` shows all green
- [ ] Can test individual scrapers (`./test-scraper.py <name>`)

---

## 🔍 What to Monitor (First Week)

### Daily (First 3 Days)

```bash
# Check system status
./check-status.sh

# Review recent alerts
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=WARNING" \
  --limit=20
```

**Look for:**
- False positives (alerts that shouldn't trigger)
- Missing alerts (issues not caught)
- Health score trends

### Adjust as Needed

**If getting too many alerts:**
```yaml
# In monitoring_config.yaml
freshness:
  max_age_hours:
    regular_season: 36  # Increase threshold
```

**If scraper not checked on game days:**
```yaml
seasonality:
  requires_games_today: true  # Add this
```

**If offseason alerts:**
```yaml
freshness:
  max_age_hours:
    offseason: 168  # 1 week is OK
```

Then redeploy:
```bash
./deploy.sh
```

---

## 📚 Resources to Bookmark

1. **QUICK_REFERENCE.md** - Most-used commands
2. **TROUBLESHOOTING.md** - When things go wrong
3. **README.md** - Full documentation
4. **monitoring_config.yaml** - Scraper configuration

---

## 🎯 Success Metrics (After 1 Week)

By the end of week 1, you should have:

- ✅ Zero false positives (or thresholds adjusted)
- ✅ Caught at least one real issue
- ✅ Team comfortable checking status
- ✅ Health score consistently >80%
- ✅ Alert response process established

---

## 🆘 If Something Goes Wrong

### Can't deploy?
```bash
# Check GCP authentication
gcloud auth list

# Check project
gcloud config get-value project

# Check permissions
gcloud projects get-iam-policy $GCP_PROJECT_ID
```

### No alerts received?
```bash
# Test notification system directly
python3 << 'EOF'
from shared.utils.notification_system import notify_warning
notify_warning(
    title="Test Alert",
    message="Testing from freshness monitor",
    details={'test': True}
)
EOF
```

### Job fails to run?
```bash
# Check detailed logs
gcloud logging read \
  "resource.type=cloud_run_job" \
  --limit=50 \
  --format=json

# Try dry-run locally
python3 runners/scheduled_monitor.py --dry-run --test
```

### Still stuck?
1. Check TROUBLESHOOTING.md
2. Review error messages in logs
3. Test components individually
4. Verify configuration syntax

---

## 🎉 You're Done When...

- ✅ `./check-status.sh` shows all green
- ✅ Scheduler running hourly
- ✅ Receiving alerts (in Slack/Email)
- ✅ Can test scrapers individually
- ✅ Team knows how to check status

**Congratulations!** Your freshness monitoring is now protecting your data pipeline.

---

## 📞 Quick Commands for Daily Use

```bash
# Morning check
./check-status.sh

# Test problematic scraper
./test-scraper.py odds_api_player_props --verbose

# View recent logs
gcloud logging read "resource.type=cloud_run_job" --limit=20

# Manual trigger
gcloud run jobs execute freshness-monitor --region=us-west2
```

---

**Ready to start?** Begin with Step 1 above! ⬆️
