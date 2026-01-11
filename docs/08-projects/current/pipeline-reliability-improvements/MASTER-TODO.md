# Pipeline Reliability Master TODO

**Created:** December 30, 2025
**Last Updated:** January 11, 2026 (Prop Data Gap Incident - Session 10)
**Status:** Active - Comprehensive tracking document
**Total Items:** 112+ (added 7 from prop data gap incident)

---

## Session 11 Progress (Jan 11, 2026 - Continuation)

### Completed This Session
- [x] **Props Backfill Complete** - 46 dates loaded (Nov 14 - Dec 31), 28,078 records
- [x] **NO_LINE Alert Deployed** - Cloud Function `prediction-health-alert-00002` active
- [x] **CatBoost V8 Added to Backfill** - Now generates 6 prediction systems
- [x] **Predictions Regenerated** - Nov 19 - Dec 19 with Vegas lines (6,244 predictions)
- [x] **Grading Re-run** - 35,166 predictions graded with correct prop data
- [x] **catboost_v8 Historical Verified** - 121,215 predictions since Nov 2021 (live production)
- [x] **Gap Recovery Plan Created** - Full analysis of Oct 22 - Nov 13 gap

### Key Findings
- **catboost_v8 performance: 74-82% win rate** (better than 70% claim)
- **Production worker already generates catboost_v8** - backfill wasn't needed historically
- **Oct 22 - Nov 13 gap requires historical Odds API** - separate recovery effort

### Files Modified/Created
- `backfill_jobs/prediction/player_prop_predictions_backfill.py` - Added CatBoost V8
- `docs/.../2026-01-11-GAP-RECOVERY-PLAN.md` - Recovery plan for remaining gap

---

## Session 10 Progress (Jan 11, 2026)

### Completed This Session
- [x] **YESTERDAY Bug Fix Deployed** - Phase 3 analytics now handles YESTERDAY date correctly
- [x] **Pick Subset Tracking Schema** - Multi-model aware performance tracking tables created
- [x] **NO_LINE Alerting Added** - prediction_health_alert now detects prop data gaps
- [x] **Prop Gap Detection Enabled** - Added odds_api_player_props to processor_config.py
- [x] **Props Backfill Script Created** - scripts/backfill_odds_api_props.py
- [x] **Prop Freshness Monitor Created** - tools/monitoring/check_prop_freshness.py
- [x] **Props Backfill Complete** - ✅ Done in Session 11

### Key Files Modified
- `data_processors/analytics/main_analytics_service.py` - YESTERDAY fix
- `orchestration/cloud_functions/prediction_health_alert/main.py` - NO_LINE alerting
- `monitoring/processors/gap_detection/config/processor_config.py` - Enabled prop monitoring
- `schemas/bigquery/predictions/*.sql` - Subset tracking tables

### Documentation Created
- `docs/08-projects/current/pipeline-reliability-improvements/2026-01-11-PROP-DATA-GAP-INCIDENT.md`
- `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`

---

## Overview

This document consolidates ALL pipeline improvement work discovered from:
- Original session analysis (23 items)
- 5-agent deep exploration (75+ new items)
- Existing documentation review
- Handoff document patterns
- **Jan 2026 Prop Data Gap Incident** (7 new items)

---

## Priority Legend

| Priority | Meaning | Response Time | Count |
|----------|---------|---------------|-------|
| P0 | Critical - security/reliability risk | Immediate | 3 |
| P1 | High - significant impact | This week | 15 |
| P2 | Medium - important improvement | Next 2 weeks | 15 |
| P3 | Low - nice to have | When time permits | 10+ |

---

## P0 - CRITICAL (Fix Immediately)

### P0-SEC-1: No Authentication on Coordinator Endpoints
**Status:** 🔴 Not Started
**File:** `predictions/coordinator/coordinator.py` lines 153, 296
**Risk:** CRITICAL - Remote code execution potential

**Problem:**
- `/start` endpoint has NO authentication
- `/complete` endpoint has NO authentication
- Anyone can trigger prediction batches
- Anyone can inject completion events

**Fix:**
```python
# Add to coordinator.py before route handlers
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.environ.get('COORDINATOR_API_KEY'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/start', methods=['POST'])
@require_api_key
def start_batch():
    ...
```

---

### P0-ORCH-1: Cleanup Processor is Non-Functional
**Status:** 🔴 Not Started
**File:** `orchestration/cleanup_processor.py` lines 252-267
**Risk:** HIGH - Self-healing doesn't work

**Problem:**
```python
# Line 252-267 - TODO comment, never implemented!
# TODO: Implement actual Pub/Sub publishing
# from shared.utils.pubsub_utils import publish_message

# For now, just log
logger.info(f"🔄 Would republish: {file_info['scraper_name']}")
republished_count += 1  # MISLEADING - doesn't actually republish!
```

**Fix:**
- Import and use actual Pub/Sub publishing
- Test with simulated missing files

---

### P0-ORCH-2: Phase 4→5 Has No Timeout
**Status:** 🔴 Not Started
**File:** `orchestration/cloud_functions/phase4_to_phase5/main.py` line 54
**Risk:** HIGH - Pipeline can get stuck indefinitely

**Problem:**
```python
trigger_mode: str = 'all_complete'  # No timeout, no fallback
```
If ANY Phase 4 processor fails to publish completion, Phase 5 NEVER triggers.

**Fix:**
- Add `max_wait_hours: float = 4.0` parameter
- Implement timeout-based trigger
- Log warning when timeout triggers

---

## P1 - HIGH PRIORITY (This Week)

### P1-PERF-1: Add BigQuery Query Timeouts
**Status:** 🔴 Not Started
**File:** `predictions/worker/data_loaders.py` lines 112-183, 270-312

**Problem:** BigQuery queries have no timeout - workers can hang indefinitely

**Fix:**
```python
# Add timeout parameter to all queries
results = self.client.query(query, job_config=job_config).result(timeout=30)
```

---

### P1-PERF-2: Batch Load Historical Games (50x Performance)
**Status:** 🔴 Not Started
**Files:** `worker.py:571`, `data_loaders.py:435-559`

**Problem:** Worker calls `load_historical_games()` per-player sequentially

**Available Solution:**
```python
# data_loaders.py already has batch method!
def load_historical_games_batch(
    self,
    player_lookups: List[str],
    game_date: date
) -> Dict[str, List[Dict]]:
    # Load all players in ONE query - 50x faster
```

**Fix:** Coordinator pre-loads all historical games, passes to workers

---

### P1-PERF-3: Fix MERGE FLOAT64 Partitioning Error
**Status:** 🔴 Not Started
**File:** `predictions/worker/batch_staging_writer.py` lines 302-319

**Error:**
```
Invalid MERGE query: 400 Partitioning by expressions of type FLOAT64 is not allowed
```

**Root Cause:**
- ROW_NUMBER uses `CAST(current_points_line AS STRING)` ✓
- ON clause uses raw `current_points_line` without CAST ✗

**Fix:**
```python
# Line 319 - change:
ON T.current_points_line = S.current_points_line
# To:
ON CAST(T.current_points_line AS STRING) = CAST(S.current_points_line AS STRING)
```

---

### P1-ORCH-3: Add Phase 5→6 Data Validation
**Status:** 🔴 Not Started
**File:** `orchestration/cloud_functions/phase5_to_phase6/main.py` lines 106-136

**Problem:** Only checks status='success', doesn't verify actual data exists

**Fix:**
```python
# Add before triggering Phase 6:
row_count = bq_client.query(f"""
    SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}' AND is_active = TRUE
""").result().to_dataframe().iloc[0, 0]

if row_count < MIN_PREDICTIONS_THRESHOLD:
    logger.error(f"Insufficient predictions: {row_count}")
    return
```

---

### P1-ORCH-4: Add Health Checks to Cloud Functions
**Status:** 🔴 Not Started
**Files:** All `orchestration/cloud_functions/*/main.py`

**Problem:** No `/health` endpoints - can't detect function failures

**Fix:** Add to each function:
```python
@functions_framework.http
def health(request):
    # Check Firestore
    db.collection('_health_check').document('probe').get()
    # Check BigQuery
    bq_client.list_datasets(max_results=1)
    return jsonify({'status': 'healthy'}), 200
```

---

### P1-DATA-1: Fix Prediction Duplicates
**Status:** 🔴 Not Started
**File:** `predictions/worker/worker.py` lines 996-1041

**Problem:** Uses `WRITE_APPEND` which creates duplicates on Pub/Sub retry

**Fix:** Use MERGE statement instead of load_table_from_json

---

### P1-DATA-2: Update Circuit Breaker Hardcodes
**Status:** 🟡 Partial (2/7 done)
**Files:** 5 processor files still need updates

| File | Line | Status |
|------|------|--------|
| `player_composite_factors_processor.py` | 1066 | 🔴 TODO |
| `player_shot_zone_analysis_processor.py` | 810 | 🔴 TODO |
| `player_daily_cache_processor.py` | 1172, 1237 | 🔴 TODO |
| `team_defense_zone_analysis_processor.py` | 607 | 🔴 TODO |
| `upcoming_team_game_context_processor.py` | 1036 | 🔴 TODO |

---

### P1-MON-1: Implement DLQ Monitoring
**Status:** 🔴 Not Started

**Existing DLQs:**
- `analytics-ready-dead-letter`
- `line-changed-dead-letter`
- `phase2-raw-complete-dlq`
- `phase3-analytics-complete-dlq`

**Fix:**
- Create Cloud Monitoring alert on message count > 0
- Add DLQ status to admin dashboard
- Consider auto-replay mechanism

---

### P1-MON-2: Add Pub/Sub Publish Retries
**Status:** 🔴 Not Started
**File:** `predictions/coordinator/coordinator.py` lines 421-424

**Problem:**
```python
future = publisher.publish(topic_path, data=message_bytes)
future.result(timeout=5.0)  # Single attempt, no retry
```

**Fix:** Implement exponential backoff with max 3 retries

---

### P1-PROC-1: PlayerDailyCacheProcessor Slowdown
**Status:** 🔴 Not Started
**File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Problem:** +39.7% slower (48.21s vs 34.52s baseline)

**Investigation:**
- [ ] Profile 4 extract queries
- [ ] Check records_processed correlation
- [ ] Review completeness checking overhead

---

### P1-PROC-2: Missing Individual Player Retry
**Status:** 🔴 Not Started
**File:** `predictions/worker/worker.py` lines 314-334

**Problem:**
```python
if not predictions:
    logger.warning(f"No predictions generated for {player_lookup}")
    return ('', 204)  # Pub/Sub won't retry!
```

**Fix:** Return 500 on transient errors to trigger Pub/Sub retry

---

## P2 - MEDIUM PRIORITY (Next 2 Weeks)

### P2-PERF-1: Add Feature Caching
**File:** `predictions/worker/worker.py` lines 88-96
- Features for same game_date queried 450 times
- Add cache with 5-minute TTL

### P2-PERF-2: Fix Validation Threshold Inconsistency
**Files:** `data_loaders.py:705` vs `worker.py:496`
- Default is 70.0 but worker uses 50.0
- Standardize to single config value

### P2-ORCH-1: Implement DLQ for Cloud Functions
**Files:** All orchestration cloud functions
- Send permanently failed messages to DLQ
- Distinguish transient vs permanent errors

### P2-ORCH-2: Add Firestore Document Cleanup
**File:** `orchestration/cloud_functions/transition_monitor/main.py`
- Documents accumulate forever
- Implement 30-day TTL or cleanup function

### P2-MON-1: End-to-End Latency Tracking
- Create `nba_monitoring.pipeline_execution_log` table
- Track game_end → grading latency
- Define 6-hour SLA

### P2-MON-2: Add Firestore Health to Dashboard
- Integrate `monitoring/firestore_health_check.py`
- Show connectivity, latency, stuck processors

### P2-MON-3: Add Slowdown Alerts to Dashboard
- Integrate `monitoring/processor_slowdown_detector.py`
- Show processors > 2x baseline

### P2-MON-4: Per-System Prediction Success Rates
**File:** `predictions/worker/execution_logger.py` lines 88-91
- Systems tracked but not exposed as metrics
- Add per-system success rate dashboard

### P2-SEC-1: Fix API Key Timing Attack
**File:** `services/admin_dashboard/main.py` lines 116-132
- Simple string comparison vulnerable
- Use `secrets.compare_digest()`

### P2-SEC-2: Add Rate Limiting
**File:** `services/admin_dashboard/main.py`
- No rate limiting anywhere
- Add Flask-Limiter

### P2-DATA-1: Automatic Backfill Trigger
- Create `boxscore-backfill-trigger` Cloud Function
- Listen to gaps-detected topic
- Trigger scraper for missing dates

### P2-DATA-2: Extend Self-Heal to Phase 2
**File:** `orchestration/cloud_functions/self_heal/main.py`
- Currently only checks predictions
- Add boxscore, game context, prop lines checks

### P2-PROC-1: Generic Exception Handling
**File:** `data_processors/analytics/analytics_base.py`
- 34 try-except blocks with generic catching
- Implement custom exception hierarchy

### P2-PROC-2: Missing Dependency Validation
**File:** `data_processors/precompute/precompute_base.py` lines 232-243
- Only checks existence, not data quality
- Add row count validation

### P2-PROC-3: Incomplete Fallback Logic
**File:** `shared/processors/patterns/fallback_source_mixin.py`
- No retry on transient failures
- Add exponential backoff

---

## P3 - LOWER PRIORITY (When Time Permits)

### Performance
- P3-PERF-1: Migrate coordinator to Firestore (multi-instance)
- P3-PERF-2: No batch staging cleanup strategy

### Orchestration
- P3-ORCH-1: Add SLA monitoring for predictions
- P3-ORCH-2: Fix batch ID format for Firestore
- P3-ORCH-3: Phase 2→3 vestigial trigger (wasted Pub/Sub)

### Monitoring
- P3-MON-1: Add metrics/Prometheus endpoint
- P3-MON-2: Admin audit trail to database
- P3-MON-3: Quality score distribution metrics
- P3-MON-4: Recommendation distribution (OVER/UNDER/PASS)

### Data
- P3-DATA-1: Multi-source scraper fallback
- P3-DATA-2: BigQuery fallback for Firestore

---

## Summary Statistics

| Category | P0 | P1 | P2 | P3 | Total |
|----------|-----|-----|-----|-----|-------|
| Security | 1 | 0 | 2 | 0 | 3 |
| Performance | 0 | 3 | 2 | 2 | 7 |
| Orchestration | 2 | 2 | 2 | 3 | 9 |
| Data Reliability | 0 | 2 | 2 | 2 | 6 |
| Monitoring | 0 | 2 | 4 | 4 | 10 |
| Processors | 0 | 2 | 3 | 0 | 5 |
| **TOTAL** | **3** | **11** | **15** | **11** | **40** |

*Note: Full count is 75+ when including all sub-items from agent findings*

---

## Quick Reference: Files with Most Issues

| File | Issues | Priority Range |
|------|--------|----------------|
| `predictions/coordinator/coordinator.py` | 8 | P0-P2 |
| `predictions/worker/worker.py` | 6 | P1-P2 |
| `orchestration/cleanup_processor.py` | 2 | P0 |
| `data_processors/analytics/analytics_base.py` | 5 | P1-P2 |
| `services/admin_dashboard/main.py` | 6 | P1-P3 |
| `predictions/worker/data_loaders.py` | 4 | P1-P2 |
| `batch_staging_writer.py` | 2 | P1 |
| `phase4_to_phase5/main.py` | 2 | P0-P1 |

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `AGENT-FINDINGS-DEC30.md` | Detailed agent findings |
| `2025-12-30-EVENING-SESSION-HANDOFF.md` | Session handoff |
| `plans/PIPELINE-ROBUSTNESS-PLAN.md` | Original robustness plan |
| `plans/ORCHESTRATION-IMPROVEMENTS.md` | Monitoring plan |
| `docs/07-monitoring/observability-gaps.md` | Observability analysis |

---

*Last Updated: December 30, 2025 Evening*
