# Complete Handoff - January 1, 2026 Session

**Date**: January 1, 2026, 1:00 AM - 11:00 AM PST (11 hours)
**Status**: ✅ ALL SYSTEMS OPERATIONAL - Ready for next session
**Session Type**: Critical production fixes + P0 orchestration issues
**Outcome**: SUCCESS - All objectives achieved, systems verified

---

## 🎯 Executive Summary

### What Was Accomplished

**4 Major Fixes Deployed:**
1. ✅ **Injury Data Pipeline** - Restored automatic processing (9-day outage resolved)
2. ✅ **Cleanup Processor** - Fixed datetime serialization in BigQuery logging
3. ✅ **Phase 4→5 Timeout** - Verified comprehensive timeouts already exist
4. ✅ **Batch Loader** - Confirmed 331x speedup (deployed Dec 31, already in prod)

**Production Deployments:**
- `nba-scrapers`: revision `00087-mgr` (injury fix)
- `nba-phase1-scrapers`: revision `00066-tx5` (cleanup processor fix)

**Documentation Created:**
- 1400+ lines across 4 comprehensive documents
- All committed to git and pushed to `main`

**Current State:**
- ✅ All automatic pipelines operational
- ✅ Self-healing system working correctly
- ✅ End-to-end verification complete
- ✅ No outstanding critical issues

---

## 📋 Table of Contents

1. [Critical Context](#critical-context)
2. [What's Deployed & Verified](#whats-deployed--verified)
3. [System Health Status](#system-health-status)
4. [Monitoring & Verification Commands](#monitoring--verification-commands)
5. [Optional Tasks (Backfill)](#optional-tasks-backfill)
6. [Next Session Priorities](#next-session-priorities)
7. [Important Files & Locations](#important-files--locations)
8. [Key Decisions Made](#key-decisions-made)
9. [Common Commands Reference](#common-commands-reference)
10. [Troubleshooting Guide](#troubleshooting-guide)

---

## 🔥 Critical Context

### Starting Point (What Was Broken)

**Issue #1: Injury Data Pipeline (CRITICAL)**
- **Problem**: Automatic pipeline broken since Dec 23, 2025 (9 days)
- **Symptom**: Scraper published PDF path to Pub/Sub instead of JSON path
- **Impact**: Phase 2 processor couldn't handle PDF paths, no data reached BigQuery
- **Source**: Original handoff doc: `2026-01-01-INJURY-FIX-HANDOFF.md`

**Issue #2: Cleanup Processor Logging (P0-ORCH-1)**
- **Problem**: DateTime serialization error when logging to BigQuery
- **Symptom**: `ERROR: Object of type datetime is not JSON serializable`
- **Impact**: Cleanup operations not tracked in BigQuery (core functionality still worked)

**Issue #3: Phase 4→5 Timeout (P0-ORCH-2)**
- **Problem**: Listed as missing timeout
- **Actual**: Timeouts already exist (issue was mislabeled or already fixed)

**Issue #4: Batch Loader (Quick Win #7)**
- **Problem**: Listed as "wire up batch loader for 50x speedup"
- **Actual**: Already deployed Dec 31, achieving 331x speedup

---

## ✅ What's Deployed & Verified

### 1. Injury Data Pipeline Fix

**File Changed**: `scrapers/nbacom/nbac_injury_report.py` (lines 86-100)

**What Was Fixed**:
```python
# BEFORE (broken):
exporters = [
    {"type": "gcs", "key": "...injury_report_pdf_raw", ...},     # PDF first ❌
    {"type": "gcs", "key": "...injury_report_data", ...},        # JSON second
]

# AFTER (fixed):
# NOTE: Order matters! First GCS exporter's path is published to Pub/Sub for Phase 2.
exporters = [
    {"type": "gcs", "key": "...injury_report_data", ...},  # PRIMARY: JSON for Phase 2 ✅
    {"type": "gcs", "key": "...injury_report_pdf_raw", ...},  # SECONDARY: PDF archive
]
```

**Why This Works**:
- `scraper_base.py` (lines 1697-1707) captures only the FIRST GCS exporter's path
- This path is published to Pub/Sub for Phase 2 processors
- By putting JSON first, correct path is published
- PDF is still created for archival (just not published to Pub/Sub)

**Deployed**: `nba-scrapers` revision `00087-mgr`

**Verification (End-to-End Test - 9:17 AM PST)**:
```
✅ Scraper executed: 65 records retrieved
✅ JSON path published: gs://.../injury-report-data/.../20260101_171743.json
✅ Processor received: JSON file (not PDF)
✅ BigQuery updated: 325 records for 2026-01-01
✅ Latest scrape: 17-17-43 (matches test run)
```

**Log Evidence**:
```
INFO:scraper_base:Captured gcs_output_path:
  gs://nba-scraped-data/nba-com/injury-report-data/2026-01-01/09/20260101_171743.json

INFO:data_processors.raw.main_processor_service:✅ Successfully processed
  nba-com/injury-report-data/2026-01-01/09/20260101_171743.json
```

**Commits**:
- `442d404`: Code fix (exporter reordering)
- `b36763e`: Initial documentation
- `747547f`: Test results documentation

---

### 2. Cleanup Processor Fix

**File Changed**: `orchestration/cleanup_processor.py` (lines 321-337)

**What Was Fixed**:
```python
# BEFORE (broken):
missing_files_records.append({
    'triggered_at': f['triggered_at'],  # ❌ datetime object, not JSON serializable
})

# AFTER (fixed):
triggered_at = f['triggered_at']
if hasattr(triggered_at, 'isoformat'):
    triggered_at = triggered_at.isoformat()  # ✅ Convert to ISO string
elif not isinstance(triggered_at, str):
    triggered_at = str(triggered_at)

missing_files_records.append({
    'triggered_at': triggered_at,  # ✅ Now JSON serializable
})
```

**Why This Matters**:
- Cleanup processor runs every 15 minutes (Cloud Scheduler)
- Finds files that Phase 2 didn't process
- Republishes them to Pub/Sub (self-healing)
- Logs operations to BigQuery for tracking
- Bug prevented logging, but core republishing still worked

**Deployed**: `nba-phase1-scrapers` revision `00066-tx5`

**Verification (10:30 AM & 10:45 AM runs)**:
```bash
# BEFORE fix (10:15 AM run):
ERROR:shared.utils.bigquery_utils:Failed to insert rows into
nba_orchestration.cleanup_operations: Object of type datetime is not JSON serializable

# AFTER fix (10:30 AM run):
✅ Logged cleanup operation to BigQuery  # ← NO ERROR!
✅ No files to check, cleanup complete

# AFTER fix (10:45 AM run):
✅ Logged cleanup operation to BigQuery  # ← STILL WORKING!
✅ No files to check, cleanup complete
```

**Commits**:
- `d88f38d`: Cleanup processor datetime fix
- `af6e20e`: (deployment commit with fix)

---

### 3. Phase 4→5 Timeout Verification

**File**: `orchestration/cloud_functions/phase4_to_phase5/main.py`

**What Was Found**:
- **NO CHANGES NEEDED** - Comprehensive timeouts already exist

**Existing Timeouts**:
1. **Pub/Sub publish**: 10 second timeout (line 362)
   ```python
   message_id = future.result(timeout=10.0)
   ```

2. **HTTP requests**: 30 second timeout (line 416)
   ```python
   response = requests.post(url, json=payload, headers=headers, timeout=30)
   ```

3. **Processor completion wait**: 4 hour timeout (lines 51-52, 288-312)
   ```python
   MAX_WAIT_HOURS = 4
   MAX_WAIT_SECONDS = MAX_WAIT_HOURS * 3600

   if wait_seconds > MAX_WAIT_SECONDS:
       logger.warning("TIMEOUT: Waited {wait_seconds/3600:.1f} hours...")
       # Triggers Phase 5 with partial data (prevents freeze)
   ```

**Conclusion**: Issue was mislabeled or already fixed. No action needed.

---

### 4. Batch Loader Verification

**Status**: Already deployed December 31, 2025

**Performance**:
- **Before**: 225 seconds for 118 players (sequential queries)
- **After**: 0.68 seconds for 118 players (single batch query)
- **Speedup**: 331x (exceeded 50x expectation by 6.6x!)

**Documentation**: `BATCH-LOADER-VERIFICATION.md`

**Verification (Dec 31, 22:03 UTC)**:
```
🚀 Pre-loading started:  22:03:30.256
✅ Batch loaded complete: 22:03:30.935
Duration: 0.68 seconds
Players: 118
Workers using batch data: 100%
Individual queries from workers: 0
```

**Conclusion**: Already in production and working perfectly. No action needed.

---

## 🏥 System Health Status

### Production Services (All Healthy ✅)

| Service | Revision | Deployed | Status | Purpose |
|---------|----------|----------|--------|---------|
| `nba-scrapers` | 00087-mgr | Jan 1, 10:16 AM | ✅ Running | Phase 1 scraper execution |
| `nba-phase1-scrapers` | 00066-tx5 | Jan 1, 10:16 AM | ✅ Running | Phase 1 orchestration + cleanup |
| `nba-phase2-raw-processors` | (not changed) | - | ✅ Running | Phase 2 raw data processing |
| `prediction-coordinator` | (not changed) | - | ✅ Running | Phase 5 predictions |

### Automated Workflows (All Operational ✅)

| Workflow | Schedule | Status | Last Verified |
|----------|----------|--------|---------------|
| `execute-workflows` | Every hour at :05 | ✅ Active | Jan 1, 10:00 AM |
| `cleanup-processor` | Every 15 minutes | ✅ Active | Jan 1, 10:45 AM |
| `injury_discovery` | Discovery mode (learned timing) | ✅ Active | Skips outside window (expected) |

### Data Pipelines (All Flowing ✅)

| Pipeline | Status | Last Successful | Notes |
|----------|--------|-----------------|-------|
| Injury Data | ✅ Automatic | Jan 1, 2026 (455 records) | Fixed and verified |
| Other Scrapers | ✅ Automatic | Ongoing | Not affected by injury fix |
| Phase 2 Processing | ✅ Automatic | Ongoing | Working correctly |
| Predictions | ✅ Automatic | Ongoing | 331x speedup active |

---

## 📊 Monitoring & Verification Commands

### Check Injury Data Pipeline Health

**1. Verify scraper is publishing JSON path (not PDF)**:
```bash
# Check recent scraper logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-scrapers"' \
  --limit=50 --freshness=2h --format="value(textPayload)" | grep "gcs_output_path"

# Should see:
# INFO:scraper_base:Captured gcs_output_path: gs://.../injury-report-data/.../json
# NOT: gs://.../injury-report-pdf/.../pdf
```

**2. Check BigQuery for recent injury data**:
```bash
bq query --nouse_legacy_sql \
  "SELECT
    report_date,
    COUNT(*) as records,
    MAX(scrape_time) as latest_scrape
   FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
   WHERE report_date >= CURRENT_DATE() - 7
   GROUP BY report_date
   ORDER BY report_date DESC"

# Should see records for recent dates
```

**3. Monitor injury workflow execution**:
```bash
# Check when injury_discovery workflow was evaluated
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=100 --freshness=6h --format="value(textPayload)" | grep "injury_discovery"

# Expected behavior:
# - SKIP outside time window (21:00 ±30min) - THIS IS NORMAL
# - RUN during publication window (11 AM - 3 PM PT)
```

### Check Cleanup Processor Health

**1. Verify cleanup processor is running**:
```bash
# Should run every 15 minutes
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=50 --freshness=30m --format="value(textPayload)" | grep "cleanup"

# Should see (every 15 min):
# INFO:orchestration.cleanup_processor:🔧 Cleanup Processor: Starting self-healing check
# INFO:orchestration.cleanup_processor:✅ Logged cleanup operation to BigQuery
# (NO datetime serialization errors)
```

**2. Check if cleanup is republishing any files**:
```bash
# Look for republish messages
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=100 --freshness=1h --format="value(textPayload)" | grep "Republished"

# If cleanup is republishing:
# INFO:orchestration.cleanup_processor:🔄 Republished <scraper_name> to Pub/Sub

# If no files need republishing:
# INFO:orchestration.cleanup_processor:✅ No files to check, cleanup complete
```

**3. Query BigQuery cleanup operations log**:
```bash
bq query --nouse_legacy_sql \
  "SELECT
    cleanup_id,
    cleanup_time,
    files_checked,
    missing_files_found,
    republished_count
   FROM \`nba-props-platform.nba_orchestration.cleanup_operations\`
   WHERE cleanup_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
   ORDER BY cleanup_time DESC
   LIMIT 20"

# Should show cleanup operations logging successfully
```

### Check Overall Pipeline Health

**1. Quick health check script**:
```bash
./bin/monitoring/daily_health_check.sh
# Or the comprehensive one:
./bin/monitoring/check_pipeline_health.sh
```

**2. Manual comprehensive check**:
```bash
# Check predictions are being generated
bq query --nouse_legacy_sql \
  "SELECT game_date, COUNT(DISTINCT player_lookup) as players
   FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
   WHERE game_date >= CURRENT_DATE('America/New_York')
   GROUP BY game_date
   ORDER BY game_date"

# Check processor run history
bq query --nouse_legacy_sql \
  "SELECT processor_name, status, COUNT(*) as runs
   FROM \`nba-props-platform.nba_orchestration.processor_run_history\`
   WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
   GROUP BY processor_name, status
   ORDER BY processor_name, status"
```

---

## 🔄 Optional Tasks (Backfill)

### Injury Data Backfill (Dec 23-31, 2025)

**Status**: ⏸️ **OPTIONAL - Low Priority**

**Background**:
- Gap: Dec 23-31, 2025 (9 days)
- Last successful before break: Dec 22, 2025 (529 records)
- First successful after fix: Jan 1, 2026 (455 records)

**Investigation Results**:
```bash
# GCS files exist but are EMPTY
gsutil cat "gs://nba-scraped-data/nba-com/injury-report-data/2025-12-23/19/20251224_000508.json" | jq

# Returns:
# {
#   "metadata": {
#     "is_empty_report": true,
#     "no_data_reason": "pdf_unavailable"
#   },
#   "records": []
# }
```

**Why Empty**:
1. Scraper was broken (publishing PDF path, not JSON path to Pub/Sub)
2. Discovery mode tried to find data at various hours (1 AM, 4 AM, 7 AM, etc.)
3. NBA.com publishes injury reports ~11 AM - 3 PM ET
4. Scraper got "PDF unavailable" errors
5. Even if data was available later, Pub/Sub wasn't working (wrong path)

**Impact Assessment**:
- **Predictions**: LOW impact (models use recent 30-60 days, missing 9/60 = 15%)
- **Analytics**: LOW impact (holiday period, fewer games)
- **Data Integrity**: MEDIUM impact (historical completeness)
- **Operations**: NO impact (current pipeline working)

**Effort**: 2 hours (setup + execution + verification)

**Recommendation**: ⏸️ **DEFER**
- Not critical for operations
- Can do anytime (or never)
- Better priorities exist

**How to Backfill (if needed)**:
```bash
# Script to backfill Dec 23-31
# Try late afternoon hours when NBA.com publishes injury reports

for date in 2025-12-{23..31}; do
  echo "Backfilling $date..."

  curl -s -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
    -H "Content-Type: application/json" \
    -d "{
      \"scraper\": \"nbac_injury_report\",
      \"gamedate\": \"$date\",
      \"hour\": 18,
      \"period\": \"PM\",
      \"minute\": \"00\",
      \"group\": \"prod\"
    }" | jq -r '.status'

  echo "Waiting 60 seconds for processing..."
  sleep 60
done

# Verify backfill
bq query --nouse_legacy_sql \
  "SELECT report_date, COUNT(*) as records
   FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
   WHERE report_date BETWEEN '2025-12-23' AND '2025-12-31'
   GROUP BY report_date
   ORDER BY report_date"
```

**Note**: Some dates may still return empty (NBA.com might not have had injury reports during holiday period).

---

## 🎯 Next Session Priorities

### Context for Next Session
- **Work completed today**: 11 hours
- **Production systems**: All healthy ✅
- **Critical issues**: All resolved ✅
- **Documentation**: Comprehensive and up-to-date ✅

### Recommended Starting Point

**Top Pick: Quick Win #9 - GCS Cache Warming (2 hours)**
- Quick win to build momentum
- Clear value proposition
- Low risk, well-understood
- Documented in Dec 31 analysis

### Priority Tracks (Choose Based on Preference)

**🚀 Performance Track** (if you like speed improvements):
1. **Quick Win #9**: GCS cache warming (2 hours)
   - Pre-warm GCS cache before heavy processing
   - Reduces latency and improves reliability
   - Already analyzed and documented

2. **Quick Win #8**: Phase 1 parallel processing (4-6 hours)
   - Run scrapers in parallel instead of sequential
   - 83% faster Phase 1 execution
   - Bigger effort but significant win

**🔧 Reliability Track** (if you like fixing things):
1. **Quick Win #10**: Fix remaining bare except handlers (4-6 hours)
   - 15+ bare `except:` statements with silent failures
   - Prevent silent errors from being swallowed
   - Improve error visibility and debugging

2. **P0-ORCH-3**: Implement alert manager (6-10 hours)
   - Wire up email/Slack/Sentry notifications
   - Critical for operational awareness
   - Currently all TODOs, not implemented

**🔒 Security Track** (if you like security):
1. **P0-SEC-1**: Add coordinator authentication (6-8 hours)
   - Prediction coordinator has no auth (RCE potential)
   - Critical security vulnerability
   - Requires careful implementation and testing

2. **P0-SEC-2**: Move secrets to Secret Manager (4-6 hours)
   - 7 secrets currently in .env file
   - Credential leak risk
   - Migrate to GCP Secret Manager

**🧹 Cleanup Track** (if you like tidying):
1. **Backfill Dec 23-31 injury data** (2 hours)
   - Optional historical completeness
   - See backfill section above

2. **Update issue tracking** (1 hour)
   - Mark completed P0 issues (cleanup, phase4→5)
   - Update README with current status
   - Archive completed work

3. **Add automated tests** (2-4 hours)
   - Test for exporter order pattern
   - Prevent regression of injury data bug
   - CI/CD integration

### What NOT to Do Next

**❌ Don't repeat completed work:**
- Batch loader is already deployed (331x speedup) ✅
- Phase 4→5 timeout already exists ✅
- Injury pipeline already fixed ✅
- Cleanup processor already fixed ✅

**❌ Don't test in test environment:**
- Production verification was comprehensive
- Test env doesn't support Phase 1 scrapers
- Minimal value for time investment

---

## 📁 Important Files & Locations

### Code Files Modified This Session

**1. Injury Scraper Fix**:
```
File: scrapers/nbacom/nbac_injury_report.py
Lines: 86-100
Commit: 442d404
What: Reordered exporters (JSON first, PDF second)
```

**2. Cleanup Processor Fix**:
```
File: orchestration/cleanup_processor.py
Lines: 321-337
Commit: d88f38d
What: Convert datetime to ISO format for JSON serialization
```

### Documentation Files Created

**1. Original Handoff** (from previous session):
```
File: docs/08-projects/current/pipeline-reliability-improvements/2026-01-01-INJURY-FIX-HANDOFF.md
Lines: 400+
Purpose: Original problem description and context
```

**2. Implementation Details**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/2026-01-01-INJURY-FIX-IMPLEMENTATION.md
Lines: 600+
Purpose: Complete root cause analysis, fix details, testing, verification
```

**3. Session Summary**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/2026-01-01-SESSION-SUMMARY.md
Lines: 400+
Purpose: High-level summary of all work completed
```

**4. This Handoff**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/2026-01-01-COMPLETE-HANDOFF.md
Lines: 1000+ (this file)
Purpose: Complete handoff for next session
```

### Related Documentation

**Project Overview**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/README.md
Purpose: Pipeline reliability improvements project tracking
Status: Updated with Jan 1 session results
```

**Quick Wins Checklist**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/QUICK-WINS-CHECKLIST.md
Purpose: List of 10 quick wins with time estimates
Status: 6/10 completed (including batch loader from Dec 31)
```

**Batch Loader Verification**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/BATCH-LOADER-VERIFICATION.md
Purpose: Documents 331x speedup achievement
Date: December 31, 2025
```

**Comprehensive Analysis**:
```
File: docs/08-projects/current/pipeline-reliability-improvements/COMPREHENSIVE-IMPROVEMENT-ANALYSIS-DEC31.md
Purpose: 100+ improvements identified from 6-agent analysis
Date: December 31, 2025
```

### Git Commits (In Order)

```
442d404 - fix: reorder injury scraper exporters to publish JSON path to Pub/Sub
b36763e - docs: add comprehensive injury data pipeline fix documentation
747547f - docs: add end-to-end test results for injury data fix
d88f38d - fix: resolve datetime serialization error in cleanup processor logging
af6e20e - (deployment build with cleanup fix)
3c50a9e - docs: add comprehensive session summary for Jan 1, 2026
[latest] - docs: add complete handoff document (this file)
```

All commits pushed to `main` branch ✅

---

## 🧠 Key Decisions Made

### Decision 1: Fix Scraper vs Fix Processor

**Question**: Should we fix the scraper (publish correct path) or fix the processor (handle both paths)?

**Options Considered**:
- A: Fix scraper (reorder exporters)
- B: Fix processor (add PDF→JSON path mapping)
- C: Both (defense in depth)

**Decision**: **Option A - Fix scraper only**

**Reasoning**:
- Root cause fix (addresses source, not symptom)
- Simple solution (one-line change + documentation)
- Follows design intent (scraper_base publishes ONE primary output)
- No over-engineering
- Easy to test and verify
- Low maintenance burden

**Trade-offs Accepted**:
- No fallback if something similar happens again
- But: Simple fix + clear documentation prevents regression

### Decision 2: Test Environment

**Question**: Should we test in test environment before production?

**Decision**: **No - test in production**

**Reasoning**:
- Fix is simple (exporter reordering)
- Production test can be comprehensive (manual trigger)
- Test environment doesn't support Phase 1 scrapers
- Risk is extremely low
- Time to value: immediate vs 2+ hours delay
- Can verify end-to-end in production

**Verification Approach**:
- Manual trigger with monitoring
- Check logs for JSON path (not PDF)
- Verify processor receives correct file
- Confirm BigQuery update
- 100% success before declaring victory

### Decision 3: Backfill Missing Data

**Question**: Should we backfill Dec 23-31 injury data?

**Decision**: **Defer - optional, low priority**

**Reasoning**:
- Not critical for operations
- Low impact on predictions (9/60 days = 15%)
- Holiday period - fewer games anyway
- GCS files are empty (need to re-scrape, not reprocess)
- Effort: 2 hours for historical completeness only
- Better priorities exist
- Can do anytime (or never)

**Alternative Considered**:
- Do it now for completeness
- Rejected: Low ROI, better to move forward

### Decision 4: Cleanup Processor - Deploy vs Wait

**Question**: After initial deployment failure, retry immediately or wait?

**Decision**: **Retry immediately**

**Reasoning**:
- Build failure likely transient
- Fix is small (datetime serialization)
- Core functionality already working (republishing)
- Only logging was broken
- Quick retry could save time

**Outcome**: Second deployment succeeded ✅

### Decision 5: Next Steps

**Question**: Continue with more work or stop after 11 hours?

**Decision**: **STOP - declare victory**

**Reasoning**:
- Already worked 11 hours (full day)
- All critical issues resolved
- Production systems healthy
- Diminishing returns with fatigue
- Quality will suffer
- Better to tackle remaining items fresh

**Recommendation for Next Session**:
- Start with Quick Win #9 (GCS cache warming, 2 hours)
- Build momentum with easy win
- Then tackle bigger items

---

## 🛠️ Common Commands Reference

### Deployment Commands

**Deploy scrapers (orchestrator + cleanup processor)**:
```bash
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# What this does:
# 1. Deploys nba-phase1-scrapers (orchestrator)
# 2. Configures SERVICE_URL to point to nba-scrapers
# 3. Sets up API key secrets
# 4. Tests health endpoint
```

**Deploy just nba-scrapers (actual scraper code)**:
```bash
cp docker/scrapers.Dockerfile ./Dockerfile
gcloud run deploy nba-scrapers \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=540 \
  --set-secrets="ODDS_API_KEY=ODDS_API_KEY:latest,BDL_API_KEY=BDL_API_KEY:latest" \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform"
rm ./Dockerfile
```

### Manual Testing Commands

**Trigger injury scraper manually**:
```bash
curl -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "nbac_injury_report",
    "gamedate": "2026-01-01",
    "hour": 9,
    "period": "AM",
    "minute": "00",
    "group": "prod"
  }' | jq .
```

**Trigger cleanup processor manually**:
```bash
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/cleanup" \
  -H "Content-Type: application/json" | jq .
```

### Log Viewing Commands

**View recent logs for a service**:
```bash
# Scraper logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-scrapers"' \
  --limit=100 --freshness=1h

# Orchestrator logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=100 --freshness=1h

# Processor logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=100 --freshness=1h
```

**Follow logs in real-time** (if deploying or testing):
```bash
gcloud run services logs tail nba-scrapers --region=us-west2
```

### BigQuery Query Commands

**Check injury data**:
```bash
bq query --nouse_legacy_sql \
  "SELECT report_date, COUNT(*) as records, MAX(scrape_time)
   FROM nba_raw.nbac_injury_report
   WHERE report_date >= CURRENT_DATE() - 7
   GROUP BY report_date ORDER BY report_date DESC"
```

**Check processor runs**:
```bash
bq query --nouse_legacy_sql \
  "SELECT processor_name, status, COUNT(*)
   FROM nba_orchestration.processor_run_history
   WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
   GROUP BY processor_name, status"
```

**Check cleanup operations**:
```bash
bq query --nouse_legacy_sql \
  "SELECT cleanup_id, cleanup_time, files_checked, republished_count
   FROM nba_orchestration.cleanup_operations
   WHERE cleanup_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
   ORDER BY cleanup_time DESC"
```

### Git Commands

**Check current status**:
```bash
git status
git log --oneline -10
```

**Create a commit**:
```bash
git add <file>
git commit -m "descriptive message"
git push origin main
```

**View recent changes**:
```bash
git diff HEAD~3  # Last 3 commits
git show <commit-sha>  # Specific commit
```

---

## 🚨 Troubleshooting Guide

### Issue: Injury scraper publishing PDF path again

**Symptoms**:
- Logs show: `Captured gcs_output_path: gs://.../injury-report-pdf/.../pdf`
- Processor logs show errors or no processing
- BigQuery has no new injury data

**Diagnosis**:
```bash
# Check scraper logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-scrapers"' \
  --limit=50 --freshness=2h --format="value(textPayload)" | grep "gcs_output_path"
```

**Likely Causes**:
1. Code reverted (check git history)
2. Deployment didn't include fix (check revision)
3. Different scraper instance running

**Resolution**:
```bash
# Verify git has the fix
git log --oneline | grep "injury"
git show 442d404  # Should show exporter reordering

# Check deployed revision
gcloud run services describe nba-scrapers --region=us-west2 --format="value(status.latestReadyRevisionName)"

# Redeploy if needed
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

---

### Issue: Cleanup processor datetime errors again

**Symptoms**:
- Logs show: `Object of type datetime is not JSON serializable`
- Cleanup operations not in BigQuery

**Diagnosis**:
```bash
# Check cleanup logs
gcloud logging read \
  'resource.type="cloud_run_revision" AND
   resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=50 --freshness=30m --format="value(textPayload)" | grep -A2 "cleanup"
```

**Likely Causes**:
1. Deployment failed or didn't include fix
2. Old revision still running
3. Code reverted

**Resolution**:
```bash
# Verify git has fix
git show d88f38d  # Should show datetime conversion

# Check deployed revision
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="value(status.latestReadyRevisionName)"
# Should be 00066-tx5 or later

# Redeploy if needed
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

---

### Issue: Cleanup processor not running

**Symptoms**:
- No cleanup logs for 30+ minutes
- Cloud Scheduler shows enabled

**Diagnosis**:
```bash
# Check scheduler status
gcloud scheduler jobs describe cleanup-processor --location=us-west2

# Check recent executions
gcloud logging read \
  'resource.type="cloud_scheduler_job"' \
  --limit=20 --freshness=1h | grep cleanup
```

**Likely Causes**:
1. Scheduler paused
2. Service endpoint changed
3. Authentication issues

**Resolution**:
```bash
# Check if job is enabled
gcloud scheduler jobs describe cleanup-processor --location=us-west2 --format="value(state)"

# Re-enable if needed
gcloud scheduler jobs resume cleanup-processor --location=us-west2

# Trigger manually to test
gcloud scheduler jobs run cleanup-processor --location=us-west2
```

---

### Issue: Injury workflow never executes

**Symptoms**:
- Always shows "SKIP - Not in time window"
- Even during 11 AM - 3 PM PT

**Diagnosis**:
```bash
# Check workflow decisions
bq query --nouse_legacy_sql \
  "SELECT triggered_at, decision, decision_reason
   FROM nba_orchestration.workflow_decisions
   WHERE workflow = 'injury_discovery'
     AND DATE(triggered_at) >= CURRENT_DATE() - 3
   ORDER BY triggered_at DESC
   LIMIT 20"
```

**Likely Causes**:
1. Discovery mode time window misconfigured
2. Game date check failing
3. Max attempts reached

**Resolution**:
```bash
# Check workflow config
cat config/workflows.yaml | grep -A15 "injury_discovery"

# Manually trigger scraper to bypass workflow
curl -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "nbac_injury_report",
    "gamedate": "2026-01-01",
    "hour": 14,
    "period": "PM",
    "minute": "00",
    "group": "prod"
  }'
```

---

### Issue: Deployment fails with "Build failed"

**Symptoms**:
- `ERROR: (gcloud.run.deploy) Build failed`
- Container build times out or errors

**Diagnosis**:
```bash
# Get latest build ID
gcloud builds list --limit=1 --format="value(id)"

# Check build logs
gcloud builds log <build-id>
```

**Likely Causes**:
1. Dockerfile errors
2. Missing dependencies
3. Transient build failures

**Resolution**:
```bash
# Retry deployment (often works for transient failures)
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# If still failing, check Dockerfile
cat docker/scrapers.Dockerfile

# Clean up and retry
rm -f Dockerfile Dockerfile.backup.*
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

---

### Issue: BigQuery shows no recent data

**Symptoms**:
- Query returns empty or old data
- Scraper logs show success
- Processor logs show success

**Diagnosis**:
```bash
# Check if data is there but query is wrong
bq query --nouse_legacy_sql \
  "SELECT MAX(processed_at), COUNT(*)
   FROM nba_raw.nbac_injury_report"

# Check processor run history
bq query --nouse_legacy_sql \
  "SELECT * FROM nba_orchestration.processor_run_history
   WHERE processor_name = 'nbac_injury_report'
   ORDER BY triggered_at DESC
   LIMIT 5"
```

**Likely Causes**:
1. Timezone confusion (dates are ET, not UTC)
2. Data in different table
3. Processor succeeded but wrote 0 rows

**Resolution**:
```bash
# Check with timezone awareness
bq query --nouse_legacy_sql \
  "SELECT
    DATE(report_date) as date,
    COUNT(*) as records
   FROM nba_raw.nbac_injury_report
   WHERE report_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY date
   ORDER BY date DESC"

# If still missing, manually trigger processor
# (requires GCS path from scraper logs)
```

---

## 📞 Quick Reference Card

### Essential URLs

**Cloud Run Services**:
- Scrapers: https://nba-scrapers-756957797294.us-west2.run.app
- Orchestrator: https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app
- Raw Processors: https://nba-phase2-raw-processors-756957797294.us-west2.run.app

**Cloud Console**:
- Cloud Run: https://console.cloud.google.com/run?project=nba-props-platform
- Cloud Scheduler: https://console.cloud.google.com/cloudscheduler?project=nba-props-platform
- BigQuery: https://console.cloud.google.com/bigquery?project=nba-props-platform
- GCS Buckets: https://console.cloud.google.com/storage/browser?project=nba-props-platform

### Key Service Revisions (Current)

```
nba-scrapers: 00087-mgr (injury fix)
nba-phase1-scrapers: 00066-tx5 (cleanup fix)
```

### Quick Health Check

```bash
# One-liner to check everything
echo "=== Injury Data ===" && \
bq query --nouse_legacy_sql --format=csv \
  "SELECT MAX(report_date) FROM nba_raw.nbac_injury_report" && \
echo "=== Recent Scraper Runs ===" && \
gcloud logging read 'resource.labels.service_name="nba-scrapers"' \
  --limit=3 --freshness=6h --format="value(timestamp)" | head -3 && \
echo "=== Cleanup Status ===" && \
gcloud logging read 'resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=50 --freshness=30m --format="value(textPayload)" | \
  grep -c "cleanup" && echo "runs in last 30min"
```

---

## ✅ Handoff Checklist

Before starting next session, verify:

- [ ] All git commits are pushed to `main` ✅
- [ ] Documentation is up-to-date ✅
- [ ] Production services are healthy ✅
- [ ] No outstanding critical issues ✅
- [ ] Clear next steps identified ✅
- [ ] Monitoring commands tested and working ✅

**Status**: ✅ ALL ITEMS COMPLETE

---

## 🎯 Summary for Next Session

**Start Here**:
1. Read this handoff document (you're doing it!)
2. Verify systems are healthy (run health check commands)
3. Choose your priority track (Performance/Reliability/Security/Cleanup)
4. Start with Quick Win #9 (GCS cache warming, 2 hours) - recommended easy start

**Key Points**:
- ✅ Injury pipeline fixed and working
- ✅ Cleanup processor logging fixed
- ✅ All deployments verified
- ✅ 331x speedup confirmed (batch loader)
- ⏸️ Backfill is optional (low priority)
- 🎯 Next: Pick a quick win or P0 to tackle

**What NOT to Do**:
- ❌ Don't re-test in test environment (already verified in prod)
- ❌ Don't backfill unless you want complete historical data
- ❌ Don't re-deploy anything (all fixes are already deployed)

**Documentation Location**:
```
docs/08-projects/current/pipeline-reliability-improvements/
├── 2026-01-01-COMPLETE-HANDOFF.md (THIS FILE - START HERE)
├── 2026-01-01-INJURY-FIX-IMPLEMENTATION.md (detailed technical docs)
├── 2026-01-01-SESSION-SUMMARY.md (session summary)
└── README.md (project overview)
```

---

**Handoff Complete** ✅
**Production Status**: All systems operational
**Ready for Next Session**: Yes
**Confidence Level**: High

---

*Last Updated: January 1, 2026, 11:00 AM PST*
*Session Duration: 11 hours*
*Total Documentation: 2000+ lines*
*Status: READY FOR HANDOFF*
