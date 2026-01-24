"""
Phase 2 Validator - Raw Data

Validates Phase 2 raw data sources are present and complete.
"""

from datetime import date
from typing import Optional
import time
import logging

from google.cloud import bigquery

from shared.validation.config import (
    PROJECT_ID,
    PHASE2_SOURCES,
)
from shared.validation.context.schedule_context import ScheduleContext
from shared.validation.context.player_universe import PlayerUniverse
from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
    query_table_count,
)

logger = logging.getLogger(__name__)


def validate_phase2(
    game_date: date,
    schedule_context: ScheduleContext,
    player_universe: PlayerUniverse,
    client: Optional[bigquery.Client] = None,
) -> PhaseValidationResult:
    """
    Validate Phase 2 raw data sources.

    Args:
        game_date: Date to validate
        schedule_context: Schedule context for the date
        player_universe: Player universe for the date
        client: Optional BigQuery client

    Returns:
        PhaseValidationResult for Phase 2
    """
    start_time = time.time()

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    result = PhaseValidationResult(phase=2, status=ValidationStatus.MISSING)

    # If not a valid processing date, return early
    if not schedule_context.is_valid_processing_date:
        result.status = ValidationStatus.NOT_APPLICABLE
        result.issues.append(schedule_context.skip_reason or "Not a valid processing date")
        return result

    expected_game_count = schedule_context.game_count
    expected_player_count = player_universe.total_active

    # Validate each source
    for source_name, source_config in PHASE2_SOURCES.items():
        table_result = _validate_source(
            client=client,
            game_date=game_date,
            source_name=source_name,
            source_config=source_config,
            expected_game_count=expected_game_count,
            expected_player_count=expected_player_count,
        )
        result.tables[source_name] = table_result

    # Check fallback coverage
    _check_fallback_coverage(result)

    # Determine overall status
    _determine_phase_status(result)

    result.validation_duration_ms = (time.time() - start_time) * 1000
    result._update_aggregates()

    return result


def _validate_source(
    client: bigquery.Client,
    game_date: date,
    source_name: str,
    source_config,
    expected_game_count: int,
    expected_player_count: int,
) -> TableValidation:
    """Validate a single Phase 2 source."""

    record_count = query_table_count(
        client=client,
        dataset='nba_raw',
        table=source_config.table_name,
        date_column=source_config.date_column,
        game_date=game_date,
    )

    # Determine expected count based on source type
    if 'player' in source_name.lower() or 'gamebook' in source_name.lower():
        expected_count = expected_player_count
    elif 'team_boxscore' in source_name.lower():
        expected_count = expected_game_count * 2  # 2 teams per game
    elif 'schedule' in source_name.lower():
        expected_count = expected_game_count
    else:
        expected_count = 0  # Unknown expected count

    # Determine status
    if record_count == 0:
        if source_config.priority == 'optional':
            status = ValidationStatus.NOT_APPLICABLE
        elif source_config.fallback_for:
            status = ValidationStatus.MISSING  # Will be checked for fallback
        else:
            status = ValidationStatus.MISSING
    elif expected_count > 0 and record_count >= expected_count * 0.95:
        status = ValidationStatus.COMPLETE
    elif record_count > 0:
        status = ValidationStatus.PARTIAL
    else:
        status = ValidationStatus.MISSING

    table_result = TableValidation(
        table_name=source_config.table_name,
        dataset='nba_raw',
        status=status,
        record_count=record_count,
        expected_count=expected_count if expected_count > 0 else record_count,
    )

    # Add issues/warnings based on priority
    if status == ValidationStatus.MISSING:
        if source_config.priority == 'critical':
            table_result.issues.append(f"CRITICAL: {source_name} has no data")
        elif source_config.priority == 'important':
            table_result.warnings.append(f"{source_name} missing (checking fallback)")

    return table_result


def _check_fallback_coverage(result: PhaseValidationResult) -> None:
    """Check if fallback sources cover for missing primaries."""

    # Check player data fallback
    gamebook = result.tables.get('nbac_gamebook_player_stats')
    bdl = result.tables.get('bdl_player_boxscores')

    if gamebook and gamebook.status == ValidationStatus.MISSING:
        if bdl and bdl.record_count > 0:
            # Fallback available
            result.warnings.append(
                "nbac_gamebook missing but bdl_player_boxscores available as fallback"
            )
            gamebook.warnings.append("Using bdl_player_boxscores as fallback")
        else:
            result.issues.append("No player boxscore data available (primary and fallback both missing)")

    # Check props fallback
    bettingpros = result.tables.get('bettingpros_player_points_props')
    odds_api = result.tables.get('odds_api_player_points_props')

    if bettingpros and bettingpros.status == ValidationStatus.MISSING:
        if odds_api and odds_api.record_count > 0:
            result.warnings.append(
                "bettingpros missing but odds_api available as fallback"
            )
        # Note: It's OK to have no props for historical dates


def _determine_phase_status(result: PhaseValidationResult) -> None:
    """Determine overall phase status from table results."""

    critical_sources = [
        name for name, config in PHASE2_SOURCES.items()
        if config.priority == 'critical'
    ]

    critical_complete = all(
        result.tables[name].status == ValidationStatus.COMPLETE
        for name in critical_sources
        if name in result.tables
    )

    any_data = any(
        t.record_count > 0
        for t in result.tables.values()
    )

    if critical_complete:
        result.status = ValidationStatus.COMPLETE
    elif any_data:
        result.status = ValidationStatus.PARTIAL
    else:
        result.status = ValidationStatus.MISSING
