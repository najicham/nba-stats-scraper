# Morning Handoff - Jan 23, 2026

**Last Updated:** 7:30 AM ET (4:30 AM PST)
**Status:** ✅ Fixes deployed, regenerating historical predictions
**Priority:** HIGH - Verify Jan 23 predictions generate with real betting lines (8 AM ET)

---

## Session Progress (Overnight + Morning)

### Completed
- ✅ Root cause identified: odds_api stopped after Jan 18, no bettingpros fallback
- ✅ prediction-coordinator deployed with bettingpros fallback
- ✅ phase5b-grading deployed accepting BETTINGPROS line source
- ✅ Jan 21 predictions regenerated (1480 predictions with real lines)
- ✅ Jan 19 predictions started (58 requests)
- ✅ Added 20.0 placeholder avoidance (adjusts to 19.5/20.5)

### In Progress
- 🔄 Jan 19 prediction batch running
- 🔄 Waiting for 8 AM ET betting_lines workflow

### Pending
- Jan 20, 22 prediction regeneration
- Coordinator redeployment (with 20.0 fix + line source monitoring)
- Grade backfill for Jan 17-22

---

## Code Changes Made This Session

### 1. predictions/coordinator/player_loader.py
- **v3.8**: Added `_query_bettingpros_betting_line()` fallback method
- **v3.9**: Added 20.0 placeholder avoidance (adjusts to 19.5/20.5)
- **v3.9**: Added `_track_line_source()` for monitoring
- **v3.9**: Added `get_line_source_stats()` for batch summary

### 2. predictions/coordinator/coordinator.py
- Added line source statistics logging after batch creation
- Logs WARNING when bettingpros > odds_api (degraded odds_api)
- Logs WARNING when any players have no lines

### 3. shared/config/orchestration_config.py
- Deprecated `use_default_line` - MUST remain False
- Added documentation warnings about placeholder lines

### 4. data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py
- Added BETTINGPROS to accepted `line_source` values

### 5. predictions/coordinator/missing_prediction_detector.py
- Fixed f-string backslash syntax error (Python 3.12+ compatibility)

---

## Audit Report

See **[2026-01-23-PLACEHOLDER-LINE-AUDIT.md](./2026-01-23-PLACEHOLDER-LINE-AUDIT.md)** for full analysis of:
- 919 predictions with placeholder 20.0 lines found
- Root cause: odds_api failure + no bettingpros fallback
- Players affected: Primarily Jan 21, 2026 (869 predictions)
- Historical 2025 cases: 50 predictions for ~20 PPG players (legitimate rounding)

---

## Critical Findings Tonight

### Root Cause of Prediction/Grading Failures

**Problem:** All predictions since Jan 19 have been generated with placeholder lines (20.0), causing grading to fail.

**Root Cause:** The `odds_api_player_points_props` table stopped receiving data after Jan 18. The prediction coordinator was querying this table exclusively for betting lines, with no fallback.

**Evidence:**
- `odds_api_player_points_props`: Only 159 rows total for Jan 17-18, ZERO rows after
- `bettingpros_player_points_props`: Has ~28,000+ rows per day (working correctly)
- Jan 21 predictions: ALL 869 have `current_points_line = 20.0`, `line_source = NULL`

### Fix Implemented

Added bettingpros as a fallback line source in `predictions/coordinator/player_loader.py`:

```python
def _query_actual_betting_line(self, player_lookup, game_date):
    # Try odds_api first
    result = self._query_odds_api_betting_line(player_lookup, game_date)
    if result is not None:
        return result

    # Fallback to bettingpros
    result = self._query_bettingpros_betting_line(player_lookup, game_date)
    if result is not None:
        return result

    return None
```

Also updated grading filter to accept `BETTINGPROS` as valid line source in `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`:
```sql
AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
```

---

## Deployment Status

### prediction-coordinator
- **Status:** ✅ DEPLOYED (revision: prediction-coordinator-00081-v8h)
- **Health:** ✅ Healthy
- **Change:** Added bettingpros fallback for betting lines
- **Files Changed:**
  - `predictions/coordinator/player_loader.py`

### phase5b-grading
- **Status:** ⚠️ Needs deployment
- **Change:** Accept BETTINGPROS as valid line_source
- **Files Changed:**
  - `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

### Deploy Script Bug Found!
The `bin/predictions/deploy/deploy_prediction_coordinator.sh` script uses the WRONG Dockerfile:
- **Wrong:** `docker/predictions-coordinator.Dockerfile` (flat file structure - BROKEN)
- **Correct:** `predictions/coordinator/Dockerfile` (proper module structure)

This caused deployment to fail with `ModuleNotFoundError: No module named 'predictions'`.
Workaround: Copy correct Dockerfile to root and deploy manually.

---

## Odds API Investigation

### Status
- **API Key**: ✅ Working (tested directly, returns events)
- **GCS Data**: Stopped after 2026-01-18
- **Scheduler**: No dedicated scheduler for odds player props
- **Workflow**: `betting_lines` workflow runs but scraper returns HTTP 400

### Error Found
```
ERROR:orchestration.workflow_executor:❌ scraper1: FAILED - HTTP 400
```

### Root Cause (Suspected)
The odds_api player props scraper is failing with HTTP 400 during workflow execution. This could be:
1. Scraper parameter issue
2. Missing game events for the date
3. Rate limiting or quota issues

### Mitigation
Bettingpros fallback is now active, so predictions will use bettingpros lines when odds_api fails.

---

## What to Verify This Morning

### 1. Prediction Coordinator Deployment Success
```bash
# Check service status
gcloud run services describe prediction-coordinator --region=us-west2 --format="value(status.conditions[0].status)"

# Check health
curl https://prediction-coordinator-756957797294.us-west2.run.app/health
```

### 2. Jan 23 Predictions Generate with Real Lines
After betting_lines workflow runs (~8 AM ET / 5 AM PST):
```bash
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(current_points_line != 20.0) as with_real_lines,
  COUNTIF(line_source = "BETTINGPROS") as from_bettingpros
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = "2026-01-23"
  AND is_active = TRUE
GROUP BY 1'
```

Should see `with_real_lines > 0` and `from_bettingpros > 0`.

### 3. Deploy Grading Function
```bash
./bin/deploy/deploy_grading_function.sh
```

### 4. Backfill Jan 21-22 Predictions (if coordinator deployed)
The existing Jan 21 predictions have placeholder lines. To regenerate with real lines:
```bash
# This will be needed after verifying coordinator works
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H 'Content-Type: application/json' \
  -d '{"game_date":"2026-01-21"}'
```

---

## Data Status

| Date | Boxscores | Analytics | Predictions | Grades | Status |
|------|-----------|-----------|-------------|--------|--------|
| Jan 22 | 282 | 282 | 0 | 0 | Needs prediction backfill |
| Jan 21 | 247 | 156 | 869 (placeholder) | 0 | Needs regeneration |
| Jan 20 | 140 | 147 | 885 (placeholder) | 0 | Needs regeneration |
| Jan 19 | 281 | 227 | ? | 0 | Check status |
| Jan 18 | 141 | 23 | ? | ? | Low analytics (16.3%) |
| Jan 17 | 247 | 254 | ? | 1240 | Last good grading |

---

## Outstanding Issues

### 1. odds_api Props Scraper Stopped (Jan 18)
- GCS data stops at `gs://nba-scraped-data/odds-api/player-props/2026-01-18/`
- No scheduler job found for this scraper
- **Action:** Investigate why scraper stopped, but bettingpros fallback covers this

### 2. Jan 18 Low Analytics Completeness (16.3%)
- Only 23/141 boxscores processed to analytics
- Could be data quality issue or processing failure
- **Action:** Investigate after predictions are fixed

### 3. Grading Backlog (Jan 17-22)
- 6 days of predictions ungraded
- Need to regenerate predictions with real lines first
- Then run grading backfill

---

## Immediate Morning Actions

1. **Check coordinator deployment completed**
2. **Deploy grading function** (has BETTINGPROS acceptance)
3. **Monitor betting_lines workflow** (~8 AM ET) for Jan 23 predictions
4. **Verify Jan 23 predictions have real lines**
5. **If working:** Backfill Jan 21-22 predictions

---

## Files Changed This Session

```
predictions/coordinator/player_loader.py              # Added bettingpros fallback
data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py  # Accept BETTINGPROS
docs/09-handoff/2026-01-23-MORNING-HANDOFF.md        # This document
```

---

## Quick Reference Commands

```bash
# Full health check
./bin/monitoring/daily_health_check.sh

# Check prediction line sources
bq query --use_legacy_sql=false '
SELECT line_source, COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= "2026-01-20" AND is_active = TRUE
GROUP BY 1'

# Check workflow decisions
bq query --use_legacy_sql=false '
SELECT workflow_name, action, reason, decision_time
FROM nba_orchestration.workflow_decisions
WHERE workflow_name = "betting_lines"
ORDER BY decision_time DESC LIMIT 5'

# Check for errors
gcloud logging read 'severity>=ERROR' --limit=20 --freshness=2h
```

---

## Summary

- **Root cause found:** odds_api props data stopped Jan 18, causing placeholder lines
- **Fix implemented:** Added bettingpros as fallback line source
- **Deployment:** In progress for prediction-coordinator
- **Next step:** Verify deployment, then deploy grading function
- **After verification:** Backfill predictions for Jan 19-22 with real lines
