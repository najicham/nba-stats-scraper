"""
Phase 2 Quality Gate (Session 135 - Resilience Layer 3)
========================================================

Validates raw data quality before triggering Phase 3 analytics processing.
Prevents bad data from propagating through the pipeline.

Usage:
    gate = Phase2QualityGate(bq_client, project_id)

    result = gate.check_raw_data_quality(
        game_date=date(2026, 2, 5),
        table='nba_raw.nbac_gamebook_player_stats'
    )

    if result.status == GateStatus.FAIL:
        raise ProcessingBlockedError(result.message)

    # Proceed with Phase 3 processing

Thresholds:
- MIN_PLAYER_RECORDS_PER_GAME: 20 (expect 20+ players per game)
- MAX_NULL_RATE: 0.05 (5% max NULL rate for critical fields on active players)
- MAX_HOURS_SINCE_SCRAPE: 24 (data must be fresh, if timestamp available)

Note: NULL checks for stats (points, minutes) only apply to active players.
      DNP/inactive players are expected to have NULL stats.

Created: 2026-02-05
"""

import logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from google.cloud import bigquery
from shared.validation.processing_gate import GateStatus, GateResult

logger = logging.getLogger(__name__)


@dataclass
class RawDataMetrics:
    """Metrics from raw data quality check."""
    game_count: int
    player_records: int
    null_player_names: int
    null_team_abbr: int
    null_points: int
    null_minutes: int
    has_processed_at: bool  # Whether timestamp field is available
    avg_scrape_age_hours: Optional[float]
    max_scrape_age_hours: Optional[float]


class Phase2QualityGate:
    """
    Quality gate for Phase 2 → Phase 3 transition.

    Validates raw game data before analytics processing:
    - Game coverage (min 2 games if games scheduled)
    - Player record count (min 20 per game)
    - NULL rates for critical fields
    - Data freshness

    Gate Status Logic:
    - All checks pass: PROCEED
    - Minor issues (1-2 NULLs, slightly stale data): PROCEED_WITH_WARNING
    - Critical issues (high NULL rate, missing games, very stale data): FAIL
    """

    # Thresholds
    MIN_PLAYER_RECORDS_PER_GAME = 20
    MAX_NULL_RATE = 0.05  # 5%
    MAX_HOURS_SINCE_SCRAPE = 24  # 1 day
    WARNING_HOURS_SINCE_SCRAPE = 12  # 12 hours

    # Critical fields that must not be NULL
    CRITICAL_FIELDS = [
        'player_name',
        'team_abbr',
        'game_id',
        'points',
        'minutes_decimal'
    ]

    def __init__(
        self,
        bq_client: bigquery.Client,
        project_id: str
    ):
        """
        Initialize Phase 2 quality gate.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id

    def check_raw_data_quality(
        self,
        game_date: date,
        table: str = 'nba_raw.nbac_gamebook_player_stats'
    ) -> GateResult:
        """
        Check raw data quality for a game date.

        Args:
            game_date: Game date to check
            table: Raw data table to validate

        Returns:
            GateResult with status and quality metrics
        """
        logger.info(f"Phase 2 quality gate check for {game_date}")

        try:
            # Get scheduled games for this date
            scheduled_games = self._get_scheduled_game_count(game_date)

            # Get raw data metrics
            metrics = self._get_raw_data_metrics(game_date, table)

            # Check if any games scheduled
            if scheduled_games == 0:
                logger.info(f"No games scheduled for {game_date}")
                return GateResult(
                    status=GateStatus.PROCEED,
                    can_proceed=True,
                    quality_score=1.0,
                    message="No games scheduled for this date",
                    completeness_pct=100.0,
                    expected_count=0,
                    actual_count=0,
                    quality_metadata={
                        'gate_status': 'no_games_scheduled',
                        'gate_timestamp': datetime.utcnow().isoformat()
                    }
                )

            # Validate metrics
            status, quality_score, quality_issues = self._validate_metrics(
                metrics, scheduled_games
            )

            # Build message
            message = self._build_message(status, metrics, scheduled_games, quality_issues)

            # Build quality metadata
            quality_metadata = {
                'gate_status': status.value,
                'gate_timestamp': datetime.utcnow().isoformat(),
                'gate_processor': 'Phase2QualityGate',
                'quality_score': quality_score,
                'game_count': metrics.game_count,
                'scheduled_games': scheduled_games,
                'player_records': metrics.player_records,
                'avg_scrape_age_hours': metrics.avg_scrape_age_hours
            }

            logger.info(
                f"Gate decision: {status.value} - {message} "
                f"(games={metrics.game_count}/{scheduled_games}, "
                f"players={metrics.player_records}, "
                f"quality={quality_score:.2f})"
            )

            return GateResult(
                status=status,
                can_proceed=status in (GateStatus.PROCEED, GateStatus.PROCEED_WITH_WARNING),
                quality_score=quality_score,
                message=message,
                completeness_pct=(metrics.game_count / scheduled_games * 100) if scheduled_games > 0 else 0,
                expected_count=scheduled_games,
                actual_count=metrics.game_count,
                quality_issues=quality_issues,
                quality_metadata=quality_metadata
            )

        except Exception as e:
            logger.error(f"Phase 2 quality gate check failed: {e}", exc_info=True)
            return GateResult(
                status=GateStatus.FAIL,
                can_proceed=False,
                quality_score=0.0,
                message=f"Quality gate check error: {str(e)}",
                completeness_pct=0.0,
                expected_count=0,
                actual_count=0,
                quality_issues=[f"check_error: {str(e)}"],
                quality_metadata={
                    'gate_status': 'error',
                    'error_type': type(e).__name__,
                    'gate_timestamp': datetime.utcnow().isoformat()
                }
            )

    def _get_scheduled_game_count(self, game_date: date) -> int:
        """
        Get number of scheduled games for a date.

        Args:
            game_date: Game date

        Returns:
            Number of games scheduled
        """
        query = f"""
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM `{self.project_id}.nba_reference.nba_schedule`
        WHERE game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        result = list(self.bq_client.query(query, job_config=job_config).result())

        if not result:
            return 0

        return result[0]['game_count'] or 0

    def _get_raw_data_metrics(self, game_date: date, table: str) -> RawDataMetrics:
        """
        Get raw data metrics for a game date.

        Args:
            game_date: Game date
            table: Raw data table

        Returns:
            RawDataMetrics
        """
        query = f"""
        SELECT
            COUNT(DISTINCT game_id) as game_count,
            COUNT(*) as player_records,
            COUNTIF(player_name IS NULL) as null_player_names,
            COUNTIF(team_abbr IS NULL) as null_team_abbr,
            -- Only check stats for active players (DNP/inactive expected to have NULL stats)
            COUNTIF(player_status = 'active' AND points IS NULL) as null_points,
            COUNTIF(player_status = 'active' AND minutes_decimal IS NULL) as null_minutes,
            COUNTIF(processed_at IS NOT NULL) as has_processed_at_count,
            AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), processed_at, HOUR)) as avg_scrape_age_hours,
            MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), processed_at, HOUR)) as max_scrape_age_hours
        FROM `{self.project_id}.{table}`
        WHERE game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        result = list(self.bq_client.query(query, job_config=job_config).result())

        if not result:
            return RawDataMetrics(
                game_count=0,
                player_records=0,
                null_player_names=0,
                null_team_abbr=0,
                null_points=0,
                null_minutes=0,
                has_processed_at=False,
                avg_scrape_age_hours=None,
                max_scrape_age_hours=None
            )

        row = result[0]
        player_records = row['player_records'] or 0
        has_processed_at_count = row['has_processed_at_count'] or 0
        has_processed_at = has_processed_at_count > 0

        return RawDataMetrics(
            game_count=row['game_count'] or 0,
            player_records=player_records,
            null_player_names=row['null_player_names'] or 0,
            null_team_abbr=row['null_team_abbr'] or 0,
            null_points=row['null_points'] or 0,
            null_minutes=row['null_minutes'] or 0,
            has_processed_at=has_processed_at,
            avg_scrape_age_hours=float(row['avg_scrape_age_hours']) if row['avg_scrape_age_hours'] is not None else None,
            max_scrape_age_hours=float(row['max_scrape_age_hours']) if row['max_scrape_age_hours'] is not None else None
        )

    def _validate_metrics(
        self,
        metrics: RawDataMetrics,
        scheduled_games: int
    ) -> tuple[GateStatus, float, list[str]]:
        """
        Validate raw data metrics against thresholds.

        Args:
            metrics: Raw data metrics
            scheduled_games: Number of scheduled games

        Returns:
            Tuple of (GateStatus, quality_score, quality_issues)
        """
        quality_issues = []
        quality_score = 1.0

        # Check game coverage
        if metrics.game_count < scheduled_games:
            quality_issues.append(
                f"Missing games: {metrics.game_count}/{scheduled_games}"
            )
            quality_score -= 0.3

        # Check player record count
        expected_player_records = scheduled_games * self.MIN_PLAYER_RECORDS_PER_GAME
        if metrics.player_records < expected_player_records:
            quality_issues.append(
                f"Low player record count: {metrics.player_records} (expected ≥{expected_player_records})"
            )
            quality_score -= 0.2

        # Check NULL rates
        if metrics.player_records > 0:
            null_rate_player_names = metrics.null_player_names / metrics.player_records
            null_rate_team_abbr = metrics.null_team_abbr / metrics.player_records
            null_rate_points = metrics.null_points / metrics.player_records
            null_rate_minutes = metrics.null_minutes / metrics.player_records

            if null_rate_player_names > self.MAX_NULL_RATE:
                quality_issues.append(
                    f"High NULL rate for player_name: {null_rate_player_names:.1%}"
                )
                quality_score -= 0.3

            if null_rate_team_abbr > self.MAX_NULL_RATE:
                quality_issues.append(
                    f"High NULL rate for team_abbr: {null_rate_team_abbr:.1%}"
                )
                quality_score -= 0.2

            if null_rate_points > self.MAX_NULL_RATE:
                quality_issues.append(
                    f"High NULL rate for points: {null_rate_points:.1%}"
                )
                quality_score -= 0.2

            if null_rate_minutes > self.MAX_NULL_RATE:
                quality_issues.append(
                    f"High NULL rate for minutes_decimal: {null_rate_minutes:.1%}"
                )
                quality_score -= 0.2

        # Check data freshness (only if processed_at timestamp is available)
        if metrics.has_processed_at and metrics.max_scrape_age_hours is not None:
            if metrics.max_scrape_age_hours > self.MAX_HOURS_SINCE_SCRAPE:
                quality_issues.append(
                    f"Stale data: {metrics.max_scrape_age_hours:.1f} hours old (max {self.MAX_HOURS_SINCE_SCRAPE})"
                )
                quality_score -= 0.2
            elif metrics.avg_scrape_age_hours is not None and metrics.avg_scrape_age_hours > self.WARNING_HOURS_SINCE_SCRAPE:
                quality_issues.append(
                    f"Data moderately stale: avg {metrics.avg_scrape_age_hours:.1f} hours"
                )
                quality_score -= 0.1

        # Clamp quality score
        quality_score = max(0.0, quality_score)

        # Determine status
        if quality_score >= 1.0:
            status = GateStatus.PROCEED
        elif quality_score >= 0.7:
            status = GateStatus.PROCEED_WITH_WARNING
        else:
            status = GateStatus.FAIL

        return status, quality_score, quality_issues

    def _build_message(
        self,
        status: GateStatus,
        metrics: RawDataMetrics,
        scheduled_games: int,
        quality_issues: list[str]
    ) -> str:
        """
        Build gate result message.

        Args:
            status: Gate status
            metrics: Raw data metrics
            scheduled_games: Number of scheduled games
            quality_issues: List of quality issues

        Returns:
            Message string
        """
        if status == GateStatus.PROCEED:
            return (
                f"Raw data quality passed "
                f"({metrics.game_count} games, {metrics.player_records} players)"
            )
        elif status == GateStatus.PROCEED_WITH_WARNING:
            issues_str = "; ".join(quality_issues[:2])  # First 2 issues
            return (
                f"Proceeding with warnings: {issues_str} "
                f"({metrics.game_count}/{scheduled_games} games)"
            )
        else:  # FAIL
            issues_str = "; ".join(quality_issues)
            return (
                f"Raw data quality insufficient: {issues_str} "
                f"({metrics.game_count}/{scheduled_games} games)"
            )
