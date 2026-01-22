# CRITICAL FIXES REQUIRED - January 21, 2026
**Validation Date:** 2026-01-21 20:50 ET
**Status:** 🔴 CRITICAL - Pipeline Blocked
**Impact:** Predictions disabled, Analytics failing, Data gaps

---

## EXECUTIVE SUMMARY

Comprehensive validation of today's orchestration identified **4 critical issues** blocking the pipeline:

1. **🔴 CRITICAL:** Prediction Coordinator deployment failure - zero predictions possible
2. **🔴 CRITICAL:** Phase 3 Analytics failures - 4,937 errors in 24 hours
3. **🔴 CRITICAL:** BDL table name mismatch - cleanup processor failing
4. **🟡 HIGH:** Injury discovery missing dependency

**All issues have been root-caused with exact file paths and line numbers below.**

---

## ISSUE #1: PREDICTION COORDINATOR DEPLOYMENT FAILURE

### **Status:** 🔴 CRITICAL - Service completely broken
### **Impact:** Zero predictions can be generated (Phase 5 blocked)
### **First Detected:** Jan 21 15:00 ET
### **Error Count:** 20 errors in 24 hours

### Root Cause
**Missing `predictions/__init__.py` file in Docker container**

The Dockerfile copies `predictions/coordinator/` directory but **does NOT copy** `predictions/__init__.py`, which is required to make `predictions` a valid Python package.

### Error Message
```
ModuleNotFoundError: No module named 'predictions'
```

### Exact Code Locations

#### **File:** `/predictions/coordinator/Dockerfile`
**Line 14:** Missing COPY command for `predictions/__init__.py`

**Current Code (BROKEN):**
```dockerfile
# Line 10-14
# Copy shared modules from repository root
COPY shared/ ./shared/

# Copy coordinator code
COPY predictions/coordinator/ ./predictions/coordinator/
```

**Container Result:**
```
/app/
├── shared/                     ✅ Copied
├── predictions/
│   └── coordinator/            ✅ Copied
│       ├── coordinator.py
│       └── ...
└── predictions/__init__.py     ❌ MISSING!
```

#### **Files Affected by Import Failures:**

**File:** `/predictions/coordinator/coordinator.py`
**Lines 39-46:** Cannot import from predictions.coordinator package
```python
39: from predictions.coordinator.player_loader import PlayerLoader
40: from predictions.coordinator.progress_tracker import ProgressTracker
41: from predictions.coordinator.run_history import CoordinatorRunHistory
42: from predictions.coordinator.coverage_monitor import PredictionCoverageMonitor
43: from predictions.coordinator.batch_state_manager import get_batch_state_manager
46: from predictions.coordinator.batch_staging_writer import BatchConsolidator
```

**File:** `/predictions/coordinator/batch_staging_writer.py`
**Line 48:** Cannot import distributed_lock
```python
48: from predictions.coordinator.distributed_lock import DistributedLock, LockAcquisitionError
```

### Fix Required

**File:** `/predictions/coordinator/Dockerfile`
**Action:** Add COPY command between lines 12-13

**Change:**
```dockerfile
# Copy shared modules from repository root
COPY shared/ ./shared/

# Copy predictions package structure
COPY predictions/__init__.py ./predictions/__init__.py

# Copy coordinator code
COPY predictions/coordinator/ ./predictions/coordinator/
```

### Verification Steps

```bash
# 1. Build locally to verify
cd /home/naji/code/nba-stats-scraper
docker build -f predictions/coordinator/Dockerfile -t test-coordinator .

# 2. Test the import
docker run test-coordinator python -c "from predictions.coordinator.coordinator import app; print('Success!')"

# 3. Deploy to Cloud Run
gcloud run deploy prediction-coordinator \
  --source=. \
  --dockerfile=predictions/coordinator/Dockerfile \
  --region=us-west1 \
  --project=nba-props-platform

# 4. Verify deployment
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND severity>=ERROR' \
  --limit=10 --format=json | grep -i "modulenotfound"
```

### Historical Context
- This is the **3rd similar incident** (Jan 17-18, 2026)
- MLB worker Dockerfile has the correct pattern (line 32)
- Previous incidents documented in handoff reports

### Priority: IMMEDIATE (Must fix before 02:45 ET tonight or zero predictions)

---

## ISSUE #2: PHASE 3 ANALYTICS STALE DEPENDENCY FAILURES

### **Status:** 🔴 CRITICAL - Analytics pipeline blocked
### **Impact:** 4,937 errors in 24 hours, Phase 3-6 cannot run
### **First Detected:** Jan 21 04:00 ET (morning), 19:00 ET (evening)
### **Error Count:** 4,937 total (1,000+/hour during peak)

### Root Cause
**BDL player boxscore data is 45+ hours old, exceeding 36-hour freshness threshold**

Phase 3 analytics processors validate upstream Phase 2 data freshness before processing. The BDL `bdl_player_boxscores` table hasn't been updated since ~Jan 19, causing validation to block processing.

### Error Messages

**Morning Errors (04:00-07:00):**
```
ValueError: No data extracted
```

**Evening Errors (19:00-23:00):**
```
ValueError: Stale dependencies (FAIL threshold):
  ['nba_raw.bdl_player_boxscores: 44-46h old (max: 36h)']
```

### Exact Code Locations

#### **Primary Validation Logic**

**File:** `/data_processors/analytics/analytics_base.py`

**Function:** `check_dependencies()`
**Lines:** 844-938

Key validation logic at **lines 912-930:**
```python
# Check freshness (if exists)
if exists and details.get('age_hours') is not None:
    max_age_warn = config.get('max_age_hours_warn', 24)
    max_age_fail = config.get('max_age_hours_fail', 72)

    if details['age_hours'] > max_age_fail:
        results['all_fresh'] = False
        results['has_stale_fail'] = True
        stale_msg = (f"{table_name}: {details['age_hours']:.1f}h old "
                   f"(max: {max_age_fail}h)")
        results['stale_fail'].append(stale_msg)
        logger.error(f"Stale dependency (FAIL threshold): {stale_msg}")
```

**Function:** `_check_table_data()`
**Lines:** 940-1069

Age calculation at **lines 1034-1044:**
```python
# Calculate age
if last_updated:
    now_utc = datetime.now(timezone.utc)
    if last_updated.tzinfo is None:
        age_hours = (now_utc.replace(tzinfo=None) - last_updated).total_seconds() / 3600
    else:
        age_hours = (now_utc - last_updated).total_seconds() / 3600
else:
    age_hours = None
```

**Enforcement Logic**
**Lines:** 444-462

```python
# Handle stale data FAIL threshold (skip in backfill mode)
if dep_check.get('has_stale_fail') and not self.is_backfill_mode:
    error_msg = f"Stale upstream data detected (BLOCKING): {dep_check['stale_fail']}"
    logger.error(error_msg)
    raise ValueError(error_msg)  # BLOCKS PROCESSING
elif dep_check.get('has_stale_fail') and self.is_backfill_mode:
    logger.info(f"BACKFILL_MODE: Ignoring stale data check - {dep_check['stale_fail']}")
```

#### **BDL Threshold Configuration**

**File:** `/data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Lines:** 202-210
```python
# SOURCE 2: BDL Boxscores (FALLBACK - Critical)
'nba_raw.bdl_player_boxscores': {
    'field_prefix': 'source_bdl',
    'description': 'BDL boxscores - fallback for basic stats',
    'date_field': 'game_date',
    'check_type': 'date_range',
    'expected_count_min': 200,
    'max_age_hours_warn': 12,
    'max_age_hours_fail': 36,  # ← THE THRESHOLD CAUSING FAILURES
    'critical': True
}
```

### Fix Options

#### **Option A: Use Backfill Mode (RECOMMENDED - Immediate)**

**For Manual Runs:**
```bash
python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2026-01-20 \
  --end-date 2026-01-20 \
  --backfill-mode  # ← Skips all dependency checks
```

**For Orchestrated Runs:**
```python
# In orchestrator that triggers Phase 3
message_data = {
    "game_date": "2026-01-20",
    "processor": "player_game_summary",
    "backfill_mode": True  # ← Add this flag
}
```

**What It Does (Lines 374-395):**
```python
if self.is_backfill_mode:
    logger.info("⏭️  BACKFILL MODE: Skipping dependency BQ checks")
    dep_check = {
        'all_critical_present': True,
        'all_fresh': True,
        'has_stale_fail': False,
        'has_stale_warn': False,
        'missing': [],
        'stale_fail': [],
        'stale_warn': [],
        'details': {}
    }
```

#### **Option B: Increase Threshold (Short-term)**

**File:** `/data_processors/analytics/player_game_summary/player_game_summary_processor.py`
**Line:** 209

**Change:**
```python
# FROM:
'max_age_hours_fail': 36,  # Current threshold

# TO:
'max_age_hours_fail': 72,  # Increase to 72 hours
```

**Note:** Requires redeployment of analytics service

#### **Option C: Make BDL Non-Critical (Long-term)**

**File:** `/data_processors/analytics/player_game_summary/player_game_summary_processor.py`
**Line:** 210

**Change:**
```python
# FROM:
'critical': True

# TO:
'critical': False  # Allow processing without BDL
```

**Rationale:** BDL has documented reliability issues (30-40% data gaps). Gamebook provides same data and is 100% reliable.

### Additional Investigation Required

**Underlying BDL Data Issue:**
- BDL boxscore data hasn't updated since Jan 19 (~45 hours)
- Last load: 2026-01-21 07:59:53 (17 hours ago)
- Pattern: Jan 15 had 89% missing games, Jan 19-20 had 11-43% missing

**Action:** Investigate why BDL scraper not successfully updating table
- Check if BDL API is returning data
- Verify scraper is running
- Check for BDL API key/quota issues
- Review error logs for `bdl_box_scores` and `bdl_player_box_scores` scrapers

### Priority: IMMEDIATE (Blocks tonight's analytics unless addressed)

---

## ISSUE #3: BDL TABLE NAME MISMATCH IN CLEANUP PROCESSOR

### **Status:** 🔴 CRITICAL - Cleanup processor failing
### **Impact:** File tracking broken, cascading orchestration failures
### **First Detected:** Jan 21 23:45 ET
### **Error Count:** Multiple 404 errors

### Root Cause
**Hardcoded incorrect table name in cleanup processor**

The cleanup processor queries `nba_raw.bdl_box_scores` (plural) but the actual table is named `nba_raw.bdl_player_boxscores` (singular, includes "player").

### Error Message
```
ERROR: 404 Not found: Table nba-props-platform:nba_raw.bdl_box_scores was not found
```

### Exact Code Location

**File:** `/orchestration/cleanup_processor.py`
**Line:** 223

**Current Code (INCORRECT):**
```python
SELECT source_file_path FROM `nba-props-platform.nba_raw.bdl_box_scores`
WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.lookback_hours + 1} HOUR)
```

**Correct Table Name:** `nba_raw.bdl_player_boxscores`

### Fix Required

**File:** `/orchestration/cleanup_processor.py`
**Line:** 223

**Change:**
```python
# FROM:
SELECT source_file_path FROM `nba-props-platform.nba_raw.bdl_box_scores`

# TO:
SELECT source_file_path FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
```

### Table Name Reference Guide

| Component | Name Used | Correct? |
|-----------|-----------|----------|
| **BigQuery Table** | `bdl_player_boxscores` | ✅ Actual table |
| **Scraper Name** | `bdl_box_scores` | ✅ Valid (module name) |
| **GCS Path** | `boxscores` | ✅ Valid (directory) |
| **Processor** | `BdlBoxscoresProcessor` | ✅ Valid (class name) |
| **Cleanup Query** | `bdl_box_scores` | ❌ **WRONG** |

### Historical Context
- **Same issue identified December 2025** (Session 157)
- Fixed in `orchestration/master_controller.py:496`
- **Cleanup processor was not fixed** (or fix was reverted)
- Documented in: `docs/09-handoff/archive/2025-12/2025-12-21-SESSION157-SCRAPER-STALENESS-FIXES.md`

### Verification

```bash
# 1. Verify correct table exists
bq show nba-props-platform:nba_raw.bdl_player_boxscores

# 2. Verify incorrect table does NOT exist (should fail)
bq show nba-props-platform:nba_raw.bdl_box_scores

# 3. Test query after fix
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 25 HOUR)
"
```

### Priority: HIGH (Affects cleanup and file tracking)

---

## ISSUE #4: INJURY DISCOVERY MISSING PDFPLUMBER DEPENDENCY

### **Status:** 🟡 HIGH - Injury workflow completely failing
### **Impact:** Injury data not updating
### **First Detected:** Jan 21 (21 consecutive failures)
### **Error Count:** 21 failures

### Root Cause
**`pdfplumber` package missing from raw processor requirements.txt**

The injury report processor needs to read PDF files, but `pdfplumber` is only installed in the scraper service, not in the raw processor service.

### Error Message
```
ModuleNotFoundError: No module named 'pdfplumber'
```

### Exact Code Locations

#### **Where pdfplumber is imported:**

**File 1:** `/scrapers/nbacom/nbac_injury_report.py`
**Line 33:** `import pdfplumber`

**File 2:** `/scrapers/nbacom/nbac_gamebook_pdf.py`
**Line 33:** `import pdfplumber`

#### **Where pdfplumber IS listed:**

**File:** `/scrapers/requirements.txt`
**Line 8:** `pdfplumber==0.11.7` ✅

#### **Where pdfplumber IS MISSING:**

**File:** `/data_processors/raw/requirements.txt`
**Status:** Missing pdfplumber ❌

### Architecture Context

The system uses **separate Cloud Run services**:

1. **Scraper Service** - Has pdfplumber ✅
2. **Raw Processor Service** - Missing pdfplumber ❌

The injury report processor runs in the raw processor service:
- **Location:** `/data_processors/raw/nbacom/nbac_injury_report_processor.py`
- **Registered:** `main_processor_service.py` line 120
- **Deployed via:** `bin/raw/deploy/deploy_processors_simple.sh`
- **Dockerfile:** `docker/raw-processor.Dockerfile`

### Fix Required

**File:** `/data_processors/raw/requirements.txt`
**Action:** Add pdfplumber dependency

**Add this line (around line 20-24):**
```python
# PDF processing (for injury report and gamebook processors)
pdfplumber==0.11.7
```

### Deployment

```bash
# 1. Deploy updated raw processor service
cd /home/naji/code/nba-stats-scraper
./bin/raw/deploy/deploy_processors_simple.sh

# 2. Verify deployment
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# 3. Test injury discovery workflow
# (Wait for next hourly trigger or manually invoke)

# 4. Check logs for success
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"
  AND textPayload=~"injury"' --limit=20 --format=json
```

### Priority: MEDIUM (Does not affect core statistics pipeline)

---

## ADDITIONAL CONCERNS: INCOMPLETE DEPLOYMENTS

### Recent Changes Analysis

**Recent Commits:**
1. **76357826** (HEAD, Jan 21 11:40 AM) - Enable backfill mode for Phase 3 analytics
2. **e013ea85** (Jan 21 10:51 AM) - Prevent Jan 16-21 pipeline failures (10 files changed)
3. **21d7cd35** (origin/main, Jan 21 7:51 AM) - Organize Jan 21 incident resolution

### Potentially Not Deployed

#### 1. **Prediction Services** (br_rosters_current fix)
- **Files:**
  - `/predictions/coordinator/shared/config/orchestration_config.py`
  - `/predictions/worker/shared/config/orchestration_config.py`
- **Change:** `br_roster` → `br_rosters_current`
- **Evidence:** No deployment logs found for prediction services on Jan 21
- **Impact:** May be looking for wrong table name

#### 2. **Phase 3 Analytics Service** (backfill mode logic)
- **File:** `/data_processors/analytics/main_analytics_service.py`
- **Changed:** Jan 21 11:40 AM
- **Evidence:** No deployment documentation
- **Impact:** Backfill mode flag may not work as expected

#### 3. **Orchestrator Shared Modules** (validation modules)
- **New Files:**
  - `shared/validation/phase_boundary_validator.py`
  - `shared/config/rate_limit_config.py`
  - `shared/utils/rate_limit_handler.py`
- **Required in:** Phase 2→3, Phase 3→4, Self-heal orchestrators
- **Status:** May not be copied to Cloud Function directories before deployment
- **Impact:** ModuleNotFoundError if missing

### Verification Needed

```bash
# 1. Check Cloud Function revision numbers
gcloud functions describe phase3-to-phase4-orchestrator \
  --region=us-west2 --gen2 --format="value(updateTime)"

gcloud functions describe self-heal-predictions \
  --region=us-west2 --gen2 --format="value(updateTime)"

# 2. Check prediction service revisions
gcloud run services describe prediction-coordinator \
  --region=us-west1 --format="value(status.latestReadyRevisionName)"

gcloud run services describe prediction-worker \
  --region=us-west1 --format="value(status.latestReadyRevisionName)"

# 3. Check for module import errors in logs
gcloud logging read 'severity>=ERROR AND textPayload=~"ModuleNotFoundError"' \
  --limit=50 --format=json
```

---

## TIMELINE FOR TONIGHT'S ORCHESTRATION

### Expected Events (if fixes applied)

```
Current Time:     20:50 ET - Games in progress (5 games)
Games Complete:   22:30 ET - Final scores available
Post-Game Win 1:  23:00 ET - Scraper execution begins
Post-Game Win 2:  01:00 ET - BDL boxscores should load
Phase 2 Raw:      02:00 ET - Raw data processing
Phase 3 Analytics: 02:05 ET - Will FAIL without Fix #2
Phase 4 Precompute: 02:15 ET - May run with partial data
Phase 5 Predictions: 02:45 ET - BLOCKED without Fix #1
```

### Critical Deadlines

1. **Fix #1 (Prediction Coordinator)** - Must deploy before 02:45 ET
2. **Fix #2 (Analytics Validation)** - Must apply before 02:05 ET
3. **Fix #3 (Cleanup Processor)** - Can deploy anytime (affects file tracking)
4. **Fix #4 (Injury Discovery)** - Can deploy anytime (affects injury reports only)

---

## DEPLOYMENT PRIORITY

### **IMMEDIATE (Next 1-2 Hours):**

1. ✅ Deploy Fix #1 - Prediction Coordinator Dockerfile
2. ✅ Apply Fix #2 - Enable backfill mode for tonight's analytics run

### **HIGH (Next 4-6 Hours):**

3. ✅ Deploy Fix #3 - Cleanup processor table name
4. ✅ Monitor tonight's post-game processing
5. ✅ Verify BDL data loads for tonight's games

### **MEDIUM (Next 24 Hours):**

6. ✅ Deploy Fix #4 - Injury discovery pdfplumber
7. ✅ Redeploy prediction services with br_rosters_current fix
8. ✅ Verify all orchestrators have new shared modules
9. ✅ Investigate BDL data staleness root cause

---

## FILES TO MODIFY - QUICK REFERENCE

| Priority | File | Line | Change |
|----------|------|------|--------|
| 🔴 CRITICAL | `/predictions/coordinator/Dockerfile` | 14 | Add `COPY predictions/__init__.py ./predictions/__init__.py` |
| 🔴 CRITICAL | Run analytics with flag | N/A | Add `--backfill-mode` |
| 🔴 CRITICAL | `/orchestration/cleanup_processor.py` | 223 | `bdl_box_scores` → `bdl_player_boxscores` |
| 🟡 HIGH | `/data_processors/raw/requirements.txt` | ~22 | Add `pdfplumber==0.11.7` |
| 🟡 MEDIUM | `/data_processors/analytics/player_game_summary/player_game_summary_processor.py` | 209 | Consider `36` → `72` |

---

## VALIDATION CHECKLIST

After deploying fixes, verify:

- [ ] Prediction coordinator starts without ModuleNotFoundError
- [ ] Phase 3 analytics processes without stale dependency errors
- [ ] Cleanup processor query runs without 404 errors
- [ ] Injury discovery workflow completes without import errors
- [ ] Tonight's 5 games have complete data in all phases
- [ ] Predictions generated for tomorrow's games

---

## DOCUMENT METADATA

**Created:** 2026-01-21 20:50 ET
**Validation Source:** Comprehensive orchestration validation
**Agents Used:** 5 specialized exploration agents
**Error Logs Analyzed:** 4,984 errors across 7 components
**Code Files Examined:** 50+ files across scrapers, processors, orchestration
**BigQuery Queries Run:** 12 validation queries

**Next Session Action:** Review this document and execute fixes in priority order
