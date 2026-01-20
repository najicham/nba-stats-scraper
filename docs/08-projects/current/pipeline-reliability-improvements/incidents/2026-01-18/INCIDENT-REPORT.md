# Incident Report: 2026-01-18 Daily Orchestration Issues

**Date:** January 18, 2026
**Severity:** P1 - High Priority
**Status:** Investigating
**Detected:** Manual daily validation check
**Impact:** Partial orchestration failure, grading issues, missing analytics

---

## Executive Summary

Daily orchestration validation for 2026-01-18 revealed multiple critical issues:
1. **Firestore import error** causing prediction worker crashes
2. **Low grading accuracy** (18.75% - 9/48 correct)
3. **Incomplete Phase 3** processing (2/5 processors completed)
4. **Phase 4 not triggered** due to strict completion criteria
5. **Live scoring operational** but grading impacted by worker errors

**Overall System Status:** Partially functional - predictions generated successfully (1,680 predictions), but grading and analytics pipelines degraded.

---

## Timeline of Events

| Time (UTC) | Event | Status |
|------------|-------|--------|
| 2026-01-17 23:01-23:02 | Predictions created (1,680 total, 57 players, 6 systems) | ✅ SUCCESS |
| 2026-01-18 02:03-02:06 | Live grading export attempted | ⚠️ PARTIAL |
| 2026-01-18 02:04-02:05 | Multiple Firestore ImportError in prediction-worker | ❌ FAILED |
| 2026-01-18 02:06 | Live grading found 57 predictions, graded 48 | ⚠️ DEGRADED |
| 2026-01-18 20:05 | Phase 3: team_offense_game_summary completed | ✅ SUCCESS |
| 2026-01-18 23:05 | Final boxscores scraped (35 players) | ✅ SUCCESS |
| 2026-01-19 02:03 | Live scoring last poll (4 games, 141 players) | ✅ SUCCESS |

---

## Issue #1: Firestore Import Error (CRITICAL)

### Symptoms
```
ImportError: cannot import name 'firestore' from 'google.cloud' (unknown location)
File: /app/predictions/worker/worker.py, line 556
Frequency: 20+ errors in 1 minute (02:04-02:05 UTC)
```

### Root Cause
**Missing dependency:** `google-cloud-firestore` not in `predictions/worker/requirements.txt`

### Chain of Failure
1. Worker receives prediction request via Pub/Sub
2. Generates predictions successfully
3. Calls `write_predictions_to_bigquery()` at line 556
4. Function lazy-loads `BatchStagingWriter` at line 1443
5. `BatchStagingWriter` imports `DistributedLock` at line 48
6. `DistributedLock` tries to import Firestore at line 46
7. **Import fails → 500 error → Pub/Sub retry storm**

### Why This Happened
- Distributed lock feature added in Session 92 to prevent duplicate predictions
- Firestore dependency added to coordinator's requirements.txt
- **Never added to worker's requirements.txt** (separate deployment)
- Worker crashes when attempting to use distributed locking

### Impact
- Worker crashes during grading operations
- Predictions not written to BigQuery properly
- Pub/Sub retry storm (20+ errors in 1 minute)
- Grading accuracy metrics potentially unreliable

### Fix Required
**File:** `predictions/worker/requirements.txt`

**Add:**
```
google-cloud-firestore==2.14.0
```

**Deployment:**
```bash
cd /home/naji/code/nba-stats-scraper/predictions/worker
gcloud run deploy prediction-worker \
  --source=. \
  --region=us-west2 \
  --project=nba-props-platform
```

**Verification:**
```bash
# Check worker logs for successful Firestore import
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker"' \
  --limit=10 --format="table(timestamp,severity,textPayload)"
```

---

## Issue #2: Low Grading Accuracy (INVESTIGATE)

### Symptoms
- **9/48 correct predictions** (18.75% accuracy)
- Exported to: `gs://nba-props-platform-api/v1/live-grading/2026-01-18.json`

### Context
Historical system performance (Jan 4-17):
- Overall grading coverage: 99.4% average
- System-wide accuracy: 39-50% (varies by system)
- CatBoost V8: ~48-50% (best system, 4.81 MAE)
- Ensemble V1: ~39% (5.41 MAE)

### Possible Explanations

**Hypothesis 1: Small Sample Size**
- Only 48 predictions graded (vs typical 280 per system)
- Could represent single system or specific prop types
- Need to see full breakdown by system

**Hypothesis 2: Morning Game Issues**
- Morning games (earlier than typical 7 PM starts)
- Betting lines may not have been final when predictions made
- Injury status changes after predictions
- Player rotations not confirmed

**Hypothesis 3: Data Staleness**
- Phase 3 timing issues (see Issue #3)
- Predictions made with outdated analytics
- Missing context data

**Hypothesis 4: Firestore Error Impact**
- Worker crashes may have corrupted grading writes
- Partial results recorded
- Need to cross-reference with BigQuery tables

### Investigation Required

**Query to run:**
```sql
-- Full accuracy breakdown by system
SELECT
  game_date,
  system_id,
  COUNT(*) as total,
  SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) as correct,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 2) as accuracy_pct,
  ROUND(AVG(absolute_error), 2) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = '2026-01-18'
  AND recommendation IN ('OVER', 'UNDER')
  AND graded_at IS NOT NULL
GROUP BY game_date, system_id
ORDER BY system_id;

-- Check prediction timing
SELECT
  MIN(created_at) as first_prediction,
  MAX(created_at) as last_prediction,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-01-18'
  AND is_active = TRUE;

-- Check grading timing
SELECT
  MIN(graded_at) as first_graded,
  MAX(graded_at) as last_graded,
  COUNT(*) as total_graded
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = '2026-01-18';
```

### Action Items
1. Run investigation queries to understand 18.75% metric
2. Compare to historical morning game accuracy
3. Check if this is system-specific or across all systems
4. Verify grading writes completed properly (not corrupted by Firestore error)
5. If system regression: investigate model drift or data quality issues

---

## Issue #3: Incomplete Phase 3 Processing (HIGH PRIORITY)

### Symptoms
**Expected Processors:** 5
**Completed:** 2/5 (40%)

| Processor | Status | Notes |
|-----------|--------|-------|
| team_offense_game_summary | ✅ Completed | 2026-01-18 20:05:38 UTC |
| upcoming_player_game_context | ✅ Completed | 2026-01-17 22:01:40 UTC |
| player_game_summary | ❌ MISSING | Required for analytics |
| team_defense_game_summary | ❌ MISSING | Required for analytics |
| upcoming_team_game_context | ❌ MISSING | Required for predictions |

### Root Cause Analysis

**Context from Investigation:**
- Jan 18 (Sunday) and Jan 19 (Monday/MLK Day) had **NO NBA GAMES scheduled**
- Coordinator correctly did not run when no games scheduled
- **BUT** Phase 3 should have processed data for games that occurred on Jan 18

**Historical Pattern Identified:**
From `phase3_root_cause_analysis_20260118_1528.txt`:
- **Jan 17 Phase 3 run:** Created only 1 record instead of 156
- **Jan 18 Phase 3 run:** Created 156 records (21 hours late)
- **Root cause:** Betting lines for Sunday games not available until Saturday afternoon

**Timing Issue:**
- Phase 3 runs at 5:00 PM ET (17:00 local, 22:00 UTC)
- Predictions run at 6:00 PM ET (18:00 local, 23:00 UTC)
- **Gap: Only 1 hour**
- Betting lines often not published yet, especially for weekend games

### Why Only 2/5 Processors Completed

**Data Dependency:**
- Processors can't run if upstream data (betting lines, game schedule) is missing
- Weekend games have later line publication
- Smart skipping: Processors gracefully skip when data unavailable

**Impact:**
- 14 players (20%) missing predictions on Jan 17
- Phase 4 not triggered due to incomplete Phase 3
- Cascading failure through entire pipeline

### Fix Options

**Option 1: Retry Logic**
```python
# If Phase 3 creates <50 records, wait 30 min and retry
if records_created < expected_records * 0.5:
    schedule_retry(delay_minutes=30)
    alert_data_availability_issue()
```

**Option 2: Data Freshness Validator** (Already Deployed)
- Runs at 5:45 PM (15 minutes after Phase 3)
- Checks if Phase 3 data is <24 hours old
- Blocks predictions if data stale
- **Should have prevented Jan 17 issue** - needs investigation

**Option 3: Pub/Sub Event-Driven**
- Phase 3 waits for upstream data confirmation
- Use completion signals instead of fixed schedules
- Eliminates timing-based failures

### Action Items
1. Investigate why Data Freshness Validator didn't block Jan 17 predictions
2. Add monitoring for Phase 3 record creation counts
3. Implement retry logic for low-record scenarios
4. Consider moving Phase 3 scheduler to later time (6 PM or 7 PM)
5. Add alerts when Phase 3 creates <50% expected records

---

## Issue #4: Phase 4 Not Triggered (ARCHITECTURAL)

### Symptoms
Phase 4 did not trigger despite Phase 3 processors completing

### Current Logic
```python
# Phase 3 -> Phase 4 orchestration
trigger_mode: 'all_complete'  # Requires ALL 5 Phase 3 processors
```

**Expected Phase 4 Processors:**
1. team_defense_zone_analysis
2. player_shot_zone_analysis
3. player_composite_factors
4. player_daily_cache
5. ml_feature_store

### Problem
**Too Strict:** "all_complete" requirement means if even one Phase 3 processor fails/skips, entire Phase 4 is blocked

**Cascading Impact:**
- No Phase 4 → No Phase 5 (predictions)
- Single processor failure blocks entire pipeline
- No graceful degradation

### Recommended Fix: Critical-Processor-Only Requirement

**Critical Processors** (MUST complete for predictions):
```python
critical_processors = [
    'upcoming_player_game_context',  # Essential for predictions
    'upcoming_team_game_context'     # Essential for predictions
]
```

**Non-Critical Processors** (Analytics, can be regenerated later):
```python
optional_processors = [
    'player_game_summary',        # Historical analytics
    'team_defense_game_summary',  # Historical analytics
    'team_offense_game_summary'   # Historical analytics
]
```

**New Logic:**
```python
# Phase 4 triggers if critical processors complete
# Optional processors can fail without blocking pipeline
trigger_mode: 'critical_only'
critical_set = ['upcoming_player_game_context', 'upcoming_team_game_context']
```

### Alternative Approaches

**Option 1: Majority Trigger** (60% completion)
```python
trigger_mode: 'majority'  # Trigger Phase 4 if >60% Phase 3 complete
```

**Option 2: Graceful Degradation**
```python
# Phase 4 runs with whatever Phase 3 data exists
# Quality flags indicate which Phase 3 inputs were available
# Predictions generated with degraded confidence scores
```

**Option 3: Separate Pipelines**
```python
# Critical path: upcoming_context → features → predictions
# Analytics path: game_summary → historical_metrics (parallel, non-blocking)
```

### Recommendation
**Use Option 1 (Critical-Only Requirement)** with Option 2 (Graceful Degradation)

**Rationale:**
- Better to have predictions with slightly lower quality than no predictions
- Analytics processors can be run as backfill later
- Reduces single point of failure risk
- Maintains system availability during partial failures

### Implementation
**File:** `shared/config/orchestration_config.py`

**Change:**
```python
# Before
phase3_to_phase4_trigger = {
    'mode': 'all_complete',
    'processors': all_phase3_processors
}

# After
phase3_to_phase4_trigger = {
    'mode': 'critical_only',
    'critical_processors': [
        'upcoming_player_game_context',
        'upcoming_team_game_context'
    ],
    'optional_processors': [
        'player_game_summary',
        'team_defense_game_summary',
        'team_offense_game_summary'
    ]
}
```

---

## What Worked Well

### ✅ Successes

1. **Predictions Generated:** 1,680 predictions for 57 players across 6 systems
2. **Live Scoring:** 4 games tracked with 141 players, BDL API working
3. **Data Scraping:** 35 players scraped for final boxscores
4. **Live Grading Export:** Ran and exported results (despite worker errors)
5. **Overall System Health (Last 7 Days):**
   - 99.4% grading coverage average
   - Zero errors in logs (before this incident)
   - All 6 prediction systems operational

---

## Broader System Issues

### 1. Missing Dependency Management
- **Pattern:** Dependencies added to one service but not related services
- **Example:** Firestore added to coordinator but not worker
- **Fix Needed:** Centralized dependency management or dependency audits

### 2. Overly Strict Orchestration
- **Pattern:** All-or-nothing completion requirements
- **Impact:** Single component failure blocks entire pipeline
- **Fix Needed:** Graceful degradation and critical-path prioritization

### 3. Fixed Timing Without Validation
- **Pattern:** Schedulers run at fixed times without checking prerequisites
- **Example:** Phase 3 at 5 PM assumes betting lines available
- **Fix Needed:** Event-driven triggers or data availability checks

### 4. Limited Alerting
- **Current:** Zero alerts configured for orchestration failures
- **Impact:** Issues detected manually during daily checks
- **Fix Needed:** Automated alerts for:
  - Phase completion <80%
  - Data staleness >2 hours
  - Grading accuracy <30%
  - Prediction volume <200

### 5. Monitoring Gaps
- **Missing:** Dashboard for Phase 3/4 completion tracking
- **Missing:** Processor-level success rate metrics
- **Missing:** End-to-end pipeline latency tracking
- **Impact:** Limited visibility into partial failures

---

## Immediate Action Plan

### Priority 0: Fix Firestore Import (5 minutes)
```bash
cd /home/naji/code/nba-stats-scraper/predictions/worker
echo "google-cloud-firestore==2.14.0" >> requirements.txt
git add requirements.txt
git commit -m "fix(predictions): Add missing google-cloud-firestore dependency"
git push
./bin/predictions/deploy/deploy_worker.sh
```

**Verification:**
- Check worker logs for successful startup
- Verify distributed lock initialization
- Monitor next grading cycle for errors

### Priority 1: Investigate Grading Accuracy (15 minutes)
- Run investigation queries (see Issue #2)
- Determine if 18.75% is system regression or expected variance
- Check for data quality issues

### Priority 2: Review Phase 3 Completion Logic (1 hour)
- Implement critical-only trigger for Phase 4
- Add retry logic for Phase 3 low-record scenarios
- Set up alerts for Phase 3 timing issues

### Priority 3: Add Monitoring & Alerts (2 hours)
- Phase 3/4/5 completion dashboard
- Processor-level success rate tracking
- Data staleness alerts
- Grading accuracy regression alerts

---

## Long-Term Improvements

### Week 1: Robustness Hardening
1. **Dependency Audit** (4 hours)
   - Scan all services for missing dependencies
   - Centralize common dependencies
   - Add dependency validation to CI/CD

2. **Orchestration Redesign** (8 hours)
   - Implement critical-path prioritization
   - Add graceful degradation
   - Separate blocking vs non-blocking processors

3. **Retry Logic Implementation** (4 hours)
   - Phase 3 retry on low records
   - Exponential backoff for transient failures
   - Max retry limits with alerts

### Week 2: Monitoring & Alerting
1. **Comprehensive Dashboard** (6 hours)
   - Phase completion rates
   - Processor-level metrics
   - End-to-end latency tracking
   - Data freshness indicators

2. **Alert Configuration** (4 hours)
   - Phase completion <80%
   - Data staleness >2 hours
   - Grading accuracy <30%
   - Prediction volume <200
   - Worker errors >5 in 5 minutes

3. **Email/Slack Integration** (2 hours)
   - Alert manager setup
   - Incident severity classification
   - Escalation policies

### Week 3: Event-Driven Architecture
1. **Pub/Sub Orchestration** (12 hours)
   - Data availability signals
   - Completion-based triggers
   - Eliminate fixed-time dependencies

2. **State Management** (6 hours)
   - Firestore orchestration state
   - Atomic transaction protection
   - Race condition prevention

### Week 4: Self-Healing Capabilities
1. **Auto-Retry Mechanisms** (8 hours)
   - Intelligent retry logic
   - Circuit breaker patterns
   - Auto-recovery from transient failures

2. **Fallback Data Sources** (8 hours)
   - Multi-source scraper fallback
   - Primary → secondary → tertiary
   - Circuit breaker with auto-recovery

---

## Lessons Learned

1. **Dependency Management:** Need centralized approach to prevent missing dependencies across services
2. **Orchestration Design:** All-or-nothing completion is too fragile for production
3. **Timing Assumptions:** Fixed schedules fail when external data has variable availability
4. **Monitoring:** Manual daily checks catch issues, but automated alerts needed for faster detection
5. **Testing:** Deployment testing should include dependency validation and integration checks

---

## Related Documents

- [Recurring Issues](../RECURRING-ISSUES.md) - Historical pattern analysis
- [Future Improvements](../FUTURE-IMPROVEMENTS.md) - Planned optimizations
- [Next Steps](../NEXT-STEPS.md) - Implementation roadmap
- [Phase 3 Root Cause Analysis](./phase3_root_cause_analysis_20260118_1528.txt) - Deep dive on timing issues

---

**Report Created:** 2026-01-18
**Last Updated:** 2026-01-18
**Status:** Under Investigation
**Next Review:** After Priority 0-2 fixes deployed
