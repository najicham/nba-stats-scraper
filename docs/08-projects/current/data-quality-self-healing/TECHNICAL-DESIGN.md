# Technical Design - Data Quality Self-Healing

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           DATA QUALITY SYSTEM                                   │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │  Analytics  │───▶│  Pre-Write  │───▶│  BigQuery   │───▶│  Downstream │     │
│  │  Processor  │    │  Validator  │    │   Write     │    │   Systems   │     │
│  └─────────────┘    └──────┬──────┘    └─────────────┘    └─────────────┘     │
│                            │                                                    │
│                    ┌───────▼───────┐                                           │
│                    │  Validation   │                                           │
│                    │   Failures    │                                           │
│                    │    Table      │                                           │
│                    └───────────────┘                                           │
│                                                                                 │
│  ═══════════════════════════════════════════════════════════════════════════  │
│                                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Cloud     │───▶│   Quality   │───▶│   Alert     │───▶│   Slack/    │     │
│  │  Scheduler  │    │   Checker   │    │   Router    │    │   Email     │     │
│  └─────────────┘    └──────┬──────┘    └─────────────┘    └─────────────┘     │
│                            │                                                    │
│                    ┌───────▼───────┐                                           │
│                    │    Quality    │                                           │
│                    │    Metrics    │                                           │
│                    │    Table      │                                           │
│                    └───────┬───────┘                                           │
│                            │                                                    │
│                    ┌───────▼───────┐    ┌─────────────┐                        │
│                    │   Backfill    │───▶│   Backfill  │                        │
│                    │    Queue      │    │   Worker    │                        │
│                    └───────────────┘    └─────────────┘                        │
│                                                                                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schemas

### 1. Validation Failures Table

Captures records blocked by pre-write validation.

```sql
-- File: schemas/bigquery/orchestration/validation_failures.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.validation_failures` (
    -- Identity
    failure_id STRING NOT NULL OPTIONS(description="Unique failure ID"),
    failure_timestamp TIMESTAMP NOT NULL OPTIONS(description="When validation failed"),

    -- Context
    table_name STRING NOT NULL OPTIONS(description="Target table name"),
    processor_name STRING OPTIONS(description="Processor class name"),
    game_date DATE OPTIONS(description="Game date if applicable"),
    player_lookup STRING OPTIONS(description="Player lookup if applicable"),
    game_id STRING OPTIONS(description="Game ID if applicable"),

    -- Failure details
    violations ARRAY<STRING> NOT NULL OPTIONS(description="List of rule violations"),
    record_json STRING OPTIONS(description="Full record as JSON for debugging"),

    -- Metadata
    session_id STRING OPTIONS(description="Processing session ID"),
    environment STRING DEFAULT 'production' OPTIONS(description="Environment: production, staging, dev")
)
PARTITION BY DATE(failure_timestamp)
CLUSTER BY table_name, game_date
OPTIONS(
    description="Records blocked by pre-write validation",
    labels=[("team", "data-quality"), ("retention", "90-days")]
);

-- Index for common queries
-- Note: BigQuery doesn't support explicit indexes, but clustering helps
```

### 2. Data Quality Metrics Table

Stores daily quality measurements for trend analysis.

```sql
-- File: schemas/bigquery/orchestration/data_quality_metrics.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.data_quality_metrics` (
    -- Identity
    metric_id STRING NOT NULL OPTIONS(description="Unique metric ID"),
    metric_date DATE NOT NULL OPTIONS(description="Date of measurement"),

    -- Metric definition
    table_name STRING NOT NULL OPTIONS(description="Source table being measured"),
    metric_name STRING NOT NULL OPTIONS(description="Metric identifier"),
    metric_value FLOAT64 NOT NULL OPTIONS(description="Measured value"),

    -- Thresholds
    threshold_warning FLOAT64 OPTIONS(description="Warning threshold"),
    threshold_critical FLOAT64 OPTIONS(description="Critical threshold"),

    -- Status
    status STRING NOT NULL OPTIONS(description="OK, WARNING, or CRITICAL"),
    direction STRING OPTIONS(description="above, below, or outside_range"),

    -- Context
    details STRING OPTIONS(description="Additional context or debug info"),
    query_duration_ms INT64 OPTIONS(description="How long the check took"),

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    check_run_id STRING OPTIONS(description="Batch ID for this check run")
)
PARTITION BY metric_date
CLUSTER BY table_name, metric_name
OPTIONS(
    description="Daily data quality metrics and thresholds",
    labels=[("team", "data-quality"), ("retention", "365-days")]
);
```

### 3. Backfill Queue Table

Manages automated remediation tasks.

```sql
-- File: schemas/bigquery/orchestration/backfill_queue.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.backfill_queue` (
    -- Identity
    queue_id STRING NOT NULL OPTIONS(description="Unique queue entry ID"),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

    -- Target
    table_name STRING NOT NULL OPTIONS(description="Table to backfill"),
    game_date DATE NOT NULL OPTIONS(description="Date to backfill"),

    -- Reason
    reason STRING NOT NULL OPTIONS(description="Why backfill was triggered"),
    triggered_by STRING OPTIONS(description="auto, manual, or incident"),
    quality_metric STRING OPTIONS(description="Metric that triggered this"),
    quality_value FLOAT64 OPTIONS(description="Value that triggered this"),

    -- Scheduling
    priority INT64 DEFAULT 0 OPTIONS(description="Higher = more urgent"),
    scheduled_for TIMESTAMP OPTIONS(description="Don't run before this time"),

    -- Execution
    status STRING DEFAULT 'PENDING' OPTIONS(description="PENDING, RUNNING, COMPLETED, FAILED, CANCELLED"),
    attempts INT64 DEFAULT 0 OPTIONS(description="Number of attempts"),
    max_attempts INT64 DEFAULT 3 OPTIONS(description="Max retry attempts"),
    last_attempt_at TIMESTAMP OPTIONS(description="When last attempted"),
    completed_at TIMESTAMP OPTIONS(description="When completed successfully"),

    -- Results
    error_message STRING OPTIONS(description="Error if failed"),
    records_processed INT64 OPTIONS(description="Records affected"),
    duration_seconds INT64 OPTIONS(description="How long it took"),

    -- Metadata
    worker_id STRING OPTIONS(description="Which worker processed this")
)
PARTITION BY DATE(created_at)
CLUSTER BY status, table_name
OPTIONS(
    description="Queue of automated backfill tasks",
    labels=[("team", "data-quality"), ("retention", "90-days")]
);
```

---

## Business Rules Reference

### player_game_summary Rules

| Rule | Condition | Error | Rationale |
|------|-----------|-------|-----------|
| `dnp_null_points` | is_dnp=True → points=NULL | DNP players must have NULL points | Prevents 0s corrupting averages |
| `dnp_null_minutes` | is_dnp=True → minutes=NULL | DNP players must have NULL minutes | Same as above |
| `dnp_null_rebounds` | is_dnp=True → rebounds=NULL | DNP players must have NULL rebounds | Same as above |
| `dnp_null_assists` | is_dnp=True → assists=NULL | DNP players must have NULL assists | Same as above |
| `active_non_negative` | is_dnp=False → points>=0 | Active players cannot have negative stats | Data integrity |
| `active_has_minutes` | is_dnp=False → minutes IS NOT NULL | Active players must have minutes | Completeness check |
| `required_player_lookup` | player_lookup IS NOT NULL | player_lookup is required | Primary key |
| `required_game_date` | game_date IS NOT NULL | game_date is required | Primary key |
| `required_game_id` | game_id IS NOT NULL | game_id is required | Primary key |

### player_composite_factors Rules

| Rule | Condition | Error | Rationale |
|------|-----------|-------|-----------|
| `fatigue_score_range` | 0 <= fatigue_score <= 100 | Must be 0-100 | Known valid range |
| `matchup_score_range` | -50 <= score <= 50 | Must be -50 to 50 | Known valid range |
| `pace_score_range` | 80 <= pace <= 120 | Must be 80-120 | Typical NBA pace range |

### ml_feature_store_v2 Rules

| Rule | Condition | Error | Rationale |
|------|-----------|-------|-----------|
| `feature_count` | len(features) == 34 | Must have 34 features | Model expects exact count |
| `no_nan_features` | No NaN in features | Features cannot be NaN | Model will fail |
| `no_inf_features` | No Inf in features | Features cannot be Inf | Model will fail |

---

## Quality Metrics Reference

### Daily Checks

| Metric | Table | Query | Warning | Critical |
|--------|-------|-------|---------|----------|
| `pct_zero_points` | player_game_summary | `COUNTIF(points=0)/COUNT(*)` | >15% | >30% |
| `pct_dnp_marked` | player_game_summary | `COUNTIF(is_dnp=TRUE)/COUNT(*)` | <5% | =0% |
| `avg_points` | player_game_summary | `AVG(points)` | <8 or >18 | <5 or >22 |
| `record_count` | player_game_summary | `COUNT(*)` | <200 | <100 |
| `fatigue_avg` | player_composite_factors | `AVG(fatigue_score)` | <50 or >95 | <30 or >99 |
| `feature_completeness` | ml_feature_store_v2 | `COUNTIF(features IS NOT NULL)/COUNT(*)` | <95% | <90% |

### Statistical Checks

| Metric | Description | Alert Condition |
|--------|-------------|-----------------|
| `points_stddev` | Std dev of points | >2 sigma from 7-day rolling |
| `minutes_distribution` | Minutes distribution shift | KL divergence > threshold |
| `dnp_rate_change` | Day-over-day DNP rate change | >10% absolute change |

---

## API Contracts

### Pre-Write Validator

```python
class PreWriteValidator:
    """
    Validates records against business rules before BigQuery write.

    Usage:
        validator = PreWriteValidator('player_game_summary')
        valid, invalid = validator.validate(records)
        # Write only valid records
        write_to_bigquery(valid)
        # Log invalid for debugging
        log_validation_failures(invalid)
    """

    def __init__(self, table_name: str):
        """Initialize with target table name."""

    def validate(self, records: List[dict]) -> Tuple[List[dict], List[dict]]:
        """
        Validate records, returning (valid_records, invalid_records).

        Args:
            records: List of record dicts to validate

        Returns:
            Tuple of (valid_records, invalid_records)
            Invalid records include 'violations' key with list of errors
        """

    def add_rule(self, rule: ValidationRule) -> None:
        """Add custom rule at runtime."""

    def disable_rule(self, rule_name: str) -> None:
        """Disable a rule by name (for testing/migration)."""
```

### Quality Monitor

```python
class DataQualityMonitor:
    """
    Runs quality checks and manages alerting/remediation.

    Usage:
        monitor = DataQualityMonitor()
        results = monitor.run_daily_checks(date.today() - timedelta(days=1))
        monitor.process_results(results)  # Alerts + queues backfills
    """

    def __init__(self, client: bigquery.Client = None):
        """Initialize with optional BigQuery client."""

    def run_daily_checks(self, check_date: date) -> List[QualityCheckResult]:
        """
        Run all configured quality checks for a date.

        Returns list of QualityCheckResult with metric, value, status.
        """

    def process_results(self, results: List[QualityCheckResult]) -> None:
        """
        Process check results: log metrics, send alerts, queue backfills.
        """

    def add_check(self, check: QualityCheck) -> None:
        """Add custom quality check."""
```

### Backfill Queue Manager

```python
class BackfillQueueManager:
    """
    Manages the backfill queue for automated remediation.

    Usage:
        manager = BackfillQueueManager()
        manager.queue_backfill('player_game_summary', date(2026, 1, 22), 'High zero rate')
        pending = manager.get_pending()
        manager.execute_backfill(pending[0])
    """

    def queue_backfill(self, table_name: str, game_date: date,
                       reason: str, priority: int = 0) -> str:
        """
        Add backfill to queue. Returns queue_id.
        Skips if already queued for same table/date.
        """

    def get_pending(self, limit: int = 10) -> List[QueueItem]:
        """Get pending backfill items, ordered by priority."""

    def execute_backfill(self, item: QueueItem) -> bool:
        """
        Execute backfill for queue item.
        Updates status and returns success/failure.
        """

    def cancel_backfill(self, queue_id: str, reason: str) -> None:
        """Cancel a pending backfill."""
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_PRE_WRITE_VALIDATION` | `true` | Enable/disable pre-write validation |
| `VALIDATION_MODE` | `block` | `block` (reject invalid) or `warn` (log only) |
| `QUALITY_CHECK_ENABLED` | `true` | Enable/disable daily quality checks |
| `AUTO_BACKFILL_ENABLED` | `false` | Enable/disable automatic backfill triggering |
| `QUALITY_ALERT_CHANNEL` | `#data-quality` | Slack channel for alerts |
| `BACKFILL_WORKER_CONCURRENCY` | `1` | Max concurrent backfills |

---

## Monitoring & Observability

### Cloud Monitoring Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `validation/records_validated` | Counter | table, status | Records validated |
| `validation/records_blocked` | Counter | table, rule | Records blocked by rule |
| `quality/check_status` | Gauge | metric, table | 0=OK, 1=WARNING, 2=CRITICAL |
| `backfill/queue_depth` | Gauge | table | Pending backfills per table |
| `backfill/execution_time` | Distribution | table | Backfill duration |

### Log Queries

```sql
-- Find validation failures for a date
SELECT failure_timestamp, player_lookup, violations
FROM `nba_orchestration.validation_failures`
WHERE game_date = '2026-01-22'
ORDER BY failure_timestamp DESC;

-- Quality metric trends
SELECT metric_date, metric_name, metric_value, status
FROM `nba_orchestration.data_quality_metrics`
WHERE table_name = 'player_game_summary'
  AND metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY metric_date, metric_name;

-- Backfill queue status
SELECT table_name, status, COUNT(*) as count
FROM `nba_orchestration.backfill_queue`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2;
```

---

## Testing Strategy

### Unit Tests

```python
# tests/validation/test_pre_write_validator.py

def test_dnp_with_zero_points_blocked():
    """DNP players with points=0 should be blocked."""
    validator = PreWriteValidator('player_game_summary')

    record = {
        'player_lookup': 'test_player',
        'game_date': '2026-01-22',
        'is_dnp': True,
        'points': 0,  # Should be NULL
    }

    valid, invalid = validator.validate([record])

    assert len(valid) == 0
    assert len(invalid) == 1
    assert 'dnp_null_points' in str(invalid[0]['violations'])


def test_dnp_with_null_points_allowed():
    """DNP players with points=NULL should pass."""
    validator = PreWriteValidator('player_game_summary')

    record = {
        'player_lookup': 'test_player',
        'game_date': '2026-01-22',
        'is_dnp': True,
        'points': None,  # Correct
    }

    valid, invalid = validator.validate([record])

    assert len(valid) == 1
    assert len(invalid) == 0
```

### Integration Tests

```python
# tests/integration/test_quality_pipeline.py

def test_quality_check_detects_high_zero_rate():
    """Quality check should detect abnormally high zero-point rate."""
    monitor = DataQualityMonitor()

    # Inject test data with 50% zeros
    inject_test_data('player_game_summary', {'pct_zero': 0.50})

    results = monitor.run_daily_checks(date.today())

    zero_check = next(r for r in results if r.metric == 'pct_zero_points')
    assert zero_check.status == 'CRITICAL'
    assert zero_check.value == 50.0
```

---

*Technical Design v1.0 - 2026-01-30*
