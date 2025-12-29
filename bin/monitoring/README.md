# NBA Platform Monitoring

This directory contains deployment and status scripts for various monitoring systems that watch different parts of the NBA data pipeline.

## Monitoring Systems

### 0. Daily Health Check (`daily_health_check.sh`) - NEW

**What it does:** Comprehensive morning health check for pipeline status
**How to run:** `./bin/monitoring/daily_health_check.sh [DATE]`
**Purpose:** Run each morning to verify predictions are generated

**Quick commands:**
```bash
# Run health check for today
./bin/monitoring/daily_health_check.sh

# Run health check for specific date
./bin/monitoring/daily_health_check.sh 2025-12-29
```

**What it checks:**
- Games scheduled for the day (NBA API + BigQuery fallback)
- Predictions count, games covered, players with predictions
- Phase 3 completion state (Firestore)
- ML Feature Store record count
- Recent errors (last 2 hours)
- Service health (Phase 3, Phase 4, Coordinator)
- Summary with pipeline status

### 0b. Orchestration State Tool (`check_orchestration_state.py`) - NEW

**What it does:** Query Firestore orchestration state for debugging
**How to run:** `PYTHONPATH=. python3 bin/monitoring/check_orchestration_state.py [DATE]`
**Purpose:** Debug Phase 3/4 orchestration issues

**Quick commands:**
```bash
# Check today's state
PYTHONPATH=. python3 bin/monitoring/check_orchestration_state.py

# Check specific date
PYTHONPATH=. python3 bin/monitoring/check_orchestration_state.py 2025-12-29
```

**What it shows:**
- Phase 3 completion: X/5 processors complete
- Phase 4 completion status
- Phase 4/5 trigger status
- Stuck run_history entries
- Tomorrow's state preview

---

### 1. Freshness Monitoring (`freshness_monitor`)

**What it monitors:** GCS raw data files from all scrapers  
**How it works:** Cloud Run Job triggered hourly by Cloud Scheduler  
**Location:** `monitoring/scrapers/freshness/`  
**Alerts:** Slack + Email when scraper data is stale or missing

**Quick commands:**
```bash
# Deploy the monitoring job
./deploy/deploy_freshness_monitor.sh

# Check system status
./status/freshness_status.sh

# View recent logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=freshness-monitor" --limit=20

# Manually trigger check
gcloud run jobs execute freshness-monitor --region=us-west2
```

### 2. Table Monitoring (Future)

**What it will monitor:** BigQuery tables populated by processors  
**How it will work:** Cloud Run Job checking table freshness and completeness  
**Location:** TBD  
**Alerts:** Slack + Email when processor output is stale or incomplete

### 3. Gap Detection (Existing)

**What it monitors:** Missing processor runs  
**Location:** `monitoring/processors/gap_detection/`  
**Alerts:** Detects when processors should have run but didn't

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Cloud Scheduler                            │
│              (Triggers monitoring jobs)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               Cloud Run Jobs (Monitoring)                    │
│                                                              │
│  ┌────────────────────┐  ┌────────────────────┐            │
│  │ Freshness Monitor  │  │  Table Monitor     │            │
│  │ (Scraper Data)     │  │  (Processor Data)  │            │
│  │ Checks GCS         │  │  Checks BigQuery   │            │
│  └────────────────────┘  └────────────────────┘            │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┴───────────────┐
           ▼                               ▼
┌────────────────────┐         ┌────────────────────┐
│  Slack Webhooks    │         │  Email (Brevo)     │
│  #nba-alerts       │         │  Critical alerts   │
└────────────────────┘         └────────────────────┘
```

## Deployment

### First-Time Setup

1. **Configure environment:**
   ```bash
   # Ensure .env has monitoring credentials
   vim .env
   # Add: BALL_DONT_LIE_API_KEY, SLACK_WEBHOOK_URL, etc.
   ```

2. **Deploy monitoring job:**
   ```bash
   cd bin/monitoring/deploy
   ./deploy_freshness_monitor.sh
   ```

3. **Set up scheduler:**
   ```bash
   cd monitoring/scrapers/freshness
   ./setup-scheduler.sh
   ```

4. **Verify deployment:**
   ```bash
   cd bin/monitoring/status
   ./freshness_status.sh
   ```

### Updating Configuration

Configuration changes only (no code changes):
```bash
# Edit config
vim monitoring/scrapers/freshness/config/monitoring_config.yaml

# Redeploy
./bin/monitoring/deploy/deploy_freshness_monitor.sh
```

Code changes:
```bash
# Make changes to monitoring/scrapers/freshness/
# Then redeploy
./bin/monitoring/deploy/deploy_freshness_monitor.sh
```

## Monitoring the Monitors

### Daily Checks

```bash
# Quick status of all monitoring systems
./status/freshness_status.sh

# View recent alerts
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=WARNING" \
  --limit=20
```

### Weekly Review

```bash
# Check health score trends
gcloud logging read \
  "resource.type=cloud_run_job AND jsonPayload.message:\"Health Score\"" \
  --limit=50 \
  --format='value(timestamp,jsonPayload.summary.health_score)'

# Review false positive rate
# (Manual review of alerts vs actual issues)
```

## Troubleshooting

### Freshness Monitor Not Running

```bash
# Check if job exists
gcloud run jobs describe freshness-monitor --region=us-west2

# Check scheduler status
gcloud scheduler jobs describe freshness-monitor-hourly --location=us-west2

# View error logs
gcloud logging read \
  "resource.type=cloud_run_job AND severity>=ERROR" \
  --limit=20
```

### No Alerts Received

```bash
# Test notifications directly
cd monitoring/scrapers/freshness
python3 runners/scheduled_monitor.py --test

# Check environment variables
gcloud run jobs describe freshness-monitor \
  --region=us-west2 \
  --format='value(template.template.containers[0].env)'
```

### False Positives

```bash
# Test specific scraper
cd monitoring/scrapers/freshness
./test-scraper.py <scraper_name> --verbose

# Adjust thresholds in config
vim monitoring/scrapers/freshness/config/monitoring_config.yaml

# Redeploy
./bin/monitoring/deploy/deploy_freshness_monitor.sh
```

## Cost Estimates

**Freshness Monitor:**
- Cloud Run Job: ~$5-10/month (hourly execution, 30-60s runtime)
- Cloud Scheduler: Free (under 3 jobs)
- Cloud Storage: Negligible (just reading metadata)
- **Total: ~$5-10/month**

**Future Table Monitor:**
- Similar cost structure
- BigQuery queries: Minimal (just metadata checks)
- **Estimated: ~$5-10/month**

## Related Documentation

- Freshness Monitor: `monitoring/scrapers/freshness/README.md`
- Gap Detection: `monitoring/processors/gap_detection/README.md`
- Deployment Patterns: `bin/README.md`

## Support

**Common Issues:**
- No alerts → Check TROUBLESHOOTING.md in monitoring/scrapers/freshness/
- False positives → Adjust thresholds in monitoring_config.yaml
- Job failures → Check Cloud Run logs

**Quick Commands:**
```bash
# Status
./status/freshness_status.sh

# Deploy
./deploy/deploy_freshness_monitor.sh

# Logs
gcloud logging read "resource.type=cloud_run_job" --limit=50

# Manual trigger
gcloud run jobs execute freshness-monitor --region=us-west2
```
