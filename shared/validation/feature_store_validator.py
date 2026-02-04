"""
Feature Store Validator

Validates data integrity between ml_feature_store_v2 and its source tables.
Detects issues like:
- L5/L10 rolling average mismatches vs player_daily_cache
- Duplicate records
- Invalid feature arrays (wrong length, NaN/Inf values)

This validator was created to catch bugs like the Session 27 L5/L10 data leakage issue.

Usage:
    # CLI validation
    python -m shared.validation.feature_store_validator --days 7

    # In code
    from shared.validation.feature_store_validator import (
        validate_feature_store,
        check_feature_cache_consistency,
        check_duplicates,
        check_array_integrity,
    )

    result = validate_feature_store(client, start_date, end_date)
    if not result.passed:
        print(result.summary)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import logging
import argparse

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID, BQ_QUERY_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

FEATURE_STORE_TABLE = "nba_predictions.ml_feature_store_v2"
CACHE_TABLE = "nba_precompute.player_daily_cache"
PREDICTIONS_TABLE = "nba_predictions.player_prop_predictions"

# Expected feature array length
# Note: Changed from 33 to 34 on 2026-01-29, then to 37 on 2026-02-03 after trajectory features added
EXPECTED_FEATURE_COUNT = 37

# Thresholds
L5_L10_MATCH_THRESHOLD = 95.0  # Minimum % of records that should match cache
DUPLICATE_THRESHOLD = 0  # Any duplicates are bad
ARRAY_INTEGRITY_THRESHOLD = 0  # Any invalid arrays are bad
MISMATCH_TOLERANCE = 0.1  # Allowable difference for L5/L10 values

# Feature bounds (index -> (min, max, name))
# These are reasonable ranges for NBA player statistics
FEATURE_BOUNDS = {
    0: (0, 50, "points_l5_avg"),      # L5 points avg
    1: (0, 50, "points_l10_avg"),     # L10 points avg
    6: (0, 48, "minutes_l5_avg"),     # L5 minutes avg (max 48 min/game)
    7: (0, 48, "minutes_l10_avg"),    # L10 minutes avg
    14: (0, 50, "usage_rate_l5"),     # L5 usage rate (0-50%)
    15: (0, 50, "usage_rate_l10"),    # L10 usage rate
    16: (0, 14, "days_rest"),         # Days rest (0-14 reasonable)
    17: (0, 1, "is_home"),            # Binary
    21: (0, 100, "season_games"),     # Season games played
    31: (0, 60, "line_value"),        # Prop line value
    33: (0, 1, "dnp_rate"),           # DNP rate (0-1)
    34: (-5, 5, "pts_slope_10g"),     # Points slope over 10 games
    35: (-4, 4, "pts_vs_season_zscore"),  # Z-score vs season avg
    36: (0, 1, "breakout_flag"),      # Breakout flag (binary)
}

# Prop line thresholds
PROP_LINE_COVERAGE_THRESHOLD = 50.0  # Minimum % of predictions with prop lines
PLACEHOLDER_LINE_VALUE = 20.0  # Known placeholder value


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
class ConsistencyResult:
    """Result of feature store vs cache consistency check."""
    total_records: int = 0
    matched_records: int = 0
    l5_match_pct: float = 0.0
    l10_match_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    mismatched_samples: List[Dict[str, Any]] = field(default_factory=list)
    by_month: Dict[str, Dict[str, float]] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)


@dataclass
class DuplicateResult:
    """Result of duplicate detection check."""
    feature_store_duplicates: int = 0
    cache_duplicates: int = 0
    predictions_duplicates: int = 0
    status: CheckStatus = CheckStatus.PASS
    duplicate_samples: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class ArrayIntegrityResult:
    """Result of array integrity check."""
    total_checked: int = 0
    null_arrays: int = 0
    wrong_length: int = 0
    nan_values: int = 0
    inf_values: int = 0
    status: CheckStatus = CheckStatus.PASS
    invalid_samples: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class FeatureBoundsResult:
    """Result of feature bounds check."""
    total_checked: int = 0
    out_of_bounds: int = 0
    out_of_bounds_pct: float = 0.0
    by_feature: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    status: CheckStatus = CheckStatus.PASS
    sample_violations: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class PropLineCoverageResult:
    """Result of prop line coverage check."""
    total_predictions: int = 0
    with_prop_line: int = 0
    without_prop_line: int = 0
    placeholder_lines: int = 0
    coverage_pct: float = 0.0
    status: CheckStatus = CheckStatus.PASS
    by_date: Dict[str, float] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)


@dataclass
class FeatureStoreValidationResult:
    """Complete validation result for feature store."""
    start_date: date
    end_date: date
    passed: bool = True
    consistency: Optional[ConsistencyResult] = None
    duplicates: Optional[DuplicateResult] = None
    array_integrity: Optional[ArrayIntegrityResult] = None
    feature_bounds: Optional[FeatureBoundsResult] = None
    prop_line_coverage: Optional[PropLineCoverageResult] = None
    validation_time_seconds: float = 0.0
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Feature Store Validation: {self.start_date} to {self.end_date}",
            f"Overall: {'PASS' if self.passed else 'FAIL'}",
            "",
        ]

        if self.consistency:
            lines.append(f"Consistency Check: {self.consistency.status.value.upper()}")
            lines.append(f"  L5 match: {self.consistency.l5_match_pct:.1f}%")
            lines.append(f"  L10 match: {self.consistency.l10_match_pct:.1f}%")
            lines.append(f"  Records checked: {self.consistency.total_records:,}")
            lines.append("")

        if self.duplicates:
            lines.append(f"Duplicate Check: {self.duplicates.status.value.upper()}")
            lines.append(f"  Feature store: {self.duplicates.feature_store_duplicates}")
            lines.append(f"  Cache: {self.duplicates.cache_duplicates}")
            lines.append(f"  Predictions: {self.duplicates.predictions_duplicates}")
            lines.append("")

        if self.array_integrity:
            lines.append(f"Array Integrity: {self.array_integrity.status.value.upper()}")
            lines.append(f"  NULL arrays: {self.array_integrity.null_arrays}")
            lines.append(f"  Wrong length: {self.array_integrity.wrong_length}")
            lines.append(f"  NaN values: {self.array_integrity.nan_values}")
            lines.append(f"  Inf values: {self.array_integrity.inf_values}")
            lines.append("")

        if self.feature_bounds:
            lines.append(f"Feature Bounds: {self.feature_bounds.status.value.upper()}")
            lines.append(f"  Out of bounds: {self.feature_bounds.out_of_bounds} ({self.feature_bounds.out_of_bounds_pct:.2f}%)")
            lines.append("")

        if self.prop_line_coverage:
            lines.append(f"Prop Line Coverage: {self.prop_line_coverage.status.value.upper()}")
            lines.append(f"  Coverage: {self.prop_line_coverage.coverage_pct:.1f}%")
            lines.append(f"  Placeholder lines: {self.prop_line_coverage.placeholder_lines}")
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

def check_feature_cache_consistency(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
    sample_mismatches: bool = True,
) -> ConsistencyResult:
    """
    Check L5/L10 consistency between feature store and cache.

    Args:
        client: BigQuery client
        start_date: Start of date range
        end_date: End of date range
        sample_mismatches: Whether to sample mismatched records

    Returns:
        ConsistencyResult with match rates and samples
    """
    result = ConsistencyResult()

    # Query to compare L5/L10 values by month
    query = f"""
    WITH comparison AS (
        SELECT
            FORMAT_DATE('%Y-%m', fs.game_date) as month,
            fs.player_lookup,
            fs.game_date,
            ROUND(fs.features[OFFSET(0)], 2) as fs_l5,
            ROUND(c.points_avg_last_5, 2) as cache_l5,
            ROUND(fs.features[OFFSET(1)], 2) as fs_l10,
            ROUND(c.points_avg_last_10, 2) as cache_l10,
            ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < {MISMATCH_TOLERANCE} as l5_match,
            ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) < {MISMATCH_TOLERANCE} as l10_match
        FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}` fs
        JOIN `{PROJECT_ID}.{CACHE_TABLE}` c
            ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
        WHERE fs.game_date BETWEEN @start_date AND @end_date
            AND ARRAY_LENGTH(fs.features) >= 2
    )
    SELECT
        month,
        COUNT(*) as total,
        COUNTIF(l5_match) as l5_matches,
        ROUND(100.0 * COUNTIF(l5_match) / COUNT(*), 1) as l5_match_pct,
        COUNTIF(l10_match) as l10_matches,
        ROUND(100.0 * COUNTIF(l10_match) / COUNT(*), 1) as l10_match_pct
    FROM comparison
    GROUP BY month
    ORDER BY month
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

        total_records = 0
        total_l5_matches = 0
        total_l10_matches = 0

        for row in query_result:
            result.by_month[row.month] = {
                'total': row.total,
                'l5_match_pct': row.l5_match_pct,
                'l10_match_pct': row.l10_match_pct,
            }
            total_records += row.total
            total_l5_matches += row.l5_matches
            total_l10_matches += row.l10_matches

        result.total_records = total_records
        result.matched_records = total_l5_matches

        if total_records > 0:
            result.l5_match_pct = 100.0 * total_l5_matches / total_records
            result.l10_match_pct = 100.0 * total_l10_matches / total_records

        # Determine status
        if result.l5_match_pct >= L5_L10_MATCH_THRESHOLD and result.l10_match_pct >= L5_L10_MATCH_THRESHOLD:
            result.status = CheckStatus.PASS
        elif result.l5_match_pct >= 50 and result.l10_match_pct >= 50:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"L5/L10 match rates below threshold: L5={result.l5_match_pct:.1f}%, L10={result.l10_match_pct:.1f}%"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"CRITICAL: L5/L10 match rates very low: L5={result.l5_match_pct:.1f}%, L10={result.l10_match_pct:.1f}% - possible data leakage"
            )

    except Exception as e:
        logger.error(f"Error checking feature-cache consistency: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")
        return result

    # Sample mismatched records
    if sample_mismatches and result.l5_match_pct < 100:
        sample_query = f"""
        WITH comparison AS (
            SELECT
                fs.player_lookup,
                fs.game_date,
                ROUND(fs.features[OFFSET(0)], 2) as fs_l5,
                ROUND(c.points_avg_last_5, 2) as cache_l5,
                ROUND(fs.features[OFFSET(1)], 2) as fs_l10,
                ROUND(c.points_avg_last_10, 2) as cache_l10
            FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}` fs
            JOIN `{PROJECT_ID}.{CACHE_TABLE}` c
                ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
            WHERE fs.game_date BETWEEN @start_date AND @end_date
                AND ARRAY_LENGTH(fs.features) >= 2
                AND ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) >= {MISMATCH_TOLERANCE}
        )
        SELECT * FROM comparison
        ORDER BY game_date DESC, ABS(fs_l5 - cache_l5) DESC
        LIMIT 10
        """

        try:
            sample_result = client.query(sample_query, job_config=job_config).result(
                timeout=BQ_QUERY_TIMEOUT_SECONDS
            )
            for row in sample_result:
                result.mismatched_samples.append({
                    'player_lookup': row.player_lookup,
                    'game_date': str(row.game_date),
                    'fs_l5': row.fs_l5,
                    'cache_l5': row.cache_l5,
                    'diff': round(abs(row.fs_l5 - row.cache_l5), 2),
                })
        except Exception as e:
            logger.warning(f"Error sampling mismatches: {e}")

    return result


def check_duplicates(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> DuplicateResult:
    """
    Check for duplicate records in feature store and related tables.

    Args:
        client: BigQuery client
        start_date: Start of date range
        end_date: End of date range

    Returns:
        DuplicateResult with duplicate counts
    """
    result = DuplicateResult()

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    # Check feature store duplicates
    fs_dup_query = f"""
    SELECT COUNT(*) as dup_count
    FROM (
        SELECT player_lookup, game_date, COUNT(*) as cnt
        FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}`
        WHERE game_date BETWEEN @start_date AND @end_date
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
    )
    """

    # Check cache duplicates
    cache_dup_query = f"""
    SELECT COUNT(*) as dup_count
    FROM (
        SELECT player_lookup, cache_date, COUNT(*) as cnt
        FROM `{PROJECT_ID}.{CACHE_TABLE}`
        WHERE cache_date BETWEEN @start_date AND @end_date
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
    )
    """

    # Check predictions duplicates
    pred_dup_query = f"""
    SELECT COUNT(*) as dup_count
    FROM (
        SELECT player_lookup, game_date, model_version, prop_type, COUNT(*) as cnt
        FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
        WHERE game_date BETWEEN @start_date AND @end_date
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(*) > 1
    )
    """

    try:
        # Run queries
        fs_result = client.query(fs_dup_query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        result.feature_store_duplicates = next(iter(fs_result)).dup_count

        cache_result = client.query(cache_dup_query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        result.cache_duplicates = next(iter(cache_result)).dup_count

        pred_result = client.query(pred_dup_query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        result.predictions_duplicates = next(iter(pred_result)).dup_count

        # Determine status
        total_dups = (
            result.feature_store_duplicates +
            result.cache_duplicates +
            result.predictions_duplicates
        )

        if total_dups == 0:
            result.status = CheckStatus.PASS
        else:
            result.status = CheckStatus.FAIL
            if result.feature_store_duplicates > 0:
                result.issues.append(
                    f"Feature store has {result.feature_store_duplicates} duplicate (player, date) pairs"
                )
            if result.cache_duplicates > 0:
                result.issues.append(
                    f"Cache has {result.cache_duplicates} duplicate (player, date) pairs"
                )
            if result.predictions_duplicates > 0:
                result.issues.append(
                    f"Predictions has {result.predictions_duplicates} duplicate records"
                )

    except Exception as e:
        logger.error(f"Error checking duplicates: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_array_integrity(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> ArrayIntegrityResult:
    """
    Check feature array integrity (length, NaN, Inf).

    Args:
        client: BigQuery client
        start_date: Start of date range
        end_date: End of date range

    Returns:
        ArrayIntegrityResult with integrity metrics
    """
    result = ArrayIntegrityResult()

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    # Check array structure
    structure_query = f"""
    SELECT
        COUNT(*) as total,
        COUNTIF(features IS NULL) as null_count,
        COUNTIF(ARRAY_LENGTH(features) < {EXPECTED_FEATURE_COUNT}) as short_count,
        COUNTIF(ARRAY_LENGTH(features) > {EXPECTED_FEATURE_COUNT}) as long_count
    FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}`
    WHERE game_date BETWEEN @start_date AND @end_date
    """

    # Check for NaN/Inf values
    nan_inf_query = f"""
    SELECT COUNT(*) as bad_count
    FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}`
    WHERE game_date BETWEEN @start_date AND @end_date
        AND (
            EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_NAN(f))
            OR EXISTS(SELECT 1 FROM UNNEST(features) f WHERE IS_INF(f))
        )
    """

    try:
        # Check structure
        struct_result = client.query(structure_query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        row = next(iter(struct_result))
        result.total_checked = row.total
        result.null_arrays = row.null_count
        result.wrong_length = row.short_count + row.long_count

        # Check NaN/Inf
        nan_result = client.query(nan_inf_query, job_config=job_config).result(
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )
        bad_row = next(iter(nan_result))
        result.nan_values = bad_row.bad_count  # Combines NaN and Inf for simplicity

        # Determine status
        total_issues = result.null_arrays + result.wrong_length + result.nan_values

        if total_issues == 0:
            result.status = CheckStatus.PASS
        else:
            result.status = CheckStatus.FAIL
            if result.null_arrays > 0:
                result.issues.append(f"{result.null_arrays} records have NULL feature arrays")
            if result.wrong_length > 0:
                result.issues.append(
                    f"{result.wrong_length} records have wrong array length (expected {EXPECTED_FEATURE_COUNT})"
                )
            if result.nan_values > 0:
                result.issues.append(f"{result.nan_values} records have NaN or Inf values in features")

    except Exception as e:
        logger.error(f"Error checking array integrity: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_feature_bounds(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> FeatureBoundsResult:
    """
    Check that feature values are within reasonable bounds.

    Catches data issues where features have impossible values
    (e.g., negative minutes, usage_rate > 100%).
    """
    result = FeatureBoundsResult()

    # Build query to check each bounded feature
    bound_checks = []
    for idx, (min_val, max_val, name) in FEATURE_BOUNDS.items():
        bound_checks.append(
            f"COUNTIF(features[OFFSET({idx})] < {min_val} OR features[OFFSET({idx})] > {max_val}) as {name}_violations"
        )

    checks_sql = ",\n        ".join(bound_checks)

    query = f"""
    SELECT
        COUNT(*) as total,
        {checks_sql}
    FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}`
    WHERE game_date BETWEEN @start_date AND @end_date
        AND ARRAY_LENGTH(features) >= {max(FEATURE_BOUNDS.keys()) + 1}
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

        result.total_checked = row.total
        total_violations = 0

        for idx, (min_val, max_val, name) in FEATURE_BOUNDS.items():
            violations = getattr(row, f"{name}_violations", 0) or 0
            total_violations += violations
            if violations > 0:
                result.by_feature[name] = {
                    'violations': violations,
                    'min': min_val,
                    'max': max_val,
                }

        result.out_of_bounds = total_violations
        if result.total_checked > 0:
            result.out_of_bounds_pct = 100.0 * total_violations / result.total_checked

        if result.out_of_bounds_pct == 0:
            result.status = CheckStatus.PASS
        elif result.out_of_bounds_pct < 1.0:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"Some features out of bounds: {result.out_of_bounds_pct:.2f}%"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"HIGH: {result.out_of_bounds_pct:.2f}% features out of bounds"
            )

    except Exception as e:
        logger.error(f"Error checking feature bounds: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def check_prop_line_coverage(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
) -> PropLineCoverageResult:
    """
    Check prop line coverage and quality.

    Validates that predictions have real prop lines (not placeholders).
    """
    result = PropLineCoverageResult()

    query = f"""
    SELECT
        game_date,
        COUNT(*) as total,
        COUNTIF(line_value IS NOT NULL AND line_value > 0) as with_line,
        COUNTIF(line_value IS NULL OR line_value = 0) as without_line,
        COUNTIF(line_value = {PLACEHOLDER_LINE_VALUE}) as placeholder_lines
    FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
    WHERE game_date BETWEEN @start_date AND @end_date
    GROUP BY game_date
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
            timeout=BQ_QUERY_TIMEOUT_SECONDS
        )

        total_pred = 0
        total_with_line = 0
        total_placeholder = 0

        for row in query_result:
            total_pred += row.total
            total_with_line += row.with_line
            total_placeholder += row.placeholder_lines

            if row.total > 0:
                coverage = 100.0 * row.with_line / row.total
                result.by_date[str(row.game_date)] = coverage

        result.total_predictions = total_pred
        result.with_prop_line = total_with_line
        result.without_prop_line = total_pred - total_with_line
        result.placeholder_lines = total_placeholder

        if total_pred > 0:
            result.coverage_pct = 100.0 * total_with_line / total_pred

        if result.coverage_pct >= PROP_LINE_COVERAGE_THRESHOLD:
            result.status = CheckStatus.PASS
        elif result.coverage_pct >= 30:
            result.status = CheckStatus.WARN
            result.issues.append(
                f"Low prop line coverage: {result.coverage_pct:.1f}%"
            )
        else:
            result.status = CheckStatus.FAIL
            result.issues.append(
                f"CRITICAL: Very low prop line coverage: {result.coverage_pct:.1f}%"
            )

        if total_placeholder > 0:
            result.issues.append(
                f"{total_placeholder} predictions have placeholder line value ({PLACEHOLDER_LINE_VALUE})"
            )

    except Exception as e:
        logger.error(f"Error checking prop line coverage: {e}", exc_info=True)
        result.status = CheckStatus.ERROR
        result.issues.append(f"Query error: {str(e)}")

    return result


def validate_feature_store(
    client: Optional[bigquery.Client] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    days: int = 7,
    check_consistency: bool = True,
    check_dups: bool = True,
    check_arrays: bool = True,
    check_bounds: bool = True,
    check_prop_lines: bool = True,
) -> FeatureStoreValidationResult:
    """
    Run complete feature store validation.

    Args:
        client: BigQuery client (created if not provided)
        start_date: Start of date range (defaults to end_date - days)
        end_date: End of date range (defaults to yesterday)
        days: Number of days to check if start_date not provided
        check_consistency: Whether to check L5/L10 consistency
        check_dups: Whether to check for duplicates
        check_arrays: Whether to check array integrity
        check_bounds: Whether to check feature value bounds
        check_prop_lines: Whether to check prop line coverage

    Returns:
        FeatureStoreValidationResult with all check results
    """
    start_time = datetime.now()

    # Default dates
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    if start_date is None:
        start_date = end_date - timedelta(days=days)

    result = FeatureStoreValidationResult(
        start_date=start_date,
        end_date=end_date,
    )

    # Create client if needed
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    # Run checks
    if check_consistency:
        result.consistency = check_feature_cache_consistency(client, start_date, end_date)
        if result.consistency.status in (CheckStatus.FAIL, CheckStatus.ERROR):
            result.passed = False
            result.issues.extend(result.consistency.issues)
        elif result.consistency.status == CheckStatus.WARN:
            result.warnings.extend(result.consistency.issues)

    if check_dups:
        result.duplicates = check_duplicates(client, start_date, end_date)
        if result.duplicates.status in (CheckStatus.FAIL, CheckStatus.ERROR):
            result.passed = False
            result.issues.extend(result.duplicates.issues)

    if check_arrays:
        result.array_integrity = check_array_integrity(client, start_date, end_date)
        if result.array_integrity.status in (CheckStatus.FAIL, CheckStatus.ERROR):
            result.passed = False
            result.issues.extend(result.array_integrity.issues)

    if check_bounds:
        result.feature_bounds = check_feature_bounds(client, start_date, end_date)
        if result.feature_bounds.status in (CheckStatus.FAIL, CheckStatus.ERROR):
            result.passed = False
            result.issues.extend(result.feature_bounds.issues)
        elif result.feature_bounds.status == CheckStatus.WARN:
            result.warnings.extend(result.feature_bounds.issues)

    if check_prop_lines:
        result.prop_line_coverage = check_prop_line_coverage(client, start_date, end_date)
        if result.prop_line_coverage.status in (CheckStatus.FAIL, CheckStatus.ERROR):
            result.passed = False
            result.issues.extend(result.prop_line_coverage.issues)
        elif result.prop_line_coverage.status == CheckStatus.WARN:
            result.warnings.extend(result.prop_line_coverage.issues)

    result.validation_time_seconds = (datetime.now() - start_time).total_seconds()

    return result


def validate_after_backfill(
    client: Optional[bigquery.Client] = None,
    backfill_start: date = None,
    backfill_end: date = None,
) -> Tuple[bool, str]:
    """
    Convenience function to validate feature store after a backfill.

    Args:
        client: BigQuery client
        backfill_start: Start date of backfill
        backfill_end: End date of backfill

    Returns:
        Tuple of (passed: bool, summary: str)
    """
    result = validate_feature_store(
        client=client,
        start_date=backfill_start,
        end_date=backfill_end,
    )

    return result.passed, result.summary


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for feature store validation."""
    parser = argparse.ArgumentParser(description="Validate feature store data integrity")
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD), defaults to yesterday",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to check (used if start-date not provided)",
    )
    parser.add_argument(
        "--consistency-only",
        action="store_true",
        help="Only run consistency check",
    )
    parser.add_argument(
        "--duplicates-only",
        action="store_true",
        help="Only run duplicate check",
    )
    parser.add_argument(
        "--arrays-only",
        action="store_true",
        help="Only run array integrity check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Exit with code 1 if validation fails",
    )

    args = parser.parse_args()

    # Parse dates
    start_date = None
    end_date = None
    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    if args.end_date:
        end_date = date.fromisoformat(args.end_date)

    # Determine which checks to run
    check_all = not (args.consistency_only or args.duplicates_only or args.arrays_only)

    # Run validation
    result = validate_feature_store(
        start_date=start_date,
        end_date=end_date,
        days=args.days,
        check_consistency=check_all or args.consistency_only,
        check_dups=check_all or args.duplicates_only,
        check_arrays=check_all or args.arrays_only,
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
            'validation_time_seconds': result.validation_time_seconds,
        }
        if result.consistency:
            output['consistency'] = {
                'status': result.consistency.status.value,
                'l5_match_pct': result.consistency.l5_match_pct,
                'l10_match_pct': result.consistency.l10_match_pct,
                'total_records': result.consistency.total_records,
                'by_month': result.consistency.by_month,
                'mismatched_samples': result.consistency.mismatched_samples,
            }
        if result.duplicates:
            output['duplicates'] = {
                'status': result.duplicates.status.value,
                'feature_store': result.duplicates.feature_store_duplicates,
                'cache': result.duplicates.cache_duplicates,
                'predictions': result.duplicates.predictions_duplicates,
            }
        if result.array_integrity:
            output['array_integrity'] = {
                'status': result.array_integrity.status.value,
                'total_checked': result.array_integrity.total_checked,
                'null_arrays': result.array_integrity.null_arrays,
                'wrong_length': result.array_integrity.wrong_length,
                'nan_inf_values': result.array_integrity.nan_values,
            }
        print(json.dumps(output, indent=2))
    else:
        print(result.summary)

    # Exit code for CI
    if args.ci and not result.passed:
        exit(1)


if __name__ == "__main__":
    main()
