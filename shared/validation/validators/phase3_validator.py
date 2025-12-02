"""
Phase 3 Validator - Analytics

Validates Phase 3 analytics tables are populated correctly.
"""

from datetime import date
from typing import Optional, Set
import time
import logging

from google.cloud import bigquery

from shared.validation.config import (
    PROJECT_ID,
    PHASE3_TABLES,
)
from shared.validation.context.schedule_context import ScheduleContext
from shared.validation.context.player_universe import PlayerUniverse
from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
    QualityDistribution,
    query_table_count,
    query_player_count,
    query_quality_distribution,
    query_actual_players,
)

logger = logging.getLogger(__name__)


def validate_phase3(
    game_date: date,
    schedule_context: ScheduleContext,
    player_universe: PlayerUniverse,
    client: Optional[bigquery.Client] = None,
) -> PhaseValidationResult:
    """
    Validate Phase 3 analytics tables.

    Args:
        game_date: Date to validate
        schedule_context: Schedule context for the date
        player_universe: Player universe for the date
        client: Optional BigQuery client

    Returns:
        PhaseValidationResult for Phase 3
    """
    start_time = time.time()

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    result = PhaseValidationResult(phase=3, status=ValidationStatus.MISSING)

    # If not a valid processing date, return early
    if not schedule_context.is_valid_processing_date:
        result.status = ValidationStatus.NOT_APPLICABLE
        result.issues.append(schedule_context.skip_reason or "Not a valid processing date")
        return result

    # Validate each table
    for table_name, table_config in PHASE3_TABLES.items():
        table_result = _validate_table(
            client=client,
            game_date=game_date,
            table_name=table_name,
            table_config=table_config,
            schedule_context=schedule_context,
            player_universe=player_universe,
        )
        result.tables[table_name] = table_result

    # Determine overall status
    _determine_phase_status(result)

    result.validation_duration_ms = (time.time() - start_time) * 1000
    result._update_aggregates()

    return result


def _validate_table(
    client: bigquery.Client,
    game_date: date,
    table_name: str,
    table_config,
    schedule_context: ScheduleContext,
    player_universe: PlayerUniverse,
) -> TableValidation:
    """Validate a single Phase 3 table."""

    # Query record count
    record_count = query_table_count(
        client=client,
        dataset=table_config.dataset,
        table=table_config.table_name,
        date_column=table_config.date_column,
        game_date=game_date,
    )

    # Determine expected count based on scope
    # 'all_rostered' = all players on game-day rosters (active + DNP + inactive)
    if table_config.expected_scope == 'all_rostered':
        expected_count = player_universe.total_rostered
        player_count = query_player_count(
            client=client,
            dataset=table_config.dataset,
            table=table_config.table_name,
            date_column=table_config.date_column,
            game_date=game_date,
        )
        expected_players = player_universe.total_rostered
    elif table_config.expected_scope == 'active_only':
        # Only players who actually played
        expected_count = player_universe.total_active
        player_count = query_player_count(
            client=client,
            dataset=table_config.dataset,
            table=table_config.table_name,
            date_column=table_config.date_column,
            game_date=game_date,
        )
        expected_players = player_universe.total_active
    elif table_config.expected_scope == 'teams':
        expected_count = len(schedule_context.teams_playing)
        player_count = 0
        expected_players = 0
    else:
        expected_count = 0
        player_count = 0
        expected_players = 0

    # Query quality distribution if available
    quality = None
    if table_config.has_quality_columns:
        quality = query_quality_distribution(
            client=client,
            dataset=table_config.dataset,
            table=table_config.table_name,
            date_column=table_config.date_column,
            game_date=game_date,
        )

    # Determine status
    if record_count == 0:
        status = ValidationStatus.MISSING
    elif expected_count > 0 and record_count >= expected_count * 0.95:
        status = ValidationStatus.COMPLETE
    elif record_count > 0:
        status = ValidationStatus.PARTIAL
    else:
        status = ValidationStatus.MISSING

    table_result = TableValidation(
        table_name=table_config.table_name,
        dataset=table_config.dataset,
        status=status,
        record_count=record_count,
        expected_count=expected_count if expected_count > 0 else record_count,
        player_count=player_count,
        expected_players=expected_players,
        game_count=schedule_context.game_count if table_config.expected_scope == 'teams' else 0,
        expected_games=schedule_context.game_count,
        quality=quality,
    )

    # Add issues/warnings
    if status == ValidationStatus.MISSING:
        table_result.issues.append(f"{table_name} has no data for {game_date}")
    elif status == ValidationStatus.PARTIAL:
        if expected_players > 0 and player_count < expected_players:
            missing_count = expected_players - player_count
            table_result.warnings.append(
                f"{table_name}: {player_count}/{expected_players} players ({missing_count} missing)"
            )

    # Quality warnings
    if quality and quality.has_issues():
        table_result.warnings.append(
            f"{table_name}: {quality.poor + quality.unusable} records with poor/unusable quality"
        )

    # For player tables, add prop line coverage breakdown
    if table_config.expected_scope in ('all_rostered', 'active_only'):
        prop_breakdown = _query_prop_line_breakdown(
            client=client,
            dataset=table_config.dataset,
            table=table_config.table_name,
            date_column=table_config.date_column,
            game_date=game_date,
        )
        if prop_breakdown:
            table_result.metadata['prop_breakdown'] = prop_breakdown
            with_props = prop_breakdown.get('with_prop_line', 0)
            without_props = prop_breakdown.get('without_prop_line', 0)
            total = with_props + without_props
            if total > 0:
                prop_pct = (with_props / total) * 100
                table_result.metadata['prop_coverage_pct'] = prop_pct
                # Add info about prop coverage to metadata for display
                table_result.metadata['prop_summary'] = f"{with_props} with props, {without_props} without ({prop_pct:.1f}% coverage)"

    return table_result


def _query_prop_line_breakdown(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
) -> dict:
    """Query prop line breakdown for a table (if has_prop_line column exists)."""
    query = f"""
    SELECT
        COUNTIF(has_prop_line = TRUE) as with_prop_line,
        COUNTIF(has_prop_line = FALSE OR has_prop_line IS NULL) as without_prop_line
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()
        row = next(iter(result))
        return {
            'with_prop_line': row.with_prop_line or 0,
            'without_prop_line': row.without_prop_line or 0,
        }
    except Exception as e:
        # Column may not exist (pre-v3.2 data)
        logger.debug(f"Could not query prop breakdown for {dataset}.{table}: {e}")
        return {}


def _determine_phase_status(result: PhaseValidationResult) -> None:
    """Determine overall phase status from table results."""

    all_complete = all(
        t.status == ValidationStatus.COMPLETE
        for t in result.tables.values()
    )

    any_data = any(
        t.record_count > 0
        for t in result.tables.values()
    )

    all_missing = all(
        t.status == ValidationStatus.MISSING
        for t in result.tables.values()
    )

    if all_complete:
        result.status = ValidationStatus.COMPLETE
    elif all_missing:
        result.status = ValidationStatus.MISSING
    elif any_data:
        result.status = ValidationStatus.PARTIAL
    else:
        result.status = ValidationStatus.MISSING
