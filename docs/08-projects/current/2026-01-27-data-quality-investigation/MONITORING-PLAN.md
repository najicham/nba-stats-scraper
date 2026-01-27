# Data Quality Monitoring & Alerting System

**Author:** Claude Code
**Date:** 2026-01-27
**Status:** Implementation Ready
**Purpose:** Prevent data quality issues like 2026-01-26 from reaching production

## Executive Summary

This document outlines the monitoring and alerting system designed to catch data quality issues before they impact users. The system addresses the specific failures identified in the 2026-01-26 incident:
- 0 predictions generated (silent success because 0/0 = 100% coverage)
- 71% NULL usage_rate in player_game_summary
- 93 duplicate records
- Prediction coordinator stuck for hours
- Betting lines arrived after Phase 3 processed

## Architecture Overview

### Components

1. **SQL Queries** (`monitoring/queries/`)
   - Self-contained, parameterized queries
   - Can be run manually or via BigQuery scheduled queries
   - Include diagnostic hints and remediation suggestions

2. **Cloud Function** (`orchestration/cloud_functions/data_quality_alerts/`)
   - Runs all quality checks in a single execution
   - Sends alerts to appropriate Slack channels
   - Supports dry-run mode for testing
   - 540s timeout to handle long-running queries

3. **Cloud Scheduler**
   - Triggers quality checks at 7 PM ET daily (after predictions complete)
   - Ensures checks run even if manual triggers are forgotten

4. **Notification Infrastructure** (existing)
   - Slack channels: #app-error-alerts (CRITICAL), #nba-alerts (WARNING)
   - Email via AWS SES (backup)
   - Rate limiting to prevent alert floods

## Alert Definitions

### P0: Zero Predictions Alert

**Trigger:** 0 predictions for a game day after 6 PM local time

**Query:** `monitoring/queries/zero_predictions.sql`

**Detection Logic:**
```sql
-- Alert if players_predicted = 0 AND games_today > 0
-- Check upcoming_player_game_context for expected players
-- Compare with actual prediction count in player_prop_predictions
```

**Alert Content:**
- Number of games scheduled
- Number of eligible players (expected predictions)
- Actual predictions generated
- Coverage percentage
- Diagnostic hint (e.g., "betting lines may have arrived late")

**Action:**
1. Immediate Slack alert to #app-error-alerts
2. Check coordinator logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-coordinator-prod" --limit 50`
3. Verify Phase 3 timing: Check upcoming_player_game_context.created_at vs props scraped_at
4. Manual intervention: Re-run Phase 3 if needed, then trigger coordinator

**Would Have Caught:** 2026-01-26 incident where 0 predictions were generated

---

### P0: Coordinator Stuck Alert

**Trigger:** Batch running > 30 minutes with 0 progress

**Implementation:** Enhancement to existing coordinator code

**Detection Logic:**
- Monitor Firestore batch state: `batch_states/{batch_id}`
- Track `last_update_time` and `completed_count`
- Alert if `TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_update_time, MINUTE) > 30 AND completed_count = 0`

**Alert Content:**
- Batch ID
- Started time
- Last update time
- Players expected vs completed
- Stuck reason (if identifiable)

**Action:**
1. Immediate Slack alert to #app-error-alerts
2. Check coordinator instance: `gcloud run services describe prediction-coordinator-prod --region=us-west2`
3. Check worker logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker-prod" --limit 50`
4. Manual intervention: Restart coordinator if truly stuck

**Implementation Notes:**
- Add to `predictions/coordinator/batch_state_manager.py`
- Integrate with existing heartbeat logging
- Send alert via existing notification_system

**Would Have Caught:** Coordinator running for hours with no progress

---

### P1: Low Usage Rate Coverage

**Trigger:** usage_rate coverage < 80% for completed game day

**Query:** `monitoring/queries/low_usage_coverage.sql`

**Detection Logic:**
```sql
-- Alert if (records_with_usage_rate / total_records) < 0.80
-- AND all games have status = 'Final'
-- Check nbacom_schedule for game completion status
```

**Alert Content:**
- Total records in player_game_summary
- Records with usage_rate
- Coverage percentage
- Number of games completed
- Timing hint (e.g., "games recently completed - may need more time")

**Action:**
1. Slack alert to #nba-alerts (WARNING level)
2. Check if games recently finished (< 2 hours ago) - may be acceptable
3. If > 2 hours since final game, investigate BDL boxscore processor
4. Check for incomplete boxscores: `gs://nba-scraped-data/balldontlie/box-scores/`

**Would Have Caught:** 71% NULL usage_rate on 2026-01-26

---

### P1: All Players Missing Prop Lines

**Trigger:** has_prop_line = FALSE for 100% of players after 5 PM

**Query:** `monitoring/queries/prop_lines_missing.sql`

**Detection Logic:**
```sql
-- Alert if players_with_lines = 0 AND total_players > 0
-- Compare Phase 3 processed_at vs props scraped_at
-- Recommend re-triggering Phase 3 if props arrived late
```

**Alert Content:**
- Total players in upcoming_player_game_context
- Players with prop lines
- Coverage percentage
- Phase 3 last run time
- Props last scraped time
- Timing analysis (did props arrive after Phase 3?)
- Recommended action (re-trigger Phase 3 if needed)

**Action:**
1. Slack alert to #nba-alerts (CRITICAL if 0%, WARNING if < 50%)
2. Check timing: Did props scraper run before Phase 3?
3. If props arrived late: `gcloud scheduler jobs run phase3-trigger --location=us-west2`
4. Monitor Phase 3 completion before predictions run

**Auto-Remediation (Future):**
- If 0% coverage detected, automatically re-trigger Phase 3
- Add guard: Only re-trigger once per day to prevent loops
- Track auto-remediation in Firestore

**Would Have Caught:** Root cause of 2026-01-26 (betting lines arrived after Phase 3)

---

### P2: Duplicate Records Detected

**Trigger:** Any duplicates in player_game_summary

**Query:** `monitoring/queries/duplicate_detection.sql`

**Detection Logic:**
```sql
-- GROUP BY player_lookup, game_id HAVING COUNT(*) > 1
-- Alert severity:
--   <= 5 duplicates: INFO
--   <= 20 duplicates: WARNING
--   > 20 duplicates: CRITICAL
```

**Alert Content:**
- Number of duplicate groups
- Total excess records
- Duplicate percentage
- Top 10 duplicate examples with timing info
- Diagnostic hint (e.g., "processor may have run multiple times")

**Action:**
1. Slack alert to #nba-alerts (severity-based)
2. Check processor logs for multiple runs
3. Investigate deduplication logic in processor
4. Check Pub/Sub for duplicate messages
5. If CRITICAL: Consider running deduplication script

**Would Have Caught:** 93 duplicate records on 2026-01-26

---

### P2: Processing Order Violation

**Trigger:** Player stats processed before team stats

**Implementation:** Not yet implemented (future enhancement)

**Detection Logic:**
- Compare processed_at timestamps between related processors
- Alert if Phase N+1 ran before Phase N completed
- Track phase dependencies in orchestration metadata

**Alert Content:**
- Phase that ran early
- Phase that should have run first
- Timestamp difference
- Impact assessment

**Action:**
1. Slack alert to #nba-alerts (WARNING level)
2. Check orchestration logic
3. Review phase trigger conditions
4. Add dependencies if missing

**Would Have Caught:** Phase 2 processing incomplete boxscores before Phase 1 updated them

---

## Implementation Status

### ✅ Completed

1. **SQL Queries Created**
   - `zero_predictions.sql` - P0 alert
   - `low_usage_coverage.sql` - P1 alert
   - `duplicate_detection.sql` - P2 alert
   - `prop_lines_missing.sql` - P1 alert

2. **Cloud Function Created**
   - `orchestration/cloud_functions/data_quality_alerts/main.py`
   - Checks all 4 quality metrics
   - Sends alerts to appropriate Slack channels
   - Supports dry-run mode
   - Error handling and logging

3. **Documentation**
   - This monitoring plan
   - Query comments with usage examples
   - Deployment instructions

### 🚧 In Progress

1. **Cloud Function Deployment**
   - Deploy to GCP
   - Configure environment variables
   - Test with real data

2. **Cloud Scheduler Setup**
   - Create scheduler job
   - Set schedule (7 PM ET daily)
   - Configure retry policy

3. **Coordinator Stuck Alert**
   - Enhance batch_state_manager.py
   - Add heartbeat monitoring
   - Integrate with notification system

### 📋 TODO (Future Enhancements)

1. **Auto-Remediation**
   - Auto re-trigger Phase 3 when prop lines missing
   - Auto-restart coordinator when stuck
   - Add guard rails (max 1 auto-remediation per day)

2. **Historical Tracking**
   - Store alert history in BigQuery
   - Build dashboard for alert trends
   - Track false positive rate

3. **Additional Alerts**
   - Processing order violation detection
   - Feature store staleness check
   - Model confidence drift detection
   - Coordinator completion time (SLA)

4. **Integration with Existing Monitoring**
   - Connect to existing prediction_health_alert
   - Consolidate with daily_health_summary
   - Add to monitoring dashboard

5. **Testing**
   - Unit tests for alert logic
   - Integration tests with test data
   - Load testing for query performance

## Deployment Instructions

### 1. Deploy Cloud Function

```bash
# Navigate to function directory
cd orchestration/cloud_functions/data_quality_alerts

# Deploy to GCP
gcloud functions deploy data-quality-alerts \
    --gen2 \
    --runtime python311 \
    --region us-west2 \
    --source . \
    --entry-point check_data_quality \
    --trigger-http \
    --allow-unauthenticated \
    --timeout=540 \
    --memory=512MB \
    --set-env-vars GCP_PROJECT_ID=nba-props-platform,SLACK_WEBHOOK_URL_ERROR=[URL],SLACK_WEBHOOK_URL_WARNING=[URL]

# Get function URL
gcloud functions describe data-quality-alerts --gen2 --region us-west2 --format="value(serviceConfig.uri)"
```

### 2. Create Cloud Scheduler Job

```bash
# Create scheduler job (runs daily at 7 PM ET)
gcloud scheduler jobs create http data-quality-alerts-job \
    --schedule "0 19 * * *" \
    --time-zone "America/New_York" \
    --uri [FUNCTION_URL] \
    --http-method GET \
    --location us-west2 \
    --description "Daily data quality checks for NBA predictions pipeline"

# Test the job
gcloud scheduler jobs run data-quality-alerts-job --location=us-west2
```

### 3. Test the System

```bash
# Test with dry-run (no alerts sent)
curl "[FUNCTION_URL]?game_date=2026-01-26&dry_run=true"

# Test specific checks
curl "[FUNCTION_URL]?game_date=2026-01-26&checks=zero_predictions,prop_lines&dry_run=true"

# Run for real (sends alerts)
curl "[FUNCTION_URL]?game_date=2026-01-26"
```

### 4. Monitor Function Performance

```bash
# View function logs
gcloud functions logs read data-quality-alerts --gen2 --region us-west2 --limit 50

# Check function metrics
gcloud monitoring dashboards list | grep data-quality
```

## Testing Strategy

### Manual Testing

1. **Test with 2026-01-26 Data** (known issues)
   ```bash
   curl "[FUNCTION_URL]?game_date=2026-01-26&dry_run=true"
   ```
   Expected alerts:
   - Zero predictions: CRITICAL
   - Usage rate: WARNING (71% coverage)
   - Duplicates: WARNING (93 duplicates)
   - Prop lines: CRITICAL (0% coverage)

2. **Test with Recent Good Data**
   ```bash
   curl "[FUNCTION_URL]?game_date=2026-01-25&dry_run=true"
   ```
   Expected: All checks OK

3. **Test Individual Checks**
   ```bash
   curl "[FUNCTION_URL]?checks=zero_predictions&dry_run=true"
   ```

### Integration Testing

1. **Run Queries Manually in BigQuery**
   ```bash
   bq query --use_legacy_sql=false \
     --parameter=game_date:DATE:2026-01-26 \
     < monitoring/queries/zero_predictions.sql
   ```

2. **Verify Slack Alerts**
   - Remove `dry_run=true` flag
   - Check #app-error-alerts and #nba-alerts channels
   - Verify alert content is accurate and actionable

3. **Test Scheduler Trigger**
   ```bash
   gcloud scheduler jobs run data-quality-alerts-job --location=us-west2
   ```

### Load Testing

1. **Query Performance**
   - Run queries for date ranges (last 7 days)
   - Measure execution time
   - Verify < 30s per query

2. **Function Timeout**
   - Run all checks simultaneously
   - Ensure completion within 540s timeout
   - Monitor BigQuery quota usage

## Monitoring the Monitor

### Function Health Checks

- Health endpoint: `[FUNCTION_URL]/health`
- Expected uptime: > 99.5%
- Alert if function fails 3+ times consecutively

### Alert Effectiveness

Track in BigQuery:
```sql
CREATE TABLE nba_monitoring.alert_history (
    alert_date DATE,
    check_name STRING,
    alert_level STRING,
    message STRING,
    details JSON,
    alerted_at TIMESTAMP,
    was_true_positive BOOL,
    resolved_at TIMESTAMP,
    resolution_notes STRING
);
```

### False Positive Rate

- Target: < 10% false positive rate
- Review weekly: Are we alerting on expected conditions?
- Adjust thresholds based on historical data

### Alert Fatigue Prevention

- Use severity levels appropriately
- Rate limit duplicate alerts (via notification_system)
- Send daily digest of INFO-level issues instead of individual alerts
- Auto-resolve alerts after 24 hours if not acknowledged

## Operational Runbook

### When You Receive a CRITICAL Alert

1. **Acknowledge** - React to Slack message within 15 minutes
2. **Assess** - Review alert details and diagnostic hints
3. **Investigate** - Check logs, data, and timing
4. **Remediate** - Follow recommended actions in alert
5. **Document** - Add notes to alert history table
6. **Review** - Post-mortem if systemic issue

### When You Receive a WARNING Alert

1. **Review** - Check if expected (e.g., games recently finished)
2. **Monitor** - Watch for escalation to CRITICAL
3. **Investigate** - If persistent, follow CRITICAL runbook
4. **Document** - Note if this is a recurring pattern

### When You Receive an INFO Alert

1. **Log** - No immediate action required
2. **Review Weekly** - Check for patterns
3. **Adjust** - Update thresholds if too noisy

## Success Metrics

### Primary Metrics

- **Detection Rate:** % of data quality issues caught before users notice
  - Target: > 95%
  - Measure: Compare alerts fired vs user-reported issues

- **Time to Detection:** How quickly issues are identified
  - Target: < 1 hour after issue occurs
  - Measure: Alert timestamp - issue timestamp

- **False Positive Rate:** % of alerts that are not actionable
  - Target: < 10%
  - Measure: True positives / total alerts

### Secondary Metrics

- **Query Performance:** Average query execution time
  - Target: < 30 seconds per query
  - Measure: BigQuery execution statistics

- **Alert Actionability:** % of alerts with clear remediation steps
  - Target: 100%
  - Measure: Manual review of alert content

- **Resolution Time:** Average time from alert to resolution
  - Target: < 2 hours for CRITICAL, < 24 hours for WARNING
  - Measure: resolved_at - alerted_at

## Cost Analysis

### BigQuery Costs

- **Queries:** 4 queries × ~100 MB scanned each = 400 MB per day
- **Cost:** $0.005 per GB = ~$0.002 per day = $0.73 per year
- **Negligible impact** on overall BigQuery budget

### Cloud Function Costs

- **Invocations:** 1 per day
- **Compute:** ~10 seconds at 512MB
- **Cost:** ~$0.0000004 per invocation = $0.00015 per year
- **Free tier covers this completely**

### Cloud Scheduler Costs

- **Jobs:** 1 job
- **Cost:** $0.10 per month = $1.20 per year

### Total: ~$2 per year

**ROI:** Prevented one incident like 2026-01-26 saves hours of investigation time and prevents user impact. This monitoring system pays for itself immediately.

## Related Documentation

- Root Cause Analysis: `2026-01-27-root-cause-analysis.md`
- Remediation Plan: `2026-01-27-remediation-plan.md`
- Incident Timeline: `2026-01-27-timeline.md`
- Existing Monitoring: `monitoring/README_QUOTA_MONITORING.md`
- Prediction Health Alert: `orchestration/cloud_functions/prediction_health_alert/main.py`

## Changelog

- **2026-01-27:** Initial version created by Claude Code
  - Defined 6 alert types (P0-P2)
  - Created 4 SQL queries
  - Implemented Cloud Function for 4 checks
  - Documented deployment and testing strategy

## Next Steps

1. **Deploy Cloud Function** - Get it running in production
2. **Test with Historical Data** - Verify it catches known issues
3. **Monitor for False Positives** - Tune thresholds as needed
4. **Add Auto-Remediation** - Start with prop lines re-triggering
5. **Implement Coordinator Stuck Alert** - Enhance batch state manager
6. **Build Dashboard** - Visualize alert trends over time

---

**Questions or Issues?** Contact the data engineering team or review the incident analysis docs.
