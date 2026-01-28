# Data Quality Monitoring Deployment Log

## Deployment Date: 2026-01-28

### Overview
Successfully deployed the data quality monitoring Cloud Function to detect critical data quality issues before they impact production.

### Deployment Details

**Function Name:** `data-quality-alerts`
**Region:** `us-west2`
**Runtime:** `python311`
**Timeout:** `540s` (9 minutes)
**Memory:** `512MB`
**Function URL:** `https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app`

### Environment Variables
- `GCP_PROJECT_ID`: `nba-props-platform`
- `SLACK_WEBHOOK_URL_ERROR`: Retrieved from Secret Manager (`slack-webhook-monitoring-error`)
- `SLACK_WEBHOOK_URL_WARNING`: Retrieved from Secret Manager (`slack-webhook-monitoring-warning`)

### Scheduler Configuration

**Job Name:** `data-quality-alerts-job`
**Schedule:** `0 19 * * *` (Daily at 7:00 PM ET)
**Time Zone:** `America/New_York`
**HTTP Method:** `GET`
**Target:** `https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app/`

### Deployment Steps Executed

1. **Reviewed deployment configuration**
   - Examined `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts/deploy.sh`
   - Reviewed `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts/README.md`
   - Confirmed `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts/main.py`

2. **Retrieved Slack webhook URLs from Secret Manager**
   ```bash
   gcloud secrets versions access latest --secret="slack-webhook-monitoring-error"
   gcloud secrets versions access latest --secret="slack-webhook-monitoring-warning"
   ```

3. **Fixed table reference bug**
   - **Issue:** Code referenced `nba_raw.nbacom_schedule` (incorrect)
   - **Fix:** Updated to `nba_raw.nbac_schedule` (correct)
   - **Files updated:**
     - `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts/main.py`
     - `/home/naji/code/nba-stats-scraper/monitoring/queries/low_usage_coverage.sql`

4. **Deployed Cloud Function**
   ```bash
   gcloud functions deploy data-quality-alerts \
     --gen2 \
     --region us-west2 \
     --source /home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts \
     --runtime python311 \
     --entry-point check_data_quality \
     --trigger-http \
     --allow-unauthenticated \
     --timeout=540 \
     --memory=512MB \
     --set-env-vars GCP_PROJECT_ID=nba-props-platform,SLACK_WEBHOOK_URL_ERROR=...,SLACK_WEBHOOK_URL_WARNING=... \
     --project nba-props-platform
   ```

5. **Created Cloud Scheduler job**
   ```bash
   gcloud scheduler jobs create http data-quality-alerts-job \
     --location=us-west2 \
     --schedule="0 19 * * *" \
     --time-zone="America/New_York" \
     --uri="https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app/" \
     --http-method=GET \
     --description="Daily data quality checks for NBA predictions pipeline" \
     --project=nba-props-platform
   ```

6. **Tested deployment**
   - Tested with dry run for 2026-01-26 (known issues)
   - Tested with dry run for 2026-01-28 (current date)
   - Manually triggered scheduler job
   - Verified all 4 checks execute successfully

### Test Results

#### Test 1: Historical Data (2026-01-26)
```json
{
  "game_date": "2026-01-26",
  "overall_status": "CRITICAL",
  "checks_run": 4,
  "critical_issues": 1,
  "warnings": 2,
  "results": {
    "zero_predictions": {
      "level": "CRITICAL",
      "message": "ZERO PREDICTIONS: No predictions generated for 2026-01-26 despite 7 games scheduled."
    },
    "usage_rate": {
      "level": "WARNING",
      "message": "LOW COVERAGE: Only 58.6% of records have usage_rate."
    },
    "duplicates": {
      "level": "OK",
      "message": "No duplicate records detected"
    },
    "prop_lines": {
      "level": "WARNING",
      "message": "WARNING: Only 48.5% of players have prop lines."
    }
  }
}
```

#### Test 2: Current Data (2026-01-28)
```json
{
  "game_date": "2026-01-28",
  "overall_status": "CRITICAL",
  "checks_run": 4,
  "critical_issues": 2,
  "warnings": 0,
  "results": {
    "zero_predictions": {
      "level": "CRITICAL",
      "message": "ZERO PREDICTIONS: No predictions generated for 2026-01-28 despite 11 games scheduled."
    },
    "usage_rate": {
      "level": "OK",
      "message": "No boxscore data yet"
    },
    "duplicates": {
      "level": "OK",
      "message": "No duplicate records detected"
    },
    "prop_lines": {
      "level": "CRITICAL",
      "message": "CRITICAL: 0% of 305 players have prop lines."
    }
  }
}
```

### Checks Implemented

1. **Zero Predictions Check (P0)**
   - Detects when no predictions are generated despite games being scheduled
   - Alert Level: CRITICAL
   - Channel: #app-error-alerts

2. **Usage Rate Coverage Check (P1)**
   - Detects low usage_rate coverage in player_game_summary
   - Alert Level: WARNING (<80%), CRITICAL (<50%)
   - Channel: #nba-alerts or #app-error-alerts

3. **Duplicate Detection Check (P2)**
   - Detects duplicate records in player_game_summary
   - Alert Level: INFO (≤5), WARNING (≤20), CRITICAL (>20)
   - Channel: #nba-alerts or #app-error-alerts

4. **Prop Lines Check (P1)**
   - Detects when players are missing betting lines
   - Alert Level: INFO (<80%), WARNING (<50%), CRITICAL (0% or <20%)
   - Channel: #nba-alerts or #app-error-alerts

### Monitoring & Operations

#### View Function Logs
```bash
gcloud functions logs read data-quality-alerts --gen2 --region us-west2 --limit 50 --project nba-props-platform
```

#### Check Function Status
```bash
gcloud functions describe data-quality-alerts --gen2 --region us-west2 --project nba-props-platform
```

#### View Scheduler Jobs
```bash
gcloud scheduler jobs list --location=us-west2 --project nba-props-platform
```

#### Manually Trigger Job
```bash
gcloud scheduler jobs run data-quality-alerts-job --location=us-west2 --project nba-props-platform
```

#### Test with Dry Run
```bash
# Test all checks without sending alerts
curl "https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app?dry_run=true"

# Test with specific date
curl "https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app?game_date=2026-01-26&dry_run=true"

# Test specific checks only
curl "https://data-quality-alerts-f7p3g7f6ya-wl.a.run.app?checks=zero_predictions,prop_lines&dry_run=true"
```

### Issues Fixed During Deployment

1. **Table Name Correction**
   - **Issue:** Referenced `nba_raw.nbacom_schedule` which doesn't exist
   - **Root Cause:** Incorrect table name in queries
   - **Fix:** Updated to correct table name `nba_raw.nbac_schedule`
   - **Impact:** `usage_rate` check was failing with 404 error

2. **Field Name Correction**
   - **Issue:** Used `game_status = 'Final'` instead of `game_status_text = 'Final'`
   - **Root Cause:** Incorrect field reference
   - **Fix:** Updated to use `game_status_text` field
   - **Impact:** Game completion detection now works correctly

### Next Steps

1. **Monitor alert accuracy** over the next few days
   - Check for false positives
   - Verify alerts are sent to correct channels
   - Adjust thresholds if needed

2. **Consider additional checks**
   - Coordinator stuck detection
   - Processing order violation detection
   - Integration with existing prediction_health_alert

3. **Auto-remediation** (future enhancement)
   - Automatically re-trigger Phase 3 when prop lines missing
   - Auto-restart coordinator when stuck

### Success Criteria

- ✅ Function deployed successfully
- ✅ All 4 checks execute without errors
- ✅ Scheduler job created and configured
- ✅ Manual test execution successful
- ✅ Dry run tests show correct alerts for known issues
- ✅ Environment variables configured with Slack webhooks
- ✅ Documentation updated

### Cost Estimate

- **BigQuery:** ~400 MB scanned per day = $0.002/day = $0.73/year
- **Cloud Function:** 1 invocation per day × 10 seconds = Free (within free tier)
- **Cloud Scheduler:** 1 job = $0.10/month = $1.20/year
- **Total:** ~$2/year

**ROI:** One prevented incident saves hours of investigation time and prevents user impact.

### Related Documentation

- [Cloud Function README](/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/data_quality_alerts/README.md)
- [Monitoring Plan](/home/naji/code/nba-stats-scraper/docs/08-projects/current/2026-01-27-data-quality-investigation/MONITORING-PLAN.md)
- [Root Cause Analysis](/home/naji/code/nba-stats-scraper/docs/08-projects/current/2026-01-27-data-quality-investigation/ROOT-CAUSE-ANALYSIS.md)
- [SQL Queries](/home/naji/code/nba-stats-scraper/monitoring/queries/)

### Deployment Verification Checklist

- [x] Function deployed to production
- [x] Environment variables set correctly
- [x] Slack webhooks configured and tested
- [x] Scheduler job created and enabled
- [x] Manual trigger test successful
- [x] Dry run tests show expected results
- [x] Function logs accessible
- [x] Documentation updated
- [x] Code changes committed

### Conclusion

The data quality monitoring Cloud Function has been successfully deployed and is now running daily at 7 PM ET. The system will automatically detect and alert on the following critical issues:

1. Zero predictions generated
2. Low usage_rate coverage
3. Duplicate records
4. Missing prop lines

This deployment addresses the root causes identified in the 2026-01-26 incident and provides early warning for similar issues in the future.

---

**Deployed by:** Claude Code
**Deployment Date:** 2026-01-28
**Deployment Time:** 00:20 UTC
**Status:** ✅ COMPLETE
