# Injury Data Fix - Session Handoff - Jan 1, 2026

**Status**: ⚠️ PARTIALLY FIXED - Manual workaround works, automatic pipeline broken
**Priority**: HIGH - Needs proper fix for production reliability
**Current Time**: ~1:00 AM PST, Jan 1, 2026

---

## 🎯 Executive Summary

**What Works**:
- ✅ Scraper code fixed to use new NBA.com URL format (with minutes)
- ✅ Both services deployed with updated code
- ✅ Manual scraper execution returns current injury data (65 records)
- ✅ Manual processing to BigQuery successful
- ✅ BigQuery has Jan 1, 2026 injury data

**What's Broken**:
- ❌ Automatic hourly workflow doesn't run
- ❌ Scraper publishes wrong file path to Pub/Sub (PDF instead of JSON)
- ❌ Processor can't handle the published path
- ❌ Data never reaches BigQuery automatically

**Impact**: Injury data will remain stale unless manually triggered daily.

---

## 📊 Current State

### Services Deployed (All Updated)

| Service | Revision | Commit | Status |
|---------|----------|--------|--------|
| `nba-scrapers` | `00086-7jm` | `a9dd00e` | ✅ Has fix |
| `nba-phase1-scrapers` | `00062-rpj` | `a9dd00e` | ✅ Has fix |
| `nba-phase2-raw-processors` | (not redeployed) | (old) | ⚠️ No changes needed |

### BigQuery Status

```sql
SELECT report_date, COUNT(*) as records
FROM `nba-props-platform.nba_raw.nbac_injury_report`
WHERE report_date >= '2025-12-22'
ORDER BY report_date DESC;

-- Results:
-- 2026-01-01: 65 records (manually loaded)
-- 2025-12-22: X records (last automatic load)
-- 2025-12-23 to 2025-12-31: 0 records (missing)
```

### GCS File Status

**Successful Manual Run**:
```
gs://nba-scraped-data/nba-com/injury-report-data/2026-01-01/01/20260101_085523.json
Size: 13.07 KiB
Records: 65 injury reports
is_empty_report: false ✅
```

**Failed Automatic Runs**:
```
gs://nba-scraped-data/nba-com/injury-report-data/2026-01-01/01/20260101_060519.json
Size: 2 bytes
Content: []
is_empty_report: true (but file exists in PDF format)
```

---

## 🔍 Root Cause Analysis

### The Original Issue (FIXED)

**Problem**: NBA.com changed URL format on Dec 23, 2025

**Old Format** (worked until Dec 22):
```
https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-22_06PM.pdf
```

**New Format** (required since Dec 23):
```
https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-12-31_06_00PM.pdf
                                                                    ^^^^^^^
                                                            (includes minutes)
```

**Fix Applied**:
- File: `scrapers/nbacom/nbac_injury_report.py`
- Added date-based URL selection (cutoff: Dec 23, 2025)
- Added `minute` parameter (defaults to "00")
- Commit: `14b9b53`

### The New Issue (NOT FIXED)

**Problem**: Scraper publishes wrong file to Pub/Sub

**What Happens**:

1. **Scraper runs** and creates TWO files:
   ```
   PDF:  gs://.../injury-report-pdf/2026-01-01/01/20260101_085523.pdf
   JSON: gs://.../injury-report-data/2026-01-01/01/20260101_085523.json
   ```

2. **Scraper publishes to Pub/Sub** with:
   ```json
   {
     "gcs_path": "gs://.../injury-report-pdf/.../20260101_085523.pdf",  // ❌ WRONG
     "status": "success"
   }
   ```

3. **Processor receives message** and tries to process PDF:
   ```
   WARNING: No processor found for file: nba-com/injury-report-pdf/.../pdf
   ```

4. **JSON file never processed** → No data in BigQuery

**Evidence from Logs**:
```
INFO:data_processors.raw.main_processor_service:📥 Processing file:
  gs://nba-scraped-data/nba-com/injury-report-pdf/2026-01-01/01/20260101_085523.pdf

WARNING:data_processors.raw.main_processor_service:
  No processor found for file: nba-com/injury-report-pdf/2026-01-01/01/20260101_085523.pdf
```

### The Workflow Issue (ALSO NOT FIXED)

**Problem**: `injury_discovery` workflow stops after first run

**Workflow Config** (`config/workflows.yaml` line 422):
```yaml
injury_discovery:
  enabled: true
  priority: "MEDIUM"
  decision_type: "discovery"
  schedule:
    discovery_mode: true              # ← PROBLEM
    max_attempts_per_day: 12
    retry_interval_hours: 2
    requires_game_day: true
```

**What `discovery_mode: true` Does**:
- Workflow runs hourly to "discover" when data becomes available
- Once it finds data (even if empty), it marks itself as complete
- Won't run again until next day
- This was designed for data that appears once per day

**Why It's Failing**:
- Early morning runs found empty files (from broken URL format)
- Workflow marked as "completed" for the day
- Later runs with fixed code never execute
- Data stays stale

**Evidence from Logs**:
```
📊 Evaluating: injury_discovery (type: discovery)
# But no execution, because already marked complete
```

---

## 🛠️ What We've Done

### 1. Updated Scraper Code ✅

**File**: `scrapers/nbacom/nbac_injury_report.py`

**Changes**:
```python
# Lines 218-232: Date-based URL format selection
cutoff_date = datetime(2025, 12, 23).date()

if date_obj >= cutoff_date:
    # New format with minutes (post-Dec 22, 2025)
    self.url = (
        f"https://ak-static.cms.nba.com/referee/injury/"
        f"Injury-Report_{formatted_date}_{hour}_{minute}{period}.pdf"
    )
else:
    # Old format without minutes (pre-Dec 23, 2025)
    self.url = (
        f"https://ak-static.cms.nba.com/referee/injury/"
        f"Injury-Report_{formatted_date}_{hour}{period}.pdf"
    )
```

**File**: `orchestration/parameter_resolver.py`

**Changes**:
```python
# Lines 543-565: Calculate minute intervals
minute_interval = (current_minute // 15) * 15

return {
    'gamedate': context['execution_date'],
    'hour': hour,
    'period': period,
    'minute': f"{minute_interval:02d}"  # 00, 15, 30, or 45
}
```

### 2. Deployed Services ✅

**nba-scrapers** (actual scraper code):
```bash
./bin/scrapers/deploy/deploy_scrapers_simple.sh
# But this only deployed nba-phase1-scrapers (orchestrator)

# Had to manually deploy nba-scrapers:
gcloud run deploy nba-scrapers \
  --source=. \
  --region=us-west2 \
  ... (full command in history)

# Result: revision 00086-7jm with commit a9dd00e
```

**nba-phase1-scrapers** (orchestrator):
```bash
./bin/scrapers/deploy/deploy_scrapers_simple.sh

# Result: revision 00062-rpj with commit a9dd00e
```

### 3. Tested Manual Execution ✅

**Command**:
```bash
curl -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "nbac_injury_report",
    "gamedate": "2026-01-01",
    "hour": 1,
    "period": "AM",
    "minute": "00",
    "group": "prod"
  }'
```

**Result**:
```json
{
  "status": "success",
  "data_summary": {
    "total_records": 65,
    "is_empty_report": false,
    "status_counts": {
      "Out": 44,
      "Questionable": 11,
      "Available": 5,
      "Doubtful": 4,
      "Probable": 1
    },
    "overall_confidence": 1.0
  }
}
```

### 4. Manually Loaded to BigQuery ✅

**Method**: Used processor directly in Python
```python
from data_processors.raw.nbacom.nbac_injury_report_processor import NbacInjuryReportProcessor
# ... (code in history)

# Result: Loaded 65 rows to BigQuery
```

**Verification**:
```sql
SELECT report_date, COUNT(*) FROM nba_raw.nbac_injury_report
WHERE report_date = '2026-01-01';

-- Result: 2026-01-01 | 65
```

---

## 🚨 Critical Issues Remaining

### Issue #1: Scraper Publishes Wrong Path

**Severity**: HIGH - Blocks automatic processing

**Location**: `scrapers/nbacom/nbac_injury_report.py`

**Problem**: Scraper has TWO exporters:
```python
# Line 88-91: Exporters configuration
exporters = [
    {"type": "gcs", "key": GCSPathBuilder.get_path("nba_com_injury_report_pdf_raw"),
     "export_mode": ExportMode.RAW, "groups": ["prod", "gcs"]},  # ← Exports PDF

    {"type": "gcs", "key": GCSPathBuilder.get_path("nba_com_injury_report_data"),
     "export_mode": ExportMode.DATA, "groups": ["prod", "gcs"]},  # ← Exports JSON
]
```

**Current Behavior**:
- Both files get created ✅
- PDF exporter runs first
- PDF path gets published to Pub/Sub ❌
- JSON file exists but never gets processed

**What Needs Investigation**:
1. Which exporter triggers the Pub/Sub publish?
2. Is it the FIRST exporter? The LAST exporter?
3. Can we control which path gets published?
4. Should we change the order?
5. Should we remove the PDF exporter from the `prod` group?

**Files to Check**:
- `scrapers/scraper_base.py` - Base scraper export logic
- `scrapers/exporters.py` - GCS exporter implementation
- `scrapers/utils/pubsub_utils.py` - Pub/Sub publishing logic

### Issue #2: Processor Doesn't Handle PDF Path

**Severity**: MEDIUM - Workaround is to fix Issue #1

**Location**: `data_processors/raw/main_processor_service.py`

**Problem**: Processor registry doesn't map PDF path to processor:
```python
# Line 100: Processor registry
PROCESSOR_REGISTRY = {
    'nba-com/injury-report-data': NbacInjuryReportProcessor,  # ← JSON path
    # Missing: 'nba-com/injury-report-pdf' mapping
}
```

**Options**:
1. **Fix the scraper** to publish JSON path (preferred)
2. **Update processor** to handle PDF path → process JSON file
3. **Both**: Add mapping and fix scraper for redundancy

**If Option 2 (processor fix)**:
```python
# Pseudocode for processor change
if gcs_path.endswith('.pdf') and 'injury-report-pdf' in gcs_path:
    # Replace path to point to JSON file
    json_path = gcs_path.replace('injury-report-pdf', 'injury-report-data')
    json_path = json_path.replace('.pdf', '.json')
    # Process JSON file instead
```

### Issue #3: Workflow Discovery Mode

**Severity**: MEDIUM - Prevents automatic retries

**Location**: `config/workflows.yaml` line 422

**Problem**:
```yaml
injury_discovery:
  schedule:
    discovery_mode: true  # ← Stops after first success
```

**Why This Exists**:
- Injury reports are published sporadically (usually 11 AM - 3 PM ET)
- Discovery mode keeps checking until found
- Once found, stops to avoid redundant processing

**Why It's Problematic**:
- If first run gets empty data (broken URL), marks as "complete"
- Never retries with fixed URL
- Manual intervention required

**Options**:
1. **Change to `discovery_mode: false`**
   - Runs every hour regardless
   - Processes every update
   - More resilient to failures

2. **Add failure detection**
   - Only mark complete if data is non-empty
   - Retry if `is_empty_report: true`

3. **Add manual reset mechanism**
   - Allow resetting workflow state
   - Useful for debugging

**Decision Needed**: What's the desired behavior?
- Process injury reports every hour?
- Or once per day when first available?

---

## 📋 TODO List for Next Session

### Priority 1: Fix Automatic Processing (CRITICAL)

- [ ] **Investigate Pub/Sub publishing logic**
  - [ ] Read `scrapers/scraper_base.py` export logic
  - [ ] Read `scrapers/exporters.py` GCS exporter
  - [ ] Read `scrapers/utils/pubsub_utils.py`
  - [ ] Identify which exporter triggers Pub/Sub publish
  - [ ] Understand if it's first, last, or all exporters

- [ ] **Fix scraper to publish JSON path** (Option A)
  - [ ] Option A1: Change exporter order (JSON first, PDF second)
  - [ ] Option A2: Remove PDF from prod group
  - [ ] Option A3: Add flag to control which path publishes
  - [ ] Test manually to verify JSON path published
  - [ ] Deploy and verify automatic processing works

- [ ] **OR Fix processor to handle PDF path** (Option B)
  - [ ] Add 'nba-com/injury-report-pdf' to processor registry
  - [ ] Map to NbacInjuryReportProcessor
  - [ ] Update processor to substitute JSON path when given PDF
  - [ ] Test with manual Pub/Sub message
  - [ ] Deploy processor

- [ ] **Verify end-to-end automatic processing**
  - [ ] Wait for next hourly run (at :05)
  - [ ] Check logs for successful execution
  - [ ] Verify JSON file created with data
  - [ ] Verify processor received correct path
  - [ ] Verify data loaded to BigQuery
  - [ ] Confirm no manual intervention needed

### Priority 2: Fix Workflow Discovery Mode

- [ ] **Decide on desired behavior**
  - [ ] Should injury reports process every hour?
  - [ ] Or only once per day when first available?
  - [ ] Discuss with team/stakeholder

- [ ] **Implement chosen solution**
  - [ ] Option 1: Set `discovery_mode: false` in config
  - [ ] Option 2: Add empty-data detection to workflow logic
  - [ ] Option 3: Add manual reset capability
  - [ ] Test workflow execution pattern
  - [ ] Verify it handles failures gracefully

### Priority 3: Backfill Missing Data

- [ ] **Backfill Dec 23-31, 2025**
  - [ ] Option 1: Re-run scraper backfill job with updated code
  - [ ] Option 2: Manually trigger scraper for each date
  - [ ] Option 3: Use processor backfill on existing empty files
  - [ ] Verify all dates have data in BigQuery
  - [ ] Verify Phase 6 exports reflect historical data

### Priority 4: Add Monitoring & Alerts

- [ ] **Data freshness monitoring**
  - [ ] Create BigQuery view for stale data detection
  - [ ] Alert if no new injury data in 24 hours
  - [ ] Alert if data is empty (is_empty_report: true)

- [ ] **Scraper success tracking**
  - [ ] Track consecutive failures
  - [ ] Alert if >5 consecutive no_data responses
  - [ ] Alert on 403 Forbidden (URL format issue)

- [ ] **Processor health monitoring**
  - [ ] Alert if Pub/Sub messages not processed
  - [ ] Track processing lag
  - [ ] Alert on processor errors

### Priority 5: Deployment Process Improvements

- [ ] **Fix deployment script**
  - [ ] `deploy_scrapers_simple.sh` only deploys orchestrator
  - [ ] Need separate script or update existing to deploy BOTH:
    - [ ] nba-phase1-scrapers (orchestrator)
    - [ ] nba-scrapers (actual scraper code)
  - [ ] Document which service runs what code

- [ ] **Add deployment verification**
  - [ ] Verify both services have same commit SHA
  - [ ] Test scraper endpoint after deployment
  - [ ] Smoke test: Manual scraper execution
  - [ ] Check logs for any startup errors

---

## 🧪 Testing & Verification

### Manual Test (Known Working)

```bash
# 1. Trigger scraper manually
curl -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "nbac_injury_report",
    "gamedate": "2026-01-01",
    "hour": 7,
    "period": "PM",
    "minute": "00",
    "group": "prod"
  }'

# Expected: 200 OK with data_summary showing 50-100 records

# 2. Check GCS file
gsutil ls -lh gs://nba-scraped-data/nba-com/injury-report-data/$(date +%Y-%m-%d)/

# Expected: File >10KB (not 2 bytes)

# 3. Verify BigQuery (requires manual processor run)
bq query --nouse_legacy_sql \
  'SELECT COUNT(*) FROM nba_raw.nbac_injury_report
   WHERE report_date = CURRENT_DATE()'

# Expected: >0 records (after manual processing)
```

### Automatic Test (Needs Fix)

```bash
# 1. Wait for hourly run (at :05 past hour)
# 2. Check orchestrator logs
gcloud logging read \
  'resource.labels.service_name="nba-phase1-scrapers"' \
  --limit=50 --freshness=10m | grep injury

# Expected: Should see "Executing Workflow: injury_discovery"

# 3. Check scraper logs
gcloud logging read \
  'resource.labels.service_name="nba-scrapers"' \
  --limit=50 --freshness=10m | grep injury

# Expected: Should see "Injury Report URL: ..._{hour}_{minute}{period}.pdf"

# 4. Check processor logs
gcloud logging read \
  'resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=50 --freshness=10m | grep injury

# Expected: Should see "Processing file: .../injury-report-data/...json"
# NOT: ".../injury-report-pdf/...pdf" ❌

# 5. Verify BigQuery
bq query --nouse_legacy_sql \
  'SELECT MAX(report_date), COUNT(*)
   FROM nba_raw.nbac_injury_report'

# Expected: Latest date = today, count increasing
```

---

## 📁 Key Files Reference

### Scraper Files
```
scrapers/nbacom/nbac_injury_report.py          # Main scraper (UPDATED)
  - Line 75: optional_params = {"minute": "00"}
  - Line 88-97: exporters configuration (CHECK THIS)
  - Line 196-241: set_url() with date-based logic

scrapers/scraper_base.py                       # Base scraper class
  - Export orchestration logic
  - Pub/Sub publishing trigger

scrapers/exporters.py                          # Exporter implementations
  - GCS exporter
  - When does it publish to Pub/Sub?

scrapers/utils/pubsub_utils.py                 # Pub/Sub publishing
  - Which GCS path gets published?
```

### Processor Files
```
data_processors/raw/main_processor_service.py  # Main processor
  - Line 75-100: PROCESSOR_REGISTRY
  - Line 100: 'nba-com/injury-report-data' mapping
  - Missing: 'nba-com/injury-report-pdf' mapping

data_processors/raw/nbacom/nbac_injury_report_processor.py
  - Transform and load logic
  - Works correctly when called manually
```

### Orchestration Files
```
orchestration/parameter_resolver.py            # Parameter resolver (UPDATED)
  - Line 523-566: _resolve_nbac_injury_report()
  - Calculates minute intervals

orchestration/workflow_executor.py             # Workflow execution
  - Discovery mode logic

config/workflows.yaml                          # Workflow configuration
  - Line 422-437: injury_discovery workflow
  - Line 428: discovery_mode: true (PROBLEM?)
```

### Deployment Scripts
```
bin/scrapers/deploy/deploy_scrapers_simple.sh  # Deployment script
  - Deploys nba-phase1-scrapers (orchestrator)
  - Does NOT deploy nba-scrapers (scraper code)
  - Needs fix or separate script
```

---

## 🔧 Technical Context

### Architecture Flow

```
┌─────────────────┐
│ Cloud Scheduler │ (Runs at :05 every hour)
└────────┬────────┘
         │
         ▼
┌────────────────────────┐
│ nba-phase1-scrapers    │ (Orchestrator)
│ - Evaluates workflows  │
│ - Calls scrapers       │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│ nba-scrapers           │ (Actual scraper code)
│ - Downloads PDF        │
│ - Parses to JSON       │
│ - Exports both files   │
│ - Publishes to Pub/Sub │ ← PUBLISHES WRONG PATH
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│ Pub/Sub: scrapers-     │
│ complete               │
│ Message: {gcs_path}    │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│ nba-phase2-raw-        │ (Processor)
│ processors             │
│ - Receives Pub/Sub     │
│ - Loads JSON to BQ     │ ← CAN'T FIND PROCESSOR FOR PDF
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│ BigQuery:              │
│ nba_raw.nbac_injury_   │
│ report                 │
└────────────────────────┘
```

### Service URLs

```
Orchestrator:  https://nba-phase1-scrapers-756957797294.us-west2.run.app
Scraper:       https://nba-scrapers-756957797294.us-west2.run.app
Processor:     https://nba-phase2-raw-processors-756957797294.us-west2.run.app

Scheduler Job: execute-workflows (runs at :05 every hour)
Schedule:      5 0-23 * * * (every hour at 5 minutes past)
```

### Data Paths

```
GCS Bucket: nba-scraped-data

PDF Path:  nba-com/injury-report-pdf/YYYY-MM-DD/HH/YYYYMMDDHHmmss.pdf
JSON Path: nba-com/injury-report-data/YYYY-MM-DD/HH/YYYYMMDDHHmmss.json

Example:
PDF:  nba-com/injury-report-pdf/2026-01-01/01/20260101_085523.pdf
JSON: nba-com/injury-report-data/2026-01-01/01/20260101_085523.json
                                   ^
                                   This is what processor expects
```

---

## 🐛 Known Issues & Gotchas

### 1. Two Scraper Services
- `nba-phase1-scrapers` = Orchestrator (runs workflows)
- `nba-scrapers` = Actual scraper code (does the work)
- BOTH must be deployed for changes to take effect
- Deployment script only deploys orchestrator

### 2. Discovery Mode State
- Workflow state persists in BigQuery
- Once marked "complete", won't run again until next day
- No UI to reset state
- Manual database update required to force re-run

### 3. Deployment Timing
- We deployed at 7:40 PM (before making the fix)
- Then made the fix
- Then redeployed at 10:15 PM
- First deployment had no effect because code wasn't ready

### 4. URL Format Transition
- Old format still works for dates before Dec 23, 2025
- New format required for Dec 23, 2025 and later
- Code handles both based on date
- Backfill for old dates will use old format automatically

### 5. Empty vs No Data
- `[]` in file = empty report (scraper ran, found no injuries)
- `2 bytes` file = scraper failed, created placeholder
- `is_empty_report: true` with `no_data_reason` = expected condition
- `is_empty_report: true` without reason = unexpected

---

## 📚 Related Documentation

- **Main Issue Doc**: `2025-12-31-INJURY-URL-FORMAT-CHANGE.md`
  - Root cause analysis
  - Original fix implementation
  - Verification steps

- **Session Summary**: `2025-12-31-SESSION-SUMMARY.md`
  - Investigation process
  - Solutions attempted
  - Lessons learned

- **Previous Handoff**: `2025-12-31-SESSION-HANDOFF.md`
  - Dataset isolation validation
  - Other pipeline improvements

---

## 💡 Recommendations

### Immediate (Next Session)

1. **Start with investigation** - Don't code yet
   - Understand the exact Pub/Sub publishing mechanism
   - Read the exporter code carefully
   - Trace through the full flow

2. **Choose one fix approach** - Don't try both
   - Either fix scraper OR fix processor
   - Scraper fix is cleaner (prevents bad message)
   - Processor fix is more resilient (handles legacy data)

3. **Test manually first** - Before deploying
   - Use curl to trigger scraper
   - Check which path gets published
   - Verify fix before deployment

### Medium Term

1. **Add integration tests**
   - End-to-end test: scraper → processor → BigQuery
   - Detect this type of issue automatically

2. **Improve monitoring**
   - Alert on empty injury reports
   - Alert on processing failures
   - Track data freshness

3. **Document architecture better**
   - Service responsibilities
   - Data flow diagrams
   - Deployment process

### Long Term

1. **Simplify workflow logic**
   - Discovery mode is complex
   - Consider simpler hourly processing
   - Add resilience to failures

2. **Consolidate services**
   - Two scraper services is confusing
   - Consider merging orchestrator + scraper

3. **Add fallback data source**
   - BallDontLie injuries API available
   - Could use as backup if NBA.com fails

---

## ✅ Success Criteria

The fix will be complete when:

1. **Automatic hourly run succeeds**
   - No manual intervention required
   - Runs at :05 every hour
   - Processes latest injury data

2. **Data flows end-to-end**
   - Scraper downloads PDF successfully
   - JSON file created with data
   - Correct path published to Pub/Sub
   - Processor receives and loads data
   - BigQuery updated within 5 minutes

3. **Monitoring confirms health**
   - No empty reports (unless genuinely empty)
   - No processor errors
   - Data freshness < 24 hours

4. **Backfill complete**
   - Dec 23-31, 2025 data loaded
   - No gaps in historical data

---

## 🚀 Quick Start for Next Session

```bash
# 1. Understand current publishing behavior
cd /home/naji/code/nba-stats-scraper

# Read these files IN ORDER:
cat scrapers/nbacom/nbac_injury_report.py | grep -A 20 "exporters ="
cat scrapers/exporters.py | grep -A 50 "class GCSExporter"
cat scrapers/utils/pubsub_utils.py | grep -A 30 "publish"

# 2. Test current behavior
curl -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper":"nbac_injury_report","gamedate":"2026-01-01","hour":2,"period":"AM","minute":"00","group":"prod"}'

# 3. Check what got published
gcloud logging read 'resource.labels.service_name="nba-scrapers"' \
  --limit=20 --freshness=5m | grep -i "published\|gcs_path"

# 4. Check what processor received
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors"' \
  --limit=20 --freshness=5m | grep -i "injury"

# 5. Make a decision on fix approach
# Then code, test, deploy
```

---

**Session Ended**: Jan 1, 2026, ~1:00 AM PST
**Next Session**: Fix automatic processing (Priority 1 TODOs)
**Estimated Time**: 2-3 hours for investigation + fix + verification
**Risk Level**: MEDIUM - Manual workaround available if fix fails

---

## 🔥 Emergency Workaround

If automatic processing is broken and you need injury data NOW:

```bash
# 1. Manually trigger scraper
curl -X POST "https://nba-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "nbac_injury_report",
    "gamedate": "2026-01-01",
    "hour": 7,
    "period": "PM",
    "minute": "00",
    "group": "prod"
  }'

# 2. Get the file path from response
# Look for the JSON file path in GCS

# 3. Manually process to BigQuery
PYTHONPATH=. python3 << 'EOF'
from data_processors.raw.nbacom.nbac_injury_report_processor import NbacInjuryReportProcessor
from google.cloud import storage
import json

processor = NbacInjuryReportProcessor()
storage_client = storage.Client()
bucket = storage_client.bucket('nba-scraped-data')

# UPDATE THIS PATH with actual file
blob = bucket.blob('nba-com/injury-report-data/2026-01-01/19/YYYYMMDD_HHMMSS.json')

data = json.loads(blob.download_as_text())
data['metadata']['source_file'] = f'gs://nba-scraped-data/{blob.name}'
processor.raw_data = data
processor.transform_data()
result = processor.save_data()
print(f"Loaded {result.get('rows_processed', 0)} rows")
EOF

# 4. Verify
bq query --nouse_legacy_sql \
  'SELECT MAX(report_date), COUNT(*) FROM nba_raw.nbac_injury_report'
```

---

**Document Version**: 1.0
**Author**: Claude (Session Jan 1, 2026)
**Status**: Ready for next session
