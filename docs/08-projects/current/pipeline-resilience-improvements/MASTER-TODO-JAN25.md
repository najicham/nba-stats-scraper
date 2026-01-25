# Master TODO List - Pipeline Resilience Improvements
## January 25, 2026

**Session Goal:** Make the system run without errors every day through better validation, error visibility, and self-healing.

---

## ✅ COMPLETED THIS SESSION

### 1. Streaming Buffer Fixes (Root Cause Elimination)
Converted critical logging utilities from `insert_rows_json()` (streaming) to `insert_bigquery_rows()` (batch loading):

| File | Status |
|------|--------|
| `shared/utils/phase_execution_logger.py` | ✅ Fixed |
| `shared/utils/pipeline_logger.py` | ✅ Fixed |
| `shared/utils/completion_tracker.py` | ✅ Fixed |
| `shared/utils/proxy_health_logger.py` | ✅ Fixed |
| `shared/utils/daily_scorecard.py` | ✅ Fixed (2 locations) |
| `data_processors/raw/processor_base.py` | ✅ Fixed |

### 2. Automated Monitoring
- Added `check_workflow_decision_gaps()` to `daily_health_summary` cloud function
- Alerts if orchestration gap > 2 hours (would catch 45-hour outage)
- Added orchestration health to Slack summary

### 3. BDL Availability Logging & Missing Game Alerts (Session 2)
| Feature | Status |
|---------|--------|
| BDL availability logging in scraper | ✅ Added to `bdl_player_box_scores.py` |
| Missing game Slack alerts | ✅ Added to `bdl_availability_logger.py` |
| Auto-retry queue for missing games | ✅ Queues to `failed_processor_queue` |

### 4. Analytics Player Count Validation (Session 2)
| Feature | Status |
|---------|--------|
| Boxscore vs Analytics player comparison | ✅ Added to `player_game_summary_processor.py` |
| Slack alerts for <80% coverage | ✅ Implemented |

### 5. Phase Execution Logging Enhancement (Session 2)
Added `log_phase_execution()` calls to all phase orchestrators:
| File | Status |
|------|--------|
| `phase2_to_phase3/main.py` | ✅ Already had logging |
| `phase3_to_phase4/main.py` | ✅ Added |
| `phase4_to_phase5/main.py` | ✅ Added |
| `phase5_to_phase6/main.py` | ✅ Added |

### 6. Daily Reconciliation Report (Session 2)
Created `bin/monitoring/daily_reconciliation.py`:
- Compares data at each phase boundary
- Schedule → Boxscores → Analytics → Features → Predictions
- Slack integration with `--alert` flag
- Exit codes for CI/CD integration

### 7. Phase Transition Monitor (Already Existed)
`bin/monitoring/phase_transition_monitor.py` provides:
- Workflow decision gap detection (warn 60min, critical 120min)
- Phase transition delay monitoring
- Stuck processor detection
- Data completeness checks

---

## 🔴 P0 - CRITICAL (Must Fix Immediately)

### A. Remaining Streaming Buffer Fixes
Files still using `insert_rows_json()` that need conversion:

**Shared Utils:**
| File | Lines | Priority |
|------|-------|----------|
| `shared/utils/proxy_manager.py` | 764, 802 | HIGH |
| `shared/utils/bdl_availability_logger.py` | 298 | MEDIUM |
| `shared/utils/scraper_availability_logger.py` | 324 | MEDIUM |
| `shared/utils/mlb_player_registry/resolver.py` | 326, 364 | MEDIUM (MLB) |
| `shared/validation/phase_boundary_validator.py` | 526 | HIGH |

**Data Processors:**
| File | Lines | Priority |
|------|-------|----------|
| `data_processors/precompute/mlb/pitcher_features_processor.py` | 1027 | MEDIUM (MLB) |
| `data_processors/precompute/mlb/lineup_k_analysis_processor.py` | 388 | MEDIUM (MLB) |

**Cloud Functions (need sync after shared/ fixes):**
- All `orchestration/cloud_functions/*/shared/utils/` directories contain copies of shared utilities
- After fixing main shared/ files, run sync script: `bin/orchestrators/sync_shared_utils.sh`

**Other:**
| File | Lines | Priority |
|------|-------|----------|
| `predictions/mlb/worker.py` | 662 | MEDIUM (MLB) |
| `predictions/shadow_mode_runner.py` | 321 | LOW |
| `predictions/worker/env_monitor.py` | 255 | LOW |
| `monitoring/scraper_cost_tracker.py` | 397 | LOW |
| `monitoring/pipeline_latency_tracker.py` | 377 | LOW |
| `functions/monitoring/data_completeness_checker/main.py` | 418, 449 | LOW |
| `functions/monitoring/realtime_completeness_checker/main.py` | 110, 307 | LOW |
| `scrapers/scraper_base.py` | 1319 | MEDIUM |
| `scrapers/news/storage.py` | 232, 385, 522 | LOW |

### B. Phase Transition Gating
**Problem:** Pipeline proceeds with partial data, causing NULL cascades.

**Implementation:**
1. Add completeness check before Phase 2→3 transition
2. Require 80%+ boxscore coverage before proceeding
3. Block transition if below threshold, alert operators

**Files to modify:**
- `orchestration/cloud_functions/phase2_to_phase3/main.py`
- `orchestration/cloud_functions/phase3_to_phase4/main.py`
- `orchestration/cloud_functions/phase4_to_phase5/main.py`

### C. Streaming Buffer Auto-Retry
**Problem:** Games with streaming conflicts are skipped without retry.

**Implementation:**
```python
MAX_STREAMING_RETRIES = 3
RETRY_DELAYS = [300, 600, 1200]  # 5min, 10min, 20min

def save_data_with_retry(self, rows, streaming_conflicts):
    for attempt, delay in enumerate(RETRY_DELAYS):
        if not streaming_conflicts:
            return self._do_save(rows)
        time.sleep(delay)
        streaming_conflicts = self._check_streaming_status(streaming_conflicts)
```

**File to modify:**
- `data_processors/raw/balldontlie/bdl_boxscores_processor.py`

---

## 🟠 P1 - HIGH PRIORITY (This Week)

### D. Silent Exception Audit
**Problem:** 7,061 `except: pass` patterns hide errors.

**Approach:**
1. Use grep to find remaining patterns
2. Prioritize orchestration/ and predictions/ directories
3. Replace with specific exception handling + logging

**Command to find:**
```bash
grep -rn "except:" --include="*.py" | grep -v "except Exception" | grep -v tests/
```

### E. More Frequent Workflow Monitoring
**Problem:** Daily health check only runs once at 7 AM ET.

**Options:**
1. Create Cloud Scheduler job running every 30 min
2. Add HTTP endpoint for on-demand checks
3. Add to existing phase transition orchestrators

### F. Sync Cloud Function Shared Utils
After fixing main shared/ utilities, sync to cloud functions:
```bash
./bin/orchestrators/sync_shared_utils.sh
```

### G. Deploy v_game_id_mappings View
```bash
bq query --use_legacy_sql=false < schemas/bigquery/raw/v_game_id_mappings.sql
```

---

## 🟡 P2 - MEDIUM PRIORITY (This Sprint)

### H. Create Streaming Conflict Log Table
```sql
CREATE TABLE nba_orchestration.streaming_conflict_log (
  conflict_id STRING,
  timestamp TIMESTAMP,
  processor_name STRING,
  game_id STRING,
  game_date DATE,
  conflict_type STRING,
  retry_count INT64,
  resolved BOOL,
  resolution_time TIMESTAMP,
  resolution_method STRING,
  details JSON
);
```

### I. BigQuery Client Pooling
**Problem:** 145 files create fresh BigQuery clients.

**Fix:** Use `get_bigquery_client()` from `shared/clients/bigquery_pool.py`

### J. HTTP Session Pooling
**Problem:** 187 direct requests without pooling.

**Fix:** Use `get_http_session()` from `shared/clients/http_pool.py`

### K. Dead Letter Queue Configuration
**Problem:** 10+ Pub/Sub topics missing DLQ.

**Topics needing DLQ:**
- phase3-trigger
- phase4-trigger
- phase3-analytics-complete
- prediction-requests
- grading-requests

---

## 🔵 P3 - LOW PRIORITY (Technical Debt)

### L. Prediction Worker State Persistence
- Add Firestore state persistence
- Add heartbeat monitoring
- Recover from Cloud Run restarts

### M. Circuit Breaker for Streaming Conflicts
- Trip if >50% of games conflict
- Prevent cascading failures

### N. Soft Dependencies with Thresholds
- Replace binary dependency checks
- Allow partial processing when upstream is incomplete

---

## VALIDATION COMMANDS

```bash
# Daily health check
python bin/validation/comprehensive_health_check.py --date $(date +%Y-%m-%d)

# Workflow health (orchestration)
python bin/validation/workflow_health.py --hours 48 --threshold-minutes 120

# Phase transition health
python bin/validation/phase_transition_health.py --days 7

# Root cause analysis
python bin/validation/root_cause_analyzer.py --date $(date +%Y-%m-%d) --issue all

# Find streaming inserts
grep -rn "insert_rows_json" --include="*.py" | grep -v tests/ | grep -v docs/

# Find silent exceptions
grep -rn "except:" --include="*.py" | grep -v "except Exception" | grep -v tests/
```

---

## DEPLOYMENT CHECKLIST

After making changes:

1. [ ] Run tests: `pytest tests/unit/ -v`
2. [ ] Sync cloud function shared utils: `./bin/orchestrators/sync_shared_utils.sh`
3. [ ] Deploy affected cloud functions:
   - `./bin/orchestrators/deploy_phase2_to_phase3.sh`
   - `./bin/orchestrators/deploy_phase3_to_phase4.sh`
   - etc.
4. [ ] Monitor Slack for errors after deployment
5. [ ] Run validation: `python bin/validation/comprehensive_health_check.py`

---

## SESSION NOTES

**Key Insight:** The 45-hour outage went undetected because:
1. Existing validation only checked "does data exist?" not "is orchestration running?"
2. Count-based validation showed data (stale), hiding quality degradation
3. No monitoring of workflow decision gaps

**Root Cause of Streaming Buffer Conflicts:**
- Logging utilities used `insert_rows_json()` (streaming inserts)
- This creates 90-minute buffer blocking DML operations
- Fixed by converting to `load_table_from_json()` (batch loading)

**Files Updated This Session:**
- `shared/utils/phase_execution_logger.py`
- `shared/utils/pipeline_logger.py`
- `shared/utils/completion_tracker.py`
- `shared/utils/proxy_health_logger.py`
- `shared/utils/daily_scorecard.py`
- `data_processors/raw/processor_base.py`
- `orchestration/cloud_functions/daily_health_summary/main.py`

---

*Last Updated: January 25, 2026*
