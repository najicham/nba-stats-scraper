# External Review: Sonnet (Web Chat)

**Date**: 2026-01-26
**Reviewer**: Claude Sonnet (Web Chat)
**Document**: Data Validation & Quality Architecture - Complete Solution Specification

---

## Executive Summary

### The Core Problem

Your NBA Props Platform has discovered that **81% of this season's game data was backfilled late**, causing cascade contamination:

```
Game played → Data missing → Rolling averages computed without it →
Predictions generated with wrong averages → Data backfilled later →
Contamination remains in downstream tables
```

### Current Approach vs Recommended Approach

**Current (Reactive)**:
- Build elaborate validation to detect contamination after it happens
- Reprocess contaminated data when found
- Repeat cycle when new gaps occur

**Recommended (Proactive)**:
- **Prevent** contamination by checking dependencies before processing
- **Track** data quality through completeness scores
- **Detect** issues through automated validation
- **Remediate** automatically when possible

### Core Insight

You're treating **symptoms** (contaminated data) rather than preventing the **disease** (processing with incomplete dependencies).

**The solution**: Add a **prevention layer** that verifies data completeness before processing, then enhance validation to catch what slips through.

### Architecture Change

```
BEFORE:
Scraper → Raw → Analytics → Precompute → Predictions
                    ↓
              (Validation finds contamination later)

AFTER:
Scraper → Raw → [Readiness Check] → Analytics → Precompute → Predictions
                        ↓                ↓            ↓            ↓
                   Block if incomplete   Tag quality  Tag quality  Tag quality
                        ↓
              (Validation catches edge cases only)
```

---

## Problem Analysis

### What Happened

**Timeline of Contamination**:
1. **Game Day**: NBA game played
2. **Day+1**: Scraper fails to get data (API timeout, missing data)
3. **Day+2**: Pipeline runs anyway, computes rolling averages without missing game
4. **Day+3**: Predictions generated using contaminated rolling averages
5. **Day+7**: Missing game data finally backfilled
6. **Result**: Days 2-6 have contaminated downstream data

### Why Current Validation Isn't Enough

**Your three validation skills**:
1. `/validate-daily` - Checks if today's pipeline ran (not if data is correct)
2. `/validate-historical` - Checks if data exists (not if it's correct)
3. `/validate-lineage` - Checks if data is correct (but only after contamination)

**All three are detective controls** (find problems after they happen).
**None are preventive controls** (stop problems from happening).

### Root Cause

**Optimistic processing**:
```python
# Current pattern
def compute_rolling_average(player_id, game_date):
    # Get last 10 games
    games = query_games(player_id, game_date, limit=10)

    # Problem: What if only 7 games exist?
    # It computes avg of 7 games, not 10
    # No warning, no quality flag, no alert

    return mean([g.points for g in games])
```

**Should be defensive processing**:
```python
# Better pattern
def compute_rolling_average(player_id, game_date):
    # Get last 10 games
    games = query_games(player_id, game_date, limit=10)

    # Verify we have what we expect
    if len(games) < 10:
        quality_flag = "INCOMPLETE_WINDOW"
        completeness_score = len(games) / 10

        # Decide: fail, warn, or proceed with flag
        if completeness_score < 0.7:
            raise InsufficientDataError(
                f"Only {len(games)}/10 games available"
            )

    return {
        'value': mean([g.points for g in games]),
        'quality_score': completeness_score,
        'flags': [quality_flag] if quality_flag else []
    }
```

---

## Recommended Architecture

### Three-Layer Approach

```
┌─────────────────────────────────────────────────────────────────┐
│                     LAYER 1: PREVENTION                          │
│  Verify dependencies before processing, block if incomplete     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Components:                                                     │
│  - Dependency Checker (verifies upstream data ready)            │
│  - Readiness Gates (block processing if not ready)              │
│  - Completeness Metadata (track what was available)             │
│  - Processing Cutoffs (wait for data to stabilize)              │
│                                                                  │
│  Goal: Make contamination impossible                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────┐
│                     LAYER 2: QUALITY TRACKING                    │
│  Tag every record with quality metadata as it's processed       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Components:                                                     │
│  - Quality Scores (0-1 scale for each record)                   │
│  - Completeness Flags (COMPLETE, PARTIAL, INCOMPLETE)           │
│  - Dependency Timestamps (when upstream data was loaded)        │
│  - Processing Context (daily, backfill, manual)                 │
│                                                                  │
│  Goal: Make quality visible and traceable                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

                              ↓

┌─────────────────────────────────────────────────────────────────┐
│                     LAYER 3: VALIDATION                          │
│  Detect edge cases and validate fixes                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Components:                                                     │
│  - Lineage Validation (recompute and compare)                   │
│  - Statistical Validation (detect anomalies)                    │
│  - Metadata Validation (check timestamps and flags)             │
│  - Cross-table Validation (verify consistency)                  │
│                                                                  │
│  Goal: Catch what prevention missed                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Specifications

### Layer 1: Prevention

#### Component 1.1: Dependency Checker

**Purpose**: Verify upstream data is ready before processing

```python
class ReadinessStatus(Enum):
    """Recommendation for whether to proceed with processing."""
    PROCEED = "proceed"                    # All dependencies satisfied
    PROCEED_WITH_WARNING = "proceed_warn"  # Minor issues, safe to proceed
    WAIT = "wait"                          # Wait for data to arrive
    FAIL = "fail"                          # Critical issue, cannot proceed


@dataclass
class ReadinessResult:
    """Result of dependency readiness check."""

    status: ReadinessStatus
    is_ready: bool
    confidence_score: float  # 0-1 scale
    message: str

    # Details
    expected_games: int = 0
    actual_games: int = 0
    missing_games: List[str] = None
    quality_issues: List[str] = None


class DependencyChecker:
    """
    Check if dependencies are satisfied before processing.

    Usage:
        checker = DependencyChecker(bq_client)

        # Check if games are ready for a date
        result = checker.check_games_ready(date(2026, 1, 26))

        if result.status == ReadinessStatus.WAIT:
            logger.warning(f"Not ready: {result.message}")
            delay_processing()
        elif result.status == ReadinessStatus.PROCEED_WITH_WARNING:
            logger.warning(f"Proceeding with warning: {result.message}")
            mark_as_incomplete(result.completeness_score)
        else:
            logger.info("Ready to process")
            process()
    """
```

#### Component 1.2: Processing Gates

**Purpose**: Block processing when dependencies not ready

```python
class ProcessingGate:
    """
    Control when processing can proceed based on data readiness.

    Usage:
        gate = ProcessingGate(dependency_checker)

        # Check if can process
        result = gate.check_can_process(
            downstream_table='nba_analytics.player_game_summary',
            game_date=date(2026, 1, 26),
            upstream_tables=['nba_raw.bdl_player_boxscores']
        )

        if result.status == ReadinessStatus.FAIL:
            raise ProcessingBlockedError(result.message)

        if result.status == ReadinessStatus.WAIT:
            delay_processing(hours=2)
            return

        # Proceed with processing, attaching quality metadata
        quality = DataQuality.from_readiness_result(result)
        context = ProcessingContext.from_readiness_result(result)

        process_data(quality=quality, context=context)
    """
```

### Layer 2: Quality Tracking

#### Completeness Metadata Schema

```sql
-- Add to ALL analytics and downstream tables

ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS data_quality STRUCT<
  overall_score FLOAT64,           -- 0-1 scale, weighted quality
  completeness_score FLOAT64,      -- Ratio of actual/expected data
  timeliness_score FLOAT64,        -- Based on processing delay
  accuracy_score FLOAT64,          -- From validation checks
  flags ARRAY<STRING>,             -- Quality flags/warnings
  confidence STRING                -- HIGH, MEDIUM, LOW
>;

ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS processing_context STRUCT<
  execution_type STRING,           -- daily, backfill, manual
  expected_games INT64,            -- For this date
  actual_games INT64,              -- Available when processed
  missing_games ARRAY<STRING>,     -- IDs of missing games
  quality_issues ARRAY<STRING>     -- Specific issues found
>;
```

#### Python Structures

```python
@dataclass
class DataQuality:
    """
    Data quality metadata for any record.

    Tracks completeness, timeliness, and accuracy of data.
    Propagates through pipeline so downstream knows input quality.
    """

    overall_score: float  # 0-1, weighted combination of below
    completeness_score: float  # Ratio of actual/expected data
    timeliness_score: float  # Based on processing delay
    accuracy_score: float = 1.0  # From validation (1.0 = not validated)

    flags: List[str] = field(default_factory=list)
    confidence: QualityConfidence = QualityConfidence.HIGH

    # Optional context
    window_completeness: Optional[float] = None  # For rolling calcs
    input_quality_score: Optional[float] = None  # For derived tables
```

### Layer 3: Enhanced Validation

#### Recompute Validator

```python
class RecomputeValidator:
    """
    Validate data by recomputing and comparing to stored values.

    Usage:
        validator = RecomputeValidator(bq_client)

        # Validate single record
        result = validator.validate_record(
            table='nba_precompute.player_composite_factors',
            record_id={'player_id': 123, 'game_date': '2026-01-15'}
        )

        if not result.is_valid:
            logger.warning(f"Contamination detected: {result.message}")
            trigger_reprocessing(record_id)

        # Validate date range (aggregate)
        result = validator.validate_date_range(
            table='nba_precompute.player_composite_factors',
            start_date=date(2025, 12, 1),
            end_date=date(2026, 1, 1)
        )
    """
```

---

## Prioritized Action Plan

### Week 1: Critical Prevention (Blocks New Contamination)

**Goal**: Stop new contamination from occurring

**Tasks**:

1. **Day 1-2: Implement Dependency Checker** (CRITICAL)
   - Create `shared/validation/dependency_checker.py`
   - Implement `DependencyChecker` class
   - Implement `ReadinessResult` dataclass
   - Write unit tests

2. **Day 2-3: Implement Data Quality Models** (CRITICAL)
   - Create `shared/models/data_quality.py`
   - Implement `DataQuality`, `ProcessingContext` classes
   - Add schema migrations for quality columns

3. **Day 3-4: Implement Processing Gates** (CRITICAL)
   - Create `shared/processors/processing_gate.py`
   - Integrate with `BaseProcessor`

4. **Day 4-5: Deploy to Production**
   - Update all Phase 3+ processors to use gates
   - Deploy schema changes
   - Monitor first day of processing

**Deliverable**: Pipeline blocks on incomplete data, tags partial data with quality scores

### Week 2: Detection & Quantification

**Goal**: Understand extent of existing contamination

**Tasks**:
- Implement Recompute Validator
- Run validation on 2025-26 season
- Generate contamination report
- Create reprocessing plan

### Week 3: Remediation

**Goal**: Clean the dataset

**Tasks**:
- Implement reprocessing framework
- Execute reprocessing
- Validate fixes

### Week 4: Monitoring & Observability

**Goal**: Continuous data quality monitoring

**Tasks**:
- Create validation dashboard
- Set up automated validation
- Documentation

---

## Success Metrics

### Week 1 (Prevention)

- [ ] Dependency checker deployed
- [ ] Processing gates block incomplete data
- [ ] Quality metadata attached to all new records
- [ ] Zero new contamination incidents

### Week 2 (Detection)

- [ ] Contamination report complete
- [ ] Know exact extent of contamination
- [ ] Reprocessing plan approved

### Week 3 (Remediation)

- [ ] All contaminated dates reprocessed
- [ ] >95% records have quality score >0.9
- [ ] <5% contamination rate remaining

### Week 4 (Monitoring)

- [ ] Quality dashboard operational
- [ ] Daily validation running
- [ ] Alerts configured
- [ ] Team trained on new system

---

## Summary

**The Core Change**: Shift from "detect and fix" to "prevent and track"

**Three Layers**:
1. **Prevention**: Verify dependencies before processing
2. **Quality Tracking**: Tag every record with quality metadata
3. **Validation**: Catch edge cases and verify fixes

**Expected Outcomes**:
- Zero new contamination (prevention blocks it)
- Clean historical data (remediation fixes it)
- Ongoing visibility (monitoring tracks it)
- Self-healing system (auto-remediation when possible)

**Timeline**: 4 weeks to full implementation, with prevention deployed in Week 1

**Next Steps**: Begin with Week 1 implementation, starting with `DependencyChecker` class

---

**End of Review**
