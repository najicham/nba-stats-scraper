"""
Chain Validator - Validates data sources organized by fallback chains.

This module validates Phase 1 (GCS) and Phase 2 (BQ) data together, organized
by the fallback chains defined in fallback_config.yaml.

Key features:
- Unified view of GCS files + BQ records per chain
- Tracks which source is being used (primary vs fallback)
- Reports quality impact when fallbacks are used or chains are missing
"""

from datetime import date
from typing import Dict, List, Optional, Tuple
import logging
import time

from google.cloud import bigquery, storage

from shared.validation.chain_config import (
    ChainConfig,
    ChainValidation,
    SourceConfig,
    SourceValidation,
    get_chain_configs,
    GCS_PATH_MAPPING,
    SEASON_BASED_GCS_SOURCES,
    GCS_BUCKET,
    VIRTUAL_SOURCE_DEPENDENCIES,
    CHAIN_VALIDATION_ORDER,
)
from shared.validation.config import PROJECT_ID, BQ_QUERY_TIMEOUT_SECONDS
from shared.validation.context.schedule_context import ScheduleContext

logger = logging.getLogger(__name__)


def _check_virtual_source_available(
    source_name: str,
    validated_chains: Dict[str, 'ChainValidation'],
) -> bool:
    """
    Check if a virtual source can provide data.

    Virtual sources depend on other chains (e.g., reconstructed_team_from_players
    depends on player_boxscores chain having data).

    Args:
        source_name: Name of the virtual source
        validated_chains: Already-validated chains

    Returns:
        True if the virtual source's input chain is complete/partial
    """
    # Get the input chain for this virtual source
    input_chain_name = VIRTUAL_SOURCE_DEPENDENCIES.get(source_name)

    if input_chain_name is None:
        # No dependency defined - assume virtual source is unavailable
        # (safer default: don't count virtual without known dependency)
        logger.debug(f"Virtual source {source_name} has no defined dependency")
        return False

    # Check if input chain has been validated
    input_chain = validated_chains.get(input_chain_name)
    if input_chain is None:
        # Input chain not yet validated - can't determine
        logger.warning(
            f"Virtual source {source_name} depends on {input_chain_name} "
            "which hasn't been validated yet. Check CHAIN_VALIDATION_ORDER."
        )
        return False

    # Virtual source is available if input chain has data
    if input_chain.status in ('complete', 'partial'):
        logger.debug(
            f"Virtual source {source_name} available "
            f"(input chain {input_chain_name} is {input_chain.status})"
        )
        return True
    else:
        logger.debug(
            f"Virtual source {source_name} unavailable "
            f"(input chain {input_chain_name} is {input_chain.status})"
        )
        return False


def validate_all_chains(
    game_date: date,
    schedule_context: ScheduleContext,
    bq_client: Optional[bigquery.Client] = None,
    gcs_client: Optional[storage.Client] = None,
    skip_roster_chain: bool = True,
) -> Dict[str, ChainValidation]:
    """
    Validate all fallback chains for a given date.

    Chains are validated in dependency order (CHAIN_VALIDATION_ORDER) so that
    virtual sources can check if their input chain has data.

    Args:
        game_date: Date to validate
        schedule_context: Schedule context for the date
        bq_client: Optional BigQuery client (created if not provided)
        gcs_client: Optional GCS client (created if not provided)
        skip_roster_chain: Skip player_roster chain (handled by maintenance)

    Returns:
        Dict mapping chain_name -> ChainValidation
    """
    start_time = time.time()

    if bq_client is None:
        bq_client = bigquery.Client(project=PROJECT_ID)
    if gcs_client is None:
        gcs_client = storage.Client()

    chain_configs = get_chain_configs()
    results = {}

    # Validate chains in dependency order
    # This ensures input chains are validated before chains with virtual sources
    ordered_chains = []
    for chain_name in CHAIN_VALIDATION_ORDER:
        if chain_name in chain_configs:
            ordered_chains.append(chain_name)

    # Add any chains not in the order list (safety fallback)
    for chain_name in chain_configs:
        if chain_name not in ordered_chains:
            ordered_chains.append(chain_name)

    for chain_name in ordered_chains:
        # Skip player_roster chain if requested (handled separately by maintenance)
        if skip_roster_chain and chain_name == 'player_roster':
            continue

        chain_config = chain_configs[chain_name]
        chain_start = time.time()

        # Pass already-validated chain results for virtual source dependency checking
        results[chain_name] = validate_chain(
            chain_config=chain_config,
            game_date=game_date,
            schedule_context=schedule_context,
            bq_client=bq_client,
            gcs_client=gcs_client,
            validated_chains=results,  # Pass previous results
        )
        chain_duration = time.time() - chain_start
        logger.debug(f"Chain {chain_name} validated in {chain_duration:.2f}s")

    total_duration = time.time() - start_time
    logger.info(f"All chains validated in {total_duration:.2f}s")

    return results


def validate_chain(
    chain_config: ChainConfig,
    game_date: date,
    schedule_context: ScheduleContext,
    bq_client: bigquery.Client,
    gcs_client: storage.Client,
    validated_chains: Optional[Dict[str, ChainValidation]] = None,
) -> ChainValidation:
    """
    Validate a single fallback chain.

    The chain is considered "complete" if ANY source has data (primary or fallback).
    We track which source will actually be used by the processor.

    For virtual sources, we check if their input chain has data before considering
    them as available. This prevents false "complete" status when virtual sources
    can't actually provide data.

    Args:
        chain_config: Chain configuration
        game_date: Date to validate
        schedule_context: Schedule context
        bq_client: BigQuery client
        gcs_client: GCS client
        validated_chains: Already-validated chains (for virtual source dependency checking)

    Returns:
        ChainValidation with status and source details
    """
    if validated_chains is None:
        validated_chains = {}

    source_validations = []
    primary_available = False
    fallback_used = False
    first_available_source: Optional[SourceConfig] = None

    # Validate each source in the chain
    for source_config in chain_config.sources:
        source_val = validate_source(
            source_config=source_config,
            game_date=game_date,
            bq_client=bq_client,
            gcs_client=gcs_client,
        )
        source_validations.append(source_val)

        # Determine if this source has usable data
        if source_config.is_virtual:
            # Virtual sources only "have data" if their input chain is complete
            has_data = _check_virtual_source_available(
                source_config.name,
                validated_chains,
            )
            if not has_data:
                # Update status to show why virtual source isn't available
                source_val.status = 'virtual_unavailable'
        else:
            has_data = source_val.bq_record_count > 0

        # Track which source will be used (first one with data)
        if has_data and first_available_source is None:
            first_available_source = source_config
            if source_config.is_primary:
                primary_available = True
                source_val.status = 'primary'
            elif source_config.is_virtual:
                # Virtual source is being used as fallback
                fallback_used = True
                source_val.status = 'virtual_used'
            else:
                # Non-virtual fallback
                fallback_used = True
                source_val.status = 'fallback'
        elif has_data and not source_config.is_virtual:
            # Mark non-virtual as available (backup to the one being used)
            source_val.status = 'available'
        # Virtual sources keep their status (virtual, virtual_unavailable, or virtual_used)

    # Determine overall chain status
    if first_available_source is not None:
        chain_status = 'complete'
    elif any(sv.bq_record_count > 0 for sv in source_validations):
        # Partial data but no complete source
        chain_status = 'partial'
    else:
        chain_status = 'missing'

    # Build impact message
    impact_message = _build_impact_message(
        chain_config=chain_config,
        chain_status=chain_status,
        fallback_used=fallback_used,
        first_available_source=first_available_source,
    )

    return ChainValidation(
        chain=chain_config,
        sources=source_validations,
        status=chain_status,
        primary_available=primary_available,
        fallback_used=fallback_used,
        impact_message=impact_message,
    )


def validate_source(
    source_config: SourceConfig,
    game_date: date,
    bq_client: bigquery.Client,
    gcs_client: storage.Client,
) -> SourceValidation:
    """
    Validate a single data source (both GCS and BQ).

    Args:
        source_config: Source configuration
        game_date: Date to validate
        bq_client: BigQuery client
        gcs_client: GCS client

    Returns:
        SourceValidation with counts and status
    """
    # Virtual sources don't have GCS or BQ counts
    if source_config.is_virtual:
        return SourceValidation(
            source=source_config,
            gcs_file_count=None,
            bq_record_count=0,
            status='virtual',
        )

    # Check GCS files
    gcs_count = None
    if source_config.gcs_path_template:
        gcs_count = count_gcs_files(
            gcs_client=gcs_client,
            source_name=source_config.name,
            gcs_path_template=source_config.gcs_path_template,
            game_date=game_date,
        )

    # Check BQ records
    bq_count = 0
    bq_timeout = False
    if source_config.table:
        bq_count = count_bq_records(
            bq_client=bq_client,
            dataset=source_config.dataset,
            table=source_config.table,
            game_date=game_date,
        )
        # Handle timeout sentinel (-1)
        if bq_count == -1:
            bq_timeout = True
            bq_count = 0  # Reset for downstream logic

    # Determine status (will be updated by validate_chain based on chain position)
    if bq_timeout:
        status = 'timeout'  # Distinct from 'missing' - query didn't complete
    elif bq_count == 0:
        status = 'missing'
    else:
        status = 'available'

    return SourceValidation(
        source=source_config,
        gcs_file_count=gcs_count,
        bq_record_count=bq_count,
        status=status,
    )


def count_gcs_files(
    gcs_client: storage.Client,
    source_name: str,
    gcs_path_template: str,
    game_date: date,
) -> Optional[int]:
    """
    Count JSON/CSV files in GCS for a source on a given date.

    Args:
        gcs_client: GCS client
        source_name: Name of the source (for special handling)
        gcs_path_template: Base path template
        game_date: Date to check

    Returns:
        Number of data files found
    """
    try:
        bucket = gcs_client.bucket(GCS_BUCKET)
        date_str = game_date.strftime('%Y-%m-%d')

        # Handle season-based paths differently
        if source_name in SEASON_BASED_GCS_SOURCES:
            # For season-based sources, we can't easily count by date
            # Return None to indicate "not applicable for per-date counting"
            return None

        # Build prefix
        prefix = f"{gcs_path_template}/{date_str}/"

        # Special handling for bettingpros (has market_type subdir)
        if source_name == 'bettingpros_player_points_props':
            prefix = f"bettingpros/player-props/points/{date_str}/"

        # List blobs with this prefix
        blobs = list(bucket.list_blobs(prefix=prefix, max_results=100))

        # Count data files (JSON or CSV)
        data_files = [
            b for b in blobs
            if b.name.endswith('.json') or b.name.endswith('.csv')
        ]
        return len(data_files)

    except Exception as e:
        logger.warning(f"Error counting GCS files for {source_name}: {e}")
        return 0


def count_bq_records(
    bq_client: bigquery.Client,
    dataset: str,
    table: str,
    game_date: date,
) -> int:
    """
    Count records in a BigQuery table for a given date.

    For reference tables (no date column), counts all records.
    Uses BQ_QUERY_TIMEOUT_SECONDS to prevent hanging.

    Args:
        bq_client: BigQuery client
        dataset: Dataset name
        table: Table name
        game_date: Date to check

    Returns:
        Number of records
    """
    try:
        # Determine the date column based on table name
        date_column = _get_date_column(table)

        if date_column is None:
            # Reference table - count all records (current snapshot)
            query = f"""
                SELECT COUNT(*) as cnt
                FROM `{PROJECT_ID}.{dataset}.{table}`
            """
            job_config = bigquery.QueryJobConfig()
        else:
            # Date-partitioned table - filter by date
            query = f"""
                SELECT COUNT(*) as cnt
                FROM `{PROJECT_ID}.{dataset}.{table}`
                WHERE {date_column} = @game_date
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter('game_date', 'DATE', game_date)
                ]
            )

        # Execute with timeout
        result = bq_client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        row = next(iter(result))
        return row.cnt

    except TimeoutError:
        logger.warning(f"Timeout counting BQ records for {dataset}.{table} (>{BQ_QUERY_TIMEOUT_SECONDS}s)")
        return -1  # Sentinel value: timeout (distinct from 0 = no data)
    except Exception as e:
        logger.warning(f"Error counting BQ records for {dataset}.{table}: {e}")
        return 0


def _get_date_column(table: str) -> Optional[str]:
    """
    Get the appropriate date column for a table.

    Most tables use 'game_date', but some tables use different columns.
    Reference tables (current snapshots) return None - they have no date column.

    Returns:
        Column name or None for reference tables
    """
    # Reference tables - current snapshots with no date column
    # These are validated by count only, not filtered by date
    REFERENCE_TABLES = {
        'nbac_player_list_current',
        'bdl_active_players_current',
        'espn_team_rosters',  # Uses roster_date but validated differently
        'nbac_team_list',
        'br_rosters_current',  # Basketball Reference rosters
    }
    if table in REFERENCE_TABLES:
        return None

    # Phase 4 tables with different date columns
    if table in ('player_shot_zone_analysis', 'team_defense_zone_analysis'):
        return 'analysis_date'
    elif table == 'player_daily_cache':
        return 'cache_date'
    # BDL injuries uses scrape_date
    elif table == 'bdl_injuries':
        return 'scrape_date'
    # Rosters use roster_date
    elif table == 'espn_team_rosters':
        return 'roster_date'
    # Default to game_date (works for nbac_injury_report, most raw tables)
    else:
        return 'game_date'


def _build_impact_message(
    chain_config: ChainConfig,
    chain_status: str,
    fallback_used: bool,
    first_available_source: Optional[SourceConfig],
) -> Optional[str]:
    """
    Build an impact message for the chain status.

    Shows what the impact is when:
    - Chain is missing entirely
    - Fallback source is being used
    """
    if chain_status == 'missing':
        # Show the on_all_fail message with quality impact
        message = chain_config.on_all_fail_message
        if chain_config.quality_impact:
            message += f" ({chain_config.quality_impact:+d} quality)"
        return message

    elif fallback_used and first_available_source:
        # Show which fallback is being used
        return (
            f"Using fallback: {first_available_source.name} "
            f"({first_available_source.quality_tier} quality)"
        )

    return None


# =============================================================================
# SUMMARY HELPERS
# =============================================================================

def get_chain_summary(chain_validations: Dict[str, ChainValidation]) -> Dict[str, int]:
    """
    Get a summary of chain statuses.

    Returns:
        Dict with counts: {'complete': N, 'partial': N, 'missing': N}
    """
    summary = {'complete': 0, 'partial': 0, 'missing': 0}
    for cv in chain_validations.values():
        summary[cv.status] = summary.get(cv.status, 0) + 1
    return summary


def get_chains_needing_attention(
    chain_validations: Dict[str, ChainValidation]
) -> List[Tuple[str, ChainValidation]]:
    """
    Get chains that need attention (missing critical or using fallback).

    Returns:
        List of (chain_name, ChainValidation) tuples
    """
    needs_attention = []
    for name, cv in chain_validations.items():
        if cv.status == 'missing' and cv.chain.severity == 'critical':
            needs_attention.append((name, cv))
        elif cv.fallback_used and cv.chain.severity in ('critical', 'warning'):
            needs_attention.append((name, cv))
    return needs_attention


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == '__main__':
    """Quick test to verify chain validation works."""
    from datetime import date as dt
    from shared.validation.context.schedule_context import get_schedule_context

    test_date = dt(2021, 10, 19)  # Season opener with known data
    print(f"Testing chain validation for {test_date}...")

    # Get schedule context
    schedule_context = get_schedule_context(test_date)
    print(f"Schedule: {schedule_context.game_count} games")

    # Validate all chains
    chain_results = validate_all_chains(
        game_date=test_date,
        schedule_context=schedule_context,
    )

    print(f"\nValidated {len(chain_results)} chains:")
    for name, cv in chain_results.items():
        status_symbol = {'complete': '✓', 'partial': '△', 'missing': '○'}.get(cv.status, '?')
        print(f"\n{status_symbol} {name} ({cv.chain.severity}): {cv.status}")
        for sv in cv.sources:
            gcs_str = str(sv.gcs_file_count) if sv.gcs_file_count is not None else '-'
            print(f"    {sv.source.name}: GCS={gcs_str}, BQ={sv.bq_record_count}, status={sv.status}")
        if cv.impact_message:
            print(f"    Impact: {cv.impact_message}")

    # Summary
    summary = get_chain_summary(chain_results)
    print(f"\nSummary: {summary['complete']}/{len(chain_results)} complete, "
          f"{summary['partial']} partial, {summary['missing']} missing")
