# Silent Failure Prevention Strategy
**Date:** 2026-01-14
**Status:** DRAFT - For Implementation
**Priority:** P0 - Critical Infrastructure

---

## 🚨 Problem Statement

Today (2026-01-14) we discovered 3 critical silent failures that went undetected:

1. **BDL Box Scores Pipeline Failure** (36+ hours)
   - Jan 12-13 data never reached BigQuery (0/12 games)
   - Root cause: Pub/Sub subscription pointing to wrong URL
   - Impact: Missing box scores for 2 days
   - **Detection method:** Manual check

2. **Cloud Run Deployment Hangs** (10+ hours)
   - 4 deployment attempts all hung with no timeout
   - Root cause: GCP gRPC incident (not officially reported for our region)
   - Impact: Unable to deploy BettingPros fix
   - **Detection method:** Manual timeout after waiting

3. **Data Completeness Gaps** (Unknown duration)
   - Missing data only visible via manual completeness check
   - No proactive alerts for incomplete data
   - **Detection method:** Manual script execution

---

## 🎯 Goals

1. **Zero Silent Failures** - Every failure must be visible
2. **Proactive Detection** - Catch issues before impact grows
3. **Fast Response** - Alert within minutes, not hours
4. **Clear Diagnostics** - Logs must explain what went wrong
5. **Automated Recovery** - Self-healing where possible

---

## 💡 Proposed Solutions

### Category 1: Pipeline Health Monitoring

#### 1.1 Real-Time Data Flow Monitoring
**Problem:** BDL box scores stopped flowing from Phase 1 → Phase 2 for 36+ hours undetected

**Solution:**
```python
# New monitoring service: orchestration/pipeline_health_monitor.py
class PipelineHealthMonitor:
    """
    Monitors data flow between phases in real-time.
    Alerts if expected data doesn't appear within SLA.
    """

    def check_phase1_to_phase2_flow(self):
        """
        For each scraper execution in last hour:
        - Check if GCS file was created ✓
        - Check if Pub/Sub message was sent ✓
        - Check if Phase 2 received message ✓
        - Check if data appeared in BigQuery ✓
        - Alert if any step missing
        """

    def check_sla_violations(self):
        """
        Phase 1 → Phase 2 SLA: 10 minutes
        Phase 2 → Phase 3 SLA: 15 minutes
        Phase 3 → Phase 4 SLA: 30 minutes

        Alert if data stuck longer than SLA
        """
```

**Implementation:**
- Run every 15 minutes via Cloud Scheduler
- Check scraper_execution_log vs actual BigQuery data
- Alert if gap > 10 minutes
- Track metrics in `nba_orchestration.pipeline_health_log`

**Expected Outcome:**
- BDL box score issue would have been detected within 25 minutes
- Alert: "bdl_box_scores: 6 files in GCS, 0 in BigQuery for 25min"

---

#### 1.2 Daily Data Completeness Checks (Automated)
**Problem:** Completeness check script exists but requires manual execution

**Solution:**
```bash
# New Cloud Function: daily_completeness_check
# Trigger: Cloud Scheduler at 8 AM ET daily
# Checks yesterday's data completeness
# Sends alert if any phase < 95% complete
```

**Implementation:**
```python
def check_daily_completeness(date: str) -> Dict:
    """
    Run full completeness check for date.
    Alert on Slack/Email if incomplete.
    """
    results = run_completeness_check(date)

    if results['gamebooks'] < 1.0:
        alert("Gamebooks incomplete", results)
    if results['box_scores'] < 1.0:
        alert("Box scores incomplete", results)
    if results['betting_props'] < 0.95:
        alert("Betting props incomplete", results)

    return results
```

**Schedule:**
- 8:00 AM ET: Check yesterday's data
- 12:00 PM ET: Recheck if issues found
- 4:00 PM ET: Final check + escalation if still incomplete

**Expected Outcome:**
- Jan 12 missing box scores detected by 8 AM on Jan 13
- Automatic alert with specifics: "0/6 box scores for 2026-01-12"

---

#### 1.3 Pub/Sub Subscription Health Checks
**Problem:** Subscription pointing to wrong URL had no visibility

**Solution:**
```python
# New check: orchestration/pubsub_health_check.py
def validate_pubsub_subscriptions():
    """
    For each critical subscription:
    - Verify pushEndpoint is reachable (HTTP 200/403)
    - Verify service actually exists at that URL
    - Check for high undelivered message count
    - Check for high NACK rate
    - Alert if unhealthy
    """

    for sub in CRITICAL_SUBSCRIPTIONS:
        endpoint = get_push_endpoint(sub)

        # Check 1: Endpoint exists
        if not endpoint_reachable(endpoint):
            alert(f"Subscription {sub} points to unreachable endpoint")

        # Check 2: Dead letter queue accumulating
        dlq_count = get_dlq_message_count(sub)
        if dlq_count > 100:
            alert(f"Subscription {sub} DLQ has {dlq_count} messages")

        # Check 3: Old undelivered messages
        oldest_message = get_oldest_undelivered_message_age(sub)
        if oldest_message > 3600:  # 1 hour
            alert(f"Subscription {sub} has messages stuck for {oldest_message}s")
```

**Schedule:** Every 30 minutes

**Expected Outcome:**
- Wrong URL detected within 30 minutes of subscription update
- Alert: "nba-phase2-raw-sub points to non-existent service"

---

### Category 2: Deployment Safety

#### 2.1 Deployment Timeout Protection
**Problem:** Cloud Run deployments hung for 10+ hours with no timeout

**Solution:**
```bash
# Update bin/scrapers/deploy/deploy_scrapers_simple.sh
# Add aggressive timeout with fallback

deploy_with_timeout() {
    # Try deployment with 10-minute timeout
    timeout 600 gcloud run deploy ... || DEPLOY_FAILED=true

    if [ "$DEPLOY_FAILED" = true ]; then
        echo "❌ Deployment timed out after 10 minutes"
        echo "🔍 Checking GCP status..."
        check_gcp_service_health

        echo "💡 Suggested actions:"
        echo "   1. Check https://status.cloud.google.com/"
        echo "   2. Try: gcloud run deploy via Cloud Shell"
        echo "   3. Try: Deploy to different region (us-central1)"

        exit 1
    fi
}
```

**Additional Protection:**
- Set `--timeout=300` flag on all gcloud commands
- Add deployment health check after timeout
- Suggest alternatives (Cloud Shell, different region)

**Expected Outcome:**
- Deployment failure detected in 10 minutes (not 10 hours)
- Clear error message with next steps

---

#### 2.2 Deployment Smoke Tests
**Problem:** No verification that deployment actually works

**Solution:**
```bash
# After deployment, run smoke tests
post_deploy_smoke_test() {
    echo "🧪 Running post-deployment smoke tests..."

    # Test 1: Health endpoint
    health_status=$(curl -s $SERVICE_URL/health | jq -r '.status')
    if [ "$health_status" != "healthy" ]; then
        alert "Deployment health check failed"
        rollback_deployment
    fi

    # Test 2: Sample scraper execution
    test_result=$(curl -s -X POST $SERVICE_URL/scrapers/bdl_box_scores \
      -d '{"date":"2024-01-01","debug":true}')

    if echo "$test_result" | grep -q "error"; then
        alert "Scraper test failed after deployment"
        rollback_deployment
    fi

    echo "✅ Smoke tests passed"
}
```

**Expected Outcome:**
- Bad deployments caught immediately
- Automatic rollback if smoke tests fail

---

### Category 3: Enhanced Logging

#### 3.1 Structured Error Logs with Context
**Problem:** Errors like "Invalid Pub/Sub Format" don't include the actual message

**Solution:**
```python
# Update all error logging to include full context
def log_error_with_context(error_msg: str, context: Dict):
    """
    Log error with full diagnostic context.
    """
    logger.error(
        error_msg,
        extra={
            'error_details': context,
            'timestamp': datetime.utcnow().isoformat(),
            'environment': os.environ.get('ENV', 'unknown'),
            'service': 'phase2-processor',
            'trace_id': get_trace_id()
        }
    )

    # Also send to error tracking service
    sentry.capture_exception(
        Exception(error_msg),
        extra=context
    )

# Example usage:
if 'message' not in envelope:
    log_error_with_context(
        "Invalid Pub/Sub Format: Missing 'message' field",
        context={
            'envelope_keys': list(envelope.keys()),
            'envelope_sample': str(envelope)[:500],  # First 500 chars
            'subscription': request.headers.get('X-Subscription'),
            'message_id': envelope.get('subscription', 'unknown')
        }
    )
```

**Expected Outcome:**
- Error logs include enough info to debug without SSHing into service
- "Invalid Pub/Sub Format" would show the actual envelope structure

---

#### 3.2 Pipeline Tracing
**Problem:** Hard to trace a single file through all phases

**Solution:**
```python
# Add trace_id to all messages
class PipelineTracer:
    """
    Track a single file through all pipeline phases.
    """

    def create_trace(self, scraper_name: str, date: str) -> str:
        """Generate unique trace ID for this execution."""
        trace_id = f"{scraper_name}_{date}_{uuid.uuid4().hex[:8]}"
        return trace_id

    def log_phase_transition(self, trace_id: str, from_phase: str, to_phase: str):
        """Log when data moves between phases."""
        logger.info(
            f"Pipeline trace {trace_id}: {from_phase} → {to_phase}",
            extra={'trace_id': trace_id, 'from': from_phase, 'to': to_phase}
        )

    def find_stuck_traces(self) -> List[str]:
        """Find traces stuck in a phase for too long."""
        query = """
        SELECT trace_id, phase,
               TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_update, MINUTE) as stuck_minutes
        FROM pipeline_traces
        WHERE stuck_minutes > 60
        """
        return execute_bigquery(query)
```

**Usage:**
```python
# Phase 1 scraper
trace_id = tracer.create_trace('bdl_box_scores', '2026-01-12')
publish_message(data, trace_id=trace_id)

# Phase 2 processor
tracer.log_phase_transition(trace_id, 'phase1_scraper', 'phase2_processor')

# Phase 3 analytics
tracer.log_phase_transition(trace_id, 'phase2_processor', 'phase3_analytics')
```

**Expected Outcome:**
- Can query: "Where did bdl_box_scores for 2026-01-12 get stuck?"
- Answer: "Stuck between phase1_scraper and phase2_processor for 36 hours"

---

### Category 4: Self-Healing Improvements

#### 4.1 Dead Letter Queue Monitoring
**Problem:** DLQ exists but not monitored

**Solution:**
```python
# New monitor: orchestration/dlq_monitor.py
def check_dead_letter_queues():
    """
    Check all DLQs for stuck messages.
    Alert if DLQ has messages > 1 hour old.
    Attempt automatic reprocessing for recoverable errors.
    """

    for dlq in ALL_DLQS:
        messages = pull_dlq_messages(dlq, max_count=100)

        if len(messages) > 0:
            alert(f"DLQ {dlq} has {len(messages)} messages")

            # Attempt recovery for known recoverable errors
            for msg in messages:
                error_type = analyze_error(msg)

                if error_type in RECOVERABLE_ERRORS:
                    retry_message(msg, original_topic)
                    logger.info(f"Recovered {msg.id} from DLQ")
                else:
                    logger.error(f"DLQ message {msg.id} needs manual intervention")
```

**Schedule:** Every 15 minutes

**Expected Outcome:**
- DLQ messages detected and either recovered or escalated
- No silent failures accumulating in DLQ

---

#### 4.2 Subscription Auto-Healing
**Problem:** Subscription URL can become stale when services redeploy

**Solution:**
```python
# New service: orchestration/subscription_auto_healer.py
def validate_and_heal_subscriptions():
    """
    Verify all Pub/Sub subscriptions point to correct URLs.
    Auto-heal if service URL has changed.
    """

    for sub_name, expected_service in SUBSCRIPTION_MAPPINGS.items():
        # Get current push endpoint
        current_endpoint = get_subscription_endpoint(sub_name)

        # Get actual service URL
        actual_url = get_cloud_run_service_url(expected_service)

        # Check if mismatch
        if not current_endpoint.startswith(actual_url):
            logger.warning(
                f"Subscription {sub_name} URL mismatch:\n"
                f"  Current:  {current_endpoint}\n"
                f"  Expected: {actual_url}"
            )

            # Auto-heal
            update_subscription_endpoint(sub_name, actual_url + '/process')

            alert(
                f"Auto-healed subscription {sub_name}",
                details={'old': current_endpoint, 'new': actual_url}
            )
```

**Schedule:** Every 1 hour

**Expected Outcome:**
- URL mismatches detected and fixed automatically
- Today's BDL issue would have been prevented entirely

---

### Category 5: Alerting Strategy

#### 5.1 Alert Tiers
**Problem:** All alerts treated equally, causing alert fatigue

**Solution:**
```python
class AlertTier(Enum):
    P0_CRITICAL = "critical"  # Page on-call, immediate action required
    P1_HIGH = "high"          # Email + Slack, action within 1 hour
    P2_MEDIUM = "medium"      # Slack only, action within 4 hours
    P3_LOW = "low"            # Daily digest, action within 24 hours

# Examples:
# P0: 0/6 box scores for today (production data loss)
# P1: Pub/Sub subscription unhealthy (may cause future data loss)
# P2: Deployment took longer than usual (no immediate impact)
# P3: Cleanup processor republished 2 messages (normal recovery)
```

**Implementation:**
- P0: SMS + Email + Slack #alerts-critical
- P1: Email + Slack #alerts-high
- P2: Slack #alerts-medium
- P3: Daily digest email

---

#### 5.2 Alert Deduplication
**Problem:** Same issue generates 100+ alerts

**Solution:**
```python
class AlertDeduplicator:
    """
    Group similar alerts to prevent spam.
    """

    def should_send_alert(self, alert_key: str, content: str) -> bool:
        """
        Only send alert if:
        - First occurrence
        - 1 hour since last alert for this key
        - Content changed significantly
        """

        last_alert = get_last_alert_time(alert_key)

        if last_alert is None:
            return True  # First occurrence

        if (datetime.now() - last_alert) > timedelta(hours=1):
            return True  # Alert again after 1 hour

        return False  # Suppress duplicate

# Usage:
if deduplicator.should_send_alert('bdl_box_scores_missing', message):
    send_alert(message)
else:
    logger.info(f"Suppressed duplicate alert: {message}")
```

---

## 📊 Metrics to Track

### Pipeline Health Metrics
```sql
-- Dashboard: Pipeline Health
CREATE VIEW pipeline_health_metrics AS
SELECT
    DATE(execution_time) as date,
    phase,
    COUNT(*) as executions,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
    AVG(duration_seconds) as avg_duration,
    MAX(duration_seconds) as max_duration,
    COUNTIF(duration_seconds > sla_threshold) as sla_violations
FROM pipeline_execution_log
GROUP BY date, phase
```

### Data Completeness Metrics
```sql
-- Dashboard: Data Completeness
CREATE VIEW daily_completeness_metrics AS
SELECT
    game_date,
    expected_games,
    actual_gamebooks,
    actual_box_scores,
    actual_betting_props,
    (actual_box_scores / expected_games) as box_score_completeness,
    (actual_betting_props / (expected_games * 150)) as props_completeness
FROM data_completeness_daily
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

### Alert Metrics
```sql
-- Dashboard: Alert Health
CREATE VIEW alert_metrics AS
SELECT
    DATE(alert_time) as date,
    alert_tier,
    alert_category,
    COUNT(*) as alert_count,
    COUNT(DISTINCT alert_key) as unique_alerts,
    AVG(TIMESTAMP_DIFF(resolution_time, alert_time, MINUTE)) as avg_resolution_minutes
FROM alert_log
GROUP BY date, alert_tier, alert_category
```

---

## 🚀 Implementation Plan

### Phase 1: Quick Wins (This Week)
**Priority: P0 - Deploy immediately**

1. ✅ Fix BDL Pub/Sub subscription URL (DONE)
2. Add deployment timeouts to all scripts
3. Deploy daily completeness check Cloud Function
4. Add context to "Invalid Pub/Sub Format" error

**Estimated Time:** 4 hours
**Impact:** Prevents 80% of today's issues

---

### Phase 2: Monitoring Foundation (Next Week)
**Priority: P0 - Critical infrastructure**

1. Implement Pipeline Health Monitor
2. Implement Pub/Sub Subscription Health Check
3. Set up DLQ monitoring
4. Create alerting tiers

**Estimated Time:** 2 days
**Impact:** Proactive detection of all pipeline issues

---

### Phase 3: Self-Healing (Week 3-4)
**Priority: P1 - Reduce manual intervention**

1. Subscription auto-healer
2. Enhanced cleanup processor
3. Automatic DLQ recovery
4. Deployment smoke tests

**Estimated Time:** 3 days
**Impact:** 90% of issues auto-resolve

---

### Phase 4: Advanced Observability (Month 2)
**Priority: P2 - Nice to have**

1. Pipeline tracing with trace IDs
2. Distributed tracing (OpenTelemetry)
3. Comprehensive dashboards
4. SLA monitoring and reporting

**Estimated Time:** 1 week
**Impact:** Complete visibility into system health

---

## ✅ Success Metrics

### Before (Current State)
- **Silent Failure Rate:** 100% (3/3 issues today were silent)
- **Mean Time to Detection (MTTD):** 36+ hours
- **Manual Detection:** 100% (all issues found manually)
- **Alert Coverage:** ~10% of failure modes

### After Phase 1 (Target)
- **Silent Failure Rate:** <20%
- **MTTD:** <2 hours
- **Manual Detection:** <50%
- **Alert Coverage:** ~60%

### After Phase 2 (Target)
- **Silent Failure Rate:** <5%
- **MTTD:** <15 minutes
- **Manual Detection:** <10%
- **Alert Coverage:** ~90%

### After Phase 4 (Target)
- **Silent Failure Rate:** <1%
- **MTTD:** <5 minutes
- **Manual Detection:** 0% (all issues detected automatically)
- **Alert Coverage:** ~99%

---

## 📚 Related Documentation

- `docs/08-projects/current/silent-failure-prevention/` - This project
- `scripts/check_data_completeness.py` - Existing completeness checker
- `orchestration/cleanup_processor.py` - Existing self-healing
- `docs/00-start-here/BACKFILL-VERIFICATION-GUIDE.md` - Manual verification process

---

## 💭 Lessons Learned (2026-01-14)

1. **Pub/Sub subscriptions can become stale** when services redeploy to new URLs
2. **Cleanup processor is working** but won't help if subscription is broken
3. **Error logs need context** - "Invalid format" is useless without the actual payload
4. **GCP incidents may not be fully reported** - trust your systems, not status pages
5. **Manual checks are not sustainable** - automation is critical
6. **Silent = Invisible** - If it doesn't alert, it doesn't exist

---

**Status:** DRAFT
**Next Steps:** Review with team, prioritize Phase 1 quick wins, create tickets

---

*Created: 2026-01-14*
*Last Updated: 2026-01-14*
*Owner: Engineering Team*
