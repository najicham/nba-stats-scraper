"""
Feature Drift Detector

Monitors ML feature distributions over time to detect data quality issues early.
Compares feature statistics (mean, std, percentiles) between time periods.

Drift detection catches issues like:
- Data source changes affecting feature values
- Bug introductions causing systematic shifts
- Schema changes affecting feature calculations
- Upstream data quality degradation

Usage:
    # CLI
    python -m shared.validation.feature_drift_detector --days 14

    # In code
    from shared.validation.feature_drift_detector import detect_feature_drift

    result = detect_feature_drift(client, current_week, previous_week)
    if result.has_drift:
        print(result.drifted_features)
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import logging
import argparse
import statistics

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID, BQ_QUERY_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

FEATURE_STORE_TABLE = "nba_predictions.ml_feature_store_v2"

# Feature names for the 34-element feature array
# (indices 0-33)
FEATURE_NAMES = [
    "points_l5_avg",           # 0
    "points_l10_avg",          # 1
    "rebounds_l5_avg",         # 2
    "rebounds_l10_avg",        # 3
    "assists_l5_avg",          # 4
    "assists_l10_avg",         # 5
    "minutes_l5_avg",          # 6
    "minutes_l10_avg",         # 7
    "fg_pct_l5",               # 8
    "fg_pct_l10",              # 9
    "fg3_pct_l5",              # 10
    "fg3_pct_l10",             # 11
    "ft_pct_l5",               # 12
    "ft_pct_l10",              # 13
    "usage_rate_l5",           # 14
    "usage_rate_l10",          # 15
    "days_rest",               # 16
    "is_home",                 # 17
    "opp_def_rating",          # 18
    "opp_pace",                # 19
    "team_pace",               # 20
    "season_games_played",     # 21
    "career_ppg",              # 22
    "age",                     # 23
    "height_inches",           # 24
    "weight_lbs",              # 25
    "experience_years",        # 26
    "position_encoded",        # 27
    "back_to_back",            # 28
    "games_last_7d",           # 29
    "points_variance_l10",     # 30
    "line_value",              # 31
    "line_movement",           # 32
    "prop_confidence",         # 33
]

# Key features to monitor for drift (most important for predictions)
KEY_FEATURES = [0, 1, 6, 7, 14, 15, 18, 19, 21, 22, 30, 31]

# Drift thresholds
MEAN_DRIFT_THRESHOLD = 0.15  # 15% change in mean
STD_DRIFT_THRESHOLD = 0.25   # 25% change in std
PERCENTILE_DRIFT_THRESHOLD = 0.20  # 20% change in percentiles


# =============================================================================
# RESULT DATA CLASSES
# =============================================================================

class DriftSeverity(Enum):
    """Severity of detected drift."""
    NONE = 'none'
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'


@dataclass
class FeatureStats:
    """Statistics for a single feature."""
    feature_idx: int
    feature_name: str
    count: int = 0
    mean: float = 0.0
    std: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    null_count: int = 0


@dataclass
class FeatureDrift:
    """Drift detection result for a single feature."""
    feature_idx: int
    feature_name: str
    current_mean: float
    previous_mean: float
    mean_change_pct: float
    current_std: float
    previous_std: float
    std_change_pct: float
    severity: DriftSeverity = DriftSeverity.NONE
    issues: List[str] = field(default_factory=list)


@dataclass
class DriftDetectionResult:
    """Complete drift detection result."""
    current_period: Tuple[date, date]
    previous_period: Tuple[date, date]
    has_drift: bool = False
    total_features_checked: int = 0
    features_with_drift: int = 0
    critical_drifts: int = 0
    high_drifts: int = 0
    medium_drifts: int = 0
    drifted_features: List[FeatureDrift] = field(default_factory=list)
    all_features: List[FeatureDrift] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "Feature Drift Detection Report",
            f"Current period: {self.current_period[0]} to {self.current_period[1]}",
            f"Previous period: {self.previous_period[0]} to {self.previous_period[1]}",
            "",
            f"Overall: {'DRIFT DETECTED' if self.has_drift else 'NO SIGNIFICANT DRIFT'}",
            f"Features checked: {self.total_features_checked}",
            f"Features with drift: {self.features_with_drift}",
            f"  Critical: {self.critical_drifts}",
            f"  High: {self.high_drifts}",
            f"  Medium: {self.medium_drifts}",
            "",
        ]

        if self.drifted_features:
            lines.append("Drifted Features:")
            for drift in sorted(self.drifted_features, key=lambda x: x.severity.value, reverse=True):
                lines.append(
                    f"  [{drift.severity.value.upper()}] {drift.feature_name}: "
                    f"mean {drift.previous_mean:.2f} -> {drift.current_mean:.2f} "
                    f"({drift.mean_change_pct:+.1f}%)"
                )

        if self.issues:
            lines.append("")
            lines.append("Issues:")
            for issue in self.issues:
                lines.append(f"  - {issue}")

        return "\n".join(lines)


# =============================================================================
# DETECTION FUNCTIONS
# =============================================================================

def get_feature_stats(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
    feature_indices: List[int] = None,
) -> Dict[int, FeatureStats]:
    """
    Get statistics for features in the specified date range.
    """
    if feature_indices is None:
        feature_indices = KEY_FEATURES

    stats = {}

    for idx in feature_indices:
        feature_name = FEATURE_NAMES[idx] if idx < len(FEATURE_NAMES) else f"feature_{idx}"

        query = f"""
        SELECT
            COUNT(*) as cnt,
            AVG(feature_{idx}_value) as mean_val,
            STDDEV(feature_{idx}_value) as std_val,
            MIN(feature_{idx}_value) as min_val,
            MAX(feature_{idx}_value) as max_val,
            APPROX_QUANTILES(feature_{idx}_value, 4)[OFFSET(1)] as p25,
            APPROX_QUANTILES(feature_{idx}_value, 4)[OFFSET(2)] as p50,
            APPROX_QUANTILES(feature_{idx}_value, 4)[OFFSET(3)] as p75,
            COUNTIF(feature_{idx}_value IS NULL) as null_cnt
        FROM `{PROJECT_ID}.{FEATURE_STORE_TABLE}`
        WHERE game_date BETWEEN @start_date AND @end_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        try:
            result = client.query(query, job_config=job_config).result(
                timeout=BQ_QUERY_TIMEOUT_SECONDS
            )
            row = next(iter(result))

            stats[idx] = FeatureStats(
                feature_idx=idx,
                feature_name=feature_name,
                count=row.cnt or 0,
                mean=row.mean_val or 0.0,
                std=row.std_val or 0.0,
                min_val=row.min_val or 0.0,
                max_val=row.max_val or 0.0,
                p25=row.p25 or 0.0,
                p50=row.p50 or 0.0,
                p75=row.p75 or 0.0,
                null_count=row.null_cnt or 0,
            )
        except Exception as e:
            logger.warning(f"Error getting stats for feature {idx}: {e}")
            stats[idx] = FeatureStats(feature_idx=idx, feature_name=feature_name)

    return stats


def calculate_drift(
    current_stats: Dict[int, FeatureStats],
    previous_stats: Dict[int, FeatureStats],
) -> List[FeatureDrift]:
    """
    Calculate drift between two sets of feature statistics.
    """
    drifts = []

    for idx in current_stats:
        if idx not in previous_stats:
            continue

        current = current_stats[idx]
        previous = previous_stats[idx]

        # Skip if no data
        if current.count == 0 or previous.count == 0:
            continue

        # Calculate changes
        mean_change_pct = 0.0
        if previous.mean != 0:
            mean_change_pct = 100.0 * (current.mean - previous.mean) / abs(previous.mean)
        elif current.mean != 0:
            mean_change_pct = 100.0  # From 0 to non-zero is 100% change

        std_change_pct = 0.0
        if previous.std != 0:
            std_change_pct = 100.0 * (current.std - previous.std) / abs(previous.std)

        # Determine severity
        severity = DriftSeverity.NONE
        issues = []

        abs_mean_change = abs(mean_change_pct)
        abs_std_change = abs(std_change_pct)

        if abs_mean_change > 50 or abs_std_change > 75:
            severity = DriftSeverity.CRITICAL
            issues.append(f"Critical drift: mean changed {mean_change_pct:+.1f}%")
        elif abs_mean_change > 30 or abs_std_change > 50:
            severity = DriftSeverity.HIGH
            issues.append(f"High drift: mean changed {mean_change_pct:+.1f}%")
        elif abs_mean_change > MEAN_DRIFT_THRESHOLD * 100 or abs_std_change > STD_DRIFT_THRESHOLD * 100:
            severity = DriftSeverity.MEDIUM
            issues.append(f"Medium drift: mean changed {mean_change_pct:+.1f}%")
        elif abs_mean_change > 10 or abs_std_change > 15:
            severity = DriftSeverity.LOW

        drifts.append(FeatureDrift(
            feature_idx=idx,
            feature_name=current.feature_name,
            current_mean=current.mean,
            previous_mean=previous.mean,
            mean_change_pct=mean_change_pct,
            current_std=current.std,
            previous_std=previous.std,
            std_change_pct=std_change_pct,
            severity=severity,
            issues=issues,
        ))

    return drifts


def detect_feature_drift(
    client: Optional[bigquery.Client] = None,
    current_start: Optional[date] = None,
    current_end: Optional[date] = None,
    previous_start: Optional[date] = None,
    previous_end: Optional[date] = None,
    days: int = 7,
    feature_indices: List[int] = None,
) -> DriftDetectionResult:
    """
    Detect feature drift between two time periods.

    By default, compares the last `days` to the previous `days`.
    """
    # Default to comparing last week vs previous week
    if current_end is None:
        current_end = date.today() - timedelta(days=1)
    if current_start is None:
        current_start = current_end - timedelta(days=days - 1)
    if previous_end is None:
        previous_end = current_start - timedelta(days=1)
    if previous_start is None:
        previous_start = previous_end - timedelta(days=days - 1)

    if feature_indices is None:
        feature_indices = KEY_FEATURES

    result = DriftDetectionResult(
        current_period=(current_start, current_end),
        previous_period=(previous_start, previous_end),
    )

    # Create client if needed
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    # Get stats for both periods
    current_stats = get_feature_stats(client, current_start, current_end, feature_indices)
    previous_stats = get_feature_stats(client, previous_start, previous_end, feature_indices)

    # Calculate drift
    drifts = calculate_drift(current_stats, previous_stats)
    result.all_features = drifts
    result.total_features_checked = len(drifts)

    # Categorize drifts
    for drift in drifts:
        if drift.severity != DriftSeverity.NONE:
            result.drifted_features.append(drift)
            result.has_drift = True

            if drift.severity == DriftSeverity.CRITICAL:
                result.critical_drifts += 1
                result.issues.extend(drift.issues)
            elif drift.severity == DriftSeverity.HIGH:
                result.high_drifts += 1
                result.issues.extend(drift.issues)
            elif drift.severity == DriftSeverity.MEDIUM:
                result.medium_drifts += 1
                result.warnings.extend(drift.issues)

    result.features_with_drift = len(result.drifted_features)

    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for feature drift detection."""
    parser = argparse.ArgumentParser(description="Detect feature drift in ML feature store")
    parser.add_argument("--days", type=int, default=7, help="Days per comparison period")
    parser.add_argument("--all-features", action="store_true", help="Check all 34 features")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--ci", action="store_true", help="Exit with code 1 if critical drift")

    args = parser.parse_args()

    feature_indices = None
    if args.all_features:
        feature_indices = list(range(len(FEATURE_NAMES)))

    result = detect_feature_drift(days=args.days, feature_indices=feature_indices)

    if args.json:
        import json
        output = {
            'has_drift': result.has_drift,
            'current_period': [str(d) for d in result.current_period],
            'previous_period': [str(d) for d in result.previous_period],
            'features_with_drift': result.features_with_drift,
            'critical_drifts': result.critical_drifts,
            'high_drifts': result.high_drifts,
            'issues': result.issues,
            'drifted_features': [
                {
                    'feature': d.feature_name,
                    'severity': d.severity.value,
                    'mean_change_pct': d.mean_change_pct,
                }
                for d in result.drifted_features
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(result.summary)

    if args.ci and result.critical_drifts > 0:
        exit(1)


if __name__ == "__main__":
    main()
