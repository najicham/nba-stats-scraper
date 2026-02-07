"""
Daily Scorecard System

Provides a single source of truth for "how did today go?"
Writes to BigQuery for historical tracking and querying.

Usage:
    # At end of each phase, record status
    from shared.utils.daily_scorecard import DailyScorecard

    scorecard = DailyScorecard(game_date='2026-01-24')
    scorecard.record_phase_completion('phase_2', 'bdl_box_scores', success=True, records=282)
    scorecard.record_phase_completion('phase_3', 'player_game_summary', success=True, records=282)

    # At end of day, compute overall health score
    scorecard.compute_daily_score()

Created: 2026-01-24
Part of: Pipeline Resilience Improvements
"""

import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
DATASET = 'nba_orchestration'
SCORECARD_TABLE = 'daily_scorecard'
PHASE_STATUS_TABLE = 'daily_phase_status_log'


class HealthStatus(Enum):
    HEALTHY = "healthy"           # 90%+ success
    DEGRADED = "degraded"         # 70-90% success
    UNHEALTHY = "unhealthy"       # 50-70% success
    CRITICAL = "critical"         # <50% success


@dataclass
class PhaseStatus:
    """Status of a single phase execution."""
    phase: str
    processor: str
    status: str  # success, failed, partial, skipped
    records_processed: int = 0
    records_expected: int = 0
    error_message: Optional[str] = None
    duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DailyScorecardRecord:
    """Daily summary record."""
    game_date: date

    # Phase completion counts
    phase_2_success: int = 0
    phase_2_failed: int = 0
    phase_3_success: int = 0
    phase_3_failed: int = 0
    phase_4_success: int = 0
    phase_4_failed: int = 0
    phase_5_success: int = 0
    phase_5_failed: int = 0

    # Data completeness
    expected_games: int = 0
    bdl_games: int = 0
    analytics_games: int = 0
    feature_quality_avg: float = 0.0
    predictions_made: int = 0
    predictions_graded: int = 0

    # Overall health
    health_score: float = 0.0  # 0-100
    health_status: str = "unknown"

    # Timing
    first_event_time: Optional[datetime] = None
    last_event_time: Optional[datetime] = None

    # Issues
    critical_errors: int = 0
    warnings: int = 0
    error_summary: str = ""

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DailyScorecard:
    """
    Tracks and persists daily pipeline health metrics.

    Provides a single place to understand:
    - Did all phases run?
    - Was data complete?
    - Were there errors?
    - What's the overall health score?
    """

    def __init__(self, game_date: Optional[date] = None, project_id: str = PROJECT_ID):
        self.game_date = game_date or date.today()
        self.project_id = project_id
        self.client = get_bigquery_client(project_id)
        self.phase_statuses: List[PhaseStatus] = []
        self._errors: List[str] = []
        self._warnings: List[str] = []

    def record_phase_completion(
        self,
        phase: str,
        processor: str,
        success: bool,
        records: int = 0,
        expected: int = 0,
        error: Optional[str] = None,
        duration: float = 0.0
    ):
        """Record completion of a phase/processor."""
        status = PhaseStatus(
            phase=phase,
            processor=processor,
            status="success" if success else "failed",
            records_processed=records,
            records_expected=expected,
            error_message=error,
            duration_seconds=duration
        )
        self.phase_statuses.append(status)

        if error:
            self._errors.append(f"{phase}/{processor}: {error}")

        # Log to phase_status table
        self._log_phase_status(status)

    def record_error(self, message: str, is_critical: bool = False):
        """Record an error."""
        if is_critical:
            self._errors.append(f"CRITICAL: {message}")
        else:
            self._warnings.append(message)

    def _log_phase_status(self, status: PhaseStatus):
        """Write phase status to BigQuery."""
        try:
            table_id = f"{self.project_id}.{DATASET}.{PHASE_STATUS_TABLE}"
            rows = [{
                'game_date': self.game_date.isoformat(),
                'phase': status.phase,
                'processor': status.processor,
                'status': status.status,
                'records_processed': status.records_processed,
                'records_expected': status.records_expected,
                'error_message': status.error_message,
                'duration_seconds': status.duration_seconds,
                'timestamp': status.timestamp.isoformat()
            }]

            # Use batch loading to avoid streaming buffer issues
            from shared.utils.bigquery_utils import insert_bigquery_rows
            success = insert_bigquery_rows(table_id, rows)
            if not success:
                logger.warning(f"Failed to log phase status")
        except Exception as e:
            logger.warning(f"Error logging phase status: {e}")

    def compute_daily_score(self) -> DailyScorecardRecord:
        """
        Compute overall daily health score and persist to BigQuery.

        Health score formula:
        - 40% Phase completion rate
        - 30% Data completeness
        - 20% Feature quality
        - 10% Error rate
        """
        record = DailyScorecardRecord(game_date=self.game_date)

        # Get data completeness from BigQuery
        completeness = self._query_data_completeness()
        record.expected_games = completeness.get('expected_games', 0)
        record.bdl_games = completeness.get('bdl_games', 0)
        record.analytics_games = completeness.get('analytics_games', 0)
        record.feature_quality_avg = completeness.get('feature_quality', 0.0)
        record.predictions_made = completeness.get('predictions_made', 0)
        record.predictions_graded = completeness.get('predictions_graded', 0)

        # Count phase completions from scraper_execution_log
        phase_counts = self._query_phase_counts()
        record.phase_2_success = phase_counts.get('phase_2_success', 0)
        record.phase_2_failed = phase_counts.get('phase_2_failed', 0)
        record.phase_3_success = phase_counts.get('phase_3_success', 0)
        record.phase_3_failed = phase_counts.get('phase_3_failed', 0)
        record.phase_4_success = phase_counts.get('phase_4_success', 0)
        record.phase_4_failed = phase_counts.get('phase_4_failed', 0)
        record.phase_5_success = phase_counts.get('phase_5_success', 0)
        record.phase_5_failed = phase_counts.get('phase_5_failed', 0)

        # Calculate health score
        phase_success_rate = self._calc_phase_success_rate(phase_counts)
        data_completeness_rate = self._calc_data_completeness_rate(completeness)
        feature_quality_score = min(record.feature_quality_avg / 100.0, 1.0) if record.feature_quality_avg else 0.5
        error_penalty = min(len(self._errors) * 5, 30) / 100.0  # Max 30% penalty

        record.health_score = (
            phase_success_rate * 40 +
            data_completeness_rate * 30 +
            feature_quality_score * 20 +
            (1 - error_penalty) * 10
        )

        # Determine status
        if record.health_score >= 90:
            record.health_status = HealthStatus.HEALTHY.value
        elif record.health_score >= 70:
            record.health_status = HealthStatus.DEGRADED.value
        elif record.health_score >= 50:
            record.health_status = HealthStatus.UNHEALTHY.value
        else:
            record.health_status = HealthStatus.CRITICAL.value

        record.critical_errors = len(self._errors)
        record.warnings = len(self._warnings)
        record.error_summary = "; ".join(self._errors[:5])  # First 5 errors

        # Persist to BigQuery
        self._persist_scorecard(record)

        return record

    def _query_data_completeness(self) -> Dict[str, Any]:
        """Query data completeness for the game date."""
        try:
            query = f"""
            WITH schedule AS (
                SELECT COUNT(DISTINCT game_id) as expected
                FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
                WHERE game_status = 3 AND game_date = @game_date
            ),
            bdl AS (
                SELECT COUNT(DISTINCT game_id) as actual
                FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
                WHERE game_date = @game_date
            ),
            analytics AS (
                SELECT COUNT(DISTINCT game_id) as actual
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date = @game_date
            ),
            features AS (
                SELECT AVG(feature_quality_score) as avg_quality
                FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
                WHERE game_date = @game_date
            ),
            predictions AS (
                SELECT
                    COUNT(*) as made,
                    0 as graded  -- Would need join to prediction_accuracy
                FROM `{self.project_id}.nba_predictions.player_prop_predictions`
                WHERE game_date = @game_date AND system_id = 'catboost_v8'
            )
            SELECT
                s.expected as expected_games,
                b.actual as bdl_games,
                a.actual as analytics_games,
                f.avg_quality as feature_quality,
                p.made as predictions_made,
                p.graded as predictions_graded
            FROM schedule s, bdl b, analytics a, features f, predictions p
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", self.game_date),
                ]
            )

            result = list(self.client.query(query, job_config=job_config).result())
            if result:
                row = result[0]
                return {
                    'expected_games': row.expected_games or 0,
                    'bdl_games': row.bdl_games or 0,
                    'analytics_games': row.analytics_games or 0,
                    'feature_quality': row.feature_quality or 0,
                    'predictions_made': row.predictions_made or 0,
                    'predictions_graded': row.predictions_graded or 0
                }
        except Exception as e:
            logger.error(f"Error querying data completeness: {e}")

        return {}

    def _query_phase_counts(self) -> Dict[str, int]:
        """Query phase success/failure counts from execution logs."""
        try:
            query = f"""
            SELECT
                CASE
                    WHEN scraper_name LIKE '%bdl%' OR scraper_name LIKE '%nbac%' THEN 'phase_2'
                    WHEN scraper_name LIKE '%analytics%' OR scraper_name LIKE '%summary%' THEN 'phase_3'
                    WHEN scraper_name LIKE '%feature%' OR scraper_name LIKE '%precompute%' THEN 'phase_4'
                    WHEN scraper_name LIKE '%prediction%' OR scraper_name LIKE '%grading%' THEN 'phase_5'
                    ELSE 'other'
                END as phase,
                status,
                COUNT(*) as count
            FROM `{self.project_id}.nba_orchestration.scraper_execution_log`
            WHERE DATE(triggered_at) = @game_date
            GROUP BY 1, 2
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", self.game_date),
                ]
            )

            result = {}
            for row in self.client.query(query, job_config=job_config).result():
                key = f"{row.phase}_{'success' if row.status == 'success' else 'failed'}"
                result[key] = result.get(key, 0) + row.count

            return result
        except Exception as e:
            logger.error(f"Error querying phase counts: {e}")

        return {}

    def _calc_phase_success_rate(self, counts: Dict[str, int]) -> float:
        """Calculate overall phase success rate."""
        total_success = sum(v for k, v in counts.items() if 'success' in k)
        total_failed = sum(v for k, v in counts.items() if 'failed' in k)
        total = total_success + total_failed
        return total_success / total if total > 0 else 0.5

    def _calc_data_completeness_rate(self, completeness: Dict[str, Any]) -> float:
        """Calculate data completeness rate."""
        expected = completeness.get('expected_games', 0)
        if expected == 0:
            return 1.0  # No games expected

        bdl_rate = completeness.get('bdl_games', 0) / expected
        analytics_rate = completeness.get('analytics_games', 0) / expected

        return (bdl_rate + analytics_rate) / 2

    def _persist_scorecard(self, record: DailyScorecardRecord):
        """Write scorecard to BigQuery."""
        try:
            table_id = f"{self.project_id}.{DATASET}.{SCORECARD_TABLE}"

            # Convert to dict, handling date/datetime serialization
            row = {
                'game_date': record.game_date.isoformat(),
                'phase_2_success': record.phase_2_success,
                'phase_2_failed': record.phase_2_failed,
                'phase_3_success': record.phase_3_success,
                'phase_3_failed': record.phase_3_failed,
                'phase_4_success': record.phase_4_success,
                'phase_4_failed': record.phase_4_failed,
                'phase_5_success': record.phase_5_success,
                'phase_5_failed': record.phase_5_failed,
                'expected_games': record.expected_games,
                'bdl_games': record.bdl_games,
                'analytics_games': record.analytics_games,
                'feature_quality_avg': record.feature_quality_avg,
                'predictions_made': record.predictions_made,
                'predictions_graded': record.predictions_graded,
                'health_score': record.health_score,
                'health_status': record.health_status,
                'critical_errors': record.critical_errors,
                'warnings': record.warnings,
                'error_summary': record.error_summary[:1000],  # Truncate
                'created_at': record.created_at.isoformat()
            }

            # Use batch loading to avoid streaming buffer issues
            from shared.utils.bigquery_utils import insert_bigquery_rows
            success = insert_bigquery_rows(table_id, [row])
            if not success:
                logger.error(f"Failed to persist scorecard")
            else:
                logger.info(f"Scorecard persisted for {record.game_date}: score={record.health_score:.1f}, status={record.health_status}")

        except Exception as e:
            logger.error(f"Error persisting scorecard: {e}")


def get_daily_scorecard_summary(days: int = 7) -> List[Dict[str, Any]]:
    """
    Get scorecard summary for recent days.

    Useful for dashboards and quick health checks.
    """
    client = get_bigquery_client(PROJECT_ID)

    query = f"""
    SELECT
        game_date,
        health_score,
        health_status,
        expected_games,
        bdl_games,
        analytics_games,
        predictions_made,
        critical_errors,
        error_summary
    FROM `{PROJECT_ID}.{DATASET}.{SCORECARD_TABLE}`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
    ORDER BY game_date DESC
    """

    result = []
    for row in client.query(query).result():
        result.append(dict(row))

    return result
