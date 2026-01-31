# Implementation Plan - Data Quality Self-Healing

## Phase 1: Pre-Write Validation (Priority: P0)

### Goal
Block data corruption at the source before it reaches BigQuery.

### Tasks

#### 1.1 Create Pre-Write Validator Module

**File:** `shared/validation/pre_write_validator.py`

```python
"""
Pre-write validation with business logic rules.
Blocks records that would corrupt downstream data.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class ValidationRule:
    name: str
    condition: Callable[[dict], bool]  # Returns True if valid
    error_message: str
    severity: str = "ERROR"  # ERROR blocks write, WARNING logs only

class PreWriteValidator:
    """Validates records against business rules before BigQuery write."""

    def __init__(self, table_name: str):
        self.table_name = table_name
        self.rules = BUSINESS_RULES.get(table_name, [])

    def validate(self, records: List[dict]) -> tuple[List[dict], List[dict]]:
        """
        Validate records, returning (valid_records, invalid_records).
        Invalid records are logged but not written.
        """
        valid = []
        invalid = []

        for record in records:
            violations = self._check_rules(record)
            if violations:
                invalid.append({'record': record, 'violations': violations})
                self._log_violations(record, violations)
            else:
                valid.append(record)

        return valid, invalid

    def _check_rules(self, record: dict) -> List[str]:
        violations = []
        for rule in self.rules:
            try:
                if not rule.condition(record):
                    violations.append(f"{rule.name}: {rule.error_message}")
            except Exception as e:
                logger.warning(f"Rule {rule.name} failed: {e}")
        return violations

    def _log_violations(self, record: dict, violations: List[str]):
        player = record.get('player_lookup', 'unknown')
        game_date = record.get('game_date', 'unknown')
        logger.error(
            f"PRE_WRITE_VALIDATION_FAILED: table={self.table_name} "
            f"player={player} date={game_date} violations={violations}"
        )
```

#### 1.2 Define Business Rules

**Add to `shared/validation/pre_write_validator.py`:**

```python
BUSINESS_RULES = {
    'player_game_summary': [
        # DNP players must have NULL stats
        ValidationRule(
            name='dnp_null_points',
            condition=lambda r: not r.get('is_dnp') or r.get('points') is None,
            error_message="DNP players must have NULL points, not 0"
        ),
        ValidationRule(
            name='dnp_null_minutes',
            condition=lambda r: not r.get('is_dnp') or r.get('minutes') is None,
            error_message="DNP players must have NULL minutes"
        ),

        # Active players must have valid stats
        ValidationRule(
            name='active_non_negative_points',
            condition=lambda r: r.get('is_dnp') or (r.get('points') or 0) >= 0,
            error_message="Active players cannot have negative points"
        ),
        ValidationRule(
            name='active_has_minutes',
            condition=lambda r: r.get('is_dnp') or r.get('minutes') is not None,
            error_message="Active players must have minutes recorded"
        ),

        # Data completeness
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
    ],

    'player_composite_factors': [
        # Fatigue score range
        ValidationRule(
            name='fatigue_score_range',
            condition=lambda r: 0 <= (r.get('fatigue_score') or 0) <= 100,
            error_message="fatigue_score must be 0-100"
        ),

        # Context scores range
        ValidationRule(
            name='matchup_score_range',
            condition=lambda r: -50 <= (r.get('matchup_difficulty_score') or 0) <= 50,
            error_message="matchup_difficulty_score must be -50 to 50"
        ),
    ],

    'ml_feature_store_v2': [
        # Feature array completeness
        ValidationRule(
            name='feature_count',
            condition=lambda r: len(r.get('features', [])) == 34,
            error_message="ML features array must have exactly 34 elements"
        ),
    ],
}
```

#### 1.3 Integrate with Analytics Base

**File:** `data_processors/analytics/analytics_base.py`

Add pre-write validation before `_save_to_bigquery`:

```python
from shared.validation.pre_write_validator import PreWriteValidator

class AnalyticsProcessorBase:
    def _save_to_bigquery(self, records: List[dict], table_name: str):
        # NEW: Pre-write validation
        validator = PreWriteValidator(table_name)
        valid_records, invalid_records = validator.validate(records)

        if invalid_records:
            logger.warning(
                f"Blocked {len(invalid_records)} invalid records "
                f"from {table_name}"
            )
            # Optionally write to error table for investigation
            self._log_validation_failures(invalid_records, table_name)

        if not valid_records:
            logger.warning(f"No valid records to write to {table_name}")
            return

        # Continue with existing write logic
        # ...
```

#### 1.4 Add Validation Failure Logging Table

**File:** `schemas/bigquery/orchestration/validation_failures.sql`

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.validation_failures (
    failure_id STRING NOT NULL,
    failure_timestamp TIMESTAMP NOT NULL,
    table_name STRING NOT NULL,
    game_date DATE,
    player_lookup STRING,
    violations ARRAY<STRING>,
    record_json STRING,  -- JSON dump of failed record
    processor_name STRING,
    session_id STRING
)
PARTITION BY DATE(failure_timestamp)
CLUSTER BY table_name, game_date;
```

---

## Phase 2: Daily Anomaly Detection

### Goal
Catch quality issues within 24 hours through automated monitoring.

### Tasks

#### 2.1 Create Quality Metrics Table

**File:** `schemas/bigquery/orchestration/data_quality_metrics.sql`

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.data_quality_metrics (
    metric_id STRING NOT NULL,
    metric_date DATE NOT NULL,
    table_name STRING NOT NULL,
    metric_name STRING NOT NULL,
    metric_value FLOAT64 NOT NULL,
    threshold_warning FLOAT64,
    threshold_critical FLOAT64,
    status STRING NOT NULL,  -- OK, WARNING, CRITICAL
    details STRING,  -- Additional context
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY metric_date
CLUSTER BY table_name, metric_name;
```

#### 2.2 Define Quality Metrics

| Metric | Table | Warning | Critical | Query |
|--------|-------|---------|----------|-------|
| `pct_zero_points` | player_game_summary | > 15% | > 30% | See below |
| `pct_dnp_marked` | player_game_summary | < 5% | = 0% | See below |
| `avg_points_deviation` | player_game_summary | > 2 sigma | > 3 sigma | See below |
| `pct_null_features` | ml_feature_store_v2 | > 5% | > 10% | See below |
| `fatigue_avg` | player_composite_factors | < 50 or > 95 | < 30 or > 99 | See below |

#### 2.3 Create Anomaly Detection Cloud Function

**File:** `orchestration/cloud_functions/data_quality_monitor/main.py`

```python
"""
Daily data quality monitoring Cloud Function.
Runs at 8 AM ET, checks previous day's data.
"""

import functions_framework
from google.cloud import bigquery
from datetime import date, timedelta
import logging

from shared.utils.notification_system import notify_error, notify_warning

logger = logging.getLogger(__name__)

QUALITY_CHECKS = [
    {
        'name': 'pct_zero_points',
        'table': 'player_game_summary',
        'query': '''
            SELECT
                game_date,
                ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as value
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = @check_date
            GROUP BY game_date
        ''',
        'warning_threshold': 15.0,
        'critical_threshold': 30.0,
        'direction': 'above',  # Alert if value is ABOVE threshold
    },
    {
        'name': 'pct_dnp_marked',
        'table': 'player_game_summary',
        'query': '''
            SELECT
                game_date,
                ROUND(100.0 * COUNTIF(is_dnp = TRUE) / COUNT(*), 1) as value
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = @check_date
            GROUP BY game_date
        ''',
        'warning_threshold': 5.0,
        'critical_threshold': 0.0,
        'direction': 'below',  # Alert if value is BELOW threshold
    },
    {
        'name': 'fatigue_avg',
        'table': 'player_composite_factors',
        'query': '''
            SELECT
                game_date,
                AVG(fatigue_score) as value
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @check_date
            GROUP BY game_date
        ''',
        'warning_threshold': (50.0, 95.0),  # Range
        'critical_threshold': (30.0, 99.0),
        'direction': 'outside_range',
    },
]

@functions_framework.cloud_event
def check_data_quality(cloud_event):
    """Main entry point for Cloud Function."""
    client = bigquery.Client()
    check_date = date.today() - timedelta(days=1)

    results = []
    for check in QUALITY_CHECKS:
        result = run_quality_check(client, check, check_date)
        results.append(result)

        # Log to metrics table
        log_metric(client, result)

        # Alert if threshold breached
        if result['status'] == 'CRITICAL':
            notify_error(
                f"Data Quality CRITICAL: {check['name']}",
                f"Value: {result['value']}, Threshold: {check['critical_threshold']}"
            )
        elif result['status'] == 'WARNING':
            notify_warning(
                f"Data Quality Warning: {check['name']}",
                f"Value: {result['value']}, Threshold: {check['warning_threshold']}"
            )

    # Trigger backfills for fixable issues
    trigger_remediation(client, results, check_date)

    return {'status': 'completed', 'checks': len(results)}
```

#### 2.4 Deploy Cloud Scheduler

```bash
# Create scheduler job to run daily at 8 AM ET
gcloud scheduler jobs create pubsub data-quality-daily-check \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --topic=data-quality-check \
  --location=us-west2 \
  --message-body='{"action": "daily_check"}'
```

---

## Phase 3: Alerting Integration

### Goal
Route quality alerts through existing notification infrastructure.

### Tasks

#### 3.1 Add Quality Alert Channel

**File:** `shared/utils/notification_system.py` (extend)

```python
# Add new alert category
ALERT_CATEGORIES = {
    # ... existing categories
    'DATA_QUALITY': {
        'slack_channel': '#data-quality-alerts',
        'email_recipients': ['data-team@example.com'],
        'rate_limit': 5,  # per hour
    }
}

def notify_data_quality(severity: str, metric: str, details: str):
    """Send data quality alert through appropriate channels."""
    category = ALERT_CATEGORIES['DATA_QUALITY']

    message = f"[{severity}] Data Quality: {metric}\n{details}"

    if severity == 'CRITICAL':
        # Immediate notification
        send_slack(category['slack_channel'], message, urgent=True)
        send_email(category['email_recipients'], f"CRITICAL: {metric}", details)
    else:
        # Batched notification
        queue_alert(category, message)
```

#### 3.2 Create Alert Aggregation

Prevent alert fatigue by aggregating similar issues:

```python
class QualityAlertAggregator:
    """Aggregates similar quality alerts into digest."""

    def __init__(self):
        self.pending_alerts = {}

    def add_alert(self, metric: str, severity: str, details: dict):
        key = f"{metric}:{severity}"
        if key not in self.pending_alerts:
            self.pending_alerts[key] = []
        self.pending_alerts[key].append(details)

    def send_digest(self):
        """Send aggregated digest of pending alerts."""
        if not self.pending_alerts:
            return

        message = "Data Quality Alert Digest\n\n"
        for key, alerts in self.pending_alerts.items():
            metric, severity = key.split(':')
            message += f"**{metric}** ({severity}): {len(alerts)} issues\n"
            for alert in alerts[:3]:  # Show first 3
                message += f"  - {alert}\n"
            if len(alerts) > 3:
                message += f"  - ... and {len(alerts) - 3} more\n"

        send_slack('#data-quality-alerts', message)
        self.pending_alerts = {}
```

---

## Phase 4: Self-Healing Backfills

### Goal
Automatically fix known issues without manual intervention.

### Tasks

#### 4.1 Create Backfill Queue Table

**File:** `schemas/bigquery/orchestration/backfill_queue.sql`

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.backfill_queue (
    queue_id STRING NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    table_name STRING NOT NULL,
    game_date DATE NOT NULL,
    reason STRING NOT NULL,
    priority INT64 DEFAULT 0,  -- Higher = more urgent
    status STRING DEFAULT 'PENDING',  -- PENDING, RUNNING, COMPLETED, FAILED
    attempts INT64 DEFAULT 0,
    max_attempts INT64 DEFAULT 3,
    last_attempt_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY status, table_name;
```

#### 4.2 Create Backfill Worker

**File:** `orchestration/cloud_functions/backfill_worker/main.py`

```python
"""
Processes backfill queue entries.
Runs every 15 minutes, picks up PENDING items.
"""

import functions_framework
from google.cloud import bigquery
import subprocess
import logging

logger = logging.getLogger(__name__)

BACKFILL_COMMANDS = {
    'player_game_summary': (
        'python backfill_jobs/analytics/player_game_summary/'
        'player_game_summary_analytics_backfill.py --dates={date}'
    ),
    'player_composite_factors': (
        'python backfill_jobs/precompute/player_composite_factors/'
        'player_composite_factors_precompute_backfill.py --dates={date}'
    ),
    'ml_feature_store_v2': (
        'python backfill_jobs/precompute/ml_feature_store/'
        'ml_feature_store_precompute_backfill.py --dates={date}'
    ),
}

@functions_framework.cloud_event
def process_backfill_queue(cloud_event):
    """Process pending backfill items."""
    client = bigquery.Client()

    # Get pending items
    query = '''
        SELECT queue_id, table_name, game_date, attempts
        FROM `nba-props-platform.nba_orchestration.backfill_queue`
        WHERE status = 'PENDING' AND attempts < max_attempts
        ORDER BY priority DESC, created_at ASC
        LIMIT 5
    '''

    items = list(client.query(query).result())

    for item in items:
        execute_backfill(client, item)

    return {'processed': len(items)}


def execute_backfill(client: bigquery.Client, item: dict):
    """Execute single backfill and update status."""
    queue_id = item['queue_id']
    table_name = item['table_name']
    game_date = item['game_date'].strftime('%Y-%m-%d')

    # Mark as running
    update_status(client, queue_id, 'RUNNING')

    try:
        command = BACKFILL_COMMANDS[table_name].format(date=game_date)
        result = subprocess.run(
            command.split(),
            capture_output=True,
            timeout=600,  # 10 minute timeout
            cwd='/app'
        )

        if result.returncode == 0:
            update_status(client, queue_id, 'COMPLETED')
            logger.info(f"Backfill completed: {table_name} {game_date}")
        else:
            error = result.stderr.decode()[:500]
            update_status(client, queue_id, 'PENDING', error=error)
            logger.error(f"Backfill failed: {error}")

    except Exception as e:
        update_status(client, queue_id, 'PENDING', error=str(e))
        logger.error(f"Backfill exception: {e}")
```

#### 4.3 Create Queue Trigger Logic

Add to anomaly detection to queue backfills:

```python
def trigger_remediation(client: bigquery.Client, results: list, check_date: date):
    """Queue backfills for fixable issues."""

    for result in results:
        if result['status'] != 'CRITICAL':
            continue

        # Only queue if we know how to fix it
        if result['metric'] == 'pct_zero_points' and result['value'] > 30:
            queue_backfill(
                client,
                table_name='player_game_summary',
                game_date=check_date,
                reason=f"High zero-points rate: {result['value']}%"
            )

        elif result['metric'] == 'fatigue_avg' and result['value'] < 30:
            queue_backfill(
                client,
                table_name='player_composite_factors',
                game_date=check_date,
                reason=f"Low fatigue average: {result['value']}"
            )


def queue_backfill(client: bigquery.Client, table_name: str,
                   game_date: date, reason: str):
    """Add item to backfill queue."""

    # Check if already queued
    check_query = '''
        SELECT COUNT(*) as cnt
        FROM `nba-props-platform.nba_orchestration.backfill_queue`
        WHERE table_name = @table AND game_date = @date
        AND status IN ('PENDING', 'RUNNING')
    '''

    result = client.query(check_query, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('table', 'STRING', table_name),
            bigquery.ScalarQueryParameter('date', 'DATE', game_date),
        ]
    )).result()

    if list(result)[0]['cnt'] > 0:
        logger.info(f"Backfill already queued: {table_name} {game_date}")
        return

    # Insert to queue
    insert_query = '''
        INSERT INTO `nba-props-platform.nba_orchestration.backfill_queue`
        (queue_id, table_name, game_date, reason, priority)
        VALUES (GENERATE_UUID(), @table, @date, @reason, 1)
    '''

    client.query(insert_query, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('table', 'STRING', table_name),
            bigquery.ScalarQueryParameter('date', 'DATE', game_date),
            bigquery.ScalarQueryParameter('reason', 'STRING', reason),
        ]
    )).result()

    logger.info(f"Queued backfill: {table_name} {game_date} - {reason}")
    notify_warning(
        "Auto-Backfill Queued",
        f"Table: {table_name}\nDate: {game_date}\nReason: {reason}"
    )
```

---

## Deployment Checklist

### Phase 1 Deployment

- [ ] Create `shared/validation/pre_write_validator.py`
- [ ] Add business rules for player_game_summary
- [ ] Integrate with `analytics_base.py`
- [ ] Create validation_failures table
- [ ] Test with simulated DNP=0 records
- [ ] Deploy to Cloud Run (Phase 3 Analytics)

### Phase 2 Deployment

- [ ] Create data_quality_metrics table
- [ ] Create Cloud Function `data_quality_monitor`
- [ ] Deploy Cloud Scheduler job
- [ ] Verify metrics being written
- [ ] Monitor for 3 days before enabling alerts

### Phase 3 Deployment

- [ ] Add quality alert channel to Slack
- [ ] Extend notification_system.py
- [ ] Test alert routing
- [ ] Enable alert aggregation

### Phase 4 Deployment

- [ ] Create backfill_queue table
- [ ] Create Cloud Function `backfill_worker`
- [ ] Deploy Cloud Scheduler (15-minute interval)
- [ ] Test with manual queue entry
- [ ] Monitor for 1 week before enabling auto-queue

---

## Rollback Plan

If issues occur:

1. **Disable pre-write validation:** Set `ENABLE_PRE_WRITE_VALIDATION=false` env var
2. **Pause anomaly detection:** Disable Cloud Scheduler job
3. **Stop auto-backfills:** Set backfill_worker to skip execution
4. **Revert code:** `git revert` the validation commits

---

*Implementation Plan v1.0 - 2026-01-30*
