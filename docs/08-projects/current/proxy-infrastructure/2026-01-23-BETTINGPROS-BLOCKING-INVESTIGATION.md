# BettingPros Blocking Investigation

**Date:** 2026-01-23
**Status:** Active Issue
**Severity:** P1 - BettingPros data collection impacted

---

## Executive Summary

BettingPros is actively blocking both proxy providers (ProxyFuel datacenter and Decodo residential). The scraper is hitting "Proxy Exhaustion" after trying both proxies and receiving 403 Forbidden responses from all.

---

## Timeline

| Date | Time (UTC) | Status |
|------|------------|--------|
| 2026-01-22 | 18:27-19:38 | Last successful scrapes (Jan 22 data) |
| 2026-01-23 | 13:27-13:33 | Multiple failed attempts, all 403 |
| 2026-01-23 | 21:00+ | No further BettingPros attempts |

---

## Evidence

### Proxy Health Metrics
```
| date       | proxy_provider | target_host           | requests | blocked_403 |
|------------|---------------|------------------------|----------|-------------|
| 2026-01-23 | proxyfuel     | api.bettingpros.com   | 27       | 27          |
```

- 100% failure rate for ProxyFuel
- Decodo attempts not showing in metrics (may be logging issue or not reached)

### Log Analysis
```
2026-01-23T13:33:55 - Scraper Proxy Exhaustion: BettingProsEvents
2026-01-23T13:33:55 - Invalid HTTP status code (retry): 403
2026-01-23T13:33:57 - Failed to fetch events for date 2026-01-23 after 3 retries
```

### Direct API Test
```bash
curl "https://api.bettingpros.com/v3/events?sport=NBA&date=2026-01-23"
# Returns: 403 Forbidden
```

Direct calls from Cloud Shell also return 403 - BettingPros is blocking GCP IP ranges.

---

## GCS Data Status

| Game Date | Scrapes | Last File |
|-----------|---------|-----------|
| 2026-01-22 | 3 files | 19:38 UTC |
| 2026-01-23 | 0 files | - |

---

## Root Cause Analysis

BettingPros appears to be blocking:
1. **Datacenter IPs** (ProxyFuel) - Common anti-bot measure
2. **GCP IP ranges** (Cloud Run, Cloud Shell) - Common blocking
3. **Possibly residential IPs** (Decodo) - Less common but possible if fingerprinting

### Blocking Mechanism Theories

1. **IP-based blocking** - Blocking known datacenter/cloud IP ranges
2. **Rate limiting** - Too many requests from same IP pool
3. **Fingerprinting** - Detecting non-browser traffic despite headers
4. **API key requirement** - May now require authentication

---

## Current Fallback Status

The prediction system has fallbacks:
1. **Odds API** (primary) - Still working, uses API key
2. **BettingPros** (fallback) - Currently blocked
3. **NO_PROP_LINE** - For players without any line source

Impact: Players only covered by BettingPros may have NO_PROP_LINE status.

---

## Mitigation Options

### Short-term (Hours)

1. **Try different Decodo endpoints**
   - Current: `us.decodo.com:10001`
   - Try: `gate.smartproxy.com:7000` (alternative gateway)

2. **Increase request delays**
   - Add longer delays between requests
   - Randomize request timing

3. **Use BettingPros API key**
   - Check if BettingPros offers authenticated API access
   - May bypass IP blocking

### Medium-term (Days)

4. **Try alternative residential proxies**
   - Bright Data
   - Oxylabs
   - IPRoyal

5. **Implement browser automation fallback**
   - Playwright/Puppeteer with residential proxy
   - Slower but harder to block

### Long-term (Weeks)

6. **Diversify data sources**
   - Add more sportsbook APIs (Action Network, etc.)
   - Reduce single-source dependency

---

## Monitoring Commands

```bash
# Check proxy health
bq query --use_legacy_sql=false "
SELECT DATE(timestamp) as date, proxy_provider, target_host,
       COUNTIF(success) as success, COUNTIF(NOT success) as failed
FROM nba_orchestration.proxy_health_metrics
WHERE target_host LIKE '%bettingpros%'
GROUP BY 1, 2, 3 ORDER BY 1 DESC"

# Check GCS for recent scrapes
gsutil ls -l "gs://nba-scraped-data/bettingpros/player-props/points/" | tail -5

# Check logs for proxy errors
gcloud logging read 'resource.labels.service_name="nba-scrapers" AND textPayload=~"Proxy Exhaustion"' --limit=20
```

---

## Impact Assessment

| Metric | Without BettingPros |
|--------|---------------------|
| Line coverage | Reduced (Odds API only) |
| Player coverage | Lower (BP had unique players) |
| Prediction quality | Minimal (Odds API sufficient for stars) |
| Historical backfill | Blocked |

**Severity:** P1 - Important but not critical since Odds API is primary source.

---

## Next Steps

1. [ ] Test alternative Decodo endpoints
2. [ ] Check if BettingPros has authenticated API
3. [ ] Monitor if blocking is temporary (check again tomorrow)
4. [ ] Consider browser automation fallback
5. [ ] Update proxy_utils.py with new endpoint options
