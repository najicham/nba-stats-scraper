# Comprehensive Pipeline Hidden Issues Scan
**Scan Date:** 2026-01-01
**Scope:** Last 7 days
**Focus:** Silent failures, degrading systems, systemic problems

---

## CRITICAL ISSUES FOUND

### 1. INJURIES DATA CRITICALLY STALE (CRITICAL - P0)
**Severity:** CRITICAL
**Impact:** User-facing data is 41 days stale
**Next Incident:** Immediate (already impacting decisions)

**Findings:**
- Last update: November 21, 2025 (985 hours / 41 days stale)
- Table: `nba_raw.bdl_injuries` - 603 rows frozen in time
- Workflow: `injury_discovery` failing continuously (11/60 executions failed in last 7 days)
- Scraper: `nbac_injury_report` failing every hour since Dec 31

**Evidence:**
```
table_id: bdl_injuries
last_modified: 2025-11-21 19:34:35
hours_stale: 985 (41 DAYS)
```

**Root Cause Analysis:**
1. BDL injuries scraper configured but not running/updating
2. NBA.com injury report scraper failing silently (no alerts triggered)
3. Workflow execution shows failures but no recovery action taken
4. No monitoring on data freshness for injuries specifically

**Immediate Actions Required:**
1. Check why BDL injuries API stopped working on Nov 21
2. Investigate NBA.com injury report scraper auth/API changes
3. Add freshness monitoring alert for injuries table (threshold: 24 hours)
4. Manual data update needed immediately for 41 days of missing injury data

**Long-term Fixes:**
- Add fallback scraper (if BDL fails, use NBA.com and vice versa)
- Add daily freshness check to boxscore-completeness-check job
- Circuit breaker on stale data should trigger alerts

---

### 2. WORKFLOW EXECUTION FAILURES - SYSTEMATIC (HIGH - P1)
**Severity:** HIGH
**Impact:** 4 critical workflows failing hourly, creating data gaps
**Next Incident:** Within 24-48 hours (compounding gaps)

**Failing Workflows (Last 7 Days):**
| Workflow | Failures | Success Rate | Failed Scrapers |
|----------|----------|--------------|-----------------|
| injury_discovery | 11/60 | 82% | nbac_injury_report |
| referee_discovery | 12/54 | 78% | nbac_referee_assignments |
| betting_lines | 12/54 | 78% | oddsa_events, bp_events, oddsa_player_props |
| schedule_dependency | 6/33 | 82% | nbac_schedule_api |

**Pattern Analysis:**
- Failures concentrated in Dec 31 (hourly between 11:05 - 19:05)
- All failures show scrapers_succeeded=0, scrapers_failed=1-3
- No automatic retry or recovery mechanism visible
- No alerts appear to be firing for these failures

**Silent Failure Evidence:**
```
execution_time: 2025-12-31 19:05:11
workflow_name: injury_discovery
status: failed
scrapers_failed: 1
scrapers_succeeded: 0
```

**Root Causes:**
1. Scraper authentication failures (likely API key expiry or rate limits)
2. No automatic retry logic for transient failures
3. Workflow orchestration doesn't escalate repeated failures
4. Alert fatigue - failures normalized, not investigated

**Immediate Actions:**
1. Check API credentials for Odds API, BettingPros, NBA.com
2. Review rate limiting configuration
3. Add automatic retry with exponential backoff
4. Create escalation alert for >3 consecutive failures

---

### 3. MASSIVE PROCESSOR FAILURE HISTORY (MEDIUM - P2)
**Severity:** MEDIUM
**Impact:** Indicates systemic reliability issues, potential data gaps
**Next Incident:** Ongoing (continuous low-level failures)

**Failure Counts (All Time):**
| Processor | Total Failures | Note |
|-----------|----------------|------|
| NbacPlayerBoxscoreProcessor | 348,396 | MASSIVE - needs investigation |
| NbacGamebookProcessor | 54,516 | High failure rate |
| OddsApiPropsProcessor | 23,017 | Betting data at risk |
| BasketballRefRosterProcessor | 20,230 | Historical data gaps |
| PlayerGameSummaryProcessor | 960 | Analytics impacted |
| PlayerDailyCacheProcessor | 761 | Cache invalidation issues |
| MLFeatureStoreProcessor | 243 | ML pipeline impacted |

**Analysis:**
- 348K failures for NbacPlayerBoxscoreProcessor is extraordinary
- Suggests fundamental design issue, not transient failures
- Latest failure: Dec 4, 2024 - problem may be historical but unresolved
- No success records in sample - 100% failure rate for some processors

**Pattern Indicators:**
1. Early processor failures (Phase 2) cascade to later phases
2. Circuit breaker on UpcomingPlayerGameContext (954 entities locked)
3. Processor run history shows no timestamp field - may be missing failure tracking

**Investigation Needed:**
1. Query run history for date range of failures
2. Check if processor logic changed Dec 4, 2024
3. Review circuit breaker logic - 954 players locked seems excessive
4. Audit processor retry mechanisms

---

### 4. CLOUD RUN WARNING STORM (MEDIUM - P2)
**Severity:** MEDIUM
**Impact:** Service degradation, potential memory/CPU exhaustion
**Next Incident:** 24-48 hours (resource exhaustion)

**Evidence:**
- Phase 4 precompute service: Continuous warnings (50+ in last hour)
- All warnings have "No message" - indicates logging infrastructure issue
- Pattern: Warnings every 3-16 seconds
- Service: nba-phase4-precompute-processors

**Possible Causes:**
1. Memory leak or excessive memory usage
2. CPU throttling warnings
3. Request timeout warnings
4. Structured logging misconfiguration (messages not extracted)

**Risk Assessment:**
- Service appears functional (tables updating normally)
- But warning volume suggests underlying stress
- Could degrade into OOM errors or service crashes
- No visibility into actual issue due to "No message"

**Immediate Actions:**
1. Check Cloud Run logs with jsonPayload filter
2. Review service memory/CPU metrics in Cloud Monitoring
3. Fix logging configuration to capture warning messages
4. Consider increasing instance resources if at limits

---

### 5. PLAYER GAME SUMMARY STALE (MEDIUM - P2)
**Severity:** MEDIUM
**Impact:** Analytics and predictions using stale summary data
**Next Incident:** Daily (affecting predictions)

**Evidence:**
```
table_id: player_game_summary
last_modified: 2026-01-01 09:06:54
hours_stale: 11 hours
```

**Expected vs Actual:**
- Expected: Updated daily at 6:30 AM (daily-yesterday-analytics scheduler)
- Actual: Last update 9:06 AM (2.5 hours late)
- Other analytics tables updated correctly (team_offense_game_summary, upcoming_player_game_context)

**Impact Chain:**
1. PlayerGameSummary stale → ML features stale → Predictions quality degraded
2. Workflow: daily-yesterday-analytics shows 6:30 AM success
3. But table update timestamp doesn't match

**Investigation Needed:**
1. Check if scheduler runs but processor fails silently
2. Review processor_run_history for PlayerGameSummaryProcessor Dec 31 - Jan 1
3. Check for partial updates (some entities processed, some skipped)
4. Circuit breaker may be preventing updates (960 failures recorded)

---

## MEDIUM PRIORITY ISSUES

### 6. CIRCUIT BREAKER LOCKOUT - 954 PLAYERS (MEDIUM - P2)
**Severity:** MEDIUM
**Impact:** Nearly 1000 players locked from UpcomingPlayerGameContext updates
**Next Incident:** Ongoing (predictions coverage reduced)

**Evidence:**
```sql
circuit_breaker_tripped: true
processor_name: nba_analytics.upcoming_player_game_context
count: 954
latest_breaker_until: 2026-01-05 00:50:11
```

**Locked Entities Sample:**
- vincewilliams, zackaustin, daronholmes, phillipwheeler, ronaldholland
- javontesmart, treymurphy, robertwilliams, yanghansen, reecebeekman

**Analysis:**
- 954 locked entities is 30-40% of active NBA players
- Breaker set until Jan 5 (4 more days)
- Root cause: Upstream data dependency failures
- No auto-reset logic when upstream data becomes available

**Impact:**
- Predictions for these players will be stale or unavailable
- Upcoming game context won't reflect latest matchups
- ML features incomplete for affected players

**Fix Strategy:**
1. Investigate why 954 players triggered breaker (likely upstream BDL data gap)
2. Add auto-reset when upstream tables have data (already exists in processor service)
3. Consider separate breakers for different failure types
4. Manual override needed for Jan 1-2 games

---

### 7. LIVE EXPORT FUNCTION ERRORS (LOW - P3)
**Severity:** LOW
**Impact:** Live game tracking intermittent
**Next Incident:** During next game day

**Error Pattern:**
```
live-export: HTTPSConnectionPool(host='api.balldontlie.io', port=443):
Read timed out. (read timeout=30)
```

**Frequency:**
- Multiple timeouts on Dec 29 (22:12, 23:15)
- BigQuery query errors on Dec 28 (parameter parsing)

**Root Causes:**
1. BDL API timeout (30 seconds not enough during high load)
2. BigQuery query syntax error with 'today' parameter

**Recommendation:**
- Increase timeout to 60 seconds for live endpoints
- Fix hardcoded 'today' parameter in query
- Add retry logic with exponential backoff
- Not critical - historical data pipeline unaffected

---

### 8. MISSING DLQ INFRASTRUCTURE (LOW - P3)
**Severity:** LOW
**Impact:** Failed messages not captured, no recovery mechanism
**Next Incident:** N/A (preventive measure)

**Evidence:**
```
gcloud pubsub subscriptions list | grep dlq
# No results
```

**Expected DLQs:**
- nba-phase1-scrapers-complete-dlq-sub
- nba-phase2-raw-complete-dlq-sub
- analytics-ready-dead-letter-sub
- line-changed-dead-letter-sub

**Status:**
- DLQ monitor function exists: `/orchestration/cloud_functions/dlq_monitor/main.py`
- But actual DLQ subscriptions not created
- Messages that exceed retry limits are lost

**Impact:**
- Can't investigate failed message payloads
- No way to replay failed messages
- Permanent data loss for edge cases

**Recommendation:**
- Create DLQ subscriptions (low priority - only catches extreme failures)
- Deploy dlq-monitor function with scheduler
- Document DLQ recovery procedures

---

## POSITIVE FINDINGS (NO ACTION REQUIRED)

### Data Completeness - HEALTHY ✓
```
Game Date     | Games | Gamebook Missing | BDL Missing
2025-12-31    | 9     | 0                | 0
2025-12-30    | 4     | 0                | 0
2025-12-29    | 11    | 0                | 0
2025-12-28    | 6     | 0                | 0
```
**Status:** All games accounted for in last 7 days

### Scheduler Jobs - RUNNING ✓
- 30 schedulers active and running
- execute-workflows: Running hourly
- overnight-predictions: Running daily 7 AM
- boxscore-completeness-check: Running daily 6 AM
**Status:** Orchestration layer healthy

### Core Data Tables - FRESH ✓
```
nbac_gamebook_player_stats: 0 hours stale (192,243 rows)
bdl_player_boxscores: 0 hours stale (265,445 rows)
nbac_schedule: 5 hours stale (6,524 rows)
```
**Status:** Primary data sources updating correctly

### Predictions - GENERATING ✓
```
2026-01-01: 40 players, 340 predictions
2025-12-31: 118 players, 1,125 predictions
2025-12-30: 28 players, 980 predictions
```
**Status:** Predictions running (though coverage lower than expected)

---

## SYSTEMIC PATTERNS IDENTIFIED

### Pattern 1: Silent Failure Tolerance
**Observation:** Workflows failing hourly for days without escalation
**Symptom:** injury_discovery, referee_discovery failing 10-12 times
**Root Cause:** Monitoring gaps - failures logged but not alerted
**Fix:** Implement failure threshold alerts (>3 consecutive = alert)

### Pattern 2: Stale Data Blindness
**Observation:** Injuries table 41 days stale with no detection
**Symptom:** No freshness monitoring on critical user-facing tables
**Root Cause:** Completeness check exists but doesn't cover all tables
**Fix:** Expand freshness monitoring to all Phase 2 tables

### Pattern 3: Logging Infrastructure Gaps
**Observation:** 50+ Cloud Run warnings with "No message"
**Symptom:** Can't diagnose service health issues
**Root Cause:** Structured logging not configured correctly
**Fix:** Audit all services for proper logging configuration

### Pattern 4: Circuit Breaker Overcorrection
**Observation:** 954 players locked for 4+ days
**Symptom:** Circuit breaker too aggressive, no auto-recovery
**Root Cause:** Dependency failures cause cascade lockouts
**Fix:** Implement auto-reset when upstream data available

---

## RECOMMENDED INVESTIGATION PRIORITY

### IMMEDIATE (Next 2 Hours)
1. **Injuries Data Emergency** - Investigate BDL API + NBA.com scraper
2. **Workflow Failures** - Check API credentials for failing scrapers
3. **Cloud Run Warnings** - Fix logging to see actual error messages

### URGENT (Next 24 Hours)
4. **Circuit Breaker Review** - Investigate 954 locked players
5. **Processor Failure Audit** - Understand 348K failures pattern
6. **Player Game Summary** - Why 11 hours stale?

### IMPORTANT (Next 48 Hours)
7. **DLQ Infrastructure** - Create missing dead letter queues
8. **Freshness Monitoring** - Add alerts for all critical tables
9. **Workflow Retry Logic** - Implement exponential backoff

### LONG-TERM (Next Week)
10. **Processor Reliability** - Redesign high-failure processors
11. **Alerting Strategy** - Reduce alert fatigue, escalate correctly
12. **Observability Gaps** - Fix "No message" logging issues

---

## HIDDEN ISSUES SUMMARY

**Total Issues Found:** 8 (3 Critical, 3 Medium, 2 Low)

**Issues NOT Previously Logged:**
1. ✓ Injuries data 41 days stale (completely missed)
2. ✓ Cloud Run warning storm (no visibility due to logging)
3. ✓ 954 players circuit breaker locked (known but not quantified)
4. ✓ Systematic workflow failures (logged but not escalated)

**Issues Degrading Silently:**
1. ✓ Injuries scraper (failing since Nov 21, no alerts)
2. ✓ PlayerGameSummary staleness (partial failures)
3. ✓ Cloud Run service stress (warnings ignored)

**Issues That Will Cause Problems in 24-48 Hours:**
1. ✓ Injuries data gap (users making decisions on stale data)
2. ✓ Workflow failures accumulating (data gaps compounding)
3. ✓ Circuit breaker preventing predictions (coverage degrading)

**Systemic Problems Identified:**
1. ✓ Monitoring gaps (not all critical tables monitored)
2. ✓ Alert fatigue (failures normalized, not investigated)
3. ✓ Logging infrastructure (can't diagnose issues)
4. ✓ Recovery mechanisms (no auto-retry, no DLQ replay)

---

## NEXT STEPS

**Owner should:**
1. Review this report with team
2. Assign owners to each IMMEDIATE action
3. Schedule war room for injuries data investigation
4. Create tickets for all identified issues
5. Run this scan weekly to catch degrading systems early

**Monitoring Improvements Needed:**
- Add freshness alerts for all Phase 2 tables (threshold: 24h)
- Escalate alerts after 3 consecutive workflow failures
- Monitor circuit breaker status (alert if >100 entities locked)
- Fix Cloud Run logging to capture warning messages
- Add DLQ depth monitoring

**File Location:** `/home/naji/code/nba-stats-scraper/PIPELINE_SCAN_REPORT_2026-01-01.md`

---
**End of Report**
