# Comprehensive Validation & Resilience Improvements Guide

**Created:** 2026-01-25
**Purpose:** Complete reference for improving daily orchestration validation
**Audience:** Future Claude sessions or developers implementing these improvements

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [Recommended Improvements](#3-recommended-improvements)
4. [Implementation Details](#4-implementation-details)
5. [Files to Study](#5-files-to-study)
6. [Implementation Patterns](#6-implementation-patterns)
7. [Success Criteria](#7-success-criteria)
8. [Quick Start Guide](#8-quick-start-guide)

---

## 1. Executive Summary

### The Core Problem

The NBA stats pipeline has mature validation capabilities (26 validators, 25 validation angles) but suffers from:

1. **Reactive validation** - Finds problems after they cascade through the pipeline
2. **Missing gates** - Bad data flows downstream without blocking
3. **Silent degradation** - Quality drops aren't detected until severe
4. **Manual recovery** - Most fixes require human intervention
5. **Scheduling gaps** - Validators exist but aren't running at optimal times

### The Solution

Shift from **reactive detection** to **proactive prevention**:

- Add validation gates between phases
- Monitor quality trends, not just thresholds
- Automate post-recovery validation
- Schedule validators at strategic times
- Add cross-phase consistency checks

### Impact of Recent Outage (Lesson Learned)

A 45-hour Firestore permission failure caused:
```
Firestore 403 → Master Controller blocked (45h)
    → No Phase 2 processors triggered
    → No new boxscores collected
    → Rolling window calculations stale
    → Feature quality drops (78→64)
    → Players filtered out (282→85 predictions)
    → Grading has nothing to grade
```

**Key insight:** Count-based validation showed "data exists" while quality was severely degraded.

---

## 2. Current State Analysis

### What Exists

| Component | Count | Location |
|-----------|-------|----------|
| Validators | 26 | `/validation/validators/` |
| YAML Configs | 41 | `/validation/configs/` |
| Validation Scripts | 11 | `/bin/validation/` |
| Validation Angles | 25 | Documented in framework |

### What's Working Well

- **Base validator framework** - Extensible, config-driven, multi-layer
- **Remediation generation** - Auto-generates backfill commands
- **Result persistence** - Stores to BigQuery for analysis
- **Notification integration** - Slack/email alerts

### What's Missing

| Gap | Impact | Priority |
|-----|--------|----------|
| Phase transition gates | Bad data flows downstream | P0 |
| Quality trend monitoring | Silent degradation undetected | P0 |
| Cross-phase consistency | Orphan data accumulates | P0 |
| Validation scheduling | Validators don't run at key times | P1 |
| Post-backfill validation | No verification fixes worked | P1 |
| Real-time validation | Hours to detect live issues | P2 |
| Recovery validation | Manual verification after outages | P1 |

---

## 3. Recommended Improvements

### P0 - Critical (Implement First)

#### 3.1 Phase 4→5 Gating Validator

**Problem:** Predictions run on incomplete/degraded feature data.

**Solution:** Create a validator that BLOCKS Phase 5 if:
- Feature quality score < 70 average
- Player count < 80% of expected
- Rolling window freshness > 48 hours stale
- Critical features have NULL rates > 5%

**Files to create:**
- `/validation/validators/gates/phase4_to_phase5_gate.py`
- `/validation/configs/gates/phase4_to_phase5_gate.yaml`

**Integration point:**
- Modify `/orchestration/cloud_functions/phase4_to_phase5/main.py` to call gate before processing

---

#### 3.2 Quality Trend Monitoring

**Problem:** Quality degrades gradually without alerts until severe.

**Solution:** Compare current metrics against rolling baselines:
- 7-day rolling average for feature quality
- Alert when quality drops >10% from baseline
- Track quality score distribution shifts

**Files to create:**
- `/validation/validators/trends/quality_trend_validator.py`
- `/bin/validation/quality_trend_monitor.py`

**Query pattern:**
```sql
WITH baseline AS (
  SELECT AVG(feature_quality_score) as avg_quality
  FROM `nba_precompute.ml_feature_store`
  WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 14 DAY)
    AND DATE_SUB(@target_date, INTERVAL 7 DAY)
),
current AS (
  SELECT AVG(feature_quality_score) as avg_quality
  FROM `nba_precompute.ml_feature_store`
  WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 7 DAY)
    AND @target_date
)
SELECT
  current.avg_quality,
  baseline.avg_quality,
  (baseline.avg_quality - current.avg_quality) / baseline.avg_quality * 100 as pct_drop
FROM current, baseline
```

---

#### 3.3 Cross-Phase Consistency Validator

**Problem:** No validation that data flows correctly across all phases.

**Solution:** Trace entity counts through phases and flag mismatches:
- Games in schedule → boxscores → analytics → features → predictions
- Players in boxscores → analytics → features → predictions
- Flag "orphan" records (predictions without features, analytics without boxscores)

**Files to create:**
- `/validation/validators/consistency/cross_phase_validator.py`
- `/validation/configs/consistency/cross_phase.yaml`
- `/bin/validation/cross_phase_consistency.py`

**Key checks:**
```python
CROSS_PHASE_CHECKS = [
    {
        "name": "games_phase2_to_phase3",
        "source_table": "nba_raw.nbac_player_boxscore",
        "target_table": "nba_analytics.player_game_summary",
        "join_field": "game_id",
        "date_field": "game_date",
        "expected_match_rate": 0.98
    },
    {
        "name": "players_phase3_to_phase4",
        "source_table": "nba_analytics.player_game_summary",
        "target_table": "nba_precompute.ml_feature_store",
        "join_field": "player_lookup",
        "date_field": "game_date",
        "expected_match_rate": 0.95
    },
    {
        "name": "players_phase4_to_phase5",
        "source_table": "nba_precompute.ml_feature_store",
        "target_table": "nba_predictions.player_prop_predictions",
        "join_field": "player_lookup",
        "date_field": "game_date",
        "expected_match_rate": 0.90
    }
]
```

---

### P1 - High Priority (Implement Second)

#### 3.4 Validation Scheduling System

**Problem:** Validators exist but don't run at optimal times.

**Solution:** Create Cloud Scheduler jobs for key validation windows:

| Time (ET) | Validator | Purpose |
|-----------|-----------|---------|
| 6:00 AM | `daily_data_completeness.py` | Morning reconciliation |
| 3:00 PM | `workflow_health.py` | Pre-game health check |
| 11:00 PM | `comprehensive_health_check.py` | Post-game validation |
| Every 30 min (4pm-1am) | `phase_transition_health.py` | Live monitoring |

**Files to create:**
- `/bin/orchestrators/deploy_validation_schedulers.sh`
- `/orchestration/cloud_functions/validation_scheduler/main.py`

**Scheduler configuration:**
```yaml
validation_schedules:
  morning_reconciliation:
    schedule: "0 6 * * *"
    timezone: "America/New_York"
    script: "daily_data_completeness.py"
    args: "--days 3"

  pre_game_health:
    schedule: "0 15 * * *"
    timezone: "America/New_York"
    script: "workflow_health.py"
    args: "--hours 24"

  post_game_validation:
    schedule: "0 23 * * *"
    timezone: "America/New_York"
    script: "comprehensive_health_check.py"
    args: "--date $(date +%Y-%m-%d)"

  live_monitoring:
    schedule: "*/30 16-24 * * *"
    timezone: "America/New_York"
    script: "phase_transition_health.py"
    args: "--hours 2"
```

---

#### 3.5 Post-Backfill Validator

**Problem:** After running backfills, no automated check verifies the fix worked.

**Solution:** Create a validator that runs after any backfill and verifies:
- Gap is now filled
- Data quality is at expected levels
- Downstream phases were reprocessed

**Files to create:**
- `/validation/validators/recovery/post_backfill_validator.py`
- `/bin/validation/validate_backfill.py`

**Usage pattern:**
```bash
# After running a backfill:
python bin/backfill/bdl_boxscores.py --date 2026-01-24

# Automatically run validation:
python bin/validation/validate_backfill.py \
  --phase raw \
  --table nbac_player_boxscore \
  --date 2026-01-24
```

**Integration:** Modify backfill scripts to call validation automatically on completion.

---

#### 3.6 Recovery Validation Framework

**Problem:** After outages, manual verification is needed to confirm recovery.

**Solution:** Create a "recovery validation" mode that:
- Compares pre-outage baseline to post-recovery state
- Verifies all phases recovered
- Generates recovery report

**Files to create:**
- `/validation/validators/recovery/outage_recovery_validator.py`
- `/bin/validation/validate_recovery.py`

**Usage:**
```bash
python bin/validation/validate_recovery.py \
  --outage-start "2026-01-23 04:20" \
  --outage-end "2026-01-25 01:35" \
  --baseline-date "2026-01-22"
```

---

### P2 - Medium Priority (Implement Third)

#### 3.7 Real-Time Validation Hooks

**Problem:** Batch validation runs periodically; issues aren't caught until next run.

**Solution:** Add lightweight validation in data ingestion Cloud Functions:
- Check boxscore arrival within 30 min of game end
- Validate record counts match expectations
- Alert immediately on anomalies

**Files to modify:**
- `/orchestration/cloud_functions/phase2_to_phase3/main.py`
- Add validation hooks in processor base classes

**Pattern:**
```python
class ProcessorWithValidation(ProcessorBase):
    def process(self, data):
        # Pre-validation
        if not self._validate_input(data):
            self._alert("Input validation failed")
            return

        # Process
        result = super().process(data)

        # Post-validation
        if not self._validate_output(result):
            self._alert("Output validation failed")

        return result
```

---

#### 3.8 Validation Analytics Dashboard

**Problem:** Validation results stored but not analyzed for trends.

**Solution:** Create queries/views for validation analytics:
- Pass rate by validator over time
- Most common failure types
- Time to detection metrics
- Remediation effectiveness

**Files to create:**
- `/schemas/bigquery/orchestration/v_validation_analytics.sql`
- `/bin/validation/validation_analytics.py`

**Key metrics:**
```sql
-- Validation pass rate trend
SELECT
  DATE(run_timestamp) as run_date,
  validator_name,
  COUNT(CASE WHEN passed THEN 1 END) / COUNT(*) as pass_rate
FROM `nba_orchestration.validation_results`
GROUP BY 1, 2
ORDER BY 1 DESC;

-- Mean time to detection
SELECT
  check_type,
  AVG(TIMESTAMP_DIFF(detected_at, issue_started_at, MINUTE)) as avg_mtd_minutes
FROM `nba_orchestration.validation_detections`
GROUP BY 1;
```

---

#### 3.9 Config Drift in CI/CD

**Problem:** Config drift detected reactively, not during deployment.

**Solution:** Add config validation to deployment pipeline:
- Run `detect_config_drift.py` pre-deployment
- Block deployment if critical drift detected
- Store config snapshots on each deployment

**Files to modify:**
- `/bin/orchestrators/deploy_*.sh` - Add validation step
- `/.github/workflows/` - Add CI check

**Pattern:**
```bash
# In deploy script:
echo "Checking for config drift..."
python bin/validation/detect_config_drift.py --strict
if [ $? -ne 0 ]; then
    echo "ERROR: Config drift detected. Fix before deploying."
    exit 1
fi
```

---

#### 3.10 Duplicate/Idempotency Validation

**Problem:** No idempotency keys; duplicate processing possible and undetected.

**Solution:** Add duplicate detection as standard base validator check:
- Check for duplicate business keys
- Detect same data written multiple times
- Flag processing that ran multiple times for same inputs

**Files to modify:**
- `/validation/base_validator.py` - Add `_check_duplicates()` method

**Pattern:**
```python
def _check_duplicates(self, table: str, key_fields: List[str], date_field: str):
    """Check for duplicate records based on business key."""
    query = f"""
    SELECT {', '.join(key_fields)}, COUNT(*) as cnt
    FROM `{table}`
    WHERE {date_field} BETWEEN @start_date AND @end_date
    GROUP BY {', '.join(key_fields)}
    HAVING COUNT(*) > 1
    """
    duplicates = self._run_query(query)
    if duplicates:
        self._add_result(ValidationResult(
            check_name="duplicate_detection",
            check_type="data_quality",
            passed=False,
            severity="error",
            message=f"Found {len(duplicates)} duplicate records",
            affected_count=len(duplicates),
            affected_items=duplicates[:10]
        ))
```

---

### P3 - Lower Priority (Future Improvements)

#### 3.11 Chaos Testing Framework

**Problem:** Unknown how pipeline behaves under failure conditions.

**Solution:** Create controlled failure injection tests:
- Simulate Firestore failures
- Simulate BigQuery timeouts
- Simulate missing data scenarios
- Measure time to detection

**Files to create:**
- `/tests/chaos/` directory
- `/tests/chaos/test_firestore_failure.py`
- `/tests/chaos/test_bigquery_timeout.py`

---

#### 3.12 Predictive Alerting

**Problem:** Alerts fire when problems exist, not before they become critical.

**Solution:** Use ML to predict issues:
- Detect degradation patterns that precede failures
- Alert on anomalous processing times
- Predict coverage gaps based on schedule

---

## 4. Implementation Details

### 4.1 Phase Gate Implementation

Create the base gate class:

```python
# /validation/validators/gates/base_gate.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class GateDecision(Enum):
    PROCEED = "proceed"
    BLOCK = "block"
    WARN_AND_PROCEED = "warn_and_proceed"

@dataclass
class GateResult:
    decision: GateDecision
    checks_passed: int
    checks_failed: int
    blocking_reasons: List[str]
    warnings: List[str]
    metrics: dict

class PhaseGate(ABC):
    """Base class for phase transition gates."""

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.bq_client = bigquery.Client()

    @abstractmethod
    def evaluate(self, target_date: str) -> GateResult:
        """Evaluate whether processing should proceed."""
        pass

    def should_block(self, target_date: str) -> bool:
        """Quick check if gate blocks processing."""
        result = self.evaluate(target_date)
        return result.decision == GateDecision.BLOCK

    def _check_quality_threshold(self, table: str, quality_field: str,
                                  threshold: float, target_date: str) -> bool:
        """Check if quality metric meets threshold."""
        query = f"""
        SELECT AVG({quality_field}) as avg_quality
        FROM `{table}`
        WHERE game_date = @target_date
        """
        result = self._run_query(query, {"target_date": target_date})
        return result[0].avg_quality >= threshold if result else False

    def _check_completeness(self, source_table: str, target_table: str,
                            join_field: str, target_date: str,
                            threshold: float = 0.80) -> bool:
        """Check if target has sufficient coverage of source."""
        query = f"""
        WITH source AS (
            SELECT DISTINCT {join_field} FROM `{source_table}`
            WHERE game_date = @target_date
        ),
        target AS (
            SELECT DISTINCT {join_field} FROM `{target_table}`
            WHERE game_date = @target_date
        )
        SELECT
            COUNT(target.{join_field}) / COUNT(source.{join_field}) as coverage
        FROM source
        LEFT JOIN target USING ({join_field})
        """
        result = self._run_query(query, {"target_date": target_date})
        return result[0].coverage >= threshold if result else False
```

### 4.2 Phase 4→5 Gate Implementation

```python
# /validation/validators/gates/phase4_to_phase5_gate.py

from .base_gate import PhaseGate, GateResult, GateDecision

class Phase4ToPhase5Gate(PhaseGate):
    """Gate that validates feature quality before predictions run."""

    QUALITY_THRESHOLD = 70.0
    PLAYER_COUNT_THRESHOLD = 0.80
    MAX_NULL_RATE = 0.05
    MAX_STALENESS_HOURS = 48

    def evaluate(self, target_date: str) -> GateResult:
        blocking_reasons = []
        warnings = []
        metrics = {}

        # Check 1: Feature quality score
        quality_check = self._check_feature_quality(target_date)
        metrics["avg_quality"] = quality_check["avg_quality"]
        if not quality_check["passed"]:
            blocking_reasons.append(
                f"Feature quality {quality_check['avg_quality']:.1f} "
                f"below threshold {self.QUALITY_THRESHOLD}"
            )

        # Check 2: Player count
        player_check = self._check_player_count(target_date)
        metrics["player_coverage"] = player_check["coverage"]
        if not player_check["passed"]:
            blocking_reasons.append(
                f"Player coverage {player_check['coverage']:.1%} "
                f"below threshold {self.PLAYER_COUNT_THRESHOLD:.0%}"
            )

        # Check 3: Rolling window freshness
        freshness_check = self._check_rolling_window_freshness(target_date)
        metrics["staleness_hours"] = freshness_check["staleness_hours"]
        if not freshness_check["passed"]:
            blocking_reasons.append(
                f"Rolling window {freshness_check['staleness_hours']:.1f}h stale, "
                f"max allowed {self.MAX_STALENESS_HOURS}h"
            )

        # Check 4: Critical field NULL rates
        null_check = self._check_critical_nulls(target_date)
        metrics["null_rates"] = null_check["null_rates"]
        if not null_check["passed"]:
            blocking_reasons.append(
                f"Critical fields have high NULL rates: {null_check['problem_fields']}"
            )

        # Determine decision
        if blocking_reasons:
            decision = GateDecision.BLOCK
        elif warnings:
            decision = GateDecision.WARN_AND_PROCEED
        else:
            decision = GateDecision.PROCEED

        return GateResult(
            decision=decision,
            checks_passed=4 - len(blocking_reasons),
            checks_failed=len(blocking_reasons),
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            metrics=metrics
        )

    def _check_feature_quality(self, target_date: str) -> dict:
        query = """
        SELECT AVG(feature_quality_score) as avg_quality
        FROM `nba_precompute.ml_feature_store`
        WHERE game_date = @target_date
        """
        result = self._run_query(query, {"target_date": target_date})
        avg_quality = result[0].avg_quality if result else 0
        return {
            "passed": avg_quality >= self.QUALITY_THRESHOLD,
            "avg_quality": avg_quality
        }

    def _check_player_count(self, target_date: str) -> dict:
        query = """
        WITH expected AS (
            SELECT COUNT(DISTINCT player_lookup) as cnt
            FROM `nba_analytics.player_game_summary`
            WHERE game_date = @target_date
        ),
        actual AS (
            SELECT COUNT(DISTINCT player_lookup) as cnt
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date = @target_date
        )
        SELECT actual.cnt / expected.cnt as coverage
        FROM expected, actual
        """
        result = self._run_query(query, {"target_date": target_date})
        coverage = result[0].coverage if result else 0
        return {
            "passed": coverage >= self.PLAYER_COUNT_THRESHOLD,
            "coverage": coverage
        }

    def _check_rolling_window_freshness(self, target_date: str) -> dict:
        query = """
        SELECT
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as staleness_hours
        FROM `nba_precompute.ml_feature_store`
        WHERE game_date = @target_date
        """
        result = self._run_query(query, {"target_date": target_date})
        staleness = result[0].staleness_hours if result else 999
        return {
            "passed": staleness <= self.MAX_STALENESS_HOURS,
            "staleness_hours": staleness
        }

    def _check_critical_nulls(self, target_date: str) -> dict:
        critical_fields = [
            "points_rolling_avg", "minutes_rolling_avg",
            "usage_rate_rolling_avg", "opponent_def_rating"
        ]
        null_rates = {}
        problem_fields = []

        for field in critical_fields:
            query = f"""
            SELECT
                COUNTIF({field} IS NULL) / COUNT(*) as null_rate
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date = @target_date
            """
            result = self._run_query(query, {"target_date": target_date})
            null_rate = result[0].null_rate if result else 1.0
            null_rates[field] = null_rate
            if null_rate > self.MAX_NULL_RATE:
                problem_fields.append(f"{field}={null_rate:.1%}")

        return {
            "passed": len(problem_fields) == 0,
            "null_rates": null_rates,
            "problem_fields": problem_fields
        }
```

### 4.3 Cross-Phase Consistency Check

```python
# /validation/validators/consistency/cross_phase_validator.py

from validation.base_validator import BaseValidator, ValidationResult

class CrossPhaseValidator(BaseValidator):
    """Validates data consistency across pipeline phases."""

    PHASE_MAPPINGS = [
        {
            "name": "schedule_to_boxscores",
            "source": {
                "table": "nba_raw.v_nbac_schedule_latest",
                "field": "game_id",
                "filter": "game_status = 'Final'"
            },
            "target": {
                "table": "nba_raw.nbac_player_boxscore",
                "field": "game_id"
            },
            "expected_rate": 0.98,
            "severity": "error"
        },
        {
            "name": "boxscores_to_analytics",
            "source": {
                "table": "nba_raw.nbac_player_boxscore",
                "field": "player_lookup",
                "group_by": "game_date"
            },
            "target": {
                "table": "nba_analytics.player_game_summary",
                "field": "player_lookup"
            },
            "expected_rate": 0.95,
            "severity": "error"
        },
        {
            "name": "analytics_to_features",
            "source": {
                "table": "nba_analytics.player_game_summary",
                "field": "player_lookup"
            },
            "target": {
                "table": "nba_precompute.ml_feature_store",
                "field": "player_lookup"
            },
            "expected_rate": 0.90,
            "severity": "warning"
        },
        {
            "name": "features_to_predictions",
            "source": {
                "table": "nba_precompute.ml_feature_store",
                "field": "player_lookup",
                "filter": "is_production_ready = TRUE"
            },
            "target": {
                "table": "nba_predictions.player_prop_predictions",
                "field": "player_lookup"
            },
            "expected_rate": 0.85,
            "severity": "warning"
        }
    ]

    def _run_custom_validations(self, start_date: str, end_date: str,
                                 season_year: Optional[int] = None):
        """Run cross-phase consistency checks."""

        for mapping in self.PHASE_MAPPINGS:
            self._check_phase_consistency(mapping, start_date, end_date)

        # Check for orphan records
        self._check_orphan_predictions(start_date, end_date)
        self._check_orphan_analytics(start_date, end_date)

    def _check_phase_consistency(self, mapping: dict, start_date: str, end_date: str):
        """Check that records flow from source to target phase."""
        source = mapping["source"]
        target = mapping["target"]

        source_filter = source.get("filter", "1=1")

        query = f"""
        WITH source_records AS (
            SELECT DISTINCT {source['field']}, game_date
            FROM `{source['table']}`
            WHERE game_date BETWEEN @start_date AND @end_date
            AND {source_filter}
        ),
        target_records AS (
            SELECT DISTINCT {target['field']}, game_date
            FROM `{target['table']}`
            WHERE game_date BETWEEN @start_date AND @end_date
        ),
        comparison AS (
            SELECT
                s.game_date,
                COUNT(DISTINCT s.{source['field']}) as source_count,
                COUNT(DISTINCT t.{target['field']}) as target_count
            FROM source_records s
            LEFT JOIN target_records t
                ON s.{source['field']} = t.{target['field']}
                AND s.game_date = t.game_date
            GROUP BY s.game_date
        )
        SELECT
            game_date,
            source_count,
            target_count,
            target_count / source_count as match_rate
        FROM comparison
        WHERE target_count / source_count < @expected_rate
        ORDER BY game_date
        """

        params = {
            "start_date": start_date,
            "end_date": end_date,
            "expected_rate": mapping["expected_rate"]
        }

        mismatches = self._run_query(query, params)

        if mismatches:
            self.results.append(ValidationResult(
                check_name=f"cross_phase_{mapping['name']}",
                check_type="consistency",
                layer="bigquery",
                passed=False,
                severity=mapping["severity"],
                message=f"Phase consistency below {mapping['expected_rate']:.0%} threshold",
                affected_count=len(mismatches),
                affected_items=[
                    f"{r.game_date}: {r.target_count}/{r.source_count} ({r.match_rate:.1%})"
                    for r in mismatches[:5]
                ],
                remediation=[
                    f"# Reprocess {mapping['name'].split('_to_')[1]} for affected dates",
                    f"python bin/backfill/{mapping['name'].split('_to_')[1]}.py "
                    f"--start-date {mismatches[0].game_date} --end-date {mismatches[-1].game_date}"
                ]
            ))
        else:
            self.results.append(ValidationResult(
                check_name=f"cross_phase_{mapping['name']}",
                check_type="consistency",
                layer="bigquery",
                passed=True,
                severity="info",
                message=f"Phase consistency above {mapping['expected_rate']:.0%} threshold",
                affected_count=0
            ))

    def _check_orphan_predictions(self, start_date: str, end_date: str):
        """Find predictions without corresponding features."""
        query = """
        SELECT
            p.game_date,
            p.player_lookup,
            p.player_name
        FROM `nba_predictions.player_prop_predictions` p
        LEFT JOIN `nba_precompute.ml_feature_store` f
            ON p.player_lookup = f.player_lookup
            AND p.game_date = f.game_date
        WHERE p.game_date BETWEEN @start_date AND @end_date
        AND f.player_lookup IS NULL
        """
        orphans = self._run_query(query, {
            "start_date": start_date,
            "end_date": end_date
        })

        if orphans:
            self.results.append(ValidationResult(
                check_name="orphan_predictions",
                check_type="consistency",
                layer="bigquery",
                passed=False,
                severity="warning",
                message="Found predictions without feature records",
                affected_count=len(orphans),
                affected_items=[f"{o.game_date}: {o.player_name}" for o in orphans[:10]]
            ))
```

---

## 5. Files to Study

### Understanding Current Validation System

| File | Purpose | Study For |
|------|---------|-----------|
| `/validation/base_validator.py` | Core validation framework | Understanding patterns, extending |
| `/validation/validators/precompute/ml_feature_store_validator.py` | Feature validation | Quality checks pattern |
| `/validation/validators/grading/prediction_accuracy_validator.py` | Prediction validation | Complex multi-check pattern |
| `/validation/configs/precompute/ml_feature_store.yaml` | YAML config pattern | Configuration approach |

### Understanding Orchestration

| File | Purpose | Study For |
|------|---------|-----------|
| `/orchestration/master_controller.py` | Pipeline orchestrator | Integration points |
| `/orchestration/cloud_functions/phase4_to_phase5/main.py` | Phase transition | Where to add gates |
| `/shared/config/orchestration_config.py` | Config management | Configuration patterns |

### Understanding Current Issues

| File | Purpose | Study For |
|------|---------|-----------|
| `/docs/08-projects/current/validation-framework/VALIDATION-FRAMEWORK-COMPREHENSIVE.md` | Full framework doc | Current capabilities |
| `/docs/08-projects/current/pipeline-resilience-improvements/RESILIENCE-IMPROVEMENTS-JAN25.md` | Resilience status | Known gaps |
| `/docs/08-projects/current/pipeline-resilience-improvements/MASTER-TODO-JAN25.md` | Implementation status | What's done/pending |

### Understanding Data Flow

| File | Purpose | Study For |
|------|---------|-----------|
| `/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature generation | What Phase 4 produces |
| `/predictions/coordinator/coordinator.py` | Prediction coordinator | What Phase 5 consumes |
| `/predictions/coordinator/player_loader.py` | Player loading | Filtering logic |

### Key Queries to Run

```bash
# Understand validation result history
bq query --use_legacy_sql=false '
SELECT validator_name, DATE(run_timestamp) as run_date,
       COUNTIF(passed) / COUNT(*) as pass_rate
FROM `nba_orchestration.validation_results`
WHERE run_timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1, 2 DESC'

# Understand phase data volumes
bq query --use_legacy_sql=false '
SELECT
  "boxscores" as phase, COUNT(*) as records
FROM `nba_raw.nbac_player_boxscore` WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT "analytics", COUNT(*)
FROM `nba_analytics.player_game_summary` WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT "features", COUNT(*)
FROM `nba_precompute.ml_feature_store` WHERE game_date = CURRENT_DATE()
UNION ALL
SELECT "predictions", COUNT(*)
FROM `nba_predictions.player_prop_predictions` WHERE game_date = CURRENT_DATE()'

# Check feature quality distribution
bq query --use_legacy_sql=false '
SELECT
  game_date,
  AVG(feature_quality_score) as avg_quality,
  MIN(feature_quality_score) as min_quality,
  MAX(feature_quality_score) as max_quality,
  COUNTIF(feature_quality_score >= 75) as high_quality_count
FROM `nba_precompute.ml_feature_store`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC'
```

---

## 6. Implementation Patterns

### Pattern 1: Adding a New Validator

```bash
# 1. Create config file
touch /validation/configs/{layer}/{validator_name}.yaml

# 2. Create validator class
touch /validation/validators/{layer}/{validator_name}_validator.py

# 3. Create CLI script (optional)
touch /bin/validation/{validator_name}.py

# 4. Test locally
python -m validation.validators.{layer}.{validator_name}_validator \
  --start-date 2026-01-20 --end-date 2026-01-25
```

### Pattern 2: Adding a Phase Gate

```python
# 1. In the phase transition cloud function main.py:

from validation.validators.gates.phase_gate import PhaseGate

def process_phase_transition(request):
    target_date = extract_date(request)

    # Add gate check
    gate = Phase4ToPhase5Gate()
    gate_result = gate.evaluate(target_date)

    if gate_result.decision == GateDecision.BLOCK:
        logger.warning(f"Gate blocked processing: {gate_result.blocking_reasons}")
        return {"status": "blocked", "reasons": gate_result.blocking_reasons}

    # Proceed with normal processing
    return process_normally(request)
```

### Pattern 3: Scheduling a Validator

```bash
# Create Cloud Scheduler job
gcloud scheduler jobs create http validation-morning-check \
  --location=us-central1 \
  --schedule="0 6 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-central1-{PROJECT}.cloudfunctions.net/validation-runner" \
  --http-method=POST \
  --message-body='{"validator": "daily_data_completeness", "args": "--days 3"}'
```

### Pattern 4: Adding Trend Detection

```python
# In any validator, add baseline comparison:

def _check_with_baseline(self, metric_name: str, current_value: float,
                          lookback_days: int = 7):
    """Compare current metric against historical baseline."""
    query = f"""
    SELECT AVG({metric_name}) as baseline
    FROM `{self.table}`
    WHERE game_date BETWEEN
        DATE_SUB(@target_date, INTERVAL {lookback_days + 7} DAY)
        AND DATE_SUB(@target_date, INTERVAL 7 DAY)
    """
    baseline = self._run_query(query)[0].baseline

    pct_change = (baseline - current_value) / baseline * 100

    if pct_change > 10:  # More than 10% degradation
        self.results.append(ValidationResult(
            check_name=f"{metric_name}_trend",
            check_type="trend",
            passed=False,
            severity="warning",
            message=f"{metric_name} degraded {pct_change:.1f}% from baseline"
        ))
```

---

## 7. Success Criteria

### P0 Improvements Complete When:

- [ ] Phase 4→5 gate blocks predictions when feature quality < 70
- [ ] Cross-phase validator detects >5% entity drop between phases
- [ ] Quality trend monitoring alerts on >10% degradation from baseline
- [ ] All three run in CI or scheduled jobs

### P1 Improvements Complete When:

- [ ] Validators run at scheduled times (morning, pre-game, post-game)
- [ ] Post-backfill validation runs automatically after any backfill
- [ ] Recovery validation can verify pipeline health after outages

### P2 Improvements Complete When:

- [ ] Real-time validation hooks in Phase 2 cloud functions
- [ ] Validation analytics dashboard shows trends
- [ ] Config drift blocks deployments in CI

### Overall Success Metrics:

| Metric | Current | Target |
|--------|---------|--------|
| Time to detect issues | 4+ hours | < 30 minutes |
| False positive rate | Unknown | < 5% |
| Manual intervention needed | 100% | < 20% |
| Validation coverage | ~60% | > 95% |

---

## 8. Quick Start Guide

### For a New Session Implementing These Improvements:

```bash
# 1. Understand current state
cat docs/08-projects/current/validation-framework/VALIDATION-FRAMEWORK-COMPREHENSIVE.md
cat docs/08-projects/current/pipeline-resilience-improvements/MASTER-TODO-JAN25.md

# 2. Check what validators exist
ls -la validation/validators/

# 3. Read the base validator
cat validation/base_validator.py | head -200

# 4. Check recent validation results
bq query --use_legacy_sql=false '
SELECT * FROM `nba_orchestration.validation_runs`
ORDER BY run_timestamp DESC LIMIT 10'

# 5. Start with P0 item: Phase 4→5 gate
# Create the gate following patterns in Section 4
```

### Recommended Implementation Order:

1. **Day 1:** Implement Phase 4→5 gate (Section 4.2)
2. **Day 2:** Implement cross-phase validator (Section 4.3)
3. **Day 3:** Add quality trend monitoring to existing validators
4. **Day 4:** Set up validation scheduling
5. **Day 5:** Implement post-backfill validation

### Key Commands:

```bash
# Run existing validation
python bin/validation/comprehensive_health_check.py --date 2026-01-25

# Check validation results
python bin/validation/daily_pipeline_doctor.py --days 3 --show-fixes

# Test new validator locally
python -m validation.validators.gates.phase4_to_phase5_gate --date 2026-01-25

# Deploy to Cloud Functions
./bin/orchestrators/deploy_phase4_to_phase5.sh
```

---

## Appendix: Files Created/Modified Summary

### New Files to Create:

```
/validation/validators/gates/
├── __init__.py
├── base_gate.py
└── phase4_to_phase5_gate.py

/validation/validators/consistency/
├── __init__.py
└── cross_phase_validator.py

/validation/validators/trends/
├── __init__.py
└── quality_trend_validator.py

/validation/validators/recovery/
├── __init__.py
├── post_backfill_validator.py
└── outage_recovery_validator.py

/validation/configs/gates/
└── phase4_to_phase5_gate.yaml

/validation/configs/consistency/
└── cross_phase.yaml

/bin/validation/
├── cross_phase_consistency.py
├── quality_trend_monitor.py
├── validate_backfill.py
└── validate_recovery.py

/bin/orchestrators/
└── deploy_validation_schedulers.sh
```

### Files to Modify:

```
/orchestration/cloud_functions/phase4_to_phase5/main.py  # Add gate check
/validation/base_validator.py  # Add duplicate detection method
/bin/orchestrators/deploy_*.sh  # Add config drift check
```

---

## 9. Additional Critical Fixes (From Resilience Audit)

The following items were identified in the resilience improvements audit and should be addressed alongside or after the validation improvements above.

### 9.1 Silent Failure Epidemic: 7,061 Bare `except: pass` Statements

**Problem:** The codebase has 7,061 instances of bare `except: pass` patterns that silently swallow errors, making debugging nearly impossible.

**Impact:** Errors go undetected, failures aren't logged, root cause analysis is blocked.

**Solution:**
```bash
# Find all instances
grep -rn "except:" --include="*.py" | grep -v "except.*:" | wc -l

# Replace pattern with proper logging
# Before:
try:
    risky_operation()
except:
    pass

# After:
try:
    risky_operation()
except Exception as e:
    logger.warning(f"Operation failed: {e}", exc_info=True)
```

**Priority:** P0 - This affects all error visibility

**Files to audit:**
- `/shared/` - Core utilities
- `/orchestration/` - Cloud functions
- `/data_processors/` - All processors
- `/predictions/` - Prediction pipeline

---

### 9.2 Streaming Buffer Retry Logic

**Problem:** BigQuery's 90-minute streaming buffer prevents DELETE operations, causing 62.9% of games to be skipped during backfills.

**Solution:** Add automatic retry with exponential backoff for streaming conflicts:

```python
# In bdl_boxscores_processor.py

STREAMING_RETRY_DELAYS = [300, 600, 1200]  # 5, 10, 20 minutes

def process_with_streaming_retry(self, game_id: str, game_date: str):
    for attempt, delay in enumerate(STREAMING_RETRY_DELAYS):
        try:
            # Check for streaming buffer conflict
            if self._has_streaming_conflict(game_id, game_date):
                logger.info(f"Streaming conflict for {game_id}, retry in {delay}s")
                self._log_streaming_conflict(game_id, game_date, attempt)
                time.sleep(delay)
                continue

            return self._process_game(game_id, game_date)
        except StreamingBufferError:
            if attempt == len(STREAMING_RETRY_DELAYS) - 1:
                self._queue_for_later_retry(game_id, game_date)
                raise

    return None
```

**Files to modify:**
- `/scrapers/balldontlie/bdl_player_box_scores.py`
- `/data_processors/raw/processor_base.py`

---

### 9.3 Dead Letter Queues for Pub/Sub Topics

**Problem:** 10+ critical Pub/Sub topics have no DLQs, so failed messages disappear silently.

**Solution:** Configure DLQs for critical topics:

```bash
# Create DLQ topic
gcloud pubsub topics create phase-transitions-dlq

# Create DLQ subscription
gcloud pubsub subscriptions create phase-transitions-dlq-sub \
  --topic=phase-transitions-dlq \
  --message-retention-duration=7d

# Update main subscription to use DLQ
gcloud pubsub subscriptions update phase-transitions-sub \
  --dead-letter-topic=phase-transitions-dlq \
  --max-delivery-attempts=5
```

**Topics needing DLQs:**
- `phase-transitions`
- `processor-completions`
- `prediction-requests`
- `grading-requests`
- `backfill-requests`

---

### 9.4 Prediction Timing Validation

**Problem:** Predictions made AFTER game start time are invalid for betting but aren't flagged.

**Solution:** Add timing validation check:

```python
# In prediction_accuracy_validator.py

def _check_prediction_timing(self, start_date: str, end_date: str):
    """Flag predictions made after game start."""
    query = """
    SELECT
        p.game_date,
        p.player_name,
        p.created_at as prediction_time,
        s.game_time_et as game_start,
        TIMESTAMP_DIFF(p.created_at, s.game_time_et, MINUTE) as minutes_after_start
    FROM `nba_predictions.player_prop_predictions` p
    JOIN `nba_raw.v_nbac_schedule_latest` s
        ON p.game_id = s.game_id
    WHERE p.game_date BETWEEN @start_date AND @end_date
    AND p.created_at > s.game_time_et
    """
    late_predictions = self._run_query(query, {
        "start_date": start_date,
        "end_date": end_date
    })

    if late_predictions:
        self.results.append(ValidationResult(
            check_name="late_predictions",
            check_type="timing",
            passed=False,
            severity="error",
            message=f"Found {len(late_predictions)} predictions made after game start",
            affected_count=len(late_predictions),
            affected_items=[
                f"{p.game_date} {p.player_name}: {p.minutes_after_start}min late"
                for p in late_predictions[:10]
            ]
        ))
```

---

### 9.5 Void Rate Anomaly Detection

**Problem:** High void rates indicate injury detection or data issues but aren't monitored.

**Solution:** Alert when void rate exceeds threshold:

```python
def _check_void_rate_anomaly(self, target_date: str):
    """Check if void rate is abnormally high."""
    query = """
    SELECT
        COUNTIF(is_voided) / COUNT(*) as void_rate,
        COUNT(*) as total_predictions
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = @target_date
    """
    result = self._run_query(query, {"target_date": target_date})

    void_rate = result[0].void_rate if result else 0
    VOID_THRESHOLD = 0.10  # 10% max expected

    if void_rate > VOID_THRESHOLD:
        self.results.append(ValidationResult(
            check_name="void_rate_anomaly",
            check_type="data_quality",
            passed=False,
            severity="warning",
            message=f"Void rate {void_rate:.1%} exceeds {VOID_THRESHOLD:.0%} threshold",
            affected_count=int(result[0].total_predictions * void_rate)
        ))
```

---

### 9.6 Line Value Sanity Checks

**Problem:** Unreasonable betting line values (e.g., 500 points) slip through without validation.

**Solution:** Add bounds checking:

```python
LINE_BOUNDS = {
    "points": (0.5, 60),
    "rebounds": (0.5, 25),
    "assists": (0.5, 20),
    "threes": (0.5, 12),
    "steals": (0.5, 6),
    "blocks": (0.5, 8),
}

def _check_line_value_sanity(self, start_date: str, end_date: str):
    """Check for unreasonable line values."""
    insane_lines = []

    for prop_type, (min_val, max_val) in LINE_BOUNDS.items():
        query = f"""
        SELECT game_date, player_name, line_value, prop_type
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date BETWEEN @start_date AND @end_date
        AND prop_type = @prop_type
        AND (line_value < @min_val OR line_value > @max_val)
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
            passed=False,
            severity="error",
            message=f"Found {len(insane_lines)} lines outside reasonable bounds"
        ))
```

---

### 9.7 Cross-Field Validation

**Problem:** Logical inconsistencies like `FG_MAKES > FG_ATTEMPTS` go undetected.

**Solution:** Add cross-field consistency checks:

```python
FIELD_CONSTRAINTS = [
    ("fg_made", "<=", "fg_attempted", "FG made cannot exceed attempted"),
    ("fg3_made", "<=", "fg3_attempted", "3PT made cannot exceed attempted"),
    ("ft_made", "<=", "ft_attempted", "FT made cannot exceed attempted"),
    ("minutes", "<=", 60, "Minutes cannot exceed 60"),
    ("points", ">=", 0, "Points cannot be negative"),
]

def _check_field_constraints(self, table: str, start_date: str, end_date: str):
    """Validate cross-field logical constraints."""
    violations = []

    for field1, operator, field2, message in FIELD_CONSTRAINTS:
        if isinstance(field2, str):
            condition = f"{field1} {operator} {field2}"
            where = f"NOT ({condition})"
        else:
            where = f"NOT ({field1} {operator} {field2})"

        query = f"""
        SELECT game_date, player_name, {field1},
               {field2 if isinstance(field2, str) else f"'{field2}' as threshold"}
        FROM `{table}`
        WHERE game_date BETWEEN @start_date AND @end_date
        AND {where}
        """
        results = self._run_query(query, {
            "start_date": start_date,
            "end_date": end_date
        })

        for r in results:
            violations.append(f"{r.game_date} {r.player_name}: {message}")

    if violations:
        self.results.append(ValidationResult(
            check_name="field_constraints",
            check_type="data_quality",
            passed=False,
            severity="error",
            message=f"Found {len(violations)} cross-field constraint violations",
            affected_items=violations[:10]
        ))
```

---

### 9.8 Heartbeat Monitoring for Stuck Processors

**Problem:** Processors can hang without detection for 4+ hours.

**Solution:** Add heartbeat checks:

```python
# In workflow_health.py

def _check_processor_heartbeats(self):
    """Detect processors that may be stuck."""
    query = """
    SELECT
        processor_name,
        status,
        started_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as running_minutes
    FROM `nba_orchestration.processor_runs`
    WHERE status = 'running'
    AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 30
    """
    stuck_processors = self._run_query(query)

    if stuck_processors:
        for proc in stuck_processors:
            logger.warning(
                f"Potentially stuck processor: {proc.processor_name} "
                f"running for {proc.running_minutes} minutes"
            )
```

---

### 9.9 Batch Processors to Sentry

**Problem:** Batch processors don't report to Sentry, so errors go untracked.

**Solution:** Add Sentry integration to processor base:

```python
# In processor_base.py

import sentry_sdk

class ProcessorBase:
    def __init__(self):
        sentry_sdk.init(
            dsn=os.environ.get("SENTRY_DSN"),
            environment=os.environ.get("ENVIRONMENT", "development"),
            traces_sample_rate=0.1
        )

    def process(self, *args, **kwargs):
        with sentry_sdk.start_transaction(
            op="processor",
            name=self.__class__.__name__
        ):
            try:
                return self._process(*args, **kwargs)
            except Exception as e:
                sentry_sdk.capture_exception(e)
                raise
```

---

## 10. Gate Override Strategy

**Important:** When implementing phase gates, include override mechanisms for emergencies.

### Override Patterns

```python
class Phase4ToPhase5Gate(PhaseGate):
    def evaluate(self, target_date: str, force_proceed: bool = False) -> GateResult:
        # Allow manual override with logging
        if force_proceed:
            logger.warning(
                f"GATE OVERRIDE: Proceeding despite gate failure for {target_date}"
            )
            sentry_sdk.capture_message(
                f"Gate override used for {target_date}",
                level="warning"
            )
            return GateResult(
                decision=GateDecision.PROCEED,
                checks_passed=0,
                checks_failed=0,
                blocking_reasons=["MANUAL OVERRIDE"],
                warnings=["Processing with degraded data quality"],
                metrics={}
            )

        # Normal evaluation
        return self._evaluate_checks(target_date)
```

### Override via Environment Variable

```bash
# Emergency override
GATE_OVERRIDE=true python orchestration/phase4_to_phase5.py --date 2026-01-25
```

### Override Audit Log

```sql
-- Create override audit table
CREATE TABLE nba_orchestration.gate_overrides (
    override_id STRING,
    gate_name STRING,
    target_date DATE,
    override_reason STRING,
    overridden_by STRING,
    override_timestamp TIMESTAMP,
    original_decision STRING,
    metrics JSON
);
```

---

## 11. Testing Strategy for Validators

### Unit Testing Pattern

```python
# tests/validation/test_phase4_to_phase5_gate.py

import pytest
from unittest.mock import Mock, patch
from validation.validators.gates.phase4_to_phase5_gate import Phase4ToPhase5Gate

class TestPhase4ToPhase5Gate:
    @pytest.fixture
    def gate(self):
        return Phase4ToPhase5Gate()

    def test_blocks_on_low_quality(self, gate):
        with patch.object(gate, '_run_query') as mock_query:
            # Simulate low quality response
            mock_query.return_value = [Mock(avg_quality=60.0)]

            result = gate.evaluate("2026-01-25")

            assert result.decision == GateDecision.BLOCK
            assert "quality" in result.blocking_reasons[0].lower()

    def test_proceeds_on_good_quality(self, gate):
        with patch.object(gate, '_run_query') as mock_query:
            mock_query.side_effect = [
                [Mock(avg_quality=75.0)],  # quality check
                [Mock(coverage=0.95)],      # player count
                [Mock(staleness_hours=2)],  # freshness
                []                          # no null issues
            ]

            result = gate.evaluate("2026-01-25")

            assert result.decision == GateDecision.PROCEED
```

### Integration Testing

```bash
# Test against real data (read-only)
python -m pytest tests/validation/integration/ \
    --date 2026-01-24 \
    --readonly \
    -v
```

### Dry-Run Mode

```python
class PhaseGate:
    def evaluate(self, target_date: str, dry_run: bool = False) -> GateResult:
        result = self._evaluate_checks(target_date)

        if dry_run:
            logger.info(f"DRY RUN: Gate would {result.decision.value}")
            # Don't actually block in dry run
            result.decision = GateDecision.PROCEED

        return result
```

---

## 12. Monitoring After Implementation

### Key Alerts to Create

| Alert | Condition | Channel |
|-------|-----------|---------|
| Gate blocked processing | Any gate returns BLOCK | Slack #alerts |
| Validation pass rate drop | Pass rate < 80% | Slack #alerts |
| Stuck processor | Running > 30 min | PagerDuty |
| High void rate | Void rate > 15% | Slack #data-quality |
| Late predictions | Any prediction after game start | Slack #predictions |

### Dashboard Queries

```sql
-- Gate decision history
SELECT
    DATE(evaluated_at) as date,
    gate_name,
    decision,
    COUNT(*) as count
FROM `nba_orchestration.gate_evaluations`
WHERE evaluated_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2;

-- Validation health score
SELECT
    DATE(run_timestamp) as date,
    COUNTIF(passed) / COUNT(*) * 100 as health_score
FROM `nba_orchestration.validation_results`
WHERE run_timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY 1;
```

---

## 13. Complete Priority Matrix

| # | Improvement | Impact | Effort | Priority | Dependencies |
|---|-------------|--------|--------|----------|--------------|
| 1 | Phase 4→5 gate | High | Medium | **P0** | None |
| 2 | Cross-phase consistency | High | Medium | **P0** | None |
| 3 | Quality trend monitoring | High | Low | **P0** | None |
| 4 | Fix bare except: pass (7,061) | High | High | **P0** | None |
| 5 | Validation scheduling | Medium | Low | **P1** | #1-3 done |
| 6 | Post-backfill validation | Medium | Low | **P1** | None |
| 7 | Recovery validation | Medium | Medium | **P1** | None |
| 8 | Streaming buffer retry | Medium | Medium | **P1** | None |
| 9 | Pub/Sub DLQs | Medium | Low | **P1** | None |
| 10 | Prediction timing validation | Medium | Low | **P1** | None |
| 11 | Real-time validation hooks | Medium | High | **P2** | #1-3 done |
| 12 | Validation analytics dashboard | Low | Medium | **P2** | #5 done |
| 13 | Config drift in CI/CD | Low | Low | **P2** | None |
| 14 | Duplicate/idempotency validation | Low | Medium | **P2** | None |
| 15 | Void rate monitoring | Low | Low | **P2** | None |
| 16 | Line value sanity | Low | Low | **P2** | None |
| 17 | Cross-field validation | Low | Low | **P2** | None |
| 18 | Heartbeat monitoring | Medium | Medium | **P2** | None |
| 19 | Batch processors to Sentry | Medium | Low | **P2** | None |
| 20 | Chaos testing | Low | High | **P3** | #1-10 done |
| 21 | Predictive alerting | Low | High | **P3** | #12 done |

---

**Document Version:** 1.1
**Last Updated:** 2026-01-25
**Next Review:** After P0 implementations complete
