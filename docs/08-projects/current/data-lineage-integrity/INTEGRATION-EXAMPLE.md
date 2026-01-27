# Integration Example: ProcessingGate & WindowCompletenessValidator

**Date**: 2026-01-26
**Purpose**: Show how to integrate data lineage integrity checks into existing processors

---

## Overview

This document demonstrates how to integrate the new prevention layer into an existing processor to stop cascade contamination.

**Key Changes**:
1. Add ProcessingGate check before computing
2. Track window completeness per entity
3. Store NULL for incomplete windows instead of computing wrong values
4. Add quality metadata to output records

---

## Example: PlayerCompositeFactorsProcessor Integration

### Step 1: Import New Components

```python
# Add to imports at top of file
from shared.validation.processing_gate import ProcessingGate, GateStatus, ProcessingBlockedError
from shared.validation.window_completeness import WindowCompletenessValidator
```

### Step 2: Initialize in __init__

```python
class PlayerCompositeFactorsProcessor(PrecomputeProcessorBase):
    WINDOW_SIZES = [5, 10, 15, 20]

    def __init__(self):
        super().__init__()

        # Initialize gate and validator
        self.processing_gate = ProcessingGate(
            self.bq_client,
            self.project_id,
            min_completeness=0.8,
            grace_period_hours=36,
            window_completeness_threshold=0.7
        )

        self.window_validator = WindowCompletenessValidator(
            self.completeness_checker,
            compute_threshold=0.7,
            upstream_table='nba_analytics.player_game_summary',
            upstream_entity_field='player_lookup'
        )
```

### Step 3: Add Gate Check Before Processing

```python
def process(self):
    """Main processing method with gate check."""

    # Get players to process
    players = self._get_players_for_date(self.game_date)
    logger.info(f"Processing {len(players)} players for {self.game_date}")

    # GATE CHECK: Verify overall data readiness
    gate_result = self.processing_gate.check_can_process(
        processor_name=self.__class__.__name__,
        game_date=self.game_date,
        entity_ids=players,
        window_size=10,  # Primary window size
        window_type='games',
        upstream_table='nba_analytics.player_game_summary',
        upstream_entity_field='player_lookup',
        season_start_date=self.season_start_date
    )

    # Handle gate status
    if gate_result.status == GateStatus.FAIL:
        raise ProcessingBlockedError(
            f"Processing blocked: {gate_result.message}",
            gate_result=gate_result
        )

    if gate_result.status == GateStatus.WAIT:
        logger.info(f"Waiting for data: {gate_result.message}")
        return  # Will retry later

    if gate_result.status == GateStatus.PROCEED_WITH_WARNING:
        logger.warning(f"Proceeding with degraded data: {gate_result.message}")

    # Check which players have complete windows for primary window size
    computable, skip = self.window_validator.get_computable_players(
        player_ids=players,
        game_date=self.game_date,
        window_size=10,  # Primary window
        season_start_date=self.season_start_date
    )

    logger.info(
        f"Window check: {len(computable)} computable, {len(skip)} skip "
        f"(threshold=70%)"
    )

    # Process all players, handling incomplete windows appropriately
    results = []
    for player_id in players:
        record = self._process_player(player_id, gate_result)
        results.append(record)

    # Save results
    self._write_results(results)

    logger.info(f"Processed {len(results)} players")
```

### Step 4: Process Player with Window Checks

```python
def _process_player(self, player_id: str, gate_result: GateResult) -> Dict:
    """
    Process a single player with window completeness checks.

    Args:
        player_id: Player lookup ID
        gate_result: Gate check result from overall check

    Returns:
        Dict with player's computed factors and quality metadata
    """
    # Check window completeness for all window sizes
    window_results = self.window_validator.check_player_windows(
        player_id=player_id,
        game_date=self.game_date,
        window_sizes=self.WINDOW_SIZES,
        season_start_date=self.season_start_date
    )

    # Initialize record with base fields
    record = {
        'player_id': player_id,
        'game_date': self.game_date,
        'analysis_date': self.analysis_date,
        'processed_at': datetime.utcnow(),
        'calculation_version': self.calculation_version,
    }

    # Compute each window, respecting completeness
    for window_size in self.WINDOW_SIZES:
        result = window_results[window_size]

        if result.recommendation == 'skip':
            # CRITICAL: Don't compute contaminated value - store NULL
            record[f'points_last_{window_size}_avg'] = None
            record[f'rebounds_last_{window_size}_avg'] = None
            record[f'assists_last_{window_size}_avg'] = None
            record[f'window_{window_size}_complete'] = False

            logger.debug(
                f"{player_id}: Skipping L{window_size} window "
                f"({result.completeness_ratio:.1%} complete, "
                f"{result.games_available}/{result.games_required} games)"
            )
        else:
            # Safe to compute - window has sufficient data
            record[f'points_last_{window_size}_avg'] = self._compute_rolling_avg(
                player_id, 'points', window_size
            )
            record[f'rebounds_last_{window_size}_avg'] = self._compute_rolling_avg(
                player_id, 'rebounds', window_size
            )
            record[f'assists_last_{window_size}_avg'] = self._compute_rolling_avg(
                player_id, 'assists', window_size
            )
            record[f'window_{window_size}_complete'] = result.is_complete

            if result.recommendation == 'compute_with_flag':
                logger.debug(
                    f"{player_id}: Computing L{window_size} with flag "
                    f"({result.completeness_ratio:.1%} complete)"
                )

    # Add quality metadata (from gate check)
    primary_window = window_results[10]  # Primary window size
    record.update({
        'quality_score': primary_window.completeness_ratio,
        'window_completeness': primary_window.completeness_ratio,
        'processing_context': gate_result.quality_metadata['processing_context'],
        'upstream_quality_min': gate_result.quality_score,
        'gate_status': gate_result.status.value,
    })

    # Add DNP awareness metadata
    if primary_window.dnp_count > 0:
        record['dnp_games_excluded'] = primary_window.dnp_count
        record['gap_classification'] = primary_window.gap_classification

    return record
```

### Step 5: Helper Method for Rolling Average

```python
def _compute_rolling_avg(
    self,
    player_id: str,
    stat: str,
    window_size: int
) -> Optional[float]:
    """
    Compute rolling average for a stat over window.

    This method assumes completeness has already been verified.
    If called with incomplete data, the result will be contaminated.

    Args:
        player_id: Player lookup ID
        stat: Stat name (e.g., 'points', 'rebounds')
        window_size: Number of games to average

    Returns:
        Rolling average, or None if no data
    """
    query = f"""
    SELECT AVG({stat}) as avg_value
    FROM (
        SELECT {stat}
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_id
          AND game_date < @game_date
        ORDER BY game_date DESC
        LIMIT @window_size
    )
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("player_id", "STRING", player_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", self.game_date),
            bigquery.ScalarQueryParameter("window_size", "INT64", window_size),
        ]
    )

    try:
        result = list(self.bq_client.query(query, job_config=job_config))
        if result and result[0].avg_value is not None:
            return float(result[0].avg_value)
        return None
    except Exception as e:
        logger.error(f"Error computing {stat} L{window_size} for {player_id}: {e}")
        return None
```

---

## Output Schema Changes

The integration adds these columns to output records:

```python
{
    # Existing fields
    'player_id': 'lebron_james',
    'game_date': date(2026, 1, 26),

    # Rolling averages (NULL if window incomplete)
    'points_last_5_avg': 28.4,      # Computed (70%+ complete)
    'points_last_10_avg': None,     # NULL (below 70% threshold)
    'points_last_15_avg': 27.8,     # Computed with flag
    'points_last_20_avg': None,     # NULL

    # Window completeness flags
    'window_5_complete': True,
    'window_10_complete': False,
    'window_15_complete': False,    # Partial but computed
    'window_20_complete': False,

    # Quality metadata (NEW)
    'quality_score': 0.85,           # Primary window completeness
    'window_completeness': 0.85,     # Same as quality_score
    'processing_context': 'daily',   # daily | backfill | cascade
    'upstream_quality_min': 0.85,    # Weakest upstream source
    'gate_status': 'proceed_warn',   # Gate decision

    # DNP awareness (NEW, optional)
    'dnp_games_excluded': 2,         # DNP games not counted
    'gap_classification': 'NO_GAP',  # NO_GAP | DATA_GAP | NAME_UNRESOLVED
}
```

---

## Error Handling

### Scenario 1: Gate Blocks Processing

```python
try:
    self.process()
except ProcessingBlockedError as e:
    logger.error(f"Processing blocked: {e.message}")
    # Log to run history with status='blocked'
    self.log_processing_run(
        success=False,
        error=f"Gate blocked: {e.gate_result.message}",
        summary={
            'gate_status': e.gate_result.status.value,
            'completeness_pct': e.gate_result.completeness_pct,
            'expected_count': e.gate_result.expected_count,
            'actual_count': e.gate_result.actual_count,
        }
    )
    # Don't retry immediately - wait for upstream data
    return
```

### Scenario 2: Gate Returns WAIT

```python
if gate_result.status == GateStatus.WAIT:
    logger.info(f"Data not ready: {gate_result.message}")
    # Don't mark as failure - this is expected
    self.log_processing_run(
        success=False,
        error=None,
        summary={
            'status': 'waiting_for_data',
            'completeness_pct': gate_result.completeness_pct,
            'hours_since_game': gate_result.quality_metadata.get('hours_since_game'),
        }
    )
    return  # Scheduler will retry later
```

---

## Testing

### Unit Test Example

```python
def test_window_completeness_skip():
    """Test that incomplete windows return NULL."""

    # Mock completeness checker to return 60% complete
    mock_checker = Mock()
    mock_checker.check_completeness_batch.return_value = {
        'lebron_james': {
            'expected_count': 10,
            'actual_count': 6,
            'completeness_pct': 60.0,
            'is_complete': False,
            'dnp_count': 0,
        }
    }

    validator = WindowCompletenessValidator(mock_checker, compute_threshold=0.7)

    window_results = validator.check_player_windows(
        player_id='lebron_james',
        game_date=date(2026, 1, 26),
        window_sizes=[10]
    )

    result = window_results[10]
    assert result.recommendation == 'skip', "Should skip 60% complete window"
    assert result.completeness_ratio == 0.6
```

---

## Monitoring

### Key Metrics to Track

1. **Gate Decision Distribution**
   - % of runs that PROCEED vs PROCEED_WITH_WARNING vs WAIT vs FAIL
   - Alert if FAIL rate > 5%

2. **Window Completeness Distribution**
   - % of windows marked as incomplete
   - % of NULL values in rolling averages
   - Alert if incomplete rate > 20%

3. **Processing Context Distribution**
   - % daily vs backfill vs cascade
   - Should be mostly 'daily' in production

4. **Quality Score Trends**
   - Average quality_score by date
   - Alert on sudden drops (>10% decrease)

---

## Migration Path

### Phase 1: Add Columns (Non-Breaking)
Run `migrations/add_quality_metadata.sql` to add columns with defaults.

### Phase 2: Deploy New Code (Parallel)
Deploy processors with gate checks but in "warn-only" mode initially.

### Phase 3: Enable Enforcement
Switch to strict mode where FAIL status blocks processing.

### Phase 4: Backfill Quality Metadata
Reprocess historical data to populate quality columns.

---

## Questions?

See:
- `docs/08-projects/current/data-lineage-integrity/IMPLEMENTATION-REQUEST.md`
- `docs/08-projects/current/data-lineage-integrity/DESIGN-DECISIONS.md`
