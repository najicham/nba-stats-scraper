# Systemic Analysis: Why These Failures Happened & How to Prevent Them

**Date**: 2026-01-20
**Author**: Root Cause Analysis Session
**Status**: 🎯 COMPREHENSIVE - Ready for Implementation

---

## Executive Summary

This document analyzes **WHY** the Week 0 incidents happened from a systemic perspective, not just the technical root causes. It reveals patterns of failure and proposes a comprehensive robustness plan.

**Key Insight**: All 4 incidents share a common pattern: **"Deploy and Forget"** — infrastructure deployed without validation, monitoring, or operational rigor.

---

## 🔍 Systemic Failure Pattern Analysis

### Pattern 1: Deployment Without Verification

**Manifestation**:
- Grading readiness monitor deployed with bug (wrong table name)
- Cloud Schedulers never created despite documentation existing
- BigQuery Data Transfer API not enabled despite being required
- Phase 4 processors failed silently without detection

**Root Systemic Cause**: **No Deployment Checklist**

**Why This Happened**:
1. **Manual Deployment Process**: Steps executed ad-hoc without systematic verification
2. **No Post-Deployment Testing**: Deployed code assumed to work
3. **No Automated Validation**: No CI/CD checks for infrastructure completeness
4. **Documentation vs Reality Gap**: Docs describe what *should* exist, not what *does* exist

**Impact Score**: **CRITICAL** - Led to 3 of 4 incidents

---

### Pattern 2: Silent Failures (No Observability)

**Manifestation**:
- Grading didn't run for 3 days, no one noticed
- Phase 4 processors failed on Jan 16/18, discovered days later
- Box scores missing (11-33% gaps), no alerts
- Prediction gaps appeared, no monitoring flagged change

**Root Systemic Cause**: **Monitoring Gap - "Happy Path Only"**

**Why This Happened**:
1. **Positive Monitoring Only**: Alerts for success, not absence of success
2. **No SLA Thresholds**: No defined "by when" for critical milestones
3. **No Completeness Checks**: Volume monitoring missing
4. **Alert Fatigue Prevention Overdone**: Fear of noise led to insufficient alerting

**Impact Score**: **CRITICAL** - Led to delayed discovery of all 4 incidents

---

### Pattern 3: No Retry/Recovery Mechanisms

**Manifestation**:
- BDL scraper fails once, never retries → 17 missing box scores
- Phase 4 processors fail, no automatic retry
- Grading doesn't trigger, no backup mechanism
- Single points of failure throughout pipeline

**Root Systemic Cause**: **Brittle Design - "One Shot" Architecture**

**Why This Happened**:
1. **Optimistic Design**: Assumed everything works first time
2. **No Circuit Breakers**: Failures propagate without detection
3. **Manual Recovery Only**: Human intervention required for every failure
4. **No Exponential Backoff**: Network/API transient failures become permanent

**Impact Score**: **HIGH** - Led to 2 of 4 incidents becoming persistent

---

### Pattern 4: Insufficient Pre-flight Validation

**Manifestation**:
- Phase 4 ran without checking Phase 3 completeness
- Grading attempted without checking actuals exist
- Predictions generated without validating feature availability
- Cascading failures due to missing upstream dependencies

**Root Systemic Cause**: **Trust, Don't Verify**

**Why This Happened**:
1. **Performance Over Reliability**: Validation seen as overhead
2. **Tight Coupling**: Phases assume predecessors completed successfully
3. **No Quality Gates**: Phases trigger on existence, not quality
4. **Optimistic Scheduling**: Time-based triggers ignore dependency state

**Impact Score**: **MEDIUM** - Amplified impact of other failures

---

### Pattern 5: Configuration as Code Missing

**Manifestation**:
- Cloud Schedulers not defined in code/Terraform
- API enablements not tracked
- Environment variables scattered
- Infrastructure drift undetected

**Root Systemic Cause**: **Manual Infrastructure Management**

**Why This Happened**:
1. **Console Clicking**: GCP resources created via UI
2. **No Version Control**: Infrastructure changes not tracked
3. **No Drift Detection**: Can't compare expected vs actual
4. **Knowledge in Heads**: "I thought I deployed that..."

**Impact Score**: **HIGH** - Made incidents harder to diagnose

---

## 🎯 Comprehensive Robustness Plan

### Phase 1: Immediate Fixes (This Session - 4 hours)

**Objective**: Stop the bleeding, prevent immediate recurrence

#### 1.1 Add Retry Mechanisms (HIGH PRIORITY)

**Box Score Scraper Retry**:
```python
# NEW FILE: scrapers/balldontlie/bdl_retry_wrapper.py

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
import logging

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=60, max=1800),  # 1 min → 30 min
    retry=retry_if_exception_type((ConnectionError, TimeoutError, requests.HTTPError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def fetch_with_retry(scraper_instance, **kwargs):
    """
    Retry wrapper for scraper execution.

    Retry Strategy:
    - Attempt 1: Immediate
    - Attempt 2: Wait 1 minute
    - Attempt 3: Wait 2 minutes
    - Attempt 4: Wait 4 minutes
    - Attempt 5: Wait 8 minutes (final)

    Total retry window: ~15 minutes

    After all retries fail, alert and raise.
    """
    return scraper_instance.run(**kwargs)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=5, min=300, max=3600),  # 5 min → 1 hour
    retry=retry_if_result(lambda result: result['scraped'] < result['expected'] * 0.8),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def validate_completeness_with_retry(check_func, game_date):
    """
    Retry wrapper for completeness validation.

    Retries if coverage < 80% threshold.
    Useful for delayed data availability.
    """
    return check_func(game_date)
```

**Phase 4 Processor Retry**:
```python
# MODIFY: orchestration/cloud_functions/phase3_to_phase4/main.py

def trigger_phase4_with_retry(game_date: str, max_retries: int = 3):
    """
    Trigger Phase 4 with automatic retry for failed processors.

    Strategy:
    1. Trigger all processors
    2. Wait for completion (timeout: 30 min)
    3. Check which failed
    4. Retry failed processors (up to 3 times each)
    5. Alert if still failing after retries
    """
    for attempt in range(max_retries):
        result = trigger_phase4(game_date)
        failed = check_failed_processors(game_date)

        if not failed:
            return result

        if attempt < max_retries - 1:
            logger.warning(f"Phase 4 attempt {attempt + 1} had failures: {failed}. Retrying...")
            time.sleep(300)  # Wait 5 min before retry
            retry_specific_processors(game_date, failed)
        else:
            send_slack_alert(
                channel='#app-error-alerts',
                message=f"⚠️ Phase 4 failed after {max_retries} attempts for {game_date}: {failed}"
            )
            raise Phase4FailureError(f"Processors failed: {failed}")
```

#### 1.2 Add Critical Missing Alerts (HIGH PRIORITY)

**New Alert Functions**:

1. **`box_score_completeness_alert`** (Priority 1)
   - Checks: Box score coverage vs scheduled games
   - Triggers:
     - CRITICAL: <50% after 24 hours
     - WARNING: <90% after 12 hours
     - INFO: <100% after 6 hours
   - Schedule: Every 6 hours

2. **`phase4_failure_alert`** (Priority 1)
   - Checks: Phase 4 processor completion
   - Triggers:
     - CRITICAL: <3/5 processors succeeded
     - WARNING: Any processor failed
   - Schedule: 2 hours after Phase 3 completion

3. **`daily_data_quality_report`** (Priority 1)
   - Checks: All pipeline layers for yesterday
   - Reports:
     - Phase 2 completeness (scrapers)
     - Phase 3 completeness (analytics)
     - Phase 4 completeness (precompute)
     - Phase 5 completeness (predictions)
     - Phase 6 completeness (grading)
   - Schedule: 8 AM ET daily (after grading should complete)

4. **`grading_coverage_alert`** (Priority 1) - ENHANCE EXISTING
   - Current: Only checks if grading ran
   - Add: Coverage percentage check
   - Add: Timeliness check (by 3 PM ET next day)

#### 1.3 Add Pre-flight Validation Gates (HIGH PRIORITY)

**Phase 3 → Phase 4 Gate**:
```python
# MODIFY: orchestration/cloud_functions/phase3_to_phase4/main.py

def validate_phase3_before_phase4(game_date: str):
    """
    Pre-flight checks before triggering Phase 4.

    Requirements:
    - player_game_summary: >0 records
    - team_defense_game_summary: >0 records
    - upcoming_player_game_context: >0 records
    - Coverage: ≥80% of scheduled games

    If any check fails, block Phase 4 and alert.
    """
    checks = {
        'player_game_summary': check_table_count(game_date, 'player_game_summary'),
        'team_defense': check_table_count(game_date, 'team_defense_game_summary'),
        'upcoming_context': check_table_count(game_date, 'upcoming_player_game_context')
    }

    scheduled_games = get_scheduled_game_count(game_date)
    expected_players = scheduled_games * 13  # ~13 players per game

    # Validation
    failures = []
    for table, count in checks.items():
        if count == 0:
            failures.append(f"{table}: 0 records")
        elif count < expected_players * 0.8:
            failures.append(f"{table}: {count} records (<80% of expected {expected_players})")

    if failures:
        send_slack_alert(
            channel='#app-error-alerts',
            message=f"🚫 Phase 4 blocked for {game_date} - Phase 3 incomplete:\n" + "\n".join(failures)
        )
        raise ValidationError(f"Phase 3 validation failed: {failures}")

    logger.info(f"✅ Phase 3 validation passed for {game_date}")
    return True
```

**Phase 4 → Phase 5 Circuit Breaker**:
```python
# MODIFY: orchestration/cloud_functions/phase4_to_phase5/main.py

def check_phase4_minimum_coverage(game_date: str):
    """
    Circuit breaker: Require minimum Phase 4 coverage before predictions.

    Requirement: At least 3/5 Phase 4 processors must complete.

    Critical processors (at least 2 required):
    - PlayerDailyCache (PDC)
    - MLFeatureStoreV2 (MLFS)

    If requirements not met, block Phase 5 and alert.
    """
    processors = {
        'PDC': {'critical': True, 'count': check_processor_count(game_date, 'player_daily_cache')},
        'PSZA': {'critical': False, 'count': check_processor_count(game_date, 'player_shot_zone_analysis')},
        'PCF': {'critical': False, 'count': check_processor_count(game_date, 'player_composite_factors')},
        'MLFS': {'critical': True, 'count': check_processor_count(game_date, 'ml_feature_store')},
        'TDZA': {'critical': False, 'count': check_processor_count(game_date, 'team_defense_zone_analysis')}
    }

    completed = sum(1 for p in processors.values() if p['count'] > 0)
    critical_completed = sum(1 for p in processors.values() if p['critical'] and p['count'] > 0)

    # Requirements
    if completed < 3:
        failures = [f"{name}: {info['count']}" for name, info in processors.items() if info['count'] == 0]
        send_slack_alert(
            channel='#app-error-alerts',
            message=f"🚫 Phase 5 blocked for {game_date} - Only {completed}/5 Phase 4 processors completed:\n" +
                   "\n".join(failures)
        )
        raise InsufficientDataError(f"Phase 4 coverage too low: {completed}/5")

    if critical_completed < 2:
        send_slack_alert(
            channel='#app-error-alerts',
            message=f"🚫 Phase 5 blocked for {game_date} - Critical Phase 4 processors missing"
        )
        raise InsufficientDataError("Critical Phase 4 processors incomplete")

    logger.info(f"✅ Phase 4 circuit breaker passed: {completed}/5 processors, {critical_completed}/2 critical")
    return True
```

---

### Phase 2: Short-term Hardening (Next 2 Weeks)

**Objective**: Build operational rigor and monitoring

#### 2.1 Deployment Checklist Enforcement

**Action Items**:
1. ✅ Convert deployment checklist to executable script
2. ✅ Add to CI/CD pipeline
3. ✅ Require signoff before marking deployment complete
4. ✅ Automated verification of all infrastructure

**Implementation**:
```bash
# NEW FILE: bin/verify_deployment.sh

#!/bin/bash
# Deployment Verification Script
# Run after every deployment to ensure completeness

set -e

echo "=== NBA Pipeline Deployment Verification ==="
echo ""

# 1. Cloud Schedulers
echo "1. Checking Cloud Schedulers..."
EXPECTED_SCHEDULERS=("grading-daily-6am" "grading-daily-10am-backup" "grading-readiness-monitor-schedule")
for scheduler in "${EXPECTED_SCHEDULERS[@]}"; do
    if gcloud scheduler jobs describe "$scheduler" --location=us-central1 &>/dev/null; then
        echo "  ✅ $scheduler exists"
    else
        echo "  ❌ $scheduler MISSING"
        exit 1
    fi
done

# 2. APIs Enabled
echo "2. Checking Required APIs..."
REQUIRED_APIS=("bigquery.googleapis.com" "bigquerydatatransfer.googleapis.com" "run.googleapis.com")
for api in "${REQUIRED_APIS[@]}"; do
    if gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        echo "  ✅ $api enabled"
    else
        echo "  ❌ $api NOT ENABLED"
        exit 1
    fi
done

# 3. Cloud Functions
echo "3. Checking Critical Cloud Functions..."
REQUIRED_FUNCTIONS=("phase5b-grading" "grading-readiness-monitor" "grading-delay-alert")
for func in "${REQUIRED_FUNCTIONS[@]}"; do
    if gcloud functions describe "$func" --region=us-west1 &>/dev/null; then
        echo "  ✅ $func deployed"
    else
        echo "  ❌ $func NOT DEPLOYED"
        exit 1
    fi
done

# 4. BigQuery Tables
echo "4. Checking Critical BigQuery Tables..."
REQUIRED_TABLES=("player_prop_predictions" "prediction_grades" "system_daily_performance")
for table in "${REQUIRED_TABLES[@]}"; do
    if bq show "nba-props-platform:nba_predictions.$table" &>/dev/null; then
        echo "  ✅ $table exists"
    else
        echo "  ❌ $table MISSING"
        exit 1
    fi
done

echo ""
echo "✅ ALL CHECKS PASSED - Deployment verified!"
```

#### 2.2 Monitoring Dashboard

**Create Cloud Monitoring Dashboard**:

Metrics to Track:
1. **Pipeline Health** (5-minute resolution)
   - Phase 2 completion %
   - Phase 3 completion %
   - Phase 4 completion %
   - Phase 5 prediction count
   - Phase 6 grading coverage %

2. **SLA Tracking**
   - Grading completed by 3 PM ET? (✅/❌)
   - Predictions ready by 12 PM ET? (✅/❌)
   - Phase 4 success rate (≥60% = ✅)
   - Box score coverage (≥90% = ✅)

3. **Error Rates**
   - Scraper failures (count per day)
   - Processor failures (count per day)
   - Grading failures (count per day)
   - Alert frequency (count per day)

#### 2.3 Weekly Validation Reports

**Automated Report**:
- Sent every Monday 9 AM ET
- Summarizes past 7 days
- Highlights:
  - Days with perfect execution (all SLAs met)
  - Days with partial failures
  - Recurring failure patterns
  - Performance trends

---

### Phase 3: Long-term Resilience (Next Month)

**Objective**: Infrastructure as Code + Self-Healing

#### 3.1 Infrastructure as Code (Terraform)

**Convert all GCP resources to Terraform**:

```hcl
# NEW FILE: terraform/schedulers.tf

# Grading Schedulers
resource "google_cloud_scheduler_job" "grading_daily_primary" {
  name             = "grading-daily-6am"
  description      = "Trigger NBA grading daily at 6 AM PT (primary)"
  schedule         = "0 6 * * *"
  time_zone        = "America/Los_Angeles"
  attempt_deadline = "180s"
  region           = "us-central1"

  pubsub_target {
    topic_name = google_pubsub_topic.grading_trigger.id
    data       = base64encode(jsonencode({
      target_date      = "yesterday"
      run_aggregation  = true
      trigger_source   = "cloud-scheduler-primary"
    }))
  }
}

resource "google_cloud_scheduler_job" "grading_daily_backup" {
  name             = "grading-daily-10am-backup"
  description      = "Backup NBA grading trigger at 10 AM PT (secondary)"
  schedule         = "0 10 * * *"
  time_zone        = "America/Los_Angeles"
  attempt_deadline = "180s"
  region           = "us-central1"

  pubsub_target {
    topic_name = google_pubsub_topic.grading_trigger.id
    data       = base64encode(jsonencode({
      target_date      = "yesterday"
      run_aggregation  = true
      trigger_source   = "cloud-scheduler-backup"
    }))
  }
}

# Alerting Schedulers
resource "google_cloud_scheduler_job" "box_score_alert" {
  name             = "box-score-completeness-alert"
  description      = "Check box score completeness every 6 hours"
  schedule         = "0 */6 * * *"
  time_zone        = "America/New_York"
  attempt_deadline = "180s"
  region           = "us-central1"

  http_target {
    uri         = google_cloudfunctions2_function.box_score_alert.service_config[0].uri
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
}
```

**Benefits**:
- Version controlled
- Repeatable deployments
- Drift detection
- Documentation that matches reality

#### 3.2 Self-Healing Mechanisms

**Auto-Recovery Workflows**:

```python
# NEW FILE: orchestration/cloud_functions/auto_recovery/main.py

"""
Auto-Recovery Orchestrator

Monitors for failures and automatically triggers recovery actions:
1. Retry failed scrapers
2. Backfill missing data
3. Re-run failed processors
4. Trigger manual override if all retries fail

Schedule: Every 30 minutes
"""

@functions_framework.http
def auto_recovery_check(request):
    """Check for failures and auto-recover."""
    yesterday = get_yesterday_date()

    # Check 1: Box Score Completeness
    box_score_coverage = check_box_score_coverage(yesterday)
    if box_score_coverage < 0.90:
        logger.warning(f"Box score coverage low: {box_score_coverage:.1%}. Triggering retry...")
        retry_box_score_scraper(yesterday)

    # Check 2: Phase 4 Completeness
    phase4_coverage = check_phase4_coverage(yesterday)
    if phase4_coverage < 0.60:
        logger.warning(f"Phase 4 coverage low: {phase4_coverage:.1%}. Triggering backfill...")
        trigger_phase4_backfill(yesterday)

    # Check 3: Grading Coverage
    grading_coverage = check_grading_coverage(yesterday)
    if grading_coverage < 0.90 and is_after_cutoff_time():
        logger.warning(f"Grading coverage low: {grading_coverage:.1%}. Triggering grading...")
        trigger_grading(yesterday)

    return {'status': 'recovery checks complete'}
```

#### 3.3 Predictive Alerting

**Trend Analysis for Early Warning**:

```python
# NEW FILE: orchestration/cloud_functions/predictive_alerts/main.py

"""
Predictive Alerting

Analyzes trends to predict failures before they happen:
- Increasing error rates
- Degrading performance metrics
- Resource utilization approaching limits
- API rate limit approaching

Sends early-warning alerts before SLA violations occur.
"""

def analyze_error_trend(days=7):
    """Alert if error rate increasing over past week."""
    error_counts = get_daily_error_counts(days)

    # Linear regression to detect trend
    trend = calculate_linear_trend(error_counts)

    if trend > 0.10:  # 10% increase per day
        send_slack_alert(
            channel='#nba-alerts',
            message=f"📈 Error rate increasing: +{trend*100:.1f}% per day over past {days} days. " +
                   f"Current: {error_counts[-1]} errors/day"
        )
```

---

## 📊 Robustness Metrics

**Define Success Metrics**:

### Tier 1: Reliability (Must Have)
- **Grading SLA**: ≥95% of days graded by 3 PM ET next day
- **Prediction SLA**: ≥95% of days predicted by 12 PM ET
- **Phase 4 Success Rate**: ≥80% of dates have ≥3/5 processors complete
- **Box Score Coverage**: ≥90% coverage within 24 hours

### Tier 2: Quality (Should Have)
- **Alert Response Time**: Median time from alert to resolution <2 hours
- **False Positive Rate**: <10% of alerts are false positives
- **Automated Recovery**: ≥50% of failures self-recover without human intervention

### Tier 3: Operational Excellence (Nice to Have)
- **Zero-Touch Days**: ≥80% of days require no manual intervention
- **Mean Time to Detect (MTTD)**: <30 minutes
- **Mean Time to Resolve (MTTR)**: <2 hours

---

## 🎯 Implementation Priority Matrix

| Priority | Item | Effort | Impact | Status |
|----------|------|--------|--------|--------|
| P0 | Add retry to BDL scraper | 1 hour | HIGH | ⏳ This session |
| P0 | Add Phase 4 failure alert | 30 min | HIGH | ⏳ This session |
| P0 | Add daily data quality report | 1 hour | HIGH | ⏳ This session |
| P0 | Add Phase 3→4 validation gate | 45 min | HIGH | ⏳ This session |
| P0 | Add Phase 4→5 circuit breaker | 30 min | MEDIUM | ⏳ This session |
| P1 | Deployment verification script | 30 min | HIGH | ⏳ This session |
| P1 | Box score completeness alert | 30 min | MEDIUM | ⏳ This session |
| P1 | Enhance grading coverage alert | 20 min | MEDIUM | ⏳ This session |
| P2 | Create monitoring dashboard | 2 hours | HIGH | Next week |
| P2 | Weekly validation reports | 1 hour | MEDIUM | Next week |
| P2 | Convert to Terraform (IaC) | 4 hours | HIGH | Next week |
| P3 | Auto-recovery orchestrator | 3 hours | MEDIUM | Next 2 weeks |
| P3 | Predictive alerting | 2 hours | LOW | Next month |

**This Session Focus**: Complete all P0 and P1 items (6 hours estimated)

---

## 🔑 Key Lessons for Future

### 1. **Deploy with Eyes Open**
- ✅ Never deploy without immediate verification
- ✅ Test in production after deployment
- ✅ Assume nothing works until proven

### 2. **Alert on Absence, Not Just Presence**
- ✅ "Grading completed" is not enough → need "grading DIDN'T complete"
- ✅ Monitor negative space (what should exist but doesn't)
- ✅ SLA-based alerting (time-bound expectations)

### 3. **Fail Gracefully, Recover Automatically**
- ✅ Every external call needs retry logic
- ✅ Every pipeline stage needs recovery mechanism
- ✅ Human intervention should be exception, not rule

### 4. **Validate Before Proceeding**
- ✅ Pre-flight checks before expensive operations
- ✅ Circuit breakers to prevent cascading failures
- ✅ Quality gates, not just existence gates

### 5. **Infrastructure as Code is Not Optional**
- ✅ If it's not in code, it doesn't exist (as far as automation knows)
- ✅ Manual changes = Untracked changes = Future incidents
- ✅ Version control everything, including infrastructure

---

## 📁 Related Documents

- [INCIDENT-REPORT-JAN-13-19-2026.md](./INCIDENT-REPORT-JAN-13-19-2026.md) - Technical root causes
- [DEPLOYMENT-CHECKLIST.md](../../02-operations/DEPLOYMENT-CHECKLIST.md) - Deployment procedures
- [HISTORICAL-DATA-VALIDATION-AND-BACKFILL-STRATEGY.md](./HISTORICAL-DATA-VALIDATION-AND-BACKFILL-STRATEGY.md) - Validation procedures

---

## 📝 Document Status

**Created**: 2026-01-20
**Status**: ✅ COMPREHENSIVE
**Next Review**: After P0/P1 implementation complete

---

**END OF SYSTEMIC ANALYSIS**
