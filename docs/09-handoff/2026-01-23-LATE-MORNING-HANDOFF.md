# Late Morning Handoff - Jan 23, 2026

**Time:** 7:57 AM ET (4:57 AM PST)
**Status:** Fixes deployed, prediction regeneration in progress
**Priority:** Monitor 8 AM ET workflow for Jan 23 predictions

---

## Executive Summary

The overnight session identified and fixed a critical issue: **odds_api stopped providing betting lines after Jan 18**, causing all predictions to use placeholder 20.0 lines. A bettingpros fallback was implemented and deployed. Historical predictions are being regenerated.

---

## Current System State

### Coordinator
- **Status:** ✅ Healthy (revision: prediction-coordinator-00083-tvc)
- **Health URL:** https://prediction-coordinator-756957797294.us-west2.run.app/health
- **Fixes Deployed:**
  - v3.8: Bettingpros fallback for betting lines
  - v3.9: 20.0 placeholder avoidance (adjusts to 19.5/20.5)
  - v3.9: Line source tracking and monitoring

### Grading Function
- **Status:** ✅ Deployed (phase5b-grading)
- **Fix:** Accepts BETTINGPROS as valid line_source

### Predictions Status (as of 7:56 AM ET)

| Date | ACTUAL_PROP | ESTIMATED_AVG | Placeholders (20.0) | Status |
|------|-------------|---------------|---------------------|--------|
| Jan 19 | 285 | 540 | 0 | ✅ Complete |
| Jan 20 | 0 | 885 | 0 | ⚠️ Needs regeneration (batch started) |
| Jan 21 | 262 | 170 | 865 (NULL source) | ⚠️ Old placeholders need cleanup |
| Jan 22 | 449 | 160 | 0 | ✅ Complete |
| Jan 23 | - | - | - | ⏳ Waiting for 8 AM ET workflow |

### Active Batch
- **Jan 20 regeneration started:** batch_2026-01-20_1769172856
- **Players:** 81
- Check status:
```bash
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=batch_2026-01-20_1769172856" -H "X-API-Key: $API_KEY"
```

---

## Immediate Actions Required

### 1. Monitor 8 AM ET Workflow (~3 min from now)
The betting_lines workflow runs hourly 8-20 ET. Check that it runs and triggers predictions:

```bash
# Check workflow decision
bq query --use_legacy_sql=false '
SELECT workflow_name, action, reason, decision_time
FROM nba_orchestration.workflow_decisions
WHERE workflow_name = "betting_lines"
ORDER BY decision_time DESC LIMIT 3'
```

### 2. Verify Jan 23 Predictions (after ~8:30 AM ET)
After workflow completes, verify predictions have real lines:

```bash
bq query --use_legacy_sql=false '
SELECT line_source, COUNT(*) as count,
  SUM(CASE WHEN current_points_line = 20.0 THEN 1 ELSE 0 END) as placeholder
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = "2026-01-23" AND is_active = TRUE
GROUP BY 1'
```

Should see BETTINGPROS or ACTUAL_PROP with 0 placeholders.

### 3. Complete Jan 20 Regeneration
Check if batch completed:
```bash
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=batch_2026-01-20_1769172856" -H "X-API-Key: $API_KEY"
```

If not, it should complete within ~5 minutes.

### 4. Clean Up Jan 21 Placeholder Predictions
The 865 old predictions with NULL line_source need to be deactivated:

```bash
# Check old vs new predictions
bq query --use_legacy_sql=false '
SELECT line_source, is_active, COUNT(*)
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = "2026-01-21"
GROUP BY 1, 2'

# Deactivate old placeholder predictions (careful!)
# bq query --use_legacy_sql=false '
# UPDATE `nba_predictions.player_prop_predictions`
# SET is_active = FALSE
# WHERE game_date = "2026-01-21" AND line_source IS NULL'
```

### 5. Run Grading Backfill
After predictions are clean, run grading for each day:

```bash
# Trigger grading for a specific date
curl -X POST https://phase5b-grading-756957797294.us-west2.run.app \
  -H 'Content-Type: application/json' \
  -d '{"target_date": "2026-01-21", "run_aggregation": true}'
```

---

## Root Cause Summary

### Problem
All predictions since Jan 19 used placeholder 20.0 lines because:
1. `odds_api_player_points_props` stopped receiving data after Jan 18
2. The coordinator only queried odds_api, with no fallback
3. When no line found, it estimated based on player averages (~20 PPG → 20.0)

### Evidence
```
odds_api_player_points_props: 159 rows total, 0 after Jan 18
bettingpros_player_points_props: ~28,000+ rows/day (working)
```

### Fix
Added bettingpros as fallback in `predictions/coordinator/player_loader.py`:
- Query odds_api first
- If no result, query bettingpros
- Log WARNING when falling back (for visibility)
- Track line source statistics per batch

---

## Key Files Changed

```
predictions/coordinator/player_loader.py     # Bettingpros fallback + monitoring
predictions/coordinator/coordinator.py       # Line source stats logging
shared/config/orchestration_config.py        # Deprecated use_default_line
data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py  # Accept BETTINGPROS
predictions/coordinator/missing_prediction_detector.py  # Fixed f-string syntax
```

---

## Useful Commands

### Full Health Check
```bash
./bin/monitoring/daily_health_check.sh
```

### Check Prediction Line Sources
```bash
bq query --use_legacy_sql=false '
SELECT game_date, line_source, COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= "2026-01-19" AND is_active = TRUE
GROUP BY 1, 2 ORDER BY 1, 2'
```

### Check for Errors
```bash
gcloud logging read 'severity>=ERROR' --limit=20 --freshness=1h \
  --format="table(timestamp,resource.labels.service_name,textPayload)"
```

### Trigger Prediction Batch for Date
```bash
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -s -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  -d '{"game_date":"2026-01-XX"}'
```

### Check Batch Status
```bash
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=BATCH_ID" \
  -H "X-API-Key: $API_KEY"
```

---

## Outstanding Issues

### 1. Odds API Scraper Broken
- **Status:** HTTP 400 errors in workflow execution
- **API Key:** Works (tested directly)
- **Impact:** Mitigated by bettingpros fallback
- **Action:** Low priority - bettingpros provides coverage

### 2. Jan 18 Low Analytics (16.3%)
- Only 23/141 boxscores processed
- Lower priority than prediction fixes
- Investigate after predictions stabilized

### 3. Deploy Script Bug
- `bin/predictions/deploy/deploy_prediction_coordinator.sh` uses wrong Dockerfile
- Workaround: Copy `predictions/coordinator/Dockerfile` to root before deploying

---

## Task Checklist

- [ ] Monitor 8 AM ET betting_lines workflow
- [ ] Verify Jan 23 predictions have real lines (~8:30 AM)
- [ ] Confirm Jan 20 batch completes
- [ ] Deactivate Jan 21 placeholder predictions (865 rows)
- [ ] Run grading backfill for Jan 19-22
- [ ] Verify grading produces results

---

## Related Documents

- [2026-01-23-PLACEHOLDER-LINE-AUDIT.md](./2026-01-23-PLACEHOLDER-LINE-AUDIT.md) - Full audit of placeholder lines
- [2026-01-23-MORNING-HANDOFF.md](./2026-01-23-MORNING-HANDOFF.md) - Earlier morning handoff
- [2026-01-23-OVERNIGHT-MONITORING-HANDOFF.md](./2026-01-23-OVERNIGHT-MONITORING-HANDOFF.md) - Original overnight handoff

---

## Session Notes

The overnight/early morning session (11:30 PM - 8 AM ET) accomplished:
1. Identified root cause of prediction failures
2. Implemented and deployed bettingpros fallback
3. Regenerated predictions for Jan 19, 21, 22 (Jan 20 in progress)
4. Added monitoring for line source degradation
5. Created audit report of placeholder lines

The system is now much more resilient - if odds_api fails, bettingpros will provide coverage. Warnings are logged when this happens for visibility.
