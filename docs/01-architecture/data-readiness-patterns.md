# Data Readiness Patterns

**Status:** v1.0 Production
**Created:** 2025-11-29
**Category:** Pipeline Safety & Data Integrity
**Phase:** All phases (cross-cutting concern)

---

## Overview

This document consolidates all data readiness mechanisms that ensure processors don't start without proper upstream data. These patterns prevent cascading failures, incomplete predictions, and data quality issues.

**Key Question This Document Answers:**
> "What checks run when I process date X?"

---

## Document Organization

The patterns are organized by **when they fire** in the processor lifecycle:

1. **Pre-Run Guards** - Block processing before it starts
   - Deduplication Check
   - Defensive Checks (Strict Mode)
   - Bootstrap Period Check
   - Circuit Breaker Check

2. **Data Quality Gates** - Validate upstream data exists and is fresh
   - Dependency Checking
   - Completeness Checking
   - Source Coverage

3. **Processing Optimizations** - Reduce unnecessary work
   - Change Detection
   - Smart Skip
   - Early Exit

4. **Output Safeguards** - Ensure reliable writes and cascades
   - Smart Idempotency
   - Pipeline Integrity / Cascade Control
   - Run History Tracking

---

## Quick Reference Table

| Pattern | Phase | When It Fires | What It Prevents | Implementation |
|---------|-------|---------------|------------------|----------------|
| [Deduplication Check](#1-deduplication-check) | 2 | Before run history | Duplicate processing on Pub/Sub retries | `processor_base.py:139-154` |
| [Dependency Checking](#2-dependency-checking) | 3, 4 | Before data extraction | Processing with missing/stale upstream data | `analytics_base.py:612-706` |
| [Defensive Checks](#3-defensive-checks-strict-mode) | 3, 4 | After dependency check | Cascade failures, processing with gaps | `analytics_base.py:274-377` |
| [Source Coverage](#4-source-coverage) | 3 | During data extraction | Processing without quality tracking | `source-coverage/` docs |
| [Bootstrap Period](#5-bootstrap-period-handling) | 4 | Early in run() | Bad early-season predictions | `bootstrap-period-overview.md` |
| [Pipeline Integrity](#6-pipeline-integrity--cascade-control) | All | During backfills | Uncontrolled cascades, missing gaps | `pipeline-integrity.md` |
| [Smart Idempotency](#7-smart-idempotency) | 2, 3, 4 | Before save | Duplicate writes, wasted processing | `smart-idempotency.md` |
| [Completeness Checking](#8-completeness-checking) | 4 | During precompute | Incomplete historical windows | `completeness_checker.py` |
| [Change Detection](#9-change-detection) | 3 | Before data extraction | Unnecessary full-batch processing | `analytics_base.py:379-456` |
| [Run History Tracking](#10-run-history-tracking) | All | Start/end of run() | No audit trail, can't check upstream status | `RunHistoryMixin` |
| [Smart Skip](#11-smart-skip) | 3, 4 | Before run() | Processing when irrelevant sources triggered | `SmartSkipMixin` |
| [Early Exit](#12-early-exit) | 3, 4 | Before run() | Processing no-game days, offseason, old dates | `EarlyExitMixin` |
| [Circuit Breaker](#13-circuit-breaker) | 3, 4, 5 | Before processing entity | Infinite retry loops on bad entities | `CircuitBreakerMixin` |

---

## Pattern Usage by Processor

### Phase 2 (Raw) Processors

| Processor | SmartIdempotency | RunHistory | Notes |
|-----------|------------------|------------|-------|
| `NbacGamebookProcessor` | ✅ | ✅ | Primary stats source |
| `BdlBoxscoresProcessor` | ✅ | ✅ | Fallback stats source |
| `OddsApiPropsProcessor` | ✅ | ✅ | Prop lines source |
| All other Phase 2 | ✅ | ✅ | via `ProcessorBase` |

### Phase 3 (Analytics) Processors

| Processor | Dependencies | SmartSkip | EarlyExit | CircuitBreaker | ChangeDetect | Quality |
|-----------|--------------|-----------|-----------|----------------|--------------|---------|
| `PlayerGameSummaryProcessor` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `TeamDefenseGameSummaryProcessor` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `TeamOffenseGameSummaryProcessor` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `UpcomingPlayerGameContextProcessor` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `UpcomingTeamGameContextProcessor` | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |

### Phase 4 (Precompute) Processors

| Processor | Dependencies | SmartIdempotency | Bootstrap | Completeness | CircuitBreaker |
|-----------|--------------|------------------|-----------|--------------|----------------|
| `PlayerShotZoneAnalysisProcessor` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `TeamDefenseZoneAnalysisProcessor` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `PlayerCompositeFactorsProcessor` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `PlayerDailyCacheProcessor` | ✅ | ✅ | ✅ | ✅ (multi-window) | ✅ |
| `MLFeatureStoreProcessor` | ✅ | ✅ | ✅ | ✅ | ✅ |

### Phase 5 (Predictions)

| Component | CircuitBreaker | ExecutionLogging | Notes |
|-----------|----------------|------------------|-------|
| `PredictionCoordinator` | ❌ | ✅ | Orchestrates batch |
| `PredictionWorker` | ✅ (system-level) | ✅ | Per-system circuit breakers |

---

## Processing Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROCESSOR RUN LIFECYCLE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. DEDUPLICATION CHECK                                                     │
│     └─ "Was this already processed?" (Pub/Sub retry protection)             │
│                                                                             │
│  2. RUN HISTORY START                                                       │
│     └─ Write 'running' status (enables upstream status checks)              │
│                                                                             │
│  3. BOOTSTRAP PERIOD CHECK (Phase 4 only)                                   │
│     └─ "Is this day 0-6 of season?" → Skip entirely                         │
│                                                                             │
│  4. DEPENDENCY CHECKING                                                     │
│     ├─ "Does upstream data exist?"                                          │
│     ├─ "Is it fresh enough (max_age_hours)?"                                │
│     └─ "Are there enough rows (expected_count_min)?"                        │
│                                                                             │
│  5. DEFENSIVE CHECKS (strict_mode=True)                                     │
│     ├─ "Did upstream processor succeed yesterday?"                          │
│     └─ "Any gaps in lookback window?"                                       │
│                                                                             │
│  6. CHANGE DETECTION (Phase 3)                                              │
│     └─ "Which entities changed?" → Process only those                       │
│                                                                             │
│  7. DATA EXTRACTION                                                         │
│     ├─ SOURCE COVERAGE: Track quality tiers                                 │
│     └─ COMPLETENESS: Compare expected vs actual games                       │
│                                                                             │
│  8. CALCULATION / TRANSFORMATION                                            │
│     └─ SMART IDEMPOTENCY: Hash output, skip if unchanged                    │
│                                                                             │
│  9. SAVE TO BIGQUERY                                                        │
│     └─ CASCADE CONTROL: Publish or skip downstream trigger                  │
│                                                                             │
│ 10. RUN HISTORY COMPLETE                                                    │
│     └─ Write 'success'/'failed' status                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Pattern Details

### 1. Deduplication Check

**Purpose:** Prevent duplicate processing when Pub/Sub retries delivery.

**When:** First thing in `run()`, before run history starts.

**How It Works:**
```python
# processor_base.py:139-154
already_processed = self.check_already_processed(
    processor_name=self.__class__.__name__,
    data_date=data_date,
    stale_threshold_hours=2  # Retry if stuck for > 2 hours
)

if already_processed:
    logger.info(f"⏭️ Skipping {self.__class__.__name__} for {data_date} - already processed")
    return True  # Success (not an error)
```

**Scenario:**
- Pub/Sub delivers message, processor starts
- Network blip, Pub/Sub doesn't receive ACK
- Pub/Sub redelivers message
- Deduplication check sees `status='running'` → skip

**Configuration:** `stale_threshold_hours=2` (retry if previous run stuck)

**Documentation:** Implemented in `processor_base.py`, no separate doc.

---

### 2. Dependency Checking

**Purpose:** Ensure upstream data exists and is fresh before processing.

**When:** After setup, before data extraction.

**How It Works:**
```python
# Child class defines dependencies
def get_dependencies(self) -> dict:
    return {
        'nba_raw.nbac_team_boxscore': {
            'field_prefix': 'source_nbac_boxscore',
            'description': 'Team box score statistics',
            'date_field': 'game_date',
            'check_type': 'date_range',        # or 'lookback', 'existence'
            'expected_count_min': 20,          # Minimum rows required
            'max_age_hours_warn': 24,          # Warning threshold
            'max_age_hours_fail': 72,          # Failure threshold
            'critical': True                   # Fail if missing?
        }
    }

# Base class checks dependencies
dep_check = self.check_dependencies(start_date, end_date)
if not dep_check['all_critical_present']:
    raise ValueError(f"Missing critical dependencies: {dep_check['missing']}")
```

**What Gets Checked:**
1. **Existence:** Does data exist for date range?
2. **Row Count:** Enough rows (`expected_count_min`)?
3. **Freshness:** Data age within thresholds?

**Source Tracking Fields (stored with output):**
- `source_{prefix}_last_updated` - When source was last updated
- `source_{prefix}_rows_found` - How many rows found
- `source_{prefix}_completeness_pct` - Data quality metric
- `source_{prefix}_hash` - For smart reprocessing

**Documentation:**
- [`docs/05-development/guides/processor-patterns/02-dependency-tracking.md`](../05-development/guides/processor-patterns/02-dependency-tracking.md)
- [`docs/08-projects/completed/dependency-checking/`](../08-projects/completed/dependency-checking/)

---

### 3. Defensive Checks (Strict Mode)

**Purpose:** Block processing when upstream processor failed or data has gaps.

**When:** After dependency checking, enabled by `strict_mode=True` (default).

**How It Works:**
```python
# analytics_base.py:274-377, precompute_base.py:637-778

# Check 1: Did yesterday's upstream processor succeed?
status = checker.check_upstream_processor_status(
    processor_name=self.upstream_processor_name,
    data_date=yesterday
)
if not status['safe_to_process']:
    raise DependencyError(f"Upstream {self.upstream_processor_name} failed")

# Check 2: Any gaps in lookback window?
gaps = checker.check_date_range_completeness(
    table=self.upstream_table,
    date_column='game_date',
    start_date=lookback_start,
    end_date=analysis_date
)
if gaps['has_gaps']:
    raise DependencyError(f"{gaps['gap_count']} gaps in historical data")
```

**Scenario:**
```
Monday:  Phase 2 fails for game data
Tuesday: Phase 3 triggered by scheduler
         └─ Defensive check: "Did Phase 2 succeed for Monday?" → NO
         └─ DependencyError raised, alert sent
         └─ Phase 3 blocked until Monday is fixed
```

**Configuration:**
- `strict_mode=True` (default) - Enable checks
- `backfill_mode=True` - Disable checks
- Child class sets: `upstream_processor_name`, `upstream_table`, `lookback_days`

**Documentation:** [`docs/01-architecture/pipeline-integrity.md`](./pipeline-integrity.md)

---

### 4. Source Coverage

**Purpose:** Track data availability from external sources and handle gaps gracefully.

**When:** During data extraction in Phase 3 processors.

**How It Works:**
- Log events to `source_coverage_log` table
- Assign quality tiers: Gold (100%), Silver (75-99%), Bronze (<75%)
- Automatic fallbacks to backup sources
- Daily audit detects silent failures

**Quality Propagation:**
```
Phase 2: Source event logged, quality assessed
    ↓
Phase 3: Quality columns added to output
    ↓
Phase 4: Quality inherited from upstream
    ↓
Phase 5: Prediction confidence capped by quality
```

**Key Components:**
- `QualityMixin` - Track quality in processors
- `FallbackSourceMixin` - Automatic fallback logic
- Daily audit job - Detect silent failures

**Documentation:** [`docs/01-architecture/source-coverage/`](./source-coverage/)

---

### 5. Bootstrap Period Handling

**Purpose:** Handle first 7 days of NBA season when insufficient historical data exists.

**When:** Early in `run()` for Phase 4 processors.

**How It Works:**
```python
# Phase 4 processors check early season
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date

season_year = get_season_year_from_date(analysis_date)
if is_early_season(analysis_date, season_year, days_threshold=7):
    logger.info(f"⏭️ Skipping {analysis_date}: early season period (day 0-6)")
    self.raw_data = None  # Signal skip
    return
```

**Behavior:**
| Season Day | Action | Reason |
|------------|--------|--------|
| 0-6 | Skip entirely | Not enough games for L5/L10/L30 |
| 7+ | Process normally | Partial windows OK with completeness metadata |

**Documentation:** [`docs/01-architecture/bootstrap-period-overview.md`](./bootstrap-period-overview.md)

---

### 6. Pipeline Integrity / Cascade Control

**Purpose:** Control Pub/Sub cascades during backfills and detect gaps.

**When:** During backfills (manual) and daily operations (automatic).

**How It Works:**
```bash
# Backfill Mode: Disable cascades
python processor.py --date 2023-10-15 --skip-downstream-trigger

# Verify completeness before next phase
python verify_phase2.py --fail-on-gaps

# Then enable cascades
python phase3_processor.py --start-date 2023-10-15 --end-date 2023-10-15
```

**Cascade Control Flag:**
```python
# In processor opts
skip_downstream = self.opts.get('skip_downstream_trigger', False)

if skip_downstream:
    logger.info("⏸️ Skipping downstream trigger (backfill mode)")
else:
    publisher.publish_completion(...)  # Triggers next phase
```

**Gap Detection:**
```python
gaps = checker.check_date_range_completeness(
    table='nba_analytics.player_game_summary',
    date_column='game_date',
    start_date=date(2023, 10, 1),
    end_date=date(2023, 10, 31)
)
# Returns: has_gaps, missing_dates, coverage_pct
```

**Documentation:** [`docs/01-architecture/pipeline-integrity.md`](./pipeline-integrity.md)

---

### 7. Smart Idempotency

**Purpose:** Skip processing/writing when output would be identical.

**When:** Before saving to BigQuery.

**How It Works:**
```python
# Phase 2: Hash source data
data_hash = compute_hash(source_data)

# Check existing record
existing = query_existing_record(entity_id, date)

if existing and existing.data_hash == data_hash:
    logger.info("Data unchanged - skipping write")
    return

# Data changed - write new record with hash
save_with_hash(transformed_data, data_hash)
```

**Benefits:**
- Saves BigQuery write costs
- Prevents duplicate records
- Enables smart reprocessing decisions

**Documentation:**
- [`docs/05-development/guides/processor-patterns/01-smart-idempotency.md`](../05-development/guides/processor-patterns/01-smart-idempotency.md)
- [`docs/05-development/patterns/smart-idempotency.md`](../05-development/patterns/smart-idempotency.md)

---

### 8. Completeness Checking

**Purpose:** Compare expected games (from schedule) vs actual games to detect missing data.

**When:** During dependency checking and backfill verification.

**How It Works:**
```python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker(bq_client, 'nba-props-platform')

results = checker.check_completeness_batch(
    entity_ids=['LAL', 'GSW', 'BOS'],
    entity_type='team',
    analysis_date=date(2024, 11, 22),
    upstream_table='nba_analytics.team_defense_game_summary',
    upstream_entity_field='defending_team_abbr',
    lookback_window=15,
    window_type='games'
)

# Returns per entity:
# {
#     'LAL': {
#         'expected_count': 17,
#         'actual_count': 15,
#         'completeness_pct': 88.2,
#         'is_production_ready': False
#     }
# }
```

**Production Ready Threshold:** 90% completeness

**Documentation:**
- [`docs/02-operations/completeness-quick-start.md`](../02-operations/completeness-quick-start.md)
- [`docs/08-projects/completed/completeness/`](../08-projects/completed/completeness/)

---

### 9. Change Detection

**Purpose:** Detect which entities changed to enable incremental processing.

**When:** Before data extraction in Phase 3.

**How It Works:**
```python
# If processor implements get_change_detector()
if hasattr(self, 'get_change_detector'):
    self.change_detector = self.get_change_detector()
    self.entities_changed = self.change_detector.detect_changes(game_date=analysis_date)

    if 0 < len(self.entities_changed) < total_entities:
        self.is_incremental_run = True
        logger.info(f"🎯 INCREMENTAL: {len(self.entities_changed)}/{total_entities} changed")
```

**Efficiency Gain:**
- Full batch: Process all 450 players
- Incremental: Process only 5 changed players
- **Result:** 99%+ reduction in processing for mid-day updates

**Passed to Downstream:**
```python
# Phase 3 → Phase 4 message includes
metadata={
    'entities_changed': ['player1', 'player2'],
    'is_incremental': True
}
```

**Documentation:** [`docs/01-architecture/change-detection/`](./change-detection/)

---

### 10. Run History Tracking

**Purpose:** Log all processor runs for debugging, monitoring, and upstream status checks.

**When:** Start and end of every `run()`.

**How It Works:**
```python
# All base classes inherit RunHistoryMixin
class AnalyticsProcessorBase(RunHistoryMixin):
    PHASE = 'phase_3_analytics'
    OUTPUT_TABLE = ''
    OUTPUT_DATASET = 'nba_analytics'

# Start tracking (writes 'running' status)
self.start_run_tracking(
    data_date=data_date,
    trigger_source='pubsub',
    trigger_message_id=message_id,
    parent_processor='Phase2Processor'
)

# Complete tracking (writes 'success' or 'failed')
self.record_run_complete(
    status='success',
    records_processed=100,
    summary=self.stats
)
```

**Table:** `nba_reference.processor_run_history`

**Used By:**
- Defensive checks (upstream processor status)
- Deduplication (already running?)
- Monitoring dashboards
- Alert correlation

**Documentation:** [`docs/07-monitoring/run-history-guide.md`](../07-monitoring/run-history-guide.md)

---

### 11. Smart Skip (SmartSkipMixin)

**Purpose:** Skip processing when triggered by irrelevant source updates.

**When:** Before `run()` begins, checks Pub/Sub message source.

**How It Works:**
```python
class PlayerGameSummaryProcessor(SmartSkipMixin, AnalyticsProcessorBase):
    # Define which Phase 2 sources are relevant to this processor
    RELEVANT_SOURCES = {
        # Player stats sources - RELEVANT
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,

        # Team-level sources - NOT RELEVANT
        'nbac_gamebook_team_stats': False,
        'bdl_team_boxscores': False,

        # Odds/spreads sources - NOT RELEVANT
        'odds_api_spreads': False,
        'odds_api_totals': False,
    }
```

**Scenario:**
- `odds_api_spreads` processor completes and triggers Phase 3
- `PlayerGameSummaryProcessor` receives message
- Smart Skip checks: "Is `odds_api_spreads` in my RELEVANT_SOURCES?"
- Answer: No → Skip processing, log "Skipped: triggered by irrelevant source"

**Benefits:**
- Reduces unnecessary processing by ~70%
- Prevents Phase 3 from running on every Phase 2 completion
- Enables efficient incremental updates

**Implementation:** `shared/processors/patterns/smart_skip_mixin.py`

---

### 12. Early Exit (EarlyExitMixin)

**Purpose:** Exit early on no-game days, offseason, or historical dates.

**When:** Before `run()` begins.

**How It Works:**
```python
class PlayerGameSummaryProcessor(EarlyExitMixin, AnalyticsProcessorBase):
    # Configuration
    ENABLE_NO_GAMES_CHECK = True       # Skip if no games scheduled today
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = True  # Skip dates >90 days old
```

**Checks Performed:**
1. **No Games Check:** Query schedule for games on date → skip if zero
2. **Offseason Check:** Is date in July-September? → skip
3. **Historical Date Check:** Is date > 90 days old? → skip (use backfill instead)

**Benefits:**
- Avoids processing on NBA off-days
- Prevents accidental runs during offseason
- Protects against processing ancient dates in production mode

**Implementation:** `shared/processors/patterns/early_exit_mixin.py`

---

### 13. Circuit Breaker (CircuitBreakerMixin)

**Purpose:** Prevent infinite retry loops on consistently failing entities.

**When:** Before processing each entity in Phase 4.

**How It Works:**
```python
class PlayerDailyCacheProcessor(CircuitBreakerMixin, PrecomputeProcessorBase):
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes
```

**States:**
| State | Behavior |
|-------|----------|
| **Closed** | Normal operation, process entity |
| **Open** | Skip entity, log "Circuit breaker active" |
| **Half-Open** | After timeout, try one request to test recovery |

**Entity-Level Circuit Breaker (Phase 4):**
```python
# Per-entity tracking in nba_orchestration.reprocess_attempts
circuit_status = self._check_circuit_breaker(player_lookup, analysis_date)

if circuit_status['active']:
    logger.warning(f"{player_lookup}: Circuit breaker active until {circuit_status['until']}")
    failed.append({'entity_id': player_lookup, 'category': 'CIRCUIT_BREAKER_ACTIVE'})
    continue
```

**System-Level Circuit Breaker (Phase 5):**
```python
# Prediction systems have their own circuit breakers
from system_circuit_breaker import SystemCircuitBreaker

breaker = SystemCircuitBreaker(system_name='xgboost_v1', threshold=3)

if breaker.is_open():
    logger.warning("XGBoost system circuit breaker open - using fallback")
    return fallback_prediction()
```

**Benefits:**
- Prevents runaway retries on bad data
- Protects downstream systems from cascading failures
- Enables graceful degradation

**Implementation:**
- `shared/processors/patterns/circuit_breaker_mixin.py` (Phase 3/4)
- `predictions/worker/system_circuit_breaker.py` (Phase 5)

---

## Decision Matrix: Which Patterns Apply?

| Scenario | Active Patterns | Skipped Patterns |
|----------|-----------------|------------------|
| **Daily scheduled run** | All patterns enabled | None |
| **Manual CLI run** | All patterns enabled | None |
| **Backfill (historical)** | Dedup, Dependencies, Smart Idem, Completeness | Strict mode, Cascade triggers, Early Exit |
| **Early season (day 0-6)** | Bootstrap skip only | All others (processor exits early) |
| **Pub/Sub retry** | Deduplication blocks | All others (processor exits early) |
| **Upstream failed** | Defensive checks block | All others (processor exits early) |
| **Missing data gaps** | Defensive checks block | All others (processor exits early) |
| **No games scheduled** | Early Exit blocks | All others (processor exits early) |
| **Offseason (Jul-Sep)** | Early Exit blocks | All others (processor exits early) |
| **Irrelevant source trigger** | Smart Skip blocks | All others (processor exits early) |
| **Entity circuit breaker open** | Circuit Breaker skips entity | Processing for that entity only |

### Pattern Execution Order

When a processor runs, patterns are checked in this order (first blocker wins):

```
1. Smart Skip      → "Is this triggered by a relevant source?"
2. Early Exit      → "Is this a valid processing day?"
3. Deduplication   → "Already processing this date?"
4. Bootstrap Check → "Is this day 0-6 of season?" (Phase 4 only)
5. Defensive Checks→ "Did upstream succeed? Any gaps?"
6. Dependencies    → "Does upstream data exist and is it fresh?"
7. Completeness    → "Is historical data complete?" (Phase 4 only)
8. Circuit Breaker → "Has this entity failed too many times?"
   ↓
9. [Processing occurs]
   ↓
10. Smart Idempotency → "Has output changed? Skip write if unchanged"
11. Cascade Control   → "Should I trigger downstream?"
12. Run History       → "Log success/failure for tracking"
```

---

## Configuration Reference

### Processor-Level Options

| Option | Default | Effect |
|--------|---------|--------|
| `strict_mode` | `True` | Enable defensive checks |
| `backfill_mode` | `False` | Disable alerts, relax thresholds |
| `skip_downstream_trigger` | `False` | Don't publish to next phase |

### Child Class Configuration

```python
class MyProcessor(AnalyticsProcessorBase):
    # For defensive checks
    upstream_processor_name = 'PlayerBoxscoreProcessor'
    upstream_table = 'nba_analytics.player_game_summary'
    lookback_days = 15

    # For dependency checking
    def get_dependencies(self):
        return {
            'nba_raw.nbac_team_boxscore': {
                'field_prefix': 'source_boxscore',
                'critical': True,
                'max_age_hours_fail': 72,
                ...
            }
        }
```

---

## Related Documentation

### Architecture Docs
- [Pipeline Integrity](./pipeline-integrity.md) - Cascade control, gap detection
- [Bootstrap Period Overview](./bootstrap-period-overview.md) - Early season handling
- [Source Coverage](./source-coverage/) - Quality tracking system
- [Change Detection](./change-detection/) - Incremental processing

### Developer Guides
- [Processor Patterns](../05-development/guides/processor-patterns/) - Implementation guides
- [Processing Patterns](../05-development/patterns/) - Pattern catalog
- [Processor Development](../05-development/guides/processor-development.md) - Building processors

### Operations
- [Run History Guide](../07-monitoring/run-history-guide.md) - Using processor_run_history
- [Completeness Quick Start](../02-operations/completeness-quick-start.md) - Validating completeness
- [Backfill Guide](../02-operations/backfill-guide.md) - Running backfills safely

### Code Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| Deduplication | `data_processors/raw/processor_base.py` | 139-154 |
| Dependency Checking | `data_processors/analytics/analytics_base.py` | 612-706 |
| Defensive Checks (Phase 3) | `data_processors/analytics/analytics_base.py` | 274-377 |
| Defensive Checks (Phase 4) | `data_processors/precompute/precompute_base.py` | 637-778 |
| Change Detection | `data_processors/analytics/analytics_base.py` | 379-456 |
| Completeness Checker | `shared/utils/completeness_checker.py` | Full file |
| Run History Mixin | `shared/processors/mixins/run_history_mixin.py` | Full file |
| Smart Skip Mixin | `shared/processors/patterns/smart_skip_mixin.py` | Full file |
| Early Exit Mixin | `shared/processors/patterns/early_exit_mixin.py` | Full file |
| Circuit Breaker (Phase 3/4) | `shared/processors/patterns/circuit_breaker_mixin.py` | Full file |
| Circuit Breaker (Phase 5) | `predictions/worker/system_circuit_breaker.py` | Full file |
| Smart Idempotency | `data_processors/raw/smart_idempotency_mixin.py` | Full file |
| Quality Mixin | `shared/processors/patterns/quality_mixin.py` | Full file |

---

## Troubleshooting

### "DependencyError: Upstream X failed for Y"
**Cause:** Defensive checks detected upstream failure.
**Fix:** Check `processor_run_history` for upstream error, fix and re-run upstream.

### "Missing critical dependencies"
**Cause:** Dependency check found no data in upstream table.
**Fix:** Verify upstream processor ran, check date ranges.

### Processing runs but data seems stale
**Cause:** `strict_mode=False` or `backfill_mode=True` bypassed checks.
**Fix:** Re-run with default settings (strict_mode=True).

### Pub/Sub message processed twice
**Cause:** Deduplication check using stale threshold (>2 hours).
**Fix:** Normal behavior for retries; check if previous run is stuck.

---

## Pattern Coverage Gaps (Potential Improvements)

Based on code review, some patterns are not uniformly applied across all processors:

### Phase 3 Gaps

| Processor | Missing Pattern | Priority | Notes |
|-----------|-----------------|----------|-------|
| `TeamDefenseGameSummaryProcessor` | `QualityMixin` | Low | No source coverage tracking |
| `TeamDefenseGameSummaryProcessor` | `get_change_detector()` | Medium | Always full-batch, could be incremental |
| `TeamOffenseGameSummaryProcessor` | `QualityMixin` | Low | No source coverage tracking |
| `TeamOffenseGameSummaryProcessor` | `get_change_detector()` | Medium | Always full-batch, could be incremental |
| `UpcomingPlayerGameContextProcessor` | `QualityMixin` | Low | No source coverage tracking |
| `UpcomingTeamGameContextProcessor` | `QualityMixin` | Low | No source coverage tracking |

### Phase 5 Gaps

| Component | Missing Pattern | Priority | Notes |
|-----------|-----------------|----------|-------|
| `PredictionCoordinator` | `RunHistoryMixin` integration | Medium | Has ExecutionLogger but not RunHistoryMixin |
| `PredictionWorker` | Dependency checking | Low | Relies on Phase 4 completeness |

### Recommendations

1. **Add `QualityMixin` to team processors** - Would enable source coverage tracking for team-level data, useful for monitoring.

2. **Add `get_change_detector()` to team processors** - Currently these always do full-batch processing. Adding change detection could reduce processing by ~90% on mid-day updates.

3. **Consider `SmartReprocessingMixin` for Phase 4** - Some Phase 4 processors already check source hashes, but could be standardized into a mixin.

4. **Standardize Phase 5 run history** - Coordinator and worker have their own logging, but could integrate with `processor_run_history` for unified monitoring.

These are not blocking issues - the current implementation is production-ready. These are optimization opportunities for future iterations.

---

**Last Updated:** 2025-11-29
**Owner:** Engineering Team
**Next Review:** After backfill operations complete
