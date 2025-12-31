# Session 157: Scraper Staleness Root Causes and Fixes

**Date:** 2025-12-21
**Status:** Fixes deployed, awaiting next scheduled run for verification

---

## Executive Summary

Investigated and fixed 3 root causes for stale scrapers identified in Session 156 handoff:

1. **BigDataBall PBP** (stale since Dec 16) - Wrong table name in master_controller.py
2. **Injury Report** (appeared stale since June 2025) - Missing Phase 2 processor registry entry
3. **BettingPros** (never ran this season) - Not included in any workflow

All fixes deployed to production.

---

## Root Cause Analysis

### Issue 1: BigDataBall PBP Stopped at Dec 16

**Symptom:** `bigdataball_play_by_play` table had data only up to 2025-12-16.

**Root Cause:** `orchestration/master_controller.py:496` referenced non-existent table `bdl_box_scores`:

```python
# BEFORE (broken)
query = f"""
    SELECT DISTINCT game_id
    FROM `nba-props-platform.nba_raw.bdl_box_scores`
    WHERE game_date = '{yesterday}'
"""
```

The actual table is `bdl_player_boxscores`. This caused the query to fail with:
```
ERROR: 404 Not found: Table nba-props-platform:nba_raw.bdl_box_scores was not found
```

When the query failed, `post_game_window_3` workflow (which includes BigDataBall PBP) couldn't determine which games needed collection and silently failed.

**Fix:** Changed table reference to correct name:
```python
# AFTER (fixed)
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
```

**File Changed:** `orchestration/master_controller.py:496`

---

### Issue 2: Injury Report Not in BigQuery

**Symptom:** `nbac_injury_report` table showed latest date as 2025-06-22 (end of last season), but GCS had files up to 2025-12-20.

**Root Cause:** Two issues:

1. **Phase 2 PROCESSOR_REGISTRY missing entry:** The scraper publishes to `nba-com/injury-report-data/`, but `main_processor_service.py` had no registry entry for this path.

2. **Phase 2 was logging:** "No processor found for file: nba-com/injury-report-pdf/..."

The injury report scraper outputs to TWO paths:
- `nba-com/injury-report-pdf/` (raw PDF)
- `nba-com/injury-report-data/` (extracted JSON)

Neither was in PROCESSOR_REGISTRY.

**Fix:** Added import and registry entry:

```python
# Added import
from data_processors.raw.nbacom.nbac_injury_report_processor import NbacInjuryReportProcessor

# Added to PROCESSOR_REGISTRY
'nba-com/injury-report-data': NbacInjuryReportProcessor,
```

**File Changed:** `data_processors/raw/main_processor_service.py`

---

### Issue 3: BettingPros Never Ran This Season

**Symptom:** `bettingpros_player_points_props` table showed latest date as 2025-06-22.

**Root Cause:** BettingPros scrapers (`bp_events`, `bp_player_props`) were defined in `scrapers/registry.py` but **never added to any workflow** in `config/workflows.yaml`.

**Fix:**

1. Added scraper definitions to `config/workflows.yaml`:
```yaml
bp_events:
  name: "bp_events"
  description: "BettingPros event IDs (MUST complete before player props)"
  module: "scrapers.bettingpros.bp_events"
  critical: false
  dependency_for: ["bp_player_props"]
  processor_name: "p2_bettingpros_events"
  estimated_duration_seconds: 30

bp_player_props:
  name: "bp_player_props"
  description: "BettingPros player prop betting lines"
  module: "scrapers.bettingpros.bp_player_props"
  critical: false
  depends_on: "bp_events"
  processor_name: "p2_bettingpros_player_props"
  estimated_duration_seconds: 60
```

2. Added to `betting_lines` workflow execution_plan:
```yaml
execution_plan:
  step_1:
    type: "sequential"
    scrapers:
      - oddsa_events
      - bp_events  # NEW
  step_2:
    type: "parallel"
    depends_on: ["oddsa_events", "bp_events"]
    scrapers:
      - oddsa_player_props
      - oddsa_game_lines
      - bp_player_props  # NEW
```

**File Changed:** `config/workflows.yaml`

---

## Deployments

### Phase 1 Scrapers
```
Service: nba-phase1-scrapers
Revision: nba-phase1-scrapers-00025-xkg
Changes: master_controller.py fix, workflows.yaml updates
```

### Phase 2 Raw Processors
```
Service: nba-phase2-raw-processors
Revision: nba-phase2-raw-processors-00021-4jv
Changes: injury report processor registry entry
```

---

## Verification

### Evaluate Endpoint Test
```bash
# Called at 17:18 ET
curl -X POST ".../evaluate"
# Response shows all 7 workflows evaluated correctly
# post_game_window_3 shows "Not in time window" (correct, it's not 4 AM)
```

### Health Checks
- Phase 1 Scrapers: `healthy`
- Phase 2 Processors: `healthy`

---

## Remaining Work

### Backfill Required

1. **BigDataBall PBP (Dec 17-21)**
   - 5 days of missing data
   - GCS has files up to Dec 16, BigQuery same

2. **Injury Report (Current Season)**
   - GCS has files through Dec 20
   - Need to republish/process these files through Phase 2

3. **BettingPros (Current Season)**
   - Will start collecting with next `betting_lines` run
   - Consider backfill if historical data needed

### Backfill Commands

```bash
# BigDataBall PBP backfill (Phase 1 scraper)
# Need to run the post_game_window_3 scrapers for missed dates

# Injury Report backfill (Phase 2 processor)
# Files exist in GCS, just need to reprocess
PYTHONPATH=. .venv/bin/python -c "
from backfill_jobs.raw.nbac_injury_report.nbac_injury_report_raw_backfill import NbacInjuryReportBackfill
backfill = NbacInjuryReportBackfill()
backfill.run_backfill(start_date='2025-10-22', end_date='2025-12-20')
"
```

---

## Prevention Recommendations

### 1. Add Integration Test for Table Names

Create a test that verifies all BigQuery table references in orchestration code actually exist:

```python
# tests/orchestration/test_table_references.py
def test_master_controller_table_references():
    """Verify all table names in master_controller.py exist in BigQuery."""
    # Extract table references from code
    # Check each exists
```

### 2. Add PROCESSOR_REGISTRY Completeness Check

Ensure every scraper that outputs to GCS has a corresponding Phase 2 processor:

```python
# tests/integration/test_processor_coverage.py
def test_all_scrapers_have_processors():
    """Verify every scraper's GCS output path has a matching processor."""
```

### 3. Add Workflow Coverage Check

Ensure every defined scraper is included in at least one workflow:

```python
# tests/config/test_workflow_coverage.py
def test_all_scrapers_in_workflows():
    """Verify every scraper definition is used in at least one workflow."""
```

### 4. Data Freshness Monitoring

Add alerting for data freshness beyond expected thresholds:
- BigDataBall: Alert if > 2 days stale
- Injury Report: Alert if no data for game day
- BettingPros: Alert if > 1 day stale

---

## Files Changed

| File | Change |
|------|--------|
| `orchestration/master_controller.py` | Fixed table name `bdl_box_scores` → `bdl_player_boxscores` |
| `data_processors/raw/main_processor_service.py` | Added `NbacInjuryReportProcessor` import and registry entry |
| `config/workflows.yaml` | Added BettingPros scrapers and included in `betting_lines` workflow |

---

## Git Commits

```
(pending commit after verification)
```

---

## Next Session Tasks

1. Run backfills for BigDataBall and injury report
2. Verify data flowing at next 4 AM window
3. Consider adding integration tests for prevention
4. Check BettingPros runs with next `betting_lines` window

---

## Quick Reference

### Check Data Freshness
```bash
bq query --use_legacy_sql=false '
SELECT "bigdataball_play_by_play" as tbl, MAX(game_date) FROM nba_raw.bigdataball_play_by_play WHERE game_date >= "2025-12-01"
UNION ALL SELECT "nbac_injury_report", MAX(report_date) FROM nba_raw.nbac_injury_report WHERE report_date >= "2025-01-01"
UNION ALL SELECT "bettingpros_player_points_props", MAX(game_date) FROM nba_raw.bettingpros_player_points_props WHERE game_date >= "2025-01-01"
ORDER BY tbl'
```

### Check Workflow Decisions
```bash
bq query --use_legacy_sql=false '
SELECT workflow_name, action, decision_time
FROM nba_orchestration.workflow_decisions
WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
AND workflow_name IN ("post_game_window_3", "betting_lines", "injury_discovery")
ORDER BY decision_time DESC
LIMIT 20'
```
