# Quota Monitoring Deployment Checklist

**Task:** #14 - Add quota usage metrics and alerting
**Date:** 2026-01-26
**Status:** Ready for Deployment

---

## Pre-Deployment Verification ✅

- [x] Code changes implemented in `pipeline_logger.py`
- [x] Metrics API tested and working (`get_buffer_metrics()`)
- [x] SQL query syntax validated
- [x] Dashboard JSON structure verified
- [x] Setup script tested (dry-run)
- [x] Test suite created and passing
- [x] Documentation complete

---

## Deployment Steps

### Phase 1: Infrastructure Setup (15-20 minutes)

**Prerequisites:**
- [ ] GCP project ID
- [ ] `bigquery.admin` permissions
- [ ] `monitoring.admin` permissions
- [ ] `gcloud` CLI authenticated
- [ ] `bq` CLI installed

**Steps:**

1. **Get Notification Channel ID**
   ```bash
   gcloud alpha monitoring channels list --project=<YOUR_PROJECT_ID>
   # Copy the channel ID for email/slack notifications
   ```

2. **Run Setup Script**
   ```bash
   cd /home/naji/code/nba-stats-scraper/monitoring/scripts
   ./setup_quota_alerts.sh <PROJECT_ID> <NOTIFICATION_CHANNEL_ID>
   ```

   **Expected Output:**
   - [x] BigQuery table `nba_orchestration.quota_usage_hourly` created
   - [x] Scheduled query "Pipeline Quota Usage Tracking" created
   - [x] Warning about log-based metrics (manual step)
   - [x] Alert policies created (if notification channel provided)

3. **Verify BigQuery Setup**
   ```bash
   # Check table exists
   bq show nba_orchestration.quota_usage_hourly

   # Check scheduled query
   bq ls --transfer_config --transfer_location=US
   ```

---

### Phase 2: Cloud Monitoring Configuration (20-30 minutes)

**Steps:**

1. **Create Log-Based Metrics**

   Navigate to: **Cloud Console > Logging > Logs-based Metrics**

   **Metric 1: Events Buffered**
   - [ ] Click "Create Metric"
   - [ ] Name: `pipeline/events_buffered`
   - [ ] Type: Counter
   - [ ] Filter:
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Pipeline Event Buffer Metrics"
     ```
   - [ ] Labels: Add `processor_name`, `phase` from jsonPayload
   - [ ] Click "Create Metric"

   **Metric 2: Batch Flushes**
   - [ ] Name: `pipeline/batch_flushes`
   - [ ] Type: Counter
   - [ ] Filter:
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Flushed .* events to"
     severity="INFO"
     ```

   **Metric 3: Flush Latency**
   - [ ] Name: `pipeline/flush_latency_ms`
   - [ ] Type: Distribution
   - [ ] Filter: (same as Metric 2)
   - [ ] Value field: Extract from message using regex: `latency: (\d+\.?\d*)ms`

   **Metric 4: Flush Failures**
   - [ ] Name: `pipeline/flush_failures`
   - [ ] Type: Counter
   - [ ] Filter:
     ```
     resource.type="cloud_function"
     jsonPayload.message=~"Failed to flush .* events"
     severity="WARNING"
     ```

2. **Import Dashboard**

   Navigate to: **Cloud Console > Monitoring > Dashboards**

   - [ ] Click "Create Dashboard"
   - [ ] Click "⋮" menu > "Import from JSON"
   - [ ] Upload file: `/home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_quota_dashboard.json`
   - [ ] Click "Import"
   - [ ] Verify all 10 charts load correctly

3. **Verify Alert Policies**

   Navigate to: **Cloud Console > Monitoring > Alerting**

   - [ ] Verify "Pipeline Quota Usage Warning" exists
   - [ ] Verify "Pipeline Quota Usage CRITICAL" exists
   - [ ] Verify "Pipeline Event Buffer Flush Failures" exists
   - [ ] Check notification channels are configured
   - [ ] Enable policies if disabled

---

### Phase 3: Testing & Validation (30 minutes)

**Steps:**

1. **Run Test Suite**
   ```bash
   cd /home/naji/code/nba-stats-scraper
   python3 monitoring/scripts/test_quota_metrics.py --events 100 --dry-run
   ```

   **Expected:**
   - [ ] All tests pass (3/3)
   - [ ] Metrics tracked correctly
   - [ ] Batching efficiency verified
   - [ ] Thread safety confirmed

2. **Generate Real Events**
   ```bash
   # Trigger a real pipeline processor to generate events
   # OR use test script without dry-run
   python3 monitoring/scripts/test_quota_metrics.py --events 50
   ```

3. **Verify Data Flow**

   **Check Application Logs:**
   ```bash
   gcloud logging read 'jsonPayload.message=~"Pipeline Event Buffer Metrics"' --limit 10
   ```
   - [ ] Metrics logs appear
   - [ ] Flush logs show latency
   - [ ] No error messages

   **Check BigQuery:**
   ```sql
   -- Check events logged
   SELECT COUNT(*) as event_count
   FROM nba_orchestration.pipeline_event_log
   WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR);

   -- Wait ~1 hour for scheduled query, then check
   SELECT *
   FROM nba_orchestration.quota_usage_hourly
   ORDER BY hour_timestamp DESC
   LIMIT 1;
   ```
   - [ ] Events appear in `pipeline_event_log`
   - [ ] Hourly query populates `quota_usage_hourly` (wait 1+ hour)

   **Check Cloud Monitoring:**
   - [ ] Navigate to dashboard
   - [ ] Verify charts show data (may take 5-10 minutes)
   - [ ] Check metric explorer for custom metrics

4. **Test Alert (Optional)**
   ```python
   # Generate enough events to trigger warning alert (>80 partition mods)
   # With batch_size=50, need ~4000 events
   python3 monitoring/scripts/test_quota_metrics.py --events 4000
   ```
   - [ ] Wait 5-10 minutes
   - [ ] Check for alert notification
   - [ ] Verify alert shows in Cloud Console

---

### Phase 4: Production Monitoring Setup (10 minutes)

**Steps:**

1. **Configure Environment Variables (if needed)**
   ```bash
   # Increase batch size to reduce quota usage
   export PIPELINE_LOG_BATCH_SIZE=100  # Default: 50
   export PIPELINE_LOG_BATCH_TIMEOUT=15.0  # Default: 10.0

   # Restart Cloud Functions/Cloud Run to pick up changes
   ```

2. **Set Up Notification Channels**

   Navigate to: **Cloud Console > Monitoring > Alerting > Notification Channels**

   - [ ] Email notifications configured
   - [ ] Slack/Teams integration (if using)
   - [ ] PagerDuty integration (for critical alerts)
   - [ ] Test notifications send successfully

3. **Document Runbook**
   - [ ] Add to team documentation
   - [ ] Share quick reference with team
   - [ ] Schedule training session (optional)

---

## Post-Deployment Validation (24-48 hours)

**Monitoring Tasks:**

- [ ] Check dashboard daily for anomalies
- [ ] Verify scheduled query runs hourly
- [ ] Monitor alert policy incidents
- [ ] Review quota usage trends

**Success Criteria:**

- [ ] No "403 Quota exceeded" errors
- [ ] Partition modifications stay below 80/hour
- [ ] Flush success rate > 99%
- [ ] Average flush latency < 1000ms
- [ ] No false positive alerts

**If Issues Occur:**

1. Check logs: `gcloud logging read 'jsonPayload.message=~"Failed to flush"' --limit 20`
2. Review metrics: `get_buffer_metrics()` in Python
3. Query BigQuery: Check `quota_usage_hourly` for spikes
4. Adjust thresholds or batch size as needed
5. Consult troubleshooting guide: `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_setup.md`

---

## Rollback Plan

**If deployment causes issues:**

1. **Disable Alert Policies**
   ```bash
   gcloud alpha monitoring policies list --filter="displayName:'Pipeline Quota'" --format="value(name)" | \
   xargs -I {} gcloud alpha monitoring policies update {} --no-enabled
   ```

2. **Pause Scheduled Query**
   - Navigate to BigQuery > Scheduled Queries
   - Find "Pipeline Quota Usage Tracking"
   - Click "Pause"

3. **Revert Code Changes (if needed)**
   - Code changes are backward compatible
   - Metrics collection is passive (no breaking changes)
   - No rollback needed unless critical issues

4. **Remove Dashboard (optional)**
   - Navigate to Cloud Console > Monitoring > Dashboards
   - Delete "Pipeline Quota Usage Dashboard"

---

## Support & Documentation

**Primary Documentation:**
- Setup Guide: `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_setup.md`
- Quick Reference: `/home/naji/code/nba-stats-scraper/monitoring/docs/quota_monitoring_quick_reference.md`
- Main README: `/home/naji/code/nba-stats-scraper/monitoring/README_QUOTA_MONITORING.md`

**Scripts:**
- Setup: `/home/naji/code/nba-stats-scraper/monitoring/scripts/setup_quota_alerts.sh`
- Test: `/home/naji/code/nba-stats-scraper/monitoring/scripts/test_quota_metrics.py`

**Configuration:**
- SQL: `/home/naji/code/nba-stats-scraper/monitoring/queries/quota_usage_tracking.sql`
- Dashboard: `/home/naji/code/nba-stats-scraper/monitoring/dashboards/pipeline_quota_dashboard.json`

**Code:**
- Pipeline Logger: `/home/naji/code/nba-stats-scraper/shared/utils/pipeline_logger.py`

---

## Sign-Off

**Deployed By:** ___________________________
**Date:** ___________________________
**Verified By:** ___________________________
**Date:** ___________________________

**Deployment Status:**
- [ ] Phase 1: Infrastructure Setup - COMPLETE
- [ ] Phase 2: Cloud Monitoring Config - COMPLETE
- [ ] Phase 3: Testing & Validation - COMPLETE
- [ ] Phase 4: Production Monitoring - COMPLETE
- [ ] Post-Deployment Validation - IN PROGRESS

**Notes:**
_Add any deployment notes or observations here_

---

*Deployment checklist version 1.0*
*Last updated: 2026-01-26*
