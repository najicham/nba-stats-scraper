# NBA Pipeline Error Analysis Report
**Period:** January 15-21, 2026  
**Generated:** 2026-01-21  

---

## Executive Summary

Total issues detected across all NBA pipeline services:
- **Total Errors:** 1,218
- **Total Warnings:** 1,785
- **Total Issues:** 3,003

---

## Critical Findings by Service

### 1. nba-phase3-analytics-processors
**Status:** 🔴 CRITICAL - Data Quality Issues

**Issues:**
- **Total Errors:** 226
- **Total Warnings:** 928
- **Total:** 1,154

**Primary Issue: Stale Dependencies**
- **Frequency:** 113 ERROR occurrences
- **Root Cause:** `nba_raw.bdl_player_boxscores` table is 38.1 hours old (exceeds 36h threshold)
- **Impact:** Analytics processors are rejecting stale upstream data, blocking downstream processing
- **Affected Timeframe:** Jan 21, ~4:09 PM - 4:12 PM UTC

**Error Message:**
```
ValueError: Stale dependencies (FAIL threshold): 
['nba_raw.bdl_player_boxscores: 38.1h old (max: 36h)']
```

**Impact on Data Completeness:** HIGH
- Analytics processing halted when dependencies are stale
- Downstream Phase 4 and predictions cannot proceed with incomplete Phase 3 data
- Data quality gates are working as designed (preventing bad data propagation)

**Potential Fixes:**
1. **Immediate:** Manually trigger Phase 2 BDL player boxscore processor to refresh stale table
2. **Short-term:** Investigate why BDL player boxscores are not being updated on schedule
3. **Medium-term:** Add monitoring alerts for tables approaching staleness threshold (e.g., 32h warning)
4. **Long-term:** Consider increasing threshold to 48h or implementing more flexible staleness checks

---

### 2. nba-phase1-scrapers
**Status:** 🟡 MODERATE - Intermittent Scraping Failures

**Issues:**
- **Total Errors:** 480
- **Total Warnings:** 20
- **Total:** 500

**Error Breakdown:**
- **Server Errors (500/502/503):** 290 occurrences
- **Validation Errors:** 162 occurrences
- **Connection Errors:** 22 occurrences
- **Timeout Errors:** 6 occurrences

**Primary Issues:**

**A. Team Boxscore Validation Failures (290 errors)**
```
DownloadDataException: Expected 2 teams for game 0022500626, got 0
```
- **Root Cause:** NBA.com API returning empty/incomplete team data
- **Impact:** MEDIUM - Individual game data may be missing
- **Pattern:** Concentrated around specific game IDs

**B. Player Boxscore Validation Failures (18 errors)**
```
DownloadDataException: No player rows in leaguegamelog JSON
```
- **Root Cause:** NBA.com API returning empty player statistics
- **Impact:** MEDIUM - Player statistics may be incomplete for affected games

**C. Container Startup Failures (22 errors)**
```
Default STARTUP TCP probe failed 1 time consecutively for container "nba-phase1-scrapers-1" on port 8080
Connection failed with status CANCELLED
```
- **Root Cause:** Container failing health checks during deployment
- **Impact:** LOW - Deployment issues, not runtime issues

**Impact on Data Completeness:** MEDIUM
- Individual games may have missing data
- Retry mechanisms should recover most failures
- Need to verify completeness checks are catching these gaps

**Potential Fixes:**
1. **Immediate:** Check if affected games (e.g., 0022500626) eventually populated
2. **Short-term:** Add retry logic with exponential backoff for empty API responses
3. **Medium-term:** Implement scraper-level alerts for repeated validation failures on same game
4. **Long-term:** Add fallback data sources for critical game data

---

### 3. nba-phase2-raw-processors
**Status:** 🟡 MODERATE - Container Startup Issues

**Issues:**
- **Total Errors:** 497
- **Total Warnings:** 3
- **Total:** 500

**Error Breakdown:**
- **Connection Errors (Container Startup):** 362 occurrences
- **Other Errors:** 129 occurrences
- **Timeout Errors:** 6 occurrences

**Primary Issue: Container Startup Failures**
```
Default STARTUP TCP probe failed 1 time consecutively for container "nba-phase2-raw-processors-1" on port 8080
Connection failed with status CANCELLED
```

**Pattern:** 
- Occurring during deployments (Jan 21 ~7:13 AM, Jan 21 ~2:02 AM)
- Container exiting with code 0 (clean exit)
- Health check failures on port 8080

**Impact on Data Completeness:** LOW
- These are deployment-time errors, not runtime processing errors
- Successful deployments eventually complete
- No evidence of data processing failures

**Potential Fixes:**
1. **Immediate:** Review deployment logs to identify startup sequence issues
2. **Short-term:** Increase startup probe timeout or add readiness checks
3. **Medium-term:** Investigate why containers are calling exit(0) during startup
4. **Long-term:** Implement blue-green deployments to avoid service interruption

---

### 4. prediction-worker
**Status:** 🟡 MODERATE - Authentication Warnings

**Issues:**
- **Total Errors:** 0
- **Total Warnings:** 426
- **Total:** 426

**Primary Issue: Unauthenticated Requests**
```
The request was not authenticated. Either allow unauthenticated invocations or set the proper Authorization header.
```

**Pattern:**
- **Frequency:** 426 occurrences
- **Timeframe:** Jan 21, 3:38 PM - 4:12 PM UTC (34 minutes)
- **Rate:** ~12.5 warnings per minute

**Impact on Data Completeness:** UNKNOWN
- These are warnings, not errors
- Service may still be processing requests
- Need to verify if predictions are being generated successfully

**Potential Fixes:**
1. **Immediate:** Check if prediction-worker is configured to accept unauthenticated requests from Pub/Sub
2. **Short-term:** Verify Pub/Sub push subscription is using correct OIDC token configuration
3. **Medium-term:** Review service account permissions for prediction-worker@nba-props-platform.iam.gserviceaccount.com
4. **Long-term:** Implement proper authentication flow between Pub/Sub and Cloud Run

---

### 5. nba-phase4-precompute-processors
**Status:** 🟢 HEALTHY - Minor Warnings

**Issues:**
- **Total Errors:** 0
- **Total Warnings:** 408
- **Total:** 408

**Note:** All warnings have empty messages, likely informational logging. No actionable errors detected.

---

### 6. Orchestration Functions
**Status:** 🟡 MODERATE - Deployment Timeouts

**Combined Analysis of All Orchestration Functions:**
- phase2-to-phase3-orchestrator
- phase3-to-phase4
- phase4-to-phase5-orchestrator
- phase5-to-phase6-orchestrator
- self-heal-predictions
- daily-health-summary
- box-score-completeness-alert
- grading-readiness-monitor
- validate-freshness
- pipeline-reconciliation
- check-missing
- live-export

**Issues:**
- **Total Errors:** 21
- **Total Warnings:** 2

**Error Breakdown:**
- **Timeout Errors:** 17 occurrences
- **Connection Errors:** 2 occurrences
- **Authentication Errors:** 1 occurrence
- **Not Found Errors:** 1 occurrence

**Primary Pattern: Deployment/Update Timeouts**

Most errors are audit log entries showing deployment operations, not runtime failures:
```
{'@type': 'type.googleapis.com/google.cloud.audit.AuditLog', 
 'methodName': '/InternalServices.ReplaceInternalService', 
 'principalEmail': 'nchammas@gmail.com'}
```

**Affected Functions:**
1. **self-heal-predictions:** 5 timeout errors (Jan 20, 10:19 PM - 10:20 PM)
2. **phase4-to-phase5-orchestrator:** 3 timeout errors (Jan 16, Jan 19)
3. **daily-health-summary:** 4 timeout errors + 2 connection errors (Jan 21, 3:41 PM - 3:42 PM)
4. **phase5-to-phase6-orchestrator:** 2 timeout errors (Jan 21, 8:15 AM - 8:17 AM)
5. **phase2-to-phase3-orchestrator:** 2 timeout errors (Jan 19, Jan 21)
6. **phase3-to-phase4:** 1 timeout error (Jan 20)
7. **box-score-completeness-alert:** 1 timeout error (Jan 20)
8. **grading-readiness-monitor:** 1 timeout error (Jan 20)
9. **validate-freshness:** 1 timeout error (Jan 18)
10. **pipeline-reconciliation:** 1 timeout error (Jan 16)
11. **check-missing:** 1 auth error + 1 not found error (Jan 18)
12. **live-export:** 1 connection error (Jan 19)

**Impact on Data Completeness:** LOW
- These are deployment/update operations, not runtime failures
- Functions continue to run after successful deployment
- No evidence of orchestration logic failures

**Potential Fixes:**
1. **Immediate:** Verify all orchestration functions are currently deployed and running
2. **Short-term:** Review deployment processes to minimize timeout occurrences
3. **Medium-term:** Add deployment health checks and rollback mechanisms
4. **Long-term:** Automate deployments with CI/CD to reduce manual update errors

---

### 7. prediction-coordinator
**Status:** 🟢 HEALTHY - Minimal Issues

**Issues:**
- **Total Errors:** 2
- **Total Warnings:** 0

**Errors:** Connection error during deployment (Jan 21, 3:59 PM)
- Malformed HTTP response during instance startup
- Likely deployment-related, not runtime issue

---

### 8. Pub/Sub Infrastructure
**Status:** 🟢 HEALTHY

**Issues Found:** 1 error

**Error Type:** Concurrent Update Conflict
```
status: {code: 10, message: "The request raced with another user request. Please try again."}
```

**Details:**
- **Subscription:** prediction-request-prod
- **Operation:** UpdateSubscription (manual configuration change)
- **Timestamp:** Jan 18, 12:18 AM
- **Impact:** LOW - Retry resolved the issue

---

### 9. Dead Letter Queue
**Status:** 🟢 HEALTHY

**Issues Found:** 0

No messages found in dead letter queues. All failed messages are being retried successfully or discarded appropriately.

---

## Missing Services Analysis

The following services were not found in error logs (indicating they are healthy):
- No errors detected (this is good!)

---

## Summary by Error Type

### Critical Issues Requiring Immediate Attention:
1. **Phase 3 Stale Dependencies (113 errors)** - Blocking analytics processing
2. **Phase 1 Team Boxscore Failures (290 errors)** - Missing game data

### Moderate Issues Requiring Investigation:
3. **Prediction Worker Auth Warnings (426 warnings)** - Need to verify predictions are working
4. **Phase 1 Container Startups (22 errors)** - Deployment issues
5. **Phase 2 Container Startups (362 errors)** - Deployment issues

### Low Priority Issues:
6. **Orchestration Deployment Timeouts (17 errors)** - Manual deployment artifacts
7. **Phase 1 Player Boxscore Failures (18 errors)** - Intermittent API issues

---

## Error Categories Summary

| Category | Count | Services Affected |
|----------|-------|-------------------|
| Data Quality / Staleness | 113 | Phase 3 Analytics |
| Scraper Validation Failures | 308 | Phase 1 Scrapers |
| Container Startup Failures | 384 | Phase 1, Phase 2 |
| Authentication Warnings | 426 | Prediction Worker |
| Deployment Timeouts | 17 | Orchestration Functions |
| Connection Errors | 25 | Multiple |
| Other | 730 | Multiple |

---

## No Evidence Found For:

✅ **Circuit Breaker Activations** - No circuit breaker errors detected  
✅ **Memory Limit Errors** - No OOM or memory errors detected  
✅ **API Rate Limiting (429 errors)** - No rate limit errors detected  
✅ **Database Connection Issues** - No database connection errors detected  
✅ **Pub/Sub Delivery Failures** - Only 1 transient error, no persistent failures  
✅ **Dead Letter Queue Messages** - No DLQ messages found  

---

## Recommended Actions

### Immediate (Today):
1. ✅ Investigate and resolve Phase 3 stale dependency issue (bdl_player_boxscores)
2. ✅ Verify prediction-worker authentication configuration
3. ✅ Check data completeness for game 0022500626 and related games

### Short-term (This Week):
4. Add monitoring alerts for table staleness approaching thresholds
5. Review and fix container startup health check failures
6. Implement retry logic for NBA.com API empty responses

### Medium-term (Next Sprint):
7. Add scraper-level alerts for repeated validation failures
8. Review and optimize deployment processes to reduce timeout errors
9. Implement comprehensive data completeness checks

### Long-term (Next Quarter):
10. Consider adding fallback data sources for critical game data
11. Implement blue-green deployments for zero-downtime updates
12. Build comprehensive monitoring dashboard for all pipeline stages

