# Additional Recommendations - Validation & Resilience Improvements (V2)

**Created:** 2026-01-25
**Purpose:** Additional improvements identified during comprehensive review
**Complements:** MASTER-IMPROVEMENT-PLAN.md, ADDITIONAL-IMPROVEMENTS-ADDENDUM.md, FINAL-COMPREHENSIVE-HANDOFF.md

---

## Overview

This document contains additional recommendations discovered after thorough review of the existing improvement plans. These items fall into several categories:

1. **Operational Gaps** - Missing alerting, rollback procedures, runbooks
2. **Reliability Improvements** - Circuit breakers, health checks, concurrency handling
3. **Edge Case Handling** - Seasonal variations, timezone issues, data corrections
4. **Observability Enhancements** - Structured logging, cost monitoring, SLOs
5. **Recovery Procedures** - Dependency ordering, partial recovery

---

## 1. Operational Gaps

### 1.1 Alerting Implementation

**Priority:** P1 (High)
**Effort:** Medium
**Status:** Validators exist but alerting not implemented

**The Gap:**

Validators produce results but there's no implementation showing how alerts reach operators. The master plan mentions `notification_channels` but doesn't show implementation.

**Recommendation:**

```python
# shared/utils/alerting.py
"""Centralized alerting for validation framework."""

import os
import requests
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class Alert:
    title: str
    message: str
    severity: AlertSeverity
    source: str  # validator name
    affected_date: Optional[str] = None
    affected_items: Optional[List[str]] = None
    remediation: Optional[List[str]] = None

class AlertDispatcher:
    """Dispatch alerts to appropriate channels based on severity."""

    SLACK_WEBHOOKS = {
        "critical": os.environ.get("SLACK_WEBHOOK_CRITICAL"),
        "error": os.environ.get("SLACK_WEBHOOK_ALERTS"),
        "warning": os.environ.get("SLACK_WEBHOOK_PIPELINE_HEALTH"),
        "info": None,  # Don't alert on info
    }

    PAGERDUTY_KEY = os.environ.get("PAGERDUTY_INTEGRATION_KEY")

    def dispatch(self, alert: Alert):
        """Route alert to appropriate channels."""

        # Critical: PagerDuty + Slack
        if alert.severity == AlertSeverity.CRITICAL:
            self._send_pagerduty(alert)
            self._send_slack(alert, self.SLACK_WEBHOOKS["critical"])

        # Error: Slack alerts channel
        elif alert.severity == AlertSeverity.ERROR:
            self._send_slack(alert, self.SLACK_WEBHOOKS["error"])

        # Warning: Slack health channel
        elif alert.severity == AlertSeverity.WARNING:
            self._send_slack(alert, self.SLACK_WEBHOOKS["warning"])

        # Always log
        self._log_alert(alert)

    def _send_slack(self, alert: Alert, webhook: Optional[str]):
        if not webhook:
            return

        color = {
            AlertSeverity.CRITICAL: "#FF0000",
            AlertSeverity.ERROR: "#FF6600",
            AlertSeverity.WARNING: "#FFCC00",
            AlertSeverity.INFO: "#0066FF",
        }.get(alert.severity, "#808080")

        payload = {
            "attachments": [{
                "color": color,
                "title": f"[{alert.severity.value.upper()}] {alert.title}",
                "text": alert.message,
                "fields": [
                    {"title": "Source", "value": alert.source, "short": True},
                    {"title": "Date", "value": alert.affected_date or "N/A", "short": True},
                ],
                "footer": "NBA Pipeline Validation",
            }]
        }

        if alert.remediation:
            payload["attachments"][0]["fields"].append({
                "title": "Remediation",
                "value": "\n".join(f"• {r}" for r in alert.remediation[:3]),
                "short": False
            })

        try:
            requests.post(webhook, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")

    def _send_pagerduty(self, alert: Alert):
        if not self.PAGERDUTY_KEY:
            return

        payload = {
            "routing_key": self.PAGERDUTY_KEY,
            "event_action": "trigger",
            "payload": {
                "summary": f"{alert.title}: {alert.message}",
                "source": alert.source,
                "severity": "critical",
                "custom_details": {
                    "affected_date": alert.affected_date,
                    "affected_items": alert.affected_items[:5] if alert.affected_items else [],
                    "remediation": alert.remediation,
                }
            }
        }

        try:
            requests.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                timeout=10
            )
        except Exception as e:
            logger.error(f"Failed to send PagerDuty alert: {e}")

    def _log_alert(self, alert: Alert):
        """Log alert to BigQuery for historical tracking."""
        # Implementation: Insert into nba_orchestration.alert_log
        pass


# Usage in validators:
def send_validation_alert(result: ValidationResult):
    """Convert ValidationResult to Alert and dispatch."""
    alert = Alert(
        title=result.check_name,
        message=result.message,
        severity=AlertSeverity(result.severity),
        source=result.validator_name,
        affected_date=result.date_checked,
        affected_items=result.affected_items,
        remediation=result.remediation,
    )
    AlertDispatcher().dispatch(alert)
```

**Environment Variables Needed:**
```bash
SLACK_WEBHOOK_CRITICAL=https://hooks.slack.com/services/xxx
SLACK_WEBHOOK_ALERTS=https://hooks.slack.com/services/xxx
SLACK_WEBHOOK_PIPELINE_HEALTH=https://hooks.slack.com/services/xxx
PAGERDUTY_INTEGRATION_KEY=xxx
```

---

### 1.2 Rollback Procedures

**Priority:** P1 (High)
**Effort:** Low
**Status:** Not documented

**The Gap:**

No documented procedures for rolling back if deployments cause issues.

**Recommendation:**

Add to DEPLOYMENT-GUIDE.md:

```markdown
## Rollback Procedures

### Auto-Retry Processor Rollback

If auto-retry processor causes issues after deployment:

```bash
# Option 1: Disable the function temporarily
gcloud functions delete auto-retry-processor --region us-west2

# Option 2: Revert to previous version (if available in source control)
git checkout HEAD~1 -- orchestration/cloud_functions/auto_retry_processor/main.py
./bin/orchestrators/deploy_auto_retry_processor.sh

# Option 3: Deploy minimal "no-op" version
cat > /tmp/noop_main.py << 'EOF'
def process_failed_processors(request):
    """Temporarily disabled - returns success without processing."""
    return {"status": "disabled", "message": "Auto-retry temporarily disabled"}
EOF
# Deploy this instead
```

### Phase 4→5 Gate Emergency Disable

If the gate is blocking legitimate processing:

```bash
# Method 1: Environment variable override (preferred)
gcloud functions update phase4-to-phase5-orchestrator \
  --update-env-vars GATE_OVERRIDE=true \
  --region us-west2

# Method 2: Remove gate check from code temporarily
# Edit phase4_to_phase5/main.py and comment out gate logic

# Method 3: Lower thresholds temporarily
gcloud functions update phase4-to-phase5-orchestrator \
  --update-env-vars GATE_QUALITY_THRESHOLD=50,GATE_PLAYER_THRESHOLD=0.5 \
  --region us-west2
```

### Validator Rollback

Validators are standalone scripts, so rollback is simpler:

```bash
# Just don't run the validator, or:
git checkout HEAD~1 -- bin/validation/<validator>.py

# If scheduled, disable the Cloud Scheduler job:
gcloud scheduler jobs pause validation-<name> --location us-central1
```

### Full System Rollback Checklist

If multiple components need rollback:

1. [ ] Pause all Cloud Scheduler jobs for validators
2. [ ] Disable auto-retry processor
3. [ ] Remove gate environment variables
4. [ ] Revert code changes in git
5. [ ] Redeploy affected cloud functions
6. [ ] Verify system health with manual checks
7. [ ] Gradually re-enable components one by one
```

---

### 1.3 Operational Runbook

**Priority:** P1 (High)
**Effort:** Medium
**Status:** Not documented

**The Gap:**

No quick-reference runbook for common validation issues.

**Recommendation:**

Create `/docs/runbooks/VALIDATION-RUNBOOK.md`:

```markdown
# Validation Runbook - Quick Reference

## Decision Tree: Which Validator to Run

```
Issue Reported
    │
    ├─► "Missing data for date X"
    │   └─► Run: python bin/validation/daily_data_completeness.py --date X
    │
    ├─► "Predictions seem wrong"
    │   └─► Run: python bin/validation/trace_entity.py --player "name" --date X
    │
    ├─► "Feature quality dropped"
    │   └─► Run: python bin/validation/quality_trend_monitor.py --days 7
    │
    ├─► "Pipeline seems stuck"
    │   └─► Run: python bin/validation/workflow_health.py --hours 24
    │
    ├─► "After running backfill"
    │   └─► Run: python bin/validation/validate_backfill.py --phase X --date Y
    │
    └─► "General health check"
        └─► Run: python bin/validation/comprehensive_health_check.py --date today
```

## Common Issues & Fixes

### Issue: Gate Blocking Phase 5

**Symptoms:** No new predictions being generated
**Diagnosis:**
```bash
# Check gate status
python -c "
from validation.validators.gates.phase4_to_phase5_gate import evaluate_phase4_to_phase5_gate
result = evaluate_phase4_to_phase5_gate('$(date +%Y-%m-%d)')
print(f'Decision: {result.decision}')
print(f'Reasons: {result.blocking_reasons}')
"
```

**Fixes:**
- If quality legitimately low → Run feature backfill first
- If false positive → Use GATE_OVERRIDE=true temporarily
- If threshold too strict → Adjust GATE_QUALITY_THRESHOLD

### Issue: Auto-Retry Not Processing

**Symptoms:** Games stuck in failed_processor_queue
**Diagnosis:**
```bash
gcloud functions logs read auto-retry-processor --region us-west2 --limit 20
```

**Fixes:**
- If 404 errors → Redeploy with HTTP endpoints
- If 500 errors → Check target service health
- If not running → Check Cloud Scheduler trigger

### Issue: Validator Reporting False Positives

**Symptoms:** Alerts for data that exists
**Diagnosis:**
```bash
# Check if it's a timezone issue
bq query "SELECT game_date, COUNT(*) FROM table WHERE game_date = 'YYYY-MM-DD' GROUP BY 1"
# vs
bq query "SELECT game_date, COUNT(*) FROM table WHERE game_date = DATE('YYYY-MM-DD', 'America/New_York') GROUP BY 1"
```

**Fixes:**
- Timezone mismatch → Standardize on UTC or ET consistently
- Query logic error → Fix validator query
- View stale → Refresh materialized view

## Emergency Contacts

- Pipeline On-Call: #nba-pipeline-oncall
- Escalation: @pipeline-team-lead
```

---

## 2. Reliability Improvements

### 2.1 Circuit Breaker for HTTP Retries

**Priority:** P1 (High)
**Effort:** Low
**Status:** Not implemented

**The Gap:**

Auto-retry processor makes HTTP calls without circuit breaker protection. If a Cloud Run service is overloaded, auto-retry will keep hammering it.

**Recommendation:**

```python
# Add to auto_retry_processor/main.py

from functools import wraps
import time

class CircuitBreaker:
    """Simple circuit breaker implementation."""

    def __init__(self, failure_threshold=3, recovery_timeout=300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = {}  # endpoint -> failure count
        self.last_failure = {}  # endpoint -> timestamp
        self.state = {}  # endpoint -> 'closed' | 'open' | 'half-open'

    def call(self, endpoint: str, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""

        # Check if circuit is open
        if self._is_open(endpoint):
            raise CircuitOpenError(f"Circuit open for {endpoint}")

        try:
            result = func(*args, **kwargs)
            self._record_success(endpoint)
            return result
        except Exception as e:
            self._record_failure(endpoint)
            raise

    def _is_open(self, endpoint: str) -> bool:
        if self.state.get(endpoint) != 'open':
            return False

        # Check if recovery timeout has passed
        if time.time() - self.last_failure.get(endpoint, 0) > self.recovery_timeout:
            self.state[endpoint] = 'half-open'
            return False

        return True

    def _record_success(self, endpoint: str):
        self.failures[endpoint] = 0
        self.state[endpoint] = 'closed'

    def _record_failure(self, endpoint: str):
        self.failures[endpoint] = self.failures.get(endpoint, 0) + 1
        self.last_failure[endpoint] = time.time()

        if self.failures[endpoint] >= self.failure_threshold:
            self.state[endpoint] = 'open'
            logger.warning(f"Circuit opened for {endpoint} after {self.failures[endpoint]} failures")


class CircuitOpenError(Exception):
    pass


# Global circuit breaker instance
circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=300)


def call_phase_endpoint_with_circuit_breaker(endpoint: str, payload: dict) -> dict:
    """Call endpoint with circuit breaker protection."""

    def _make_call():
        response = requests.post(
            endpoint,
            json=payload,
            headers=get_auth_headers(),
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    try:
        return circuit_breaker.call(endpoint, _make_call)
    except CircuitOpenError:
        logger.warning(f"Circuit open for {endpoint}, deferring retry")
        return {"status": "deferred", "reason": "circuit_open"}
```

---

### 2.2 Health Check Before HTTP Calls

**Priority:** P1 (High)
**Effort:** Low
**Status:** Not implemented

**The Gap:**

Auto-retry calls endpoints without checking if they're healthy first.

**Recommendation:**

```python
# Add to auto_retry_processor/main.py

import requests
from typing import Dict, Optional

# Cache health check results (TTL: 60 seconds)
_health_cache: Dict[str, tuple] = {}  # endpoint -> (healthy: bool, timestamp: float)
HEALTH_CHECK_TTL = 60


def check_endpoint_health(endpoint: str) -> bool:
    """
    Check if endpoint is healthy before making requests.

    Uses cached result if available and fresh.
    """
    # Check cache
    cached = _health_cache.get(endpoint)
    if cached and (time.time() - cached[1]) < HEALTH_CHECK_TTL:
        return cached[0]

    # Derive health endpoint from process endpoint
    # e.g., https://service/process -> https://service/health
    health_endpoint = endpoint.rsplit('/', 1)[0] + '/health'

    try:
        response = requests.get(health_endpoint, timeout=5)
        healthy = response.status_code == 200
    except Exception:
        healthy = False

    # Cache result
    _health_cache[endpoint] = (healthy, time.time())

    if not healthy:
        logger.warning(f"Endpoint unhealthy: {endpoint}")

    return healthy


def retry_with_health_check(processor_info: dict) -> dict:
    """Retry processor only if target endpoint is healthy."""

    phase = processor_info.get('phase')
    endpoint = PHASE_HTTP_ENDPOINTS.get(phase)

    if not endpoint:
        return {"status": "error", "message": f"Unknown phase: {phase}"}

    # Health check first
    if not check_endpoint_health(endpoint):
        logger.info(f"Deferring retry for {processor_info['processor_name']} - endpoint unhealthy")
        return {"status": "deferred", "reason": "endpoint_unhealthy"}

    # Proceed with retry
    return call_phase_endpoint_with_circuit_breaker(endpoint, processor_info)
```

**Cloud Run Health Endpoint:**

Ensure each Cloud Run service has a `/health` endpoint:

```python
# In each Cloud Run service main.py

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for load balancers and monitors."""
    # Basic health
    checks = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Optional: Check dependencies
    try:
        # Quick BigQuery check
        bq_client.query("SELECT 1").result()
        checks["bigquery"] = "ok"
    except Exception as e:
        checks["bigquery"] = f"error: {e}"
        checks["status"] = "degraded"

    status_code = 200 if checks["status"] == "healthy" else 503
    return jsonify(checks), status_code
```

---

### 2.3 Concurrency Protection

**Priority:** P2 (Medium)
**Effort:** Medium
**Status:** Not addressed

**The Gap:**

What happens if two validator instances run simultaneously? Or if auto-retry processes the same job twice?

**Recommendation:**

```python
# shared/utils/distributed_lock.py
"""Distributed locking using BigQuery (simple approach)."""

from google.cloud import bigquery
from datetime import datetime, timedelta
import uuid

class BigQueryLock:
    """
    Simple distributed lock using BigQuery.

    For production, consider using Redis or Cloud Memorystore.
    """

    def __init__(self, lock_name: str, ttl_seconds: int = 300):
        self.lock_name = lock_name
        self.ttl_seconds = ttl_seconds
        self.lock_id = str(uuid.uuid4())
        self.bq_client = bigquery.Client()

    def acquire(self) -> bool:
        """Attempt to acquire lock. Returns True if successful."""

        # Try to insert lock record
        query = """
        INSERT INTO `nba_orchestration.distributed_locks`
        (lock_name, lock_id, acquired_at, expires_at)
        SELECT
            @lock_name,
            @lock_id,
            CURRENT_TIMESTAMP(),
            TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL @ttl SECOND)
        WHERE NOT EXISTS (
            SELECT 1 FROM `nba_orchestration.distributed_locks`
            WHERE lock_name = @lock_name
            AND expires_at > CURRENT_TIMESTAMP()
        )
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lock_name", "STRING", self.lock_name),
                bigquery.ScalarQueryParameter("lock_id", "STRING", self.lock_id),
                bigquery.ScalarQueryParameter("ttl", "INT64", self.ttl_seconds),
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()

        # Check if we got the lock
        return result.num_dml_affected_rows > 0

    def release(self):
        """Release the lock."""
        query = """
        DELETE FROM `nba_orchestration.distributed_locks`
        WHERE lock_name = @lock_name AND lock_id = @lock_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lock_name", "STRING", self.lock_name),
                bigquery.ScalarQueryParameter("lock_id", "STRING", self.lock_id),
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()

    def __enter__(self):
        if not self.acquire():
            raise LockNotAcquiredError(f"Could not acquire lock: {self.lock_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class LockNotAcquiredError(Exception):
    pass


# Usage in validators:
def run_validator_with_lock(validator_name: str, date: str):
    """Run validator with distributed lock to prevent concurrent runs."""

    lock_name = f"validator_{validator_name}_{date}"

    try:
        with BigQueryLock(lock_name, ttl_seconds=600):
            # Run the actual validation
            return run_validation(validator_name, date)
    except LockNotAcquiredError:
        logger.info(f"Validator {validator_name} already running for {date}, skipping")
        return {"status": "skipped", "reason": "already_running"}
```

**Lock Table:**
```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.distributed_locks` (
    lock_name STRING NOT NULL,
    lock_id STRING NOT NULL,
    acquired_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL
);

-- Cleanup expired locks periodically
CREATE SCHEDULED QUERY cleanup_expired_locks
SCHEDULE 'every 1 hours'
AS
DELETE FROM `nba_orchestration.distributed_locks`
WHERE expires_at < CURRENT_TIMESTAMP();
```

---

## 3. Edge Case Handling

### 3.1 Seasonal / Schedule Edge Cases

**Priority:** P2 (Medium)
**Effort:** Low
**Status:** Not addressed

**The Gap:**

Validators might alert on "missing data" when there are legitimately no games (All-Star break, off-season, etc.)

**Recommendation:**

```python
# shared/utils/schedule_awareness.py
"""Schedule-aware utilities for validators."""

from datetime import date
from typing import Optional

# NBA schedule constants
ALL_STAR_BREAK_2026 = (date(2026, 2, 14), date(2026, 2, 19))
REGULAR_SEASON_2026 = (date(2025, 10, 22), date(2026, 4, 13))
PLAYOFFS_2026 = (date(2026, 4, 19), date(2026, 6, 22))


def get_expected_game_count(check_date: date) -> Optional[int]:
    """
    Get expected number of games for a date.

    Returns None if no games expected (off-season, all-star break).
    Returns approximate count for normal days.
    """

    # Off-season: no games expected
    if check_date < REGULAR_SEASON_2026[0] or check_date > PLAYOFFS_2026[1]:
        return None

    # All-Star break: no games (except All-Star game itself)
    if ALL_STAR_BREAK_2026[0] <= check_date <= ALL_STAR_BREAK_2026[1]:
        if check_date == date(2026, 2, 16):  # All-Star Sunday
            return 1
        return None

    # Normal day: expect 3-15 games
    # Could query schedule table for exact count
    return None  # Let validator query schedule


def is_game_day(check_date: date) -> bool:
    """Check if games are expected on this date."""
    return get_expected_game_count(check_date) is not None


def get_schedule_context(check_date: date) -> dict:
    """Get context about the schedule for a date."""
    return {
        "is_game_day": is_game_day(check_date),
        "is_all_star_break": ALL_STAR_BREAK_2026[0] <= check_date <= ALL_STAR_BREAK_2026[1],
        "is_playoffs": PLAYOFFS_2026[0] <= check_date <= PLAYOFFS_2026[1],
        "is_off_season": check_date < REGULAR_SEASON_2026[0] or check_date > PLAYOFFS_2026[1],
    }


# Usage in validators:
def validate_with_schedule_awareness(check_date: str):
    """Only alert if games were expected."""

    context = get_schedule_context(date.fromisoformat(check_date))

    if not context["is_game_day"]:
        logger.info(f"No games expected for {check_date}, skipping validation")
        return {"status": "skipped", "reason": "no_games_expected", "context": context}

    # Proceed with normal validation
    return run_normal_validation(check_date)
```

---

### 3.2 Timezone Handling

**Priority:** P2 (Medium)
**Effort:** Medium
**Status:** Implicit but not documented

**The Gap:**

Games are scheduled in ET, servers run in UTC, BigQuery timestamps are UTC. Inconsistent handling causes validation issues around midnight.

**Recommendation:**

```python
# shared/utils/timezone_utils.py
"""Standardized timezone handling for NBA pipeline."""

from datetime import datetime, date, timedelta
import pytz

ET = pytz.timezone('America/New_York')
UTC = pytz.UTC

# NBA "game date" is always in ET
# A game at 10pm ET on Jan 24 has game_date = 2026-01-24
# Even if it's 3am UTC on Jan 25


def get_nba_game_date(utc_timestamp: datetime) -> date:
    """
    Convert UTC timestamp to NBA game date (ET).

    Example:
        UTC 2026-01-25 03:00:00 -> NBA date 2026-01-24
        (because it's 10pm ET on Jan 24)
    """
    if utc_timestamp.tzinfo is None:
        utc_timestamp = UTC.localize(utc_timestamp)

    et_time = utc_timestamp.astimezone(ET)
    return et_time.date()


def get_current_nba_date() -> date:
    """Get current NBA game date (in ET)."""
    return get_nba_game_date(datetime.now(UTC))


def is_games_likely_complete(game_date: date) -> bool:
    """
    Check if games for a date are likely complete.

    Games typically end by 1am ET the next day.
    """
    now_et = datetime.now(ET)
    game_date_end = ET.localize(datetime.combine(game_date + timedelta(days=1), datetime.min.time()))
    game_date_end = game_date_end.replace(hour=1)  # 1am ET next day

    return now_et > game_date_end


def get_validation_date_range(days_back: int = 7) -> tuple:
    """
    Get safe date range for validation.

    Excludes today if games haven't completed yet.
    """
    end_date = get_current_nba_date()

    # If it's before 1am ET, don't include today's date
    if not is_games_likely_complete(end_date):
        end_date = end_date - timedelta(days=1)

    start_date = end_date - timedelta(days=days_back - 1)

    return (start_date, end_date)


# Document the standard:
"""
TIMEZONE STANDARD FOR NBA PIPELINE
==================================

1. game_date columns: Always ET date (YYYY-MM-DD)
2. Timestamps (created_at, etc): Always UTC
3. Schedule times: Stored as ET, displayed as ET
4. Validation: Always use get_current_nba_date() not date.today()

Example Query:
    -- Correct: Use ET-aware date
    WHERE game_date = DATE(CURRENT_TIMESTAMP(), 'America/New_York')

    -- Incorrect: Uses UTC date (wrong after 7pm ET)
    WHERE game_date = CURRENT_DATE()
"""
```

---

### 3.3 Postponed/Cancelled Games

**Priority:** P2 (Medium)
**Effort:** Low
**Status:** Not addressed

**The Gap:**

How do validators handle games that were scheduled but postponed/cancelled?

**Recommendation:**

```python
# In cross_phase_validator.py

VALID_GAME_STATUSES = ['Final', 'Completed']
POSTPONED_STATUSES = ['Postponed', 'Cancelled', 'Suspended']


def get_expected_games(game_date: str) -> list:
    """Get games that should have data, excluding postponed/cancelled."""

    query = """
    SELECT game_id, home_team, away_team, game_status
    FROM `nba_raw.v_nbac_schedule_latest`
    WHERE game_date = @game_date
    AND game_status IN UNNEST(@valid_statuses)
    """

    return run_query(query, {
        "game_date": game_date,
        "valid_statuses": VALID_GAME_STATUSES
    })


def check_for_postponed_games(game_date: str) -> list:
    """Check for postponed games that might confuse validation."""

    query = """
    SELECT game_id, home_team, away_team, game_status
    FROM `nba_raw.v_nbac_schedule_latest`
    WHERE game_date = @game_date
    AND game_status IN UNNEST(@postponed_statuses)
    """

    postponed = run_query(query, {
        "game_date": game_date,
        "postponed_statuses": POSTPONED_STATUSES
    })

    if postponed:
        logger.info(f"Found {len(postponed)} postponed/cancelled games for {game_date}")

    return postponed
```

---

### 3.4 NBA Retroactive Stat Corrections

**Priority:** P3 (Low)
**Effort:** Medium
**Status:** Not addressed

**The Gap:**

NBA sometimes updates stats 1-3 days after games. Predictions graded against original stats might become "incorrect" after corrections.

**Recommendation:**

```python
# Track stat versions
"""
Add to boxscore tables:
    - source_version: INT (increments on corrections)
    - last_updated_at: TIMESTAMP
    - original_values: JSON (snapshot of first version)
"""

# In grading processor:
def should_regrade_predictions(game_date: str) -> list:
    """
    Check if any boxscores have been updated since grading.

    Returns list of games that need regrading.
    """

    query = """
    SELECT DISTINCT b.game_id
    FROM `nba_raw.bdl_player_boxscores` b
    JOIN `nba_predictions.prediction_accuracy` pa
        ON b.game_id = pa.game_id
    WHERE b.game_date = @game_date
    AND b.last_updated_at > pa.graded_at
    """

    return run_query(query, {"game_date": game_date})


# Add to daily validation:
def check_for_stat_corrections(days_back: int = 7):
    """Alert if stat corrections might affect grading."""

    query = """
    SELECT
        game_date,
        COUNT(DISTINCT game_id) as games_with_updates,
        MAX(last_updated_at) as latest_update
    FROM `nba_raw.bdl_player_boxscores`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    AND last_updated_at > DATE_ADD(game_date, INTERVAL 2 DAY)  -- Updated 2+ days after game
    GROUP BY 1
    HAVING games_with_updates > 0
    """

    corrections = run_query(query, {"days": days_back})

    if corrections:
        logger.warning(f"Found {len(corrections)} dates with stat corrections")
        # Could trigger regrade
```

---

## 4. Observability Enhancements

### 4.1 Structured Logging Standard

**Priority:** P2 (Medium)
**Effort:** Medium
**Status:** Not standardized

**The Gap:**

Logs are inconsistent across modules. No correlation IDs for tracing requests.

**Recommendation:**

```python
# shared/utils/structured_logger.py
"""Structured logging with correlation IDs."""

import structlog
import uuid
import os
from contextvars import ContextVar
from functools import wraps

# Context variable for request/run ID
_run_id: ContextVar[str] = ContextVar('run_id', default='')

def get_run_id() -> str:
    return _run_id.get() or str(uuid.uuid4())[:8]

def set_run_id(run_id: str):
    _run_id.set(run_id)


# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()  # JSON for cloud logging
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


def get_logger(name: str = None):
    """Get a structured logger with automatic context."""
    logger = structlog.get_logger(name)

    # Bind common context
    return logger.bind(
        run_id=get_run_id(),
        environment=os.environ.get('ENVIRONMENT', 'development'),
        service=os.environ.get('K_SERVICE', 'unknown'),
    )


def log_processor_event(
    event: str,
    processor: str,
    game_date: str = None,
    game_id: str = None,
    player_lookup: str = None,
    **kwargs
):
    """Standard log format for processor events."""
    logger = get_logger(processor)

    logger.info(
        event,
        processor=processor,
        game_date=game_date,
        game_id=game_id,
        player_lookup=player_lookup,
        **kwargs
    )


def with_run_id(func):
    """Decorator to set run_id for a function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        run_id = kwargs.pop('run_id', None) or str(uuid.uuid4())[:8]
        set_run_id(run_id)
        return func(*args, **kwargs)
    return wrapper


# Usage:
"""
from shared.utils.structured_logger import get_logger, log_processor_event, with_run_id

logger = get_logger(__name__)

@with_run_id
def process_game(game_id: str, game_date: str):
    log_processor_event(
        event="processing_started",
        processor="boxscore_processor",
        game_id=game_id,
        game_date=game_date
    )

    # ... processing ...

    log_processor_event(
        event="processing_completed",
        processor="boxscore_processor",
        game_id=game_id,
        game_date=game_date,
        records_processed=150,
        duration_seconds=2.5
    )
"""
```

---

### 4.2 Validation Query Cost Monitoring

**Priority:** P2 (Medium)
**Effort:** Low
**Status:** Not implemented

**The Gap:**

New validators run many BigQuery queries. No cost monitoring.

**Recommendation:**

```sql
-- Create cost monitoring view
CREATE OR REPLACE VIEW `nba_orchestration.v_query_costs_by_source` AS
SELECT
  DATE(creation_time) as query_date,
  CASE
    WHEN query LIKE '%validation%' THEN 'validation'
    WHEN query LIKE '%backfill%' THEN 'backfill'
    WHEN query LIKE '%prediction%' THEN 'prediction'
    WHEN query LIKE '%grading%' THEN 'grading'
    ELSE 'other'
  END as query_source,
  COUNT(*) as query_count,
  SUM(total_bytes_billed) / POW(1024, 4) as tb_billed,
  SUM(total_bytes_billed) / POW(1024, 4) * 6.25 as estimated_cost_usd,  -- $6.25/TB on-demand
  AVG(total_slot_ms) / 1000 as avg_slot_seconds
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
AND job_type = 'QUERY'
AND state = 'DONE'
GROUP BY 1, 2
ORDER BY 1 DESC, estimated_cost_usd DESC;

-- Alert if daily validation cost exceeds threshold
CREATE SCHEDULED QUERY check_validation_costs
SCHEDULE 'every day 08:00'
AS
SELECT
  query_date,
  query_source,
  estimated_cost_usd
FROM `nba_orchestration.v_query_costs_by_source`
WHERE query_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
AND query_source = 'validation'
AND estimated_cost_usd > 5.00;  -- Alert if > $5/day
```

---

### 4.3 SLOs for Validation

**Priority:** P2 (Medium)
**Effort:** Low
**Status:** Not defined

**The Gap:**

No defined SLOs for validation system itself.

**Recommendation:**

```markdown
## Validation System SLOs

### Detection Time SLO
- **Target:** Detect data issues within 30 minutes of occurrence
- **Measurement:** Time between issue start and first alert
- **Current:** ~4 hours (before improvements)

### False Positive Rate SLO
- **Target:** < 5% of alerts are false positives
- **Measurement:** Alerts that were closed as "not an issue"
- **Current:** Unknown

### Validation Coverage SLO
- **Target:** > 95% of data paths have validation
- **Measurement:** Validated paths / Total paths
- **Current:** ~60%

### Validator Availability SLO
- **Target:** 99.5% of scheduled validator runs complete successfully
- **Measurement:** Successful runs / Total scheduled runs
- **Current:** Unknown

### Recovery Time SLO
- **Target:** < 2 hours from issue detection to fix deployed
- **Measurement:** Time between first alert and fix confirmation
- **Current:** Unknown (manual process)
```

**Tracking Query:**
```sql
-- Track detection time SLO
CREATE OR REPLACE VIEW `nba_orchestration.v_validation_slo_detection_time` AS
SELECT
  DATE(detected_at) as date,
  check_type,
  AVG(TIMESTAMP_DIFF(detected_at, issue_started_at, MINUTE)) as avg_detection_minutes,
  COUNTIF(TIMESTAMP_DIFF(detected_at, issue_started_at, MINUTE) <= 30) / COUNT(*) as within_slo_pct
FROM `nba_orchestration.validation_detections`
WHERE detected_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1, 2;
```

---

### 4.4 Validation of Validators ("Who Watches the Watchmen?")

**Priority:** P3 (Low)
**Effort:** Low
**Status:** Not addressed

**The Gap:**

What if a validator itself is broken and not running?

**Recommendation:**

```python
# bin/validation/meta_validator.py
"""Validate that validators are running correctly."""

def check_validator_health():
    """Verify validators are running and producing results."""

    checks = []

    # Check 1: Recent validation runs exist
    query = """
    SELECT validator_name, MAX(run_timestamp) as last_run
    FROM `nba_orchestration.validation_runs`
    GROUP BY 1
    """

    runs = run_query(query)

    for run in runs:
        hours_since_run = (datetime.now() - run.last_run).total_seconds() / 3600

        if hours_since_run > 24:
            checks.append({
                "validator": run.validator_name,
                "status": "stale",
                "hours_since_run": hours_since_run,
                "severity": "warning"
            })

    # Check 2: No validator has 100% failure rate recently
    query = """
    SELECT
        validator_name,
        COUNTIF(passed) / COUNT(*) as pass_rate
    FROM `nba_orchestration.validation_results`
    WHERE run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY 1
    HAVING pass_rate = 0  -- 100% failure rate
    """

    all_failures = run_query(query)

    for failure in all_failures:
        checks.append({
            "validator": failure.validator_name,
            "status": "all_failures",
            "pass_rate": 0,
            "severity": "error"
        })

    # Check 3: Scheduled validators actually ran
    expected_daily = ['daily_data_completeness', 'workflow_health', 'comprehensive_health_check']

    query = """
    SELECT validator_name
    FROM `nba_orchestration.validation_runs`
    WHERE run_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND validator_name IN UNNEST(@expected)
    """

    ran_today = [r.validator_name for r in run_query(query, {"expected": expected_daily})]
    missing = set(expected_daily) - set(ran_today)

    for validator in missing:
        checks.append({
            "validator": validator,
            "status": "did_not_run",
            "severity": "error"
        })

    return checks


if __name__ == "__main__":
    issues = check_validator_health()
    if issues:
        print(f"Found {len(issues)} validator health issues:")
        for issue in issues:
            print(f"  - {issue['validator']}: {issue['status']} ({issue['severity']})")
    else:
        print("All validators healthy")
```

---

## 5. Recovery Procedures

### 5.1 Backfill Dependency Graph

**Priority:** P2 (Medium)
**Effort:** Low
**Status:** Not documented

**The Gap:**

When recovering data, which phases must complete before others?

**Recommendation:**

```markdown
## Backfill Dependency Graph

```
Phase 1: Schedule
    │
    └─► Must exist before any other phase
        (usually auto-populated from NBA.com)

Phase 2: Boxscores (Raw Data)
    │
    ├─► BDL boxscores
    ├─► NBA.com gamebook
    └─► Odds/props data
    │
    └─► Required before Phase 3

Phase 3: Analytics
    │
    ├─► player_game_summary
    ├─► team_defense_summary
    └─► team_offense_summary
    │
    └─► Required before Phase 4

Phase 4: Features (Precompute)
    │
    ├─► ml_feature_store
    ├─► rolling windows
    └─► composite factors
    │
    └─► Required before Phase 5

Phase 5: Predictions
    │
    └─► player_prop_predictions
    │
    └─► Required before Phase 6

Phase 6: Grading
    │
    └─► prediction_accuracy
```

## Recovery Commands by Scenario

### Scenario: Missing Boxscores
```bash
# 1. Backfill boxscores
python bin/backfill/bdl_boxscores.py --date YYYY-MM-DD

# 2. Trigger downstream (or wait for orchestrator)
python bin/backfill/phase3.py --date YYYY-MM-DD
python bin/backfill/phase4.py --date YYYY-MM-DD
# Phase 5 & 6 happen automatically
```

### Scenario: Low Feature Quality
```bash
# Feature quality depends on rolling windows
# Need to backfill from a good starting point

# 1. Find last good date
bq query "SELECT MAX(game_date) FROM ml_feature_store WHERE feature_quality_score > 75"

# 2. Backfill from there
python bin/backfill/phase3.py --start-date YYYY-MM-DD --end-date today
python bin/backfill/phase4.py --start-date YYYY-MM-DD --end-date today
```

### Scenario: Missing Grading
```bash
# Grading only requires predictions + boxscores
# No need to reprocess upstream

python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```
```

---

### 5.2 Partial Recovery

**Priority:** P3 (Low)
**Effort:** Medium
**Status:** Not addressed

**The Gap:**

Can we recover just one game without affecting others?

**Recommendation:**

```python
# bin/backfill/single_game_recovery.py
"""Recover a single game through all phases."""

import argparse
from datetime import date

def recover_single_game(game_id: str, game_date: str):
    """
    Recover a single game through the entire pipeline.

    Use when one game is missing but others are fine.
    """

    print(f"Recovering game {game_id} for {game_date}")

    # Phase 2: Boxscore
    print("Phase 2: Fetching boxscore...")
    from scrapers.balldontlie import BDLBoxscoreScraper
    scraper = BDLBoxscoreScraper()
    scraper.scrape_game(game_id, game_date)

    # Phase 3: Analytics
    print("Phase 3: Processing analytics...")
    from data_processors.analytics import PlayerGameSummaryProcessor
    processor = PlayerGameSummaryProcessor()
    processor.process_game(game_id, game_date)

    # Phase 4: Features
    print("Phase 4: Computing features...")
    from data_processors.precompute import MLFeatureStoreProcessor
    processor = MLFeatureStoreProcessor()
    processor.process_players_for_game(game_id, game_date)

    # Phase 5: Predictions (if game is upcoming)
    # Usually not needed for recovery

    # Phase 6: Grading (if predictions exist)
    print("Phase 6: Grading predictions...")
    from data_processors.grading import PredictionAccuracyProcessor
    processor = PredictionAccuracyProcessor()
    processor.grade_game(game_id, game_date)

    print(f"Recovery complete for {game_id}")

    # Validate
    print("Validating recovery...")
    from bin.validation.trace_entity import trace_game
    trace_game(game_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    recover_single_game(args.game_id, args.date)
```

---

## 6. Summary: Priority Matrix

| # | Item | Priority | Effort | Category |
|---|------|----------|--------|----------|
| 1.1 | Alerting implementation | P1 | Medium | Operational |
| 1.2 | Rollback procedures | P1 | Low | Operational |
| 1.3 | Operational runbook | P1 | Medium | Operational |
| 2.1 | Circuit breaker | P1 | Low | Reliability |
| 2.2 | Health check before HTTP | P1 | Low | Reliability |
| 2.3 | Concurrency protection | P2 | Medium | Reliability |
| 3.1 | Seasonal edge cases | P2 | Low | Edge Cases |
| 3.2 | Timezone handling | P2 | Medium | Edge Cases |
| 3.3 | Postponed games | P2 | Low | Edge Cases |
| 3.4 | Stat corrections | P3 | Medium | Edge Cases |
| 4.1 | Structured logging | P2 | Medium | Observability |
| 4.2 | Query cost monitoring | P2 | Low | Observability |
| 4.3 | Validation SLOs | P2 | Low | Observability |
| 4.4 | Meta-validator | P3 | Low | Observability |
| 5.1 | Backfill dependency docs | P2 | Low | Recovery |
| 5.2 | Partial recovery | P3 | Medium | Recovery |

---

## 7. Implementation Order Recommendation

### Week 1 (Critical)
1. Alerting implementation (1.1)
2. Rollback procedures (1.2)
3. Circuit breaker (2.1)
4. Health check (2.2)

### Week 2 (Important)
5. Operational runbook (1.3)
6. Seasonal edge cases (3.1)
7. Query cost monitoring (4.2)
8. Backfill dependency docs (5.1)

### Week 3+ (Nice to Have)
9. Remaining items based on priority

---

**Document Version:** 2.0
**Created:** 2026-01-25
**Complements:** MASTER-IMPROVEMENT-PLAN.md, ADDITIONAL-IMPROVEMENTS-ADDENDUM.md
