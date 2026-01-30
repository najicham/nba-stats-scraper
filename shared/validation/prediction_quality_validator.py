"""
Prediction Quality Validator

Validates prediction grading integrity and data quality.
Detects issues like:
- DNP (actual_points=0) predictions that should be voided
- Placeholder lines (line_value=20.0) that shouldn't be graded
- Stale cache data affecting predictions
- Cross-phase player consistency issues

This validator was created to catch grading issues that corrupt accuracy metrics.

Usage:
    # CLI validation
    python -m shared.validation.prediction_quality_validator --days 7

    # In code
    from shared.validation.prediction_quality_validator import (
        validate_prediction_quality,
        check_dnp_voiding,
        check_placeholder_lines,
        check_stale_cache,
        check_player_consistency,
    )

    result = validate_prediction_quality(client, start_date, end_date)
    if not result.passed:
        print(result.summary)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import logging
import argparse

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID, BQ_QUERY_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

PREDICTION_ACCURACY_TABLE = "nba_predictions.prediction_accuracy"
PREDICTIONS_TABLE = "nba_predictions.player_prop_predictions"
CACHE_TABLE = "nba_precompute.player_daily_cache"
PLAYER_GAME_SUMMARY_TABLE = "nba_analytics.player_game_summary"

# Thresholds
DNP_GRADED_THRESHOLD = 0  # Any DNP predictions graded is bad
PLACEHOLDER_LINE_VALUE = 20.0  # Known placeholder value
STALE_CACHE_HOURS = 6  # Cache older than this is stale
PLAYER_MISMATCH_THRESHOLD = 5.0  # Max % of player mismatches allowed


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================

class CheckStatus(Enum):
    """Status of a validation check."""
    PASS = 'pass'
    WARN = 'warn'
    FAIL = 'fail'
    ERROR = 'error'


@dataclass
class DNPVoidingResult:
    """Result of DNP voiding check."""
    total_dnp: int = 0
    dnp_voided: int = 0
    dnp_graded: int = 0
    dnp_graded_as_correct: int = 0
    dnp_graded_as_incorrect: int = 0
    status: CheckStatus = CheckStatus.PASS
    sample_issues: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class PlaceholderLineResult:
    """Result of placeholder line check."""
    total_placeholders: int = 0
    placeholders_graded: int = 0
    status: CheckStatus = CheckStatus.PASS
    sample_issues: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class StaleCacheResult:
    """Result of stale cache check."""
    total_records: int = 0
    stale_records: int = 0
    stale_pct: float = 0.0
    oldest_cache_hours: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    stale_dates: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class PlayerConsistencyResult:
    """Result of cross-phase player consistency check."""
    total_players_checked: int = 0
    players_in_predictions: int = 0
    players_in_analytics: int = 0
    players_missing_in_analytics: int = 0
    players_missing_in_predictions: int = 0
    mismatch_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    sample_mismatches: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class PredictionQualityResult:
    """Complete prediction quality validation result."""
    start_date: date
    end_date: date
    passed: bool = True
    dnp_voiding: Optional[DNPVoidingResult] = None
    placeholder_lines: Optional[PlaceholderLineResult] = None
    stale_cache: Optional[StaleCacheResult] = None
    player_consistency: Optional[PlayerConsistencyResult] = None
    validation_time_seconds: float = 0.0
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Prediction Quality Validation: {self.start_date} to {self.end_date}",
            f"Overall: {'PASS' if self.passed else 'FAIL'}",
            "",
        ]

        if self.dnp_voiding:
            lines.append(f"DNP Voiding Check: {self.dnp_voiding.status.value.upper()}")
            lines.append(f"  Total DNP: {self.dnp_voiding.total_dnp}")
            lines.append(f"  Properly voided: {self.dnp_voiding.dnp_voided}")
            lines.append(f"  Incorrectly graded: {self.dnp_voiding.dnp_graded}")
            lines.append("")

        if self.placeholder_lines:
            lines.append(f"Placeholder Lines Check: {self.placeholder_lines.status.value.upper()}")
            lines.append(f"  Placeholder lines: {self.placeholder_lines.total_placeholders}")
            lines.append(f"  Incorrectly graded: {self.placeholder_lines.placeholders_graded}")
            lines.append("")

        if self.stale_cache:
            lines.append(f"Stale Cache Check: {self.stale_cache.status.value.upper()}")
            lines.append(f"  Stale records: {self.stale_cache.stale_records} ({self.stale_cache.stale_pct:.1f}%)")
            lines.append("")

        if self.player_consistency:
            lines.append(f"Player Consistency Check: {self.player_consistency.status.value.upper()}")
            lines.append(f"  Mismatch rate: {self.player_consistency.mismatch_pct:.1f}%")
            lines.append(f"  Missing in analytics: {self.player_consistency.players_missing_in_analytics}")
            lines.append("")

        if self.issues:
            lines.append("Issues:")
            for issue in self.issues:
                lines.append(f"  - {issue}")

        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        return "\n".join(lines)


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def check_dnp_voiding(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> DNPVoidingResult:
    """
    Check that DNP (actual_points=0) predictions are properly voided.

    DNP predictions should have prediction_correct=NULL, not TRUE/FALSE.
    """
    result = DNPVoidingResult()

    query = f"""
    SELECT
        COUNTIF(actual_points = 0) as total_dnp,
        COUNTIF(actual_points = 0 AND prediction_correct IS NULL) as dnp_voided,
        COUNTIF(actual_points = 0 AND prediction_correct IS NOT NULL) as dnp_graded,
        COUNTIF(actual_points = 0 AND prediction_correct = TRUE) as dnp_correct,
        COUNTIF(actual_points = 0 AND prediction_correct = FALSE) as dnp_incorrect
    FROM `{PROJECT_ID}.{PREDICTION_ACCURACY_TABLE}`
    WHERE game_date BETWEEN @start_date AND @end_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        row = next(iter(query_result))

        result.total_dnp = row.total_dnp or 0
        result.dnp_voided = row.dnp_voided or 0
        result.dnp_graded = row.dnp_graded or 0
        result.dnp_graded_as_correct = row.dnp_correct or 0
        result.dnp_graded_as_incorrect = row.dnp_incorrect or 0

        if result.dnp_graded == 0:
            result.status = CheckStatus.PASS
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"CRITICAL: {result.dnp_graded} DNP predictions incorrectly graded "
                f"({result.dnp_graded_as_correct} as correct, {result.dnp_graded_as_incorrect} as incorrect)"
            )

    except Exception as e:
        logger.error(f"Error checking DNP voiding: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    # Sample some issues
    if result.dnp_graded > 0:
        sample_query = f"""
        SELECT
            player_lookup,
            game_date,
            actual_points,
            predicted_points,
            line_value,
            prediction_correct,
            model_version
        FROM `{PROJECT_ID}.{PREDICTION_ACCURACY_TABLE}`
        WHERE game_date BETWEEN @start_date AND @end_date
            AND actual_points = 0
            AND prediction_correct IS NOT NULL
        ORDER BY game_date DESC
        LIMIT 10
        """
        try:
            sample_result = client.query(sample_query, job_config=job_config).result(
                timeout=BQ_QUERY_TIMEOUT_SECONDS
            )
            for row in sample_result:
                result.sample_issues.append({
                    'player': row.player_lookup,
                    'date': str(row.game_date),
                    'actual': row.actual_points,
                    'predicted': row.predicted_points,
                    'graded_as': 'correct' if row.prediction_correct else 'incorrect',
                })
        except Exception as e:
            logger.warning(f"Error sampling DNP issues: {e}")

    return result


def check_placeholder_lines(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> PlaceholderLineResult:
    """
    Check that placeholder lines (line_value=20.0) are not graded.
    """
    result = PlaceholderLineResult()

    query = f"""
    SELECT
        COUNTIF(line_value = {PLACEHOLDER_LINE_VALUE}) as total_placeholders,
        COUNTIF(line_value = {PLACEHOLDER_LINE_VALUE} AND prediction_correct IS NOT NULL) as placeholders_graded
    FROM `{PROJECT_ID}.{PREDICTION_ACCURACY_TABLE}`
    WHERE game_date BETWEEN @start_date AND @end_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        row = next(iter(query_result))

        result.total_placeholders = row.total_placeholders or 0
        result.placeholders_graded = row.placeholders_graded or 0

        if result.placeholders_graded == 0:
            result.status = CheckStatus.PASS
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"CRITICAL: {result.placeholders_graded} placeholder lines (value={PLACEHOLDER_LINE_VALUE}) "
                f"incorrectly graded"
            )

    except Exception as e:
        logger.error(f"Error checking placeholder lines: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_stale_cache(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> StaleCacheResult:
    """
    Check for stale cache data that might affect prediction quality.
    """
    result = StaleCacheResult()

    # For recent dates, cache should be relatively fresh
    # We check if cache was created more than STALE_CACHE_HOURS after the game date
    query = f"""
    WITH cache_freshness AS (
        SELECT
            cache_date,
            created_at,
            TIMESTAMP_DIFF(created_at, TIMESTAMP(cache_date), HOUR) as hours_after_date,
            COUNT(*) as record_count
        FROM `{PROJECT_ID}.{CACHE_TABLE}`
        WHERE cache_date BETWEEN @start_date AND @end_date
            AND created_at IS NOT NULL
        GROUP BY cache_date, created_at
    )
    SELECT
        SUM(record_count) as total_records,
        SUM(CASE WHEN hours_after_date > {STALE_CACHE_HOURS * 24} THEN record_count ELSE 0 END) as stale_records,
        MAX(hours_after_date) as max_hours_after
    FROM cache_freshness
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        row = next(iter(query_result))

        result.total_records = row.total_records or 0
        result.stale_records = row.stale_records or 0
        result.oldest_cache_hours = row.max_hours_after or 0

        if result.total_records > 0:
            result.stale_pct = 100.0 * result.stale_records / result.total_records

        # Stale cache is a warning, not a failure (could be backfill data)
        if result.stale_pct == 0:
            result.status = CheckStatus.PASS
        elif result.stale_pct < 10:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"Some cache data is stale: {result.stale_pct:.1f}% created >24h after date"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"HIGH: {result.stale_pct:.1f}% of cache data is stale"
            )

    except Exception as e:
        logger.error(f"Error checking stale cache: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_player_consistency(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> PlayerConsistencyResult:
    """
    Check player_lookup consistency across phases.
    Players in predictions should exist in analytics.
    """
    result = PlayerConsistencyResult()

    query = f"""
    WITH prediction_players AS (
        SELECT DISTINCT player_lookup
        FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
        WHERE game_date BETWEEN @start_date AND @end_date
    ),
    analytics_players AS (
        SELECT DISTINCT player_lookup
        FROM `{PROJECT_ID}.{PLAYER_GAME_SUMMARY_TABLE}`
        WHERE game_date BETWEEN @start_date AND @end_date
    )
    SELECT
        (SELECT COUNT(*) FROM prediction_players) as pred_players,
        (SELECT COUNT(*) FROM analytics_players) as analytics_players,
        (SELECT COUNT(*) FROM prediction_players p
         WHERE NOT EXISTS (SELECT 1 FROM analytics_players a WHERE a.player_lookup = p.player_lookup)
        ) as missing_in_analytics,
        (SELECT COUNT(*) FROM analytics_players a
         WHERE NOT EXISTS (SELECT 1 FROM prediction_players p WHERE p.player_lookup = a.player_lookup)
        ) as missing_in_predictions
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        row = next(iter(query_result))

        result.players_in_predictions = row.pred_players or 0
        result.players_in_analytics = row.analytics_players or 0
        result.players_missing_in_analytics = row.missing_in_analytics or 0
        result.players_missing_in_predictions = row.missing_in_predictions or 0

        total_players = max(result.players_in_predictions, result.players_in_analytics)
        result.total_players_checked = total_players

        if total_players > 0:
            result.mismatch_pct = 100.0 * result.players_missing_in_analytics / total_players

        if result.mismatch_pct <= PLAYER_MISMATCH_THRESHOLD:
            result.status = CheckStatus.PASS
        elif result.mismatch_pct <= 10:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"Player mismatch: {result.players_missing_in_analytics} players in predictions "
                f"not found in analytics ({result.mismatch_pct:.1f}%)"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"HIGH: {result.mismatch_pct:.1f}% player mismatch between predictions and analytics"
            )

    except Exception as e:
        logger.error(f"Error checking player consistency: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    # Sample mismatched players
    if result.players_missing_in_analytics > 0:
        sample_query = f"""
        WITH prediction_players AS (
            SELECT DISTINCT player_lookup
            FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
            WHERE game_date BETWEEN @start_date AND @end_date
        ),
        analytics_players AS (
            SELECT DISTINCT player_lookup
            FROM `{PROJECT_ID}.{PLAYER_GAME_SUMMARY_TABLE}`
            WHERE game_date BETWEEN @start_date AND @end_date
        )
        SELECT player_lookup
        FROM prediction_players p
        WHERE NOT EXISTS (SELECT 1 FROM analytics_players a WHERE a.player_lookup = p.player_lookup)
        LIMIT 10
        """
        try:
            sample_result = client.query(sample_query, job_config=job_config).result(
                timeout=BQ_QUERY_TIMEOUT_SECONDS
            )
            result.sample_mismatches = [row.player_lookup for row in sample_result]
        except Exception as e:
            logger.warning(f"Error sampling player mismatches: {e}")

    return result


def validate_prediction_quality(
    client: Optional[bigquery.Client] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    days: int = 7,
    check_dnp: bool = True,
    check_placeholders: bool = True,
    check_cache: bool = True,
    check_players: bool = True,
) -> PredictionQualityResult:
    """
    Run complete prediction quality validation.
    """
    start_time = datetime.now()

    # Default dates
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    if start_date is None:
        start_date = end_date - timedelta(days=days)

    result = PredictionQualityResult(
        start_date=start_date,
        end_date=end_date,
    )

    # Create client if needed
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    # Run checks
    if check_dnp:
        result.dnp_voiding = check_dnp_voiding(client, start_date, end_date)
        if result.dnp_voiding.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.dnp_voiding.issues)

    if check_placeholders:
        result.placeholder_lines = check_placeholder_lines(client, start_date, end_date)
        if result.placeholder_lines.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.placeholder_lines.issues)

    if check_cache:
        result.stale_cache = check_stale_cache(client, start_date, end_date)
        if result.stale_cache.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.stale_cache.issues)
        elif result.stale_cache.status == CheckStatus.WARN:
            result.warnings.extend(result.stale_cache.issues)

    if check_players:
        result.player_consistency = check_player_consistency(client, start_date, end_date)
        if result.player_consistency.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.player_consistency.issues)
        elif result.player_consistency.status == CheckStatus.WARN:
            result.warnings.extend(result.player_consistency.issues)

    result.validation_time_seconds = (datetime.now() - start_time).total_seconds()

    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for prediction quality validation."""
    parser = argparse.ArgumentParser(description="Validate prediction grading quality")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Number of days to check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--ci", action="store_true", help="Exit with code 1 if validation fails")

    args = parser.parse_args()

    # Parse dates
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    # Run validation
    result = validate_prediction_quality(
        start_date=start_date,
        end_date=end_date,
        days=args.days,
    )

    # Output
    if args.json:
        import json
        output = {
            'passed': result.passed,
            'start_date': str(result.start_date),
            'end_date': str(result.end_date),
            'issues': result.issues,
            'warnings': result.warnings,
        }
        if result.dnp_voiding:
            output['dnp_voiding'] = {
                'status': result.dnp_voiding.status.value,
                'total_dnp': result.dnp_voiding.total_dnp,
                'dnp_graded': result.dnp_voiding.dnp_graded,
            }
        if result.placeholder_lines:
            output['placeholder_lines'] = {
                'status': result.placeholder_lines.status.value,
                'total': result.placeholder_lines.total_placeholders,
                'graded': result.placeholder_lines.placeholders_graded,
            }
        if result.stale_cache:
            output['stale_cache'] = {
                'status': result.stale_cache.status.value,
                'stale_pct': result.stale_cache.stale_pct,
            }
        if result.player_consistency:
            output['player_consistency'] = {
                'status': result.player_consistency.status.value,
                'mismatch_pct': result.player_consistency.mismatch_pct,
            }
        print(json.dumps(output, indent=2))
    else:
        print(result.summary)

    if args.ci and not result.passed:
        exit(1)


if __name__ == "__main__":
    main()
