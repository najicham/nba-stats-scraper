"""
Phase 1 Validator - GCS Raw JSON Files

Validates that scrapers have saved JSON files to GCS.
This helps distinguish between:
- Scraper never ran (no GCS files)
- Scraper ran but processor didn't run (GCS exists, BQ empty)
- All complete (both GCS and BQ have data)

GCS Structure:
- nba-com/gamebooks-data/{date}/ - player boxscores
- nba-com/team-boxscore/{date}/ - team boxscores
- bettingpros/player-props/{date}/ - betting props
- big-data-ball/play-by-play/{date}/ - play by play
- ball-dont-lie/player-boxscores/{date}/ - BDL fallback
"""

from datetime import date
from typing import Optional, Dict, List
import time
import logging

from google.cloud import storage

from shared.validation.context.schedule_context import ScheduleContext
from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

# GCS bucket
GCS_BUCKET = 'nba-scraped-data'

# Phase 1 sources - maps to Phase 2 tables
PHASE1_SOURCES = {
    'gamebook_json': {
        'gcs_path': 'nba-com/gamebooks-data',
        'priority': 'critical',
        'description': 'Player boxscores JSON',
        'maps_to_phase2': 'nbac_gamebook_player_stats',
    },
    'team_boxscore_json': {
        'gcs_path': 'nba-com/team-boxscore',
        'priority': 'critical',
        'description': 'Team boxscores JSON',
        'maps_to_phase2': 'nbac_team_boxscore',
    },
    'bettingpros_props_json': {
        'gcs_path': 'bettingpros/player-props',
        'priority': 'important',
        'description': 'BettingPros props JSON',
        'maps_to_phase2': 'bettingpros_player_points_props',
    },
    'schedule_json': {
        'gcs_path': 'nba-com/schedule',
        'priority': 'important',
        'description': 'Schedule JSON',
        'maps_to_phase2': 'nbac_schedule',
    },
    'bdl_boxscores_json': {
        'gcs_path': 'ball-dont-lie/player-boxscores',
        'priority': 'fallback',
        'description': 'BDL player boxscores (fallback)',
        'maps_to_phase2': 'bdl_player_boxscores',
    },
}


def validate_phase1(
    game_date: date,
    schedule_context: ScheduleContext,
    client: Optional[storage.Client] = None,
) -> PhaseValidationResult:
    """
    Validate Phase 1 GCS JSON files exist.

    Args:
        game_date: Date to validate
        schedule_context: Schedule context for the date
        client: Optional GCS client

    Returns:
        PhaseValidationResult for Phase 1
    """
    start_time = time.time()

    if client is None:
        client = storage.Client()

    result = PhaseValidationResult(phase=1, status=ValidationStatus.MISSING)

    # If not a valid processing date, return early
    if not schedule_context.is_valid_processing_date:
        result.status = ValidationStatus.NOT_APPLICABLE
        result.issues.append(schedule_context.skip_reason or "Not a valid processing date")
        return result

    bucket = client.bucket(GCS_BUCKET)
    date_str = game_date.strftime('%Y-%m-%d')

    # Check each source
    for source_name, source_config in PHASE1_SOURCES.items():
        table_result = _check_gcs_files(
            bucket=bucket,
            source_name=source_name,
            source_config=source_config,
            date_str=date_str,
            schedule_context=schedule_context,
        )
        result.tables[source_name] = table_result

    # Determine overall status
    _determine_phase_status(result)

    result.validation_duration_ms = (time.time() - start_time) * 1000
    result._update_aggregates()

    return result


def _check_gcs_files(
    bucket,
    source_name: str,
    source_config: Dict,
    date_str: str,
    schedule_context: ScheduleContext,
) -> TableValidation:
    """Check if GCS files exist for a source."""

    gcs_path = source_config['gcs_path']
    prefix = f"{gcs_path}/{date_str}/"

    try:
        # List blobs with this prefix (limit to check existence)
        blobs = list(bucket.list_blobs(prefix=prefix, max_results=100))
        file_count = len(blobs)

        # Filter to just JSON files
        json_files = [b for b in blobs if b.name.endswith('.json')]
        json_count = len(json_files)

    except Exception as e:
        logger.error(f"Error checking GCS {prefix}: {e}", exc_info=True)
        return TableValidation(
            table_name=source_name,
            dataset='gcs',
            status=ValidationStatus.ERROR,
            issues=[f"Error checking GCS: {e}"],
        )

    # Determine expected count based on games
    expected_count = schedule_context.game_count if schedule_context.game_count > 0 else 1

    # Determine status
    if json_count == 0:
        status = ValidationStatus.MISSING
    elif json_count >= expected_count:
        status = ValidationStatus.COMPLETE
    else:
        status = ValidationStatus.PARTIAL

    table_result = TableValidation(
        table_name=source_name,
        dataset='gcs',
        status=status,
        record_count=json_count,
        expected_count=expected_count,
        game_count=schedule_context.game_count,
    )

    # Add metadata
    table_result.metadata = {
        'gcs_path': prefix,
        'total_files': file_count,
        'json_files': json_count,
        'maps_to': source_config['maps_to_phase2'],
        'priority': source_config['priority'],
    }

    # Issues/warnings
    if status == ValidationStatus.MISSING:
        table_result.issues.append(
            f"{source_name}: No JSON files in gs://{GCS_BUCKET}/{prefix}"
        )
    elif status == ValidationStatus.PARTIAL:
        table_result.warnings.append(
            f"{source_name}: {json_count}/{expected_count} games have files"
        )

    return table_result


def _determine_phase_status(result: PhaseValidationResult) -> None:
    """Determine overall phase status from source results."""

    # Check critical sources first
    critical_complete = True
    for source_name, table in result.tables.items():
        source_config = PHASE1_SOURCES.get(source_name, {})
        if source_config.get('priority') == 'critical':
            if table.status not in (ValidationStatus.COMPLETE, ValidationStatus.PARTIAL):
                critical_complete = False
                break

    all_complete = all(
        t.status == ValidationStatus.COMPLETE
        for t in result.tables.values()
    )

    any_data = any(
        t.record_count > 0
        for t in result.tables.values()
    )

    if all_complete:
        result.status = ValidationStatus.COMPLETE
    elif critical_complete and any_data:
        result.status = ValidationStatus.PARTIAL
    elif any_data:
        result.status = ValidationStatus.PARTIAL
    else:
        result.status = ValidationStatus.MISSING
