# Implementation Request: Data Lineage Integrity Prevention Layer

**Date**: 2026-01-26
**For**: External Claude (Sonnet Web Chat)
**Purpose**: Implement prevention layer to stop cascade contamination

---

## Context

You are implementing a prevention layer for an NBA Props Platform that has discovered **81% of this season's game data was backfilled late**, causing cascade contamination in downstream computed values.

**The Problem**: Rolling averages and ML features were computed with incomplete data windows because the pipeline runs on a schedule, not on data readiness.

**The Solution**: Add processing gates that verify data completeness before computing, and quality metadata that tracks what was available at computation time.

---

## Existing Infrastructure (Use These)

### 1. CompletenessChecker (`shared/utils/completeness_checker.py`)

Already handles window-based completeness checking:

```python
from shared.utils.completeness_checker import CompletenessChecker

checker = CompletenessChecker(bq_client, project_id)

# Check if player has enough games for rolling window
results = checker.check_completeness_batch(
    entity_ids=['lebron_james', 'stephen_curry'],
    entity_type='player',
    analysis_date=date(2026, 1, 26),
    upstream_table='nba_analytics.player_game_summary',
    upstream_entity_field='player_lookup',
    lookback_window=10,  # Last 10 games
    window_type='games',
    season_start_date=date(2025, 10, 22),
    dnp_aware=True  # Exclude DNP games from expected count
)

# results = {
#     'lebron_james': {
#         'expected_count': 10,
#         'actual_count': 8,
#         'completeness_pct': 80.0,
#         'is_complete': False,
#         'is_production_ready': True,  # >= 70% threshold
#         'dnp_count': 2,
#         'gap_classification': 'NO_GAP'
#     }
# }
```

### 2. SoftDependencyMixin (`shared/processors/mixins/soft_dependency_mixin.py`)

Already handles upstream dependency checking:

```python
class MyProcessor(SoftDependencyMixin, ProcessorBase):
    def run(self):
        dep_result = self.check_soft_dependencies(analysis_date)

        if dep_result['should_proceed']:
            if dep_result['degraded']:
                logger.warning(f"Proceeding with warnings: {dep_result['warnings']}")
            # ... do processing ...
        else:
            raise DependencyNotMetError(dep_result['errors'])
```

### 3. QualityMixin (`shared/processors/patterns/quality_mixin.py`)

Already handles quality assessment and scoring:

```python
class MyProcessor(QualityMixin, AnalyticsProcessorBase):
    REQUIRED_FIELDS = ['points', 'minutes']

    def process(self):
        with self:  # Auto-flush quality events
            data = self.fetch_data()
            quality = self.assess_quality(data, sources_used=['primary'])
            # quality = {'tier': 'GOLD', 'score': 95.0, 'issues': [], ...}
            self.load_with_quality(data, quality)
```

### 4. TransformProcessorBase (`shared/processors/base/transform_processor_base.py`)

Base class for Phase 3 (Analytics) and Phase 4 (Precompute) processors.

### 5. MultiWindowCompletenessChecker (`data_processors/precompute/player_daily_cache/builders/completeness_checker.py`)

Already checks multiple windows (L5, L10, L7d, L14d) in parallel.

---

## What to Build

### Component 1: ProcessingGate

**Purpose**: Unified gate that decides whether to proceed with processing.

**File**: `shared/validation/processing_gate.py`

**Requirements**:
- Combine CompletenessChecker and SoftDependencyMixin checks
- Return clear status: PROCEED, PROCEED_WITH_WARNING, WAIT, FAIL
- Include reason and metrics in result
- Support configurable thresholds
- Log decisions for debugging

**Interface**:

```python
from enum import Enum
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional

class GateStatus(Enum):
    PROCEED = "proceed"              # All checks passed
    PROCEED_WITH_WARNING = "proceed_warn"  # Minor issues, proceed with flags
    WAIT = "wait"                    # Data not ready, retry later
    FAIL = "fail"                    # Critical issue, cannot proceed

@dataclass
class GateResult:
    status: GateStatus
    can_proceed: bool
    quality_score: float  # 0-1 scale
    message: str

    # Details
    completeness_pct: float
    expected_count: int
    actual_count: int
    missing_items: List[str]
    quality_issues: List[str]

    # For downstream use
    quality_metadata: Dict  # To attach to output records


class ProcessingGate:
    """
    Unified processing gate for Phase 3+ processors.

    Usage:
        gate = ProcessingGate(bq_client, project_id)

        result = gate.check_can_process(
            processor_name='PlayerCompositeFactorsProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['lebron_james', 'stephen_curry'],
            window_size=10
        )

        if result.status == GateStatus.FAIL:
            raise ProcessingBlockedError(result.message)

        if result.status == GateStatus.WAIT:
            return  # Will retry later

        # Proceed with processing, attach quality metadata
        for record in output_records:
            record.update(result.quality_metadata)
    """

    def __init__(
        self,
        bq_client,
        project_id: str,
        min_completeness: float = 0.8,  # 80%
        grace_period_hours: int = 36,
        window_completeness_threshold: float = 0.7  # 70%
    ):
        ...

    def check_can_process(
        self,
        processor_name: str,
        game_date: date,
        entity_ids: List[str],
        window_size: int = 10,
        window_type: str = 'games',
        allow_override: bool = False
    ) -> GateResult:
        """Check if processing can proceed."""
        ...

    def check_window_completeness(
        self,
        player_id: str,
        game_date: date,
        window_size: int
    ) -> GateResult:
        """Check single player's window completeness."""
        ...
```

### Component 2: WindowCompletenessValidator

**Purpose**: Focused validator for rolling window calculations.

**File**: `shared/validation/window_completeness.py`

**Requirements**:
- Verify N games exist before computing last-N average
- Return NULL recommendation when window too incomplete
- Track which windows are complete vs incomplete per player
- Support multiple window sizes (5, 10, 15, 20)

**Interface**:

```python
@dataclass
class WindowResult:
    is_complete: bool
    completeness_ratio: float  # 0-1
    games_available: int
    games_required: int
    recommendation: str  # 'compute', 'compute_with_flag', 'skip'

class WindowCompletenessValidator:
    """
    Validates rolling window completeness before computation.

    Decision logic:
    - 100% complete: compute normally
    - 70-99% complete: compute but flag as incomplete
    - <70% complete: return NULL, don't compute
    """

    def __init__(self, completeness_checker: CompletenessChecker):
        self.checker = completeness_checker
        self.compute_threshold = 0.7  # Below this, return NULL

    def check_player_windows(
        self,
        player_id: str,
        game_date: date,
        window_sizes: List[int] = [5, 10, 15, 20]
    ) -> Dict[int, WindowResult]:
        """Check completeness for multiple window sizes."""
        ...

    def get_computable_players(
        self,
        player_ids: List[str],
        game_date: date,
        window_size: int
    ) -> Tuple[List[str], List[str]]:
        """
        Partition players into computable vs skip.

        Returns:
            (computable_ids, skip_ids)
        """
        ...
```

### Component 3: Quality Metadata Schema

**Purpose**: Add quality tracking columns to existing tables.

**File**: `migrations/add_quality_metadata.sql`

**Schema Changes**:

```sql
-- Phase 3: Analytics tables
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS data_quality_flag STRING DEFAULT 'complete',
-- Values: 'complete', 'partial', 'incomplete', 'corrected'
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';
-- Values: 'daily', 'backfill', 'manual', 'cascade'

-- Phase 4: Precompute tables
ALTER TABLE nba_precompute.player_composite_factors
ADD COLUMN IF NOT EXISTS quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS window_completeness FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS points_last_5_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS points_last_10_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS points_last_15_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS points_last_20_complete BOOL DEFAULT true,
ADD COLUMN IF NOT EXISTS upstream_quality_min FLOAT64 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS processing_context STRING DEFAULT 'daily';

-- Add similar to other precompute tables:
-- player_daily_cache, ml_feature_store_v2, etc.
```

### Component 4: Integration with PlayerCompositeFactorsProcessor

**Purpose**: Show how to integrate the gate into an existing processor.

**File**: Modify `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Key Changes**:
1. Add ProcessingGate check before computing
2. Track window completeness per player
3. Store NULL for incomplete windows instead of computing wrong value
4. Add quality metadata to output records

**Pattern**:

```python
class PlayerCompositeFactorsProcessor(PrecomputeProcessorBase):
    WINDOW_SIZES = [5, 10, 15, 20]

    def __init__(self, game_date: date, backfill_mode: bool = False):
        super().__init__(backfill_mode=backfill_mode)
        self.game_date = game_date
        self.processing_gate = ProcessingGate(self.bq_client, self.project_id)
        self.window_validator = WindowCompletenessValidator(self.completeness_checker)

    def process(self):
        # Get players to process
        players = self._get_players_for_date(self.game_date)

        # Check which players have complete windows
        computable, skip = self.window_validator.get_computable_players(
            player_ids=players,
            game_date=self.game_date,
            window_size=10  # Primary window
        )

        logger.info(f"Processing {len(computable)} computable, {len(skip)} incomplete")

        results = []
        for player_id in players:
            record = self._process_player(player_id)
            results.append(record)

        self._write_results(results)

    def _process_player(self, player_id: str) -> Dict:
        # Check window completeness for all sizes
        window_results = self.window_validator.check_player_windows(
            player_id=player_id,
            game_date=self.game_date,
            window_sizes=self.WINDOW_SIZES
        )

        record = {
            'player_id': player_id,
            'game_date': self.game_date,
            'processed_at': datetime.utcnow(),
        }

        # Compute each window, respecting completeness
        for window_size in self.WINDOW_SIZES:
            result = window_results[window_size]

            if result.recommendation == 'skip':
                # Don't compute contaminated value - store NULL
                record[f'points_last_{window_size}_avg'] = None
                record[f'points_last_{window_size}_complete'] = False
            else:
                # Safe to compute
                avg = self._compute_rolling_avg(player_id, window_size)
                record[f'points_last_{window_size}_avg'] = avg
                record[f'points_last_{window_size}_complete'] = result.is_complete

        # Add quality metadata
        primary_result = window_results[10]  # Primary window
        record['quality_score'] = primary_result.completeness_ratio
        record['window_completeness'] = primary_result.completeness_ratio
        record['processing_context'] = 'daily' if not self.is_backfill_mode else 'backfill'

        return record
```

### Component 5: Enhanced /validate-lineage Skill

**Purpose**: Update skill to use new quality metadata.

**File**: Update `.claude/skills/validate-lineage.md`

**New Capabilities**:
- Check quality_score distribution by date
- Find records with incomplete windows
- Compare stored quality_score to recomputed completeness
- Generate remediation recommendations

---

## Design Decisions (Follow These)

### 1. Thresholds

| Threshold | Value | Rationale |
|-----------|-------|-----------|
| `min_completeness` | 80% | Below this, gate returns FAIL |
| `window_completeness_threshold` | 70% | Below this, return NULL |
| `grace_period_hours` | 36 | Wait this long before failing |

### 2. Gate Status Logic

```python
def determine_status(completeness, hours_since_game):
    if completeness >= 1.0:
        return GateStatus.PROCEED

    if hours_since_game < 36 and completeness < 1.0:
        return GateStatus.WAIT  # Data still arriving

    if completeness >= 0.8:
        return GateStatus.PROCEED_WITH_WARNING

    return GateStatus.FAIL
```

### 3. NULL vs Compute Decision

```python
def should_compute(window_completeness):
    if window_completeness >= 1.0:
        return 'compute'  # Full window, compute normally
    elif window_completeness >= 0.7:
        return 'compute_with_flag'  # Partial, compute but flag
    else:
        return 'skip'  # Too incomplete, return NULL
```

### 4. Quality Score Propagation

- Upstream quality flows to downstream
- Use minimum quality score from inputs (weakest link)
- Aggregate flags from all upstream sources

---

## Existing Code to Reference

Read these files for patterns and context:

1. **CompletenessChecker**: `shared/utils/completeness_checker.py`
   - Window-based completeness checking
   - DNP-aware mode
   - Batch operations

2. **QualityMixin**: `shared/processors/patterns/quality_mixin.py`
   - Quality assessment
   - Tier assignment (GOLD, SILVER, BRONZE, UNUSABLE)
   - Event logging

3. **SoftDependencyMixin**: `shared/processors/mixins/soft_dependency_mixin.py`
   - Upstream dependency checking
   - Threshold-based decisions

4. **PlayerCompositeFactorsProcessor**: `data_processors/precompute/player_composite_factors/`
   - Current implementation to modify
   - Factor computation patterns

5. **TransformProcessorBase**: `shared/processors/base/transform_processor_base.py`
   - Base class patterns
   - Query execution with retry
   - Time tracking

---

## Deliverables

1. **`shared/validation/processing_gate.py`**
   - ProcessingGate class
   - GateStatus enum
   - GateResult dataclass

2. **`shared/validation/window_completeness.py`**
   - WindowCompletenessValidator class
   - WindowResult dataclass

3. **`migrations/add_quality_metadata.sql`**
   - Schema changes for quality columns

4. **Integration example** showing how to use in a processor

5. **Updated `/validate-lineage` skill** with new capabilities

6. **Unit tests** for new components

---

## Questions to Answer

As you implement, consider:

1. **How to handle new players** with <10 games legitimately?
   - Use bootstrap mode detection from CompletenessChecker
   - Allow computation with flag for early season

2. **How to integrate with existing QualityMixin?**
   - Extend, don't replace
   - Quality scores should be compatible

3. **How to handle backfill mode?**
   - Processing gates should be more permissive in backfill
   - Still track quality metadata

4. **What metrics to log for monitoring?**
   - % of records with complete windows
   - % of records skipped due to incomplete windows
   - Average quality score per date

---

## Success Criteria

After implementation:

1. New processing produces no contaminated rolling averages
2. Quality metadata attached to all new records
3. Incomplete windows produce NULL, not wrong values
4. Existing processing patterns work with minimal changes
5. /validate-lineage can use quality metadata for validation

---

**End of Implementation Request**
