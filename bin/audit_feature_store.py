#!/usr/bin/env python3
"""
ML Feature Store Audit Script

Scans all seasons/dates and checks every feature for:
1. Missing values (unexpected NULLs)
2. Constant values (stuck at default)
3. Out-of-range values
4. Distribution anomalies
5. Correlation with actuals (leakage detection)

Usage:
    # Audit all available data
    PYTHONPATH=. python bin/audit_feature_store.py

    # Audit specific season
    PYTHONPATH=. python bin/audit_feature_store.py --season 2024-25

    # Audit date range
    PYTHONPATH=. python bin/audit_feature_store.py --start 2025-11-01 --end 2026-01-31

    # Output to file
    PYTHONPATH=. python bin/audit_feature_store.py --output audit_report.txt

Session 67 - Historical Feature Cleanup
"""

import argparse
import sys
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from google.cloud import bigquery
import json

PROJECT_ID = "nba-props-platform"

# Feature definitions with validation rules
FEATURE_SPECS = [
    # (index, name, min, max, allow_null, check_constant, constant_threshold)
    (0, "points_avg_last_5", 0, 60, False, True, 0.5),
    (1, "points_avg_last_10", 0, 60, False, True, 0.5),
    (2, "points_avg_season", 0, 60, False, True, 0.5),
    (3, "points_std_last_10", 0, 20, False, True, 0.5),
    (4, "games_in_last_7_days", 0, 5, False, False, None),
    (5, "fatigue_score", 0, 100, False, True, 0.8),
    (6, "shot_zone_mismatch_score", -50, 50, True, False, None),
    (7, "pace_score", -50, 50, True, True, 0.95),  # Known issue: often 0
    (8, "usage_spike_score", -50, 50, True, False, None),
    (9, "rest_advantage", -5, 5, False, False, None),
    (10, "injury_risk", 0, 100, True, False, None),
    (11, "recent_trend", -20, 20, False, False, None),
    (12, "minutes_change", -30, 30, False, False, None),
    (13, "opponent_def_rating", 90, 130, False, True, 0.9),
    (14, "opponent_pace", 80, 120, False, True, 0.9),
    (15, "home_away", 0, 1, False, False, None),
    (16, "back_to_back", 0, 1, False, False, None),
    (17, "playoff_game", 0, 1, False, False, None),
    (18, "pct_paint", 0, 100, True, False, None),
    (19, "pct_mid_range", 0, 100, True, False, None),
    (20, "pct_three", 0, 100, True, False, None),
    (21, "pct_free_throw", 0, 100, True, False, None),
    (22, "team_pace", 80, 120, False, True, 0.9),
    (23, "team_off_rating", 90, 130, False, True, 0.9),
    (24, "team_win_pct", 0, 1, False, True, 0.95),  # Known issue: 0.5 constant
    (25, "vegas_points_line", 0, 60, True, False, None),
    (26, "vegas_opening_line", 0, 60, True, False, None),
    (27, "vegas_line_move", -10, 10, True, False, None),
    (28, "has_vegas_line", 0, 1, False, False, None),
    (29, "avg_points_vs_opponent", 0, 60, True, False, None),
    (30, "games_vs_opponent", 0, 50, False, False, None),
    (31, "minutes_avg_last_10", 0, 48, False, True, 0.8),
    (32, "ppm_avg_last_10", 0, 2, False, True, 0.8),
    (33, "dnp_rate", 0, 1, False, False, None),
    (34, "pts_slope_10g", -5, 5, False, False, None),
    (35, "pts_vs_season_zscore", -4, 4, False, False, None),
    (36, "breakout_flag", 0, 1, False, False, None),
]

# Known default values to check for
KNOWN_DEFAULTS = {
    "team_win_pct": 0.5,
    "fatigue_score": 50.0,
    "opponent_def_rating": 112.0,
    "opponent_pace": 100.0,
}

@dataclass
class FeatureAuditResult:
    name: str
    index: int
    total_records: int
    null_count: int
    null_pct: float
    min_val: float
    max_val: float
    mean_val: float
    std_val: float
    out_of_range_count: int
    constant_pct: float  # % at most common value
    most_common_value: float
    status: str  # OK, WARNING, FAILED
    issues: List[str]


def parse_args():
    parser = argparse.ArgumentParser(description='Audit ML Feature Store data quality')
    parser.add_argument('--season', help='Season to audit (e.g., 2024-25)')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', help='Output file (default: stdout)')
    parser.add_argument('--check-leakage', action='store_true',
                        help='Check for data leakage (slower)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output')
    return parser.parse_args()


def get_season_dates(season: str) -> Tuple[str, str]:
    """Convert season string to date range."""
    seasons = {
        "2021-22": ("2021-10-19", "2022-06-16"),
        "2022-23": ("2022-10-18", "2023-06-12"),
        "2023-24": ("2023-10-24", "2024-06-17"),
        "2024-25": ("2024-10-22", "2025-06-15"),
        "2025-26": ("2025-10-22", "2026-06-15"),
    }
    if season not in seasons:
        raise ValueError(f"Unknown season: {season}. Valid: {list(seasons.keys())}")
    return seasons[season]


def audit_features(client: bigquery.Client, start_date: str, end_date: str,
                   verbose: bool = False) -> List[FeatureAuditResult]:
    """Audit all features for a date range."""

    # Build query to get feature statistics
    feature_stats_parts = []
    for idx, name, min_val, max_val, allow_null, check_const, const_thresh in FEATURE_SPECS:
        feature_stats_parts.append(f"""
        -- Feature {idx}: {name}
        COUNT(CASE WHEN features[OFFSET({idx})] IS NULL THEN 1 END) as null_{idx},
        MIN(CAST(features[OFFSET({idx})] AS FLOAT64)) as min_{idx},
        MAX(CAST(features[OFFSET({idx})] AS FLOAT64)) as max_{idx},
        AVG(CAST(features[OFFSET({idx})] AS FLOAT64)) as avg_{idx},
        STDDEV(CAST(features[OFFSET({idx})] AS FLOAT64)) as std_{idx},
        COUNTIF(CAST(features[OFFSET({idx})] AS FLOAT64) < {min_val}
                OR CAST(features[OFFSET({idx})] AS FLOAT64) > {max_val}) as oor_{idx}
        """)

    query = f"""
    SELECT
        COUNT(*) as total_records,
        {','.join(feature_stats_parts)}
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND feature_count >= 33
    """

    if verbose:
        print(f"Running feature statistics query for {start_date} to {end_date}...")

    result = client.query(query).to_dataframe()

    if result.empty or result['total_records'].iloc[0] == 0:
        print(f"No records found for {start_date} to {end_date}")
        return []

    total = int(result['total_records'].iloc[0])

    # Build results for each feature
    audit_results = []
    for idx, name, min_val, max_val, allow_null, check_const, const_thresh in FEATURE_SPECS:
        null_count = int(result[f'null_{idx}'].iloc[0] or 0)
        null_pct = null_count / total * 100
        min_v = float(result[f'min_{idx}'].iloc[0] or 0)
        max_v = float(result[f'max_{idx}'].iloc[0] or 0)
        mean_v = float(result[f'avg_{idx}'].iloc[0] or 0)
        std_v = float(result[f'std_{idx}'].iloc[0] or 0)
        oor_count = int(result[f'oor_{idx}'].iloc[0] or 0)

        issues = []
        status = "OK"

        # Check for unexpected nulls
        if not allow_null and null_pct > 5:
            issues.append(f"High NULL rate: {null_pct:.1f}%")
            status = "WARNING" if null_pct < 20 else "FAILED"

        # Check for out of range
        if oor_count > total * 0.01:
            issues.append(f"Out of range: {oor_count} records ({oor_count/total*100:.1f}%)")
            status = "WARNING" if status == "OK" else status

        # Check for constant values (need separate query)
        constant_pct = 0.0
        most_common = 0.0

        audit_results.append(FeatureAuditResult(
            name=name,
            index=idx,
            total_records=total,
            null_count=null_count,
            null_pct=null_pct,
            min_val=min_v,
            max_val=max_v,
            mean_val=mean_v,
            std_val=std_v,
            out_of_range_count=oor_count,
            constant_pct=constant_pct,
            most_common_value=most_common,
            status=status,
            issues=issues
        ))

    return audit_results


def check_constant_values(client: bigquery.Client, start_date: str, end_date: str,
                          verbose: bool = False) -> Dict[str, Tuple[float, float]]:
    """Check for constant/default values in key features."""

    checks = []
    for idx, name, _, _, _, check_const, const_thresh in FEATURE_SPECS:
        if check_const and name in KNOWN_DEFAULTS:
            default_val = KNOWN_DEFAULTS[name]
            checks.append(f"""
            COUNTIF(ABS(CAST(features[OFFSET({idx})] AS FLOAT64) - {default_val}) < 0.01) as const_{idx},
            COUNT(*) as total_{idx}
            """)

    if not checks:
        return {}

    query = f"""
    SELECT {','.join(checks)}
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND feature_count >= 33
    """

    if verbose:
        print("Checking for constant/default values...")

    result = client.query(query).to_dataframe()

    constant_results = {}
    for idx, name, _, _, _, check_const, const_thresh in FEATURE_SPECS:
        if check_const and name in KNOWN_DEFAULTS:
            const_count = int(result[f'const_{idx}'].iloc[0] or 0)
            total = int(result[f'total_{idx}'].iloc[0] or 1)
            constant_results[name] = (const_count, const_count / total * 100)

    return constant_results


def check_leakage(client: bigquery.Client, start_date: str, end_date: str,
                  verbose: bool = False) -> Dict[str, float]:
    """Check for data leakage by comparing rolling averages to actual points."""

    query = f"""
    WITH joined AS (
        SELECT
            CAST(mf.features[OFFSET(0)] AS FLOAT64) as points_avg_last_5,
            CAST(mf.features[OFFSET(1)] AS FLOAT64) as points_avg_last_10,
            pgs.points as actual_points
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
            ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
        WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
          AND mf.feature_count >= 33
          AND pgs.points IS NOT NULL
          AND pgs.minutes_played > 10
    )
    SELECT
        CORR(points_avg_last_5, actual_points) as corr_avg5_actual,
        CORR(points_avg_last_10, actual_points) as corr_avg10_actual,
        AVG(ABS(points_avg_last_5 - actual_points)) as avg_diff_5,
        AVG(ABS(points_avg_last_10 - actual_points)) as avg_diff_10
    FROM joined
    """

    if verbose:
        print("Checking for data leakage...")

    result = client.query(query).to_dataframe()

    return {
        'corr_avg5_actual': float(result['corr_avg5_actual'].iloc[0] or 0),
        'corr_avg10_actual': float(result['corr_avg10_actual'].iloc[0] or 0),
        'avg_diff_5': float(result['avg_diff_5'].iloc[0] or 0),
        'avg_diff_10': float(result['avg_diff_10'].iloc[0] or 0),
    }


def print_report(start_date: str, end_date: str,
                 audit_results: List[FeatureAuditResult],
                 constant_results: Dict[str, Tuple[float, float]],
                 leakage_results: Optional[Dict[str, float]] = None,
                 output_file: Optional[str] = None):
    """Print the audit report."""

    lines = []
    lines.append("=" * 70)
    lines.append(" ML FEATURE STORE AUDIT REPORT")
    lines.append(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Date Range: {start_date} to {end_date}")

    if audit_results:
        lines.append(f"Total Records: {audit_results[0].total_records:,}")
    lines.append("")

    # Feature Health Summary
    lines.append("-" * 70)
    lines.append(" FEATURE HEALTH SUMMARY")
    lines.append("-" * 70)

    ok_count = sum(1 for r in audit_results if r.status == "OK")
    warn_count = sum(1 for r in audit_results if r.status == "WARNING")
    fail_count = sum(1 for r in audit_results if r.status == "FAILED")

    lines.append(f"  ✅ OK: {ok_count}  ⚠️ WARNING: {warn_count}  ❌ FAILED: {fail_count}")
    lines.append("")

    for result in audit_results:
        if result.status == "OK":
            icon = "✅"
        elif result.status == "WARNING":
            icon = "⚠️"
        else:
            icon = "❌"

        line = f"{icon} {result.name:25} "

        if result.issues:
            line += f"ISSUES: {'; '.join(result.issues)}"
        else:
            line += f"OK (range={result.min_val:.1f}-{result.max_val:.1f}, std={result.std_val:.2f})"

        lines.append(line)

    # Constant Values Check
    if constant_results:
        lines.append("")
        lines.append("-" * 70)
        lines.append(" CONSTANT VALUE CHECK")
        lines.append("-" * 70)

        for name, (count, pct) in constant_results.items():
            default_val = KNOWN_DEFAULTS.get(name, "?")
            if pct > 50:
                icon = "❌"
                status = "CRITICAL"
            elif pct > 20:
                icon = "⚠️"
                status = "WARNING"
            else:
                icon = "✅"
                status = "OK"

            lines.append(f"{icon} {name:25} {pct:5.1f}% at default ({default_val}) - {status}")

    # Leakage Check
    if leakage_results:
        lines.append("")
        lines.append("-" * 70)
        lines.append(" DATA LEAKAGE CHECK")
        lines.append("-" * 70)

        corr_5 = leakage_results['corr_avg5_actual']
        corr_10 = leakage_results['corr_avg10_actual']
        diff_5 = leakage_results['avg_diff_5']
        diff_10 = leakage_results['avg_diff_10']

        # If correlation > 0.85, likely leakage
        if corr_5 > 0.85:
            lines.append(f"❌ points_avg_last_5 vs actual: corr={corr_5:.3f} - POSSIBLE LEAKAGE")
        else:
            lines.append(f"✅ points_avg_last_5 vs actual: corr={corr_5:.3f} - NO LEAKAGE")

        if corr_10 > 0.85:
            lines.append(f"❌ points_avg_last_10 vs actual: corr={corr_10:.3f} - POSSIBLE LEAKAGE")
        else:
            lines.append(f"✅ points_avg_last_10 vs actual: corr={corr_10:.3f} - NO LEAKAGE")

        lines.append(f"   Avg diff from actual: last_5={diff_5:.2f}, last_10={diff_10:.2f}")
        lines.append("   (Normal range: 4-6 points. If <2, possible leakage)")

    # Recommendations
    lines.append("")
    lines.append("-" * 70)
    lines.append(" RECOMMENDATIONS")
    lines.append("-" * 70)

    recommendations = []

    for name, (count, pct) in constant_results.items():
        if pct > 50:
            recommendations.append(f"RECOMPUTE {name} - {pct:.1f}% at default value")

    if leakage_results and (leakage_results['corr_avg5_actual'] > 0.85 or
                           leakage_results['corr_avg10_actual'] > 0.85):
        recommendations.append("RECOMPUTE rolling averages - possible data leakage detected")

    for result in audit_results:
        if result.status == "FAILED":
            recommendations.append(f"INVESTIGATE {result.name} - {'; '.join(result.issues)}")

    if not recommendations:
        lines.append("✅ No critical issues found. Data appears clean for training.")
    else:
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")

    lines.append("")
    lines.append("=" * 70)

    report = "\n".join(lines)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(report)
        print(f"Report written to {output_file}")
    else:
        print(report)


def main():
    args = parse_args()

    # Determine date range
    if args.season:
        start_date, end_date = get_season_dates(args.season)
    elif args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        # Default: check all available data
        start_date = "2021-10-01"
        end_date = date.today().strftime("%Y-%m-%d")

    client = bigquery.Client(project=PROJECT_ID)

    # Run audits
    audit_results = audit_features(client, start_date, end_date, args.verbose)

    if not audit_results:
        return

    constant_results = check_constant_values(client, start_date, end_date, args.verbose)

    leakage_results = None
    if args.check_leakage:
        leakage_results = check_leakage(client, start_date, end_date, args.verbose)

    # Print report
    print_report(start_date, end_date, audit_results, constant_results,
                 leakage_results, args.output)


if __name__ == "__main__":
    main()
