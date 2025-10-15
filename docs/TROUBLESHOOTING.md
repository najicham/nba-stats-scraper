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
