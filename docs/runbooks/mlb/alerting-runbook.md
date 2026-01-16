# MLB Alerting Runbook

**Version**: 1.0
**Last Updated**: 2026-01-16
**Owner**: MLB Infrastructure Team

---

## Overview

This runbook provides procedures for responding to monitoring and validation alerts for the MLB prediction infrastructure.

---

## Alert Channels

- **Slack**: #mlb-alerts
- **Email**: mlb-ops@company.com
- **PagerDuty**: MLB Infrastructure Team

---

## Alert Severity Levels

| Severity | Response Time | Escalation | Examples |
|----------|---------------|------------|----------|
| **Critical** | Immediate (5 min) | Page on-call | Batch prediction failure, pipeline completely stalled |
| **Warning** | Within 1 hour | Slack only | Individual prediction failure, low coverage |
| **Info** | No response required | Log only | High-confidence prediction tracking |

---

## Monitoring Alerts

### Gap Detection: Processing Gaps Found

**Alert**: "MLB Gap Detection: X files not processed to BigQuery"

**Severity**: Warning (if < 10 files), Critical (if ≥ 10 files)

**Meaning**: GCS files exist but haven't been loaded into BigQuery tables

**Response Steps**:
1. Check which data sources have gaps:
   ```bash
   PYTHONPATH=. python monitoring/mlb/mlb_gap_detection.py --date today --dry-run
   ```
2. Review the gap report for affected dates and sources
3. Run remediation commands provided in the alert
4. If gaps persist after backfill, investigate processor failures:
   ```bash
   gcloud logging read "resource.type=cloud_run_service AND \
     (labels.service_name='mlb-analytics-service' OR labels.service_name='mlb-precompute-service')" \
     --limit=100 \
     --format=json | grep -i error
   ```

**Remediation Example**:
```bash
# Backfill missing dates
gcloud run jobs execute mlb-schedule-processor-backfill \
  --args=--start-date=2026-01-15,--end-date=2026-01-15 \
  --region=us-west2
```

---

### Freshness: Stale Data Detected

**Alert**: "MLB Freshness Check: [table_name] is X hours old"

**Severity**: Warning (if > max_age), Critical (if > 2x max_age)

**Meaning**: Data in BigQuery table hasn't been updated recently

**Response Steps**:
1. Identify which table is stale:
   - `mlb_raw.mlb_schedule` - Schedule data
   - `mlb_raw.bp_pitcher_props` - BettingPros props
   - `mlb_predictions.pitcher_strikeouts` - Predictions
2. Check if it's a game day:
   ```bash
   bq query --use_legacy_sql=false \
     "SELECT COUNT(*) as games FROM mlb_raw.mlb_schedule WHERE game_date = CURRENT_DATE('America/New_York')"
   ```
3. If games scheduled, check scraper/processor logs
4. If no games (off-day), acknowledge alert - expected behavior

**Remediation**:
```bash
# Re-run scraper for stale data source
gcloud run jobs execute mlb-bettingpros-pitcher-props-scraper \
  --args=--date=2026-01-16 \
  --region=us-west2

# Re-run processor if scraper succeeded
gcloud run jobs execute mlb-pitcher-props-processor \
  --args=--date=2026-01-16 \
  --region=us-west2
```

---

### Prediction Coverage: Low Coverage

**Alert**: "MLB Prediction Coverage: X% (Y/Z pitchers) - below 90% threshold"

**Severity**: Warning (if < 90%), Critical (if < 80%)

**Meaning**: Not all scheduled pitchers have predictions

**Response Steps**:
1. Check coverage report:
   ```bash
   PYTHONPATH=. python monitoring/mlb/mlb_prediction_coverage.py --date today
   ```
2. Identify missing pitchers from output
3. Check if missing pitchers have props:
   ```bash
   bq query --use_legacy_sql=false \
     "SELECT player_lookup, player_name FROM mlb_raw.bp_pitcher_props \
      WHERE game_date = CURRENT_DATE('America/New_York') \
      AND player_lookup IN ('missing_pitcher_1', 'missing_pitcher_2')"
   ```
4. If props exist but no predictions, re-run prediction worker:
   ```bash
   gcloud run jobs execute mlb-prediction-worker \
     --args=--date=2026-01-16,--mode=batch \
     --region=us-west2
   ```

**Common Causes**:
- Props arrived after prediction job ran (re-run predictions)
- Pitcher not in schedule (check schedule data)
- Prediction model error (check worker logs for errors)

---

### Stall Detection: Pipeline Stalled

**Alert**: "MLB Pipeline Stalled at [stage_name]"

**Severity**: Critical

**Meaning**: Data flow has stopped at a specific pipeline stage

**Response Steps**:
1. Identify stalled stage from alert:
   - **Raw Data**: Scrapers not running
   - **Analytics**: Processor not running
   - **Precompute**: Feature generation stuck
   - **Predictions**: Prediction worker not running
   - **Grading**: Grading service not running

2. Check stage-specific service logs:
   ```bash
   # For Analytics stage
   gcloud logging read "resource.type=cloud_run_service AND \
     labels.service_name='mlb-analytics-service'" \
     --limit=50 --format=json

   # For Predictions stage
   gcloud logging read "resource.type=cloud_run_service AND \
     labels.service_name='mlb-prediction-worker'" \
     --limit=50 --format=json
   ```

3. Check for orchestration failures:
   ```bash
   # Check Firestore orchestration state
   gcloud firestore documents list mlb_orchestration/executions \
     --filter="status:FAILED" \
     --limit=10
   ```

4. Restart stuck service or manually trigger:
   ```bash
   # Manually trigger analytics
   curl -X POST https://mlb-analytics-service-HASH.run.app/process \
     -H "Content-Type: application/json" \
     -d '{"start_date": "2026-01-16", "end_date": "2026-01-16"}'
   ```

---

## Validation Alerts

### Schedule Validator: Schedule Issues

**Alert**: "MLB Schedule Validation Failed: [issue_description]"

**Severity**: Warning (minor issues), Critical (major data quality)

**Possible Issues**:
1. **Missing probable pitchers**: Some games don't have pitcher assignments
   - **Response**: Normal 1-2 days before games, critical if < 2 hours to game time
   - **Action**: Check MLB.com for updates, may need manual scraper run

2. **Team presence**: Not all 30 teams present
   - **Response**: Check if it's early/late season (fewer teams playing)
   - **Action**: If mid-season, investigate schedule scraper

3. **Duplicate games**: Same game appears multiple times
   - **Response**: Data quality issue in BigQuery
   - **Action**: Clean duplicates:
     ```bash
     bq query --use_legacy_sql=false \
       "DELETE FROM mlb_raw.mlb_schedule \
        WHERE game_pk IN (SELECT game_pk FROM mlb_raw.mlb_schedule \
        GROUP BY game_pk, game_date HAVING COUNT(*) > 1) \
        AND created_at NOT IN (SELECT MAX(created_at) FROM mlb_raw.mlb_schedule \
        GROUP BY game_pk, game_date)"
     ```

---

### Pitcher Props Validator: Props Issues

**Alert**: "MLB Pitcher Props Validation Failed: [issue_description]"

**Severity**: Warning (coverage issues), Critical (no props data)

**Possible Issues**:
1. **Low props coverage**: < 80% of scheduled pitchers have props
   - **Response**: Check if BettingPros data is delayed
   - **Action**: Re-run props scraper, consider using Odds API as fallback

2. **Unusual lines**: Strikeout lines outside 0.5-15.5 range
   - **Response**: Investigate specific pitchers with unusual lines
   - **Action**: May be valid (rookie, injured pitcher), or data error

3. **No data**: Props table empty for game date
   - **Response**: Critical - affects all predictions
   - **Action**: Emergency scraper run:
     ```bash
     gcloud run jobs execute mlb-bettingpros-pitcher-props-scraper \
       --args=--date=2026-01-16 \
       --region=us-west2 \
       --wait
     ```

---

### Prediction Coverage Validator: Prediction Issues

**Alert**: "MLB Prediction Coverage Validation Failed: [issue_description]"

**Severity**: Warning (< 90% coverage), Critical (< 80% coverage)

**Possible Issues**:
1. **Low prediction coverage**: Not all pitchers with props have predictions
   - **Response**: Check prediction worker logs for errors
   - **Action**: Re-run batch predictions

2. **Missing quality metrics**: Predictions lack confidence/edge scores
   - **Response**: Model inference issue
   - **Action**: Check model version, may need model reload

3. **Grading incomplete**: Past games not graded
   - **Response**: Grading service not running
   - **Action**: Backfill grading:
     ```bash
     gcloud run jobs execute mlb-grading-service \
       --args=--start-date=2026-01-10,--end-date=2026-01-16 \
       --region=us-west2
     ```

---

## Service Alerts (AlertManager Integration)

### Analytics Service Failure

**Alert**: "MLB Analytics Processor Failed: [processor_name]"

**Severity**: Warning (individual processor), Critical (service-level)

**Response**:
1. Check error type and game_date from alert context
2. Review processor logs:
   ```bash
   gcloud logging read "resource.labels.service_name='mlb-analytics-service' AND \
     severity>=ERROR" --limit=20 --format=json
   ```
3. Common issues:
   - BigQuery write failure (quota exceeded, schema mismatch)
   - Missing input data (check upstream dependencies)
   - Code errors (check recent deployments)

**Remediation**:
```bash
# Re-run specific analytics processor
curl -X POST https://mlb-analytics-service-HASH.run.app/process \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-16", "processor": "pitcher_game_summary"}'
```

---

### Prediction Worker Failure

**Alert**: "MLB Prediction Failed" or "MLB Batch Prediction Failed"

**Severity**: Warning (single prediction), Critical (batch)

**Response**:
1. **Single prediction failure**: Individual pitcher prediction failed
   - Often not actionable (bad data for specific pitcher)
   - Monitor for patterns (same pitcher failing repeatedly)

2. **Batch prediction failure**: All predictions for a date failed
   - Critical - no predictions available
   - Check model availability, props data existence
   - Emergency response required

**Remediation**:
```bash
# Re-run batch predictions
curl -X POST https://mlb-prediction-worker-HASH.run.app/predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-16"}'
```

---

### Grading Service Failure

**Alert**: "MLB Grading Failed"

**Severity**: Warning

**Response**:
1. Grading failures don't block predictions (historical only)
2. Check if game results available:
   ```bash
   bq query --use_legacy_sql=false \
     "SELECT game_pk, status FROM mlb_raw.mlb_schedule \
      WHERE game_date = '2026-01-15' AND status IN ('Final', 'Completed')"
   ```
3. May need to wait for official game results (typically within 2 hours of game end)

---

## Escalation Procedures

### When to Escalate

Escalate to senior engineer when:
- Multiple critical alerts in short period (< 1 hour)
- Unable to resolve within 30 minutes
- Data loss or corruption suspected
- System-wide outage affecting all predictions

### Escalation Contacts

1. **On-Call Engineer**: PagerDuty escalation
2. **Senior Engineer**: @senior-engineer in #mlb-alerts
3. **Engineering Manager**: For business impact decisions

---

## Common Alert Patterns

### Alert Storm (Multiple Alerts in Sequence)

**Pattern**: Gap Detection → Freshness → Stall Detection

**Meaning**: Upstream failure cascading through pipeline

**Response**: Focus on earliest stage (usually Raw Data or Analytics)

### Intermittent Failures

**Pattern**: Alert → Resolves → Alert again within hours

**Meaning**: Transient issue (network, quota, rate limiting)

**Response**: Monitor for pattern, may need rate limiting adjustments

### Daily Morning Alerts

**Pattern**: Coverage/freshness alerts at 6-8 AM ET

**Meaning**: Overnight processing didn't complete

**Response**: Check overnight scheduler runs, may need earlier start times

---

## Alert Acknowledgement

Always acknowledge alerts in Slack with:
1. Acknowledgement message: "Investigating [alert_name]"
2. Status updates every 15 minutes
3. Resolution message: "Resolved [alert_name]: [what was done]"

Example:
```
@here Investigating MLB Prediction Coverage alert - 75% coverage reported
[15 min later] Found missing props data, re-running scraper
[30 min later] Resolved: Props scraped, predictions regenerated, now at 95% coverage
```

---

## Post-Incident Review

After resolving critical alerts:
1. Document incident in #mlb-incidents
2. Create post-mortem if downtime > 1 hour
3. Identify prevention measures
4. Update runbook with lessons learned

---

**Contacts**:
- **On-Call**: PagerDuty
- **Slack**: #mlb-alerts
- **Escalation**: #mlb-infrastructure

**Last Tested**: 2026-01-16
**Next Review**: Before 2026 MLB Season
