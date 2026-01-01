"""
Maintenance Validator - Validates roster and registry data freshness.

This module validates daily maintenance data (player rosters, registry) that
is needed for orchestration but not tied to a specific game date.

Only shown for today/yesterday validation runs.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import logging

from google.cloud import bigquery

from shared.validation.chain_config import (
    ChainConfig,
    ChainValidation,
    SourceConfig,
    SourceValidation,
    get_chain_configs,
)
from shared.validation.config import PROJECT_ID
from shared.validation.time_awareness import TimeContext

logger = logging.getLogger(__name__)

# How many days old before we consider roster data "stale"
STALE_THRESHOLD_DAYS = 2


@dataclass
class RegistryStatus:
    """Status of the player registry."""
    total_players: int = 0
    last_update: Optional[datetime] = None
    is_current: bool = False
    staleness_days: int = 0


@dataclass
class MaintenanceValidation:
    """Validation result for daily maintenance items."""
    roster_chain: Optional[ChainValidation] = None
    registry_status: Optional[RegistryStatus] = None
    unresolved_players: int = 0
    is_current: bool = True


def validate_maintenance(
    game_date: date,
    time_context: TimeContext,
    bq_client: Optional[bigquery.Client] = None,
) -> Optional[MaintenanceValidation]:
    """
    Validate daily maintenance tasks (roster, registry).

    Only runs for today or yesterday to avoid noise on historical dates.

    Args:
        game_date: Date being validated
        time_context: Time context for the validation
        bq_client: Optional BigQuery client

    Returns:
        MaintenanceValidation if today/yesterday, None otherwise
    """
    # Only show maintenance for today/yesterday
    if not (time_context.is_today or time_context.is_yesterday):
        return None

    if bq_client is None:
        bq_client = bigquery.Client(project=PROJECT_ID)

    # Validate player roster chain
    roster_chain = _validate_roster_chain(bq_client)

    # Check registry status
    registry_status = _check_registry_status(bq_client)

    # Check for unresolved players
    unresolved = _count_unresolved_players(bq_client)

    # Determine if maintenance is current
    is_current = (
        roster_chain is not None and
        roster_chain.status == 'complete' and
        registry_status is not None and
        registry_status.is_current
    )

    return MaintenanceValidation(
        roster_chain=roster_chain,
        registry_status=registry_status,
        unresolved_players=unresolved,
        is_current=is_current,
    )


def _validate_roster_chain(bq_client: bigquery.Client) -> Optional[ChainValidation]:
    """Validate the player_roster chain from fallback_config.yaml."""
    chain_configs = get_chain_configs()
    roster_config = chain_configs.get('player_roster')

    if not roster_config:
        logger.warning("player_roster chain not found in config")
        return None

    source_validations = []
    first_available = None

    for source_config in roster_config.sources:
        # Roster sources don't use date filtering - they're "current" tables
        sv = _validate_roster_source(source_config, bq_client)
        source_validations.append(sv)

        # Track first available source
        if sv.bq_record_count > 0 and first_available is None:
            first_available = source_config
            if source_config.is_primary:
                sv.status = 'primary'
            else:
                sv.status = 'fallback'
        elif sv.bq_record_count > 0:
            sv.status = 'available'

    # Determine chain status
    if first_available is not None:
        chain_status = 'complete'
    else:
        chain_status = 'missing'

    return ChainValidation(
        chain=roster_config,
        sources=source_validations,
        status=chain_status,
        primary_available=first_available and first_available.is_primary,
        fallback_used=first_available and not first_available.is_primary,
    )


def _validate_roster_source(
    source_config: SourceConfig,
    bq_client: bigquery.Client,
) -> SourceValidation:
    """Validate a single roster source."""
    # These are "current" tables, not date-partitioned
    # Just check record count

    if source_config.table is None:
        return SourceValidation(
            source=source_config,
            gcs_file_count=None,
            bq_record_count=0,
            status='missing',
        )

    try:
        # Simple count query - these tables may be views or have different schemas
        query = f"""
            SELECT COUNT(*) as cnt
            FROM `{PROJECT_ID}.{source_config.dataset}.{source_config.table}`
        """
        result = bq_client.query(query).result(timeout=60)
        row = next(iter(result))

        record_count = row.cnt or 0

        return SourceValidation(
            source=source_config,
            gcs_file_count=None,
            bq_record_count=record_count,
            status='available' if record_count > 0 else 'missing',
        )

    except Exception as e:
        logger.warning(f"Error validating roster source {source_config.table}: {e}")
        return SourceValidation(
            source=source_config,
            gcs_file_count=None,
            bq_record_count=0,
            status='missing',
        )


def _check_registry_status(bq_client: bigquery.Client) -> RegistryStatus:
    """Check the player registry status using processor run history."""
    try:
        # First get total player count
        count_query = f"""
            SELECT COUNT(*) as total
            FROM `{PROJECT_ID}.nba_reference.nba_players_registry`
        """
        count_result = bq_client.query(count_query).result(timeout=60)
        total = next(iter(count_result)).total or 0

        # Check last successful sync from processor_run_history
        # This is more accurate than MAX(created_at) which only shows new records
        sync_query = f"""
            SELECT MAX(run_end_at) as last_sync
            FROM `{PROJECT_ID}.nba_reference.processor_run_history`
            WHERE processor_name LIKE '%RosterRegistry%'
              AND status = 'success'
        """
        sync_result = bq_client.query(sync_query).result(timeout=60)
        sync_row = next(iter(sync_result))
        last_sync = sync_row.last_sync

        # Fallback to created_at if no run history exists
        if not last_sync:
            fallback_query = f"""
                SELECT MAX(created_at) as last_update
                FROM `{PROJECT_ID}.nba_reference.nba_players_registry`
            """
            fallback_result = bq_client.query(fallback_query).result(timeout=60)
            last_sync = next(iter(fallback_result)).last_update

        # Calculate staleness (handle timezone-aware datetimes)
        if last_sync:
            # Convert to naive datetime for comparison
            if hasattr(last_sync, 'tzinfo') and last_sync.tzinfo is not None:
                last_sync_naive = last_sync.replace(tzinfo=None)
            else:
                last_sync_naive = last_sync
            staleness = (datetime.now() - last_sync_naive).days
            is_current = staleness <= STALE_THRESHOLD_DAYS
        else:
            staleness = 999
            is_current = False

        return RegistryStatus(
            total_players=total,
            last_update=last_sync,
            is_current=is_current,
            staleness_days=staleness,
        )

    except Exception as e:
        logger.warning(f"Error checking registry status: {e}")
        return RegistryStatus()


def _count_unresolved_players(bq_client: bigquery.Client) -> int:
    """Count unresolved player names."""
    try:
        # Just count total - this table contains unresolved names
        query = f"""
            SELECT COUNT(*) as cnt
            FROM `{PROJECT_ID}.nba_reference.unresolved_player_names`
        """
        result = bq_client.query(query).result(timeout=60)
        row = next(iter(result))
        return row.cnt or 0

    except Exception as e:
        logger.warning(f"Error counting unresolved players: {e}")
        return 0


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == '__main__':
    """Quick test to verify maintenance validation works."""
    from shared.validation.time_awareness import get_time_context

    test_date = date.today()
    print(f"Testing maintenance validation for {test_date}...")

    time_context = get_time_context(test_date)
    print(f"Time context: is_today={time_context.is_today}, is_yesterday={time_context.is_yesterday}")

    result = validate_maintenance(test_date, time_context)

    if result is None:
        print("Maintenance validation skipped (not today/yesterday)")
    else:
        print(f"\nMaintenance Status: {'Current' if result.is_current else 'Stale'}")

        if result.roster_chain:
            print(f"\nRoster Chain: {result.roster_chain.status}")
            for sv in result.roster_chain.sources:
                print(f"  {sv.source.name}: {sv.bq_record_count} records ({sv.status})")

        if result.registry_status:
            print(f"\nRegistry:")
            print(f"  Total players: {result.registry_status.total_players}")
            print(f"  Last update: {result.registry_status.last_update}")
            print(f"  Staleness: {result.registry_status.staleness_days} days")
            print(f"  Current: {result.registry_status.is_current}")

        print(f"\nUnresolved players: {result.unresolved_players}")
