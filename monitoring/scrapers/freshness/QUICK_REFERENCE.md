# Freshness Monitoring - Quick Reference

## 🚀 Quick Start

```bash
# 1. Setup
cp .env.example ../../.env
vim ../../.env  # Add your credentials

# 2. Test locally
./test-local.sh

# 3. Deploy
./deploy.sh

# 4. Setup scheduler
./setup-scheduler.sh

# 5. Check status
./check-status.sh
```

## 📋 Common Commands

### Status & Monitoring

```bash
# Check system status
./check-status.sh

# Test specific scraper
./test-scraper.py odds_api_player_props --verbose

# List all scrapers
./test-scraper.py --list

# Check recent logs
gcloud logging read \
  "resource.type=cloud_run_job" \
  --limit=50
```

### Testing

```bash
# Test everything locally
./test-local.sh

# Test with dry-run (no alerts)
python3 runners/scheduled_monitor.py --dry-run

# Test with verbose output
python3 runners/scheduled_monitor.py --test

# Sync GCS paths
./sync-gcs-paths.py --apply
```

### Deployment

```bash
# Deploy changes
./deploy.sh

# Update scheduler
./setup-scheduler.sh

# Manually trigger job
gcloud run jobs execute freshness-monitor --region=us-west2
```

### Logs & Debugging

```bash
# Follow logs in real-time
gcloud logging tail "resource.type=cloud_run_job"

# View errors only
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=ERROR" \
  --limit=20

# Check specific scraper
./test-scraper.py your_scraper --verbose
```

### Scheduler Control

```bash
# Pause monitoring
gcloud scheduler jobs pause freshness-monitor-hourly --location=us-west2

# Resume monitoring
gcloud scheduler jobs resume freshness-monitor-hourly --location=us-west2

# Trigger manually
gcloud scheduler jobs run freshness-monitor-hourly --location=us-west2
```

## 📁 Key Files

| File | Purpose |
|------|---------|
| `config/monitoring_config.yaml` | Scraper definitions & thresholds |
| `config/nba_schedule_config.yaml` | Season dates & phases |
| `job-config.env` | Cloud Run job settings |
| `../../.env` | Environment variables (secrets) |

## ⚙️ Configuration Quick Edits

### Add a New Scraper

```yaml
# In config/monitoring_config.yaml
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

### Adjust Alert Schedule

```bash
# Edit job-config.env
SCHEDULE="0 * * * *"          # Every hour (default)
SCHEDULE="0 */2 * * *"        # Every 2 hours
SCHEDULE="0 6,12,18 * * *"    # 6 AM, 12 PM, 6 PM only

# Apply changes
./setup-scheduler.sh
```

### Change Thresholds

```yaml
# In config/monitoring_config.yaml
freshness:
  max_age_hours:
    regular_season: 24    # Adjust these
    preseason: 48
    playoffs: 12
    offseason: 168
```

## 🔔 Alert Severity

| Level | Meaning | Action |
|-------|---------|--------|
| **CRITICAL** 🔴 | Data missing or very stale | Immediate action |
| **WARNING** 🟡 | Data getting old | Investigate soon |
| **INFO** 🔵 | All healthy | No action needed |

## 🎯 Troubleshooting Flowchart

```
Alert received?
  ├─ No alerts → Check notification config (.env)
  │              Test: ./test-scraper.py <scraper>
  │
  ├─ False positive → Adjust thresholds or season config
  │                   Check: requires_games_today setting
  │
  └─ Real issue → Check scraper logs
                  Verify GCS path
                  Manually trigger scraper
```

## 📊 Understanding Status

| Status | Meaning | Example |
|--------|---------|---------|
| `OK` ✅ | Fresh data | File < 24h old |
| `WARNING` 🟡 | Stale data | File 24-48h old |
| `CRITICAL` 🔴 | Very stale/missing | File >48h or missing |
| `SKIPPED` ⏭️ | Not checked | No games today, offseason |
| `ERROR` ❌ | Check failed | Config or GCS error |

## 🔧 Environment Variables

### Required

```bash
GCP_PROJECT_ID="your-project-id"
BALL_DONT_LIE_API_KEY="your-api-key"
```

### Slack Alerts

```bash
SLACK_ALERTS_ENABLED="true"
SLACK_WEBHOOK_URL="https://hooks.slack.com/..."
SLACK_WEBHOOK_URL_ERROR="https://hooks.slack.com/..."     # Optional
SLACK_WEBHOOK_URL_CRITICAL="https://hooks.slack.com/..."  # Optional
```

### Email Alerts

```bash
EMAIL_ALERTS_ENABLED="true"
EMAIL_ALERTS_TO="your-email@example.com"
BREVO_SMTP_HOST="smtp-relay.brevo.com"
BREVO_SMTP_USERNAME="your-username"
BREVO_SMTP_PASSWORD="your-password"
```

## 🎮 Interactive Testing

```bash
# Test everything
./test-local.sh

# Test one scraper
./test-scraper.py odds_api_player_props

# Dry run (no alerts)
python3 runners/scheduled_monitor.py --dry-run

# Check what would alert
python3 runners/scheduled_monitor.py --test | grep "CRITICAL\|WARNING"
```

## 📞 Quick Diagnostics

```bash
# Is job deployed?
gcloud run jobs describe freshness-monitor --region=us-west2

# Is scheduler active?
gcloud scheduler jobs describe freshness-monitor-hourly --location=us-west2

# Recent executions?
gcloud run jobs executions list freshness-monitor --region=us-west2 --limit=5

# Any errors?
gcloud logging read "resource.type=cloud_run_job AND severity>=ERROR" --limit=10

# Health score trend?
gcloud logging read \
  "resource.type=cloud_run_job AND jsonPayload.message:\"Health Score\"" \
  --limit=10 \
  --format='value(jsonPayload.summary.health_score)'
```

## 🔄 Maintenance Schedule

**Daily:** Check `./check-status.sh`

**Weekly:** Review alerts, adjust false positives

**Monthly:** Update thresholds if needed

**Seasonally:** Update `nba_schedule_config.yaml`

## 💡 Pro Tips

1. **Always test locally first**: `./test-local.sh`
2. **Use dry-run for testing**: `--dry-run` flag
3. **Test single scrapers**: `./test-scraper.py <name>`
4. **Check GCS directly**: `gsutil ls gs://bucket/path/`
5. **Verify dates in config**: Season start/end dates
6. **Keep paths synced**: `./sync-gcs-paths.py`

## 🆘 Emergency Commands

```bash
# Stop monitoring immediately
gcloud scheduler jobs pause freshness-monitor-hourly --location=us-west2

# Resume monitoring
gcloud scheduler jobs resume freshness-monitor-hourly --location=us-west2

# Force run now
gcloud run jobs execute freshness-monitor --region=us-west2 --wait

# Check what's wrong
./check-status.sh
./test-scraper.py --list
```

## 📚 Documentation

- **README.md** - Full documentation
- **SETUP_GUIDE.md** - Step-by-step setup
- **TROUBLESHOOTING.md** - Common issues & solutions
- **QUICK_REFERENCE.md** - This file

## 🎯 Success Checklist

- [ ] Job deployed successfully
- [ ] Scheduler running hourly
- [ ] Alerts arriving in Slack/Email
- [ ] No false positives for 3 days
- [ ] All critical scrapers monitored
- [ ] Team knows how to check status
- [ ] Documentation bookmarked

---

**Need help?** Check TROUBLESHOOTING.md or run `./check-status.sh`
