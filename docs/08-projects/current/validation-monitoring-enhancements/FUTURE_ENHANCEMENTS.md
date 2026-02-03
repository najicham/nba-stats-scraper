# Validation & Monitoring Future Enhancements

**Created:** February 3, 2026 (Session 89)
**Status:** Planning / Backlog
**Context:** Post-completion of validation improvements project (100% done!)

---

## Overview

Now that the core validation improvements project is complete (11/11 checks implemented), this document outlines future enhancements to make the validation and monitoring systems even more powerful.

**Current State:**
- ✅ 8 pre-commit hooks and deployment checks
- ✅ 4 monitoring scripts
- ✅ Protection for 8 services and 20 tables
- ✅ Prevention of 8 bug classes

**Future Vision:**
- Automated validation dashboards
- Predictive anomaly detection
- Integrated alerting and auto-remediation
- Comprehensive observability

---

## Priority Levels

- **P0** - Critical: Prevents data loss or major outages
- **P1** - High: Significantly improves reliability or reduces toil
- **P2** - Medium: Nice to have, improves observability
- **P3** - Low: Future-looking, experimental

---

## Phase 4: Advanced Pre-commit Validation (P0-P1)

### P0-4: Schema Evolution Tracking
**Problem:** Schema changes (adding/removing fields) can break queries or cause data loss
**Current State:** We validate current schema alignment, but not evolution over time

**Implementation:**
```python
# .pre-commit-hooks/validate_schema_evolution.py

def detect_breaking_changes(old_schema, new_schema):
    """
    Detect breaking schema changes:
    - Field removals (breaks existing queries)
    - Type changes (STRING -> INT breaks writes)
    - Mode changes (NULLABLE -> REQUIRED breaks nulls)
    - Partition field changes (breaks existing queries)
    """

    breaking = []

    # Detect removed fields
    removed = set(old_schema.keys()) - set(new_schema.keys())
    if removed:
        breaking.append({
            'type': 'FIELD_REMOVAL',
            'fields': list(removed),
            'impact': 'Existing queries will fail'
        })

    # Detect type changes
    for field in set(old_schema.keys()) & set(new_schema.keys()):
        if old_schema[field]['type'] != new_schema[field]['type']:
            breaking.append({
                'type': 'TYPE_CHANGE',
                'field': field,
                'old': old_schema[field]['type'],
                'new': new_schema[field]['type'],
                'impact': 'Writes with old type will fail'
            })

    return breaking
```

**Benefits:**
- Catches breaking changes before deployment
- Enforces backward compatibility
- Documents schema evolution

**Effort:** 4 hours
**Impact:** Prevents production schema breaks

---

### P1-5: Query Performance Validation
**Problem:** Slow queries can timeout or cause OOM in production
**Current State:** No validation of query performance before deployment

**Implementation:**
```python
# .pre-commit-hooks/validate_query_performance.py

def estimate_query_cost(query: str) -> dict:
    """
    Use BigQuery dry run to estimate:
    - Bytes processed
    - Slot time
    - Cost estimate
    """

    from google.cloud import bigquery
    client = bigquery.Client()

    job_config = bigquery.QueryJobConfig(dry_run=True)
    job = client.query(query, job_config=job_config)

    return {
        'bytes_processed': job.total_bytes_processed,
        'estimated_cost': job.total_bytes_processed / (1024**4) * 5.0,  # $5/TB
        'concerns': [
            'Large scan (>100GB)' if job.total_bytes_processed > 100*1024**3 else None,
            'Very expensive (>$1)' if job.total_bytes_processed > 200*1024**3 else None
        ]
    }
```

**Thresholds:**
- WARNING: Query processes > 10GB
- CRITICAL: Query processes > 100GB
- BLOCK: Query processes > 1TB (likely missing WHERE clause)

**Benefits:**
- Prevents expensive queries from reaching production
- Catches missing filters early
- Documents query costs

**Effort:** 3 hours
**Impact:** Saves BigQuery costs, prevents timeouts

---

### P1-6: Type Mismatch Detection
**Problem:** Assigning wrong types to fields (int to string, etc.) causes write failures
**Current State:** Schema validator checks field existence, not types

**Implementation:**
```python
# Enhance .pre-commit-hooks/validate_schema_fields.py

def check_type_mismatches(code_assignments, schema):
    """
    Detect type mismatches like:
    - 'some_int_field': "string value"  # Should be int
    - 'some_float_field': 123            # Should be float (but int is ok)
    - 'some_bool_field': 1               # Should be boolean
    """

    issues = []
    for field, value_pattern in code_assignments.items():
        schema_type = schema[field]['type']

        # Check for obvious mismatches
        if schema_type == 'INTEGER' and '"' in value_pattern:
            issues.append(f'{field}: INTEGER field assigned string')
        elif schema_type == 'BOOLEAN' and value_pattern not in ['True', 'False']:
            issues.append(f'{field}: BOOLEAN field assigned non-boolean')

    return issues
```

**Benefits:**
- Catches type errors before deployment
- Reduces BigQuery write failures

**Effort:** 2 hours
**Impact:** Prevents write failures

---

## Phase 5: Monitoring & Alerting (P1-P2)

### P1-7: Prediction Timing Dashboard
**Problem:** We can check timing with scripts, but no visual dashboard
**Current State:** P2-2 script shows timing lag for single date

**Implementation:**
Create Grafana dashboard or Cloud Monitoring dashboard showing:
- Daily prediction timing (line availability → first prediction)
- Lag trend over 30 days
- Alert if lag > 2 hours
- Breakdown by scheduler (early, overnight, same-day)

**Panels:**
1. **Timing Lag (hours)** - Line chart, last 30 days
2. **Scheduler Health** - Bar chart, runs per day
3. **Batch vs Individual** - Pie chart, prediction generation mode
4. **Alert Status** - Single stat, current lag

**Benefits:**
- Visual regression detection
- Historical trend analysis
- Proactive monitoring

**Effort:** 4 hours
**Impact:** Early detection of timing regressions

---

### P1-8: Validation Status Dashboard
**Problem:** No centralized view of validation check status
**Current State:** Run scripts individually, no aggregated view

**Implementation:**
Create dashboard showing:
- Pre-commit hook status (pass/fail/skip)
- Deployment validation status (8 services × 3 checks)
- Monitoring script results (thresholds, current values)
- Historical trends

**Data Source Options:**
1. **Firestore** - Store validation results in Firestore collection
2. **BigQuery** - Log validation runs to `nba_monitoring.validation_runs`
3. **Cloud Monitoring** - Custom metrics for each check

**Dashboard Sections:**
1. **Overview** - Total checks, pass rate, recent failures
2. **Pre-commit Hooks** - Status by hook, recent violations
3. **Deployment Checks** - Status by service, recent issues
4. **Monitoring Scripts** - Threshold health, calibrated values
5. **Historical Trends** - Pass rate over time, MTBF

**Benefits:**
- Single pane of glass for validation health
- Trend analysis
- Quick incident detection

**Effort:** 8 hours
**Impact:** Improved observability

---

### P2-3: Auto-Calibrating Thresholds
**Problem:** P1-4 calibrates thresholds manually, need to run monthly
**Current State:** One-time calibration, static thresholds

**Implementation:**
```python
# bin/monitoring/auto-calibrate-thresholds.py

def auto_calibrate_daily():
    """
    Run daily, update thresholds based on rolling 30-day window.

    For each metric:
    1. Query last 30 days
    2. Calculate percentiles
    3. Compare to current thresholds
    4. Update if drift > 20%
    5. Alert on threshold changes
    """

    for metric in MONITORED_METRICS:
        historical_data = query_metric_history(metric, days=30)
        new_thresholds = calculate_percentiles(historical_data)
        current_thresholds = load_current_thresholds(metric)

        if threshold_drift(new_thresholds, current_thresholds) > 0.20:
            alert_threshold_drift(metric, current_thresholds, new_thresholds)
            update_thresholds(metric, new_thresholds)
```

**Benefits:**
- Thresholds adapt to seasonal patterns
- Reduces false alarms automatically
- No manual monthly calibration needed

**Effort:** 4 hours
**Impact:** Reduces operational toil

---

### P2-4: Slack/Email Alerting Integration
**Problem:** Validation failures require manual checking
**Current State:** Checks run, but no automatic notifications

**Implementation:**
```python
# shared/alerting/validation_alerting.py

class ValidationAlerter:
    def alert_on_failure(self, check_name, severity, details):
        """
        Alert based on severity:
        - CRITICAL: Page (PagerDuty) + Slack
        - WARNING: Slack only
        - INFO: Log only
        """

        if severity == 'CRITICAL':
            self.send_pagerduty(check_name, details)
            self.send_slack('#alerts-critical', check_name, details)
        elif severity == 'WARNING':
            self.send_slack('#alerts-validation', check_name, details)

        self.log_to_bigquery(check_name, severity, details)
```

**Alert Channels:**
- **Slack #alerts-critical** - P0 failures (data loss, outages)
- **Slack #alerts-validation** - P1 failures (degradations)
- **Email digest** - Daily summary of all checks
- **PagerDuty** (optional) - Critical failures during business hours

**Benefits:**
- Proactive failure detection
- Faster incident response
- Historical alert tracking

**Effort:** 4 hours
**Impact:** Reduces MTTD (mean time to detect)

---

## Phase 6: Predictive & ML-Based (P2-P3)

### P2-5: Anomaly Detection for Metrics
**Problem:** Static thresholds miss subtle regressions
**Current State:** Threshold-based alerting only

**Implementation:**
Use ML to detect anomalies:
- Train on historical metric data (30-90 days)
- Detect outliers using Z-score or isolation forest
- Alert on statistically significant deviations
- Adapt to seasonality (weekday vs weekend patterns)

**Metrics to Monitor:**
- Prediction hit rate (detect model drift)
- Feature completeness (detect data quality issues)
- BigQuery write rates (detect pipeline slowdowns)
- Prediction timing lag (detect scheduler issues)

**Example:**
```python
from sklearn.ensemble import IsolationForest

def detect_anomalies(metric_history):
    """
    Use Isolation Forest to detect anomalies.
    Returns confidence score and anomaly flag.
    """

    model = IsolationForest(contamination=0.05)
    model.fit(metric_history.reshape(-1, 1))

    predictions = model.predict(metric_history[-1:])
    scores = model.score_samples(metric_history[-1:])

    return {
        'is_anomaly': predictions[0] == -1,
        'confidence': abs(scores[0]),
        'severity': 'CRITICAL' if abs(scores[0]) > 0.5 else 'WARNING'
    }
```

**Benefits:**
- Catches subtle regressions
- Reduces false alarms (ML learns normal variance)
- Adapts to seasonal patterns

**Effort:** 12 hours
**Impact:** Earlier detection of issues

---

### P3-1: Data Freshness Monitoring
**Problem:** No validation that scrapers are running on schedule
**Current State:** Manual checking if data seems stale

**Implementation:**
```python
# bin/monitoring/check-data-freshness.sh

def check_freshness(table, expected_delay_hours):
    """
    Check if table has recent data.

    For each table:
    1. Find most recent processed_at or created_at
    2. Compare to current time
    3. Alert if data is stale (> expected_delay)
    """

    query = f"""
    SELECT
      MAX(processed_at) as latest_data,
      TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_stale
    FROM `{table}`
    """

    result = run_query(query)

    if result['hours_stale'] > expected_delay_hours:
        alert(f'{table} is {result["hours_stale"]}h stale (expected <{expected_delay_hours}h)')
```

**Tables to Monitor:**
- `nba_raw.*` - Expect data within 2 hours
- `nba_analytics.*` - Expect data within 4 hours
- `nba_predictions.*` - Expect data daily by 6 AM

**Benefits:**
- Detect scraper failures quickly
- Ensure data pipeline health
- Proactive alerting

**Effort:** 3 hours
**Impact:** Faster detection of pipeline issues

---

### P3-2: Model Drift Detection
**Problem:** ML model performance can degrade over time
**Current State:** Manual analysis of hit rates

**Implementation:**
```python
# bin/monitoring/detect-model-drift.py

def detect_drift():
    """
    Compare recent performance to baseline:
    - Hit rate (last 7 days vs last 30 days)
    - MAE drift (recent vs expected)
    - Edge accuracy (5+ edge predictions)
    """

    recent = query_performance(days=7)
    baseline = query_performance(days=30)

    hit_rate_drop = baseline['hit_rate'] - recent['hit_rate']
    mae_increase = recent['mae'] - baseline['mae']

    if hit_rate_drop > 5.0:  # 5% drop
        alert('Model drift detected: Hit rate dropped 5%')

    if mae_increase > 1.0:  # 1 point increase
        alert('Model drift detected: MAE increased by 1 point')
```

**Metrics:**
- **Hit rate drift** - Alert if drops >5% from baseline
- **MAE drift** - Alert if increases >1 point from baseline
- **Edge accuracy drift** - Alert if 5+ edge drops >10%
- **Signal distribution** - Alert if RED signal >70% of days

**Benefits:**
- Early detection of model degradation
- Triggers retraining workflow
- Maintains prediction quality

**Effort:** 6 hours
**Impact:** Protects model quality

---

### P3-3: Cost Anomaly Detection
**Problem:** BigQuery costs can spike unexpectedly
**Current State:** Monthly billing review only

**Implementation:**
Monitor BigQuery costs daily:
- Track bytes processed per table per day
- Alert on >50% increase from baseline
- Identify expensive queries (>$1 per run)
- Track cost trends over time

**Dashboard:**
- Daily BigQuery costs (line chart)
- Top 10 expensive queries (table)
- Cost by dataset (pie chart)
- Anomaly alerts (recent spikes)

**Benefits:**
- Prevent surprise bills
- Identify optimization opportunities
- Budget forecasting

**Effort:** 4 hours
**Impact:** Cost control

---

## Phase 7: CI/CD Integration (P1-P2)

### P1-9: GitHub Actions Integration
**Problem:** Pre-commit hooks run locally, can be bypassed
**Current State:** Hooks run on developer machine only

**Implementation:**
```yaml
# .github/workflows/validation.yml

name: Validation Checks

on:
  pull_request:
    branches: [main]

jobs:
  schema-validation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Schema alignment check
        run: python .pre-commit-hooks/validate_schema_fields.py

      - name: Partition filter check
        run: python .pre-commit-hooks/validate_partition_filters.py

      - name: Comment results on PR
        uses: actions/github-script@v6
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              body: '✅ All validation checks passed!'
            })
```

**Checks to Run:**
- Schema alignment
- Partition filters
- Query performance estimation
- Type mismatch detection

**Benefits:**
- Enforced validation (can't bypass)
- Visible in PR reviews
- Automated feedback

**Effort:** 4 hours
**Impact:** Enforcement of validation rules

---

### P2-6: Automated Issue Creation
**Problem:** Validation failures require manual follow-up
**Current State:** Alerts fire, but no tracking

**Implementation:**
```python
# shared/alerting/issue_creator.py

def create_github_issue_on_failure(check_name, details):
    """
    Auto-create GitHub issue for validation failures.

    - Title: "[Validation] {check_name} failed"
    - Labels: validation, priority based on severity
    - Assignee: Team rotation or last committer
    - Body: Failure details, affected files, remediation steps
    """

    from github import Github

    g = Github(os.getenv('GITHUB_TOKEN'))
    repo = g.get_repo('owner/nba-stats-scraper')

    issue = repo.create_issue(
        title=f'[Validation] {check_name} failed',
        body=format_issue_body(details),
        labels=['validation', severity_to_label(details['severity'])]
    )

    return issue.number
```

**Benefits:**
- Automatic tracking
- No failures slip through
- Historical failure record

**Effort:** 3 hours
**Impact:** Improved accountability

---

## Phase 8: Auto-Remediation (P2-P3)

### P2-7: Self-Healing Deployment Rollback
**Problem:** Bad deployments require manual rollback
**Current State:** Human detects issue, runs manual rollback

**Implementation:**
```python
# bin/monitoring/auto-rollback.py

def monitor_post_deployment(service, revision):
    """
    Monitor new deployment for 10 minutes.

    If critical checks fail:
    1. Alert team
    2. Auto-rollback to previous revision
    3. Create incident report
    """

    time.sleep(60)  # Wait 1 min for warmup

    for i in range(10):
        health = check_deployment_health(service, revision)

        if health['bigquery_writes'] == 0:
            alert('Zero BigQuery writes detected!')
            rollback(service, revision)
            return

        if health['error_rate'] > 0.5:  # >50% errors
            alert('High error rate detected!')
            rollback(service, revision)
            return

        time.sleep(60)

    alert('Deployment validated successfully')
```

**Rollback Triggers:**
- Zero BigQuery writes for 5 minutes
- Error rate >50% for 2 minutes
- Missing environment variables
- Service identity mismatch

**Benefits:**
- Automatic recovery from bad deployments
- Reduces MTTR (mean time to recovery)
- No manual intervention needed

**Effort:** 6 hours
**Impact:** Faster incident recovery

---

### P3-4: Intelligent Retry with Backoff
**Problem:** Transient failures trigger excessive retries
**Current State:** Fixed retry count, no adaptive logic

**Implementation:**
```python
def retry_with_adaptive_backoff(func, context):
    """
    Retry with intelligent backoff:
    - Exponential backoff (1s, 2s, 4s, 8s, 16s)
    - Circuit breaker (stop after 5 failures in 10 min)
    - Jitter (randomize to avoid thundering herd)
    - Context-aware (different strategies per error type)
    """

    max_attempts = 5
    base_delay = 1.0

    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            if not is_retryable(e):
                raise

            if circuit_breaker.is_open(context):
                raise CircuitBreakerOpen()

            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            time.sleep(delay)
            circuit_breaker.record_failure(context)

    raise MaxRetriesExceeded()
```

**Benefits:**
- Reduces unnecessary retries
- Prevents cascading failures
- Faster recovery from transients

**Effort:** 4 hours
**Impact:** Better reliability

---

## Implementation Roadmap

### Quarter 1 (Next 3 Months)
**Focus:** Immediate value, high ROI

| Week | Tasks | Effort |
|------|-------|--------|
| 1-2 | P1-7: Prediction Timing Dashboard | 4h |
| 3-4 | P1-8: Validation Status Dashboard | 8h |
| 5-6 | P2-4: Slack Alerting Integration | 4h |
| 7-8 | P1-9: GitHub Actions Integration | 4h |
| 9-10 | P3-1: Data Freshness Monitoring | 3h |
| 11-12 | P2-6: Automated Issue Creation | 3h |

**Total:** 26 hours over 12 weeks

---

### Quarter 2 (Months 4-6)
**Focus:** Advanced monitoring, predictive analytics

| Week | Tasks | Effort |
|------|-------|--------|
| 13-15 | P2-3: Auto-Calibrating Thresholds | 4h |
| 16-18 | P0-4: Schema Evolution Tracking | 4h |
| 19-21 | P1-5: Query Performance Validation | 3h |
| 22-24 | P3-2: Model Drift Detection | 6h |

**Total:** 17 hours over 12 weeks

---

### Quarter 3 (Months 7-9)
**Focus:** ML-based detection, auto-remediation

| Week | Tasks | Effort |
|------|-------|--------|
| 25-28 | P2-5: Anomaly Detection | 12h |
| 29-32 | P2-7: Self-Healing Rollback | 6h |
| 33-36 | P1-6: Type Mismatch Detection | 2h |

**Total:** 20 hours over 12 weeks

---

### Quarter 4 (Months 10-12)
**Focus:** Cost optimization, polish

| Week | Tasks | Effort |
|------|-------|--------|
| 37-40 | P3-3: Cost Anomaly Detection | 4h |
| 41-44 | P3-4: Intelligent Retry Logic | 4h |
| 45-48 | Documentation, refinement | 4h |

**Total:** 12 hours over 12 weeks

---

## Success Metrics

### Quantitative
- **MTBF** (Mean Time Between Failures): Target +50%
- **MTTD** (Mean Time To Detect): Target -75% (from hours to minutes)
- **MTTR** (Mean Time To Recover): Target -50% (auto-remediation)
- **False Alarm Rate**: Target <5% (down from ~30%)
- **Validation Coverage**: 100% of critical paths
- **BigQuery Cost**: No surprise bills, <10% month-over-month variance

### Qualitative
- Developers trust validation checks (no bypassing)
- Incidents detected proactively (not by users)
- Less time spent debugging production issues
- More time spent building features
- Confidence in deployment process

---

## Resources & Dependencies

### Infrastructure
- **Grafana/Cloud Monitoring** - Dashboards ($0-200/month)
- **BigQuery** - Query validation ($10-50/month)
- **Cloud Functions** - Automated checks ($5-20/month)
- **Firestore** - Validation state storage ($5-10/month)

**Total:** ~$20-280/month depending on scale

### External Services (Optional)
- **PagerDuty** - Critical alerting ($30-100/user/month)
- **Slack** - Already have (free/existing)
- **GitHub Actions** - Included in GitHub plan

### Time Investment
- **Q1:** 26 hours (immediate value)
- **Q2:** 17 hours (advanced features)
- **Q3:** 20 hours (ML-based)
- **Q4:** 12 hours (polish)

**Total:** 75 hours over 12 months (~1.5 hours/week)

---

## Risk Assessment

### Low Risk (Do First)
- Dashboards (read-only, no impact if broken)
- Alerting (additive, can disable if noisy)
- Monitoring scripts (run separately, no blocking)

### Medium Risk (Test Thoroughly)
- Pre-commit hooks (can block commits if buggy)
- Threshold calibration (wrong thresholds = false alarms)
- GitHub Actions (can block PRs)

### High Risk (Careful Implementation)
- Auto-rollback (could rollback good deployments)
- Schema evolution enforcement (could block legitimate changes)
- Circuit breakers (could stop valid retries)

---

## Getting Started

### This Week (Immediate)
1. Set up basic validation dashboard (use existing scripts output)
2. Schedule P1-4 calibration script to run monthly
3. Integrate P2-2 timing monitor into `/validate-daily`
4. Fix Feb 2 timing regression (if not self-resolved)

### Next Month
1. Implement P1-7: Prediction Timing Dashboard
2. Implement P2-4: Slack alerting for critical failures
3. Document validation runbooks

### This Quarter
Follow Q1 roadmap (26 hours, high ROI items)

---

## Conclusion

The validation improvements project (Session 81-89) built a solid foundation:
- 11 validation checks implemented
- 8 bug classes prevented
- 8 services protected

These future enhancements will take validation to the next level:
- **Proactive** instead of reactive (anomaly detection)
- **Automated** instead of manual (auto-remediation)
- **Visible** instead of hidden (dashboards)
- **Predictive** instead of threshold-based (ML detection)

**Estimated ROI:**
- 75 hours investment over 12 months
- Prevents ~10 major incidents per year (conservatively)
- Saves ~100 hours of debugging time per year
- **Net savings: 25 hours per year + improved reliability**

**Next Step:** Review with team, prioritize Q1 tasks, schedule implementation.

---

**Status:** Ready for review
**Owner:** TBD
**Timeline:** 12 months (75 hours total)
**ROI:** High (prevents incidents, saves time, improves reliability)
