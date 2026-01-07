# Handoff Document: December 30, 2025 Afternoon Session

**Created:** December 30, 2025 1:30 PM PT
**For:** Next chat session to continue pipeline reliability improvements
**Status:** Ready for handoff

---

## What Was Completed This Session

### Deployments (All Live)
1. **daily-yesterday-analytics scheduler** - 6:30 AM ET, runs backward-looking Phase 3 analytics
2. **Grading Cloud Function** - Now has pre-validation and auto-heal capability
3. **Transition Monitor** - Now checks player_game_summary for yesterday with actionable alerts
4. **Admin Dashboard** - New Processor Failures and Coverage Metrics tabs
5. **Phase 2 Raw Processors** - NbacGamebookProcessor now outputs standardized game_id

### Code Changes (Committed: `21a2ef5`)
- `bin/orchestrators/setup_yesterday_analytics_scheduler.sh` (new)
- `shared/utils/game_id_converter.py` (new)
- `orchestration/cloud_functions/grading/main.py` - pre-validation + auto-heal
- `orchestration/cloud_functions/transition_monitor/main.py` - player_game_summary check
- `data_processors/raw/nbacom/nbac_gamebook_processor.py` - standardized game_id
- Admin dashboard: new endpoints + templates

---

## Critical Gaps Identified (Priority Order)

### P0: CRITICAL - Must Fix

#### 1. No Explicit Wait Between 6:30 AM Analytics and 7:00 AM Grading
**Problem:** Grading scheduler fires at 7:00 AM assuming Phase 3 completes in 30 minutes. If Phase 3 is slow, grading runs with incomplete/no data.

**Current Mitigation:** Pre-grading validation added, but it only checks AFTER grading starts.

**Recommended Fix:**
```
Option A: Change grading scheduler to 7:30 AM (gives 1 hour buffer)
Option B: Add explicit completion check in grading that waits/retries
Option C: Make grading trigger event-driven (fires when Phase 3 completes)
```

**Files to modify:**
- `bin/deploy/deploy_grading_function.sh` (scheduler time)
- `orchestration/cloud_functions/grading/main.py` (add wait/retry)

#### 2. Firestore is Single Point of Failure
**Problem:** ALL phase orchestrators (3→4→5→6) depend on Firestore. If Firestore is down, entire pipeline halts with no fallback.

**No current mitigation.**

**Recommended Fix:**
- Add BigQuery fallback for phase completion tracking
- Or: Add health check that alerts immediately on Firestore failures

#### 3. Self-Heal Runs 45 Minutes AFTER Phase 6 Export
**Problem:** Self-heal runs at 2:15 PM ET. Phase 6 export (tonight-picks) runs at 1:00 PM. If predictions are missing at 1:00 PM, export fails and self-heal won't fix it for 45 more minutes.

**Recommended Fix:**
```
Option A: Move self-heal to 12:45 PM (before Phase 6 export)
Option B: Add pre-export validation in Phase 6
Option C: Make Phase 6 trigger conditional on predictions existing
```

---

### P1: HIGH - Should Fix Soon

#### 4. No End-to-End Pipeline Latency Tracking
**Problem:** Can't measure how long from "game ends" to "predictions graded". No SLA monitoring.

**Files that track partial latency:**
- `processor_run_history.duration_seconds` - per processor only
- No aggregation across phases

**Recommended Fix:**
- Add `pipeline_execution_log` table tracking game_id → phase timestamps
- Create dashboard showing end-to-end latency

#### 5. Dead Letter Queues Not Monitored
**Problem:** Pub/Sub DLQs exist but messages can expire without alerting.

**Location:** `bin/infrastructure/create_phase2_phase3_topics.sh`

**Recommended Fix:**
- Add Cloud Monitoring alert on DLQ message count > 0
- Add dashboard visibility for DLQ status

#### 6. Processor Slowdown Detection Missing
**Problem:** Processors getting slower over time would go unnoticed until they timeout.

**Data exists:** `processor_run_history.duration_seconds`

**Recommended Fix:**
```sql
-- Alert if processor is 2x slower than 7-day average
SELECT processor_name, AVG(duration_seconds) as avg_7d
FROM processor_run_history
WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name
```

#### 7. Dashboard Action Endpoints Are Stubs
**Problem:** "Force Predictions" and "Retry Phase" buttons don't actually work - they just log the request.

**Location:** `services/admin_dashboard/main.py` lines 369-400

**Recommended Fix:**
- Implement actual HTTP calls to Cloud Run endpoints
- Add confirmation dialogs
- Add audit logging

---

### P2: MEDIUM - Should Address

#### 8. No Data Quality Validation Beyond Row Counts
**Problem:** Processor could produce wrong data (nulls, duplicates, schema violations) without alerting.

**Existing infrastructure:** `shared/validation/validators/` (phase validators exist but underutilized)

**Recommended Fix:**
- Enable schema validation in processor_base.py before BigQuery insert
- Add null rate checks per column
- Add duplicate detection

#### 9. Gap Detection Only Covers 1 Processor
**Problem:** `monitoring/processors/gap_detection/` only monitors `nbac_player_list`. Other 20+ processors have no gap detection.

**Recommended Fix:**
- Expand config to cover critical processors (gamebook, boxscores, schedule)
- Prioritize Phase 2 sources that block downstream

#### 10. Daily Health Check is Manual
**Problem:** `bin/monitoring/daily_health_check.sh` must be run manually each morning.

**Recommended Fix:**
- Convert to Cloud Run job
- Add Cloud Scheduler trigger at 6:00 AM ET
- Store results in BigQuery for trending
- Send Slack/email summary

#### 11. No Stuck Processor Visibility in Dashboard
**Problem:** Firestore service has `get_run_history_stuck()` but it's NOT exposed in dashboard.

**Location:** `services/admin_dashboard/services/firestore_service.py`

**Recommended Fix:**
- Add `/api/stuck-processors` endpoint
- Add "Stuck Processors" tab to dashboard
- Show processors with status='running' for >30 minutes

#### 12. No Phase Processor Checklist in Dashboard
**Problem:** Dashboard shows aggregate counts but not which specific processors completed within Phase 3/4.

**Data exists:** Firestore `phase3_completion/{date}` has per-processor status

**Recommended Fix:**
- Add orchestration state display showing:
  - Phase 3: ☑ player_game_summary ☑ team_defense ☐ team_offense...
  - Phase 4: ☑ ml_feature_store ☐ player_composite...

---

### P3: LOW - Nice to Have

#### 13. No Trend Visualization in Dashboard
- Coverage and grading metrics shown as tables, not charts
- No anomaly detection (MAE trending up?)

#### 14. No Audit Trail for Manual Actions
- Dashboard actions not logged
- Can't see who triggered what and when

#### 15. No Predictive Gap Warnings
- Can't warn before data goes stale
- Only react after the fact

#### 16. Limited Historical Depth
- Only 7 days shown
- No seasonal pattern analysis

---

## Daily Orchestration Timeline (Current State)

```
6:30 AM ET  │ daily-yesterday-analytics (Phase 3)
            │   └─ PlayerGameSummary, TeamDefense, TeamOffense for YESTERDAY
            │   └─ ⚠️ ASSUMES completes in 30 minutes
            │
7:00 AM ET  │ Grading (via phase6-daily-results topic)
            │   └─ ⚠️ NO EXPLICIT WAIT for 6:30 AM to complete
            │   └─ Pre-validation added, but runs AFTER scheduler fires
            │
10:30 AM ET │ same-day-phase3 (Phase 3)
            │   └─ UpcomingPlayerGameContext for TODAY
            │   └─ Triggers Phase 3→4 orchestrator via Firestore
            │
11:00 AM ET │ same-day-phase4 (Phase 4)
            │   └─ MLFeatureStoreProcessor for TODAY
            │   └─ Triggers Phase 4→5 orchestrator via Firestore
            │
11:30 AM ET │ same-day-predictions (Phase 5)
            │   └─ Prediction Coordinator generates predictions
            │   └─ Triggers Phase 5→6 if >80% complete
            │
1:00 PM ET  │ phase6-tonight-picks (Phase 6)
            │   └─ ⚠️ NO VALIDATION that predictions exist
            │
2:15 PM ET  │ self_heal
            │   └─ ⚠️ 45 minutes AFTER Phase 6 export
            │   └─ Checks predictions exist, re-triggers if missing
            │
11:00 PM PT │ Evening Phase 4 processors (YESTERDAY)
(2:00 AM ET)│   └─ player-composite-factors-daily
            │   └─ player-daily-cache-daily
            │   └─ ml-feature-store-daily
```

---

## Key Files Reference

### Orchestration
| Purpose | File |
|---------|------|
| Scheduler setup | `bin/orchestrators/setup_yesterday_analytics_scheduler.sh` |
| Same-day schedulers | `bin/orchestrators/setup_same_day_schedulers.sh` |
| Phase 3→4 orchestrator | `orchestration/cloud_functions/phase3_to_phase4/main.py` |
| Phase 4→5 orchestrator | `orchestration/cloud_functions/phase4_to_phase5/main.py` |
| Self-heal | `orchestration/cloud_functions/self_heal/main.py` |
| Transition monitor | `orchestration/cloud_functions/transition_monitor/main.py` |
| Grading function | `orchestration/cloud_functions/grading/main.py` |

### Monitoring
| Purpose | File |
|---------|------|
| Daily health check | `bin/monitoring/daily_health_check.sh` |
| Freshness monitor | `monitoring/scrapers/freshness/` |
| Gap detection | `monitoring/processors/gap_detection/` |
| Stall detection | `monitoring/stall_detection/` |

### Data Quality
| Purpose | File |
|---------|------|
| Base validators | `shared/validation/validators/base.py` |
| Phase validators | `shared/validation/validators/phase{1-5}_validator.py` |
| Completeness checker | `shared/utils/completeness_checker.py` |
| Freshness checker | `shared/utils/data_freshness_checker.py` |
| Quality mixin | `shared/processors/patterns/quality_mixin.py` |

### Admin Dashboard
| Purpose | File |
|---------|------|
| Main app | `services/admin_dashboard/main.py` |
| BigQuery service | `services/admin_dashboard/services/bigquery_service.py` |
| Firestore service | `services/admin_dashboard/services/firestore_service.py` |
| Dashboard template | `services/admin_dashboard/templates/dashboard.html` |

---

## Suggested Next Steps (In Order)

### Immediate (Today/Tomorrow)
1. **Adjust grading scheduler timing** - Move from 7:00 AM to 7:30 AM ET for buffer
2. **Add pre-export validation to Phase 6** - Check predictions exist before exporting

### This Week
3. **Implement dashboard action endpoints** - Make Force Predictions actually work
4. **Add stuck processor visibility** - Expose `get_run_history_stuck()` to dashboard
5. **Automate daily health check** - Convert to Cloud Run job with scheduler

### Next Week
6. **Add processor slowdown detection** - Query duration trends, alert on 2x baseline
7. **Expand gap detection** - Cover top 10 critical processors
8. **Add DLQ monitoring** - Cloud Monitoring alerts on dead letter queues

### Future
9. **End-to-end latency tracking** - New table tracking game→prediction latency
10. **Data quality validation** - Schema validation before BigQuery insert
11. **Dashboard trend visualization** - Charts for MAE, success rates over time

---

## Testing Commands

```bash
# Verify scheduler is working
gcloud scheduler jobs list --location=us-west2 | grep yesterday

# Test transition monitor manually
curl https://transition-monitor-f7p3g7f6ya-wl.a.run.app

# Check processor failures in last 24h
bq query --use_legacy_sql=false "
SELECT processor_name, status, COUNT(*)
FROM nba_reference.processor_run_history
WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1, 2
ORDER BY 3 DESC
"

# Check player_game_summary coverage for yesterday
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as rows
FROM nba_analytics.player_game_summary
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY 1
"

# Check grading status
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as graded, ROUND(AVG(absolute_error), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC
"
```

---

## Git Status

```
Branch: main
Last commit: 21a2ef5 feat: Add comprehensive pipeline reliability improvements
Status: 1 commit ahead of origin/main (not pushed)
```

**To push:** `git push origin main`

---

*Document created by Claude Code session on December 30, 2025*
