"""
Phase 4 Validator - Precompute

Validates Phase 4 precompute tables, with bootstrap period handling.
"""

from datetime import date
from typing import Optional
import time
import logging

from google.cloud import bigquery

from shared.validation.config import (
    PROJECT_ID,
    PHASE4_TABLES,
)
from shared.validation.context.schedule_context import ScheduleContext
from shared.validation.context.player_universe import PlayerUniverse
from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
    query_table_count,
    query_player_count,
    query_quality_distribution,
)

logger = logging.getLogger(__name__)


def validate_phase4(
    game_date: date,
    schedule_context: ScheduleContext,
    player_universe: PlayerUniverse,
    client: Optional[bigquery.Client] = None,
) -> PhaseValidationResult:
    """
    Validate Phase 4 precompute tables.

    Args:
        game_date: Date to validate
        schedule_context: Schedule context for the date
        player_universe: Player universe for the date
        client: Optional BigQuery client

    Returns:
        PhaseValidationResult for Phase 4
    """
    start_time = time.time()

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    result = PhaseValidationResult(phase=4, status=ValidationStatus.MISSING)

    # If not a valid processing date, return early
    if not schedule_context.is_valid_processing_date:
        result.status = ValidationStatus.NOT_APPLICABLE
        result.issues.append(schedule_context.skip_reason or "Not a valid processing date")
        return result

    # Bootstrap handling
    is_bootstrap = schedule_context.is_bootstrap

    # Validate each table
    for table_name, table_config in PHASE4_TABLES.items():
        table_result = _validate_table(
            client=client,
            game_date=game_date,
            table_name=table_name,
            table_config=table_config,
            schedule_context=schedule_context,
            player_universe=player_universe,
            is_bootstrap=is_bootstrap,
        )
        result.tables[table_name] = table_result

    # Determine overall status
    _determine_phase_status(result, is_bootstrap)

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
    is_bootstrap: bool,
) -> TableValidation:
    """Validate a single Phase 4 table."""

    # Query record count
    record_count = query_table_count(
        client=client,
        dataset=table_config.dataset,
        table=table_config.table_name,
        date_column=table_config.date_column,
        game_date=game_date,
    )

    # Bootstrap handling
    if is_bootstrap and table_config.skips_bootstrap:
        # Expected to be empty during bootstrap
        status = ValidationStatus.BOOTSTRAP_SKIP

        return TableValidation(
            table_name=table_config.table_name,
            dataset=table_config.dataset,
            status=status,
            record_count=record_count,
            expected_count=0,
        )

    # Non-bootstrap: determine expected count
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

    # Special check for ml_feature_store_v2 (critical for Phase 5)
    if table_name == 'ml_feature_store_v2' and status != ValidationStatus.COMPLETE:
        table_result.issues.append(
            "ml_feature_store_v2 incomplete - Phase 5 predictions will be affected"
        )

    return table_result


def _determine_phase_status(result: PhaseValidationResult, is_bootstrap: bool) -> None:
    """Determine overall phase status from table results."""

    if is_bootstrap:
        # All tables should be bootstrap_skip
        all_skip = all(
            t.status == ValidationStatus.BOOTSTRAP_SKIP
            for t in result.tables.values()
        )
        if all_skip:
            result.status = ValidationStatus.BOOTSTRAP_SKIP
            return

    all_complete = all(
        t.status in (ValidationStatus.COMPLETE, ValidationStatus.BOOTSTRAP_SKIP)
        for t in result.tables.values()
    )

    any_data = any(
        t.record_count > 0
        for t in result.tables.values()
    )

    if all_complete:
        result.status = ValidationStatus.COMPLETE
    elif any_data:
        result.status = ValidationStatus.PARTIAL
    else:
        result.status = ValidationStatus.MISSING
