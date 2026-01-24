"""
Phase 5 Validator - Predictions

Validates Phase 5 predictions are generated correctly.
"""

from datetime import date
from typing import Optional, Dict, Set
import time
import logging

from google.cloud import bigquery
from google.api_core.exceptions import BadRequest

from shared.validation.config import (
    PROJECT_ID,
    EXPECTED_PREDICTION_SYSTEMS,
    PREDICTIONS_PER_PLAYER,
    PREDICTIONS_TABLE,
    PREDICTIONS_DATASET,
    PREDICTIONS_DATE_COLUMN,
)
from shared.validation.context.schedule_context import ScheduleContext
from shared.validation.context.player_universe import PlayerUniverse
from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
)

logger = logging.getLogger(__name__)


def validate_phase5(
    game_date: date,
    schedule_context: ScheduleContext,
    player_universe: PlayerUniverse,
    client: Optional[bigquery.Client] = None,
) -> PhaseValidationResult:
    """
    Validate Phase 5 predictions.

    Args:
        game_date: Date to validate
        schedule_context: Schedule context for the date
        player_universe: Player universe for the date
        client: Optional BigQuery client

    Returns:
        PhaseValidationResult for Phase 5
    """
    start_time = time.time()

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    result = PhaseValidationResult(phase=5, status=ValidationStatus.MISSING)

    # If not a valid processing date, return early
    if not schedule_context.is_valid_processing_date:
        result.status = ValidationStatus.NOT_APPLICABLE
        result.issues.append(schedule_context.skip_reason or "Not a valid processing date")
        return result

    # Bootstrap handling
    if schedule_context.is_bootstrap:
        result.status = ValidationStatus.BOOTSTRAP_SKIP
        result.tables[PREDICTIONS_TABLE] = TableValidation(
            table_name=PREDICTIONS_TABLE,
            dataset=PREDICTIONS_DATASET,
            status=ValidationStatus.BOOTSTRAP_SKIP,
            record_count=0,
            expected_count=0,
        )
        return result

    # Query prediction details
    prediction_data = _query_predictions(client, game_date)

    # Build table validation result
    table_result = _build_table_result(
        prediction_data=prediction_data,
        player_universe=player_universe,
        game_date=game_date,
    )
    result.tables[PREDICTIONS_TABLE] = table_result

    # Determine overall status
    result.status = table_result.status

    result.validation_duration_ms = (time.time() - start_time) * 1000
    result._update_aggregates()

    return result


def _query_predictions(client: bigquery.Client, game_date: date) -> Dict:
    """Query prediction statistics for a date."""

    # First try query with has_prop_line (new schema)
    # Fall back to simpler query if column doesn't exist
    query_with_prop = f"""
    SELECT
        player_lookup,
        COUNT(DISTINCT system_id) as systems_count,
        COUNT(*) as prediction_count,
        ARRAY_AGG(DISTINCT system_id) as systems,
        MAX(CASE WHEN has_prop_line = TRUE THEN 1 ELSE 0 END) as has_prop_line
    FROM `{PROJECT_ID}.{PREDICTIONS_DATASET}.{PREDICTIONS_TABLE}`
    WHERE {PREDICTIONS_DATE_COLUMN} = @game_date
    GROUP BY player_lookup
    """

    query_simple = f"""
    SELECT
        player_lookup,
        COUNT(DISTINCT system_id) as systems_count,
        COUNT(*) as prediction_count,
        ARRAY_AGG(DISTINCT system_id) as systems
    FROM `{PROJECT_ID}.{PREDICTIONS_DATASET}.{PREDICTIONS_TABLE}`
    WHERE {PREDICTIONS_DATE_COLUMN} = @game_date
    GROUP BY player_lookup
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    result = {
        'total_predictions': 0,
        'players_with_predictions': set(),
        'players_with_all_systems': set(),
        'players_with_incomplete_systems': {},  # player -> systems_count
        'systems_found': set(),
        'players_with_prop_line': set(),
        'players_without_prop_line': set(),
        'has_prop_line_column': False,
    }

    try:
        # Try with has_prop_line first
        try:
            query_result = client.query(query_with_prop, job_config=job_config).result(timeout=60)
            result['has_prop_line_column'] = True
        except BadRequest:
            # Column doesn't exist, fall back to simple query
            logger.debug("has_prop_line column not found, using simple query")
            query_result = client.query(query_simple, job_config=job_config).result(timeout=60)

        for row in query_result:
            player = row.player_lookup
            systems_count = row.systems_count
            prediction_count = row.prediction_count

            result['total_predictions'] += prediction_count
            result['players_with_predictions'].add(player)

            # Track systems found
            if row.systems:
                result['systems_found'].update(row.systems)

            # Check if player has all 5 systems
            if systems_count >= PREDICTIONS_PER_PLAYER:
                result['players_with_all_systems'].add(player)
            else:
                result['players_with_incomplete_systems'][player] = systems_count

            # Track prop line status if available
            if result['has_prop_line_column'] and hasattr(row, 'has_prop_line'):
                if row.has_prop_line:
                    result['players_with_prop_line'].add(player)
                else:
                    result['players_without_prop_line'].add(player)

    except Exception as e:
        logger.error(f"Error querying predictions for {game_date}: {e}")

    return result


def _build_table_result(
    prediction_data: Dict,
    player_universe: PlayerUniverse,
    game_date: date,
) -> TableValidation:
    """Build TableValidation from prediction data."""

    players_predicted = len(prediction_data['players_with_predictions'])
    total_predictions = prediction_data['total_predictions']

    # Target state: all rostered players should have predictions (active + DNP + inactive)
    expected_players = player_universe.total_rostered
    expected_predictions = expected_players * PREDICTIONS_PER_PLAYER

    # Determine status
    if total_predictions == 0:
        status = ValidationStatus.MISSING
    elif players_predicted >= expected_players * 0.95:
        # Check if all have complete systems
        incomplete_count = len(prediction_data['players_with_incomplete_systems'])
        if incomplete_count == 0:
            status = ValidationStatus.COMPLETE
        else:
            status = ValidationStatus.PARTIAL
    elif players_predicted > 0:
        status = ValidationStatus.PARTIAL
    else:
        status = ValidationStatus.MISSING

    table_result = TableValidation(
        table_name=PREDICTIONS_TABLE,
        dataset=PREDICTIONS_DATASET,
        status=status,
        record_count=total_predictions,
        expected_count=expected_predictions,
        player_count=players_predicted,
        expected_players=expected_players,
    )

    # Issues and warnings
    if status == ValidationStatus.MISSING:
        table_result.issues.append(f"No predictions for {game_date}")
    elif players_predicted < expected_players:
        missing_count = expected_players - players_predicted
        table_result.warnings.append(
            f"{players_predicted}/{expected_players} players have predictions "
            f"({missing_count} missing)"
        )

    # Check for incomplete prediction systems
    incomplete = prediction_data['players_with_incomplete_systems']
    if incomplete:
        sample = list(incomplete.items())[:3]
        sample_str = ', '.join(f"{p}: {c}/5" for p, c in sample)
        table_result.warnings.append(
            f"{len(incomplete)} players have incomplete systems (e.g., {sample_str})"
        )

    # Check for unexpected systems
    expected_systems = set(EXPECTED_PREDICTION_SYSTEMS)
    actual_systems = prediction_data['systems_found']
    unexpected = actual_systems - expected_systems
    missing_systems = expected_systems - actual_systems

    if unexpected:
        table_result.warnings.append(
            f"Unexpected prediction systems found: {unexpected}"
        )
    if missing_systems and total_predictions > 0:
        table_result.warnings.append(
            f"Expected prediction systems not found: {missing_systems}"
        )

    # Report prop line coverage breakdown
    if prediction_data.get('has_prop_line_column'):
        with_prop = len(prediction_data['players_with_prop_line'])
        without_prop = len(prediction_data['players_without_prop_line'])
        total = with_prop + without_prop
        if total > 0:
            prop_pct = (with_prop / total) * 100
            table_result.metadata = {
                'players_with_prop_line': with_prop,
                'players_without_prop_line': without_prop,
                'prop_coverage_pct': prop_pct,
                'prop_summary': f"{with_prop} with props, {without_prop} without ({prop_pct:.1f}% coverage)",
            }
    else:
        # No has_prop_line column - compare against props universe
        table_result.metadata = {
            'players_with_prop_line': min(players_predicted, player_universe.total_with_props),
            'players_without_prop_line': max(0, players_predicted - player_universe.total_with_props),
            'prop_summary': f"~{player_universe.total_with_props} expected with props (column not available)",
        }

    return table_result
