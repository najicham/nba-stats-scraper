# Workflow Monitoring Guide

Complete guide to monitoring and managing NBA Props Platform workflows and scrapers.

## Table of Contents
- [System Overview](#system-overview)
- [Daily Monitoring](#daily-monitoring)
- [Understanding Workflows](#understanding-workflows)
- [Troubleshooting](#troubleshooting)
- [Alert Management](#alert-management)

## System Overview

### Architecture
```
Cloud Scheduler → Workflows → Cloud Run Services → BigQuery/GCS
     (trigger)    (orchestrate)  (scrape/process)    (store)
```

**Components:**
- **Cloud Scheduler**: Triggers workflows on schedule
- **Workflows**: Orchestrate multiple scrapers/processors
- **Cloud Run Services**: Execute the actual scraping/processing
- **BigQuery**: Structured data storage
- **GCS**: Raw data and logs storage

### Active Workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `real-time-business` | Every 2h (8am-8pm PT) | CRITICAL: Events→Props revenue chain |
| `morning-operations` | Daily 8am PT | Daily setup + Enhanced PBP recovery |
| `post-game-collection` | 8pm & 11pm PT | Core game data collection |
| `late-night-recovery` | 2am PT | Enhanced PBP + comprehensive retry |
| `early-morning-final-check` | 6am PT | Final recovery attempt + Enhanced PBP |

### Cloud Run Services

| Service | Purpose |
|---------|---------|
| `nba-scrapers` | Scrapes data from external APIs |
| `nba-processors` | Processes raw data into BigQuery |
| `nba-analytics-processors` | Generates analytics/summaries |
| `nba-reference-processors` | Manages reference data |

## Daily Monitoring

### Morning Routine (Recommended)

**Every morning at 9am:**

```bash
# 1. Check yesterday's status
nba-monitor status yesterday

# 2. If errors, get details
nba-monitor errors 24

# 3. Check specific workflow if needed
gcloud workflows executions describe <EXECUTION_ID> \
  --workflow=morning-operations \
  --location=us-west2
```

### What to Look For

✅ **All Good:**
- All workflows show ✓ (green)
- No errors or only minor ones
- Execution times are reasonable (< 2 min usually)

⚠️ **Needs Attention:**
- Any workflow shows ✗ (red) 
- Multiple errors from the same scraper
- Unusually long execution times (> 5 min)

🚨 **Critical:**
- `real-time-business` workflow failed
- Multiple workflows failed
- Proxy exhaustion errors
- "No data found" errors for games that definitely happened

## Understanding Workflows

### Workflow Execution Flow

```
1. Cloud Scheduler triggers workflow
2. Workflow starts execution
3. Workflow calls scraper endpoints on Cloud Run
4. Scrapers fetch and save data to GCS
5. Workflow triggers processors (via Pub/Sub)
6. Processors read from GCS, write to BigQuery
7. Workflow completes
```

### Reading Workflow Status

**SUCCEEDED** ✓
- Workflow completed all steps successfully
- Data was collected and processed
- No intervention needed

**FAILED** ✗
- One or more steps failed
- Check the error message
- May need manual retry

**ACTIVE** ⏳
- Still running
- Normal if recent (< 5 min)
- Concerning if > 10 min

### Common Workflow Patterns

**Morning Operations (8am PT):**
1. Scrapes overnight games
2. Recovers any missed data
3. Processes enhanced play-by-play
4. Updates player props for today

**Real-Time Business (Every 2h):**
1. Scrapes current odds/events
2. Updates props available
3. Critical for revenue

**Post-Game Collection (8pm & 11pm):**
1. Collects game data
2. Box scores
3. Play-by-play
4. Updates analytics

## Troubleshooting

### No Data Found Errors

**Symptom:** `BDL Box Scores - No Data Found`

**Cause:** Scraper is trying to fetch data for games that haven't happened yet (usually fetching "today" instead of "yesterday")

**Fix:**
1. Check the workflow YAML to see what date it's passing
2. Update scraper to use yesterday's date for completed games
3. Redeploy scraper

```python
# Wrong
target_date = datetime.utcnow().strftime("%Y-%m-%d")

# Right (for completed games)
target_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
```

### Proxy Exhaustion

**Symptom:** `Scraper Proxy Exhaustion - GetNbaComPlayerList - All 1 proxies failed`

**Causes:**
- ProxyFuel subscription expired
- Proxies are blocked by the website
- Too many concurrent requests
- Wrong credentials

**Fix:**
1. Check proxy subscription status
2. Test proxy manually:
```bash
curl -x http://username:password@gate2.proxyfuel.com:2000 https://stats.nba.com
```
3. Rotate to different proxy provider if needed
4. Implement retry logic with backoff

### Workflow Timeout

**Symptom:** Workflow runs > 10 minutes

**Causes:**
- Scraper is hanging on API call
- Too much data to process
- Network issues

**Fix:**
1. Check Cloud Run logs for the specific scraper
2. Add timeout to HTTP requests in scraper
3. Break large jobs into smaller chunks

### Authentication Errors

**Symptom:** `401 Unauthorized` or `403 Forbidden`

**Causes:**
- API key expired
- Invalid credentials
- Rate limit exceeded

**Fix:**
1. Check API key/credentials in Secret Manager
2. Verify API subscription is active
3. Implement rate limiting

## Alert Management

### Current Alert System

Email alerts are sent for:
- Workflow failures
- Scraper errors
- Data quality issues
- Missing data

### Preventing Email Floods

During backfills or mass operations, use the smart alerting system:

```python
from shared.utils.smart_alerting import SmartAlertManager

alert_mgr = SmartAlertManager()

# Enable backfill mode
alert_mgr.enable_backfill_mode()

try:
    # Your backfill code
    for date in dates:
        scrape(date)
except:
    pass
finally:
    # Send summary email
    alert_mgr.disable_backfill_mode(send_summary=True)
```

### Alert Priorities

🔴 **Critical (Act Immediately):**
- `real-time-business` workflow failed
- All proxies exhausted
- Database connection lost

🟡 **Warning (Check Within Hours):**
- Single workflow failed
- Data quality issues
- High error rate (> 10%)

🔵 **Info (Check Daily):**
- Individual scraper failures
- Retries succeeded
- Expected errors (off-season, etc.)

## Manual Operations

### Running a Workflow Manually

```bash
# Execute workflow now
gcloud workflows execute morning-operations --location=us-west2

# Execute with custom data
gcloud workflows execute morning-operations \
  --location=us-west2 \
  --data='{"date":"2025-10-14"}'
```

### Checking Execution Details

```bash
# List recent executions
gcloud workflows executions list morning-operations --location=us-west2 --limit=5

# Get execution details
gcloud workflows executions describe <EXECUTION_ID> \
  --workflow=morning-operations \
  --location=us-west2
```

### Viewing Logs

```bash
# View workflow logs
gcloud logging read "resource.type=workflows.googleapis.com/Workflow 
  AND resource.labels.workflow_id=morning-operations" \
  --limit=20

# View scraper logs
gcloud logging read "resource.type=cloud_run_revision 
  AND resource.labels.service_name=nba-scrapers 
  AND severity>=WARNING" \
  --limit=50
```

### Pausing/Resuming Schedulers

```bash
# Pause all schedulers
gcloud scheduler jobs pause morning-operations-trigger --location=us-west2

# Resume
gcloud scheduler jobs resume morning-operations-trigger --location=us-west2

# List all schedulers
gcloud scheduler jobs list --location=us-west2
```

## Best Practices

### 1. Check Daily
- Run `nba-monitor status yesterday` every morning
- Review any errors before they compound

### 2. Act on Patterns
- Single error = probably okay
- Same error 3+ times = needs investigation
- Different scrapers, same error = infrastructure issue

### 3. Document Issues
- Keep a log of recurring issues
- Document fixes in comments
- Update this guide with new patterns

### 4. Proactive Monitoring
- Set up `tomorrow_morning_checklist.sh` to run nightly
- Configure Slack/email notifications for critical workflows
- Monitor API usage to avoid rate limits

### 5. Test Before Deploying
- Test scrapers locally first
- Use backfill jobs for historical data
- Deploy during low-traffic times

## Monitoring Checklist

### Daily (Automated)
- [ ] Yesterday's workflows succeeded
- [ ] No critical errors
- [ ] Data quality checks passed

### Weekly (Manual)
- [ ] Review error trends
- [ ] Check API quota usage
- [ ] Verify all scrapers are running
- [ ] Review execution times for slowness

### Monthly (Strategic)
- [ ] Review and update this documentation
- [ ] Optimize slow workflows
- [ ] Clean up old logs/data
- [ ] Update API credentials if needed

## Additional Resources

- [Troubleshooting Guide](./TROUBLESHOOTING.md)
- [System Architecture](./ARCHITECTURE.md)
- [Scraper Development Guide](./SCRAPER_DEVELOPMENT.md)
- [Monitoring Scripts README](../monitoring/scripts/README.md)
