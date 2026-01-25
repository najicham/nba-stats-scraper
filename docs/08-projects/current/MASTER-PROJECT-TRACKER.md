# Master Project Tracker - January 25, 2026
**Last Updated:** 2026-01-25 Session 15 (Final)
**Status:** 🟢 Pipeline Resilience Phase 1+2 Complete
**Owner:** Data Engineering Team

---

## Executive Dashboard

### 🔄 Session 15: Pipeline Resilience Implementation Complete (Jan 24-25)

Implemented Week 1 + Week 2 resilience improvements from the Jan 24 remediation plan.

#### Week 1 Deliverables ✅
| Deliverable | Status | Description |
|-------------|--------|-------------|
| Orchestrator Deployments | ✅ DEPLOYED | Phase 3→4, 4→5, 5→6 all redeployed with 512MB + fixes |
| failed_processor_queue Table | ✅ CREATED | BigQuery table for auto-retry tracking |
| pipeline_event_log Table | ✅ CREATED | BigQuery table for audit trail |
| pipeline_logger Utility | ✅ CREATED | `shared/utils/pipeline_logger.py` for event logging |
| auto-retry-processor Function | ✅ DEPLOYED | Cloud Function + Scheduler (every 15 min) |
| Cloud Function Import Fix | ✅ FIXED | `shared/validation/__init__.py` simplified in all CFs |

#### Week 2 Deliverables ✅
| Deliverable | Status | Description |
|-------------|--------|-------------|
| Phase 3 Event Logging | ✅ INTEGRATED | `analytics_base.py` logs start/complete/error events |
| Phase 4 Event Logging | ✅ INTEGRATED | `precompute_base.py` logs start/complete/error events |
| Recovery Dashboard View | ✅ CREATED | `nba_orchestration.v_recovery_dashboard` BigQuery view |
| Memory Warning Alert | ✅ CREATED | `bin/monitoring/setup_memory_alerts.sh` script |
| Config Drift Detection | ✅ CREATED | `bin/validation/detect_config_drift.py` script |
| Daily Health Email Updates | ✅ UPDATED | Added recovery stats to daily summary |
| E2E Tests for Auto-Retry | ✅ CREATED | `tests/e2e/test_auto_retry.py` |

**Key Accomplishments:**
- All Phase 3-4 processor events now logged to BigQuery for observability
- Auto-retry system detects failures and retries transient errors (up to 3 times)
- Recovery dashboard provides single pane of glass for pipeline health
- Config drift detection prevents silent misconfigurations
- Daily health email now includes recovery stats (pending, succeeded, rate)

**New Files Created:**
- `shared/utils/pipeline_logger.py` - Comprehensive pipeline event logging with deduplication
- `orchestration/cloud_functions/auto_retry_processor/main.py` - Auto-retry Cloud Function
- `bin/orchestrators/deploy_auto_retry_processor.sh` - Deploy script
- `bin/validation/detect_config_drift.py` - Config drift detection
- `bin/monitoring/setup_memory_alerts.sh` - Memory alert setup
- `tests/e2e/test_auto_retry.py` - E2E tests for auto-retry system

---

### 🔄 Session 14: Critical Orchestration Remediation (Jan 24 Evening)

Root cause analysis and fix for daily orchestration failure (1/6 Phase 2 complete):

| Fix | Priority | Status | Impact |
|-----|----------|--------|--------|
| Processor Name Mismatch | P0 | ✅ FIXED | Config expected old names, scrapers publish `p2_*` names |
| BigQuery Metadata Serialization | P1 | ✅ FIXED | Added `json.dumps()` for metadata field |
| Registry Broken Entry | P2 | ✅ FIXED | `nbac_schedule` pointed to missing file |
| Orchestrator Memory (256→512MB) | P1 | ✅ FIXED | OOM errors eliminated |
| Memory Monitoring Script | P2 | ✅ ADDED | `check_cloud_resources.sh` for proactive detection |

**Files Modified:**
- `shared/config/orchestration_config.py` - Fixed 6 processor names
- `shared/utils/phase_execution_logger.py` - Added json.dumps()
- `scrapers/registry.py` - Fixed nbac_schedule entry
- `bin/orchestrators/deploy_*.sh` (4 files) - Memory 256→512MB
- `bin/monitoring/check_cloud_resources.sh` - NEW monitoring script
- `docs/00-orchestration/services.md` - Memory guidelines
- `docs/00-orchestration/troubleshooting.md` - 4 new troubleshooting sections

**Root Cause:** Orchestration config processor names didn't match what scrapers actually publish. Config expected `bdl_player_boxscores` but scrapers publish `p2_bdl_box_scores`.

---

### 🔄 Session 13: Critical Infrastructure Fixes (Jan 24)

Multi-agent analysis and fixes applied. Key improvements:

| Fix | Priority | Status | Impact |
|-----|----------|--------|--------|
| Phase 5 Worker Scaling | P0 | ✅ FIXED | 10→50 max instances (was 32% failures) |
| CatBoost V8 Model Path | P0 | ✅ FIXED | Default path now set in deploy script |
| Proxy Credentials Hardcoded | P1 | ✅ FIXED | Removed from source (security) |
| User-Agent WAF Detection | P1 | ✅ FIXED | Changed from "NBA-Stats-Scraper" to Chrome UA |
| Cloud Logging TODOs | P2 | ✅ FIXED | R-006/R-008 alerts now query Cloud Logging |
| 5 Precompute Upstream Checks | P1 | ✅ FIXED | All 5 processors now have circuit breaker checks |

**Files Modified:**
- `bin/predictions/deploy/deploy_prediction_worker.sh` - Worker scaling + CatBoost default
- `scrapers/utils/proxy_utils.py` - Removed hardcoded credentials
- `shared/utils/proxy_manager.py` - Removed hardcoded credentials
- `shared/clients/http_pool.py` - Changed User-Agent
- `services/admin_dashboard/main.py` - Cloud Logging integration
- `services/admin_dashboard/services/logging_service.py` - New query methods
- 5 precompute processors - Added `get_upstream_data_check_query()`

### 🔄 Session 12 Afternoon: System-Wide Analysis (Jan 24)

5-agent deep analysis completed. New improvement projects created:

| Project | Priority | Hours | Status |
|---------|----------|-------|--------|
| Cloud Function Duplication | P0 | 8h | **NEW** - 30K duplicate lines |
| Large File Refactoring | P1 | 24h | **NEW** - 12 files >2000 LOC |
| Upstream Data Check Gaps | P1 | 4h | ✅ **FIXED** - Session 13 |
| Test Coverage Improvements | P2 | 24h | **NEW** - 79 skipped tests |

**New Documentation:**
- `architecture-refactoring-2026-01/README.md` - Cloud function consolidation & large file refactoring
- `test-coverage-improvements/README.md` - Skipped tests & E2E coverage
- `resilience-pattern-gaps/README.md` - Missing upstream checks & timeouts
- `SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md` - Consolidated improvement plan

---

### 🚨 Critical Issues (Immediate Action Required)

| ID | Issue | Status | Priority | Fixed | Notes |
|----|-------|--------|----------|-------|-------|
| **#1** | Prediction Coordinator Dockerfile | ✅ **FIXED** | P0 | Jan 22 | Deployed |
| **#2** | Prediction Worker Dockerfile | ✅ **FIXED** | P0 | Jan 22 | Missing __init__.py |
| **#3** | pdfplumber Missing | ✅ **FIXED** | P2 | Jan 22 | Added to root requirements |
| **#4** | Proxy Infrastructure Blocked | 🟡 **PARTIAL FIX** | P1 | Jan 24 | Security fixes applied (hardcoded creds, User-Agent). Need Bright Data fallback. |
| **#5** | Phase 2 Batch Processor Bug | ✅ **FIXED** | P1 | Jan 23 | Deduplication conflict resolved |
| **#6** | Health Email Metrics Bug | 🟡 **NEW** | P3 | - | Wrong counts displayed |
| **#7** | Jan 23 Cascade Failure | ✅ **FIXED** | P0 | Jan 24 | Resilience improvements deployed |

### 🔄 Reliability & Validation Improvements (Jan 24 - Session 2)

| Improvement | Status | Impact |
|-------------|--------|--------|
| Cleanup processor table coverage | ✅ Deployed | 27 tables (was 4) |
| Cleanup processor lookback window | ✅ Deployed | 4h default (was 1h) |
| Pub/Sub retry with backoff | ✅ Deployed | 3 attempts, prevents data loss |
| Proxy retry per-proxy backoff | ✅ Deployed | 40% fewer false failures |
| Phase transition handoff checks | ✅ Deployed | Detects silent Phase N+1 failures |
| DLQ monitoring via Cloud API | ✅ Deployed | Actual message counts |
| GCP_PROJECT_ID standardization | ✅ Deployed | 12 files, backwards compatible |
| NBAC Schedule validator | ✅ Created | Team presence, game counts |
| NBAC Injury Report validator | ✅ Created | Status, coverage, freshness |
| NBAC Player Boxscore validator | ✅ Created | Points calc, BDL cross-val |

### 🔄 Comprehensive Validation & Config Improvements (Jan 24 - Session 3)

| Improvement | Status | Impact |
|-------------|--------|--------|
| 12 new validator configs | ✅ Created | Full coverage for all raw data sources |
| nbac_gamebook_validator.py | ✅ Implemented | R-009 detection, starter validation, DNP checks |
| odds_api_props_validator.py | ✅ Implemented | Bookmaker coverage, line validation, player matching |
| v_scraper_latency_daily view | ✅ Created | Daily scraper latency metrics per scraper |
| v_game_data_timeline view | ✅ Created | Game-level availability across sources |
| Configurable scraper timeouts | ✅ Deployed | Per-scraper timeouts in workflows.yaml |
| Cleanup processor notification threshold | ✅ Configurable | notification_threshold in config |
| Timezone consolidation | ✅ Fixed | Removed redundant et_tz, use self.ET |
| Workflow executor logging alerts | ✅ Added | Alert on consecutive BQ logging failures |

**New Validator Configs Created:**
- `bigdataball_pbp.yaml` - Play-by-play validation
- `bdl_active_players.yaml` - Active roster validation
- `bdl_injuries.yaml` - Injury report validation
- `bdl_standings.yaml` - Standings validation
- `br_rosters.yaml` - Basketball Reference roster validation
- `espn_boxscore.yaml` - ESPN boxscore validation
- `espn_team_roster.yaml` - ESPN roster validation
- `nbac_play_by_play.yaml` - NBA.com PBP validation
- `nbac_player_list.yaml` - Player list validation
- `nbac_player_movement.yaml` - Trade/signing validation
- `nbac_referee.yaml` - Referee assignment validation
- `nbac_scoreboard_v2.yaml` - Scoreboard validation

### 🔄 Pipeline Resilience Improvements (Jan 24 - Session 1)

All items from the Jan 23 cascade failure incident have been implemented:

| Feature | Status | Description |
|---------|--------|-------------|
| Stale Processor Monitor | ✅ Deployed | 5-min detection, 15-min auto-recovery |
| Game Coverage Alert | ✅ Deployed | 2 hours before games, alerts if <8 players |
| Heartbeat System | ✅ Integrated | PrecomputeProcessorBase + AnalyticsProcessorBase |
| Soft Dependencies | ✅ Enabled | MLFeatureStore, PlayerCompositeFactors, UpcomingPlayerGameContext |
| ESPN Pub/Sub | ✅ Deployed | Triggers Phase 2 automatically |
| Pipeline Dashboard | ✅ Created | Visual HTML dashboard for monitoring |
| Auto-Backfill Orchestrator | ✅ Created | Automatic backfill on failure detection |

### 🚨 Issues Status (January 23)

| ID | Issue | Status | Impact | Details |
|----|-------|--------|--------|---------|
| **#5** | Phase 2 Batch Processor | ✅ **FIXED** | Was skipping batches | Root cause: deduplication conflict. Fix: SKIP_DEDUPLICATION=True |
| **#6** | BettingPros Blocked | 🔴 Active | 0 bettingpros data | Both ProxyFuel AND Decodo returning 403 |
| **#7** | Firestore Lock Accumulation | ✅ **FIXED** | - | Batch processors now use Firestore locks only |
| **#8** | Health Email Bug | 🟡 Low | Misleading stats | Uses run count not processor count |
| **#9** | Predictions run before lines load | ✅ **FIXED** | Was causing NO_PROP_LINE | Auto-update predictions when lines arrive |

### ✅ Completed Work (January 22-23)

| Component | Status | Deployed | Tested |
|-----------|--------|----------|--------|
| Prediction Worker Dockerfile Fix | ✅ | Jan 22 | ✅ |
| pdfplumber in root requirements | ✅ | Jan 22 | ✅ |
| Decodo Proxy Fallback | ⚠️ | Jan 22 | Now blocked |
| Proxy Health Monitoring (BigQuery) | ✅ | Jan 22 | ✅ |
| BettingPros API Key Mounted | ✅ | Jan 22 | ✅ |
| Line Quality Self-Heal Function | ✅ | Jan 23 | ✅ Working |
| Firestore Lock Cleanup | ✅ | Jan 23 | Manual |
| Pub/Sub Backlog Clear | ✅ | Jan 23 | Manual |
| **Batch Processor Dedup Fix** | ✅ | Jan 23 | ✅ Deployed |
| **Auto-Update Predictions** | ✅ | Jan 23 | ✅ Deployed |
| **Historical Odds Backfill** | ✅ | Jan 23 | Jan 19-22 complete |
| **Multi-Snapshot Lines** | ✅ | Jan 23 | Opening + Closing lines |
| **Orchestration Fixes** | ✅ | Jan 23 | YESTERDAY_TARGET_WORKFLOWS, oddsa_events resolver |
| **Feature Store 60-Day Bug** | ✅ | Jan 23 | Fixed historical completeness calculation |
| **Stale Schedule Fix Script** | ✅ | Jan 23 | Fixed column names, partition filter |

### 🔄 Active Monitoring

| Component | Status | Notes |
|-----------|--------|-------|
| Proxy Health | 🔴 BLOCKED | Both proxies blocked by BettingPros |
| BettingPros Scraper | ❌ Failing | 403 errors, 0 data for Jan 23 |
| Odds API Scraper | ✅ Working | Uses API key, no proxy |
| NBA Team Boxscore | ✅ Working | Via Decodo fallback |
| Self-Heal Function | ✅ Working | Running every 2h |
| Jan 23 Predictions | ⚠️ Stuck | 95% complete, 4 workers failing |

### 📊 Proxy Infrastructure

See: `docs/08-projects/current/proxy-infrastructure/`
- ProxyFuel (datacenter): Primary, some sites blocking
- Decodo (residential): Fallback, 25GB plan
- Health tracked in: `nba_orchestration.proxy_health_metrics`

---

## Section 1: Critical Fixes (P0 Priority)

### Issue #1: Prediction Coordinator Dockerfile ❌ NOT FIXED

**Status:** 🔴 CRITICAL - Blocking all predictions
**Impact:** Zero predictions can be generated
**Detected:** Jan 21, 15:00 ET
**Error Count:** 20 errors in 24 hours

#### Root Cause
Missing `predictions/__init__.py` in Docker container

#### Fix Plan
**File:** `predictions/coordinator/Dockerfile`
**Line:** 14 (insert after line 12)

```dockerfile
# Add this line:
COPY predictions/__init__.py ./predictions/__init__.py
```

#### Verification Steps
```bash
# 1. Build locally
docker build -f predictions/coordinator/Dockerfile -t test-coordinator .

# 2. Test import
docker run test-coordinator python -c "from predictions.coordinator.coordinator import app; print('Success!')"

# 3. Deploy to Cloud Run
gcloud run deploy prediction-coordinator \
  --source=. \
  --dockerfile=predictions/coordinator/Dockerfile \
  --region=us-west1
```

#### Unit Test Required
- [ ] Test Dockerfile COPY commands produce valid package structure
- [ ] Test predictions.coordinator imports work in container
- [ ] Test coordinator.py can import all submodules

---

### Issue #2: Phase 3 Analytics Stale Dependencies ❌ NOT FIXED

**Status:** 🔴 CRITICAL - Blocking analytics pipeline
**Impact:** 4,937 errors in 24 hours
**Detected:** Jan 21, 04:00 ET & 19:00 ET
**Error:** BDL data 45+ hours old, exceeding 36-hour threshold

#### Root Cause
BDL `bdl_player_boxscores` table hasn't updated since Jan 19

#### Fix Options

**Option A: Use Backfill Mode (RECOMMENDED - Immediate)**
```bash
# For manual runs
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-20 \
  --end-date 2026-01-20 \
  --backfill-mode
```

**Option B: Increase Threshold (Short-term)**
**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
**Line:** 209
```python
# Change: 'max_age_hours_fail': 36 → 72
```

**Option C: Make BDL Non-Critical (Long-term)**
**File:** Same as Option B
**Line:** 210
```python
# Change: 'critical': True → False
```

#### Verification Steps
```bash
# Test analytics processor runs without errors
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-20 \
  --end-date 2026-01-20 \
  --backfill-mode \
  --debug
```

#### Unit Tests Required
- [ ] Test backfill mode skips all dependency checks
- [ ] Test stale threshold logic with mock data
- [ ] Test non-critical dependency handling

---

### Issue #3: BDL Table Name Mismatch ❌ NOT FIXED

**Status:** 🔴 CRITICAL - Cleanup processor failing
**Impact:** File tracking broken
**Detected:** Jan 21, 23:45 ET
**Error:** 404 Not found: Table `bdl_box_scores` (should be `bdl_player_boxscores`)

#### Root Cause
Hardcoded incorrect table name in cleanup processor

#### Fix Plan
**File:** `orchestration/cleanup_processor.py`
**Line:** 223

```python
# Change:
SELECT source_file_path FROM `nba-props-platform.nba_raw.bdl_box_scores`
# To:
SELECT source_file_path FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
```

#### Verification Steps
```bash
# 1. Verify correct table exists
bq show nba-props-platform:nba_raw.bdl_player_boxscores

# 2. Test query after fix
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 25 HOUR)
"
```

#### Unit Test Required
- [ ] Test cleanup processor queries correct table name
- [ ] Test query returns results without 404 error
- [ ] Test all table name references are correct

---

### Issue #4: Injury Discovery Missing pdfplumber ❌ NOT FIXED

**Status:** 🟡 HIGH - Injury workflow failing
**Impact:** Injury data not updating
**Detected:** Jan 21 (21 consecutive failures)
**Error:** ModuleNotFoundError: No module named 'pdfplumber'

#### Root Cause
`pdfplumber` in scrapers/requirements.txt but NOT in data_processors/raw/requirements.txt

#### Fix Plan
**File:** `data_processors/raw/requirements.txt`
**Action:** Add pdfplumber dependency (around line 22)

```python
# PDF processing (for injury report and gamebook processors)
pdfplumber==0.11.7
```

#### Verification Steps
```bash
# 1. Deploy updated raw processor service
./bin/raw/deploy/deploy_processors_simple.sh

# 2. Verify deployment
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# 3. Test injury discovery workflow
# (Wait for next hourly trigger or manually invoke)
```

#### Unit Test Required
- [ ] Test pdfplumber import works in raw processor
- [ ] Test injury report processor can load
- [ ] Test gamebook PDF processor can load

---

## Section 2: Latency Monitoring Project

### Phase 0: Deploy Existing Monitor ✅ COMPLETE

**Completed:** January 22, 2026, 01:30 AM PST

- ✅ Scraper Availability Monitor Cloud Function deployed
- ✅ Cloud Scheduler job created (8 AM ET daily)
- ✅ Tested successfully with Jan 20 data
- ✅ Slack integration configured

**Next Alert:** January 23, 8:00 AM ET

### Phase 1: BDL Logger Integration ✅ COMPLETE

**Completed:** January 22, 2026, 01:45 AM PST

- ✅ BigQuery table deployed (`bdl_game_scrape_attempts`)
- ✅ View deployed (`v_bdl_first_availability`)
- ✅ Logger integrated into `bdl_box_scores.py`
- 🔄 **Waiting:** First production scraper run to populate table

**Next Step:** Verify data appears after tonight's games

### Phase 2: Completeness Validation ⏳ PLANNED

**Status:** Not Started
**Estimated Time:** 4 hours
**Target:** Week 1, Day 3-4

**Tasks:**
1. Create `shared/validation/scraper_completeness_validator.py`
2. Integrate into BDL scraper
3. Add to retry queue
4. Test alert flow

**Unit Tests Required:**
- [ ] Test completeness validator with mock data
- [ ] Test alert routing
- [ ] Test retry queue entry creation

### Phase 3: Fix Workflow Execution ⏳ PLANNED

**Status:** Not Started
**Estimated Time:** 2 hours
**Target:** Week 1, Day 4-5

**Tasks:**
1. Investigate why 2 AM, 4 AM, 6 AM windows didn't run
2. Check controller logs
3. Fix root cause
4. Verify all windows execute

### Phase 4: Build Retry Queue ⏳ PLANNED

**Status:** Not Started
**Estimated Time:** 6 hours
**Target:** Week 2

**Tasks:**
1. Create retry queue table
2. Build retry worker Cloud Function
3. Deploy and test
4. Monitor auto-resolution

### Phase 5: Expand to NBAC/OddsAPI ⏳ PLANNED

**Status:** Not Started
**Estimated Time:** 6 hours
**Target:** Week 2-3

**Tasks:**
1. Create NBAC availability logger
2. Create OddsAPI availability logger
3. Integrate into scrapers
4. Test and deploy

---

## Section 3: Unit Testing Plan

### Testing Infrastructure Setup

**Test Framework:** pytest
**Coverage Target:** 80%+ for new code
**Test Location:** `tests/unit/`, `tests/integration/`

### Test Suites to Create

#### Suite 1: Latency Monitoring Tests

**File:** `tests/unit/monitoring/test_availability_logger.py`

```python
# Tests to create:
- test_bdl_availability_logger_logs_games()
- test_bdl_availability_logger_handles_missing_games()
- test_bdl_availability_logger_calculates_latency()
- test_bdl_availability_logger_flags_west_coast()
- test_bdl_availability_logger_handles_empty_response()
```

**File:** `tests/unit/monitoring/test_scraper_monitor.py`

```python
# Tests to create:
- test_scraper_monitor_queries_summary_view()
- test_scraper_monitor_detects_warnings()
- test_scraper_monitor_detects_critical()
- test_scraper_monitor_sends_slack_alerts()
- test_scraper_monitor_logs_to_firestore()
```

#### Suite 2: Critical Fixes Tests

**File:** `tests/unit/orchestration/test_cleanup_processor.py`

```python
# Tests to create:
- test_cleanup_processor_uses_correct_table_name()
- test_cleanup_processor_query_succeeds()
- test_cleanup_processor_finds_recent_files()
```

**File:** `tests/unit/analytics/test_dependency_validation.py`

```python
# Tests to create:
- test_backfill_mode_skips_checks()
- test_stale_threshold_detection()
- test_non_critical_dependency_warning()
- test_critical_dependency_failure()
```

**File:** `tests/integration/test_dockerfile_builds.py`

```python
# Tests to create:
- test_prediction_coordinator_dockerfile_builds()
- test_prediction_coordinator_imports_work()
- test_predictions_package_structure_valid()
```

#### Suite 3: Completeness Validation Tests

**File:** `tests/unit/validation/test_scraper_completeness_validator.py`

```python
# Tests to create:
- test_validator_compares_schedule_to_actual()
- test_validator_identifies_missing_games()
- test_validator_sends_alerts()
- test_validator_adds_to_retry_queue()
- test_validator_handles_complete_data()
```

### Test Coverage Requirements

| Component | Target Coverage | Current Coverage |
|-----------|-----------------|------------------|
| BDL Availability Logger | 85% | 0% (new code) |
| Scraper Monitor Function | 80% | 0% (new code) |
| Completeness Validator | 85% | 0% (planned) |
| Cleanup Processor | 75% | Unknown |
| Analytics Validation | 80% | Unknown |

---

## Section 4: Implementation Timeline

### Week 1: Critical Fixes + Testing (Current Week)

**Days 1-2 (Jan 22-23):**
- [ ] Fix Issue #1: Prediction Coordinator Dockerfile
- [ ] Fix Issue #2: Phase 3 Analytics (backfill mode)
- [ ] Fix Issue #3: BDL Table Name
- [ ] Fix Issue #4: pdfplumber Dependency
- [ ] Create unit tests for all fixes
- [ ] Deploy and verify fixes

**Days 3-4 (Jan 24-25):**
- [ ] Implement Phase 2: Completeness Validation
- [ ] Create unit tests for validation
- [ ] Deploy and test validation
- [ ] Monitor first automated alerts

**Day 5 (Jan 26):**
- [ ] Investigate workflow execution issues (Phase 3)
- [ ] Document findings
- [ ] Plan fixes for Week 2

### Week 2: Expansion & Retry Queue

**Days 1-2:**
- [ ] Implement NBAC availability logger
- [ ] Create unit tests for NBAC logger
- [ ] Deploy and integrate

**Days 3-4:**
- [ ] Build retry queue infrastructure
- [ ] Create unit tests for retry worker
- [ ] Deploy and test auto-recovery

**Day 5:**
- [ ] OddsAPI availability logger
- [ ] Integration testing
- [ ] Week 2 review

### Week 3-4: Full Scraper Expansion

**Per expansion plan:** See `ALL-SCRAPERS-LATENCY-EXPANSION-PLAN.md`

---

## Section 5: Monitoring & Verification

### Daily Checks (Every Morning at 9 AM ET)

**Run Dashboard:**
```bash
bq query --nouse_legacy_sql < monitoring/daily_scraper_health.sql
```

**Check Alerts:**
- Slack `#nba-alerts` for warnings
- Slack `#app-error-alerts` for critical issues

**Verify Tables:**
```sql
-- BDL attempts (after integration activates)
SELECT COUNT(*) as attempts, COUNT(DISTINCT game_date) as dates
FROM nba_orchestration.bdl_game_scrape_attempts
WHERE scrape_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR);

-- Availability summary
SELECT * FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
```

### Weekly Reviews (Every Monday)

**Metrics to Review:**
1. Missing game rate (target: < 1%)
2. Average detection time (target: < 10 minutes)
3. Auto-recovery success rate (target: > 80%)
4. Alert accuracy (false positive rate < 5%)
5. Test coverage (target: > 80%)

**Review Meetings:**
- What went well this week?
- What issues were discovered?
- What needs to be prioritized next?
- Any architectural changes needed?

---

## Section 6: Risk Management

### High-Risk Items

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| BDL data remains stale | Medium | High | Use backfill mode, consider making BDL non-critical |
| Prediction coordinator still fails after fix | Low | High | Test locally before deploying |
| Unit tests reveal more issues | Medium | Medium | Address discovered issues before proceeding |
| Workflow execution issues persist | Medium | Medium | Deep investigation scheduled for Week 1, Day 5 |

### Dependencies & Blockers

**Prediction Coordinator (Issue #1) blocks:**
- All Phase 5 prediction generation
- Tomorrow's predictions (if not fixed by 02:45 ET)

**Phase 3 Analytics (Issue #2) blocks:**
- Phase 3-6 pipeline
- Tonight's analytics (if not fixed by 02:05 ET)

**BDL Data Staleness (underlying Issue #2) blocks:**
- Reliable BDL usage
- Need to investigate root cause

---

## Section 7: Success Metrics

### Critical Fixes Success Criteria

**Issue #1 Success:**
- [ ] Prediction coordinator starts without ModuleNotFoundError
- [ ] All predictions.coordinator submodules import successfully
- [ ] Predictions generated for tomorrow's games

**Issue #2 Success:**
- [ ] Phase 3 analytics processes without stale dependency errors
- [ ] Tonight's analytics complete successfully
- [ ] Historical backfills work with backfill mode

**Issue #3 Success:**
- [ ] Cleanup processor query runs without 404 errors
- [ ] File tracking resumes normally
- [ ] No cascading orchestration failures

**Issue #4 Success:**
- [ ] Injury discovery workflow completes without import errors
- [ ] Injury report PDF parsing works
- [ ] Injury data updates normally

### Latency Monitoring Success Criteria

**Phase 0-1 Success (Current):**
- [x] Daily alerts sent at 8 AM ET
- [ ] BDL attempts table populates after first scraper run
- [ ] Dashboard queries return meaningful data
- [ ] False positive rate < 5%

**Phase 2 Success (Week 1):**
- [ ] Missing games detected within 10 minutes
- [ ] Alerts sent for incomplete data
- [ ] Completeness tracked in BigQuery
- [ ] 85%+ test coverage

**Phase 4 Success (Week 2):**
- [ ] Retry queue operational
- [ ] Auto-recovery success rate > 80%
- [ ] Missing game rate < 1%
- [ ] Manual intervention < 20%

---

## Section 8: Documentation Index

### Implementation Plans
1. `LATENCY-VISIBILITY-AND-RESOLUTION-PLAN.md` - 5-phase implementation
2. `ALL-SCRAPERS-LATENCY-EXPANSION-PLAN.md` - 33 scrapers, 4-week roadmap
3. `CRITICAL-FIXES-REQUIRED.md` - 4 critical issues to fix

### Handoff Documents
1. `2026-01-21-SCRAPER-MONITORING-HANDOFF.md` - Previous session
2. `2026-01-21-STAGING-DEPLOYED-NEXT-STEPS.md` - Staging deployment
3. `2026-01-22-LATENCY-MONITORING-DEPLOYED.md` - Latest deployment

### Monitoring Resources
1. `monitoring/daily_scraper_health.sql` - Dashboard queries
2. `orchestration/cloud_functions/scraper_availability_monitor/` - Monitor function
3. `shared/utils/bdl_availability_logger.py` - BDL logger utility

### Unit Test Files (To Create)
1. `tests/unit/monitoring/test_availability_logger.py`
2. `tests/unit/monitoring/test_scraper_monitor.py`
3. `tests/unit/orchestration/test_cleanup_processor.py`
4. `tests/unit/analytics/test_dependency_validation.py`
5. `tests/unit/validation/test_scraper_completeness_validator.py`
6. `tests/integration/test_dockerfile_builds.py`

---

## Section 9: Quick Reference Commands

### Deploy Critical Fixes
```bash
# Fix #1: Rebuild prediction coordinator
gcloud run deploy prediction-coordinator \
  --source=. \
  --dockerfile=predictions/coordinator/Dockerfile \
  --region=us-west1

# Fix #2: Run analytics with backfill mode
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-20 \
  --end-date 2026-01-20 \
  --backfill-mode

# Fix #3: Deploy cleanup processor (if separate service)
# Or: Just commit the file change

# Fix #4: Deploy raw processors
./bin/raw/deploy/deploy_processors_simple.sh
```

### Run Unit Tests
```bash
# Run all tests
pytest tests/unit/ -v

# Run specific test suite
pytest tests/unit/monitoring/ -v

# Run with coverage
pytest tests/unit/ --cov=shared --cov=orchestration --cov-report=html
```

### Check Monitoring Status
```bash
# View monitor function logs
gcloud functions logs read scraper-availability-monitor \
  --gen2 --region=us-west2 --limit=20

# Query availability data
bq query --nouse_legacy_sql "
SELECT * FROM nba_orchestration.v_scraper_availability_daily_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
ORDER BY game_date DESC
"

# Check BDL attempts
bq query --nouse_legacy_sql "
SELECT COUNT(*) as total,
       COUNTIF(was_available) as available,
       COUNTIF(NOT was_available) as missing
FROM nba_orchestration.bdl_game_scrape_attempts
WHERE game_date >= CURRENT_DATE() - 3
"
```

---

## Section 10: Contact & Escalation

### Project Ownership
- **Primary:** Data Engineering Team
- **Secondary:** MLOps Team (for prediction issues)

### Escalation Path
1. **Minor issues** - Document and fix in next sprint
2. **Blocking issues** - Fix within 24 hours
3. **Critical issues** - Fix immediately (< 4 hours)
4. **Pipeline down** - All hands, fix within 1 hour

### Status Updates
- **Daily:** Morning standup at 9 AM ET (after alert review)
- **Weekly:** Monday review meeting
- **Ad-hoc:** Slack `#nba-alerts` for critical issues

---

## Changelog

| Date | Change | Status |
|------|--------|--------|
| 2026-01-22 01:55 AM | Initial master tracker created | ✅ |
| 2026-01-22 01:55 AM | Added 4 critical issues from Jan 21 investigation | ✅ |
| 2026-01-22 01:55 AM | Added latency monitoring phases 0-5 | ✅ |
| 2026-01-22 01:55 AM | Created unit testing plan | ✅ |
| 2026-01-22 01:55 AM | Defined success metrics and timelines | ✅ |
| 2026-01-23 03:30 PM | Updated with Jan 23 session findings | ✅ |
| 2026-01-23 03:30 PM | Added Issues #5-#8 (batch processor, proxy blocking, locks, email) | ✅ |
| 2026-01-23 03:30 PM | Documented manual interventions (lock cleanup, backlog clear) | ✅ |
| 2026-01-24 01:45 AM | Added resilience improvements from Jan 23 cascade failure | ✅ |
| 2026-01-24 01:45 AM | Deployed: stale-processor-monitor, game-coverage-alert, heartbeat system | ✅ |
| 2026-01-24 01:45 AM | Integrated: soft dependencies, ESPN Pub/Sub completion | ✅ |
| 2026-01-24 02:00 AM | Created: pipeline-dashboard, auto-backfill-orchestrator Cloud Functions | ✅ |
| 2026-01-24 02:00 AM | Enabled soft deps on 3 key processors (MLFeatureStore, PlayerCompositeFactors, UpcomingPlayerGameContext) | ✅ |
| 2026-01-24 03:30 AM | Expanded cleanup processor table coverage (4 → 27 tables) | ✅ |
| 2026-01-24 03:30 AM | Increased cleanup lookback window (1h → 4h) with env var override | ✅ |
| 2026-01-24 03:30 AM | Added Pub/Sub retry logic with exponential backoff (3 attempts) | ✅ |
| 2026-01-24 03:30 AM | Improved proxy retry strategy with per-proxy backoff | ✅ |
| 2026-01-24 03:30 AM | Added phase transition handoff verification | ✅ |
| 2026-01-24 03:30 AM | Implemented DLQ monitoring via Cloud Monitoring API | ✅ |
| 2026-01-24 03:30 AM | Standardized GCP_PROJECT_ID env var across 12 files | ✅ |
| 2026-01-24 03:30 AM | Created NBAC Schedule, Injury Report, Player Boxscore validators | ✅ |
| 2026-01-24 Session 3 | Created 12 new validator configs for full raw data coverage | ✅ |
| 2026-01-24 Session 3 | Implemented nbac_gamebook_validator.py (R-009, starters, DNP) | ✅ |
| 2026-01-24 Session 3 | Implemented odds_api_props_validator.py (bookmakers, coverage, lines) | ✅ |
| 2026-01-24 Session 3 | Created v_scraper_latency_daily & v_game_data_timeline views | ✅ |
| 2026-01-24 Session 3 | Made scraper timeouts configurable in workflows.yaml | ✅ |
| 2026-01-24 Session 3 | Made cleanup processor notification threshold configurable | ✅ |
| 2026-01-24 Session 3 | Fixed timezone handling in master_controller.py (consolidated self.ET) | ✅ |
| 2026-01-24 Session 3 | Added logging failure alerting in workflow_executor.py | ✅ |

---

| 2026-01-24 Afternoon | Session 12: 5-agent deep codebase analysis completed | ✅ |
| 2026-01-24 Afternoon | Created architecture-refactoring-2026-01/ project (30K duplicate lines identified) | ✅ |
| 2026-01-24 Afternoon | Created test-coverage-improvements/ project (79 skipped tests, E2E gaps) | ✅ |
| 2026-01-24 Afternoon | Created resilience-pattern-gaps/ project (5 processors missing upstream checks) | ✅ |
| 2026-01-24 Afternoon | Created SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md (consolidated improvement plan) | ✅ |
| 2026-01-24 Session 13 | Fixed Phase 5 worker scaling: 10→50 max instances (was 32% failure rate) | ✅ |
| 2026-01-24 Session 13 | Fixed CatBoost V8 model path: deploy script now sets default GCS path | ✅ |
| 2026-01-24 Session 13 | Fixed proxy security: removed hardcoded ProxyFuel credentials from source | ✅ |
| 2026-01-24 Session 13 | Fixed WAF detection: changed User-Agent from "NBA-Stats-Scraper" to Chrome UA | ✅ |
| 2026-01-24 Session 13 | Fixed Cloud Logging TODOs: R-006/R-008 alerts now query actual log data | ✅ |
| 2026-01-24 Session 13 | Fixed 5 precompute processors: added get_upstream_data_check_query() to all | ✅ |
| 2026-01-24 Session 13 | Processors fixed: ml_feature_store, player_daily_cache, player_composite_factors, player_shot_zone_analysis, team_defense_zone_analysis | ✅ |

| 2026-01-25 Session 15 | Deployed phase3-to-phase4 orchestrator (512MB, fixed imports) | ✅ |
| 2026-01-25 Session 15 | Deployed phase4-to-phase5 orchestrator (512MB, fixed imports) | ✅ |
| 2026-01-25 Session 15 | Deployed phase5-to-phase6 orchestrator (512MB, fixed imports) | ✅ |
| 2026-01-25 Session 15 | Fixed Cloud Function validation __init__.py (all CFs) - removed historical_completeness import | ✅ |
| 2026-01-25 Session 15 | Created nba_orchestration.failed_processor_queue BigQuery table | ✅ |
| 2026-01-25 Session 15 | Created nba_orchestration.pipeline_event_log BigQuery table | ✅ |
| 2026-01-25 Session 15 | Created shared/utils/pipeline_logger.py for event logging | ✅ |
| 2026-01-25 Session 15 | Created and deployed auto-retry-processor Cloud Function | ✅ |
| 2026-01-25 Session 15 | Created Cloud Scheduler job (every 15 min) for auto-retry | ✅ |

---

**Last Updated:** January 25, 2026 (Session 15)
**Next Update:** As needed
**Status:** 🟢 Pipeline Resilience Phase 1 Complete
