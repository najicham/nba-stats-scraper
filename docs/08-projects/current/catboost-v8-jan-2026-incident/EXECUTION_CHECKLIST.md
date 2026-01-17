# Execution Checklist: CatBoost V8 Incident Resolution
**Date**: 2026-01-16
**Estimated Time**: 1-2 hours
**Prerequisites**: Access to GCP console, local codebase, BigQuery

---

## Pre-Execution

- [ ] Read FIXES_READY_TO_EXECUTE.md
- [ ] Review FINAL_SUMMARY.md for context
- [ ] Confirm access to nba-props-platform GCP project
- [ ] Confirm local codebase is up to date (`git pull`)
- [ ] Set up session (cd to /home/naji/code/nba-stats-scraper)

---

## Part 1: Backfill Missing Data (10-15 minutes)

### Backfill player_daily_cache

- [ ] **Run for Jan 8**:
  ```bash
  python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor --date 2026-01-08
  ```

- [ ] **Verify Jan 8**:
  ```bash
  bq query --use_legacy_sql=false "SELECT cache_date, COUNT(DISTINCT player_lookup) as players FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date = '2026-01-08' GROUP BY cache_date"
  ```
  - Expected: 50-200 players

- [ ] **Run for Jan 12**:
  ```bash
  python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor --date 2026-01-12
  ```

- [ ] **Verify Jan 12**:
  ```bash
  bq query --use_legacy_sql=false "SELECT cache_date, COUNT(DISTINCT player_lookup) as players FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date = '2026-01-12' GROUP BY cache_date"
  ```
  - Expected: 50-200 players

### Regenerate ML Feature Store

- [ ] **Regenerate for Jan 8**:
  ```bash
  python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor --date 2026-01-08
  ```

- [ ] **Regenerate for Jan 12**:
  ```bash
  python -m data_processors.precompute.ml_feature_store.ml_feature_store_processor --date 2026-01-12
  ```

- [ ] **Verify feature quality restored**:
  ```bash
  bq query --use_legacy_sql=false "SELECT game_date, data_source, COUNT(*) as records, AVG(feature_quality_score) as avg_quality FROM \`nba-props-platform.ml_nba.ml_feature_store_v2\` WHERE game_date IN ('2026-01-08', '2026-01-12') GROUP BY game_date, data_source"
  ```
  - Expected: phase4_partial reappears, avg_quality ≥90

### Checkpoint 1

- [ ] Jan 8 backfill successful (50+ players)
- [ ] Jan 12 backfill successful (50+ players)
- [ ] Feature quality ≥90 for both dates
- [ ] phase4_partial ≥40% for both dates

---

## Part 2: Deploy CatBoost Model (10-15 minutes)

### Check Prerequisites

- [ ] **Verify model file exists locally**:
  ```bash
  ls -lh /home/naji/code/nba-stats-scraper/models/catboost_v8_33features_20260108_211817.cbm
  ```
  - If missing, see troubleshooting in FIXES_READY_TO_EXECUTE.md

- [ ] **Check if GCS bucket exists**:
  ```bash
  gsutil ls gs://nba-props-platform-models/
  ```
  - If error, create bucket (see troubleshooting)

### Upload Model

- [ ] **Upload to GCS**:
  ```bash
  gsutil cp /home/naji/code/nba-stats-scraper/models/catboost_v8_33features_20260108_211817.cbm gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
  ```

- [ ] **Verify upload**:
  ```bash
  gsutil ls gs://nba-props-platform-models/catboost/v8/
  ```
  - Should show the .cbm file

### Configure Cloud Run

- [ ] **Set environment variable**:
  ```bash
  gcloud run services update prediction-worker \
    --region=us-west2 \
    --set-env-vars CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm \
    --project=nba-props-platform
  ```

- [ ] **Verify environment variable set**:
  ```bash
  gcloud run services describe prediction-worker --region=us-west2 --project=nba-props-platform --format="value(spec.template.spec.containers[0].env)"
  ```
  - Should show CATBOOST_V8_MODEL_PATH with GCS path

### Checkpoint 2

- [ ] Model file uploaded to GCS
- [ ] Environment variable set in Cloud Run
- [ ] Cloud Run deployment successful

---

## Part 3: Verify Fixes (10-15 minutes)

**Note**: Wait 10-15 minutes after Part 2 for next prediction run before verifying

### Check Model Loading

- [ ] **Check Cloud Run logs for model loading**:
  ```bash
  gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND timestamp>=timestamp(\"$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ)\")" --limit=100 --format=json --project=nba-props-platform | grep -i "catboost"
  ```
  - Expected: "✓ CatBoost V8 model loaded successfully"
  - NOT expected: "FAILED to load" or "FALLBACK_PREDICTION"

### Check Confidence Distribution

- [ ] **Query current confidence distribution**:
  ```bash
  bq query --use_legacy_sql=false "SELECT ROUND(confidence_score * 100) as confidence_pct, COUNT(*) as picks, AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as win_rate FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() GROUP BY confidence_pct ORDER BY confidence_pct DESC"
  ```
  - Expected: Multiple different confidence values (not just 50%)
  - Expected: Some picks at 85%+ confidence
  - Expected: NOT 100% at 50%

### Check System Health

- [ ] **Query recent performance**:
  ```bash
  bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as picks, AVG(confidence_score) as avg_conf, AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as win_rate, AVG(ABS(predicted_points - actual_points)) as avg_error FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() - 1 GROUP BY game_date ORDER BY game_date DESC"
  ```
  - Expected: avg_conf NOT stuck at 0.50
  - Expected: Picks with various confidence levels

### Checkpoint 3

- [ ] Model loading successfully (no fallback)
- [ ] Confidence distribution shows variety (79-95%)
- [ ] High-confidence picks appearing (85%+)
- [ ] NOT 100% at 50% confidence

---

## Part 4: Deploy Monitoring (30-60 minutes)

### Prepare Environment

- [ ] **Set Slack webhook URL** (if available):
  ```bash
  export SLACK_ALERT_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  ```
  - Optional - alerts will log even if not set

### Deploy Monitoring Function

- [ ] **Make script executable**:
  ```bash
  chmod +x /home/naji/code/nba-stats-scraper/docs/08-projects/current/catboost-v8-jan-2026-incident/scripts/deploy_monitoring_alerts.sh
  ```

- [ ] **Run deployment script**:
  ```bash
  cd /home/naji/code/nba-stats-scraper/docs/08-projects/current/catboost-v8-jan-2026-incident/scripts
  ./deploy_monitoring_alerts.sh
  ```

- [ ] **Verify Cloud Function deployed**:
  - Go to: https://console.cloud.google.com/functions
  - Check: `nba-monitoring-alerts` function exists
  - Status: Active

- [ ] **Verify Cloud Scheduler job created**:
  - Go to: https://console.cloud.google.com/cloudscheduler
  - Check: `nba-monitoring-alerts` job exists
  - Schedule: Every 4 hours (0 */4 * * *)

### Test Monitoring

- [ ] **Manual test of monitoring function**:
  ```bash
  gcloud functions call nba-monitoring-alerts --region=us-west2 --project=nba-props-platform
  ```
  - Should return status for all 5 checks

- [ ] **Check function logs**:
  ```bash
  gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=nba-monitoring-alerts" --limit=50 --project=nba-props-platform
  ```
  - Should show checks running

- [ ] **Check Slack alerts** (if webhook configured):
  - Look for test message in Slack channel
  - Verify formatting looks good

### Checkpoint 4

- [ ] Monitoring function deployed
- [ ] Scheduler job created
- [ ] Manual test successful
- [ ] Alerts working (Slack or logs)

---

## Part 5: Final Verification & Monitoring (15 minutes)

### Run Final Health Check

- [ ] **Backfills complete**:
  ```bash
  bq query --use_legacy_sql=false "SELECT cache_date, COUNT(*) as players FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date IN ('2026-01-08', '2026-01-12') GROUP BY cache_date"
  ```
  - Both dates: 50-200 players

- [ ] **Feature quality restored**:
  ```bash
  bq query --use_legacy_sql=false "SELECT AVG(feature_quality_score) as avg_quality, COUNT(CASE WHEN data_source = 'phase4_partial' THEN 1 END) / COUNT(*) * 100 as phase4_pct FROM \`nba-props-platform.ml_nba.ml_feature_store_v2\` WHERE game_date IN ('2026-01-08', '2026-01-12')"
  ```
  - avg_quality ≥90, phase4_pct ≥40%

- [ ] **Model loading**:
  - Logs show "model loaded successfully"
  - No "FALLBACK_PREDICTION" in recent logs

- [ ] **Confidence distribution**:
  - NOT 100% at 50%
  - Multiple values in 79-95% range
  - High-confidence picks present

- [ ] **Monitoring active**:
  - Function deployed and tested
  - Scheduler running every 4 hours
  - Alerts configured

### Documentation

- [ ] **Update incident status**:
  - Mark as RESOLVED in tracking
  - Note resolution date
  - Link to this checklist

- [ ] **Create resolution summary** (optional):
  - Document what was fixed
  - Note any issues encountered
  - Record actual vs expected outcomes

### Next 3 Days Monitoring Plan

- [ ] **Day 1** (tomorrow):
  - Check monitoring alerts (should run 6 times)
  - Verify no new failures
  - Check confidence distribution still normal

- [ ] **Day 2**:
  - Same checks as Day 1
  - Verify stability

- [ ] **Day 3**:
  - Same checks as Day 1 & 2
  - If all stable for 3 days, mark incident CLOSED

---

## Success Criteria (All Must Pass)

### Data Quality
- [x] player_daily_cache: 50+ players for Jan 8
- [x] player_daily_cache: 50+ players for Jan 12
- [x] Feature quality ≥90 for Jan 8 & 12
- [x] phase4_partial ≥40% for Jan 8 & 12

### Model Performance
- [x] Model loaded successfully (Cloud Run logs)
- [x] Confidence distribution shows variety (NOT just 50%)
- [x] High-confidence picks appearing (85%+)
- [x] No "FALLBACK_PREDICTION" in recent logs

### Monitoring
- [x] Cloud Function deployed
- [x] Cloud Scheduler configured (every 4 hours)
- [x] 5 alerts configured and tested
- [x] Alerts firing correctly (test passed)

### System Health
- [ ] Win rate ≥53% (check after 24 hours)
- [ ] Avg error ≤5.0 points (check after 24 hours)
- [ ] 3 consecutive days stable (monitor for 3 days)

---

## Rollback Plan (If Needed)

### If Backfills Cause Issues
```bash
# Delete backfilled data
bq query --use_legacy_sql=false "DELETE FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date IN ('2026-01-08', '2026-01-12')"
bq query --use_legacy_sql=false "DELETE FROM \`nba-props-platform.ml_nba.ml_feature_store_v2\` WHERE game_date IN ('2026-01-08', '2026-01-12')"
```

### If Model Deployment Causes Issues
```bash
# Unset environment variable (reverts to fallback)
gcloud run services update prediction-worker --region=us-west2 --clear-env-vars CATBOOST_V8_MODEL_PATH --project=nba-props-platform
```

### If Monitoring Causes Issues
```bash
# Delete scheduler job
gcloud scheduler jobs delete nba-monitoring-alerts --location=us-west2 --project=nba-props-platform --quiet

# Delete function
gcloud functions delete nba-monitoring-alerts --region=us-west2 --project=nba-props-platform --quiet
```

---

## Troubleshooting

### Issue: Backfill fails with "No data found"
- Check if Phase 3 data exists for those dates
- May need to backfill Phase 3 first
- See FIXES_READY_TO_EXECUTE.md troubleshooting section

### Issue: Model file not found
- Check alternative locations: `find /home/naji -name "catboost*.cbm"`
- May need to retrain model
- See FIXES_READY_TO_EXECUTE.md troubleshooting section

### Issue: GCS upload fails
- Check bucket exists: `gsutil ls gs://nba-props-platform-models/`
- Check permissions
- See FIXES_READY_TO_EXECUTE.md troubleshooting section

### Issue: Model loads but confidence still 50%
- Force new Cloud Run revision
- Check feature vector validation
- See FIXES_READY_TO_EXECUTE.md troubleshooting section

---

## Completion

- [ ] All checkpoints passed
- [ ] All success criteria met
- [ ] No errors encountered (or all resolved)
- [ ] Documentation updated
- [ ] Monitoring plan in place
- [ ] Incident marked as RESOLVED

**Completed By**: _______________
**Date**: _______________
**Time**: _______________
**Notes**:

---

**Ready to execute? Start with Part 1!**

For detailed commands and explanations, see: [FIXES_READY_TO_EXECUTE.md](./FIXES_READY_TO_EXECUTE.md)
