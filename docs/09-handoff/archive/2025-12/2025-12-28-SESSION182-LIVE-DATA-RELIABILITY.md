# Session 182 Handoff: Live Data Reliability & Grading Architecture

**Date:** 2025-12-28
**Duration:** ~2 hours
**Status:** Complete with follow-up items

---

## Executive Summary

Fixed a critical live data pipeline issue where yesterday's games were being shown instead of today's, and implemented comprehensive reliability improvements including a new status.json endpoint for frontend visibility and a self-healing monitor.

---

## Issue Investigated

### Problem Statement
The live data endpoint (`/v1/live/latest.json`) was showing December 27's games on December 28, causing:
- Challenge grading to fail (gradeGames found no matching data)
- Test challenge for PHI @ OKC couldn't be graded
- User confusion with stale data

### Root Causes Identified

1. **Scheduler Timing Gap**
   - Scheduler ran 7 PM - 11 PM ET
   - First game (PHI @ OKC) started at 6 PM ET
   - 1 hour gap with no live exports

2. **Late-Night Date Mismatch**
   - At 1:57 AM ET, scheduler exported Dec 27's recently-finished games
   - But labeled them as Dec 28 (current ET date)
   - No date validation in code

3. **No Date Filtering**
   - BDL `/live` API returns any active games, not date-filtered
   - Code didn't validate games matched target date

4. **DST Handling Bug** (latent)
   - Hardcoded `-5 hours` offset for EST
   - Would fail during EDT (March-November)

---

## Fixes Applied

### 1. Scheduler Expansion
```bash
# Before: */3 19-23 * * * (7-11 PM ET)
# After:  */3 16-23 * * * (4-11 PM ET)

gcloud scheduler jobs update http live-export-evening \
  --location=us-west2 \
  --schedule="*/3 16-23 * * *"
```

### 2. Date Filtering Added
**Files modified:**
- `data_processors/publishing/live_scores_exporter.py`
- `data_processors/publishing/live_grading_exporter.py`

```python
# In _transform_games():
game_date = str(box.get("date", ""))[:10]
if game_date and game_date != target_date:
    skipped_games += 1
    continue
```

### 3. DST-Aware Date Handling
**File:** `orchestration/cloud_functions/live_export/main.py`

```python
def get_today_date() -> str:
    from zoneinfo import ZoneInfo
    et_tz = ZoneInfo('America/New_York')
    return datetime.now(et_tz).strftime('%Y-%m-%d')
```

### 4. Status Endpoint for Frontend
**New file:** `data_processors/publishing/status_exporter.py`

**Endpoint:** `https://storage.googleapis.com/nba-props-platform-api/v1/status.json`

```json
{
  "overall_status": "healthy",
  "services": {
    "live_data": {
      "status": "healthy",
      "age_minutes": 0.5,
      "is_stale": false,
      "games_active": true
    },
    "tonight_data": { "status": "healthy" },
    "grading": { "status": "healthy" },
    "predictions": { "status": "healthy", "predictions_count": 650 }
  },
  "known_issues": []
}
```

### 5. Live Freshness Monitor (Self-Healing)
**New files:**
- `orchestration/cloud_functions/live_freshness_monitor/main.py`
- `orchestration/cloud_functions/live_freshness_monitor/requirements.txt`
- `bin/deploy/deploy_live_freshness_monitor.sh`

**Scheduler:** `*/5 16-23,0-1 * * *` (every 5 min, 4 PM - 1 AM ET)

**Behavior:**
1. Checks if games are active (via NBA.com API)
2. Verifies live data freshness (< 10 min old)
3. Auto-triggers live-export if stale
4. Alerts on persistent issues

---

## Deployments Made

| Component | Version | Status |
|-----------|---------|--------|
| `live-export` Cloud Function | v11 | ✅ Deployed |
| `live-freshness-monitor` Cloud Function | v1 | ✅ Deployed |
| `live-freshness-monitor` Scheduler | - | ✅ Created |
| `live-export-evening` Scheduler | Updated | ✅ 4-11 PM ET |
| `bdl-live-boxscores-evening` Scheduler | Updated | ✅ 4-11 PM ET |

---

## Files Created/Modified

### New Files
```
data_processors/publishing/status_exporter.py
orchestration/cloud_functions/live_freshness_monitor/main.py
orchestration/cloud_functions/live_freshness_monitor/requirements.txt
bin/deploy/deploy_live_freshness_monitor.sh
tests/publishing/test_live_scores_exporter.py
docs/08-projects/current/live-data-reliability/README.md
docs/08-projects/current/LIVE-DATA-PIPELINE-ANALYSIS.md
docs/api/FRONTEND_LIVE_DATA_GUIDE.md
```

### Modified Files
```
data_processors/publishing/live_scores_exporter.py  (date filtering)
data_processors/publishing/live_grading_exporter.py (date filtering)
orchestration/cloud_functions/live_export/main.py   (DST fix, status export)
docs/api/FRONTEND_API_REFERENCE.md                  (added status endpoint)
docs/03-phases/phase6-publishing/README.md          (updated schedulers)
```

---

## Verification Results

### PHI @ OKC Game (Test Challenge)
- **Game Status:** Final (PHI 129, OKC 104)
- **Live Data:** ✅ Correctly showing Dec 28 games
- **Live Grading:** ✅ Players graded with actual stats

| Player | Predicted | Actual | Line | Rec | Result |
|--------|-----------|--------|------|-----|--------|
| Tyrese Maxey | 25.7 | 28 | 26.5 | OVER | ✅ Correct |
| SGA | 25.0 | 27 | 31.5 | OVER | ❌ Incorrect |
| Jared McCain | 4.8 | 10 | 7.5 | UNDER | ❌ Incorrect |

---

## Architecture Insight: Backend Grading vs Frontend Grading

### Current State
- **Frontend (gradeGames):** Grades individual challenge picks in Firestore
- **Backend (live_grading_exporter):** Grades predictions for `/v1/live-grading/latest.json`

### Recommended Enhancement
The backend should also persist graded predictions to BigQuery for:

1. **Other Frontend Pages**
   - Results page needs graded predictions
   - Player profiles need historical accuracy
   - Trends/analytics need graded data

2. **Historical Analysis**
   - Can't query GCS JSON files efficiently
   - Need BigQuery table for graded predictions

3. **Proposed Architecture**
```
Phase 5 (Predictions)
    ↓
BigQuery: nba_predictions.player_prop_predictions
    ↓
[NEW] Phase 5b (Grading) - runs after games end
    ↓
BigQuery: nba_predictions.graded_predictions (or update existing)
    ↓
Phase 6 (Publishing)
    ↓
GCS: /results/{date}.json, /live-grading/{date}.json
```

4. **Benefits**
   - Single source of truth for graded data
   - Frontend can query BigQuery via API or use exported JSON
   - Historical analysis possible
   - Challenge grading can use same data

---

## Follow-Up Items for Next Session

### High Priority
1. **Backend Grading Persistence**
   - Design schema for graded predictions table
   - Implement Phase 5b grading processor
   - Update results_exporter to use graded data

2. **Verify Challenge Grading**
   - Check if frontend gradeGames ran successfully
   - Verify Firestore challenge document updated

### Medium Priority
3. **Cloud Monitoring Dashboard**
   - Create dashboard for live data freshness
   - Set up alerting policies

4. **Integration Tests**
   - Add tests for date filtering
   - Add tests for self-healing flow

### Low Priority
5. **Dynamic Scheduler**
   - Schedule based on actual game times
   - Avoid running during off-hours

---

## Quick Commands

```bash
# Check live data status
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/status.json" | jq '.'

# Check live grading
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/live-grading/latest.json" | jq '.summary'

# Manually trigger live export
curl -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/live-export" \
  -H "Content-Type: application/json" \
  -d '{"target_date": "today"}'

# Manually trigger freshness monitor
curl -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/live-freshness-monitor"

# Check scheduler status
gcloud scheduler jobs list --location=us-west2 | grep live

# Check function logs
gcloud functions logs read live-export --region=us-west2 --limit=20
gcloud functions logs read live-freshness-monitor --region=us-west2 --limit=20
```

---

## Documentation Created

| Document | Path | Purpose |
|----------|------|---------|
| Frontend Live Data Guide | `docs/api/FRONTEND_LIVE_DATA_GUIDE.md` | Integration guide with TypeScript examples |
| Live Data Pipeline Analysis | `docs/08-projects/current/LIVE-DATA-PIPELINE-ANALYSIS.md` | Root cause analysis |
| Live Data Reliability Project | `docs/08-projects/current/live-data-reliability/README.md` | Improvement plan |

---

## Commits Made

1. `3b70a13` - fix: Live data pipeline - date filtering and DST handling
2. `932bd79` - feat: Live data reliability improvements - status.json and freshness monitor
3. `02f589b` - docs: Add frontend live data guide and update API reference

---

## Summary

This session resolved a critical issue where live data was showing the wrong day's games. The fix included:
- Expanding scheduler windows (4 PM instead of 7 PM)
- Adding date filtering to prevent mismatch
- Fixing DST handling
- Creating status.json for frontend visibility
- Deploying self-healing monitor

The backend is now correctly providing graded data for PHI @ OKC. The frontend gradeGames function should be able to use this data, but verification of Firestore needs to happen from the frontend side.

**Key insight:** Consider persisting graded predictions to BigQuery so other frontend pages (results, profiles, trends) can access graded data without relying on the challenge grading system.
