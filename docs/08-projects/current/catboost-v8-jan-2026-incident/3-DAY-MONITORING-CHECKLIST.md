# CatBoost V8 Post-Fix 3-Day Monitoring Checklist

**Created**: 2026-01-16
**Incident**: CatBoost V8 January 2026 Degradation
**Purpose**: Monitor system stability for 3 days after executing fixes

---

## Overview

After executing the CatBoost V8 fixes, monitor the system daily for 3 consecutive days to ensure:
- No regressions or new failures
- Stable performance metrics
- Monitoring alerts functioning correctly

**Success Criteria**: 3+ consecutive days of healthy metrics → Mark incident CLOSED

---

## Daily Monitoring Checklist

### **Day 1 Checklist** (Date: _________)

#### 1. Data Pipeline Health
- [ ] Check player_daily_cache updated successfully
  ```bash
  bq query --use_legacy_sql=false "SELECT cache_date, COUNT(*) as players FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date = CURRENT_DATE() GROUP BY cache_date"
  ```
  **Expected**: 50-200 players

- [ ] Check ML Feature Store updated successfully
  ```bash
  bq query --use_legacy_sql=false "SELECT game_date, data_source, COUNT(*) as records, AVG(feature_quality_score) as avg_quality FROM \`nba-props-platform.ml_nba.ml_feature_store_v2\` WHERE game_date = CURRENT_DATE() GROUP BY game_date, data_source"
  ```
  **Expected**: Feature quality ≥90, phase4_partial ≥40%

#### 2. Model Performance
- [ ] Check Cloud Run logs for model loading
  ```bash
  gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND timestamp>=timestamp(\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\")" --limit=100 --format=json --project=nba-props-platform | grep -i "catboost"
  ```
  **Expected**: "Model loaded successfully" messages, NO "FAILED to load" errors

- [ ] Check confidence distribution
  ```bash
  bq query --use_legacy_sql=false "SELECT ROUND(confidence_score * 100) as confidence_pct, COUNT(*) as picks FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() GROUP BY confidence_pct ORDER BY confidence_pct DESC"
  ```
  **Expected**: Variety of confidence values (79-95%), NOT all 50%

- [ ] Verify high-confidence picks appearing
  ```bash
  bq query --use_legacy_sql=false "SELECT COUNT(*) as high_conf_picks FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() AND confidence_score >= 0.85"
  ```
  **Expected**: >0 high-confidence picks

#### 3. Prediction Accuracy
- [ ] Check win rate
  ```bash
  bq query --use_legacy_sql=false "SELECT AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) * 100 as win_rate, AVG(ABS(predicted_value - actual_value)) as avg_error FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE()"
  ```
  **Expected**: Win rate ≥53%, Avg error ≤5.0 points

#### 4. Monitoring Alerts
- [ ] Check monitoring function executed successfully
  ```bash
  gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=nba-monitoring-alerts AND timestamp>=timestamp(\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\")" --limit=20 --project=nba-props-platform
  ```
  **Expected**: Successful executions every 4 hours, no critical alerts

- [ ] Check Slack alerts (if configured)
  **Expected**: No critical alerts in Slack channel

#### 5. No Fallback Predictions
- [ ] Verify no fallback mode
  ```bash
  gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND jsonPayload.message=~\"FALLBACK_PREDICTION\" AND timestamp>=timestamp(\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\")" --limit=10 --project=nba-props-platform
  ```
  **Expected**: 0 results (no fallback warnings)

#### Day 1 Summary
- [ ] All checks passed
- [ ] Issues found (if any): _______________________________
- [ ] Actions taken: _______________________________

---

### **Day 2 Checklist** (Date: _________)

#### 1. Data Pipeline Health
- [ ] Check player_daily_cache updated successfully (same query as Day 1)
  **Expected**: 50-200 players

- [ ] Check ML Feature Store updated successfully (same query as Day 1)
  **Expected**: Feature quality ≥90, phase4_partial ≥40%

#### 2. Model Performance
- [ ] Check Cloud Run logs for model loading (same query as Day 1)
  **Expected**: "Model loaded successfully", NO errors

- [ ] Check confidence distribution (same query as Day 1)
  **Expected**: Variety of confidence values (79-95%)

- [ ] Verify high-confidence picks appearing (same query as Day 1)
  **Expected**: >0 high-confidence picks

#### 3. Prediction Accuracy
- [ ] Check win rate (same query as Day 1)
  **Expected**: Win rate ≥53%, Avg error ≤5.0 points

#### 4. Monitoring Alerts
- [ ] Check monitoring function executed successfully (same query as Day 1)
  **Expected**: Successful executions every 4 hours

- [ ] Check Slack alerts (if configured)
  **Expected**: No critical alerts

#### 5. No Fallback Predictions
- [ ] Verify no fallback mode (same query as Day 1)
  **Expected**: 0 fallback warnings

#### Day 2 Summary
- [ ] All checks passed
- [ ] Issues found (if any): _______________________________
- [ ] Actions taken: _______________________________

---

### **Day 3 Checklist** (Date: _________)

#### 1. Data Pipeline Health
- [ ] Check player_daily_cache updated successfully (same query as Day 1)
  **Expected**: 50-200 players

- [ ] Check ML Feature Store updated successfully (same query as Day 1)
  **Expected**: Feature quality ≥90, phase4_partial ≥40%

#### 2. Model Performance
- [ ] Check Cloud Run logs for model loading (same query as Day 1)
  **Expected**: "Model loaded successfully", NO errors

- [ ] Check confidence distribution (same query as Day 1)
  **Expected**: Variety of confidence values (79-95%)

- [ ] Verify high-confidence picks appearing (same query as Day 1)
  **Expected**: >0 high-confidence picks

#### 3. Prediction Accuracy
- [ ] Check win rate (same query as Day 1)
  **Expected**: Win rate ≥53%, Avg error ≤5.0 points

#### 4. Monitoring Alerts
- [ ] Check monitoring function executed successfully (same query as Day 1)
  **Expected**: Successful executions every 4 hours

- [ ] Check Slack alerts (if configured)
  **Expected**: No critical alerts

#### 5. No Fallback Predictions
- [ ] Verify no fallback mode (same query as Day 1)
  **Expected**: 0 fallback warnings

#### Day 3 Summary
- [ ] All checks passed
- [ ] Issues found (if any): _______________________________
- [ ] Actions taken: _______________________________

---

## 3-Day Summary Metrics

### Data Quality Trends
| Metric | Day 1 | Day 2 | Day 3 | Trend |
|--------|-------|-------|-------|-------|
| player_daily_cache records | _____ | _____ | _____ | _____ |
| Feature quality score | _____ | _____ | _____ | _____ |
| phase4_partial % | _____ | _____ | _____ | _____ |

### Model Performance Trends
| Metric | Day 1 | Day 2 | Day 3 | Trend |
|--------|-------|-------|-------|-------|
| Model loaded successfully | ☐ | ☐ | ☐ | _____ |
| Confidence variety (79-95%) | ☐ | ☐ | ☐ | _____ |
| High-confidence picks count | _____ | _____ | _____ | _____ |
| Win rate % | _____ | _____ | _____ | _____ |
| Avg error (points) | _____ | _____ | _____ | _____ |

### Monitoring Health
| Check | Day 1 | Day 2 | Day 3 | Trend |
|-------|-------|-------|-------|-------|
| Monitoring function runs | _____ | _____ | _____ | _____ |
| Alerts triggered | _____ | _____ | _____ | _____ |
| Fallback predictions | _____ | _____ | _____ | _____ |

---

## Incident Closure Criteria

### **Mark incident CLOSED if ALL conditions met:**
- [x] 3 consecutive days of monitoring completed
- [ ] player_daily_cache: 50+ players daily
- [ ] Feature quality: ≥90 daily
- [ ] phase4_partial: ≥40% daily
- [ ] Model loading: Success daily, NO failures
- [ ] Confidence distribution: Variety (79-95%), NOT stuck at 50%
- [ ] High-confidence picks: >0 daily
- [ ] Win rate: ≥53% over 3 days
- [ ] Avg error: ≤5.0 points over 3 days
- [ ] Monitoring alerts: Functioning, no critical alerts
- [ ] Fallback predictions: 0 occurrences over 3 days
- [ ] No regressions or new issues

### **Final Sign-off**
- [ ] All closure criteria met
- [ ] Incident documentation updated
- [ ] Lessons learned documented
- [ ] Post-mortem scheduled (if needed)
- [ ] **Incident Status**: CLOSED on __________ (Date)

**Closed by**: __________________
**Final notes**: ________________________________________

---

## Escalation Procedures

### If any check fails:

**Level 1 - Minor Issue** (1-2 checks fail, system still functional)
1. Document the failure with logs and metrics
2. Investigate root cause
3. Apply fix if possible
4. Continue monitoring, extend to Day 4-5 if needed

**Level 2 - Moderate Issue** (3-5 checks fail, degraded performance)
1. Immediately check Cloud Run logs for errors
2. Verify all environment variables still set
3. Check GCS model file still accessible
4. Review recent deployments for conflicts
5. Consider rollback if issue persists

**Level 3 - Critical Issue** (6+ checks fail, system broken)
1. **IMMEDIATE**: Execute rollback procedures (see FIXES_READY_TO_EXECUTE.md)
2. Check for infrastructure changes (GCP maintenance, quota exceeded)
3. Verify Cloud Run service health
4. Open incident ticket with GCP support if infrastructure issue
5. Schedule emergency investigation session

---

## Quick Reference Commands

### Check Everything at Once
```bash
# Save this as check_catboost_health.sh
#!/bin/bash
echo "=== CatBoost V8 Health Check ==="
echo ""
echo "1. player_daily_cache:"
bq query --use_legacy_sql=false --format=prettyjson "SELECT cache_date, COUNT(*) as players FROM \`nba-props-platform.nba_precompute.player_daily_cache\` WHERE cache_date = CURRENT_DATE() GROUP BY cache_date" | head -10
echo ""
echo "2. Feature Quality:"
bq query --use_legacy_sql=false --format=prettyjson "SELECT data_source, AVG(feature_quality_score) as avg_quality FROM \`nba-props-platform.ml_nba.ml_feature_store_v2\` WHERE game_date = CURRENT_DATE() GROUP BY data_source" | head -10
echo ""
echo "3. Confidence Distribution:"
bq query --use_legacy_sql=false --format=prettyjson "SELECT ROUND(confidence_score * 100) as conf, COUNT(*) as picks FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE system_id = 'catboost_v8' AND game_date >= CURRENT_DATE() GROUP BY conf ORDER BY conf DESC LIMIT 10" | head -20
echo ""
echo "4. Model Loading (last 50 logs):"
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND timestamp>=timestamp(\"$(date -u -d '6 hours ago' +%Y-%m-%dT%H:%M:%SZ)\")" --limit=50 --format=json --project=nba-props-platform | grep -i "catboost" | head -5
echo ""
echo "=== Health Check Complete ==="
```

### Make it executable
```bash
chmod +x check_catboost_health.sh
./check_catboost_health.sh
```

---

## Notes

- This checklist assumes fixes were executed on: __________ (fill in date)
- Monitoring started on: __________ (fill in date)
- Expected closure date: __________ (fill in date + 3 days)
- Point of contact: Naji
- Escalation contact: __________

**Document Location**: `/home/naji/code/nba-stats-scraper/docs/08-projects/current/catboost-v8-jan-2026-incident/3-DAY-MONITORING-CHECKLIST.md`
