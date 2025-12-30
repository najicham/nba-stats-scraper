# Pipeline Reliability Improvements - December 30, 2025

**Session Started:** 1:30 PM PT
**Status:** IN PROGRESS
**Continuation of:** 2025-12-30-HANDOFF-NEXT-SESSION.md

---

## Session Goals

Address P0-P1 pipeline reliability gaps identified in the handoff document.

---

## Completed This Session

### P0 Critical Issues (All Fixed)

| Issue | Problem | Solution | Status |
|-------|---------|----------|--------|
| P0-3 | Phase 6 exports run before self-heal | Added pre-export validation to Phase 6. If predictions missing, auto-triggers self-heal | Committed |
| P0-2 | Firestore single point of failure | Added `monitoring/firestore_health_check.py` - monitors connectivity, stuck processors, phase freshness | Committed |
| P0-1* | Self-heal runs 75 min AFTER Phase 6 | Moved self-heal scheduler from 2:15 PM to 12:45 PM ET (15 min before Phase 6) | Committed |

*Note: Original P0-1 (grading timing) was not actually an issue - grading is at 11 AM ET, not 7 AM.

**Commit:** `a2f0af6` - "fix: Address P0 critical pipeline reliability gaps"

### Files Changed

```
orchestration/cloud_functions/phase6_export/main.py    (+164 lines)
  - validate_predictions_exist() - checks predictions before export
  - trigger_self_heal() - auto-triggers recovery if validation fails
  - Integration into main() for tonight export types

monitoring/firestore_health_check.py                   (+496 lines, new)
  - check_connectivity() - read/write latency test
  - check_stuck_processors() - finds processors running > 30 min
  - check_phase_completion_freshness() - validates orchestration state
  - Optional alerting to Pub/Sub

bin/deploy/deploy_self_heal_function.sh               (schedule change)
  - SCHEDULER_SCHEDULE: "15 14 * * *" → "45 12 * * *"

orchestration/cloud_functions/self_heal/main.py       (docstring update)
```

---

## Completed: P1 Issues

### P1-6: Processor Slowdown Detection - DONE

**Created:** `monitoring/processor_slowdown_detector.py`

**Features:**
- Calculates 7-day baseline stats for each processor (avg, stddev, p95, max)
- Detects runs >2x baseline (configurable threshold)
- Identifies timeout risks (processors using >75% of timeout)
- Tracks duration trends (3-day vs 7-day average)

**Current Findings:**
```
CRITICAL: PredictionCoordinator at 8.2x baseline (608s vs 74s avg)
WARNING: PredictionCoordinator at 112.6% of timeout
WARNING: PredictionCoordinator +66.8% trend (3d vs 7d)
WARNING: PlayerDailyCacheProcessor +39.7% trend
```

**Usage:**
```bash
python monitoring/processor_slowdown_detector.py        # Human report
python monitoring/processor_slowdown_detector.py --json # JSON output
python monitoring/processor_slowdown_detector.py --processor MLFeatureStoreProcessor
```

### P1-7: Dashboard Action Endpoints - DONE

**Updated:** `services/admin_dashboard/main.py`

**Implemented Endpoints:**

| Endpoint | Method | Payload | Action |
|----------|--------|---------|--------|
| `/api/actions/force-predictions` | POST | `{date: "YYYY-MM-DD"}` | Calls prediction coordinator |
| `/api/actions/retry-phase` | POST | `{date: "...", phase: "3/4/5"}` | Calls appropriate processor service |
| `/api/actions/trigger-self-heal` | POST | `{}` | Triggers self-heal check |

**Features:**
- Authenticated calls to Cloud Run services using GCP identity tokens
- Audit logging for all actions
- Error handling and status reporting
- Support for phases: 3, 4, 5/predictions, self_heal

### P1-4: End-to-End Latency Tracking

**Problem:** Can't measure game_ends → predictions_graded latency.

**Proposed Solution:**
- New table: `nba_monitoring.pipeline_execution_log`
- Track: game_id, game_end_time, phase1_complete, phase2_complete, ..., grading_complete
- Dashboard showing latency distribution

### P1-5: DLQ Monitoring

**Problem:** Pub/Sub DLQ messages can expire without alerting.

**Existing DLQs:** (from `bin/infrastructure/create_phase2_phase3_topics.sh`)
- phase2-raw-complete-dlq
- phase3-analytics-complete-dlq

**Needs:**
- Cloud Monitoring alert on DLQ message count > 0
- Dashboard visibility

---

## Investigation: PredictionCoordinator Slowdown

**Symptom:** PredictionCoordinator running at 8.2x baseline (608s vs 74s avg), exceeding 540s timeout.

**Root Cause Analysis:**

The 608s run on 2025-12-30 04:59:18 UTC was caused by **prediction worker boot failures**, not slow prediction processing:

```
ImportError: cannot import name 'monitoring_v3' from 'google.cloud' (unknown location)
```

**Timeline:**
1. 04:59:18 - Coordinator publishes 28 prediction requests
2. 05:01:54 - Worker instances try to boot but FAIL (ImportError)
3. Cloud Run retries repeatedly (autoscaling)
4. Eventually workers boot correctly
5. 05:09:27 - Last player completes (~10 min later)

**Problem:** `shared/utils/metrics_utils.py` imports `monitoring_v3` at module load time. If `google-cloud-monitoring` package is missing or has issues, the worker crashes before it can process any requests.

**Fix Applied:** Made imports lazy in `shared/utils/metrics_utils.py`:
- Moved `from google.cloud import monitoring_v3` to lazy loading
- Added `_get_monitoring_module()` helper
- Worker now boots even if metrics module isn't available
- Metrics are gracefully skipped if unavailable

**File Changed:** `shared/utils/metrics_utils.py`

---

## Deployment Required

When GCP connectivity is stable:

```bash
# Deploy Phase 6 with pre-export validation
./bin/deploy/deploy_phase6_function.sh

# Deploy self-heal with new schedule
./bin/deploy/deploy_self_heal_function.sh
```

---

## Updated Pipeline Timeline

```
6:30 AM ET  │ daily-yesterday-analytics (Phase 3)
11:00 AM ET │ grading-daily (unchanged, 4.5h buffer)
12:45 PM ET │ self-heal-predictions ← MOVED FROM 2:15 PM
1:00 PM ET  │ phase6-tonight-picks (now has pre-validation)
```

---

## Next Steps

1. Complete P1-6: Processor slowdown detection
2. Complete P1-7: Dashboard action endpoints
3. Run deployments when GCP is stable
4. Continue to P2 issues if time permits
