# Troubleshooting Guide

Quick reference for diagnosing and fixing common NBA Props Platform issues.

## Quick Diagnosis

```bash
# Check yesterday's status
nba-monitor status yesterday

# View recent errors
nba-monitor errors 24

# Check specific workflow
gcloud workflows executions list morning-operations --location=us-west2 --limit=3
```

## Common Issues

### 1. "No Data Found" Errors

#### Symptoms
```
Error: BDL Box Scores - No Data Found
Date: 2025-10-14
```

#### Root Cause
Scraper is trying to fetch data for games that haven't happened yet (usually fetching "today" when games haven't been played).

#### Diagnosis
```bash
# Check what date the workflow is using
gcloud workflows executions describe <EXECUTION_ID> \
  --workflow=post-game-collection \
  --location=us-west2 \
  --format=json | jq '.argument'

# Check if games actually happened on that date
# Look at schedule data
```

#### Fix
Update the scraper to use the correct date logic:

```python
# In your scraper (e.g., scrapers/balldontlie/bdl_box_scores.py)

from datetime import datetime, timedelta

# Wrong - fetches today (games not played yet)
target_date = datetime.utcnow().strftime("%Y-%m-%d")

# Right - fetches yesterday (completed games)
target_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

# For live games during the day
current_hour_pt = (datetime.utcnow() - timedelta(hours=8)).hour
if current_hour_pt < 4:  # Before 4am PT, games are from yesterday
    target_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
else:  # After 4am PT, fetch today's games
    target_date = datetime.utcnow().strftime("%Y-%m-%d")
```

#### Deploy Fix
```bash
cd ~/code/nba-stats-scraper
# Make changes to scraper
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

---

### 2. Proxy Exhaustion

#### Symptoms
```
Error: Scraper Proxy Exhaustion - GetNbaComPlayerList
Error Details: All 1 proxies failed
failures: [{'proxy': 'http://nohammas.gmail.com:bbuyfd@gate2.proxyfuel.com:2000', 
           'error': 'ConnectionError'}]
```

#### Root Causes
1. ProxyFuel subscription expired
2. Proxy credentials changed
3. Proxies blocked by target website
4. Network connectivity issues

#### Diagnosis

**Step 1: Test proxy directly**
```bash
# Test basic connectivity
curl -x http://username:password@gate2.proxyfuel.com:2000 https://httpbin.org/ip

# Test NBA.com specifically
curl -x http://username:password@gate2.proxyfuel.com:2000 https://stats.nba.com
```

**Step 2: Check credentials**
```bash
# View stored credentials (if in Secret Manager)
gcloud secrets versions access latest --secret="proxyfuel-credentials"

# Or check environment variables in Cloud Run
gcloud run services describe nba-scrapers \
  --region=us-west2 \
  --format=json | jq '.spec.template.spec.containers[0].env'
```

**Step 3: Check subscription**
- Log into ProxyFuel dashboard
- Verify subscription is active
- Check usage limits

#### Quick Fix
```python
# In scrapers/utils/proxy_utils.py
# Add retry logic with exponential backoff

import time
from requests.exceptions import ProxyError, ConnectionError

def fetch_with_retry(url, proxies, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, proxies=proxies, timeout=30)
            return response
        except (ProxyError, ConnectionError) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Proxy failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
```

#### Permanent Fix
1. **Rotate proxy providers** - Add multiple proxy services
2. **Implement proxy pool** - Rotate through multiple proxies
3. **Add fallback** - Direct connection if proxies fail (for some sites)
4. **Monitor proxy health** - Alert before complete failure

---

### 3. Workflow Timeout

#### Symptoms
```
Workflow: morning-operations
Status: ACTIVE
Duration: 15 minutes (still running)
```

#### Root Causes
- Scraper hanging on API call
- Large amount of data to process
- Network latency
- Infinite loop or deadlock

#### Diagnosis

**Check Cloud Run logs:**
```bash
# Get logs from the time of execution
gcloud logging read "resource.type=cloud_run_revision 
  AND resource.labels.service_name=nba-scrapers 
  AND timestamp>=\"2025-10-14T15:00:00Z\"
  AND timestamp<=\"2025-10-14T15:20:00Z\"" \
  --limit=100 \
  --format=json > timeout-logs.json

# Look for stuck operations
cat timeout-logs.json | jq '.[] | select(.jsonPayload.message | contains("Fetching"))'
```

**Check workflow steps:**
```bash
gcloud workflows executions describe <EXECUTION_ID> \
  --workflow=morning-operations \
  --location=us-west2 \
  --format=json | jq '.state'
```

#### Fix

**Add timeouts to HTTP requests:**
```python
# In scraper code
import requests

# Wrong - no timeout (can hang forever)
response = requests.get(url)

# Right - with timeout
response = requests.get(url, timeout=30)  # 30 second timeout

# Better - with retry and timeout
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

session = requests.Session()
retry = Retry(total=3, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

response = session.get(url, timeout=30)
```

**Add workflow timeout:**
```yaml
# In workflow YAML file
main:
  params: [args]
  steps:
    - scrape_data:
        call: http.post
        args:
          url: ${scraperUrl}
          timeout: 300  # 5 minute timeout
        result: scraperResult
```

---

### 4. Data Quality Issues

#### Symptoms
- Missing players in props data
- Incorrect game scores
- Duplicate records
- NULL values where expected

#### Diagnosis

**Check validation results:**
```bash
# Run validator for specific data
./scripts/validate-odds-props 2025-10-14

# Check BigQuery for data quality
bq query --use_legacy_sql=false '
SELECT 
  COUNT(*) as total_rows,
  COUNT(DISTINCT player_id) as unique_players,
  SUM(CASE WHEN points_line IS NULL THEN 1 ELSE 0 END) as missing_points
FROM `nba-props-platform.raw.odds_api_player_props`
WHERE DATE(scraped_at) = "2025-10-14"
'
```

**Compare with source:**
```bash
# Manually check the source API
curl "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
```

#### Common Fixes

**Missing data:**
```python
# Add data validation in processor
def validate_player_data(player):
    required_fields = ['player_id', 'player_name', 'points_line']
    missing = [f for f in required_fields if not player.get(f)]
    if missing:
        logger.warning(f"Missing fields: {missing} for player: {player.get('player_name')}")
        return False
    return True

# Filter out invalid data
valid_players = [p for p in players if validate_player_data(p)]
```

**Duplicate records:**
```sql
-- Find duplicates in BigQuery
SELECT 
  game_id, 
  player_id, 
  COUNT(*) as count
FROM `nba-props-platform.raw.player_props`
WHERE DATE(scraped_at) = '2025-10-14'
GROUP BY game_id, player_id
HAVING count > 1
```

```python
# Deduplicate in processor
def deduplicate_props(props):
    seen = set()
    unique_props = []
    for prop in props:
        key = (prop['game_id'], prop['player_id'], prop['market'])
        if key not in seen:
            seen.add(key)
            unique_props.append(prop)
    return unique_props
```

---

### 5. Authentication / Permission Errors

#### Symptoms
```
Error: 403 Forbidden
Error: 401 Unauthorized
Error: Permission denied on resource
```

#### Diagnosis

**Check service account:**
```bash
# View Cloud Run service account
gcloud run services describe nba-scrapers \
  --region=us-west2 \
  --format=json | jq '.spec.template.spec.serviceAccountName'

# Check service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:*nba-scrapers*"
```

**Check API keys:**
```bash
# View secrets
gcloud secrets list

# Check if key is accessible
gcloud secrets versions access latest --secret="ball-dont-lie-api-key"
```

#### Fix

**Grant necessary permissions:**
```bash
# Example: Grant Cloud Run service account access to BigQuery
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:nba-scrapers@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

# Grant access to GCS
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:nba-scrapers@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

**Update API keys:**
```bash
# Update secret
echo -n "new-api-key" | gcloud secrets versions add ball-dont-lie-api-key --data-file=-

# Redeploy service to pick up new secret
gcloud run services update nba-scrapers --region=us-west2
```

---

### 6. Memory / Resource Issues

#### Symptoms
```
Error: Memory limit exceeded
Container terminated: OutOfMemory
```

#### Diagnosis
```bash
# Check Cloud Run resource limits
gcloud run services describe nba-scrapers \
  --region=us-west2 \
  --format=json | jq '.spec.template.spec.containers[0].resources'
```

#### Fix
```bash
# Increase memory limit
gcloud run services update nba-scrapers \
  --region=us-west2 \
  --memory=2Gi \
  --cpu=2
```

Or optimize code:
```python
# Process data in chunks instead of loading all at once
def process_in_chunks(data, chunk_size=1000):
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i+chunk_size]
        process_chunk(chunk)
        # Let garbage collector free memory
        del chunk
```

---

## Emergency Procedures

### System Down - All Workflows Failing

1. **Check GCP Status:**
   ```bash
   # Check if GCP services are operational
   # Visit: https://status.cloud.google.com
   ```

2. **Pause all schedulers:**
   ```bash
   ./bin/infrastructure/scheduling/pause_all_schedulers.sh
   ```

3. **Check recent deployments:**
   ```bash
   # Did someone just deploy?
   gcloud logging read "resource.type=cloud_run_revision 
     AND textPayload=~\"Deploying\"" \
     --limit=10
   ```

4. **Rollback if needed:**
   ```bash
   # List revisions
   gcloud run revisions list --service=nba-scrapers --region=us-west2
   
   # Rollback to previous
   gcloud run services update-traffic nba-scrapers \
     --region=us-west2 \
     --to-revisions=nba-scrapers-00057-xyz=100
   ```

### Data Pipeline Stuck

1. **Identify bottleneck:**
   ```bash
   # Check Pub/Sub subscriptions
   gcloud pubsub subscriptions list

   # Check for unacked messages
   gcloud pubsub subscriptions describe SUBSCRIPTION_NAME
   ```

2. **Clear stuck messages:**
   ```bash
   # Seek to current time (skip old messages)
   gcloud pubsub subscriptions seek SUBSCRIPTION_NAME --time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   ```

3. **Manually trigger processors:**
   ```bash
   # Trigger processor directly
   curl -X POST https://nba-processors-XXX.run.app/process \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -d '{"date": "2025-10-14", "processor": "bdl_box_scores"}'
   ```

### Backfill Data Missing After Bulk Run

**Symptoms:**
- Backfill script ran "successfully" but data is incomplete
- Only 1 game per date instead of all games
- GCS files exist but BigQuery table missing records

**Root Cause:**
Pub/Sub is not reliable for bulk backfills. When many messages are published rapidly:
- Some messages may be dropped or delayed
- The subscription may not receive all messages
- Downstream processors only process a subset of data

**Diagnosis:**
```bash
# Check actual data vs expected
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as actual_games
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date >= '2025-12-20'
GROUP BY game_date ORDER BY game_date"

# Compare to schedule
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as scheduled_games
FROM nba_reference.nba_schedule
WHERE game_date >= '2025-12-20' AND game_status = 3
GROUP BY game_date ORDER BY game_date"
```

**Solution:**
Backfill scripts should **directly invoke processors**, bypassing Pub/Sub:

```python
# Example: Direct processor invocation (no Pub/Sub)
from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor

processor = NbacGamebookProcessor()
processor.process_file(gcs_path)  # Direct call, not via Pub/Sub
```

**For gamebook backfills specifically:**
```bash
# Re-process existing GCS data (bypass Pub/Sub)
PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-23 --skip-scrape

# Full scrape + process
PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-23
```

**Verification Checklist:**
- [ ] Count games in BigQuery matches scheduled games
- [ ] Player count is reasonable (~30-35 players per game)
- [ ] Phase 3 analytics show updated data after backfill

---

## Run History Cleanup and Stuck Processors

### Detecting Stuck Processors

**Symptoms:**
- Processor skips work with "Already processed" messages
- Grafana alert "Stale Running Processors"
- Processor shows `status='running'` for > 2 hours in run history

**Detection Query:**
```sql
-- Find processors stuck in 'running' status > 1 hour
SELECT
  started_at,
  processor_name,
  phase,
  data_date,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running,
  run_id
FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 60
ORDER BY started_at;
```

### How Stuck Entries Occur

1. Processor writes `status='running'` at startup
2. Process crashes or is forcefully terminated
3. No final status entry is written
4. Subsequent runs see stale `running` entry and skip (for < 2 hours)

**Automatic Recovery:**
- Stale threshold: 2 hours (entries older than this are automatically retried)
- If entry is > 2 hours old, the next run proceeds normally

### Manual Cleanup Procedure

**When to use:** When automatic recovery isn't working or you need immediate cleanup.

**Step 1: Identify stuck entries**
```bash
bq query --use_legacy_sql=false "
SELECT run_id, processor_name, data_date, started_at
FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 2
ORDER BY started_at"
```

**Step 2: Delete stale 'running' entries**
```bash
# Delete stuck entries older than 4 hours
bq query --use_legacy_sql=false "
DELETE FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 4"
```

**Step 3: Verify cleanup and re-trigger**
```bash
# Verify entries removed
bq query --use_legacy_sql=false "
SELECT COUNT(*) as stuck_count
FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 1"

# Re-trigger the processor (example for Phase 4)
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"analysis_date": "2025-12-26", "processors": ["MLFeatureStoreProcessor"]}'
```

### Bulk Cleanup (Emergency)

**Use with caution:** Only when many entries are stuck.

```bash
# Delete ALL running entries older than 4 hours
bq query --use_legacy_sql=false "
DELETE FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > 4"

# Session 170 example: Cleaned 114,434 stale entries
bq query --use_legacy_sql=false "
DELETE FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
```

### Prevention

1. **Monitor Grafana alerts** - "Stale Running Processors" triggers at 60 min
2. **Check run history table size** - Large accumulation indicates issues
3. **Review Cloud Run logs** - Look for crash patterns
4. **Ensure proper shutdown** - Processors should call `record_run_complete()` even on failure

### Related Documentation

- [Run History Guide](../07-monitoring/run-history-guide.md)
- [Grafana Dashboard Queries](../07-monitoring/grafana/dashboards/pipeline-run-history-queries.sql)

---

## Defensive Check Failures

### "DependencyError: Upstream X failed for Y"

**Symptoms:**
```
DependencyError: Upstream PlayerGameSummaryProcessor failed for 2025-12-25
```

**Root Cause:** Defensive checks detected that the upstream processor failed yesterday.

**Diagnosis:**
```bash
# Check upstream processor status
bq query --use_legacy_sql=false "
SELECT processor_name, data_date, status, error_message
FROM nba_reference.processor_run_history
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
ORDER BY data_date DESC, started_at DESC"
```

**Resolution:**
1. Fix the upstream processor issue
2. Re-run the upstream processor for the failed date
3. Then re-run the downstream processor

### "Defensive checks failed for same-day data"

**Symptoms:**
```
ERROR: Defensive checks failed - no upstream data for TODAY
```

**Root Cause:** Same-day predictions need special mode (no historical data exists yet).

**Resolution:**
Use `strict_mode=false` and `skip_dependency_check=true`:
```bash
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{
    "analysis_date": "TODAY",
    "processors": ["MLFeatureStoreProcessor"],
    "strict_mode": false,
    "skip_dependency_check": true
  }'
```

**Automated Fix:** Morning schedulers (10:30/11:00/11:30 AM ET) already use these flags.

### "Missing critical dependencies"

**Symptoms:**
```
ValueError: Missing critical dependencies: ['nba_raw.nbac_team_boxscore']
```

**Root Cause:** Required upstream data doesn't exist for the date.

**Diagnosis:**
```bash
# Check if upstream data exists
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as rows
FROM nba_raw.nbac_team_boxscore
WHERE game_date = '2025-12-25'
GROUP BY game_date"
```

**Resolution:**
1. Check if scraper ran for that date
2. If missing, run backfill: `PYTHONPATH=. python scripts/backfill_gamebooks.py --date 2025-12-25`
3. Re-run the failing processor

---

## Getting Help

### Debug Information to Collect

When reporting an issue, include:

1. **Workflow execution details:**
   ```bash
   gcloud workflows executions describe <EXECUTION_ID> \
     --workflow=WORKFLOW_NAME \
     --location=us-west2 > workflow-debug.txt
   ```

2. **Error logs:**
   ```bash
   nba-monitor errors 24 > errors.txt
   ```

3. **System status:**
   ```bash
   nba-monitor status yesterday > status.txt
   ```

4. **Recent changes:**
   - What was deployed recently?
   - Any configuration changes?
   - Any external API changes?

### Support Contacts

- **GCP Issues:** GCP Support Console
- **API Issues:** Check API provider status pages
- **Internal Issues:** Check with team on Slack

---

## Prevention

### Pre-Deployment Checklist

- [ ] Test scrapers locally
- [ ] Run with small date range first
- [ ] Check logs for warnings
- [ ] Verify data quality
- [ ] Monitor first few executions

### Monitoring Best Practices

- Run `nba-monitor status yesterday` daily
- Set up alerts for critical workflows
- Review weekly error trends
- Keep this guide updated with new issues

---

## Related Guides

- [Workflow Monitoring Guide](./WORKFLOW_MONITORING.md)
- [System Architecture](./ARCHITECTURE.md)
- [Deployment Guide](./DEPLOYMENT.md)
