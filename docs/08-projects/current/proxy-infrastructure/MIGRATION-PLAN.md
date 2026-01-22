# Proxy Provider Migration Plan

**Last Updated:** 2026-01-22

## Overview

Steps to migrate from ProxyFuel to a new proxy provider (e.g., Decodo/Smartproxy).

## Pre-Migration Checklist

- [ ] Sign up for new provider trial
- [ ] Get API credentials (username, password, endpoint)
- [ ] Test connectivity from local machine
- [ ] Test against each target site manually

## Step 1: Local Testing

```bash
# Test new proxy against each target
NEW_PROXY="http://user:pass@new-provider.com:port"

# Test BettingPros
curl -x "$NEW_PROXY" "https://api.bettingpros.com/v3/events?sport=NBA&date=2026-01-22" \
  -H "User-Agent: Mozilla/5.0" -w "\nHTTP: %{http_code}\n"

# Test NBA.com stats
curl -x "$NEW_PROXY" "https://stats.nba.com/stats/boxscoretraditionalv3?GameID=0022500620&LeagueID=00" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://www.nba.com/" -w "\nHTTP: %{http_code}\n"

# Test OddsAPI
curl -x "$NEW_PROXY" "https://api.the-odds-api.com/v4/sports/basketball_nba/events" \
  -H "User-Agent: Mozilla/5.0" -w "\nHTTP: %{http_code}\n"
```

**Success Criteria:** HTTP 200 with valid JSON for each target.

## Step 2: Update Configuration

### File: `scrapers/utils/proxy_utils.py`

```python
def get_proxy_urls():
    """
    Returns a list of proxy URLs to try.
    """
    return [
        # New provider (primary)
        "http://user:pass@new-provider.com:port",
        # Old provider (fallback) - remove after validation
        # "http://nchammas.gmail.com:bbuyfd@gate2.proxyfuel.com:2000",
    ]
```

### Environment Variables (if using)

If credentials should be in env vars:
```python
import os

def get_proxy_urls():
    proxy_user = os.getenv("PROXY_USER")
    proxy_pass = os.getenv("PROXY_PASS")
    proxy_host = os.getenv("PROXY_HOST", "gate.smartproxy.com")
    proxy_port = os.getenv("PROXY_PORT", "7000")

    return [f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"]
```

## Step 3: Deploy to Staging (Optional)

If you have a staging environment:
1. Deploy changes to staging
2. Run scrapers manually
3. Verify data flows to BigQuery
4. Check `proxy_health_metrics` for success rates

## Step 4: Deploy to Production

```bash
# Deploy phase1-scrapers with new proxy config
gcloud run deploy nba-phase1-scrapers \
  --source . \
  --region us-west2 \
  --project nba-props-platform \
  --set-env-vars="SERVICE=scrapers" \
  --quiet
```

## Step 5: Monitor

### Immediate (First Hour)

```sql
-- Check success rate for new proxy
SELECT
  target_host,
  COUNT(*) as requests,
  COUNTIF(success) as successful,
  ROUND(COUNTIF(success) * 100.0 / COUNT(*), 1) as success_rate
FROM nba_orchestration.proxy_health_metrics
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY target_host;
```

### Daily

Check the summary view:
```sql
SELECT * FROM nba_orchestration.proxy_health_summary
WHERE date = CURRENT_DATE()
ORDER BY total_requests DESC;
```

## Step 6: Cleanup

After 1 week of successful operation:
1. Remove old provider from `proxy_utils.py`
2. Cancel old provider subscription
3. Update documentation

## Rollback Plan

If new provider fails:

1. **Quick Rollback (< 5 min)**
   ```python
   # In proxy_utils.py, swap order:
   return [
       "http://old-proxy...",  # Move back to primary
       "http://new-proxy...",  # Demote to fallback
   ]
   ```
   Redeploy.

2. **Full Rollback**
   - Revert proxy_utils.py changes
   - Redeploy

## Provider-Specific Setup

### Decodo/Smartproxy

1. Sign up at https://decodo.com
2. Get credentials from dashboard
3. Endpoint format: `http://user:pass@gate.smartproxy.com:7000`
4. For rotating residential: `http://user:pass@gate.smartproxy.com:10000`

### Bright Data

1. Sign up at https://brightdata.com
2. Create a "Residential" zone
3. Get zone credentials
4. Endpoint format: `http://zone-user:zone-pass@brd.superproxy.io:22225`

## Timing Recommendations

- **Best time to switch:** During low-activity hours (2-6 AM ET)
- **Avoid:** During game days, especially close to game time
- **Monitor closely:** First 24-48 hours after switch
