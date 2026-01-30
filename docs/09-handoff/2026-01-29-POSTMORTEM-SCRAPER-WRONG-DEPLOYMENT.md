# Post-Mortem: Scraper Services Wrong Code Deployment

**Date**: January 29-30, 2026
**Severity**: P1 Critical
**Duration**: ~3 days (Jan 27 16:36 to present)
**Services Affected**: `nba-scrapers`, `nba-phase1-scrapers`
**Impact**: Live boxscores not collected during games, Phase 3 analytics blocked

---

## Executive Summary

The `nba-scrapers` and `nba-phase1-scrapers` Cloud Run services were deployed with **wrong code** - they were running the analytics-processor instead of the scraper service. This caused:
- `/scrape` endpoint returning 404 for all requests
- No live boxscore collection during games
- Downstream phases (3-5) blocked waiting for raw data

The root cause was **manual deployments using `gcloud run deploy --source .`** from the repo root, which picked up the wrong Dockerfile. This went undetected due to **gaps in alerting for Phase 1 scrapers**.

---

## Timeline

| Date/Time (PT) | Event |
|----------------|-------|
| Jan 27, 08:36 | Deployment `nba-scrapers-00103-wgh` - **WRONG CODE DEPLOYED** |
| Jan 27, 08:36+ | `/scrape` starts returning 404 for all requests |
| Jan 27 - Jan 29 | ~3 days of games with no live boxscore collection |
| Jan 29, 19:42 | Issue discovered during validation session |
| Jan 29, 20:13 | Fix committed: `scrapers/Dockerfile` created (7da5b95d) |
| Jan 29, 20:05 | Wrong deployment again: `nba-scrapers-00104-rdr` still uses old code |
| Jan 29, 20:30 | Post-mortem investigation started |

---

## Root Cause Analysis

### Primary Cause: Missing Scrapers Dockerfile

1. **No dedicated `scrapers/Dockerfile` existed** - scrapers relied on implicit assumptions
2. **Root `Dockerfile` defaults to analytics-processor** when no SERVICE env var is set:
   ```dockerfile
   CMD if [ "$SERVICE" = "phase2" ]; then
         exec gunicorn ... data_processors.raw.main_processor_service:app;
       elif [ "$SERVICE" = "analytics" ]; then
         exec gunicorn ... data_processors.analytics.main_analytics_service:app;
       else
         exec gunicorn ... data_processors.analytics.main_analytics_service:app;  # DEFAULT!
       fi
   ```
3. **Manual deployments used `gcloud run deploy --source .`** which:
   - Built from repo root
   - Used the root Dockerfile
   - Resulted in analytics-processor code being deployed to scraper services

### Contributing Factors

| Factor | Description |
|--------|-------------|
| **No deployment script for scrapers** | `bin/deploy-service.sh` didn't support scraper services until this fix |
| **Images in `cloud-run-source-deploy` registry** | Indicates `--source .` was used (not proper Dockerfile builds) |
| **No CI/CD enforcement** | Deployments are manual, no PR-based deployment gates |
| **Deployment docs incomplete** | No clear instructions on correct scraper deployment |

---

## Detection Failure Analysis

### Why We Didn't Get Alerts

| Gap | Impact | Details |
|-----|--------|---------|
| **HTTP 400 alerts only, not 404** | 404s not caught | Alert policy `nba-scrapers-http-errors` only monitors `response_code = "400"` |
| **No Cloud Scheduler failure alerts** | Scheduler jobs failed silently | No alert policy for Cloud Scheduler errors |
| **No real-time scraper health checks** | Phase 1 not monitored | `pipeline-health-monitor` only covers Phases 3-5 |
| **Manual bash checks not automated** | Requires someone to run them | `check_scraper_failures.sh` is a manual diagnostic tool |
| **Thresholds too high** | Delayed detection | 4-day staleness threshold, ≥10 failures required |
| **No "0 rows scraped" detection** | Silent failure | Completeness checks expect lag, don't catch 0 output |

### Evidence of Silent Failures

Cloud Scheduler logs show 29+ consecutive failures that triggered NO alerts:
```
bdl-live-boxscores-evening:
- 2026-01-30 04:36:01 - NOT_FOUND (404)
- 2026-01-30 04:33:01 - NOT_FOUND (404)
- 2026-01-30 04:30:01 - NOT_FOUND (404)
... repeated for hours with no alert
```

---

## Impact Assessment

### Data Impact

| Date | Games | Live Boxscores | Final Boxscores | Analytics |
|------|-------|---------------|-----------------|-----------|
| Jan 27 | 7 | ❌ Not collected | ⚠️ Via catch-up | ✅ Processed |
| Jan 28 | 9 | ❌ Not collected | ⚠️ Via catch-up | ✅ Processed |
| Jan 29 | 8 | ❌ Not collected | ❌ Pending | ❌ Blocked |

### System Impact

- **Live boxscore monitoring**: Not operational during games
- **Real-time updates**: Users didn't get live score updates
- **Prediction timeliness**: Predictions delayed waiting for data
- **Phase 3 completion**: Only 1/5 processors completing (upstream blocked)

---

## Remediation

### Immediate Fixes (Completed)

| Fix | Commit | Description |
|-----|--------|-------------|
| Created `scrapers/Dockerfile` | 7da5b95d | Proper Dockerfile for scraper services |
| Updated `bin/deploy-service.sh` | 7da5b95d | Added `nba-scrapers` and `nba-phase1-scrapers` support |

### Deployment Required

```bash
./bin/deploy-service.sh nba-scrapers
./bin/deploy-service.sh nba-phase1-scrapers
```

### Verification After Deploy

```bash
# Should return "nba-scrapers", NOT "analytics-processor"
curl -s "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/health" | jq .service
```

---

## Prevention Measures

### 1. Deployment Safeguards

| Measure | Priority | Description |
|---------|----------|-------------|
| **Pre-commit hook** | P1 | Validate Dockerfile exists for any changed service |
| **Deployment script enforcement** | P1 | Document and enforce `deploy-service.sh` usage |
| **Startup verification** | P1 | Services validate they loaded the expected module |
| **Post-deployment health check** | P2 | Auto-verify `/health` returns expected service name |

### 2. Alerting Improvements

| Alert | Priority | Description |
|-------|----------|-------------|
| **Scraper 404 alerts** | P1 | Alert on HTTP 404 from scraper services |
| **Cloud Scheduler failure alerts** | P1 | Alert on ≥3 consecutive scheduler job failures |
| **Live data freshness** | P1 | Alert if 0 live boxscores in 15 min during game hours |
| **Service identity mismatch** | P2 | Alert if `/health` returns wrong service name |

### 3. Monitoring Improvements

| Monitor | Priority | Description |
|---------|----------|-------------|
| **Phase 1 health dashboard** | P2 | Add scrapers to pipeline-health-monitor |
| **Scraper output count** | P2 | Track rows scraped per job execution |
| **Deployment drift detection** | P2 | Daily check that deployed code matches expectations |

---

## Action Items

### Immediate (P0)

- [ ] Deploy fixed scraper services
- [ ] Verify scrapers return correct service identity
- [ ] Trigger catch-up for missing data

### Short-term (P1) - This Week

- [ ] Add Cloud Monitoring alert for HTTP 404s from scrapers
- [ ] Add Cloud Monitoring alert for Cloud Scheduler failures
- [ ] Add startup verification to scraper service
- [ ] Update deployment documentation

### Medium-term (P2) - Next Sprint

- [ ] Add pre-commit hook for Dockerfile validation
- [ ] Add scrapers to real-time health monitoring
- [ ] Create deployment drift detection workflow
- [ ] Add post-deployment verification script

---

## Lessons Learned

1. **Every deployable service needs a dedicated Dockerfile** - relying on implicit defaults is dangerous
2. **Phase 1 scrapers need the same monitoring as Phases 3-5** - they're critical path
3. **Alert on 404s, not just 400s** - route-not-found is a severe failure mode
4. **Startup verification is essential** - services should validate they loaded correctly
5. **Manual deployments need guardrails** - easy to use wrong commands without CI/CD

---

## Appendix: Technical Details

### Wrong Health Check Response

```json
// WRONG (analytics-processor code deployed to scrapers)
{"service":"analytics-processor","status":"healthy"}

// CORRECT (proper scraper code)
{"service":"nba-scrapers","version":"2.3.0","status":"healthy",...}
```

### Correct Deployment Command

```bash
# Using deployment script (RECOMMENDED)
./bin/deploy-service.sh nba-scrapers

# Or with explicit Dockerfile (if manual)
gcloud run deploy nba-scrapers \
  --source . \
  --dockerfile=scrapers/Dockerfile \
  --region=us-west2
```

### Root Dockerfile CMD Logic (The Problem)

```dockerfile
# From root Dockerfile - NO "scrapers" option!
CMD if [ "$SERVICE" = "phase2" ]; then
      exec gunicorn ... data_processors.raw.main_processor_service:app;
    elif [ "$SERVICE" = "analytics" ]; then
      exec gunicorn ... data_processors.analytics.main_analytics_service:app;
    else
      exec gunicorn ... data_processors.analytics.main_analytics_service:app;
    fi
```

---

*Post-mortem authored: 2026-01-29*
*Status: Investigation complete, fixes pending deployment*
