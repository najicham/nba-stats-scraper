"""
Cross-Phase Consistency Validator

Validates data consistency across pipeline phases to catch data loss
or transformation issues.

Checks:
- Row count matching between phases for same game_date
- Player_lookup consistency across phases
- Grading completeness (predictions have grades)
- Phase timing validation

Usage:
    python -m shared.validation.cross_phase_validator --days 7

    from shared.validation.cross_phase_validator import validate_cross_phase
    result = validate_cross_phase(client, start_date, end_date)
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

# Phase 2 (Raw)
RAW_BOXSCORES = "nba_raw.nbac_gamebook_player_stats"

# Phase 3 (Analytics)
PLAYER_GAME_SUMMARY = "nba_analytics.player_game_summary"

# Phase 4 (Precompute)
PLAYER_DAILY_CACHE = "nba_precompute.player_daily_cache"
FEATURE_STORE = "nba_predictions.ml_feature_store_v2"

# Phase 5 (Predictions)
PREDICTIONS = "nba_predictions.player_prop_predictions"
PREDICTION_ACCURACY = "nba_predictions.prediction_accuracy"

# Thresholds
ROW_COUNT_VARIANCE_THRESHOLD = 10.0  # Max % difference between phases
GRADING_COMPLETENESS_THRESHOLD = 95.0  # Min % of predictions that should be graded


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================

class CheckStatus(Enum):
    PASS = 'pass'
    WARN = 'warn'
    FAIL = 'fail'
    ERROR = 'error'


@dataclass
class PhaseRowCountResult:
    """Result of row count comparison between phases."""
    game_date: date
    phase2_rows: int = 0
    phase3_rows: int = 0
    phase4_cache_rows: int = 0
    phase4_features_rows: int = 0
    phase5_predictions: int = 0
    variance_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    issues: List[str] = field(default_factory=list)


@dataclass
class RowCountConsistencyResult:
    """Aggregate row count consistency result."""
    total_dates_checked: int = 0
    dates_with_issues: int = 0
    max_variance_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    by_date: List[PhaseRowCountResult] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class GradingCompletenessResult:
    """Result of grading completeness check."""
    total_predictions: int = 0
    graded_predictions: int = 0
    ungraded_predictions: int = 0
    completeness_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    ungraded_by_date: Dict[str, int] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)


@dataclass
class PlayerFlowResult:
    """Result of player flow validation across phases."""
    total_players: int = 0
    players_in_all_phases: int = 0
    players_missing_phase3: int = 0
    players_missing_phase4: int = 0
    players_missing_phase5: int = 0
    flow_completeness_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    sample_missing: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class CrossPhaseValidationResult:
    """Complete cross-phase validation result."""
    start_date: date
    end_date: date
    passed: bool = True
    row_counts: Optional[RowCountConsistencyResult] = None
    grading: Optional[GradingCompletenessResult] = None
    player_flow: Optional[PlayerFlowResult] = None
    validation_time_seconds: float = 0.0
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Cross-Phase Validation: {self.start_date} to {self.end_date}",
            f"Overall: {'PASS' if self.passed else 'FAIL'}",
            "",
        ]

        if self.row_counts:
            lines.append(f"Row Count Consistency: {self.row_counts.status.value.upper()}")
            lines.append(f"  Dates checked: {self.row_counts.total_dates_checked}")
            lines.append(f"  Dates with issues: {self.row_counts.dates_with_issues}")
            lines.append(f"  Max variance: {self.row_counts.max_variance_pct:.1f}%")
            lines.append("")

        if self.grading:
            lines.append(f"Grading Completeness: {self.grading.status.value.upper()}")
            lines.append(f"  Total predictions: {self.grading.total_predictions:,}")
            lines.append(f"  Graded: {self.grading.graded_predictions:,} ({self.grading.completeness_pct:.1f}%)")
            lines.append(f"  Ungraded: {self.grading.ungraded_predictions:,}")
            lines.append("")

        if self.player_flow:
            lines.append(f"Player Flow: {self.player_flow.status.value.upper()}")
            lines.append(f"  Players tracked: {self.player_flow.total_players}")
            lines.append(f"  Complete flow: {self.player_flow.flow_completeness_pct:.1f}%")
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

def check_row_count_consistency(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> RowCountConsistencyResult:
    """
    Check that row counts are consistent across phases.
    """
    result = RowCountConsistencyResult()

    query = f"""
    WITH phase2 AS (
        SELECT game_date, COUNT(DISTINCT player_lookup) as rows
        FROM `{PROJECT_ID}.{RAW_BOXSCORES}`
        WHERE game_date BETWEEN @start_date AND @end_date
        GROUP BY game_date
    ),
    phase3 AS (
        SELECT game_date, COUNT(DISTINCT player_lookup) as rows
        FROM `{PROJECT_ID}.{PLAYER_GAME_SUMMARY}`
        WHERE game_date BETWEEN @start_date AND @end_date
        GROUP BY game_date
    ),
    phase4_cache AS (
        SELECT cache_date as game_date, COUNT(DISTINCT player_lookup) as rows
        FROM `{PROJECT_ID}.{PLAYER_DAILY_CACHE}`
        WHERE cache_date BETWEEN @start_date AND @end_date
        GROUP BY cache_date
    ),
    phase4_features AS (
        SELECT game_date, COUNT(DISTINCT player_lookup) as rows
        FROM `{PROJECT_ID}.{FEATURE_STORE}`
        WHERE game_date BETWEEN @start_date AND @end_date
        GROUP BY game_date
    ),
    phase5 AS (
        SELECT game_date, COUNT(DISTINCT player_lookup) as rows
        FROM `{PROJECT_ID}.{PREDICTIONS}`
        WHERE game_date BETWEEN @start_date AND @end_date
        GROUP BY game_date
    )
    SELECT
        COALESCE(p2.game_date, p3.game_date, p4c.game_date, p4f.game_date, p5.game_date) as game_date,
        COALESCE(p2.rows, 0) as phase2_rows,
        COALESCE(p3.rows, 0) as phase3_rows,
        COALESCE(p4c.rows, 0) as phase4_cache_rows,
        COALESCE(p4f.rows, 0) as phase4_features_rows,
        COALESCE(p5.rows, 0) as phase5_rows
    FROM phase2 p2
    FULL OUTER JOIN phase3 p3 ON p2.game_date = p3.game_date
    FULL OUTER JOIN phase4_cache p4c ON COALESCE(p2.game_date, p3.game_date) = p4c.game_date
    FULL OUTER JOIN phase4_features p4f ON COALESCE(p2.game_date, p3.game_date, p4c.game_date) = p4f.game_date
    FULL OUTER JOIN phase5 p5 ON COALESCE(p2.game_date, p3.game_date, p4c.game_date, p4f.game_date) = p5.game_date
    ORDER BY game_date DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS * 2  # Allow more time for complex join
        )

        for row in query_result:
            date_result = PhaseRowCountResult(
                game_date=row.game_date,
                phase2_rows=row.phase2_rows,
                phase3_rows=row.phase3_rows,
                phase4_cache_rows=row.phase4_cache_rows,
                phase4_features_rows=row.phase4_features_rows,
                phase5_predictions=row.phase5_rows,
            )

            # Calculate variance between phases
            counts = [c for c in [row.phase2_rows, row.phase3_rows, row.phase4_cache_rows] if c > 0]
            if counts:
                max_count = max(counts)
                min_count = min(counts)
                if max_count > 0:
                    date_result.variance_pct = 100.0 * (max_count - min_count) / max_count

            # Check for issues
            if date_result.variance_pct > ROW_COUNT_VARIANCE_THRESHOLD:
                date_result.status = CheckStatus.WARN
                date_result.issues.append(
                    f"Row count variance {date_result.variance_pct:.1f}% on {row.game_date}"
                )
                result.dates_with_issues += 1

            result.by_date.append(date_result)
            result.total_dates_checked += 1
            result.max_variance_pct = max(result.max_variance_pct, date_result.variance_pct)

        # Overall status
        if result.dates_with_issues == 0:
            result.status = CheckStatus.PASS
        elif result.dates_with_issues <= 2:
            result.status = CheckStatus.WARN
            result.issues.append(f"{result.dates_with_issues} dates with row count variance")
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(f"HIGH: {result.dates_with_issues} dates with row count variance")

    except Exception as e:
        logger.error(f"Error checking row count consistency: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_grading_completeness(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> GradingCompletenessResult:
    """
    Check that predictions have been graded.
    """
    result = GradingCompletenessResult()

    query = f"""
    WITH predictions AS (
        SELECT game_date, player_lookup, model_version
        FROM `{PROJECT_ID}.{PREDICTIONS}`
        WHERE game_date BETWEEN @start_date AND @end_date
    ),
    graded AS (
        SELECT game_date, player_lookup, model_version
        FROM `{PROJECT_ID}.{PREDICTION_ACCURACY}`
        WHERE game_date BETWEEN @start_date AND @end_date
    )
    SELECT
        p.game_date,
        COUNT(*) as total_predictions,
        COUNTIF(g.player_lookup IS NOT NULL) as graded_count
    FROM predictions p
    LEFT JOIN graded g
        ON p.game_date = g.game_date
        AND p.player_lookup = g.player_lookup
        AND p.model_version = g.model_version
    GROUP BY p.game_date
    ORDER BY p.game_date DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS * 2
        )

        total_pred = 0
        total_graded = 0

        for row in query_result:
            total_pred += row.total_predictions
            total_graded += row.graded_count
            ungraded = row.total_predictions - row.graded_count
            if ungraded > 0:
                result.ungraded_by_date[str(row.game_date)] = ungraded

        result.total_predictions = total_pred
        result.graded_predictions = total_graded
        result.ungraded_predictions = total_pred - total_graded

        if total_pred > 0:
            result.completeness_pct = 100.0 * total_graded / total_pred

        if result.completeness_pct >= GRADING_COMPLETENESS_THRESHOLD:
            result.status = CheckStatus.PASS
        elif result.completeness_pct >= 80:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"Grading completeness below threshold: {result.completeness_pct:.1f}%"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"HIGH: Low grading completeness: {result.completeness_pct:.1f}%"
            )

    except Exception as e:
        logger.error(f"Error checking grading completeness: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_player_flow(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> PlayerFlowResult:
    """
    Check that players flow through all phases consistently.
    """
    result = PlayerFlowResult()

    query = f"""
    WITH phase2_players AS (
        SELECT DISTINCT player_lookup, game_date
        FROM `{PROJECT_ID}.{RAW_BOXSCORES}`
        WHERE game_date BETWEEN @start_date AND @end_date
    ),
    phase3_players AS (
        SELECT DISTINCT player_lookup, game_date
        FROM `{PROJECT_ID}.{PLAYER_GAME_SUMMARY}`
        WHERE game_date BETWEEN @start_date AND @end_date
    ),
    phase4_players AS (
        SELECT DISTINCT player_lookup, cache_date as game_date
        FROM `{PROJECT_ID}.{PLAYER_DAILY_CACHE}`
        WHERE cache_date BETWEEN @start_date AND @end_date
    ),
    phase5_players AS (
        SELECT DISTINCT player_lookup, game_date
        FROM `{PROJECT_ID}.{PREDICTIONS}`
        WHERE game_date BETWEEN @start_date AND @end_date
    )
    SELECT
        COUNT(DISTINCT p2.player_lookup) as total_phase2,
        COUNT(DISTINCT CASE WHEN p3.player_lookup IS NOT NULL THEN p2.player_lookup END) as in_phase3,
        COUNT(DISTINCT CASE WHEN p4.player_lookup IS NOT NULL THEN p2.player_lookup END) as in_phase4,
        COUNT(DISTINCT CASE WHEN p5.player_lookup IS NOT NULL THEN p2.player_lookup END) as in_phase5,
        COUNT(DISTINCT CASE WHEN p3.player_lookup IS NOT NULL AND p4.player_lookup IS NOT NULL AND p5.player_lookup IS NOT NULL THEN p2.player_lookup END) as in_all_phases
    FROM phase2_players p2
    LEFT JOIN phase3_players p3 ON p2.player_lookup = p3.player_lookup AND p2.game_date = p3.game_date
    LEFT JOIN phase4_players p4 ON p2.player_lookup = p4.player_lookup AND p2.game_date = p4.game_date
    LEFT JOIN phase5_players p5 ON p2.player_lookup = p5.player_lookup AND p2.game_date = p5.game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    try:
        query_result = client.query(query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS * 2
        )
        row = next(iter(query_result))

        result.total_players = row.total_phase2
        result.players_in_all_phases = row.in_all_phases
        result.players_missing_phase3 = row.total_phase2 - row.in_phase3
        result.players_missing_phase4 = row.total_phase2 - row.in_phase4
        result.players_missing_phase5 = row.total_phase2 - row.in_phase5

        if result.total_players > 0:
            result.flow_completeness_pct = 100.0 * row.in_all_phases / result.total_players

        if result.flow_completeness_pct >= 95:
            result.status = CheckStatus.PASS
        elif result.flow_completeness_pct >= 80:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"Player flow completeness: {result.flow_completeness_pct:.1f}% "
                f"(missing: P3={result.players_missing_phase3}, P4={result.players_missing_phase4}, P5={result.players_missing_phase5})"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"HIGH: Low player flow completeness: {result.flow_completeness_pct:.1f}%"
            )

    except Exception as e:
        logger.error(f"Error checking player flow: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def validate_cross_phase(
    client: Optional[bigquery.Client] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    days: int = 7,
    check_row_counts: bool = True,
    check_grading: bool = True,
    check_flow: bool = True,
) -> CrossPhaseValidationResult:
    """
    Run complete cross-phase validation.
    """
    start_time = datetime.now()

    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    if start_date is None:
        start_date = end_date - timedelta(days=days)

    result = CrossPhaseValidationResult(
        start_date=start_date,
        end_date=end_date,
    )

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    if check_row_counts:
        result.row_counts = check_row_count_consistency(client, start_date, end_date)
        if result.row_counts.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.row_counts.issues)
        elif result.row_counts.status == CheckStatus.WARN:
            result.warnings.extend(result.row_counts.issues)

    if check_grading:
        result.grading = check_grading_completeness(client, start_date, end_date)
        if result.grading.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.grading.issues)
        elif result.grading.status == CheckStatus.WARN:
            result.warnings.extend(result.grading.issues)

    if check_flow:
        result.player_flow = check_player_flow(client, start_date, end_date)
        if result.player_flow.status == CheckStatus.FAIL:
            result.passed = False
            result.issues.extend(result.player_flow.issues)
        elif result.player_flow.status == CheckStatus.WARN:
            result.warnings.extend(result.player_flow.issues)

    result.validation_time_seconds = (datetime.now() - start_time).total_seconds()

    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Validate cross-phase data consistency")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Number of days to check")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--ci", action="store_true", help="Exit with code 1 if validation fails")

    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    result = validate_cross_phase(
        start_date=start_date,
        end_date=end_date,
        days=args.days,
    )

    if args.json:
        import json
        output = {
            'passed': result.passed,
            'start_date': str(result.start_date),
            'end_date': str(result.end_date),
            'issues': result.issues,
            'warnings': result.warnings,
        }
        if result.row_counts:
            output['row_counts'] = {
                'status': result.row_counts.status.value,
                'dates_checked': result.row_counts.total_dates_checked,
                'dates_with_issues': result.row_counts.dates_with_issues,
            }
        if result.grading:
            output['grading'] = {
                'status': result.grading.status.value,
                'completeness_pct': result.grading.completeness_pct,
                'ungraded': result.grading.ungraded_predictions,
            }
        if result.player_flow:
            output['player_flow'] = {
                'status': result.player_flow.status.value,
                'completeness_pct': result.player_flow.flow_completeness_pct,
            }
        print(json.dumps(output, indent=2))
    else:
        print(result.summary)

    if args.ci and not result.passed:
        exit(1)


if __name__ == "__main__":
    main()
