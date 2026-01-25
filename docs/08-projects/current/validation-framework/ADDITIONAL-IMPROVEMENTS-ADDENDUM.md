# Additional Improvements Addendum

**Created:** 2026-01-25
**Purpose:** Supplements MASTER-IMPROVEMENT-PLAN.md with additional items identified during review
**Status:** Ready for Implementation

---

## Overview

These items were identified during a comprehensive review of the validation framework and resilience improvements documentation. They complement the master plan and should be integrated into the implementation roadmap.

---

## Critical Bug (Add to Bugs Section)

### Bug #4: 7,061 Bare `except: pass` Statements

**Priority:** CRITICAL
**Status:** Undermines all error visibility
**Impact:** Errors silently swallowed throughout codebase, making debugging nearly impossible

**The Problem:**
```python
# Found 7,061 times across the codebase
try:
    risky_operation()
except:
    pass  # Error disappears silently - no logging, no alerting, nothing
```

**Why This Matters:**
- Root cause analysis becomes impossible
- Failures go undetected for hours/days
- All other monitoring improvements are undermined
- The 45-hour Firestore outage could have been detected faster with proper error logging

**The Fix:**
```python
# Replace with proper error handling
try:
    risky_operation()
except Exception as e:
    logger.warning(f"Operation failed: {e}", exc_info=True)
    # Optionally: sentry_sdk.capture_exception(e)
```

**Files to Audit (Priority Order):**
1. `/shared/utils/` - Core utilities used everywhere
2. `/orchestration/cloud_functions/` - All cloud functions
3. `/data_processors/` - All processors
4. `/predictions/` - Prediction pipeline
5. `/scrapers/` - Data collection

**Find Command:**
```bash
# Count instances
grep -rn "except:" --include="*.py" | grep -v "except.*:" | wc -l

# Find files with most instances
grep -rn "except:" --include="*.py" | grep -v "except.*:" | \
  cut -d: -f1 | sort | uniq -c | sort -rn | head -20
```

**Implementation Approach:**
- Phase 1: Fix `/shared/` and `/orchestration/` (highest impact)
- Phase 2: Fix `/data_processors/`
- Phase 3: Fix remaining files
- Add linting rule to prevent new instances

---

## P1 Additions

### P1.6: Streaming Buffer Auto-Retry

**Priority:** P1
**Effort:** Medium
**Goal:** Handle BigQuery streaming buffer conflicts gracefully

**The Problem:**

BigQuery has a 90-minute streaming buffer that prevents DELETE operations on recently-inserted data. This causes:
- 62.9% of games skipped during backfills
- Manual intervention required
- Data gaps persist longer than necessary

**The Solution:**

Add automatic retry with exponential backoff:

```python
# In bdl_boxscores_processor.py or processor_base.py

STREAMING_RETRY_DELAYS = [300, 600, 1200]  # 5, 10, 20 minutes

def process_with_streaming_retry(self, game_id: str, game_date: str):
    """Process with automatic retry for streaming buffer conflicts."""

    for attempt, delay in enumerate(STREAMING_RETRY_DELAYS):
        try:
            # Check for streaming buffer conflict before attempting
            if self._has_streaming_conflict(game_id, game_date):
                logger.info(
                    f"Streaming conflict for {game_id}, "
                    f"retry {attempt + 1}/{len(STREAMING_RETRY_DELAYS)} in {delay}s"
                )
                self._log_streaming_conflict(game_id, game_date, attempt)
                time.sleep(delay)
                continue

            return self._process_game(game_id, game_date)

        except StreamingBufferError as e:
            if attempt == len(STREAMING_RETRY_DELAYS) - 1:
                # Max retries exceeded, queue for later
                logger.warning(f"Max retries exceeded for {game_id}, queuing for later")
                self._queue_for_later_retry(game_id, game_date)
                raise

            logger.info(f"Streaming buffer error, retrying in {delay}s: {e}")
            time.sleep(delay)

    return None

def _has_streaming_conflict(self, game_id: str, game_date: str) -> bool:
    """Check if data is still in streaming buffer."""
    query = """
    SELECT COUNT(*) > 0 as in_buffer
    FROM `nba_raw.INFORMATION_SCHEMA.STREAMING_TIMELINE_BY_TABLE`
    WHERE table_name = 'bdl_player_boxscores'
    AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, MINUTE) < 90
    """
    # Simplified check - may need adjustment based on actual schema
    return False  # Implement actual check

def _log_streaming_conflict(self, game_id: str, game_date: str, attempt: int):
    """Log streaming conflict for monitoring."""
    self.bq_client.query("""
        INSERT INTO `nba_orchestration.streaming_conflict_log`
        (game_id, game_date, attempt, logged_at)
        VALUES (@game_id, @game_date, @attempt, CURRENT_TIMESTAMP())
    """, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("attempt", "INT64", attempt),
        ]
    ))
```

**Files to Modify:**
- `/scrapers/balldontlie/bdl_player_box_scores.py`
- `/data_processors/raw/processor_base.py`

**New Table:**
```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.streaming_conflict_log` (
    game_id STRING,
    game_date DATE,
    attempt INT64,
    logged_at TIMESTAMP,
    resolved_at TIMESTAMP
);
```

---

### P1.7: Pub/Sub Dead Letter Queues

**Priority:** P1
**Effort:** Low
**Goal:** Capture failed messages for investigation instead of losing them

**The Problem:**

10+ critical Pub/Sub topics have no Dead Letter Queues (DLQs). When message processing fails after max retries, messages are simply dropped with no record.

**Topics Needing DLQs:**

| Topic | Purpose | Priority |
|-------|---------|----------|
| `phase-transitions` | Orchestration triggers | Critical |
| `processor-completions` | Completion signals | Critical |
| `prediction-requests` | Prediction triggers | High |
| `grading-requests` | Grading triggers | High |
| `backfill-requests` | Backfill triggers | Medium |

**Setup Script:**

```bash
#!/bin/bash
# bin/orchestrators/setup_dead_letter_queues.sh

PROJECT_ID="nba-props-platform"

# Create DLQ topics and subscriptions
TOPICS=(
    "phase-transitions"
    "processor-completions"
    "prediction-requests"
    "grading-requests"
    "backfill-requests"
)

for TOPIC in "${TOPICS[@]}"; do
    DLQ_TOPIC="${TOPIC}-dlq"
    DLQ_SUB="${TOPIC}-dlq-sub"
    MAIN_SUB="${TOPIC}-sub"

    echo "Setting up DLQ for ${TOPIC}..."

    # Create DLQ topic
    gcloud pubsub topics create $DLQ_TOPIC 2>/dev/null || echo "Topic $DLQ_TOPIC exists"

    # Create DLQ subscription (retain messages for 7 days)
    gcloud pubsub subscriptions create $DLQ_SUB \
        --topic=$DLQ_TOPIC \
        --message-retention-duration=7d \
        --expiration-period=never \
        2>/dev/null || echo "Subscription $DLQ_SUB exists"

    # Update main subscription to use DLQ
    gcloud pubsub subscriptions update $MAIN_SUB \
        --dead-letter-topic=$DLQ_TOPIC \
        --max-delivery-attempts=5 \
        2>/dev/null || echo "Updated $MAIN_SUB"

    echo "✅ DLQ configured for ${TOPIC}"
done

echo ""
echo "✅ All DLQs configured"
echo ""
echo "To monitor DLQ messages:"
echo "  gcloud pubsub subscriptions pull phase-transitions-dlq-sub --limit=10"
```

**Monitoring Query:**
```sql
-- Check for messages in DLQs (requires Cloud Monitoring export)
-- Alternative: Use gcloud CLI or Cloud Console
```

**Files to Create:**
- `/bin/orchestrators/setup_dead_letter_queues.sh`

---

### P1.8: Late Prediction Detection

**Priority:** P1
**Effort:** Low
**Goal:** Flag predictions made after game start (invalid for betting)

**The Problem:**

Predictions made AFTER a game starts have no betting value but aren't flagged. This creates misleading accuracy metrics and masks timing issues.

**Implementation:**

Add to `prediction_accuracy_validator.py` or create new check:

```python
def _check_late_predictions(self, start_date: str, end_date: str):
    """Flag predictions made after game start time."""

    query = """
    SELECT
        p.game_date,
        p.player_name,
        p.game_id,
        p.created_at as prediction_time,
        s.game_time_et as game_start,
        TIMESTAMP_DIFF(p.created_at, s.game_time_et, MINUTE) as minutes_after_start
    FROM `nba_predictions.player_prop_predictions` p
    JOIN `nba_raw.v_nbac_schedule_latest` s
        ON p.game_id = s.game_id
    WHERE p.game_date BETWEEN @start_date AND @end_date
    AND p.created_at > s.game_time_et
    ORDER BY minutes_after_start DESC
    """

    late_predictions = self._run_query(query, {
        "start_date": start_date,
        "end_date": end_date
    })

    if late_predictions:
        self.results.append(ValidationResult(
            check_name="late_predictions",
            check_type="timing",
            layer="bigquery",
            passed=False,
            severity="error",
            message=f"Found {len(late_predictions)} predictions made after game start",
            affected_count=len(late_predictions),
            affected_items=[
                f"{p.game_date} {p.player_name}: {p.minutes_after_start} min late"
                for p in late_predictions[:10]
            ],
            remediation=[
                "# Investigate prediction timing pipeline",
                "# These predictions have no betting value",
                "# Consider voiding or flagging in grading"
            ]
        ))
    else:
        self.results.append(ValidationResult(
            check_name="late_predictions",
            check_type="timing",
            layer="bigquery",
            passed=True,
            severity="info",
            message="All predictions made before game start",
            affected_count=0
        ))
```

**Files to Modify:**
- `/validation/validators/grading/prediction_accuracy_validator.py`

---

## P2 Additions

### P2.7: Void Rate Anomaly Detection

**Priority:** P2
**Effort:** Low
**Goal:** Detect when void rates spike (indicates injury detection or data issues)

**Normal Void Rate:** 5-8%
**Alert Threshold:** >10%
**Critical Threshold:** >15%

```python
def _check_void_rate_anomaly(self, target_date: str):
    """Check if void rate is abnormally high."""

    query = """
    SELECT
        COUNTIF(is_voided) as voided_count,
        COUNT(*) as total_predictions,
        COUNTIF(is_voided) / COUNT(*) as void_rate
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = @target_date
    """

    result = self._run_query(query, {"target_date": target_date})

    if not result:
        return

    void_rate = result[0].void_rate or 0
    total = result[0].total_predictions
    voided = result[0].voided_count

    WARN_THRESHOLD = 0.10
    CRITICAL_THRESHOLD = 0.15

    if void_rate > CRITICAL_THRESHOLD:
        severity = "critical"
        message = f"CRITICAL: Void rate {void_rate:.1%} ({voided}/{total})"
    elif void_rate > WARN_THRESHOLD:
        severity = "warning"
        message = f"High void rate {void_rate:.1%} ({voided}/{total})"
    else:
        self.results.append(ValidationResult(
            check_name="void_rate",
            check_type="data_quality",
            passed=True,
            severity="info",
            message=f"Void rate normal: {void_rate:.1%}"
        ))
        return

    self.results.append(ValidationResult(
        check_name="void_rate_anomaly",
        check_type="data_quality",
        layer="bigquery",
        passed=False,
        severity=severity,
        message=message,
        affected_count=voided,
        remediation=[
            "# Investigate void reasons",
            "SELECT void_reason, COUNT(*) FROM predictions WHERE is_voided GROUP BY 1",
            "# Check injury report freshness",
            "# Check DNP detection accuracy"
        ]
    ))
```

---

### P2.8: Line Value Sanity Checks

**Priority:** P2
**Effort:** Low
**Goal:** Flag unreasonable betting line values

**Reasonable Bounds:**

| Prop Type | Min | Max |
|-----------|-----|-----|
| points | 0.5 | 60 |
| rebounds | 0.5 | 25 |
| assists | 0.5 | 20 |
| threes | 0.5 | 12 |
| steals | 0.5 | 6 |
| blocks | 0.5 | 8 |
| pts+reb+ast | 5 | 100 |

```python
LINE_BOUNDS = {
    "points": (0.5, 60),
    "rebounds": (0.5, 25),
    "assists": (0.5, 20),
    "threes": (0.5, 12),
    "steals": (0.5, 6),
    "blocks": (0.5, 8),
    "pts_reb_ast": (5, 100),
}

def _check_line_value_sanity(self, start_date: str, end_date: str):
    """Check for unreasonable line values."""

    insane_lines = []

    for prop_type, (min_val, max_val) in LINE_BOUNDS.items():
        query = f"""
        SELECT
            game_date,
            player_name,
            line_value,
            prop_type
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date BETWEEN @start_date AND @end_date
        AND prop_type = @prop_type
        AND (line_value < @min_val OR line_value > @max_val)
        LIMIT 100
        """

        results = self._run_query(query, {
            "start_date": start_date,
            "end_date": end_date,
            "prop_type": prop_type,
            "min_val": min_val,
            "max_val": max_val
        })

        insane_lines.extend(results)

    if insane_lines:
        self.results.append(ValidationResult(
            check_name="line_value_sanity",
            check_type="data_quality",
            layer="bigquery",
            passed=False,
            severity="error",
            message=f"Found {len(insane_lines)} lines outside reasonable bounds",
            affected_count=len(insane_lines),
            affected_items=[
                f"{l.game_date} {l.player_name}: {l.prop_type}={l.line_value}"
                for l in insane_lines[:10]
            ],
            remediation=["# Check odds API data quality", "# Verify line parsing logic"]
        ))
```

---

### P2.9: Cross-Field Validation

**Priority:** P2
**Effort:** Low
**Goal:** Detect logically impossible data combinations

**Constraints to Check:**

| Constraint | Description |
|------------|-------------|
| `fg_made <= fg_attempted` | Can't make more than attempted |
| `fg3_made <= fg3_attempted` | Can't make more 3s than attempted |
| `ft_made <= ft_attempted` | Can't make more FTs than attempted |
| `minutes >= 0 AND minutes <= 60` | Minutes in valid range |
| `points >= 0` | Points non-negative |
| `fg3_made <= fg_made` | 3-pointers are subset of field goals |

```python
FIELD_CONSTRAINTS = [
    {
        "name": "fg_made_vs_attempted",
        "condition": "fg_made > fg_attempted",
        "message": "FG made exceeds FG attempted"
    },
    {
        "name": "fg3_made_vs_attempted",
        "condition": "fg3_made > fg3_attempted",
        "message": "3PT made exceeds 3PT attempted"
    },
    {
        "name": "ft_made_vs_attempted",
        "condition": "ft_made > ft_attempted",
        "message": "FT made exceeds FT attempted"
    },
    {
        "name": "minutes_range",
        "condition": "minutes < 0 OR minutes > 60",
        "message": "Minutes outside valid range (0-60)"
    },
    {
        "name": "points_negative",
        "condition": "points < 0",
        "message": "Points is negative"
    },
]

def _check_field_constraints(self, table: str, start_date: str, end_date: str):
    """Validate cross-field logical constraints."""

    violations = []

    for constraint in FIELD_CONSTRAINTS:
        query = f"""
        SELECT
            game_date,
            player_name,
            '{constraint["name"]}' as violation_type
        FROM `{table}`
        WHERE game_date BETWEEN @start_date AND @end_date
        AND ({constraint["condition"]})
        LIMIT 50
        """

        results = self._run_query(query, {
            "start_date": start_date,
            "end_date": end_date
        })

        for r in results:
            violations.append(
                f"{r.game_date} {r.player_name}: {constraint['message']}"
            )

    if violations:
        self.results.append(ValidationResult(
            check_name="field_constraints",
            check_type="data_quality",
            layer="bigquery",
            passed=False,
            severity="error",
            message=f"Found {len(violations)} cross-field constraint violations",
            affected_count=len(violations),
            affected_items=violations[:10],
            remediation=["# Check data source for corruption", "# Verify parsing logic"]
        ))
```

---

### P2.10: Heartbeat Monitoring for Stuck Processors

**Priority:** P2
**Effort:** Medium
**Goal:** Detect processors that may be stuck/hanging

**Detection Logic:**
- Processor started > 30 minutes ago
- No completion or failure logged
- No recent heartbeat

```python
def _check_stuck_processors(self):
    """Detect processors that may be stuck."""

    query = """
    SELECT
        processor_name,
        game_date,
        status,
        started_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as running_minutes
    FROM `nba_orchestration.processor_runs`
    WHERE status = 'running'
    AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 30
    ORDER BY started_at ASC
    """

    stuck_processors = self._run_query(query)

    if stuck_processors:
        self.results.append(ValidationResult(
            check_name="stuck_processors",
            check_type="health",
            layer="bigquery",
            passed=False,
            severity="warning",
            message=f"Found {len(stuck_processors)} potentially stuck processors",
            affected_count=len(stuck_processors),
            affected_items=[
                f"{p.processor_name} ({p.game_date}): running {p.running_minutes} min"
                for p in stuck_processors
            ],
            remediation=[
                "# Check Cloud Function logs for errors",
                "gcloud functions logs read <processor_name> --limit 50",
                "# Consider manually marking as failed and retrying"
            ]
        ))
```

**Heartbeat Table (optional for detailed tracking):**
```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.processor_heartbeats` (
    processor_name STRING,
    run_id STRING,
    heartbeat_at TIMESTAMP,
    records_processed INT64,
    status STRING
);
```

---

### P2.11: Batch Processors to Sentry

**Priority:** P2
**Effort:** Low
**Goal:** Capture batch processor errors in Sentry for tracking

**The Problem:**

Cloud Functions have Sentry integration, but batch processors (run via cron or manually) don't report errors to Sentry.

**Implementation:**

Add to processor base class:

```python
# In processor_base.py

import sentry_sdk
import os

class ProcessorBase:
    def __init__(self):
        # Initialize Sentry for batch processors
        if os.environ.get("SENTRY_DSN"):
            sentry_sdk.init(
                dsn=os.environ.get("SENTRY_DSN"),
                environment=os.environ.get("ENVIRONMENT", "development"),
                traces_sample_rate=0.1,
                # Tag with processor name for filtering
                release=f"processor-{self.__class__.__name__}"
            )

    def process(self, *args, **kwargs):
        """Process with Sentry error tracking."""
        with sentry_sdk.start_transaction(
            op="processor",
            name=self.__class__.__name__
        ) as transaction:
            try:
                sentry_sdk.set_tag("processor", self.__class__.__name__)
                return self._process_impl(*args, **kwargs)
            except Exception as e:
                sentry_sdk.capture_exception(e)
                raise
```

**Files to Modify:**
- `/data_processors/raw/processor_base.py`
- `/data_processors/analytics/analytics_base.py`
- `/data_processors/precompute/precompute_base.py`

---

## Operational Safety

### Gate Override Strategy

**Purpose:** Emergency bypass when gates block legitimate processing

**Environment Variable Override:**
```bash
# Use sparingly - logs audit trail
GATE_OVERRIDE=true python orchestration/phase4_to_phase5.py --date 2026-01-25
```

**Implementation:**
```python
class PhaseGate:
    def evaluate(self, target_date: str) -> GateResult:
        # Check for override
        if os.environ.get("GATE_OVERRIDE", "").lower() == "true":
            logger.warning(f"GATE OVERRIDE active for {target_date}")
            sentry_sdk.capture_message(
                f"Gate override used for {target_date}",
                level="warning"
            )
            self._log_override(target_date)
            return GateResult(
                decision=GateDecision.WARN_AND_PROCEED,
                blocking_reasons=["MANUAL OVERRIDE ACTIVE"],
                warnings=["Processing despite gate failure"],
                metrics={}
            )

        # Normal evaluation
        return self._evaluate_checks(target_date)

    def _log_override(self, target_date: str):
        """Log override for audit trail."""
        self.bq_client.query("""
            INSERT INTO `nba_orchestration.gate_overrides`
            (gate_name, target_date, overridden_at, overridden_by)
            VALUES (@gate, @date, CURRENT_TIMESTAMP(), @user)
        """, job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("gate", "STRING", self.__class__.__name__),
                bigquery.ScalarQueryParameter("date", "DATE", target_date),
                bigquery.ScalarQueryParameter("user", "STRING", os.environ.get("USER", "unknown")),
            ]
        ))
```

**Override Audit Table:**
```sql
CREATE TABLE IF NOT EXISTS `nba_orchestration.gate_overrides` (
    gate_name STRING,
    target_date DATE,
    overridden_at TIMESTAMP,
    overridden_by STRING,
    reason STRING
);
```

---

### Testing Strategy for Validators

**Unit Tests:**
```python
# tests/validation/test_phase4_to_phase5_gate.py

import pytest
from unittest.mock import Mock, patch
from validation.validators.gates.phase4_to_phase5_gate import Phase4ToPhase5Gate, GateDecision

class TestPhase4ToPhase5Gate:

    @pytest.fixture
    def gate(self):
        with patch('google.cloud.bigquery.Client'):
            return Phase4ToPhase5Gate()

    def test_blocks_on_low_quality(self, gate):
        """Gate should block when feature quality is below threshold."""
        with patch.object(gate, '_run_query') as mock_query:
            mock_query.return_value = [Mock(avg_quality=60.0)]

            result = gate.evaluate("2026-01-25")

            assert result.decision == GateDecision.BLOCK
            assert "quality" in result.blocking_reasons[0].lower()

    def test_proceeds_on_good_quality(self, gate):
        """Gate should proceed when all checks pass."""
        with patch.object(gate, '_run_query') as mock_query:
            mock_query.side_effect = [
                [Mock(avg_quality=78.0)],   # quality check - pass
                [Mock(coverage=0.95)],       # player count - pass
                [Mock(staleness_hours=2)],   # freshness - pass
                []                           # no null issues
            ]

            result = gate.evaluate("2026-01-25")

            assert result.decision == GateDecision.PROCEED
            assert len(result.blocking_reasons) == 0

    def test_warns_on_marginal_quality(self, gate):
        """Gate should warn but proceed on marginal quality."""
        # Implement based on your warning thresholds
        pass
```

**Integration Test (Read-Only):**
```bash
# Test against real data without making changes
python -m pytest tests/validation/integration/ \
    --date 2026-01-24 \
    --readonly \
    -v
```

**Dry-Run Mode:**
```python
# Add to all gates and validators
def evaluate(self, target_date: str, dry_run: bool = False) -> GateResult:
    result = self._evaluate_checks(target_date)

    if dry_run:
        logger.info(f"DRY RUN: Gate would return {result.decision.value}")
        logger.info(f"DRY RUN: Reasons: {result.blocking_reasons}")
        # Don't actually block in dry run
        return GateResult(
            decision=GateDecision.PROCEED,
            blocking_reasons=result.blocking_reasons,
            warnings=[f"DRY RUN - would have been: {result.decision.value}"],
            metrics=result.metrics
        )

    return result
```

---

## Updated Priority Matrix

| # | Item | Priority | Effort | Status |
|---|------|----------|--------|--------|
| Bug #4 | Bare except:pass (7,061) | CRITICAL | High | New |
| P1.6 | Streaming buffer retry | P1 | Medium | New |
| P1.7 | Pub/Sub DLQs | P1 | Low | New |
| P1.8 | Late prediction detection | P1 | Low | New |
| P2.7 | Void rate monitoring | P2 | Low | New |
| P2.8 | Line value sanity | P2 | Low | New |
| P2.9 | Cross-field validation | P2 | Low | New |
| P2.10 | Heartbeat monitoring | P2 | Medium | New |
| P2.11 | Batch processors to Sentry | P2 | Low | New |
| — | Gate override strategy | — | Low | New |
| — | Testing strategy | — | Medium | New |

---

## Integration with Master Plan

These items should be added to the master plan:

1. **Bug #4** → Add to "Critical Bugs" section after Bug #3
2. **P1.6, P1.7, P1.8** → Add to "P1 Improvements" section
3. **P2.7-P2.11** → Add to "P2 Improvements" section
4. **Gate Override Strategy** → Add as new section or appendix
5. **Testing Strategy** → Add as new section or appendix

Update the dependency graph:
```
Bug #4 (bare except) → Enables better debugging of all other issues
P1.7 (DLQs) → Enables debugging of Pub/Sub issues in P1.4
P2.10 (Heartbeat) → Enhances P0.1 (gate) with better stuck detection
```

---

**Document Version:** 1.0
**Last Updated:** 2026-01-25
**Companion To:** MASTER-IMPROVEMENT-PLAN.md
