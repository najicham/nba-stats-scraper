# Incident Analysis: Pipeline Failures on January 20, 2026
**Created**: January 20, 2026 (Night Investigation)
**Status**: 🔴 CRITICAL - Multiple Systems Down
**Impact**: Phase 3 Analytics, Phase 4 Precompute, Predictions, Grading

---

## EXECUTIVE SUMMARY

Multiple interconnected failures are affecting the NBA prediction pipeline:

| System | Status | Root Cause | Impact |
|--------|--------|------------|--------|
| **Phase 3 Analytics** | 🔴 CRASHED | HealthChecker signature mismatch | Cannot process analytics |
| **Phase 4 Precompute** | 🔴 CRASHED | Same HealthChecker issue | Cannot generate features |
| **Boxscores (Jan 20)** | 🟡 PARTIAL | Only 4/7 games processed | Missing game data |
| **Predictions (Jan 20)** | 🟡 PARTIAL | Circuit breaker tripped | Only 26 players have predictions |
| **Grading** | 🟡 BLOCKED | No predictions to grade | 0 predictions graded |
| **Alerting** | 🔴 FAILED | No proactive monitoring | 5+ hour detection gap |

**Timeline of Failure:**
- **~22:00 Jan 20**: Week 1 merge deployed with HealthChecker bug
- **~22:01 Jan 20**: Phase 3 & Phase 4 services begin crashing on every request
- **~06:30 Jan 21**: Still crashing (gunicorn worker failures every few seconds)
- **Detection**: Only through manual investigation tonight

---

## ISSUE 1: Phase 3 & Phase 4 Service Crashes 🔴 CRITICAL

### Root Cause
The Week 1 merge (commit `0c82ae50`) introduced a **HealthChecker signature mismatch**:

**New HealthChecker class** (`shared/endpoints/health.py`):
```python
def __init__(self, service_name: str, version: str = '1.0'):
    # Only accepts 2 parameters
```

**But services are calling with OLD parameters**:
```python
health_checker = HealthChecker(
    project_id=os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),  # ❌ INVALID
    service_name='analytics-processor',
    check_bigquery=True,         # ❌ INVALID
    check_firestore=False,       # ❌ INVALID
    check_gcs=False,             # ❌ INVALID
    required_env_vars=['GCP_PROJECT_ID'],  # ❌ INVALID
    optional_env_vars=['ENVIRONMENT']       # ❌ INVALID
)
```

**Error:**
```
TypeError: HealthChecker.__init__() got an unexpected keyword argument 'project_id'
```

### Affected Files
1. `data_processors/analytics/main_analytics_service.py` (lines 65-73)
2. `data_processors/precompute/main_precompute_service.py` (lines 30-38)

### Fix Required
```python
# BEFORE (broken):
health_checker = HealthChecker(
    project_id=os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
    service_name='analytics-processor',
    check_bigquery=True,
    check_firestore=False,
    check_gcs=False,
    required_env_vars=['GCP_PROJECT_ID'],
    optional_env_vars=['ENVIRONMENT']
)

# AFTER (fixed):
health_checker = HealthChecker(service_name='analytics-processor')
```

---

## ISSUE 2: Incomplete Boxscores for Jan 20 🟡 PARTIAL

### Evidence
- BigQuery shows: **4 games** with 140 boxscore rows
- NBA.com shows: **7 games** completed (all Final)
- Missing: PHX@PHI, MIN@UTA, MIA@SAC (3 games)

### Root Cause Chain
1. Phase 3 service crashes → cannot publish "phase3_complete" message
2. Orchestration waits for Phase 3 → never triggers Phase 4
3. Pipeline stalls waiting for: `{'BdlPlayerBoxScoresProcessor', 'NbacGamebookProcessor'}`

### Why Only 4 Games?
- Some boxscore processing may have succeeded before the Phase 3 crash
- Or scrapers ran partially before the deployment

---

## ISSUE 3: Low Prediction Count (26 Players) 🟡 PARTIAL

### Evidence
- Jan 20 has only **885 predictions for 26 players**
- Expected: ~200+ players, 4000+ predictions
- Grading shows: "No predictions found for 2026-01-21"

### Root Cause
The Phase 4→5 orchestrator has a **circuit breaker** (R-006 requirement):
- Requires **≥3 of 5 Phase 4 processors** to complete
- Requires **BOTH critical processors**: `player_daily_cache` AND `ml_feature_store_v2`
- If thresholds not met → **BLOCKS ALL Phase 5 predictions**

Since Phase 4 (precompute) is crashing, the circuit breaker tripped:
```
Phase 3 crash → Phase 4 never triggered → Circuit breaker blocks Phase 5 → No predictions
```

The 26 players likely came from a cached/fallback mechanism or partial run before the crash.

---

## ISSUE 4: No Proactive Alerting 🔴 CRITICAL GAP

### What Should Have Alerted (But Didn't)
| Alert Type | Why It Failed |
|------------|---------------|
| Service Health | No CPU/memory/error rate monitoring for Phase 3/4 |
| Data Freshness | Self-heal only runs once at 12:45 PM ET |
| DLQ Monitoring | Passive-only, doesn't alert on failures |
| Orchestration Timeout | No timeout for "waiting for Phase 3" state |

### Detection Timeline Gap
```
22:00 - Service deployed with bug
22:01 - Phase 3 starts crashing
...
06:30 - Still crashing (12.5 hours later)
~23:00 - Manual investigation discovers issue
```

**Result: 25+ hour detection gap**

### What Alerting Exists
- ✅ Prediction quality alerts (caught CatBoost V8 issue on Jan 17)
- ✅ DLQ monitoring (passive, no auto-recovery)
- ✅ Self-heal function (runs once daily at 12:45 PM)
- ❌ No Phase 3/4 service crash detection
- ❌ No data freshness monitoring for analytics tables
- ❌ No orchestration state timeout alerts

---

## COMPLETE FAILURE CASCADE

```
Week 1 Merge (22:00)
       ↓
HealthChecker signature changed
       ↓
Phase 3 Analytics Service CRASHES on startup
       ↓
Cannot process: PlayerGameSummary, TeamOffense/DefenseGameSummary
       ↓
Phase 3 completion never published to Pub/Sub
       ↓
Phase 4 Precompute Service ALSO CRASHES (same bug)
       ↓
Phase 4→5 Orchestrator waits forever for Phase 4 completion
       ↓
Circuit breaker eventually trips (insufficient Phase 4 data)
       ↓
Phase 5 Predictions BLOCKED
       ↓
Only 26 players get predictions (from cache/fallback)
       ↓
Grading has nothing to grade
       ↓
No alerts sent (no monitoring for this failure mode)
```

---

## ACTION PLAN

### IMMEDIATE (Tonight - 30 min)

#### Step 1: Fix HealthChecker in Analytics Service
```bash
# File: data_processors/analytics/main_analytics_service.py
# Lines 65-73: Replace with:
health_checker = HealthChecker(service_name='analytics-processor')
```

#### Step 2: Fix HealthChecker in Precompute Service
```bash
# File: data_processors/precompute/main_precompute_service.py
# Lines 30-38: Replace with:
health_checker = HealthChecker(service_name='precompute-processor')
```

#### Step 3: Commit and Deploy
```bash
git add data_processors/analytics/main_analytics_service.py
git add data_processors/precompute/main_precompute_service.py
git commit -m "fix: Correct HealthChecker initialization in analytics and precompute services

Root cause: Week 1 merge changed HealthChecker signature but services
were not updated. Services were calling with project_id, check_bigquery,
etc. parameters that no longer exist.

Impact: Phase 3 and Phase 4 services crashing on every request since
deployment (~22:00 Jan 20).

Co-Authored-By: Claude <noreply@anthropic.com>"

# Deploy analytics
gcloud run deploy nba-phase3-analytics-processors \
  --source data_processors/analytics \
  --region us-west2

# Deploy precompute
gcloud run deploy nba-phase4-precompute-processors \
  --source data_processors/precompute \
  --region us-west2
```

### SHORT-TERM (Tomorrow - 2-3 hours)

#### Step 4: Backfill Missing Jan 20 Data
```bash
# After services are healthy, trigger backfill for Jan 20
./bin/run_backfill.sh raw/bdl_boxscores --dates=2026-01-20
./bin/run_backfill.sh analytics/player_game_summary --dates=2026-01-20

# Or use manual orchestration trigger
python3 bin/monitoring/check_orchestration_state.py 2026-01-20
```

#### Step 5: Regenerate Jan 20 Predictions
```bash
# Manually trigger Phase 5 coordinator
curl -X POST https://prediction-coordinator-xxx.run.app/start \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-20"}'
```

### MEDIUM-TERM (This Week - 4-6 hours)

#### Step 6: Add Proactive Monitoring
1. **Phase 3/4 Health Monitor** (every 15 min)
   - Check service CPU/memory/error rate
   - Alert if error rate > 5%
   - Alert if service unhealthy for 5+ minutes

2. **Data Freshness Monitor** (every 30 min)
   - Check `player_game_summary` row count for today
   - Alert if 0 rows 2+ hours after games should complete

3. **Orchestration State Monitor** (every 30 min)
   - Check for "waiting" states older than 2 hours
   - Alert if Phase 3 hasn't completed by expected time

4. **DLQ Auto-Recovery**
   - When DLQ messages found, trigger self-heal automatically
   - Don't just log, take action

---

## ROOT CAUSE ANALYSIS: Why This Happened

### Technical Cause
1. Week 1 refactoring simplified HealthChecker class (removed parameters)
2. Predictions coordinator was fixed (commit 88f2547a)
3. But analytics and precompute services were NOT updated
4. Merge conflict resolution may have reverted the fix

### Process Gap
1. No automated tests for HealthChecker signature compatibility
2. No integration test that actually starts the services
3. No canary deployment to catch startup crashes
4. No monitoring that would detect "service crashing on startup"

### Recommended Process Fixes
1. Add integration test that imports and instantiates services
2. Add startup health check that runs during deployment
3. Add error rate alerting for all Cloud Run services
4. Add canary deployment with automatic rollback

---

## MONITORING GAPS TO ADDRESS

| Gap | Current State | Recommended |
|-----|---------------|-------------|
| Service crashes | No monitoring | Error rate alerting (>5% = alert) |
| Data freshness | Self-heal at 12:45 PM only | Every 30 min check |
| Orchestration state | No monitoring | Timeout alerts for stuck states |
| DLQ messages | Log only | Auto-trigger recovery |
| Deployment health | No validation | Canary with auto-rollback |

---

## LESSONS LEARNED

1. **Signature changes are dangerous**: When changing class signatures, grep for ALL usages
2. **Integration tests matter**: A simple "can the service start" test would have caught this
3. **Monitoring blind spots**: Having prediction alerts but no service alerts created a gap
4. **Cascading failures**: Phase 3 crash cascaded to Phase 4, 5, and grading
5. **Detection delay**: 25+ hours to detect a service crash is unacceptable

---

## APPENDIX: Key Files

| File | Issue | Fix |
|------|-------|-----|
| `data_processors/analytics/main_analytics_service.py:65-73` | HealthChecker signature | Remove extra params |
| `data_processors/precompute/main_precompute_service.py:30-38` | HealthChecker signature | Remove extra params |
| `shared/endpoints/health.py:50-73` | New HealthChecker class | Reference (no change needed) |
| `orchestration/cloud_functions/phase4_to_phase5/main.py:871-890` | Circuit breaker | Reference (working as designed) |

---

**Document Created**: 2026-01-20 23:30 UTC
**Author**: Investigation Session
**Status**: Ready for execution
