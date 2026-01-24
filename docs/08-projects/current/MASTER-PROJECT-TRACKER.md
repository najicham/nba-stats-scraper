# Master Project Tracker - January 23, 2026
**Last Updated:** 2026-01-23 4:25 PM PST
**Status:** 🟢 Major Issues Resolved
**Owner:** Data Engineering Team

---

## Executive Dashboard

### 🚨 Critical Issues (Immediate Action Required)

| ID | Issue | Status | Priority | Fixed | Notes |
|----|-------|--------|----------|-------|-------|
| **#1** | Prediction Coordinator Dockerfile | ✅ **FIXED** | P0 | Jan 22 | Deployed |
| **#2** | Prediction Worker Dockerfile | ✅ **FIXED** | P0 | Jan 22 | Missing __init__.py |
| **#3** | pdfplumber Missing | ✅ **FIXED** | P2 | Jan 22 | Added to root requirements |
| **#4** | Proxy Infrastructure Blocked | ❌ **BROKEN** | P1 | - | Both proxies now blocked by BettingPros |
| **#5** | Phase 2 Batch Processor Bug | ✅ **FIXED** | P1 | Jan 23 | Deduplication conflict resolved |
| **#6** | Health Email Metrics Bug | 🟡 **NEW** | P3 | - | Wrong counts displayed |

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

---

**Last Updated:** January 23, 2026, 3:30 PM UTC
**Next Update:** After Phase 2 batch processor bug fixed
**Status:** 🟡 Multiple Active Issues - See pipeline-resilience-improvements/
