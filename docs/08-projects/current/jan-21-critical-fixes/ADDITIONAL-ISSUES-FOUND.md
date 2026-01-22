# ADDITIONAL ISSUES FOUND - January 21, 2026
**Deep Analysis Date:** 2026-01-21 21:30 ET
**Status:** 🟡 HIGH PRIORITY - Multiple systemic issues identified
**Scope:** Cloud Scheduler, Firestore State, Health Checks, Pub/Sub, Data Quality, Configuration

---

## EXECUTIVE SUMMARY

After completing the initial critical fixes analysis, a deeper investigation uncovered **6 categories of additional issues** affecting system reliability, data quality, and operational health:

1. **Cloud Scheduler Failures** - 326 error events, 24 jobs affected, critical monitoring broken
2. **Firestore State Management** - Unbounded growth, missing cleanup, transaction issues
3. **Health Check Problems** - False positives, breaking changes, 24-hour undetected outage
4. **Pub/Sub Configuration** - 10-second ack deadline causing duplicate processing
5. **Data Quality Degradation** - BDL coverage at 57-63%, 17 games missing in 7 days
6. **Configuration Inconsistencies** - Hardcoded values, mismatched regions, 4 different project ID variable names

**Total New Issues:** 15 high/critical, 8 medium, 5 low priority

---

## CATEGORY 1: CLOUD SCHEDULER FAILURES

### Overview
Out of 85 Cloud Scheduler jobs (74 enabled), **24 jobs experienced 326 error events today**.

### 🔴 CRITICAL ISSUES

#### **Issue #5: Environment Variable Check Job Failing Constantly**
**Job:** `nba-env-var-check-prod`
**Frequency:** Every 5 minutes (288 runs/day)
**Failure Count:** 249 errors (86% failure rate)
**Error:** HTTP 403 - PERMISSION_DENIED
**Impact:** Environment validation completely broken

**Root Cause:**
Cloud Scheduler service account lacks permission to invoke `prediction-worker` Cloud Run service.

**Fix Required:**
```bash
gcloud run services add-iam-policy-binding prediction-worker \
  --region=us-west1 \
  --member="serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --project=nba-props-platform
```

**Priority:** IMMEDIATE - This is the #1 error in the system

---

#### **Issue #6: Daily Health Check Failed**
**Job:** `daily-health-check-8am-et`
**Scheduled:** 8:00 AM ET daily
**Status:** FAILED at 2026-01-21T13:00:47Z
**Error:** HTTP 500 - INTERNAL (URL_UNREACHABLE-UNREACHABLE_5xx)
**Impact:** Daily monitoring summary not sent

**Investigation Needed:**
- Check Cloud Function `daily-health-check` logs
- Verify function code for internal errors
- Check if function was recently deployed

**Priority:** HIGH - Critical monitoring functionality broken

---

#### **Issue #7: Self-Heal Predictions Timeout**
**Job:** `self-heal-predictions`
**Scheduled:** 12:45 PM ET daily
**Status:** TIMEOUT after 9 minutes
**Error:** HTTP 504 - DEADLINE_EXCEEDED
**Impact:** Prediction gaps not being filled automatically

**Details:**
- Started: 2026-01-21T17:45:00Z
- Failed: 2026-01-21T17:54:01Z
- Duration: 9 minutes, 1 second

**Root Cause Analysis Needed:**
- Large backlog of missing predictions
- Insufficient execution time (9 min timeout)
- Self-heal function may be doing too much work

**Potential Fix:**
```bash
# Increase timeout from 540s to 1800s (30 minutes)
gcloud scheduler jobs update http self-heal-predictions \
  --location=us-west2 \
  --attempt-deadline=1800s \
  --project=nba-props-platform
```

**Priority:** HIGH - Prediction gap recovery disabled

---

### 🟡 HIGH PRIORITY ISSUES

#### **Issue #8: Authentication Failures Across Multiple Jobs**
**Affected Jobs:** 8 jobs with HTTP 401 (UNAUTHENTICATED)
- `overnight-analytics-6am-et`
- `same-day-phase3`
- `same-day-phase3-tomorrow`
- `daily-yesterday-analytics`
- And 4 others

**Pattern:**
All failures involve Cloud Scheduler → Cloud Run authentication using OIDC tokens.

**Root Cause:**
Service account `scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com` lacks Cloud Run Invoker role on some services.

**Fix Required:**
```bash
# Audit all Cloud Run services
for service in nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  gcloud run services add-iam-policy-binding $service \
    --region=us-west2 \
    --member="serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project=nba-props-platform
done
```

**Priority:** HIGH - Multiple critical workflows affected

---

#### **Issue #9: Prediction Jobs Service Unavailability**
**Affected Jobs:**
- `overnight-predictions` (6 failures)
- `same-day-predictions` (6 failures)
- `same-day-predictions-tomorrow` (6 failures)
- `morning-predictions` (1 failure)

**Error:** HTTP 503 - UNAVAILABLE
**Pattern:** Clustered around 15:00-16:35 UTC (10:00 AM - 11:35 AM ET)

**Root Cause:**
Prediction coordinator service was overloaded or experiencing issues (correlates with ModuleNotFoundError deployment failure).

**Priority:** HIGH - Already being addressed by Fix #1 (prediction coordinator Dockerfile)

---

#### **Issue #10: BDL Live Boxscores Evening Outage**
**Job:** `bdl-live-boxscores-evening`
**Frequency:** Every 3 minutes
**Failure Count:** 13 errors
**Outage Duration:** 36 minutes (00:45-01:21 UTC / 4:45-5:21 PM PT)
**Error:** HTTP 500 - INTERNAL

**Timeline:**
- Normal operation until 00:45 UTC
- Service failed for 13 consecutive attempts
- Auto-recovered at 01:24 UTC

**Impact:**
Live game tracking interrupted during evening games (minor - self-recovered).

**Investigation Needed:**
Check Cloud Run logs for root cause during outage window.

**Priority:** MEDIUM - Self-recovered but pattern should be investigated

---

### 📋 Jobs That Didn't Run

#### **Issue #11: Scraper Availability Daily Check Missing**
**Job:** `scraper-availability-daily`
**Expected:** Daily at 1:00 PM ET (18:00 UTC)
**Status:** No execution logs found for Jan 21
**Last Update:** Job definition updated 2026-01-22T01:49:01Z

**Impact:**
Daily scraper health monitoring was skipped.

**Verification Needed:**
```bash
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="scraper-availability-daily"' \
  --limit=10 --format=json --project=nba-props-platform
```

**Priority:** MEDIUM - Monitoring gap

---

## CATEGORY 2: FIRESTORE STATE MANAGEMENT ISSUES

### Overview
Firestore orchestration state has **unbounded growth** and **missing cleanup mechanisms**.

### 🔴 CRITICAL ISSUES

#### **Issue #12: No Automatic Document Cleanup**
**Location:** `/orchestration/cloud_functions/transition_monitor/main.py` (lines 524-617)

**Problem:**
- Manual cleanup function exists but **no Cloud Scheduler job configured**
- 30-day TTL defined but never enforced
- Phase completion documents accumulate indefinitely
- Firestore collection grows unbounded

**Evidence:**
```python
# Line 41: DOCUMENT_TTL_DAYS = 30 (defined but not used automatically)
# Lines 524-617: cleanup_old_documents() function exists
# BUT: No scheduler calling this endpoint
```

**Impact:**
- Firestore costs increase over time
- Query performance degrades
- Storage bloat (estimated 1,000+ documents per year)

**Fix Required:**
```bash
# Create cleanup scheduler
gcloud scheduler jobs create http firestore-state-cleanup \
  --location=us-west2 \
  --schedule="0 3 * * 0" \
  --uri="https://transition-monitor-f7p3g7f6ya-wl.a.run.app/cleanup" \
  --http-method=POST \
  --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --time-zone="America/Los_Angeles" \
  --description="Weekly cleanup of old Firestore orchestration documents" \
  --project=nba-props-platform
```

**Priority:** HIGH - Unbounded storage growth

---

#### **Issue #13: Distributed Locks Never Cleaned Up**
**Location:** `/orchestration/shared/utils/distributed_lock.py` (lines 1-328)

**Problem:**
- Locks have `expires_at` timestamp but no automatic cleanup
- Expired locks remain in Firestore indefinitely
- Collections: `consolidation_locks`, `grading_locks`, etc. grow unbounded

**Code Evidence:**
```python
# Lines 167-175: Lock created with expires_at
lock_data = {
    'expires_at': datetime.utcnow() + timedelta(seconds=LOCK_TIMEOUT_SECONDS),
    # ... other fields
}

# BUT: No cleanup job to remove expired locks
```

**Impact:**
- Lock collections grow without bound
- Firestore costs increase
- Lock acquisition queries slower over time

**Fix Required:**
Add TTL field and create cleanup logic:
```python
# In distributed_lock.py
def cleanup_expired_locks(self):
    """Remove all expired locks from Firestore."""
    cutoff = datetime.utcnow()
    expired_query = self.db.collection(f'{self.lock_type}_locks').where('expires_at', '<', cutoff)
    # ... batch delete logic
```

**Priority:** MEDIUM - Long-term storage issue

---

### 🟡 HIGH PRIORITY ISSUES

#### **Issue #14: Transaction Overwrites Entire Document**
**Location:** `/orchestration/cloud_functions/phase3_to_phase4/main.py` (lines 820-829)

**Problem:**
Transaction uses `set()` instead of `update()`, which **overwrites the entire document**.

**Code:**
```python
# Line 827: Uses set() - DANGEROUS
transaction.set(doc_ref, current)
```

**Risk:**
If two transactions read the same state simultaneously, the second write overwrites changes from the first. Completed processors could be lost.

**Fix Required:**
```python
# Change from:
transaction.set(doc_ref, current)

# To:
transaction.update(doc_ref, {
    '_triggered': True,
    '_triggered_at': firestore.SERVER_TIMESTAMP,
    '_completed_count': completed_count,
    '_mode': mode,
    '_trigger_reason': trigger_reason
})
```

**Priority:** MEDIUM - Race condition possible but mitigated by idempotency

---

#### **Issue #15: Corrupted Timestamps Silently Skipped**
**Location:** `/orchestration/cloud_functions/transition_monitor/main.py` (lines 112-123)

**Problem:**
If a completion document has corrupted timestamp data, it's silently skipped with only a log warning. No alert is sent.

**Code:**
```python
try:
    first_completion = datetime.fromisoformat(first_completion_str.replace('Z', '+00:00'))
except (ValueError, TypeError):
    logger.warning(f"Invalid timestamp for {target_date}: {first_completion_str}")
    continue  # ⚠️ SILENTLY SKIPS
```

**Impact:**
Stuck states with bad data go undetected, no monitoring alert.

**Fix Required:**
```python
except (ValueError, TypeError):
    logger.error(f"CORRUPTED TIMESTAMP for {target_date}: {first_completion_str}")
    send_alert_to_slack(f"Firestore document corruption detected: {target_date}")
    continue
```

**Priority:** MEDIUM - Silent failures should be alertable

---

#### **Issue #16: Phase 2 Deadline Enforcement Disabled**
**Location:** `/orchestration/cloud_functions/phase2_to_phase3/main.py` (lines 64-66)

**Problem:**
Feature flag for Phase 2 completion deadline defaults to **false**, so timeout is never enforced.

**Code:**
```python
# Line 64-65
ENABLE_PHASE2_COMPLETION_DEADLINE = os.environ.get('ENABLE_PHASE2_COMPLETION_DEADLINE', 'false').lower() == 'true'
PHASE2_COMPLETION_TIMEOUT_MINUTES = int(os.environ.get('PHASE2_COMPLETION_TIMEOUT_MINUTES', '30'))
```

**Impact:**
Phase 2 can wait indefinitely for processors that will never complete.

**Recommendation:**
Enable feature flag in staging first, then production:
```bash
gcloud functions deploy phase2-to-phase3-orchestrator \
  --update-env-vars ENABLE_PHASE2_COMPLETION_DEADLINE=true \
  --region=us-west2 \
  --project=nba-props-platform
```

**Priority:** LOW - Feature exists but intentionally disabled (likely for good reason)

---

#### **Issue #17: No Timeout Checks for Phase 2→3 and 3→4**
**Location:** Only Phase 4 has timeout monitoring

**Problem:**
- Phase 4 has `phase4_timeout_check` Cloud Function
- **No equivalent for Phase 2→3 or Phase 3→4 transitions**
- These phases can get stuck indefinitely without automatic recovery

**Impact:**
Manual intervention required if Phase 2 or 3 gets stuck.

**Recommendation:**
Create timeout check functions for all phase transitions.

**Priority:** MEDIUM - Architectural gap

---

## CATEGORY 3: HEALTH CHECK PROBLEMS

### 🔴 CRITICAL ISSUES

#### **Issue #18: Health Check Always Returns 200 (False Positive)**
**Location:** `/shared/endpoints/health.py` (line 157)

**Problem:**
The Week 1 HealthChecker implementation always returns HTTP 200, **even when dependencies fail**.

**Code:**
```python
# Line 157
return response, 200  # ← ALWAYS 200, even if status='degraded'
```

**Impact:**
- Cloud Run health checks see service as healthy when it's degraded
- Services with failing dependencies appear healthy
- No automated alerting on dependency failures

**Fix Required:**
```python
# Change line 157 from:
return response, 200

# To:
status_code = 200 if response['status'] == 'healthy' else 503
return response, status_code
```

**Priority:** HIGH - False positives hiding real problems

---

#### **Issue #19: Breaking Changes Caused 24-Hour Undetected Outage**
**Incident:** Jan 20-21, 2026
**Impact:** Phase 3 and Phase 4 services unavailable for 24+ hours

**Root Cause:**
1. Week 1 improvements removed `project_id` parameter from HealthChecker
2. Services still passed `project_id` causing TypeError
3. Services crashed on **any request**
4. No pre-deployment validation caught the breaking change

**Files Affected:**
- `/data_processors/analytics/main_analytics_service.py`
- `/data_processors/precompute/main_precompute_service.py`
- `/services/admin_dashboard/main.py`

**What Was Missing:**
- Integration tests for service startup
- Pre-deployment health check validation
- Automated smoke tests

**Priority:** CRITICAL - Already fixed but prevention measures needed

---

### 🟡 HIGH PRIORITY ISSUES

#### **Issue #20: Inconsistent Health Check Patterns**
**Location:** `/shared/endpoints/health.py`

**Problem:**
Two different health check implementations exist in the same file:
1. **Lines 1-207:** Legacy Week 1 enhanced pattern
2. **Lines 42-757:** Comprehensive HealthChecker class

**Impact:**
- Confusion about which to use
- Some services use legacy, others use new
- Inconsistent behavior across services

**Recommendation:**
Deprecate legacy implementation, standardize on comprehensive HealthChecker.

**Priority:** MEDIUM - Technical debt

---

## CATEGORY 4: PUB/SUB CONFIGURATION ISSUES

### 🔴 CRITICAL ISSUES

#### **Issue #21: Phase 4 Trigger Subscription Has 10-Second Ack Deadline**
**Subscription:** `eventarc-us-west2-nba-phase4-trigger-sub-sub-438`
**Topic:** `nba-phase4-trigger`
**Ack Deadline:** 10 seconds (EXTREMELY SHORT)

**Problem:**
- Phase 4 precompute processors can take **60+ seconds** to process
- With only 10-second ack deadline, Pub/Sub considers message undelivered
- Causes **duplicate processing** and potential **infinite retry loops**
- **No DLQ configured**, so failed messages retry indefinitely

**Evidence:**
All other phase subscriptions have 600-second ack deadlines except this one.

**Fix Required:**
```bash
gcloud pubsub subscriptions update eventarc-us-west2-nba-phase4-trigger-sub-sub-438 \
  --ack-deadline=600 \
  --dead-letter-topic=nba-phase4-trigger-dlq \
  --max-delivery-attempts=5 \
  --project=nba-props-platform
```

**Priority:** CRITICAL - Causing duplicate processing right now

---

### 🟡 HIGH PRIORITY ISSUES

#### **Issue #22: Missing DLQ Monitoring Subscriptions**
**Status:** DLQ topics exist but not monitored

**Missing Monitoring:**
- `nba-phase1-scrapers-complete-dlq` - No subscription
- `nba-phase2-raw-complete-dlq` - No subscription
- `nba-phase3-analytics-complete-dlq` - No subscription
- `nba-phase4-precompute-complete-dlq` - No subscription

**Only Monitored:**
- `prediction-request-dlq-sub` - Only 1 DLQ being monitored

**Impact:**
Failed messages go to DLQ but nobody knows.

**Fix Required:**
```bash
# Create monitoring subscriptions for all DLQs
for dlq in phase1-scrapers-complete phase2-raw-complete phase3-analytics-complete phase4-precompute-complete; do
  gcloud pubsub subscriptions create nba-${dlq}-dlq-sub \
    --topic=nba-${dlq}-dlq \
    --ack-deadline=60 \
    --message-retention-duration=7d \
    --project=nba-props-platform
done
```

**Priority:** HIGH - Silent failures not detected

---

#### **Issue #23: Phase 3 DLQ Has No Explicit Retention**
**Topic:** `nba-phase3-analytics-complete-dlq`

**Problem:**
No message retention duration configured (defaults to 7 days but not explicit).

**Fix Required:**
```bash
gcloud pubsub topics update nba-phase3-analytics-complete-dlq \
  --message-retention-duration=7d \
  --project=nba-props-platform
```

**Priority:** MEDIUM - Defaults work but should be explicit

---

## CATEGORY 5: DATA QUALITY DEGRADATION

### 🔴 CRITICAL ISSUES

#### **Issue #24: BDL Data Coverage at 57-63% (Severe)**
**Status:** 17 games missing from BDL in last 7 days

**Coverage Analysis:**
- **Jan 15:** 11.1% coverage (1 of 9 games) - WORST DAY
- **Jan 20:** 57.1% coverage (4 of 7 games)
- **Overall (7 days):** 63% coverage for final games
- **Overall (30 days):** ~70% coverage

**Missing Games Breakdown:**
- Jan 20: LAL @ DEN, TOR @ GSW, MIA @ SAC (3 missing)
- Jan 19: MIA @ GSW (1 missing)
- Jan 18: POR @ SAC, TOR @ LAL (2 missing)
- Jan 17: WAS @ DEN, LAL @ POR (2 missing)
- Jan 16: WAS @ SAC (1 missing)
- Jan 15: 8 of 9 games missing (CRITICAL GAP)

**Impact:**
- BDL cannot be trusted as primary data source
- Analytics layer compensating with Gamebook (good)
- But validation checks blocking analytics when BDL stale

**Root Cause:**
BDL API availability issues or rate limiting, not scraper failures.

**Priority:** CRITICAL - Data quality fundamental issue

---

#### **Issue #25: NBA.com Team Boxscore Scraper Failing Constantly**
**Status:** 148 consecutive failures in 24 hours (0% success rate)

**Error Pattern:**
```
Expected 2 teams for game [ID], got 0
No player rows in leaguegamelog JSON
```

**Root Cause:**
Scrapers triggering prematurely for games that haven't started yet. API returns empty data for future games.

**Fix Required:**
Add game status check before scraping:
```python
# Only scrape if game is "Final"
if game_status != "Final":
    logger.info(f"Skipping game {game_id} - status: {game_status}")
    return
```

**Priority:** HIGH - Generating noise and potentially missing real failures

---

### 🟡 HIGH PRIORITY ISSUES

#### **Issue #26: BDL API Instability**
**Status:** 13 API failures with 500 errors in last 24 hours

**Pattern:**
- Normal success rate: >99%
- Current success rate: 93.5%
- Error: "500 Internal Server Error" from BDL API

**Impact:**
BDL API experiencing reliability issues beyond our control.

**Recommendation:**
- Continue using Gamebook as primary source
- Treat BDL as validation/supplementary only
- Contact BDL support about API stability

**Priority:** MEDIUM - External dependency issue

---

## CATEGORY 6: CONFIGURATION INCONSISTENCIES

### 🟡 HIGH PRIORITY ISSUES

#### **Issue #27: Four Different Project ID Variable Names**
**Status:** Inconsistent environment variable naming

**Variable Names Found:**
1. `GCP_PROJECT` - Used in phase orchestrators
2. `PROJECT_ID` - Used in secrets manager, sport config
3. `GCP_PROJECT_ID` - Used in MLB deployments, pubsub clients
4. `GOOGLE_CLOUD_PROJECT` - Checked as fallback in auth utils

**Impact:**
- Configuration confusion
- Services may use wrong project
- Harder to manage multi-environment deployments

**Files Affected:**
- `/shared/utils/secrets.py:23` - Uses `PROJECT_ID`
- `/orchestration/cloud_functions/phase2_to_phase3/main.py:60` - Uses `GCP_PROJECT`
- `/orchestration/cloud_functions/daily_health_summary/shared/utils/pubsub_publishers.py:58` - Uses `GCP_PROJECT_ID`

**Fix Required:**
Standardize on `GCP_PROJECT_ID` across all services.

**Priority:** MEDIUM - Technical debt causing confusion

---

#### **Issue #28: Hardcoded Service URLs in Self-Heal Function**
**Location:** `/orchestration/cloud_functions/self_heal/main.py` (lines 50-52)

**Code:**
```python
PHASE3_URL = "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
PHASE4_URL = "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
COORDINATOR_URL = "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
```

**Problem:**
- Hardcoded production URLs
- Cannot use same code for staging/dev
- Must redeploy to change URLs

**Fix Required:**
```python
PHASE3_URL = os.environ.get('PHASE3_URL', 'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app')
PHASE4_URL = os.environ.get('PHASE4_URL', 'https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app')
COORDINATOR_URL = os.environ.get('COORDINATOR_URL', 'https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app')
```

**Priority:** MEDIUM - Limits multi-environment deployment

---

#### **Issue #29: Region Mismatch (Terraform vs Scripts)**
**Status:** Inconsistent default regions

**Mismatch:**
- **Terraform:** `/infra/variables.tf:7` - Defaults to `us-central1`
- **Deployment Scripts:** 40+ scripts - Use `us-west2`

**Impact:**
- Resources may deploy to wrong region
- Cost implications (inter-region traffic)
- Latency concerns

**Fix Required:**
Update Terraform default to match deployment scripts:
```hcl
variable "region" {
  type    = string
  default = "us-west2"  # Change from us-central1
}
```

**Priority:** MEDIUM - Infrastructure consistency

---

#### **Issue #30: Hardcoded Project ID in 100+ Files**
**Status:** Project ID hardcoded throughout codebase

**Examples:**
- `/shared/utils/bigquery_utils.py:23` - `DEFAULT_PROJECT_ID = "nba-props-platform"`
- `/shared/utils/odds_preference.py:35` - `PROJECT_ID = "nba-props-platform"`
- 100+ shell scripts in `/bin/` directory

**Impact:**
- Cannot easily support multiple projects
- Harder to test in non-prod environments
- Multi-tenant architecture difficult

**Fix Required:**
Replace all hardcoded values with environment variable references.

**Priority:** LOW - Works fine for single-project but technical debt

---

## SUMMARY OF ALL ISSUES

### Critical Priority (🔴)
1. Issue #5: Environment variable check job failing (249 errors)
2. Issue #6: Daily health check failed (monitoring broken)
3. Issue #7: Self-heal predictions timeout (9-minute limit)
4. Issue #12: No automatic Firestore document cleanup (unbounded growth)
5. Issue #13: Distributed locks never cleaned up
6. Issue #18: Health check always returns 200 (false positives)
7. Issue #19: Breaking changes caused 24-hour outage (already fixed)
8. Issue #21: Phase 4 subscription 10-second ack deadline (duplicate processing)
9. Issue #24: BDL data coverage at 57-63% (17 games missing)
10. Issue #25: NBA.com scraper failing constantly (148 errors)

### High Priority (🟡)
11. Issue #8: Authentication failures (8 jobs affected)
12. Issue #9: Prediction jobs unavailability (already being fixed)
13. Issue #10: BDL live boxscores outage (36 minutes)
14. Issue #14: Transaction overwrites (race condition possible)
15. Issue #15: Corrupted timestamps silently skipped
16. Issue #17: No timeout checks for Phase 2→3, 3→4
17. Issue #20: Inconsistent health check patterns
18. Issue #22: Missing DLQ monitoring subscriptions
19. Issue #26: BDL API instability
20. Issue #27: Four different project ID variable names
21. Issue #28: Hardcoded service URLs
22. Issue #29: Region mismatch (Terraform vs scripts)

### Medium Priority
23. Issue #11: Scraper availability check missing
24. Issue #23: Phase 3 DLQ no explicit retention

### Low Priority
25. Issue #16: Phase 2 deadline disabled (intentional)
26. Issue #30: Hardcoded project ID (technical debt)

---

## RECOMMENDED ACTION PLAN

### Immediate (Next 1-2 Hours)
1. ✅ Fix Issue #5: Grant scheduler service account Cloud Run Invoker permissions
2. ✅ Fix Issue #21: Update Phase 4 subscription ack deadline to 600s
3. ✅ Fix Issue #6: Investigate daily health check failure

### High Priority (Next 24 Hours)
4. ✅ Fix Issue #8: Grant authentication permissions to all scheduler jobs
5. ✅ Fix Issue #12: Create Firestore cleanup scheduler
6. ✅ Fix Issue #18: Fix health check to return 503 on degraded status
7. ✅ Fix Issue #22: Create DLQ monitoring subscriptions
8. ✅ Fix Issue #25: Add game status check to NBA.com scraper
9. ✅ Investigate Issue #24: BDL data quality (contact BDL support)

### Medium Priority (Next Week)
10. ✅ Fix Issue #7: Increase self-heal timeout to 30 minutes
11. ✅ Fix Issue #14: Change transaction from set() to update()
12. ✅ Fix Issue #27: Standardize on GCP_PROJECT_ID variable
13. ✅ Fix Issue #28: Convert hardcoded URLs to env vars
14. ✅ Fix Issue #29: Fix Terraform region mismatch
15. ✅ Create timeout checks for Phase 2→3 and 3→4

### Long-Term (Next Month)
16. ✅ Standardize health check implementation
17. ✅ Add pre-deployment validation tests
18. ✅ Implement comprehensive DLQ monitoring
19. ✅ Replace hardcoded project IDs with env vars
20. ✅ Create distributed lock cleanup mechanism

---

## FILES TO MODIFY - ADDITIONAL FIXES

| Priority | File | Line | Change |
|----------|------|------|--------|
| 🔴 CRITICAL | Grant IAM permissions | N/A | Add Cloud Run Invoker role |
| 🔴 CRITICAL | Phase 4 subscription config | N/A | Update ack deadline 10s→600s |
| 🔴 CRITICAL | `/shared/endpoints/health.py` | 157 | Return 503 on degraded status |
| 🟡 HIGH | Create cleanup scheduler | N/A | Weekly Firestore cleanup |
| 🟡 HIGH | `/orchestration/cloud_functions/phase3_to_phase4/main.py` | 827 | Change set() to update() |
| 🟡 HIGH | `/scrapers/nbacom/nbac_team_boxscore.py` | TBD | Add game status check |
| 🟡 MEDIUM | `/orchestration/cloud_functions/self_heal/main.py` | 50-52 | Convert URLs to env vars |
| 🟡 MEDIUM | `/infra/variables.tf` | 7 | Change region default |

---

## DOCUMENT METADATA

**Created:** 2026-01-21 21:30 ET
**Agent Count:** 6 specialized exploration agents
**Total Issues Found:** 30 (15 critical/high, 8 medium, 7 low)
**Analysis Scope:**
- Cloud Scheduler: 85 jobs analyzed
- Firestore: 5 collections examined
- Health Checks: 6 services reviewed
- Pub/Sub: 12 topics/subscriptions audited
- Data Quality: 30-day analysis completed
- Configuration: 100+ files scanned

**Next Session Action:** Review both CRITICAL-FIXES-REQUIRED.md and this document to prioritize fixes
