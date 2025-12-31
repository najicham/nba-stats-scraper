# Event-Driven Orchestration System Design

**Created:** December 31, 2025
**Status:** Design - Ready for Implementation
**Priority:** P0 - Critical for Reliability
**Author:** System Architecture Team

---

## Executive Summary

This document designs an improved event-driven orchestration system to replace the current fixed-scheduler approach. The new system uses completion events to trigger downstream phases, implements intelligent dependency checking, and supports multiple operational modes (overnight, morning refresh, midday update, manual, backfill).

**Key Improvements:**
- Event-driven cascades replace fixed schedulers
- Intelligent dependency checking (lenient vs strict)
- Multi-mode orchestration with context-aware behavior
- Dual state management (Firestore + BigQuery)
- Comprehensive monitoring and alerting
- Graceful degradation and self-healing

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Event-Driven Cascade Architecture](#2-event-driven-cascade-architecture)
3. [Intelligent Dependency Checking](#3-intelligent-dependency-checking)
4. [Multi-Mode Orchestration](#4-multi-mode-orchestration)
5. [State Management](#5-state-management)
6. [Monitoring & Observability](#6-monitoring--observability)
7. [Migration Plan](#7-migration-plan)
8. [Risk Mitigation](#8-risk-mitigation)

---

## 1. Current State Analysis

### 1.1 Current Problems

| Problem | Impact | Example |
|---------|--------|---------|
| **Fixed timing** | Phase 6 exports before predictions complete | Export at 1:00 PM, predictions at 1:30 PM |
| **No dependency awareness** | Phases run without verifying prerequisites | Phase 3→4 expects 5 processors, only 1 runs |
| **Rigid expected counts** | Partial data blocks entire pipeline | `expected_count_min` too strict |
| **No mode awareness** | Same logic for overnight vs same-day | Overnight expects all data, same-day doesn't |
| **Self-heal as crutch** | Schedulers fail, self-heal saves the day | 2:15 PM self-heal actually generates predictions |

### 1.2 Current Pub/Sub Topics

**Existing Topics:**
```
nba-phase2-raw-complete         → Phase 2 processors publish here
nba-phase3-analytics-complete   → Phase 3 processors publish here
nba-phase3-trigger              → (Unused - orchestrator monitoring-only)
nba-phase4-trigger              → Phase 3→4 orchestrator publishes here
nba-phase4-precompute-complete  → Phase 4 processors publish here
nba-predictions-trigger         → Phase 4→5 orchestrator publishes here
nba-phase5-predictions-complete → Predictions publish here
nba-phase6-export-trigger       → Phase 5→6 orchestrator publishes here
nba-phase6-export-complete      → Phase 6 exports publish here
nba-grading-trigger             → Phase 5b grading trigger

*-dlq topics (Dead Letter Queues)
*-fallback-trigger topics (Fallback mechanisms)
```

### 1.3 Current Cloud Functions

**Existing Orchestrators:**
```
phase2-to-phase3-orchestrator  → Monitoring-only (v2.0)
phase3-to-phase4-orchestrator  → Active (aggregates entities_changed)
phase4-to-phase5-orchestrator  → Active (triggers predictions)
phase5-to-phase6-orchestrator  → Active (triggers export)
phase5b-grading                → Active (triggers grading)
```

### 1.4 Current Schedulers

**Daily Operations:**
```
10:30 AM ET → same-day-phase3            (Today's analytics)
11:00 AM ET → same-day-phase4            (Today's features)
11:30 AM ET → same-day-predictions       (Today's predictions)
12:45 PM ET → self-heal-predictions      (Catch missing)
1:00 PM ET  → phase6-tonight-picks       (Website export)
5:00 PM ET  → same-day-phase3-tomorrow   (Tomorrow's analytics)
5:30 PM ET  → same-day-phase4-tomorrow   (Tomorrow's features)
6:00 PM ET  → same-day-predictions-tomorrow (Tomorrow's predictions)
11:00 PM PT → Overnight Phase 4 processors (Yesterday's data)
6:00 AM ET  → Grading (Yesterday's results)
```

---

## 2. Event-Driven Cascade Architecture

### 2.1 Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                     EVENT-DRIVEN ORCHESTRATION v3.0                    │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌──────────┐                                                          │
│  │ Phase 2  │  Processors complete → Publish to completion topic      │
│  │ (Raw)    │                                                          │
│  └────┬─────┘                                                          │
│       │                                                                │
│       ├─► nba-phase2-raw-complete                                     │
│       │         │                                                      │
│       │         ├──► Orchestrator (tracking + dependency check)       │
│       │         │         │                                            │
│       │         │         ├─► Firestore: Update completion state      │
│       │         │         │                                            │
│       │         │         └─► Dependency Check:                       │
│       │         │              • Mode-aware (overnight vs same-day)   │
│       │         │              • Completeness threshold (strict vs lenient)│
│       │         │              • Quality metrics                      │
│       │         │              • Decision: Proceed / Wait / Alert     │
│       │         │                                                      │
│       │         └──► IF dependencies met → nba-phase3-trigger         │
│       │                                                                │
│       ▼                                                                │
│  ┌──────────┐                                                          │
│  │ Phase 3  │  Same cascade pattern...                                │
│  │(Analytics)│                                                         │
│  └────┬─────┘                                                          │
│       │                                                                │
│       ├─► nba-phase3-analytics-complete                               │
│       │         │                                                      │
│       │         └──► Orchestrator → Dependency Check → Phase 4        │
│       │                                                                │
│       ▼                                                                │
│  ┌──────────┐                                                          │
│  │ Phase 4  │                                                          │
│  │(Precomp) │                                                          │
│  └────┬─────┘                                                          │
│       │                                                                │
│       ├─► nba-phase4-precompute-complete                              │
│       │         │                                                      │
│       │         └──► Orchestrator → Dependency Check → Phase 5        │
│       │                                                                │
│       ▼                                                                │
│  ┌──────────┐                                                          │
│  │ Phase 5  │                                                          │
│  │(Predict) │                                                          │
│  └────┬─────┘                                                          │
│       │                                                                │
│       ├─► nba-phase5-predictions-complete                             │
│       │         │                                                      │
│       │         └──► Orchestrator → Quality Check → Phase 6           │
│       │                                                                │
│       ▼                                                                │
│  ┌──────────┐                                                          │
│  │ Phase 6  │                                                          │
│  │ (Export) │                                                          │
│  └──────────┘                                                          │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ CONTROL PLANE (Parallel)                                       │   │
│  ├────────────────────────────────────────────────────────────────┤   │
│  │                                                                 │   │
│  │  • Schedulers (fallback triggers if cascade fails)             │   │
│  │  • Self-heal (detects stuck pipelines, force-triggers)         │   │
│  │  • Monitoring (SLO violations, alerts)                         │   │
│  │  • Manual triggers (operator override)                         │   │
│  │                                                                 │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Pub/Sub Topic Design

#### New Topics to Create

```yaml
# Enhanced orchestration topics (NEW)
nba-orchestration-status:
  purpose: State changes in orchestration
  schema:
    game_date: string
    phase: string
    status: PENDING | IN_PROGRESS | COMPLETE | FAILED | DEGRADED
    mode: overnight | same_day | tomorrow | manual | backfill
    completeness_pct: float
    quality_score: float
    timestamp: timestamp

nba-dependency-check-failed:
  purpose: Dependency checks that failed (for alerting)
  schema:
    phase: string
    game_date: string
    required_table: string
    found_rows: int
    expected_rows: int
    decision: WAIT | PROCEED_DEGRADED | FAIL
    mode: string

nba-pipeline-slo-violation:
  purpose: SLO violations (e.g., predictions late)
  schema:
    slo_type: end_to_end_latency | phase_latency | data_freshness
    game_date: string
    expected_by: timestamp
    actual_at: timestamp
    latency_minutes: int
```

#### Enhanced Existing Topics

Update message schemas for existing topics to include:
```json
{
  "processor_name": "string",
  "phase": "string",
  "game_date": "string",
  "status": "success | partial | failed",
  "correlation_id": "string",
  "execution_id": "string",

  // NEW: Mode and context
  "processing_mode": "overnight | same_day | tomorrow | manual | backfill",
  "trigger_source": "orchestrator | scheduler | self_heal | manual",

  // NEW: Completeness and quality
  "completeness": {
    "total_expected": 100,
    "total_processed": 95,
    "completeness_pct": 95.0,
    "quality_score": 0.98
  },

  // NEW: Dependency status
  "dependencies_met": true,
  "dependency_checks": [
    {
      "table": "nba_raw.player_boxscores",
      "required_rows": 200,
      "found_rows": 195,
      "status": "DEGRADED"
    }
  ],

  // Existing fields
  "entities_changed": {},
  "metadata": {}
}
```

### 2.3 Cloud Function Specifications

#### Enhanced Orchestrator Functions

**Function: `phase2-to-phase3-orchestrator` (v3.0)**
```python
"""
Phase 2→3 Orchestrator v3.0
NOW ACTIVE (was monitoring-only in v2.0)

Responsibilities:
1. Track Phase 2 processor completions in Firestore
2. Perform intelligent dependency checking
3. Trigger Phase 3 when ready (mode-aware)
4. Publish orchestration status events
"""

Configuration:
  runtime: python311
  memory: 512MB (increased from 256MB)
  timeout: 120s (increased from 60s)
  max_instances: 10
  trigger: Pub/Sub nba-phase2-raw-complete

Environment Variables:
  # Mode configuration
  ORCHESTRATION_MODE: auto  # auto, strict, lenient

  # Dependency thresholds (mode-specific)
  OVERNIGHT_MIN_COMPLETENESS: 100  # Strict for overnight
  SAME_DAY_MIN_COMPLETENESS: 80    # Lenient for same-day
  BACKFILL_MIN_COMPLETENESS: 100   # Strict for backfill

  # Quality thresholds
  MIN_QUALITY_SCORE: 0.90

  # Timing SLOs
  OVERNIGHT_MAX_LATENCY_HOURS: 6
  SAME_DAY_MAX_LATENCY_HOURS: 2

Key Logic:
  1. Parse completion message
  2. Update Firestore atomically
  3. Determine processing_mode (from message or infer from time)
  4. Get expected processors for this mode
  5. Check if all expected processors complete
  6. Perform dependency checks (table row counts, freshness)
  7. Calculate completeness and quality scores
  8. Make decision: PROCEED | WAIT | PROCEED_DEGRADED | FAIL
  9. If PROCEED: Trigger Phase 3 with mode context
  10. Publish orchestration status event
  11. Alert if degraded or failed
```

**Function: `intelligent-dependency-checker` (NEW)**
```python
"""
Intelligent Dependency Checker
Shared logic for all orchestrators

Can be invoked directly or as library
"""

Configuration:
  runtime: python311
  memory: 256MB
  timeout: 60s
  trigger: HTTP (for manual checks) or imported as module

Environment Variables:
  # Thresholds by mode
  DEPENDENCY_CHECK_MODE: auto

  # Caching (avoid repeated BigQuery queries)
  CACHE_CHECK_RESULTS_SECONDS: 300

Key Methods:
  check_dependencies(
    phase: str,
    game_date: str,
    mode: str,
    required_tables: List[str]
  ) -> DependencyCheckResult

  calculate_completeness(
    table: str,
    game_date: str,
    expected_min: int = None
  ) -> CompletenessResult

  calculate_quality_score(
    data: pd.DataFrame
  ) -> QualityScore

  make_decision(
    completeness: float,
    quality_score: float,
    mode: str
  ) -> Decision  # PROCEED | WAIT | PROCEED_DEGRADED | FAIL
```

**Function: `orchestration-state-monitor` (NEW)**
```python
"""
Orchestration State Monitor
Monitors Firestore and BigQuery for stuck pipelines

Triggered every 15 minutes
"""

Configuration:
  runtime: python311
  memory: 256MB
  timeout: 300s
  trigger: Cloud Scheduler (*/15 * * * *)

Key Logic:
  1. Query Firestore for in-progress phases older than SLO
  2. Query BigQuery for missing phase completions
  3. Check for cascades that didn't trigger
  4. Identify stuck processors
  5. Publish alerts
  6. Optionally: Auto-trigger self-heal
```

### 2.4 Handling Edge Cases

#### Partial Completeness

**Problem:** Phase 2 completes with 8/11 games scraped. Should Phase 3 run?

**Solution: Mode-aware decision matrix**

| Mode | Completeness | Quality | Decision |
|------|--------------|---------|----------|
| Overnight | 72% (8/11) | 0.95 | **WAIT** - Retry scrapers, expect 100% |
| Same-day | 72% (8/11) | 0.95 | **PROCEED_DEGRADED** - Predictions for 8 games better than 0 |
| Tomorrow | 72% (8/11) | 0.95 | **PROCEED** - Tomorrow's data, no urgency |
| Backfill | 72% (8/11) | 0.95 | **FAIL** - Backfill must be complete |

#### Infinite Loop Prevention

**Problem:** Phase 3 triggers Phase 4, but Phase 4 fails and re-publishes to Phase 3 topic.

**Solution: Firestore `_triggered` flag + correlation_id tracking**

```python
@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, data):
    doc = doc_ref.get(transaction=transaction)
    current = doc.to_dict() if doc.exists else {}

    # Check if already triggered
    if current.get('_triggered'):
        logger.info(f"Already triggered Phase 4 for {game_date}, skipping duplicate")
        return False

    # Check for duplicate processor (idempotency)
    if processor_name in current:
        logger.debug(f"Duplicate message for {processor_name}")
        return False

    # Add processor completion
    current[processor_name] = data

    # Check if complete
    if is_complete(current):
        # Mark as triggered atomically
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_correlation_id'] = data.get('correlation_id')
        transaction.set(doc_ref, current)
        return True

    transaction.set(doc_ref, current)
    return False
```

#### Duplicate Trigger Prevention

**Problem:** Pub/Sub delivers message twice, orchestrator triggers Phase 3 twice.

**Solution: Combination of:**
1. **Firestore `_triggered` flag** (prevents re-trigger)
2. **Idempotency keys** in downstream processors
3. **Correlation ID tracking** (detect duplicate flows)

```python
# In downstream processor (Phase 3)
def process(message):
    correlation_id = message['correlation_id']
    execution_id = message['execution_id']

    # Check if already processed this correlation_id
    existing = bq_client.query(f"""
        SELECT 1 FROM nba_orchestration.processor_execution_log
        WHERE correlation_id = '{correlation_id}'
        AND processor_name = 'player_game_summary'
        AND game_date = '{game_date}'
        LIMIT 1
    """).to_dataframe()

    if not existing.empty:
        logger.info(f"Already processed correlation_id={correlation_id}, skipping")
        return

    # Process...
```

---

## 3. Intelligent Dependency Checking

### 3.1 Current vs Improved Approach

**Current Approach (Too Strict):**
```python
# In processor dependency check
expected_count_min = 200  # Fixed, fails if 199 rows
if row_count < expected_count_min:
    raise DependencyError("Not enough data")
```

**Problems:**
- Blocks entire pipeline if 1 game missing
- No context awareness (is this critical?)
- No quality assessment (199 rows might be perfect data)

**Improved Approach (Intelligent):**
```python
# In dependency checker
result = check_dependencies(
    phase="phase3",
    game_date="2025-12-31",
    mode="same_day",
    required_tables=["nba_raw.player_boxscores", "nba_raw.team_boxscores"]
)

# result.decision = PROCEED | WAIT | PROCEED_DEGRADED | FAIL
# result.completeness_pct = 95.0
# result.quality_score = 0.98
# result.issues = ["Missing 5 player records"]
```

### 3.2 Dependency Checking Logic

#### Decision Tree

```
┌─────────────────────────────────────────────────────────────────┐
│ Intelligent Dependency Decision Tree                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Calculate Completeness                                      │
│     ├─► Query expected count (from schedule or game_date)      │
│     ├─► Query actual count (from required tables)              │
│     └─► completeness_pct = (actual / expected) * 100           │
│                                                                 │
│  2. Calculate Quality Score                                     │
│     ├─► Check data freshness (updated_at timestamps)           │
│     ├─► Check data validity (no NULLs in critical fields)      │
│     ├─► Check data consistency (cross-table validation)        │
│     └─► quality_score = weighted_average(freshness, validity, consistency)│
│                                                                 │
│  3. Get Mode-Specific Thresholds                                │
│     ├─► overnight: min_completeness=100%, min_quality=0.95     │
│     ├─► same_day: min_completeness=80%, min_quality=0.90       │
│     ├─► tomorrow: min_completeness=75%, min_quality=0.85       │
│     ├─► manual: min_completeness=50%, min_quality=0.80         │
│     └─► backfill: min_completeness=100%, min_quality=0.95      │
│                                                                 │
│  4. Make Decision                                               │
│     ├─► IF completeness >= 100% AND quality >= threshold       │
│     │   THEN PROCEED                                            │
│     │                                                           │
│     ├─► ELSE IF completeness >= min AND quality >= min         │
│     │   THEN PROCEED_DEGRADED (warn, track quality)            │
│     │                                                           │
│     ├─► ELSE IF completeness < min BUT mode = same_day         │
│     │   THEN PROCEED_DEGRADED (better than nothing)            │
│     │                                                           │
│     ├─► ELSE IF mode = overnight OR backfill                   │
│     │   THEN WAIT (retry, expect 100%)                         │
│     │                                                           │
│     └─► ELSE FAIL (critically incomplete)                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Implementation

**File: `orchestration/dependency_checker.py` (NEW)**

```python
"""
Intelligent Dependency Checker for Event-Driven Orchestration

Provides mode-aware dependency checking with completeness and quality scoring.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)


class Decision(Enum):
    """Dependency check decision."""
    PROCEED = "proceed"              # All good, trigger next phase
    WAIT = "wait"                    # Not ready, check again later
    PROCEED_DEGRADED = "proceed_degraded"  # Partial data, proceed with warning
    FAIL = "fail"                    # Critically incomplete, alert


@dataclass
class DependencyCheck:
    """Single table dependency check result."""
    table: str
    partition: str  # e.g., "game_date=2025-12-31"
    expected_rows: int
    found_rows: int
    completeness_pct: float
    quality_score: float
    freshness_seconds: int
    issues: List[str]
    status: str  # COMPLETE | DEGRADED | MISSING


@dataclass
class DependencyCheckResult:
    """Overall dependency check result for a phase."""
    phase: str
    game_date: str
    mode: str
    decision: Decision
    overall_completeness: float
    overall_quality: float
    checks: List[DependencyCheck]
    message: str
    should_alert: bool
    retry_in_seconds: Optional[int] = None


class IntelligentDependencyChecker:
    """
    Intelligent dependency checker with mode-aware thresholds.
    """

    # Mode-specific thresholds
    THRESHOLDS = {
        'overnight': {
            'min_completeness': 100.0,
            'min_quality': 0.95,
            'max_latency_hours': 6,
            'allow_degraded': False
        },
        'same_day': {
            'min_completeness': 80.0,
            'min_quality': 0.90,
            'max_latency_hours': 2,
            'allow_degraded': True
        },
        'tomorrow': {
            'min_completeness': 75.0,
            'min_quality': 0.85,
            'max_latency_hours': 12,
            'allow_degraded': True
        },
        'manual': {
            'min_completeness': 50.0,
            'min_quality': 0.80,
            'max_latency_hours': 24,
            'allow_degraded': True
        },
        'backfill': {
            'min_completeness': 100.0,
            'min_quality': 0.95,
            'max_latency_hours': 999999,
            'allow_degraded': False
        }
    }

    def __init__(self):
        self.bq_client = bigquery.Client()

    def check_dependencies(
        self,
        phase: str,
        game_date: str,
        mode: str,
        required_tables: List[Dict[str, any]]
    ) -> DependencyCheckResult:
        """
        Check dependencies for a phase.

        Args:
            phase: Phase name (phase2, phase3, etc.)
            game_date: Game date to check
            mode: Processing mode (overnight, same_day, etc.)
            required_tables: List of required tables with metadata
                [
                    {
                        'table': 'nba_raw.player_boxscores',
                        'partition_field': 'game_date',
                        'expected_min': 200,  # Optional
                        'critical': True      # Optional
                    }
                ]

        Returns:
            DependencyCheckResult with decision and details
        """
        checks = []

        for table_spec in required_tables:
            check = self._check_table(
                table_spec['table'],
                game_date,
                table_spec.get('partition_field', 'game_date'),
                table_spec.get('expected_min'),
                table_spec.get('critical', True)
            )
            checks.append(check)

        # Calculate overall metrics
        overall_completeness = sum(c.completeness_pct for c in checks) / len(checks)
        overall_quality = sum(c.quality_score for c in checks) / len(checks)

        # Get thresholds for mode
        thresholds = self.THRESHOLDS.get(mode, self.THRESHOLDS['same_day'])

        # Make decision
        decision = self._make_decision(
            overall_completeness,
            overall_quality,
            checks,
            thresholds
        )

        # Build result
        message = self._build_message(decision, checks, thresholds)
        should_alert = decision in (Decision.FAIL, Decision.PROCEED_DEGRADED)

        return DependencyCheckResult(
            phase=phase,
            game_date=game_date,
            mode=mode,
            decision=decision,
            overall_completeness=overall_completeness,
            overall_quality=overall_quality,
            checks=checks,
            message=message,
            should_alert=should_alert,
            retry_in_seconds=self._get_retry_interval(decision, mode)
        )

    def _check_table(
        self,
        table: str,
        game_date: str,
        partition_field: str,
        expected_min: Optional[int],
        critical: bool
    ) -> DependencyCheck:
        """Check a single table dependency."""

        # Query actual row count
        query = f"""
        SELECT
            COUNT(*) as row_count,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(updated_at), SECOND) as freshness_seconds
        FROM `{table}`
        WHERE {partition_field} = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            found_rows = int(result['row_count'].iloc[0])
            freshness_seconds = int(result['freshness_seconds'].iloc[0]) if result['freshness_seconds'].iloc[0] else 0
        except Exception as e:
            logger.error(f"Error checking {table}: {e}")
            return DependencyCheck(
                table=table,
                partition=f"{partition_field}={game_date}",
                expected_rows=expected_min or 0,
                found_rows=0,
                completeness_pct=0.0,
                quality_score=0.0,
                freshness_seconds=0,
                issues=[f"Query failed: {str(e)}"],
                status="MISSING"
            )

        # Get expected count
        if expected_min is None:
            # Infer from schedule
            expected_min = self._get_expected_count(game_date, table)

        # Calculate completeness
        completeness_pct = (found_rows / expected_min * 100) if expected_min > 0 else 0.0

        # Calculate quality score
        quality_score = self._calculate_quality_score(
            table, game_date, found_rows, freshness_seconds
        )

        # Determine status
        if completeness_pct >= 100.0 and quality_score >= 0.95:
            status = "COMPLETE"
        elif completeness_pct >= 80.0 and quality_score >= 0.90:
            status = "DEGRADED"
        else:
            status = "MISSING"

        # Collect issues
        issues = []
        if completeness_pct < 100.0:
            issues.append(f"Only {found_rows}/{expected_min} rows ({completeness_pct:.1f}%)")
        if quality_score < 0.95:
            issues.append(f"Quality score {quality_score:.2f} below optimal")
        if freshness_seconds > 3600:
            issues.append(f"Data {freshness_seconds/3600:.1f} hours old")

        return DependencyCheck(
            table=table,
            partition=f"{partition_field}={game_date}",
            expected_rows=expected_min,
            found_rows=found_rows,
            completeness_pct=completeness_pct,
            quality_score=quality_score,
            freshness_seconds=freshness_seconds,
            issues=issues,
            status=status
        )

    def _calculate_quality_score(
        self,
        table: str,
        game_date: str,
        row_count: int,
        freshness_seconds: int
    ) -> float:
        """
        Calculate quality score for table data.

        Factors:
        - Freshness (newer = better)
        - Completeness (more rows = better, up to expected)
        - Validity (check for NULLs in critical fields)
        """
        # Freshness score (1.0 if < 1 hour, 0.5 if < 6 hours, 0.0 if > 12 hours)
        if freshness_seconds < 3600:
            freshness_score = 1.0
        elif freshness_seconds < 21600:
            freshness_score = 0.8
        elif freshness_seconds < 43200:
            freshness_score = 0.5
        else:
            freshness_score = 0.3

        # Completeness score (from completeness_pct)
        # This would be calculated from expected vs actual
        # For now, assume 1.0 if we have rows
        completeness_score = 1.0 if row_count > 0 else 0.0

        # Validity score (check for NULLs, would require table-specific logic)
        # For now, assume 1.0
        validity_score = 1.0

        # Weighted average
        quality_score = (
            freshness_score * 0.4 +
            completeness_score * 0.4 +
            validity_score * 0.2
        )

        return quality_score

    def _make_decision(
        self,
        overall_completeness: float,
        overall_quality: float,
        checks: List[DependencyCheck],
        thresholds: Dict
    ) -> Decision:
        """
        Make decision based on completeness, quality, and thresholds.
        """
        min_completeness = thresholds['min_completeness']
        min_quality = thresholds['min_quality']
        allow_degraded = thresholds['allow_degraded']

        # Check for critical missing tables
        critical_missing = any(
            c.status == "MISSING" and c.completeness_pct < min_completeness
            for c in checks
        )

        # Perfect scenario
        if overall_completeness >= 100.0 and overall_quality >= min_quality:
            return Decision.PROCEED

        # Good enough scenario
        if overall_completeness >= min_completeness and overall_quality >= min_quality:
            if allow_degraded:
                return Decision.PROCEED_DEGRADED
            else:
                return Decision.WAIT  # Strict mode, wait for 100%

        # Partial data scenario
        if overall_completeness >= (min_completeness * 0.8):
            if allow_degraded and not critical_missing:
                return Decision.PROCEED_DEGRADED
            else:
                return Decision.WAIT

        # Not enough data
        if overall_completeness < min_completeness:
            if allow_degraded and overall_completeness >= 50:
                return Decision.PROCEED_DEGRADED  # Partial predictions better than none
            else:
                return Decision.FAIL

        # Default: wait
        return Decision.WAIT

    def _get_expected_count(self, game_date: str, table: str) -> int:
        """
        Get expected row count for a table on a game_date.

        Logic:
        - Query schedule for game count
        - Multiply by expected rows per game (table-specific)
        """
        # Query schedule
        query = f"""
        SELECT COUNT(*) as game_count
        FROM `nba-props-platform.nba_raw.schedule`
        WHERE game_date = '{game_date}'
        AND status_type IN ('Final', 'InProgress', 'Scheduled')
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            game_count = int(result['game_count'].iloc[0])
        except:
            game_count = 0

        # Table-specific multipliers
        multipliers = {
            'player_boxscores': 20,  # ~20 players per game
            'team_boxscores': 2,     # 2 teams per game
            'play_by_play': 250,     # ~250 plays per game
        }

        # Get multiplier for table
        for key, multiplier in multipliers.items():
            if key in table:
                return game_count * multiplier

        # Default: game_count
        return game_count

    def _build_message(
        self,
        decision: Decision,
        checks: List[DependencyCheck],
        thresholds: Dict
    ) -> str:
        """Build human-readable message about decision."""
        if decision == Decision.PROCEED:
            return "All dependencies met, proceeding to next phase"
        elif decision == Decision.PROCEED_DEGRADED:
            issues = []
            for check in checks:
                if check.status != "COMPLETE":
                    issues.append(f"{check.table}: {', '.join(check.issues)}")
            return f"Proceeding with degraded quality: {'; '.join(issues)}"
        elif decision == Decision.WAIT:
            return f"Waiting for dependencies (need {thresholds['min_completeness']}% completeness)"
        else:  # FAIL
            return f"Dependencies critically incomplete, failing"

    def _get_retry_interval(self, decision: Decision, mode: str) -> Optional[int]:
        """Get retry interval in seconds based on decision and mode."""
        if decision == Decision.WAIT:
            # Retry intervals by mode
            intervals = {
                'overnight': 600,   # 10 minutes
                'same_day': 300,    # 5 minutes
                'tomorrow': 1800,   # 30 minutes
                'manual': 60,       # 1 minute
                'backfill': 1800    # 30 minutes
            }
            return intervals.get(mode, 300)
        return None
```

### 3.3 When to Proceed with Partial Data

**Decision Matrix:**

| Scenario | Mode | Completeness | Quality | Decision | Rationale |
|----------|------|--------------|---------|----------|-----------|
| 10/11 games scraped | Overnight | 91% | 0.98 | **WAIT** | Expect 100% overnight, retry scrapers |
| 10/11 games scraped | Same-day | 91% | 0.98 | **PROCEED_DEGRADED** | 10 predictions better than 0 |
| 5/11 games scraped | Same-day | 45% | 0.95 | **PROCEED_DEGRADED** | Some data better than none |
| 2/11 games scraped | Same-day | 18% | 0.90 | **FAIL** | Too incomplete, alert |
| Missing critical table | Any | N/A | N/A | **FAIL** | Can't proceed without key data |
| Stale data (>12h old) | Overnight | 100% | 0.60 | **WAIT** | Data too old, re-scrape |

### 3.4 When to Wait for More Data

**Waiting Logic:**

```python
def should_wait(check_result: DependencyCheckResult) -> bool:
    """
    Determine if orchestrator should wait before triggering next phase.
    """
    # Never wait in manual or backfill mode (human decision)
    if check_result.mode in ('manual', 'backfill'):
        return False

    # If decision is WAIT, check time constraints
    if check_result.decision == Decision.WAIT:
        # How long have we been waiting?
        first_check_time = get_first_check_time(check_result.game_date, check_result.phase)
        waiting_minutes = (datetime.now() - first_check_time).total_seconds() / 60

        # Max wait times by mode
        max_wait = {
            'overnight': 360,  # 6 hours
            'same_day': 120,   # 2 hours
            'tomorrow': 720    # 12 hours
        }

        if waiting_minutes > max_wait.get(check_result.mode, 120):
            # Waited too long, escalate decision
            logger.warning(f"Waited {waiting_minutes} minutes, exceeded max wait")
            if check_result.overall_completeness >= 50:
                return False  # Proceed degraded
            else:
                # Still wait, but alert
                alert_dependency_timeout(check_result)
                return True

        return True  # Keep waiting

    return False  # PROCEED or FAIL, don't wait
```

### 3.5 When to Fail and Alert

**Failure Scenarios:**

1. **Critically Incomplete Data**
   - Completeness < 20% in strict mode (overnight, backfill)
   - Missing required critical tables
   - Example: No schedule data for game_date

2. **Extremely Low Quality**
   - Quality score < 0.5
   - Data corruption detected
   - Example: All player_ids are NULL

3. **Timeout Exceeded**
   - Waited beyond max wait time with no improvement
   - Example: 6 hours in overnight mode, still 30% complete

4. **Circular Dependency Detected**
   - Phase trying to trigger itself
   - Infinite loop protection triggered

**Alert Levels:**

```python
class AlertLevel(Enum):
    INFO = "info"          # FYI, no action needed
    WARNING = "warning"    # Degraded quality, monitor
    ERROR = "error"        # Failed dependency, manual intervention may be needed
    CRITICAL = "critical"  # Pipeline stuck, immediate action required

def determine_alert_level(check_result: DependencyCheckResult) -> AlertLevel:
    """Determine alert severity."""
    if check_result.decision == Decision.FAIL:
        if check_result.overall_completeness < 20:
            return AlertLevel.CRITICAL
        else:
            return AlertLevel.ERROR

    elif check_result.decision == Decision.PROCEED_DEGRADED:
        if check_result.overall_quality < 0.80:
            return AlertLevel.WARNING
        else:
            return AlertLevel.INFO

    elif check_result.decision == Decision.WAIT:
        # Check how long we've been waiting
        waiting_minutes = get_waiting_time(check_result)
        if waiting_minutes > 120:
            return AlertLevel.WARNING
        else:
            return AlertLevel.INFO

    return AlertLevel.INFO
```

---

## 4. Multi-Mode Orchestration

### 4.1 Mode Definitions

| Mode | When | Purpose | Characteristics |
|------|------|---------|-----------------|
| **overnight** | 11 PM - 6 AM | Process yesterday's completed games | Strict, expect 100%, retry on failure |
| **same_day** | 10:30 AM - 2 PM | Pre-game predictions for today | Lenient, partial OK, fast turnaround |
| **tomorrow** | 5 PM - 8 PM | Pre-game predictions for tomorrow | Lenient, advance notice, less urgency |
| **manual** | Any time | Operator-triggered reprocessing | Very lenient, operator decides |
| **backfill** | Any time | Historical data processing | Strict, 100% required, no alerts |

### 4.2 Mode-Specific Behavior

#### Overnight Mode

**Characteristics:**
- Runs: 11:00 PM PT (overnight Phase 4 processors)
- Processes: **Yesterday's** games (post-game data)
- Data source: Gamebook (actual players who played)
- Completeness requirement: **100%**
- Quality requirement: **0.95**
- Retry strategy: Aggressive (every 10 minutes for 6 hours)
- Alert threshold: Low (alert if not 100%)

**Configuration:**
```python
OVERNIGHT_CONFIG = {
    'min_completeness': 100.0,
    'min_quality': 0.95,
    'max_latency_hours': 6,
    'retry_interval_seconds': 600,
    'max_retries': 36,
    'allow_degraded': False,
    'alert_on_degraded': True,
    'alert_on_wait': True,  # Alert if waiting > 1 hour
}
```

**Orchestration Flow:**
```
11:00 PM PT → Phase 4 overnight processors start
              ├─► player_composite_factors (YESTERDAY)
              ├─► player_daily_cache (YESTERDAY)
              └─► ml_feature_store (YESTERDAY)

11:45 PM PT → All 3 processors complete
              └─► Orchestrator checks dependencies:
                  • Expected: 100% of yesterday's games
                  • Quality: 0.95+
                  • IF met → Trigger Phase 5? (No, overnight doesn't generate predictions)
                  • Just log completion

6:00 AM ET  → Grading runs (yesterday's predictions vs actual)
              └─► Uses yesterday's analytics data
```

#### Same-Day Mode

**Characteristics:**
- Runs: 10:30 AM ET (morning schedulers)
- Processes: **Today's** games (pre-game predictions)
- Data source: Schedule + Roster (predicted starters)
- Completeness requirement: **80%**
- Quality requirement: **0.90**
- Retry strategy: Moderate (every 5 minutes for 2 hours)
- Alert threshold: Medium (alert if < 50%)

**Configuration:**
```python
SAME_DAY_CONFIG = {
    'min_completeness': 80.0,
    'min_quality': 0.90,
    'max_latency_hours': 2,
    'retry_interval_seconds': 300,
    'max_retries': 24,
    'allow_degraded': True,
    'alert_on_degraded': False,  # Don't alert, expected
    'alert_on_wait': False,
    'alert_on_fail': True,  # Only alert if critically incomplete
}
```

**Orchestration Flow:**
```
10:30 AM ET → same-day-phase3
              └─► UpcomingPlayerGameContext (TODAY)
              └─► UpcomingTeamGameContext (TODAY)

11:00 AM ET → Orchestrator checks Phase 3 complete
              ├─► Expected: 2 processors
              ├─► Dependency check: Schedule exists for today?
              └─► IF complete → Trigger same-day-phase4

11:00 AM ET → same-day-phase4
              └─► MLFeatureStore (TODAY, same_day_mode=True)

11:30 AM ET → Orchestrator checks Phase 4 complete
              ├─► Expected: 1 processor (not all 5)
              ├─► Dependency check: Features exist for today?
              └─► IF complete → Trigger same-day-predictions

11:30 AM ET → same-day-predictions
              └─► Prediction Coordinator (TODAY)

12:30 PM ET → Predictions complete (ideally)
              └─► Orchestrator triggers Phase 6 export

1:00 PM ET  → Phase 6 export runs
              └─► Tonight's picks available on website
```

#### Tomorrow Mode

**Characteristics:**
- Runs: 5:00 PM ET (evening schedulers)
- Processes: **Tomorrow's** games (advance predictions)
- Data source: Schedule + Roster
- Completeness requirement: **75%**
- Quality requirement: **0.85**
- Retry strategy: Relaxed (every 30 minutes for 12 hours)
- Alert threshold: High (alert if < 30%)

**Configuration:**
```python
TOMORROW_CONFIG = {
    'min_completeness': 75.0,
    'min_quality': 0.85,
    'max_latency_hours': 12,
    'retry_interval_seconds': 1800,
    'max_retries': 24,
    'allow_degraded': True,
    'alert_on_degraded': False,
    'alert_on_wait': False,
    'alert_on_fail': True,
}
```

#### Manual Mode

**Characteristics:**
- Runs: On-demand (operator trigger)
- Processes: Any date
- Completeness requirement: **50%** (operator decides)
- Quality requirement: **0.80**
- Retry strategy: None (one-shot)
- Alert threshold: None (operator monitors)

**Configuration:**
```python
MANUAL_CONFIG = {
    'min_completeness': 50.0,
    'min_quality': 0.80,
    'max_latency_hours': 24,
    'retry_interval_seconds': 60,
    'max_retries': 1,
    'allow_degraded': True,
    'alert_on_degraded': False,
    'alert_on_wait': False,
    'alert_on_fail': False,  # Operator already knows
}
```

#### Backfill Mode

**Characteristics:**
- Runs: Batch processing (historical dates)
- Processes: Past dates (2023-2025)
- Completeness requirement: **100%**
- Quality requirement: **0.95**
- Retry strategy: Manual (script controls)
- Alert threshold: None (batch process, logged)

**Configuration:**
```python
BACKFILL_CONFIG = {
    'min_completeness': 100.0,
    'min_quality': 0.95,
    'max_latency_hours': 999999,
    'retry_interval_seconds': 0,
    'max_retries': 0,
    'allow_degraded': False,
    'alert_on_degraded': False,
    'alert_on_wait': False,
    'alert_on_fail': False,
    'skip_orchestrator': True,  # Backfill bypasses orchestrators
}
```

### 4.3 Mode Detection

**How does orchestrator determine mode?**

```python
def detect_processing_mode(message: Dict, current_time: datetime) -> str:
    """
    Detect processing mode from message or time of day.

    Priority:
    1. Explicit mode in message
    2. Infer from trigger_source and time
    3. Default to 'same_day'
    """
    # Explicit mode
    if 'processing_mode' in message:
        return message['processing_mode']

    # Backfill mode (skip_downstream_trigger=True)
    if message.get('backfill_mode') or message.get('skip_downstream_trigger'):
        return 'backfill'

    # Manual trigger
    if message.get('trigger_source') == 'manual':
        return 'manual'

    # Infer from time (ET timezone)
    hour_et = current_time.astimezone(pytz.timezone('America/New_York')).hour

    if 23 <= hour_et or hour_et < 6:
        return 'overnight'
    elif 10 <= hour_et < 15:
        return 'same_day'
    elif 17 <= hour_et < 21:
        return 'tomorrow'
    else:
        return 'same_day'  # Default
```

### 4.4 Mode-Specific Expected Processors

**Problem:** Phase 3→4 orchestrator expects 5 processors, but same-day mode only runs 1.

**Solution:** Mode-aware expected processor lists

```python
EXPECTED_PROCESSORS = {
    'phase3': {
        'overnight': [
            'player_game_summary',
            'team_defense_game_summary',
            'team_offense_game_summary',
            'upcoming_player_game_context',  # For tomorrow's games
            'upcoming_team_game_context'      # For tomorrow's games
        ],
        'same_day': [
            'upcoming_player_game_context',  # Only these 2 for today
            'upcoming_team_game_context'
        ],
        'tomorrow': [
            'upcoming_player_game_context',
            'upcoming_team_game_context'
        ],
        'backfill': [
            'player_game_summary',
            'team_defense_game_summary',
            'team_offense_game_summary'
            # No 'upcoming' processors in backfill
        ]
    },
    'phase4': {
        'overnight': [
            'player_composite_factors',
            'player_daily_cache',
            'ml_feature_store'
            # Not team_defense_zone, player_shot_zone (only when needed)
        ],
        'same_day': [
            'ml_feature_store'  # Only this for today
        ],
        'tomorrow': [
            'ml_feature_store'
        ],
        'backfill': [
            'player_composite_factors',
            'player_daily_cache',
            'ml_feature_store',
            'team_defense_zone_analysis',
            'player_shot_zone_analysis'
        ]
    }
}

def get_expected_processors(phase: str, mode: str) -> List[str]:
    """Get expected processors for phase and mode."""
    return EXPECTED_PROCESSORS.get(phase, {}).get(mode, [])
```

**Updated Orchestrator Logic:**

```python
@functions_framework.cloud_event
def orchestrate_phase3_to_phase4(cloud_event):
    message_data = parse_pubsub_message(cloud_event)
    game_date = message_data['game_date']
    processor_name = message_data['processor_name']

    # Detect mode
    mode = detect_processing_mode(message_data, datetime.now())

    # Get expected processors for this mode
    expected_processors = get_expected_processors('phase3', mode)

    # Update Firestore
    doc_ref = db.collection('phase3_completion').document(f"{game_date}_{mode}")

    # Atomic transaction
    should_trigger = update_completion_atomic(
        transaction,
        doc_ref,
        processor_name,
        completion_data,
        expected_processors  # Mode-specific list
    )

    if should_trigger:
        # Check dependencies
        dep_result = check_dependencies(
            phase='phase4',
            game_date=game_date,
            mode=mode,
            required_tables=get_required_tables('phase4', mode)
        )

        if dep_result.decision in (Decision.PROCEED, Decision.PROCEED_DEGRADED):
            trigger_phase4(game_date, mode, dep_result)
```

---

## 5. State Management

### 5.1 Dual State Tracking

**Problem:** Firestore is real-time but hard to query. BigQuery is queryable but not real-time.

**Solution:** Use both, with different purposes.

#### Firestore (Real-Time State)

**Purpose:**
- Atomic coordination between processors
- Prevent race conditions and duplicate triggers
- Short-term state (7 days)

**Collections:**

```
phase2_completion/
  {game_date}_{mode}/
    _mode: string (overnight, same_day, tomorrow)
    _triggered: boolean
    _triggered_at: timestamp
    _expected_count: int
    _completed_count: int
    _correlation_id: string

    processor_name: {
      completed_at: timestamp
      status: string
      record_count: int
      execution_id: string
      entities_changed: array
    }

phase3_completion/
  {game_date}_{mode}/
    [same structure]

phase4_completion/
  {game_date}_{mode}/
    [same structure]

phase5_completion/
  {game_date}_{mode}/
    [same structure]

orchestration_locks/
  {game_date}_{phase}_{mode}/
    locked_at: timestamp
    locked_by: string (orchestrator instance)
    expires_at: timestamp
```

**TTL Policy:**
- Auto-delete documents older than 7 days
- Keeps Firestore lightweight

#### BigQuery (Audit Log)

**Purpose:**
- Historical analysis
- Debugging past issues
- SLO tracking
- Trend analysis

**Table: `nba_orchestration.orchestration_events`**

```sql
CREATE TABLE nba_orchestration.orchestration_events (
  event_id STRING NOT NULL,
  event_time TIMESTAMP NOT NULL,
  event_type STRING NOT NULL,  -- completion, trigger, dependency_check, decision

  -- Context
  phase STRING NOT NULL,
  game_date DATE NOT NULL,
  processing_mode STRING,  -- overnight, same_day, tomorrow, manual, backfill
  correlation_id STRING,

  -- Processor info (if completion event)
  processor_name STRING,
  execution_id STRING,
  processor_status STRING,
  record_count INT64,

  -- Dependency check (if dependency_check event)
  dependency_result JSON,  -- DependencyCheckResult as JSON

  -- Decision (if trigger event)
  decision STRING,  -- PROCEED, WAIT, PROCEED_DEGRADED, FAIL
  triggered_phase STRING,

  -- Metadata
  orchestrator_version STRING,
  orchestrator_instance STRING,

  -- Timestamps
  inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY phase, processing_mode, event_type;
```

**Table: `nba_orchestration.phase_completion_log`**

```sql
CREATE TABLE nba_orchestration.phase_completion_log (
  completion_id STRING NOT NULL,

  -- Identity
  phase STRING NOT NULL,
  game_date DATE NOT NULL,
  processing_mode STRING,

  -- Status
  status STRING NOT NULL,  -- in_progress, complete, failed, degraded
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  duration_seconds INT64,

  -- Processors
  expected_processor_count INT64,
  completed_processor_count INT64,
  processors_completed ARRAY<STRING>,
  processors_missing ARRAY<STRING>,

  -- Quality metrics
  overall_completeness FLOAT64,
  overall_quality FLOAT64,

  -- Dependencies
  dependencies_met BOOLEAN,
  dependency_issues ARRAY<STRING>,

  -- Triggered downstream?
  triggered_downstream BOOLEAN,
  triggered_at TIMESTAMP,
  downstream_phase STRING,

  -- Correlation
  correlation_id STRING,

  -- Metadata
  inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY phase, status, processing_mode;
```

**Table: `nba_orchestration.dependency_check_log`**

```sql
CREATE TABLE nba_orchestration.dependency_check_log (
  check_id STRING NOT NULL,
  check_time TIMESTAMP NOT NULL,

  -- Context
  phase STRING NOT NULL,
  game_date DATE NOT NULL,
  processing_mode STRING,

  -- Table being checked
  required_table STRING NOT NULL,
  partition_spec STRING,

  -- Results
  expected_rows INT64,
  found_rows INT64,
  completeness_pct FLOAT64,
  quality_score FLOAT64,
  freshness_seconds INT64,

  -- Status
  check_status STRING,  -- COMPLETE, DEGRADED, MISSING
  issues ARRAY<STRING>,

  -- Decision impact
  contributed_to_decision STRING,  -- PROCEED, WAIT, etc.

  -- Metadata
  correlation_id STRING,
  inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(game_date)
CLUSTER BY phase, required_table;
```

### 5.2 State Synchronization

**How to keep Firestore and BigQuery in sync?**

```python
class DualStateManager:
    """
    Manages state in both Firestore (real-time) and BigQuery (audit).
    """

    def __init__(self):
        self.firestore_client = firestore.Client()
        self.bq_client = bigquery.Client()

    def record_completion(
        self,
        phase: str,
        game_date: str,
        mode: str,
        processor_name: str,
        completion_data: Dict
    ) -> bool:
        """
        Record processor completion in both Firestore and BigQuery.

        Returns:
            True if this completion triggered next phase
        """
        # 1. Update Firestore (atomic, real-time)
        doc_ref = self.firestore_client.collection(f'{phase}_completion').document(f'{game_date}_{mode}')

        transaction = self.firestore_client.transaction()
        should_trigger = update_completion_atomic(
            transaction,
            doc_ref,
            processor_name,
            completion_data
        )

        # 2. Log to BigQuery (async, audit)
        event = {
            'event_id': str(uuid.uuid4()),
            'event_time': datetime.now(timezone.utc).isoformat(),
            'event_type': 'completion',
            'phase': phase,
            'game_date': game_date,
            'processing_mode': mode,
            'processor_name': processor_name,
            'execution_id': completion_data.get('execution_id'),
            'processor_status': completion_data.get('status'),
            'record_count': completion_data.get('record_count'),
            'correlation_id': completion_data.get('correlation_id'),
            'orchestrator_version': '3.0'
        }

        self._log_event(event)

        return should_trigger

    def record_dependency_check(
        self,
        phase: str,
        game_date: str,
        mode: str,
        dep_result: DependencyCheckResult
    ):
        """
        Log dependency check to BigQuery.
        """
        # Log overall decision
        event = {
            'event_id': str(uuid.uuid4()),
            'event_time': datetime.now(timezone.utc).isoformat(),
            'event_type': 'dependency_check',
            'phase': phase,
            'game_date': game_date,
            'processing_mode': mode,
            'decision': dep_result.decision.value,
            'dependency_result': asdict(dep_result),  # Full result as JSON
            'orchestrator_version': '3.0'
        }

        self._log_event(event)

        # Log individual table checks
        for check in dep_result.checks:
            check_log = {
                'check_id': str(uuid.uuid4()),
                'check_time': datetime.now(timezone.utc).isoformat(),
                'phase': phase,
                'game_date': game_date,
                'processing_mode': mode,
                'required_table': check.table,
                'partition_spec': check.partition,
                'expected_rows': check.expected_rows,
                'found_rows': check.found_rows,
                'completeness_pct': check.completeness_pct,
                'quality_score': check.quality_score,
                'freshness_seconds': check.freshness_seconds,
                'check_status': check.status,
                'issues': check.issues,
                'contributed_to_decision': dep_result.decision.value
            }

            self._log_dependency_check(check_log)

    def record_trigger(
        self,
        phase: str,
        game_date: str,
        mode: str,
        downstream_phase: str,
        decision: Decision
    ):
        """
        Record phase trigger to BigQuery.
        """
        # Update Firestore (mark triggered)
        doc_ref = self.firestore_client.collection(f'{phase}_completion').document(f'{game_date}_{mode}')
        doc_ref.update({
            '_triggered': True,
            '_triggered_at': firestore.SERVER_TIMESTAMP,
            '_triggered_phase': downstream_phase
        })

        # Log to BigQuery
        event = {
            'event_id': str(uuid.uuid4()),
            'event_time': datetime.now(timezone.utc).isoformat(),
            'event_type': 'trigger',
            'phase': phase,
            'game_date': game_date,
            'processing_mode': mode,
            'decision': decision.value,
            'triggered_phase': downstream_phase,
            'orchestrator_version': '3.0'
        }

        self._log_event(event)

    def _log_event(self, event: Dict):
        """Log event to BigQuery (async)."""
        table_id = 'nba-props-platform.nba_orchestration.orchestration_events'
        errors = self.bq_client.insert_rows_json(table_id, [event])
        if errors:
            logger.error(f"Failed to log event: {errors}")

    def _log_dependency_check(self, check: Dict):
        """Log dependency check to BigQuery."""
        table_id = 'nba-props-platform.nba_orchestration.dependency_check_log'
        errors = self.bq_client.insert_rows_json(table_id, [check])
        if errors:
            logger.error(f"Failed to log dependency check: {errors}")
```

### 5.3 Querying State

**Real-time (Firestore):**
```python
# Check if Phase 3 complete for today
doc = db.collection('phase3_completion').document('2025-12-31_same_day').get()
if doc.exists:
    data = doc.to_dict()
    triggered = data.get('_triggered', False)
    count = len([k for k in data if not k.startswith('_')])
    print(f"Phase 3: {count} processors, triggered={triggered}")
```

**Historical (BigQuery):**
```sql
-- Get today's pipeline status across all phases
SELECT
  phase,
  processing_mode,
  status,
  completed_processor_count,
  expected_processor_count,
  overall_completeness,
  triggered_downstream
FROM nba_orchestration.phase_completion_log
WHERE game_date = CURRENT_DATE('America/New_York')
ORDER BY phase;

-- Find dependency check failures in last 7 days
SELECT
  game_date,
  phase,
  required_table,
  completeness_pct,
  issues
FROM nba_orchestration.dependency_check_log
WHERE game_date >= CURRENT_DATE() - 7
AND check_status != 'COMPLETE'
ORDER BY game_date DESC, phase;

-- Track end-to-end latency
WITH phase_times AS (
  SELECT
    game_date,
    processing_mode,
    phase,
    MIN(event_time) as phase_start,
    MAX(event_time) as phase_end
  FROM nba_orchestration.orchestration_events
  WHERE event_type IN ('completion', 'trigger')
  GROUP BY 1, 2, 3
)
SELECT
  game_date,
  processing_mode,
  TIMESTAMP_DIFF(
    MAX(CASE WHEN phase = 'phase5' THEN phase_end END),
    MIN(CASE WHEN phase = 'phase2' THEN phase_start END),
    MINUTE
  ) as end_to_end_minutes
FROM phase_times
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### 5.4 Cleanup and Retention

**Firestore:**
```python
def cleanup_old_firestore_docs():
    """
    Delete Firestore documents older than 7 days.
    Run daily via Cloud Scheduler.
    """
    cutoff_date = datetime.now() - timedelta(days=7)

    for collection in ['phase2_completion', 'phase3_completion', 'phase4_completion', 'phase5_completion']:
        docs = db.collection(collection).where('_triggered_at', '<', cutoff_date).stream()
        for doc in docs:
            doc.reference.delete()
            logger.info(f"Deleted {collection}/{doc.id}")
```

**BigQuery:**
```sql
-- Partition-level retention (automatic via table settings)
-- Keep 1 year of data
ALTER TABLE nba_orchestration.orchestration_events
SET OPTIONS (
  partition_expiration_days = 365
);
```

---

## 6. Monitoring & Observability

### 6.1 Metrics to Track

#### SLO Metrics

**End-to-End Latency:**
```
Definition: Time from first Phase 2 processor completion to Phase 6 export complete
Target:
  - Overnight: < 6 hours
  - Same-day: < 2 hours
  - Tomorrow: < 12 hours
```

**Phase Latency:**
```
Definition: Time for each phase to complete (all processors)
Target:
  - Phase 2: < 30 minutes
  - Phase 3: < 15 minutes
  - Phase 4: < 30 minutes
  - Phase 5: < 60 minutes
  - Phase 6: < 10 minutes
```

**Completeness at Each Phase:**
```
Definition: % of expected processors that completed successfully
Target:
  - Overnight: 100%
  - Same-day: >= 80%
  - Tomorrow: >= 75%
```

**Quality Score Over Time:**
```
Definition: Average quality score from dependency checks
Target: >= 0.90
```

**Failure Rate:**
```
Definition: % of orchestration decisions that resulted in FAIL
Target: < 5%
```

#### Operational Metrics

**Cascade Success Rate:**
```
Definition: % of phase completions that successfully triggered next phase
Target: >= 95%
```

**Dependency Check Duration:**
```
Definition: Time to perform dependency check
Target: < 30 seconds
```

**Firestore Transaction Conflicts:**
```
Definition: # of Firestore transaction retries due to conflicts
Target: < 10 per day
```

**Self-Heal Intervention Rate:**
```
Definition: % of pipelines that required self-heal to complete
Target: < 20%
```

### 6.2 Dashboards

#### Real-Time Pipeline Dashboard

**Data Source:** Firestore + BigQuery

**Sections:**

1. **Current Status** (refreshes every 30s)
   ```
   Game Date: 2025-12-31 (Same-Day Mode)

   Phase 2: ✅ Complete (6/6 processors, 100%)
   Phase 3: ⏳ In Progress (1/2 processors, 50%)
   Phase 4: ⏸️ Pending (waiting for Phase 3)
   Phase 5: ⏸️ Pending
   Phase 6: ⏸️ Pending

   Overall: 40% complete
   ETA: 11:30 AM ET (based on current rate)
   ```

2. **Recent Events** (last 10)
   ```
   11:05 AM - Phase 3: UpcomingPlayerGameContext completed (95% completeness)
   11:00 AM - Phase 4: Dependency check passed (proceed)
   10:55 AM - Phase 2: All 6 processors complete, triggered Phase 3
   ```

3. **Quality Metrics**
   ```
   Completeness: 95%
   Quality Score: 0.92
   Freshness: 5 minutes
   ```

4. **Alerts**
   ```
   ⚠️ WARNING: Phase 3 completeness below 100% (95%)
   ℹ️ INFO: Proceeding with degraded quality
   ```

#### Historical Trends Dashboard

**Data Source:** BigQuery

**Charts:**

1. **End-to-End Latency (Last 30 Days)**
   - Line chart: Minutes from Phase 2 start to Phase 6 complete
   - Color-coded by mode (overnight, same-day, tomorrow)
   - SLO line overlay

2. **Phase Completion Rates (Last 7 Days)**
   - Stacked bar chart: % processors complete per phase
   - Red if < 100%, yellow if < 95%, green if 100%

3. **Quality Score Trends (Last 30 Days)**
   - Line chart: Average quality score per day
   - Separate lines for each phase

4. **Failure Analysis (Last 7 Days)**
   - Pie chart: Breakdown of failure reasons
   - Table: Top 5 failing processors

5. **Dependency Check Results (Last 7 Days)**
   - Heatmap: Table completeness by date
   - Green = 100%, Yellow = 80-99%, Red = <80%

### 6.3 Alerts

#### Alert Configuration

**Alert: Pipeline Stuck**
```yaml
name: pipeline_stuck
condition: >
  Any phase in status 'in_progress' for > 2 hours (same-day)
  or > 6 hours (overnight)
severity: CRITICAL
channels: [email, slack]
message: >
  Pipeline stuck: {phase} for {game_date} in {mode} mode
  has been in_progress for {duration} hours.
  Expected processors: {expected}
  Completed processors: {completed}
  Missing: {missing}
action: >
  Check orchestrator logs and Firestore state.
  Consider manual trigger or self-heal.
```

**Alert: Dependency Check Failed**
```yaml
name: dependency_check_failed
condition: >
  Dependency check resulted in FAIL decision
severity: ERROR
channels: [email]
message: >
  Dependency check failed for {phase} on {game_date}.
  Completeness: {completeness}%
  Quality: {quality}
  Issues: {issues}
action: >
  Review missing data. Check upstream scrapers.
  May need manual data fix or re-scrape.
```

**Alert: Low Quality Predictions**
```yaml
name: low_quality_predictions
condition: >
  Phase 5 completed with quality_score < 0.85
severity: WARNING
channels: [email]
message: >
  Predictions generated with low quality score: {quality}
  Game date: {game_date}
  Completeness: {completeness}%
  May need re-run after more data arrives.
action: >
  Monitor prediction performance.
  Consider re-running after late data arrives.
```

**Alert: SLO Violation**
```yaml
name: slo_violation_end_to_end
condition: >
  End-to-end latency > SLO threshold
severity: WARNING
channels: [slack]
message: >
  SLO violation: Pipeline took {latency} minutes for {game_date}.
  SLO: {slo_minutes} minutes
  Mode: {mode}
action: >
  Review processor performance.
  Check for slowdowns or failures.
```

**Alert: Self-Heal Triggered**
```yaml
name: self_heal_triggered
condition: >
  Self-heal function triggered phase that orchestrator should have
severity: INFO
channels: [slack]
message: >
  Self-heal triggered {phase} for {game_date}.
  This indicates orchestrator cascade failed.
  Review orchestrator logs.
action: >
  Investigate why cascade didn't trigger.
  Check Firestore _triggered flag.
```

### 6.4 Observability Tools

#### Cloud Logging Queries

**View orchestrator decisions:**
```
resource.type="cloud_function"
resource.labels.function_name=~"orchestrator"
jsonPayload.decision=~"PROCEED|WAIT|FAIL"
timestamp >= "2025-12-31T00:00:00Z"
```

**Find stuck pipelines:**
```
resource.type="cloud_function"
jsonPayload.status="in_progress"
timestamp < "2025-12-31T10:00:00Z"  -- Started > 2 hours ago
```

**Dependency check failures:**
```
resource.type="cloud_function"
textPayload=~"Dependency check"
severity >= ERROR
```

#### Trace Integration

**Correlation ID tracing:**
```python
# In orchestrator
import sentry_sdk

with sentry_sdk.start_transaction(op="orchestration", name=f"{phase}_to_{next_phase}"):
    sentry_sdk.set_tag("game_date", game_date)
    sentry_sdk.set_tag("mode", mode)
    sentry_sdk.set_tag("correlation_id", correlation_id)

    # Perform orchestration
    result = check_dependencies(...)

    if result.decision == Decision.FAIL:
        sentry_sdk.capture_message(f"Dependency check failed: {result.message}", level="error")
```

---

## 7. Migration Plan

### 7.1 Migration Phases

#### Phase 1: Infrastructure Setup (Week 1)

**Tasks:**
1. Create new BigQuery tables (orchestration_events, dependency_check_log)
2. Create new Pub/Sub topics (orchestration-status, dependency-check-failed, slo-violation)
3. Deploy intelligent-dependency-checker function
4. Deploy orchestration-state-monitor function

**Validation:**
- Tables created and schemas validated
- Topics created and subscriptions configured
- Functions deployed and health checks passing

**Rollback:** Delete resources, no impact on production

#### Phase 2: Firestore Schema Migration (Week 1)

**Tasks:**
1. Update Firestore document structure to include mode suffix
2. Migrate existing documents to new format
3. Update cleanup function to handle new format

**Validation:**
- Read/write to new document format works
- Old documents still accessible
- Cleanup function doesn't delete active documents

**Rollback:** Revert document format, keep old docs

#### Phase 3: Orchestrator Updates (Week 2)

**Tasks:**
1. Update phase2-to-phase3-orchestrator to v3.0
2. Update phase3-to-phase4-orchestrator to v3.0
3. Update phase4-to-phase5-orchestrator to v3.0
4. Update phase5-to-phase6-orchestrator to v3.0

**Changes per orchestrator:**
- Add mode detection
- Add dependency checking
- Add dual state management
- Add mode-specific expected processor lists

**Deployment strategy:**
- Deploy to staging first
- Test with manual triggers
- Deploy to production (one at a time)
- Monitor for 48 hours before next

**Validation:**
- Manual trigger test passes
- Firestore and BigQuery logging works
- No duplicate triggers
- Cascades work end-to-end

**Rollback:** Revert to v2.0 (monitoring-only)

#### Phase 4: Scheduler Updates (Week 2)

**Tasks:**
1. Update scheduler messages to include processing_mode
2. Add retry logic to schedulers
3. Convert schedulers to fallback-only (cascade is primary)

**Validation:**
- Schedulers still fire at correct times
- Mode correctly set in messages
- Cascades happen before schedulers

**Rollback:** Revert scheduler messages

#### Phase 5: Monitoring Setup (Week 3)

**Tasks:**
1. Create Looker Studio dashboards
2. Configure Cloud Monitoring alerts
3. Set up Slack integration
4. Create runbooks for new alerts

**Validation:**
- Dashboards display data
- Alerts fire for test conditions
- Slack messages received

**Rollback:** Disable alerts, keep dashboards

#### Phase 6: Full Cutover (Week 3)

**Tasks:**
1. Enable event-driven cascades as primary
2. Demote schedulers to fallback-only
3. Enable self-heal as safety net
4. Monitor for 1 week

**Validation:**
- Cascades trigger 95%+ of the time
- Schedulers rarely fire
- Self-heal rarely needed
- SLOs met

**Rollback:** Re-enable schedulers as primary

### 7.2 Testing Strategy

#### Unit Tests

```python
# Test dependency checker
def test_dependency_checker_overnight_mode():
    checker = IntelligentDependencyChecker()
    result = checker.check_dependencies(
        phase='phase3',
        game_date='2025-12-31',
        mode='overnight',
        required_tables=[
            {'table': 'nba_raw.player_boxscores', 'expected_min': 200}
        ]
    )
    assert result.decision in (Decision.PROCEED, Decision.WAIT)

# Test mode detection
def test_mode_detection_same_day():
    message = {'game_date': '2025-12-31'}
    current_time = datetime(2025, 12, 31, 11, 0, 0, tzinfo=pytz.timezone('America/New_York'))
    mode = detect_processing_mode(message, current_time)
    assert mode == 'same_day'

# Test orchestrator logic
def test_orchestrator_mode_aware_expected_processors():
    expected = get_expected_processors('phase3', 'same_day')
    assert len(expected) == 2
    assert 'upcoming_player_game_context' in expected
```

#### Integration Tests

```python
# Test end-to-end cascade (Phase 2 → Phase 6)
def test_end_to_end_cascade_same_day():
    """
    Simulate full pipeline cascade for same-day mode.
    """
    game_date = '2025-12-31'
    mode = 'same_day'

    # 1. Trigger Phase 2 processors
    for processor in ['bdl_player_boxscores', 'odds_api_game_lines']:
        publish_completion('phase2', processor, game_date, mode)

    # Wait for Phase 3 trigger
    time.sleep(5)

    # 2. Verify Phase 3 triggered
    phase3_started = check_phase_started('phase3', game_date, mode)
    assert phase3_started

    # 3. Trigger Phase 3 processors
    for processor in ['upcoming_player_game_context', 'upcoming_team_game_context']:
        publish_completion('phase3', processor, game_date, mode)

    # Wait for Phase 4 trigger
    time.sleep(5)

    # 4. Verify Phase 4 triggered
    phase4_started = check_phase_started('phase4', game_date, mode)
    assert phase4_started

    # 5. Continue through Phase 6
    # ...

    # Final: Verify end-to-end latency
    latency_minutes = get_end_to_end_latency(game_date, mode)
    assert latency_minutes < 120  # < 2 hours for same-day
```

#### Load Tests

```bash
# Simulate 100 concurrent processors completing
for i in {1..100}; do
  gcloud pubsub topics publish nba-phase2-raw-complete \
    --message="{\"processor_name\":\"processor_$i\",\"game_date\":\"2025-12-31\",\"status\":\"success\"}" &
done

# Verify: No duplicate triggers, all processors recorded
```

### 7.3 Rollback Procedures

**Rollback Decision Criteria:**
- Cascade failure rate > 20%
- Duplicate triggers detected
- Firestore transaction conflicts > 50/day
- End-to-end latency increases > 50%

**Rollback Steps:**

1. **Immediate (< 5 minutes):**
   ```bash
   # Re-enable schedulers as primary
   gcloud scheduler jobs update same-day-phase3 --description="PRIMARY"
   gcloud scheduler jobs update same-day-phase4 --description="PRIMARY"
   gcloud scheduler jobs update same-day-predictions --description="PRIMARY"
   ```

2. **Within 1 hour:**
   ```bash
   # Revert orchestrators to v2.0
   ./bin/orchestrators/deploy_phase2_to_phase3.sh --version=v2.0
   ./bin/orchestrators/deploy_phase3_to_phase4.sh --version=v2.0
   ./bin/orchestrators/deploy_phase4_to_phase5.sh --version=v2.0
   ```

3. **Within 24 hours:**
   - Analyze failure logs
   - Fix bugs
   - Re-test in staging
   - Plan re-deployment

---

## 8. Risk Mitigation

### 8.1 Identified Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Firestore unavailable** | Low | Critical | Implement fallback to scheduler-only mode |
| **Dependency check too slow** | Medium | Medium | Cache results, parallel queries, timeout |
| **Cascade infinite loop** | Low | High | `_triggered` flag, correlation tracking, circuit breaker |
| **Mode detection wrong** | Medium | Medium | Explicit mode in messages, validation |
| **BigQuery logging fails** | Medium | Low | Async logging, don't block orchestration |
| **Increased Cloud costs** | Low | Low | Monitor function invocations, optimize queries |

### 8.2 Circuit Breakers

**Orchestrator Circuit Breaker:**
```python
class OrchestratorCircuitBreaker:
    """
    Prevents infinite loops and runaway cascades.
    """

    def __init__(self):
        self.failure_counts = {}  # {game_date_phase: count}
        self.max_failures = 5
        self.reset_after_seconds = 3600

    def check_and_record(self, game_date: str, phase: str) -> bool:
        """
        Check if circuit is open (too many failures).

        Returns:
            True if safe to proceed, False if circuit open
        """
        key = f"{game_date}_{phase}"

        # Get failure count
        if key not in self.failure_counts:
            self.failure_counts[key] = {'count': 0, 'first_failure': None}

        record = self.failure_counts[key]

        # Check if circuit is open
        if record['count'] >= self.max_failures:
            # Check if enough time passed to reset
            if record['first_failure']:
                elapsed = (datetime.now() - record['first_failure']).total_seconds()
                if elapsed > self.reset_after_seconds:
                    # Reset circuit
                    self.failure_counts[key] = {'count': 0, 'first_failure': None}
                    logger.info(f"Circuit breaker reset for {key}")
                    return True
                else:
                    logger.error(f"Circuit breaker OPEN for {key} (failures={record['count']})")
                    return False

        return True

    def record_failure(self, game_date: str, phase: str):
        """Record a failure."""
        key = f"{game_date}_{phase}"
        if key not in self.failure_counts:
            self.failure_counts[key] = {'count': 0, 'first_failure': datetime.now()}

        self.failure_counts[key]['count'] += 1
        if self.failure_counts[key]['first_failure'] is None:
            self.failure_counts[key]['first_failure'] = datetime.now()

    def record_success(self, game_date: str, phase: str):
        """Record a success (reset on success)."""
        key = f"{game_date}_{phase}"
        if key in self.failure_counts:
            del self.failure_counts[key]
```

**Usage in orchestrator:**
```python
circuit_breaker = OrchestratorCircuitBreaker()

def orchestrate_phase3_to_phase4(cloud_event):
    message_data = parse_pubsub_message(cloud_event)
    game_date = message_data['game_date']

    # Check circuit breaker
    if not circuit_breaker.check_and_record(game_date, 'phase3'):
        logger.error(f"Circuit breaker OPEN, skipping orchestration for {game_date}")
        notify_error(
            subject="Orchestrator Circuit Breaker Triggered",
            message=f"Phase 3→4 orchestrator circuit breaker open for {game_date}. "
                    f"Too many failures, manual intervention required."
        )
        return

    try:
        # Normal orchestration logic
        result = check_dependencies(...)

        if result.decision == Decision.FAIL:
            circuit_breaker.record_failure(game_date, 'phase3')
        else:
            circuit_breaker.record_success(game_date, 'phase3')

    except Exception as e:
        circuit_breaker.record_failure(game_date, 'phase3')
        raise
```

### 8.3 Graceful Degradation

**Fallback Hierarchy:**

```
1. Event-driven cascade (primary)
   ├─► Dependency check passes
   └─► Trigger next phase

2. Scheduler fallback (if cascade fails)
   ├─► Scheduler fires at scheduled time
   └─► Triggers phase even if dependency check would fail

3. Self-heal (if scheduler fails)
   ├─► Periodic check (every 15 minutes)
   ├─► Detect missing phases
   └─► Force-trigger with alerts

4. Manual intervention (if self-heal fails)
   ├─► Operator monitors alerts
   └─► Manual trigger via script or UI
```

**Implementation:**
```python
# In scheduler payload
{
  "game_date": "2025-12-31",
  "trigger_source": "scheduler",
  "fallback_mode": true,  # Indicates this is a fallback trigger
  "skip_dependency_check": false,  # Still check, but proceed anyway
  "alert_if_cascade_failed": true  # Alert that cascade didn't work
}
```

**Self-heal function:**
```python
@functions_framework.http
def self_heal_orchestration(request):
    """
    Periodic self-heal function.
    Detects stuck pipelines and force-triggers missing phases.
    """
    # Check Firestore for incomplete phases
    today = datetime.now(pytz.timezone('America/New_York')).date()

    for mode in ['same_day', 'overnight', 'tomorrow']:
        # Check each phase
        for phase in ['phase2', 'phase3', 'phase4', 'phase5']:
            doc = db.collection(f'{phase}_completion').document(f'{today}_{mode}').get()

            if doc.exists:
                data = doc.to_dict()
                triggered = data.get('_triggered', False)

                if not triggered:
                    # How long has it been incomplete?
                    completed_at = data.get('_completed_at')
                    if completed_at:
                        elapsed = (datetime.now() - completed_at).total_seconds() / 60

                        # If incomplete for > threshold, force-trigger
                        thresholds = {'same_day': 30, 'overnight': 60, 'tomorrow': 120}
                        if elapsed > thresholds.get(mode, 30):
                            logger.warning(
                                f"Self-heal: {phase} incomplete for {elapsed} minutes, force-triggering"
                            )

                            # Force-trigger next phase
                            next_phase = get_next_phase(phase)
                            trigger_phase(next_phase, today, mode, trigger_source='self_heal')

                            # Alert
                            notify_warning(
                                subject=f"Self-Heal Triggered: {phase}→{next_phase}",
                                message=f"Cascade failed for {today} {mode} mode. "
                                        f"Self-heal force-triggered {next_phase}."
                            )

    return jsonify({'status': 'ok', 'checked_modes': ['same_day', 'overnight', 'tomorrow']})
```

### 8.4 Monitoring During Migration

**Migration Monitoring Dashboard:**

During migration (Weeks 1-3), create special dashboard:

1. **Cascade vs Scheduler Triggers**
   - Bar chart: # triggers by source (cascade vs scheduler vs self-heal)
   - Goal: Cascade > 95%

2. **Firestore Transaction Conflicts**
   - Line chart: # conflicts per hour
   - Goal: < 5 per hour

3. **Dependency Check Latency**
   - Histogram: Check duration distribution
   - Goal: p95 < 30 seconds

4. **Migration Progress**
   - Progress bar: % of orchestrators on v3.0
   - Status: Green if no errors, Yellow if warnings, Red if errors

**Migration Alerts:**

```yaml
migration_cascade_failure_rate:
  condition: cascade_success_rate < 80%
  severity: CRITICAL
  message: Migration issue - cascade failure rate too high
  action: Consider rollback to v2.0

migration_duplicate_triggers:
  condition: duplicate_trigger_count > 5 per day
  severity: CRITICAL
  message: Duplicate triggers detected
  action: Check Firestore _triggered logic

migration_performance_degradation:
  condition: dependency_check_p95_latency > 60 seconds
  severity: WARNING
  message: Dependency checks too slow
  action: Optimize queries or add caching
```

---

## 9. Success Criteria

### 9.1 Functional Requirements

- [ ] Event-driven cascades trigger next phase 95%+ of the time
- [ ] Dependency checks complete in < 30 seconds (p95)
- [ ] No duplicate triggers (0 in 30 days)
- [ ] No infinite loops (0 in 30 days)
- [ ] Mode detection 100% accurate
- [ ] Firestore and BigQuery state always in sync
- [ ] Self-heal needed < 20% of the time

### 9.2 Performance Requirements

- [ ] End-to-end latency (same-day) < 2 hours (SLO)
- [ ] End-to-end latency (overnight) < 6 hours (SLO)
- [ ] Phase 3 completeness >= 80% (same-day mode)
- [ ] Phase 3 completeness = 100% (overnight mode)
- [ ] Quality score >= 0.90 across all modes

### 9.3 Operational Requirements

- [ ] Dashboards show real-time status
- [ ] Alerts fire within 5 minutes of issue
- [ ] Runbooks exist for all alert types
- [ ] Rollback procedure tested and documented
- [ ] On-call team trained on new system

### 9.4 Cost Requirements

- [ ] Firestore costs < $50/month
- [ ] Cloud Function invocations < 10M/month
- [ ] BigQuery queries < 100GB/month
- [ ] Total incremental cost < $200/month

---

## 10. Next Steps

### Immediate (Week 1)

1. [ ] Review and approve this design document
2. [ ] Create GitHub issues for each migration phase
3. [ ] Set up staging environment for testing
4. [ ] Create BigQuery tables (orchestration_events, etc.)
5. [ ] Deploy intelligent-dependency-checker (staging)

### Short-term (Weeks 2-3)

1. [ ] Update all orchestrators to v3.0 (staging)
2. [ ] Test end-to-end cascade (staging)
3. [ ] Create dashboards and alerts
4. [ ] Deploy to production (phased)
5. [ ] Monitor for 1 week

### Long-term (Month 2+)

1. [ ] Optimize dependency check performance
2. [ ] Add ML-based anomaly detection
3. [ ] Implement auto-scaling based on game count
4. [ ] Add predictive alerting (warn before SLO violation)
5. [ ] Integrate with broader observability platform

---

## Appendix A: File Changes

**New Files:**

```
orchestration/
  dependency_checker.py (NEW)
  state_manager.py (NEW)
  mode_detector.py (NEW)
  circuit_breaker.py (NEW)

orchestration/cloud_functions/
  intelligent_dependency_checker/ (NEW)
    main.py
    requirements.txt
    deploy.sh

  orchestration_state_monitor/ (NEW)
    main.py
    requirements.txt
    deploy.sh

schemas/bigquery/nba_orchestration/
  orchestration_events.sql (NEW)
  phase_completion_log.sql (NEW)
  dependency_check_log.sql (NEW)

bin/orchestrators/
  migrate_firestore_schema.py (NEW)
  cleanup_firestore.py (UPDATED)

docs/02-operations/
  event-driven-orchestration-runbook.md (NEW)
```

**Updated Files:**

```
orchestration/cloud_functions/phase2_to_phase3/main.py (v2.0 → v3.0)
orchestration/cloud_functions/phase3_to_phase4/main.py (v1.1 → v3.0)
orchestration/cloud_functions/phase4_to_phase5/main.py (v1.0 → v3.0)
orchestration/cloud_functions/phase5_to_phase6/main.py (v1.0 → v3.0)

shared/config/orchestration_config.py (add mode-specific configs)

bin/orchestrators/deploy_*.sh (update env vars)
bin/orchestrators/setup_same_day_schedulers.sh (add mode to payload)
```

---

## Appendix B: Cost Analysis

**Current System:**
- Cloud Functions: ~1M invocations/month = $0.40
- Firestore: ~10K writes/month = $0 (free tier)
- Pub/Sub: ~500K messages/month = $0.20
- **Total: ~$0.60/month**

**New System:**
- Cloud Functions: ~5M invocations/month = $2.00 (dependency checks)
- Firestore: ~50K writes/month = $0.15
- BigQuery: ~20GB queries/month = $0.10 (streaming inserts free)
- Pub/Sub: ~2M messages/month = $0.80
- Cloud Monitoring: ~100 alerts/month = $0
- **Total: ~$3.05/month**

**Incremental Cost: +$2.45/month**

**ROI:**
- Time saved debugging: ~10 hours/month = $1000/month (at $100/hr)
- Improved SLO adherence: Better user experience, hard to quantify
- Reduced manual intervention: ~5 hours/month = $500/month

**Net benefit: $1497.55/month**

---

**Document End**

*Created: December 31, 2025*
*Author: System Architecture Team*
*Version: 1.0*
*Status: Ready for Review*
