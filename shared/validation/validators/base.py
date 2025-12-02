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
        result = client.query(query, job_config=job_config).result()
        row = next(iter(result))
        return row.cnt
    except Exception as e:
        logger.error(f"Error querying {dataset}.{table}: {e}")
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
        result = client.query(query, job_config=job_config).result()
        row = next(iter(result))
        return row.cnt
    except Exception as e:
        logger.error(f"Error querying player count in {dataset}.{table}: {e}")
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
        result = client.query(query, job_config=job_config).result()
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
        result = client.query(query, job_config=job_config).result()
        return {row[0] for row in result}
    except Exception as e:
        logger.error(f"Error querying players in {dataset}.{table}: {e}")
        return set()
