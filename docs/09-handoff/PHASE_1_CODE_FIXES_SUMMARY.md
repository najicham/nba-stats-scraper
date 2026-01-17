# PHASE 1: CODE FIXES COMPLETE ✅
**Date**: 2026-01-16, Session 76
**Status**: Ready for Testing & Deployment
**Priority**: CRITICAL - Deploy BEFORE any data regeneration

---

## SUMMARY

Phase 1 code fixes are complete. Three critical files have been modified to prevent placeholder lines from ever entering the system again.

**Impact**: These changes will prevent the placeholder line issue from recurring when we regenerate predictions in Phases 2-4.

---

## FILES MODIFIED

### 1. predictions/worker/worker.py

**Changes**:
1. Added `validate_line_quality()` function (lines ~320-371)
   - Validates predictions before BigQuery write
   - Checks for line_value = 20.0 (placeholder)
   - Checks for missing/invalid line_source
   - Checks for NULL lines with has_prop_line=TRUE
   - Returns validation error if issues found

2. Added validation call before BigQuery write (line ~482)
   - Blocks writes if validation fails
   - Sends Slack alert on failure
   - Returns 500 to trigger Pub/Sub retry

**Why This Matters**:
- Last line of defense before bad data reaches database
- Immediate visibility via Slack alerts
- Prevents silent data corruption

---

### 2. predictions/worker/data_loaders.py

**Changes**:
1. Line ~317: Removed `season_avg = ... else 20.0`
   - Now returns empty list if no historical games
   - Logs warning for visibility
   - Skips player instead of using placeholder

2. Line ~622: Removed `season_avg = ... else 20.0`
   - Same fix for batch loading function
   - Uses `continue` to skip player in batch

**Why This Matters**:
- Eliminates root cause #1 (the 20.0 default)
- Forces explicit handling of missing data
- Makes the problem visible instead of silent

---

### 3. data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py

**Changes**:
- Line ~317: Added WHERE filters to prediction loading query:
  ```sql
  AND current_points_line IS NOT NULL
  AND current_points_line != 20.0
  AND line_source IN ('ACTUAL_PROP', 'ODDS_API')
  AND has_prop_line = TRUE
  ```

**Why This Matters**:
- Prevents placeholder data from contaminating performance metrics
- Win rates will only include valid predictions
- Grading becomes trustworthy again

---

## TESTING CHECKLIST

Before deploying, test:

### Local Testing
- [ ] Worker validation gate blocks line_value = 20.0
- [ ] Worker validation gate allows valid lines through
- [ ] Data loader returns empty list for players with no history
- [ ] Grading query excludes placeholder predictions

### Integration Testing (Staging)
- [ ] Deploy to staging environment
- [ ] Trigger prediction for player with no history (should skip)
- [ ] Trigger prediction with valid line (should succeed)
- [ ] Check Slack webhook receives alerts
- [ ] Verify grading excludes invalid data

### Validation Queries
```sql
-- Should return 0 after deployment
SELECT COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-16'  -- Today onwards
  AND current_points_line = 20.0;

-- Should show only ACTUAL_PROP
SELECT DISTINCT line_source
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-01-16';
```

---

## DEPLOYMENT PLAN

**Order**:
1. Deploy worker.py to Cloud Run (validation gate)
2. Deploy data_loaders.py (part of worker deployment)
3. Deploy grading processor to Cloud Functions

**Commands**:
```bash
# 1. Deploy worker with validation gate
cd /home/naji/code/nba-stats-scraper
gcloud run deploy nba-prediction-worker-prod \
    --region=us-west2 \
    --source=predictions/worker \
    --memory=2Gi \
    --timeout=540s \
    --set-env-vars SLACK_WEBHOOK_URL_WARNING=$SLACK_WEBHOOK_URL_WARNING

# 2. Deploy grading processor
gcloud functions deploy prediction-accuracy-grading-prod \
    --region=us-west2 \
    --runtime=python312 \
    --source=data_processors/grading/prediction_accuracy \
    --entry-point=main \
    --trigger-topic=nba-grading-trigger \
    --memory=512MB \
    --timeout=540s

# 3. Verify deployments
gcloud run services describe nba-prediction-worker-prod --region=us-west2
gcloud functions describe prediction-accuracy-grading-prod --region=us-west2
```

---

## ROLLBACK PLAN

If deployments cause issues:

```bash
# Rollback worker
gcloud run services update-traffic nba-prediction-worker-prod \
    --region=us-west2 \
    --to-revisions=PREVIOUS_REVISION=100

# Rollback grading
gcloud functions deploy prediction-accuracy-grading-prod \
    --region=us-west2 \
    --source=gs://backup-bucket/grading-processor-backup
```

**Note**: Grading changes are safe (just filters data). Worker changes are higher risk.

---

## EXPECTED BEHAVIOR AFTER DEPLOYMENT

### For New Predictions:
- Players without historical games: Skipped (logged warning)
- Predictions with line_value = 20.0: Blocked (Slack alert sent)
- Valid predictions: Proceed normally

### For Grading:
- Only predictions with real sportsbook lines are graded
- Performance metrics exclude placeholder data
- Win rates will reflect true performance (50-65% range)

### For Monitoring:
- Slack alerts fire immediately if placeholders detected
- Logs show warnings for skipped players
- Pub/Sub retries if validation fails (allows enrichment to fix)

---

## NEXT STEPS

After Phase 1 deployment:
1. Monitor for 24 hours to ensure stability
2. Verify no Slack alerts for placeholder lines
3. Check that new predictions have 0% placeholders
4. Proceed to Phase 2 (delete invalid data)

---

## RISK ASSESSMENT

**Risk Level**: LOW-MEDIUM

**Risks**:
- Worker validation may be too strict (blocks legitimate edge cases)
- Data loader changes may skip too many players
- Grading filters may exclude valid predictions

**Mitigations**:
- Validation has clear error messages for debugging
- Skipped players are logged with warnings
- Grading filters are conservative (only exclude obvious placeholders)
- Can rollback deployment quickly if needed

---

## SUCCESS CRITERIA

✅ Worker deployed successfully
✅ Grading deployed successfully
✅ Zero new predictions with line_value = 20.0
✅ Slack alerts functional
✅ Grading shows 0% placeholder rate
✅ Performance metrics exclude invalid data

---

**END OF PHASE 1 SUMMARY**

**Next Phase**: Phase 2 - Delete Invalid Data (after Phase 1 deployment and 24hr monitoring)
