# Alerting Strategy and Escalation

**File:** `docs/monitoring/06-alerting-strategy-and-escalation.md`
**Created:** 2025-11-18 15:30 PST
**Last Updated:** 2025-11-18 15:30 PST
**Purpose:** Define alert severity levels, escalation paths, and on-call runbooks
**Status:** Current
**Audience:** On-call engineers, SREs, incident responders

---

## 🎯 Overview

**This document covers:**
- ✅ Alert severity matrix (when to page vs email)
- ✅ Escalation paths and on-call rotation
- ✅ Phase-specific alerts and thresholds
- ✅ Backfill progress monitoring
- ✅ DLQ depth alerts
- ✅ On-call runbooks (quick decision trees)
- ✅ Alert fatigue prevention

---

## 📊 Alert Severity Matrix

### Severity Levels

| Severity | Impact | Response Time | Notification Method | Examples |
|----------|--------|---------------|---------------------|----------|
| **Critical** | Production broken, data loss | Immediate (page) | PagerDuty + Slack + Email | Complete Phase 2 outage, DLQ growing rapidly |
| **High** | Degraded service, partial data loss | 15 minutes | Slack + Email | Single processor failing, backfill stalled |
| **Medium** | Minor degradation, no data loss | 1 hour | Email | Slow processing, quality score degraded |
| **Low** | Informational, no impact | 24 hours | Email (digest) | Completed backfill, nearing quota |

---

### Critical Alerts (Page Immediately)

**Trigger PagerDuty:**

#### 1. **Phase 2 Complete Outage**
- **Metric:** Zero successful Phase 2 executions
- **Condition:** No successful processing in last 15 minutes
- **Impact:** New data not entering pipeline
- **Action:** Check Phase 2 service health immediately

```sql
-- Alert query
SELECT COUNT(*) as failed_processors
FROM `nba-props-platform.nba_orchestration.processor_execution_log`
WHERE DATE(processed_at, 'America/New_York') = CURRENT_DATE('America/New_York')
  AND processor_name LIKE 'phase2_%'
  AND status = 'failed'
  AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)
HAVING failed_processors > 10;
-- Alert if > 10 processors failed in last 15 min
```

**Runbook:** See "Critical: Phase 2 Outage" below

---

#### 2. **DLQ Rapidly Growing**
- **Metric:** DLQ message count
- **Condition:** > 10 messages in DLQ
- **Impact:** Processing failures accumulating
- **Action:** Investigate Phase 2 failures

```bash
# Alert query (Cloud Monitoring)
gcloud pubsub subscriptions describe nba-phase1-scrapers-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

# Alert if > 10
```

**Runbook:** See "Critical: DLQ Growing" below

---

#### 3. **Complete Data Loss for Current Date**
- **Metric:** Zero rows in Phase 2 for today
- **Condition:** No data as of 6am ET (scrapers should have run)
- **Impact:** Missing entire day of data
- **Action:** Check Phase 1 and Phase 2 immediately

```sql
-- Alert query (run at 6am ET)
SELECT COUNT(*) as row_count
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date = CURRENT_DATE('America/New_York')
HAVING row_count = 0;
-- Alert if 0 rows
```

**Runbook:** See "Critical: No Data for Today" below

---

### High Alerts (Respond in 15 Minutes)

**Notify Slack + Email:**

#### 4. **Single Processor Consistently Failing**
- **Metric:** Processor failure rate
- **Condition:** > 80% failure rate for specific processor in last hour
- **Impact:** Missing data for one source
- **Action:** Investigate specific processor

```sql
-- Alert query
WITH processor_stats AS (
  SELECT
    processor_name,
    COUNTIF(status = 'failed') as failures,
    COUNT(*) as total
  FROM `nba-props-platform.nba_orchestration.processor_execution_log`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  GROUP BY processor_name
)
SELECT
  processor_name,
  failures,
  total,
  ROUND(failures * 100.0 / total, 1) as failure_rate
FROM processor_stats
WHERE failures * 100.0 / total > 80
  AND total >= 5;
-- Alert if failure rate > 80% and at least 5 attempts
```

**Runbook:** See "High: Processor Failing" below

---

#### 5. **Backfill Stalled (No Progress)**
- **Metric:** Backfill progress tracking
- **Condition:** No new dates completed in last 2 hours during active backfill
- **Impact:** Backfill not completing, delaying features
- **Action:** Check backfill job status

```sql
-- Alert query (assumes backfill tracking table)
WITH recent_progress AS (
  SELECT MAX(completed_at) as last_completion
  FROM `nba-props-platform.nba_orchestration.backfill_progress`
  WHERE status = 'completed'
)
SELECT
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_completion, HOUR) as hours_stalled
FROM recent_progress
WHERE TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_completion, HOUR) > 2;
-- Alert if > 2 hours with no progress
```

**Runbook:** See "High: Backfill Stalled" below

---

#### 6. **DLQ Has Messages (Any Count > 0)**
- **Metric:** DLQ message count
- **Condition:** > 0 messages for > 5 minutes
- **Impact:** Some processing failures occurred
- **Action:** Review DLQ and trigger recovery if needed

```bash
# Alert if DLQ count > 0 for 5+ minutes
gcloud monitoring alert-policies create \
  --notification-channels="CHANNEL_ID" \
  --display-name="DLQ Messages Detected" \
  --condition-filter='metric.type="pubsub.googleapis.com/subscription/num_undelivered_messages"
    resource.type="pubsub_subscription"
    resource.label.subscription_id="nba-phase1-scrapers-complete-dlq-sub"' \
  --condition-threshold-value=0 \
  --condition-threshold-comparison=COMPARISON_GT \
  --condition-threshold-duration=300s
```

**Runbook:** See "High: DLQ Messages" below

---

### Medium Alerts (Respond in 1 Hour)

**Email Only:**

#### 7. **Slow Processing (Performance Degradation)**
- **Metric:** Processing duration
- **Condition:** Phase 2 taking > 10 minutes (normally 2-3 min)
- **Impact:** Delays downstream processing
- **Action:** Check resource utilization

```sql
-- Alert query
SELECT
  processor_name,
  AVG(TIMESTAMP_DIFF(processed_at, triggered_at, SECOND)) as avg_duration_sec
FROM `nba-props-platform.nba_orchestration.processor_execution_log`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND processor_name LIKE 'phase2_%'
GROUP BY processor_name
HAVING avg_duration_sec > 600;
-- Alert if avg > 10 minutes
```

---

#### 8. **Quality Score Degraded (Early Season)**
- **Metric:** Average quality score
- **Condition:** < 50 for Phase 4 processors
- **Impact:** Predictions may be less accurate
- **Action:** Review, may be expected for early season

```sql
-- Alert query
SELECT AVG(quality_score) as avg_quality
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE('America/New_York')
HAVING avg_quality < 50;
-- Alert if average quality < 50
```

---

#### 9. **Cross-Date Dependency Blocker**
- **Metric:** Phase 4 cannot run
- **Condition:** Missing required Phase 3 historical dates
- **Impact:** Phase 4 processing blocked
- **Action:** Backfill missing Phase 3 dates

```sql
-- Alert query (check if Phase 4 can run for today)
WITH required_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
),
available_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
)
SELECT COUNT(*) as missing_dates
FROM required_dates r
LEFT JOIN available_dates a ON r.game_date = a.game_date
WHERE a.game_date IS NULL
HAVING missing_dates > 0;
-- Alert if any required dates missing
```

---

### Low Alerts (Daily Digest)

**Email Digest (Once Daily):**

#### 10. **Backfill Completed Successfully**
- **Metric:** Backfill completion
- **Condition:** All dates validated complete
- **Impact:** Informational (good news!)
- **Action:** None required

#### 11. **Approaching GCP Quota Limits**
- **Metric:** Quota usage
- **Condition:** > 80% of daily quota
- **Impact:** May need quota increase
- **Action:** Review and request increase if needed

#### 12. **Disk Space Usage High**
- **Metric:** GCS bucket size
- **Condition:** > 90% of expected capacity
- **Impact:** May need cleanup or expansion
- **Action:** Review old data for archival

---

## 🚨 Escalation Paths

### On-Call Rotation

**Primary On-Call:**
- **Hours:** 24/7 rotation
- **Response:** All Critical and High alerts
- **Tools:** PagerDuty, Slack (#nba-alerts)
- **Escalation:** 15 minutes no response → Secondary

**Secondary On-Call:**
- **Hours:** Backup for primary
- **Response:** If primary doesn't respond in 15 min
- **Escalation:** 15 minutes no response → Team Lead

**Team Lead:**
- **Hours:** Business hours (9am-6pm PT)
- **Response:** Escalated incidents, major outages
- **Escalation:** 30 minutes no response → Engineering Manager

---

### Escalation Decision Tree

```
Alert Fires
  ↓
Is it CRITICAL?
  ├─ YES → Page Primary On-Call (PagerDuty)
  │         ↓
  │         15 min no response?
  │         ↓
  │         Page Secondary On-Call
  │         ↓
  │         15 min no response?
  │         ↓
  │         Call Team Lead
  │
  └─ NO → Is it HIGH?
      ├─ YES → Slack + Email to Primary On-Call
      │         ↓
      │         1 hour no response?
      │         ↓
      │         Escalate to Team Lead
      │
      └─ NO → Is it MEDIUM?
          ├─ YES → Email to Primary On-Call
          │         ↓
          │         4 hours no response?
          │         ↓
          │         Mention in daily standup
          │
          └─ NO → LOW (Daily digest email)
```

---

## 📖 On-Call Runbooks

### Critical: Phase 2 Outage

**Symptoms:**
- All Phase 2 processors failing
- DLQ filling rapidly
- No new data in BigQuery raw tables

**Diagnosis:**
```bash
# Check Phase 2 service health
gcloud run services describe nba-phase2-raw-processors \
  --region us-west2 --format="value(status.conditions)"

# Check recent logs
gcloud run services logs read nba-phase2-raw-processors \
  --region us-west2 --limit=50

# Check Pub/Sub subscription
gcloud pubsub subscriptions describe nba-phase2-raw-sub \
  --format="value(pushConfig.pushEndpoint,ackDeadlineSeconds)"
```

**Common Causes:**
1. **Cloud Run service down** → Redeploy service
2. **Code bug in recent deployment** → Rollback to previous revision
3. **BigQuery permissions issue** → Check service account permissions
4. **Pub/Sub subscription misconfigured** → Verify subscription settings

**Resolution Steps:**
1. Check if this is a recent deployment → Rollback if needed
2. Check Cloud Run error logs for specific error
3. If permissions issue → Grant required permissions
4. If service down → Redeploy
5. Monitor for 5 minutes to confirm recovery
6. Run DLQ recovery workflow (see DLQ guide)

**Escalate If:**
- Cannot identify root cause in 15 minutes
- Rollback doesn't resolve issue
- Multiple services affected (broader GCP issue)

---

### Critical: DLQ Growing

**Symptoms:**
- DLQ message count > 10 and increasing
- Processing failures in Phase 2

**Diagnosis:**
```bash
# View DLQ messages
./bin/recovery/view_dlq.sh

# Check what's failing
gcloud run services logs read nba-phase2-raw-processors \
  --region us-west2 --limit=100 | grep ERROR
```

**Common Causes:**
1. **Temporary outage** (messages will accumulate, then recover)
2. **Code bug** (specific scraper or processor failing)
3. **Data format change** (scraper output changed, processor can't parse)
4. **Resource limits** (memory/CPU exceeded)

**Resolution Steps:**
1. Identify pattern in DLQ messages (same scraper? same date?)
2. Check Phase 2 logs for error details
3. If code bug → Fix and deploy
4. If temporary → Wait for recovery, then run DLQ recovery
5. If data format → Update processor to handle new format
6. Follow DLQ recovery guide after issue resolved

**Escalate If:**
- Issue is code bug requiring immediate fix
- Cannot identify root cause
- Data loss risk (critical scrapers affected)

**Reference:** `docs/operations/02-dlq-recovery-guide.md`

---

### Critical: No Data for Today

**Symptoms:**
- Zero rows in Phase 2 tables for current date
- Time is past 6am ET (scrapers should have run)

**Diagnosis:**
```bash
# Check if Phase 1 scrapers ran
gcloud scheduler jobs list --location=us-west2 | grep nba-scraper-scheduler

# Check scraper execution log
bq query --use_legacy_sql=false "
SELECT scraper_name, status, COUNT(*) as count
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE DATE(triggered_at, 'America/New_York') = CURRENT_DATE('America/New_York')
GROUP BY scraper_name, status
"

# Check if Phase 2 received messages
gcloud pubsub topics list | grep phase1-scrapers-complete
```

**Common Causes:**
1. **Cloud Scheduler didn't fire** → Check scheduler status
2. **Phase 1 workflow failed** → Check workflow execution logs
3. **Pub/Sub not delivering** → Check topic/subscription health
4. **Phase 2 not processing** → Check service health

**Resolution Steps:**
1. Identify which phase failed (1 or 2)
2. If Phase 1 didn't run → Manually trigger workflow
3. If Phase 2 didn't process → Check service health
4. If Pub/Sub issue → Verify subscriptions
5. Monitor recovery
6. Validate data appears in BigQuery

**Escalate If:**
- Multiple phases failing (systemic issue)
- Manual trigger doesn't work
- GCP service outage suspected

---

### High: Processor Failing

**Symptoms:**
- Single processor has high failure rate (>80%)
- Other processors working fine

**Diagnosis:**
```bash
# Check specific processor logs
PROCESSOR_NAME="phase2-nbac-gamebook"
gcloud run jobs executions list --job=$PROCESSOR_NAME \
  --region=us-central1 --limit=20

# Check error details
gcloud run jobs logs read $PROCESSOR_NAME \
  --region=us-central1 --limit=100 | grep ERROR
```

**Common Causes:**
1. **Data source changed format** → Update processor parsing logic
2. **API rate limit hit** → Implement backoff/retry
3. **Specific date has bad data** → May be transient, wait for next run
4. **Code bug for edge case** → Fix and deploy

**Resolution Steps:**
1. Review error messages in logs
2. Check if issue is date-specific or persistent
3. If data format changed → Update processor
4. If rate limit → Reduce frequency or implement backoff
5. If transient → Monitor next execution
6. Document issue and resolution

**Escalate If:**
- Issue is critical data source (injuries, odds)
- Requires immediate code change
- Pattern suggests broader issue

---

### High: Backfill Stalled

**Symptoms:**
- Backfill started but no progress in 2+ hours
- Expected completion time passed

**Diagnosis:**
```bash
# Check backfill progress
./bin/backfill/check_existing.sh <start_date> <end_date>

# Check Cloud Run job status
gcloud run jobs executions list --job=phase2-nbac-gamebook \
  --region=us-central1 --limit=10

# Check for errors
gcloud run jobs logs read phase2-nbac-gamebook \
  --region=us-central1 --limit=100 | grep ERROR
```

**Common Causes:**
1. **Job failed silently** → Check execution status
2. **Dependency not met** → Missing Phase 3 data
3. **Resource exhaustion** → Memory/CPU limits hit
4. **Validation failed** → Errors in specific dates

**Resolution Steps:**
1. Identify which phase stalled
2. Check job execution logs for errors
3. If dependency issue → Backfill prerequisite phase first
4. If resource issue → Increase limits
5. If validation failed → Fix and retry
6. Resume from last successful date

**Escalate If:**
- Blocking critical deadline
- Cannot identify cause
- Requires infrastructure changes

---

### High: DLQ Messages

**Symptoms:**
- DLQ has messages (any count > 0 for 5+ minutes)
- Processing failures occurred

**Diagnosis:**
```bash
# View DLQ messages
./bin/recovery/view_dlq.sh

# Check if data gaps exist
./bin/recovery/find_data_gaps.sh 7 bdl_injuries
```

**Resolution Steps:**
1. Review DLQ messages to understand what failed
2. Check if underlying issue resolved (check Phase 2 logs)
3. Run gap detection to find missing data
4. Trigger recovery for gaps
5. Validate recovery succeeded
6. Clear DLQ after validation

**Reference:** `docs/operations/02-dlq-recovery-guide.md`

**Escalate If:**
- DLQ keeps filling (ongoing issue)
- Critical data source affected
- Recovery attempts failing

---

## 🔕 Alert Fatigue Prevention

### Strategies to Reduce Noise

#### 1. **Intelligent Grouping**
- Group alerts by incident (don't alert for each failed processor if all failing)
- Example: "Phase 2 Outage" instead of 20 separate processor alerts

#### 2. **Temporal Damping**
- Don't re-alert if condition persists (alert once, then every 30 min)
- Example: DLQ alert fires once, then only if count doubles

#### 3. **Auto-Resolution Detection**
- Clear alert automatically when condition resolves
- Example: DLQ count returns to 0 → Auto-resolve

#### 4. **Expected Degradation Flags**
- Mark early season as "expected degradation" → Lower severity
- Example: Quality score < 50 in October = Medium, in January = High

#### 5. **Maintenance Windows**
- Suppress alerts during known maintenance
- Example: Disable backfill stalled alerts during scheduled maintenance

#### 6. **Self-Healing Detection**
- If issue resolves before human intervention → Log but don't alert
- Example: Transient Pub/Sub delay that auto-recovers

---

### Alert Tuning Guidelines

**Review alert effectiveness monthly:**
- **False positive rate:** What % of alerts don't require action?
- **Response time:** How long to resolve on average?
- **Actionability:** Can on-call take clear action?
- **Severity accuracy:** Is severity level appropriate?

**Adjust thresholds based on data:**
- Too many alerts → Increase threshold or add damping
- Missing incidents → Decrease threshold or add new alert
- Wrong severity → Reclassify based on actual impact

---

### Daily Digest Configuration

**Low priority alerts grouped into daily email:**
- **Send Time:** 9am PT daily
- **Recipients:** Engineering team (not on-call)
- **Content:**
  - Successful backfills completed
  - Quota usage updates
  - Performance metrics summary
  - Upcoming maintenance windows

**Format:**
```
Daily NBA Pipeline Digest - 2025-11-18

✅ Successful Operations:
  - Backfill completed: Nov 8-14 (7 dates, all phases)
  - All Phase 2 processors: 100% success rate

📊 Metrics:
  - Processing time: Avg 2.3 min (normal)
  - Quality scores: Avg 95 (excellent)
  - DLQ depth: 0 messages

⚠️ Informational:
  - GCS bucket: 78% of expected capacity
  - BigQuery quota: 45% used (normal)

🔧 Upcoming:
  - No scheduled maintenance
```

---

## 📊 Alert Dashboard

### Grafana Alert Panel

**Recommended dashboard:**
- **Panel 1:** Current alert count by severity
- **Panel 2:** Alert history (last 24 hours)
- **Panel 3:** MTTD (Mean Time To Detect)
- **Panel 4:** MTTR (Mean Time To Resolve)
- **Panel 5:** Top 10 alerting processors
- **Panel 6:** DLQ depth over time

**Query Example (Alert Count by Severity):**
```sql
SELECT
  severity,
  COUNT(*) as alert_count
FROM `nba-props-platform.nba_monitoring.alert_history`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND status = 'active'
GROUP BY severity
ORDER BY
  CASE severity
    WHEN 'critical' THEN 1
    WHEN 'high' THEN 2
    WHEN 'medium' THEN 3
    ELSE 4
  END;
```

---

## 🔗 Related Documentation

**Operations:**
- `docs/operations/02-dlq-recovery-guide.md` - DLQ recovery procedures
- `docs/operations/01-backfill-operations-guide.md` - Backfill operations

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring
- `docs/monitoring/02-grafana-daily-health-check.md` - Daily health check
- `docs/monitoring/05-data-completeness-validation.md` - Validation queries
- `docs/monitoring/07-single-entity-debugging.md` - Debug specific entities

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub health checks

---

## 📝 Quick Reference

### Alert Severity Decision Tree

```
Is production completely broken?
  ├─ YES → CRITICAL (page immediately)
  │
  └─ NO → Is data being lost or significantly delayed?
      ├─ YES → HIGH (Slack + Email, 15 min response)
      │
      └─ NO → Is there degraded performance?
          ├─ YES → MEDIUM (Email, 1 hour response)
          │
          └─ NO → LOW (Daily digest)
```

---

### On-Call Quick Commands

```bash
# Check DLQ
./bin/recovery/view_dlq.sh

# Check Phase 2 health
gcloud run services describe nba-phase2-raw-processors --region us-west2

# Check recent errors
gcloud run services logs read nba-phase2-raw-processors --region us-west2 --limit=50 | grep ERROR

# Check backfill progress
./bin/backfill/check_existing.sh <start> <end>

# Run health check
./bin/orchestration/quick_health_check.sh
```

---

**Created:** 2025-11-18 15:30 PST
**Next Review:** After first month of on-call rotation
**Status:** ✅ Ready to use
