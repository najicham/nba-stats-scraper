# Session 18 Prioritized Implementation Plan

**Date:** January 12, 2026 (Session 18)
**Status:** IN PROGRESS - Phase A
**Focus:** Post-Session 17 cleanup, monitoring enhancements, data quality fixes

---

## Current Progress

| Task | Status | Notes |
|------|--------|-------|
| A1. Verify Scheduler Jobs | **COMPLETE** | Both jobs running, 0 pending failures |
| A2. Registry Monitoring | **COMPLETE** | Deployed, tested, shows 0 pending |
| A3. Deploy Normalization | **COMPLETE** | Revision `00086-xgg`, commit `0458005` |

### Phase A Completion Summary

**Completed:** January 12, 2026 @ 16:27 UTC

**A1 Results:**
- `registry-ai-resolution`: Last run 15:26 UTC, ENABLED
- `registry-health-check`: Last run 10:00 UTC, ENABLED
- Registry pending: 0 players (628 resolved)

**A2 Results:**
- Added `check_registry_failures()` method to HealthChecker
- Integrated into `run_health_check()` with thresholds (>5 warning, >20 critical)
- Added to Slack summary under "Registry Status"
- Deployed as `daily-health-summary-00003-rab`
- Tested: Returns `{"pending_players": 0, "pending_records": 0}`

**A3 Results:**
- Verified ESPN roster processor uses `normalize_name()` (line 166)
- Verified BettingPros processor uses `normalize_name()` (line 306)
- Deployed as `nba-phase2-raw-processors-00086-xgg`
- Commit SHA verified: `0458005`
- Health check passed

**Note:** SLACK_WEBHOOK_URL not configured - Slack alerts disabled. Configure to enable alerts.

### Phase B Status (Verified Jan 12)

| Task | Status | Finding |
|------|--------|---------|
| B1: Prediction Duplicates | **ALREADY DONE** | MERGE with ROW_NUMBER deduplication |
| B2: BigQuery Timeouts | **ALREADY DONE** | 30s timeout in place |
| B3: Circuit Breaker Hardcodes | **DEFERRED** | Values consistent, no visibility gain |

### Phase C Progress

**C1: DLQ Monitoring - COMPLETE**
- Created scheduler job: `dlq-monitor-job` (every 15 min)
- **FOUND 83 failed predictions** in `prediction-request-dlq-sub`
  - Messages from Jan 4-10, 2026
  - 255 delivery attempts each (max retries)
  - Sample: `treymurphyiii` for game `20260104_NOP_MIA`
- Gap: Slack webhook not configured (`slack-webhook-default` secret missing)
- Gap: 5/6 DLQ subscriptions don't exist yet

**Action Required:** Investigate 83 failed predictions in DLQ

**C2: Phase 5→6 Validation - ALREADY IMPLEMENTED**
Verified existing safeguards in `phase5_to_phase6/main.py`:
- `MIN_COMPLETION_PCT = 80.0` (line 69) - Won't export if <80% completed
- `MIN_PREDICTIONS_REQUIRED = 10` (line 76) - Won't export if <10 predictions
- `validate_predictions_exist()` - Queries BigQuery before export
- Logs warnings and skips export if validation fails

### Outstanding Items

**Configure Slack Alerts:**
```bash
# Create the secret
gcloud secrets create slack-webhook-default --project=nba-props-platform
echo -n "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" | \
  gcloud secrets versions add slack-webhook-default --data-file=-
```

**Investigate DLQ Messages:**
```bash
# View failed prediction details
curl "https://dlq-monitor-f7p3g7f6ya-wl.a.run.app"

# Clear DLQ after investigation (if messages are stale)
./bin/recovery/clear_dlq.sh prediction-request-dlq-sub
```

---

## Executive Summary

After deep analysis of Session 17 handoff, MASTER-TODO.md, and codebase exploration, this document provides a prioritized implementation plan. Key finding: **Several P0 items are already complete but not marked as such in MASTER-TODO.md.**

---

## Status Corrections

### Items Already Complete (Need Documentation Update)

| Item | Claimed Status | Actual Status | Evidence |
|------|---------------|---------------|----------|
| **P0-SEC-1** | Not Started | **COMPLETE** | `coordinator.py:89-215` - `require_api_key` decorator exists |
| **P0-ORCH-1** | Not Started | **COMPLETE** | `cleanup_processor.py:287` - Actual Pub/Sub publishing implemented |
| **P0-ORCH-2** | Not Started | **COMPLETE** | Session 17 deployed `phase4_timeout_check` + fixed HTTP handling |

### MASTER-TODO.md Accuracy Issues

The file header says "Last Updated: January 12, 2026 (Session 13C)" but the footer says "Last Updated: December 30, 2025 Evening" - inconsistent timestamps.

---

## Deep Analysis: Should We Do Everything?

### Decision Framework

| Criteria | Weight | Threshold |
|----------|--------|-----------|
| Security impact | HIGH | Do immediately if exposed |
| Data quality impact | HIGH | Do this week if predictions affected |
| Reliability impact | MEDIUM | Do if causes pipeline failures |
| Performance impact | LOW | Defer unless >2x slowdown |
| Technical debt | LOW | Defer unless blocks other work |

### Items NOT Worth Doing Now

| Item | Reason to Defer |
|------|-----------------|
| **Historical reprocessing** | Only affects two-way players (~1% of predictions) |
| **E2E latency tracking** | Nice-to-have observability, not blocking anything |
| **Prediction quality dashboard** | Analysis tool, not operational |
| **Registry integration tests** | System is working, test after more changes accumulate |
| **MERGE FLOAT64 fix** | No reports of actual failures from this |
| **Batch load historical games** | Performance optimization, system is functional |
| **Pub/Sub publish retries** | Not seeing publish failures in logs |
| **Feature caching** | Performance optimization, not urgent |
| **Health endpoints** | Nice-to-have, not blocking |

### Items Worth Doing

| Item | Reason to Do | Phase |
|------|--------------|-------|
| **Registry monitoring** | Prevents silent failures like Session 17 discovered | A |
| **Scheduler verification** | Confirms Session 17 fixes | A |
| **ESPN/BettingPros deploy** | Code complete, high impact on 6,000+ predictions | A |
| **Prediction duplicates fix** | Data integrity issue | B |
| **BigQuery timeouts** | Reliability - prevents indefinite hangs | B |
| **DLQ monitoring** | Critical - catches silent failures | C |
| **Phase 5→6 validation** | Prevents empty exports | C |

---

## Prioritized Implementation Plan

### Phase A: Quick Wins (Today, ~1 hour)

#### A1. Verify Scheduler Jobs (5 min)
**Purpose:** Confirm Session 17 registry fixes are working

```bash
# Check scheduler job status
gcloud scheduler jobs describe registry-ai-resolution --location=us-west2 \
  --format="yaml(lastAttemptTime,status)"

gcloud scheduler jobs describe registry-health-check --location=us-west2 \
  --format="yaml(lastAttemptTime,status)"

# Check registry pending count
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN resolved_at IS NOT NULL THEN 'resolved' ELSE 'pending' END as status,
  COUNT(DISTINCT player_lookup) as players
FROM \`nba_processing.registry_failures\`
GROUP BY 1"
```

**Exit criteria:** Both jobs show successful last attempt, 0 pending in registry

---

#### A2. Add Registry Monitoring to Daily Health Summary (30 min)
**Purpose:** Prevent silent registry failures

**File:** `orchestration/cloud_functions/daily_health_summary/main.py`

**Changes:**
1. Add `check_registry_failures()` method to HealthChecker
2. Query `nba_processing.registry_failures` for pending count
3. Add WARNING if pending > 5, CRITICAL if pending > 20
4. Include in Slack summary

**Query to add:**
```python
def check_registry_failures(self) -> Dict:
    """Check for pending registry failures."""
    query = f"""
    SELECT
        COUNT(DISTINCT player_lookup) as pending_players,
        COUNT(*) as pending_records
    FROM `{PROJECT_ID}.nba_processing.registry_failures`
    WHERE resolved_at IS NULL
    """
    results = self.run_query(query)
    return results[0] if results else {'pending_players': 0, 'pending_records': 0}
```

**Exit criteria:** Daily health summary includes registry failure count

---

#### A3. Deploy ESPN/BettingPros Normalization Fixes (15 min)
**Purpose:** Fix player_lookup mismatch affecting 6,000+ predictions

**Files already modified:**
- `data_processors/raw/espn/espn_team_roster_processor.py`
- `data_processors/raw/bettingpros/bettingpros_player_props_processor.py`

**Deployment:**
```bash
# Deploy raw processors
gcloud run deploy nba-phase2-raw-processors \
  --source . \
  --region us-west2 \
  --service-account nba-scraper-service@nba-props-platform.iam.gserviceaccount.com
```

**Exit criteria:** Suffix players (Jr., Sr., II, III) match in JOINs

---

### Phase B: Data Quality & Reliability (This Week, ~2 hours)

#### B1. Fix Prediction Duplicates (P1-DATA-1) (1 hour)
**Purpose:** Prevent duplicate predictions on Pub/Sub retry

**File:** `predictions/worker/worker.py` lines 996-1041

**Problem:** Uses `WRITE_APPEND` which creates duplicates

**Fix:** Change to MERGE statement with deduplication key:
- `(game_date, player_lookup, prop_type, system_id, line_value)`

**Exit criteria:** Duplicate predictions don't occur on retry

---

#### B2. BigQuery Query Timeouts (P1-PERF-1) (30 min)
**Purpose:** Prevent workers from hanging indefinitely

**File:** `predictions/worker/data_loaders.py`

**Fix:** Add `timeout=30` to all `.result()` calls:
```python
# Before
results = self.client.query(query).result()

# After
results = self.client.query(query).result(timeout=30)
```

**Files to update:**
- `predictions/worker/data_loaders.py` (4 locations)
- `predictions/coordinator/coordinator.py` (2 locations)

**Exit criteria:** All BigQuery queries have 30s timeout

---

#### B3. Circuit Breaker Hardcode Cleanup (P1-DATA-2) (30 min)
**Purpose:** Maintainability - use config instead of hardcoded values

**Files:**
| File | Lines | Status |
|------|-------|--------|
| `player_composite_factors_processor.py` | 1066 | TODO |
| `player_shot_zone_analysis_processor.py` | 810 | TODO |
| `player_daily_cache_processor.py` | 1172, 1237 | TODO |
| `team_defense_zone_analysis_processor.py` | 607 | TODO |
| `upcoming_team_game_context_processor.py` | 1036 | TODO |

**Exit criteria:** All circuit breaker thresholds read from config

---

### Phase C: Monitoring & Observability (This Week/Next, ~2 hours)

#### C1. Verify/Enhance DLQ Monitoring (P1-MON-1) (1 hour)
**Purpose:** Catch silent pipeline failures

**Existing:** `orchestration/cloud_functions/dlq_monitor/main.py`

**Tasks:**
1. Verify scheduler job exists and runs
2. Verify Slack alerts are configured
3. Add to daily health summary if not present

```bash
# Check DLQ monitor status
gcloud scheduler jobs describe dlq-monitor-job --location=us-west2 \
  --format="yaml(lastAttemptTime,status)"
```

**Exit criteria:** DLQ alerts are being sent when messages accumulate

---

#### C2. Phase 5→6 Data Validation (P1-ORCH-3) (1 hour)
**Purpose:** Don't export empty prediction files

**File:** `orchestration/cloud_functions/phase5_to_phase6/main.py`

**Add before triggering Phase 6:**
```python
MIN_PREDICTIONS_THRESHOLD = 50

row_count = bq_client.query(f"""
    SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}' AND is_active = TRUE
""").result().to_dataframe().iloc[0, 0]

if row_count < MIN_PREDICTIONS_THRESHOLD:
    logger.error(f"Insufficient predictions: {row_count}, not triggering Phase 6")
    # Send Slack alert
    return
```

**Exit criteria:** Phase 6 only triggers with sufficient predictions

---

## Deferred Items (With Justification)

### Deferred - Low Impact
| Item | Priority | Justification | Revisit When |
|------|----------|---------------|--------------|
| Historical reprocessing | P2 | Two-way players have limited minutes; ~1% impact | Never (unless requested) |
| Prediction quality dashboard | P2 | Analysis tool; grading already provides this info | Phase D or later |
| Feature caching | P2 | Performance opt; system is functional | Performance issues reported |
| Firestore cleanup | P2 | Documents aren't causing problems yet | Storage costs increase |

### Deferred - Need Investigation
| Item | Priority | Justification | Revisit When |
|------|----------|---------------|--------------|
| MERGE FLOAT64 fix | P1 | No production failures observed | If errors appear in logs |
| Batch load historical | P1 | Performance opt; current speed is acceptable | Worker timeout issues |
| Pub/Sub retries | P1 | Not seeing failures in logs | If publish failures occur |

### Deferred - Nice-to-Have
| Item | Priority | Justification | Revisit When |
|------|----------|---------------|--------------|
| E2E latency tracking | P2 | System is meeting SLAs without it | SLA violations occur |
| Registry integration tests | P2 | System working; tests can wait | Next registry changes |
| Health endpoints | P1 | Not blocking anything | Monitoring needs improve |

---

## Recommended Order

```
Day 1 (Today):
├── A1: Verify scheduler (5 min)
├── A2: Registry monitoring (30 min)
└── A3: Deploy normalization fixes (15 min)

Day 2-3:
├── B1: Prediction duplicates (1 hour)
├── B2: BigQuery timeouts (30 min)
└── B3: Circuit breaker cleanup (30 min)

Day 4-5:
├── C1: DLQ monitoring verify (1 hour)
└── C2: Phase 5→6 validation (1 hour)
```

**Total estimated effort:** ~5 hours

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Registry pending count | 0 (just cleared) | Stays at 0 (with alerts) |
| Prediction duplicates | Unknown | 0 (verified via query) |
| DLQ messages | Unknown | Alerts if >0 |
| Phase 6 empty exports | Unknown | 0 (with validation) |
| Query timeout hangs | Unknown | 0 (with timeouts) |

---

## Documentation Updates Needed

After implementation, update these files:

1. **MASTER-TODO.md** - Mark P0 items as complete, update timestamps
2. **Session 17 Handoff** - Add link to this plan
3. **Daily validation checklist** - Add registry monitoring step

---

## Phase A Implementation Details

### A1. Verify Scheduler Jobs

**Commands to run:**
```bash
# Check registry-ai-resolution job (runs at 4:30 AM ET)
gcloud scheduler jobs describe registry-ai-resolution --location=us-west2 \
  --format="yaml(name,state,lastAttemptTime,status)"

# Check registry-health-check job (runs at 5:00 AM ET)
gcloud scheduler jobs describe registry-health-check --location=us-west2 \
  --format="yaml(name,state,lastAttemptTime,status)"

# Check pending registry failures
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN resolved_at IS NOT NULL THEN 'resolved' ELSE 'pending' END as status,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as records
FROM \`nba_processing.registry_failures\`
GROUP BY 1"
```

**Success criteria:**
- Both jobs show `state: ENABLED`
- `lastAttemptTime` is today
- `status.code` is 0 (or status shows success)
- Pending count is 0 (per Session 17)

---

### A2. Registry Monitoring Implementation

**File:** `orchestration/cloud_functions/daily_health_summary/main.py`

**Add method to HealthChecker class (after check_7day_performance):**
```python
def check_registry_failures(self) -> Dict:
    """Check for pending registry failures."""
    query = f"""
    SELECT
        COUNT(DISTINCT player_lookup) as pending_players,
        COUNT(*) as pending_records
    FROM `{PROJECT_ID}.nba_processing.registry_failures`
    WHERE resolved_at IS NULL
    """
    results = self.run_query(query)
    return results[0] if results else {'pending_players': 0, 'pending_records': 0}
```

**Update run_health_check method to include registry check:**
```python
# After check 7 (7-day trend), add:

# 8. Registry Failures
registry = self.check_registry_failures()
results['checks']['registry_failures'] = registry

if registry['pending_players'] > 20:
    self.issues.append(f"Registry: {registry['pending_players']} pending player failures")
elif registry['pending_players'] > 5:
    self.warnings.append(f"Registry: {registry['pending_players']} pending player failures")
```

**Update Slack message (in metrics_text):**
```python
# Add to metrics_text:
f"\n\n*Registry Status*\n"
f"Pending Failures: {checks.get('registry_failures', {}).get('pending_players', 0)} players"
```

**Deployment:**
```bash
bin/deploy/deploy_daily_health_summary.sh
```

---

### A3. Deploy Normalization Fixes

**Verification (already confirmed):**
- `espn_team_roster_processor.py:166` uses `normalize_name(full_name)`
- `bettingpros_player_props_processor.py:306` uses `normalize_name(player_name)`

**Deployment:**
```bash
bin/raw/deploy/deploy_processors_simple.sh
```

**Post-deploy verification:**
```bash
# Check deployment succeeded
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.commit-sha)"

# Test health endpoint
SERVICE_URL=$(gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="value(status.url)")
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SERVICE_URL/health"
```

---

## Verification Checklist

After Phase A completion:

- [x] Registry scheduler jobs verified working (A1)
- [x] Registry pending count is 0 (A1)
- [x] Daily health summary includes registry monitoring (A2)
- [x] Raw processors deployed with normalization fixes (A3)
- [x] Health endpoint responds correctly (A3)

---

*Created: January 12, 2026*
*Last Updated: January 12, 2026 (Session 18)*
*Location: pipeline-reliability-improvements*
