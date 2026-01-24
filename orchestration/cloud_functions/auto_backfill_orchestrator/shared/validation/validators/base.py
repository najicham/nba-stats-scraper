"""
Base Validator Classes

Common classes and utilities for phase validators.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Set, Optional, Any
from enum import Enum
import logging

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID, QUALITY_TIERS

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """Status of a validation check."""
    COMPLETE = 'complete'           # All expected data present
    PARTIAL = 'partial'             # Some data present, some missing
    MISSING = 'missing'             # No data found
    BOOTSTRAP_SKIP = 'bootstrap_skip'  # Expected to be empty (bootstrap period)
    NOT_APPLICABLE = 'not_applicable'  # Not relevant for this date
    ERROR = 'error'                 # Error during validation


@dataclass
class QualityDistribution:
    """Distribution of quality tiers."""
    gold: int = 0
    silver: int = 0
    bronze: int = 0
    poor: int = 0
    unusable: int = 0
    total: int = 0

    def __post_init__(self):
        self.total = self.gold + self.silver + self.bronze + self.poor + self.unusable

    def to_summary_string(self) -> str:
        """Format as compact string like '48G 15S 4B 0P 0U'."""
        return f"{self.gold}G {self.silver}S {self.bronze}B {self.poor}P {self.unusable}U"

    def production_ready_count(self) -> int:
        """Count of production-ready records (gold + silver + bronze)."""
        return self.gold + self.silver + self.bronze

    def has_issues(self) -> bool:
        """Check if there are poor or unusable records."""
        return self.poor > 0 or self.unusable > 0


@dataclass
class RunHistoryInfo:
    """Information about a processor run."""
    processor_name: str
    status: str
    run_id: Optional[str] = None
    started_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    records_processed: int = 0
    records_created: int = 0
    alert_sent: bool = False
    alert_type: Optional[str] = None
    errors: List[Dict] = field(default_factory=list)
    dependency_check_passed: Optional[bool] = None


@dataclass
class TableValidation:
    """Validation result for a single table."""
    table_name: str
    dataset: str
    status: ValidationStatus
    record_count: int = 0
    expected_count: int = 0
    completeness_pct: float = 0.0

    # For player-based tables
    player_count: int = 0
    expected_players: int = 0
    missing_players: List[str] = field(default_factory=list)

    # For game-based tables
    game_count: int = 0
    expected_games: int = 0

    # Quality
    quality: Optional[QualityDistribution] = None

    # Run history
    run_history: Optional[RunHistoryInfo] = None

    # Issues
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Extra metadata (e.g., has_prop_line breakdown)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate completeness percentage."""
        if self.expected_count > 0:
            self.completeness_pct = (self.record_count / self.expected_count) * 100
        elif self.expected_players > 0:
            self.completeness_pct = (self.player_count / self.expected_players) * 100


@dataclass
class PhaseValidationResult:
    """Complete validation result for a phase."""
    phase: int
    status: ValidationStatus
    tables: Dict[str, TableValidation] = field(default_factory=dict)

    # Aggregated metrics
    total_tables: int = 0
    complete_tables: int = 0
    total_records: int = 0

    # Quality summary
    quality_summary: Optional[QualityDistribution] = None

    # Issues and warnings
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Run history
    processors_ran: int = 0
    processors_failed: int = 0

    # Timing
    validation_duration_ms: float = 0

    def __post_init__(self):
        """Calculate aggregated metrics."""
        self._update_aggregates()

    def _update_aggregates(self):
        """Update aggregate fields from tables."""
        self.total_tables = len(self.tables)
        self.complete_tables = sum(
            1 for t in self.tables.values()
            if t.status == ValidationStatus.COMPLETE
        )
        self.total_records = sum(t.record_count for t in self.tables.values())

        # Aggregate quality
        if any(t.quality for t in self.tables.values()):
            self.quality_summary = QualityDistribution()
            for t in self.tables.values():
                if t.quality:
                    self.quality_summary.gold += t.quality.gold
                    self.quality_summary.silver += t.quality.silver
                    self.quality_summary.bronze += t.quality.bronze
                    self.quality_summary.poor += t.quality.poor
                    self.quality_summary.unusable += t.quality.unusable
            self.quality_summary.total = (
                self.quality_summary.gold + self.quality_summary.silver +
                self.quality_summary.bronze + self.quality_summary.poor +
                self.quality_summary.unusable
            )

        # Collect all issues and warnings
        for t in self.tables.values():
            self.issues.extend(t.issues)
            self.warnings.extend(t.warnings)


def query_table_count(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date
) -> int:
    """Query record count for a table on a specific date."""
    query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        row = next(iter(result))
        return row.cnt
    except Exception as e:
        logger.error(f"Error querying {dataset}.{table}: {e}", exc_info=True)
        return 0


def query_player_count(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
    player_column: str = 'player_lookup'
) -> int:
    """Query distinct player count for a table on a specific date."""
    query = f"""
    SELECT COUNT(DISTINCT {player_column}) as cnt
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        row = next(iter(result))
        return row.cnt
    except Exception as e:
        logger.error(f"Error querying player count in {dataset}.{table}: {e}", exc_info=True)
        return 0


def query_quality_distribution(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
    quality_column: str = 'quality_tier'
) -> QualityDistribution:
    """Query quality tier distribution for a table."""
    query = f"""
    SELECT
        COALESCE({quality_column}, 'unknown') as tier,
        COUNT(*) as cnt
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
    GROUP BY tier
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    distribution = QualityDistribution()

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        for row in result:
            tier = row.tier.lower() if row.tier else 'unknown'
            if tier == 'gold':
                distribution.gold = row.cnt
            elif tier == 'silver':
                distribution.silver = row.cnt
            elif tier == 'bronze':
                distribution.bronze = row.cnt
            elif tier == 'poor':
                distribution.poor = row.cnt
            elif tier == 'unusable':
                distribution.unusable = row.cnt

        distribution.total = (
            distribution.gold + distribution.silver + distribution.bronze +
            distribution.poor + distribution.unusable
        )

    except Exception as e:
        logger.debug(f"Quality column may not exist in {dataset}.{table}: {e}")

    return distribution


def query_actual_players(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
    player_column: str = 'player_lookup'
) -> Set[str]:
    """Get set of actual players in a table for a date."""
    query = f"""
    SELECT DISTINCT {player_column}
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
      AND {player_column} IS NOT NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        return {row[0] for row in result}
    except Exception as e:
        logger.error(f"Error querying players in {dataset}.{table}: {e}", exc_info=True)
        return set()


# =============================================================================
# DATA INTEGRITY CHECKS (Added 2025-12-02)
# =============================================================================

@dataclass
class DataIntegrityResult:
    """Result of data integrity checks for a table."""
    duplicate_count: int = 0
    null_player_lookup_count: int = 0
    null_critical_fields: Dict[str, int] = field(default_factory=dict)
    has_issues: bool = False
    issues: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Determine if there are integrity issues."""
        self.has_issues = (
            self.duplicate_count > 0 or
            self.null_player_lookup_count > 0 or
            any(v > 0 for v in self.null_critical_fields.values())
        )
        self._build_issues()

    def _build_issues(self):
        """Build human-readable issue list."""
        if self.duplicate_count > 0:
            self.issues.append(f"{self.duplicate_count} duplicate records detected")
        if self.null_player_lookup_count > 0:
            self.issues.append(f"{self.null_player_lookup_count} records with NULL player_lookup")
        for field_name, count in self.null_critical_fields.items():
            if count > 0:
                self.issues.append(f"{count} records with NULL {field_name}")


def query_duplicate_count(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
    unique_keys: List[str] = None,
) -> int:
    """
    Count duplicate records in a table based on unique keys.

    Args:
        client: BigQuery client
        dataset: Dataset name
        table: Table name
        date_column: Date column for filtering
        game_date: Date to check
        unique_keys: List of columns that should be unique together.
                     Defaults to ['player_lookup', date_column] for player tables.

    Returns:
        Number of duplicate records (total - distinct)
    """
    if unique_keys is None:
        unique_keys = ['player_lookup', date_column]

    keys_str = ', '.join(unique_keys)

    query = f"""
    SELECT
        COUNT(*) as total_count,
        COUNT(DISTINCT CONCAT({', '.join(f'CAST({k} AS STRING)' for k in unique_keys)})) as distinct_count
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        row = next(iter(result))
        duplicate_count = row.total_count - row.distinct_count
        if duplicate_count > 0:
            logger.warning(
                f"Found {duplicate_count} duplicates in {dataset}.{table} "
                f"for {game_date} (unique keys: {keys_str})"
            )
        return duplicate_count
    except Exception as e:
        logger.debug(f"Could not check duplicates in {dataset}.{table}: {e}")
        return 0


def query_null_critical_fields(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
    critical_fields: List[str],
) -> Dict[str, int]:
    """
    Count records with NULL values in critical fields.

    Args:
        client: BigQuery client
        dataset: Dataset name
        table: Table name
        date_column: Date column for filtering
        game_date: Date to check
        critical_fields: List of field names that should not be NULL

    Returns:
        Dict mapping field_name -> count of NULL records
    """
    # Build COUNTIF expressions for each field
    countif_exprs = ', '.join(
        f"COUNTIF({field} IS NULL) as null_{field}"
        for field in critical_fields
    )

    query = f"""
    SELECT {countif_exprs}
    FROM `{PROJECT_ID}.{dataset}.{table}`
    WHERE {date_column} = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    result_dict = {field: 0 for field in critical_fields}

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        row = next(iter(result))
        for field in critical_fields:
            null_count = getattr(row, f'null_{field}', 0) or 0
            result_dict[field] = null_count
            if null_count > 0:
                logger.warning(
                    f"Found {null_count} NULL {field} values in {dataset}.{table} for {game_date}"
                )
    except Exception as e:
        logger.debug(f"Could not check NULL fields in {dataset}.{table}: {e}")

    return result_dict


def check_data_integrity(
    client: bigquery.Client,
    dataset: str,
    table: str,
    date_column: str,
    game_date: date,
    unique_keys: List[str] = None,
    critical_fields: List[str] = None,
) -> DataIntegrityResult:
    """
    Run comprehensive data integrity checks on a table.

    Args:
        client: BigQuery client
        dataset: Dataset name
        table: Table name
        date_column: Date column for filtering
        game_date: Date to check
        unique_keys: Columns that should be unique together
        critical_fields: Fields that should not be NULL

    Returns:
        DataIntegrityResult with all check results
    """
    # Check duplicates
    duplicate_count = query_duplicate_count(
        client, dataset, table, date_column, game_date, unique_keys
    )

    # Check NULL player_lookup
    null_player = 0
    if 'player_lookup' not in (critical_fields or []):
        null_result = query_null_critical_fields(
            client, dataset, table, date_column, game_date, ['player_lookup']
        )
        null_player = null_result.get('player_lookup', 0)

    # Check critical fields
    null_critical = {}
    if critical_fields:
        null_critical = query_null_critical_fields(
            client, dataset, table, date_column, game_date, critical_fields
        )

    return DataIntegrityResult(
        duplicate_count=duplicate_count,
        null_player_lookup_count=null_player,
        null_critical_fields=null_critical,
    )


def check_cross_table_consistency(
    client: bigquery.Client,
    game_date: date,
    source_dataset: str,
    source_table: str,
    source_date_column: str,
    target_dataset: str,
    target_table: str,
    target_date_column: str,
    player_column: str = 'player_lookup',
) -> Dict[str, Any]:
    """
    Check player consistency between two tables.

    Args:
        client: BigQuery client
        game_date: Date to check
        source_*: Source table info (e.g., Phase 3)
        target_*: Target table info (e.g., Phase 4)
        player_column: Column containing player identifiers

    Returns:
        Dict with consistency metrics:
        - source_players: count in source
        - target_players: count in target
        - missing_in_target: players in source but not target
        - extra_in_target: players in target but not source
        - is_consistent: True if sets match
    """
    # Get player sets from both tables
    source_players = query_actual_players(
        client, source_dataset, source_table, source_date_column, game_date, player_column
    )
    target_players = query_actual_players(
        client, target_dataset, target_table, target_date_column, game_date, player_column
    )

    missing_in_target = source_players - target_players
    extra_in_target = target_players - source_players

    result = {
        'source_players': len(source_players),
        'target_players': len(target_players),
        'missing_in_target': list(missing_in_target)[:10],  # Limit to 10 for display
        'missing_count': len(missing_in_target),
        'extra_in_target': list(extra_in_target)[:10],
        'extra_count': len(extra_in_target),
        'is_consistent': len(missing_in_target) == 0 and len(extra_in_target) == 0,
    }

    if not result['is_consistent']:
        logger.warning(
            f"Player mismatch between {source_table} and {target_table} for {game_date}: "
            f"{len(missing_in_target)} missing, {len(extra_in_target)} extra"
        )

    return result
