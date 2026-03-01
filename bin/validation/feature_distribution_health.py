#!/usr/bin/env python3
"""
Feature Distribution Health Validator
======================================

Audits ALL ML feature store features for distribution anomalies that
existing quality checks miss. Catches "plausible but wrong" bugs like
Feature 41 (spread_magnitude) being ALL ZEROS for 4 months.

5 checks per feature:
  1. Constant-value detection (stddev + distinct count)
  2. Zero-rate anomaly (zero% vs expected)
  3. NULL-rate anomaly (null% vs expected)
  4. Distribution drift (current vs 4-week baseline)
  5. Source cross-validation (sample-check raw tables for key features)

Usage:
  python bin/validation/feature_distribution_health.py --date 2026-02-28
  python bin/validation/feature_distribution_health.py --date 2026-02-28 --verbose
  python bin/validation/feature_distribution_health.py --date 2026-02-28 --lookback 3

Created: Session 375 — After Feature 41 (spread_magnitude) ALL ZEROS bug
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from google.cloud import bigquery

# ============================================================================
# Per-feature health profiles
# ============================================================================
# Maps feature index -> profile dict:
#   name: human-readable name
#   dead: True if feature is known dead/unused (skip all checks)
#   expected_zero_pct: fraction of records expected to be zero (0.0 = none, 0.99 = almost all)
#   min_stddev: minimum expected stddev (below this = constant-value bug)
#   min_distinct: minimum expected distinct values
#   source_table: raw table for cross-validation (optional)
#   source_column: column name in source table (optional)

FEATURE_PROFILES = {
    # 0-4: Recent Performance
    0: {"name": "points_avg_last_5", "min_stddev": 3.0, "min_distinct": 20, "expected_zero_pct": 0.05},
    1: {"name": "points_avg_last_10", "min_stddev": 3.0, "min_distinct": 20, "expected_zero_pct": 0.05},
    2: {"name": "points_avg_season", "min_stddev": 3.0, "min_distinct": 20, "expected_zero_pct": 0.05},
    3: {"name": "points_std_last_10", "min_stddev": 1.0, "min_distinct": 10, "expected_zero_pct": 0.15},
    4: {"name": "games_in_last_7_days", "min_stddev": 0.3, "min_distinct": 3, "expected_zero_pct": 0.10},

    # 5-8: Composite Factors
    5: {"name": "fatigue_score", "min_stddev": 5.0, "min_distinct": 10, "expected_zero_pct": 0.05},
    6: {"name": "shot_zone_mismatch_score", "min_stddev": 1.0, "min_distinct": 10, "expected_zero_pct": 0.10},
    7: {"name": "pace_score", "min_stddev": 0.5, "min_distinct": 10, "expected_zero_pct": 0.15},
    8: {"name": "usage_spike_score", "min_stddev": 0.0, "min_distinct": 1, "expected_zero_pct": 0.95},  # Collapses to ~0 in Feb+ (Session 370 adversarial validation — seasonal pattern, not a bug)

    # 9-12: Derived Factors
    9: {"name": "rest_advantage", "min_stddev": 0.3, "min_distinct": 5, "expected_zero_pct": 0.50},
    10: {"name": "injury_risk", "min_stddev": 0.1, "min_distinct": 3, "expected_zero_pct": 0.70},
    11: {"name": "recent_trend", "min_stddev": 0.2, "min_distinct": 5, "expected_zero_pct": 0.45},  # Many players have 0 trend
    12: {"name": "minutes_change", "min_stddev": 0.1, "min_distinct": 5, "expected_zero_pct": 0.65},  # Many players have stable minutes

    # 13-17: Matchup Context
    13: {"name": "opponent_def_rating", "min_stddev": 1.0, "min_distinct": 5, "expected_zero_pct": 0.01},
    14: {"name": "opponent_pace", "min_stddev": 0.5, "min_distinct": 5, "expected_zero_pct": 0.01},
    15: {"name": "home_away", "min_stddev": 0.3, "min_distinct": 2, "expected_zero_pct": 0.45},
    16: {"name": "back_to_back", "min_stddev": 0.1, "min_distinct": 2, "expected_zero_pct": 0.70},
    17: {"name": "playoff_game", "dead": True},  # Always 0 during regular season

    # 18-21: Shot Zones
    18: {"name": "pct_paint", "min_stddev": 0.05, "min_distinct": 10, "expected_zero_pct": 0.05},
    19: {"name": "pct_mid_range", "min_stddev": 0.03, "min_distinct": 10, "expected_zero_pct": 0.15},
    20: {"name": "pct_three", "min_stddev": 0.05, "min_distinct": 10, "expected_zero_pct": 0.05},
    21: {"name": "pct_free_throw", "min_stddev": 0.02, "min_distinct": 10, "expected_zero_pct": 0.15},

    # 22-24: Team Context
    22: {"name": "team_pace", "min_stddev": 0.5, "min_distinct": 5, "expected_zero_pct": 0.01},
    23: {"name": "team_off_rating", "min_stddev": 1.0, "min_distinct": 5, "expected_zero_pct": 0.01},
    24: {"name": "team_win_pct", "min_stddev": 0.05, "min_distinct": 5, "expected_zero_pct": 0.01},

    # 25-28: Vegas Lines
    25: {
        "name": "vegas_points_line", "min_stddev": 2.0, "min_distinct": 10,
        "expected_zero_pct": 0.40, "expected_null_pct": 0.55,  # Many players lack vegas lines
        "source_table": "nba_analytics.upcoming_player_game_context",
        "source_column": "current_points_line",
    },
    26: {"name": "vegas_opening_line", "min_stddev": 2.0, "min_distinct": 10, "expected_zero_pct": 0.40, "expected_null_pct": 0.55},
    27: {"name": "vegas_line_move", "min_stddev": 0.2, "min_distinct": 5, "expected_zero_pct": 0.50, "expected_null_pct": 0.55},
    28: {"name": "has_vegas_line", "min_stddev": 0.3, "min_distinct": 2, "expected_zero_pct": 0.55},

    # 29-30: Opponent History
    29: {"name": "avg_points_vs_opponent", "min_stddev": 2.0, "min_distinct": 10, "expected_zero_pct": 0.30},
    30: {"name": "games_vs_opponent", "min_stddev": 0.5, "min_distinct": 3, "expected_zero_pct": 0.20},

    # 31-32: Minutes/Efficiency
    31: {"name": "minutes_avg_last_10", "min_stddev": 5.0, "min_distinct": 15, "expected_zero_pct": 0.05},
    32: {"name": "ppm_avg_last_10", "min_stddev": 0.1, "min_distinct": 10, "expected_zero_pct": 0.10},

    # 33: DNP Risk
    33: {"name": "dnp_rate", "min_stddev": 0.05, "min_distinct": 3, "expected_zero_pct": 0.60},

    # 34-36: Player Trajectory
    34: {"name": "pts_slope_10g", "min_stddev": 0.2, "min_distinct": 10, "expected_zero_pct": 0.10},
    35: {"name": "pts_vs_season_zscore", "min_stddev": 0.3, "min_distinct": 10, "expected_zero_pct": 0.10},
    36: {"name": "breakout_flag", "min_stddev": 0.05, "min_distinct": 2, "expected_zero_pct": 0.90},

    # 37-38: V11 Features
    37: {"name": "star_teammates_out", "min_stddev": 0.3, "min_distinct": 3, "expected_zero_pct": 0.60},
    38: {"name": "game_total_line", "min_stddev": 2.0, "min_distinct": 5, "expected_zero_pct": 0.01},

    # 39-53: V12 Features
    39: {"name": "days_rest", "min_stddev": 0.3, "min_distinct": 3, "expected_zero_pct": 0.10},
    40: {"name": "minutes_load_last_7d", "min_stddev": 10.0, "min_distinct": 15, "expected_zero_pct": 0.10},
    41: {
        "name": "spread_magnitude", "min_stddev": 1.0, "min_distinct": 5,
        "expected_zero_pct": 0.05,  # Would have caught the ALL ZEROS bug
        "source_table": "nba_raw.odds_api_event_odds",
        "source_column": "outcome_point",
    },
    42: {
        "name": "implied_team_total", "min_stddev": 2.0, "min_distinct": 5,
        "expected_zero_pct": 0.01,
        "source_table": "nba_raw.odds_api_event_odds",
        "source_column": "outcome_point",
    },
    43: {"name": "points_avg_last_3", "min_stddev": 3.0, "min_distinct": 15, "expected_zero_pct": 0.05},
    44: {"name": "scoring_trend_slope", "min_stddev": 0.3, "min_distinct": 10, "expected_zero_pct": 0.15},
    45: {"name": "deviation_from_avg_last3", "min_stddev": 0.3, "min_distinct": 10, "expected_zero_pct": 0.15},
    46: {"name": "consecutive_games_below_avg", "min_stddev": 0.5, "min_distinct": 3, "expected_zero_pct": 0.40},
    47: {"name": "teammate_usage_available", "min_stddev": 2.0, "min_distinct": 10, "expected_zero_pct": 0.05, "expected_null_pct": 0.40},
    48: {"name": "usage_rate_last_5", "min_stddev": 2.0, "min_distinct": 10, "expected_zero_pct": 0.05},
    49: {"name": "games_since_structural_change", "min_stddev": 3.0, "min_distinct": 5, "expected_zero_pct": 0.20},
    50: {"name": "multi_book_line_std", "min_stddev": 0.1, "min_distinct": 3, "expected_zero_pct": 0.30, "expected_null_pct": 0.60},
    51: {"name": "prop_over_streak", "min_stddev": 0.5, "min_distinct": 3, "expected_zero_pct": 0.75},  # Most players at 0 (no streak)
    52: {"name": "prop_under_streak", "min_stddev": 0.5, "min_distinct": 3, "expected_zero_pct": 0.75},
    53: {"name": "line_vs_season_avg", "min_stddev": 1.0, "min_distinct": 10, "expected_zero_pct": 0.20, "expected_null_pct": 0.55},
    54: {"name": "prop_line_delta", "min_stddev": 0.3, "min_distinct": 5, "expected_zero_pct": 0.30, "expected_null_pct": 0.60},

    # 55-56: V16 Features
    55: {"name": "over_rate_last_10", "min_stddev": 0.1, "min_distinct": 5, "expected_zero_pct": 0.15, "expected_null_pct": 0.35},
    56: {"name": "margin_vs_line_avg_last_5", "min_stddev": 1.0, "min_distinct": 10, "expected_zero_pct": 0.15, "expected_null_pct": 0.35},
}

# Number of features to check (matches v2_57features schema)
MAX_FEATURE_INDEX = 56


def build_current_stats_query(target_date: str, lookback_days: int) -> str:
    """Build BQ query for current period feature stats."""
    feature_selects = []
    for idx in range(MAX_FEATURE_INDEX + 1):
        col = f"feature_{idx}_value"
        feature_selects.append(f"""
        STRUCT(
            {idx} AS idx,
            AVG({col}) AS mean_val,
            STDDEV({col}) AS stddev_val,
            COUNT(DISTINCT ROUND({col}, 4)) AS distinct_count,
            COUNTIF({col} IS NULL) AS null_count,
            COUNTIF({col} = 0) AS zero_count,
            COUNT(*) AS total_count,
            MIN({col}) AS min_val,
            MAX({col}) AS max_val
        ) AS f_{idx}""")

    return f"""
    SELECT
        {','.join(feature_selects)}
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days} DAY)
      AND game_date <= DATE('{target_date}')
    """


def build_baseline_stats_query(target_date: str, lookback_days: int) -> str:
    """Build BQ query for baseline period feature stats (4 weeks before current window)."""
    baseline_selects = []
    for idx in range(MAX_FEATURE_INDEX + 1):
        col = f"feature_{idx}_value"
        baseline_selects.append(f"""
        STRUCT(
            {idx} AS idx,
            AVG({col}) AS mean_val,
            STDDEV({col}) AS stddev_val
        ) AS f_{idx}""")

    return f"""
    SELECT
        {','.join(baseline_selects)}
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days + 28} DAY)
      AND game_date < DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days} DAY)
    """


def evaluate_feature(idx: int, current_stats: dict, baseline_stats: dict, verbose: bool) -> list:
    """Evaluate a single feature against its health profile. Returns list of (severity, message)."""
    profile = FEATURE_PROFILES.get(idx)
    if profile is None:
        return []

    name = profile.get("name", f"feature_{idx}")

    # Skip dead features
    if profile.get("dead", False):
        if verbose:
            return [("SKIP", f"Feature {idx} ({name}): Dead feature, skipped")]
        return []

    results = []
    total = current_stats.get("total_count", 0)
    if total == 0:
        results.append(("FAIL", f"Feature {idx} ({name}): No records found"))
        return results

    stddev = current_stats.get("stddev_val")
    distinct = current_stats.get("distinct_count", 0)
    null_count = current_stats.get("null_count", 0)
    zero_count = current_stats.get("zero_count", 0)
    mean_val = current_stats.get("mean_val")
    min_val = current_stats.get("min_val")
    max_val = current_stats.get("max_val")

    null_pct = null_count / total if total > 0 else 0
    zero_pct = zero_count / total if total > 0 else 0

    min_stddev = profile.get("min_stddev", 0)
    min_distinct = profile.get("min_distinct", 2)
    expected_zero_pct = profile.get("expected_zero_pct", 0.10)

    # Check 1: Constant-value detection
    effective_stddev = stddev if stddev is not None else 0
    if effective_stddev < min_stddev and distinct < min_distinct:
        results.append((
            "FAIL",
            f"Feature {idx} ({name}): CONSTANT VALUE - stddev={effective_stddev:.4f} "
            f"(min={min_stddev}), distinct={distinct} (min={min_distinct}), "
            f"range=[{min_val}, {max_val}]"
        ))
    elif effective_stddev < min_stddev:
        results.append((
            "WARN",
            f"Feature {idx} ({name}): Low variance - stddev={effective_stddev:.4f} "
            f"(min={min_stddev}), distinct={distinct}"
        ))

    # Check 2: Zero-rate anomaly
    if zero_pct > expected_zero_pct + 0.20:
        severity = "FAIL" if zero_pct > expected_zero_pct + 0.40 else "WARN"
        results.append((
            severity,
            f"Feature {idx} ({name}): Zero rate {zero_pct:.1%} "
            f"(expected ~{expected_zero_pct:.0%}, threshold +20pp)"
        ))

    # Check 3: NULL-rate anomaly
    expected_null_pct = profile.get("expected_null_pct", 0.30)
    if null_pct > expected_null_pct + 0.10:
        severity = "FAIL" if null_pct > expected_null_pct + 0.25 else "WARN"
        results.append((
            severity,
            f"Feature {idx} ({name}): NULL rate {null_pct:.1%} ({null_count}/{total}), "
            f"expected ~{expected_null_pct:.0%}"
        ))

    # Check 4: Distribution drift vs baseline
    if baseline_stats and baseline_stats.get("stddev_val") and baseline_stats["stddev_val"] > 0:
        bl_mean = baseline_stats.get("mean_val", 0) or 0
        bl_stddev = baseline_stats["stddev_val"]
        current_mean = mean_val if mean_val is not None else 0

        if bl_stddev > 0:
            z_shift = abs(current_mean - bl_mean) / bl_stddev
            if z_shift > 3.0:
                results.append((
                    "WARN",
                    f"Feature {idx} ({name}): Distribution drift - "
                    f"mean shifted {z_shift:.1f} sigma "
                    f"(current={current_mean:.3f}, baseline={bl_mean:.3f}, "
                    f"baseline_std={bl_stddev:.3f})"
                ))

    # If all passed and verbose
    if not results and verbose:
        results.append((
            "PASS",
            f"Feature {idx} ({name}): OK "
            f"(stddev={effective_stddev:.3f}, distinct={distinct}, "
            f"zero={zero_pct:.1%}, null={null_pct:.1%})"
        ))

    return results


def run_source_cross_validation(client: bigquery.Client, target_date: str, lookback_days: int, verbose: bool) -> list:
    """Check 5: Cross-validate key features against raw source tables."""
    results = []

    # Feature 41: spread_magnitude vs odds_api spreads
    query_41 = f"""
    WITH feature_store AS (
        SELECT
            game_date,
            AVG(feature_41_value) AS avg_spread_mag,
            COUNTIF(feature_41_value = 0) AS zero_count,
            COUNT(*) AS total
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days} DAY)
          AND game_date <= DATE('{target_date}')
          AND feature_41_value IS NOT NULL
        GROUP BY game_date
    ),
    raw_spreads AS (
        SELECT
            game_date,
            AVG(ABS(outcome_point)) AS avg_raw_spread
        FROM `nba-props-platform.nba_raw.odds_api_game_lines`
        WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days} DAY)
          AND game_date <= DATE('{target_date}')
          AND market_key = 'spreads'
          AND outcome_point IS NOT NULL
          AND outcome_point <= 0
        GROUP BY game_date
    )
    SELECT
        f.game_date,
        f.avg_spread_mag,
        r.avg_raw_spread,
        f.zero_count,
        f.total
    FROM feature_store f
    LEFT JOIN raw_spreads r ON f.game_date = r.game_date
    ORDER BY f.game_date DESC
    LIMIT 5
    """
    try:
        rows = list(client.query(query_41).result())
        for row in rows:
            if row.avg_spread_mag is not None and row.avg_raw_spread is not None:
                diff = abs(row.avg_spread_mag - row.avg_raw_spread)
                if diff > 3.0:
                    results.append((
                        "FAIL",
                        f"Feature 41 (spread_magnitude) source mismatch on {row.game_date}: "
                        f"feature_store avg={row.avg_spread_mag:.2f}, "
                        f"raw_spreads avg={row.avg_raw_spread:.2f}, diff={diff:.2f}"
                    ))
                elif verbose:
                    results.append((
                        "PASS",
                        f"Feature 41 (spread_magnitude) source OK on {row.game_date}: "
                        f"feature={row.avg_spread_mag:.2f}, raw={row.avg_raw_spread:.2f}"
                    ))

            if row.zero_count == row.total and row.total > 0:
                results.append((
                    "FAIL",
                    f"Feature 41 (spread_magnitude) ALL ZEROS on {row.game_date} "
                    f"({row.total} records)"
                ))
    except Exception as e:
        results.append(("WARN", f"Feature 41 source check failed: {e}"))

    # Feature 25: vegas_points_line vs upcoming_player_game_context
    query_25 = f"""
    WITH fs AS (
        SELECT
            AVG(feature_25_value) AS avg_line,
            COUNTIF(feature_25_value > 0) AS has_line_count,
            COUNT(*) AS total
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days} DAY)
          AND game_date <= DATE('{target_date}')
    ),
    raw AS (
        SELECT
            COUNTIF(current_points_line IS NOT NULL AND current_points_line > 0) AS has_line_count,
            COUNT(*) AS total
        FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(DATE('{target_date}'), INTERVAL {lookback_days} DAY)
          AND game_date <= DATE('{target_date}')
    )
    SELECT
        fs.avg_line AS fs_avg_line,
        fs.has_line_count AS fs_has_line,
        fs.total AS fs_total,
        raw.has_line_count AS raw_has_line,
        raw.total AS raw_total
    FROM fs, raw
    """
    try:
        rows = list(client.query(query_25).result())
        if rows:
            row = rows[0]
            if row.fs_total > 0 and row.raw_total > 0:
                fs_pct = row.fs_has_line / row.fs_total
                raw_pct = row.raw_has_line / row.raw_total
                if abs(fs_pct - raw_pct) > 0.15:
                    results.append((
                        "WARN",
                        f"Feature 25 (vegas_points_line) coverage mismatch: "
                        f"feature_store={fs_pct:.1%} ({row.fs_has_line}/{row.fs_total}), "
                        f"raw={raw_pct:.1%} ({row.raw_has_line}/{row.raw_total})"
                    ))
                elif verbose:
                    results.append((
                        "PASS",
                        f"Feature 25 (vegas_points_line) source OK: "
                        f"feature_store={fs_pct:.1%}, raw={raw_pct:.1%}"
                    ))
    except Exception as e:
        results.append(("WARN", f"Feature 25 source check failed: {e}"))

    return results


def parse_stats_row(row, idx: int) -> dict:
    """Extract stats for a feature index from a query result row."""
    field_name = f"f_{idx}"
    struct = getattr(row, field_name, None)
    if struct is None:
        return {}
    return {
        "mean_val": struct.get("mean_val") if isinstance(struct, dict) else getattr(struct, "mean_val", None),
        "stddev_val": struct.get("stddev_val") if isinstance(struct, dict) else getattr(struct, "stddev_val", None),
        "distinct_count": struct.get("distinct_count") if isinstance(struct, dict) else getattr(struct, "distinct_count", None),
        "null_count": struct.get("null_count") if isinstance(struct, dict) else getattr(struct, "null_count", None),
        "zero_count": struct.get("zero_count") if isinstance(struct, dict) else getattr(struct, "zero_count", None),
        "total_count": struct.get("total_count") if isinstance(struct, dict) else getattr(struct, "total_count", None),
        "min_val": struct.get("min_val") if isinstance(struct, dict) else getattr(struct, "min_val", None),
        "max_val": struct.get("max_val") if isinstance(struct, dict) else getattr(struct, "max_val", None),
    }


def parse_baseline_row(row, idx: int) -> dict:
    """Extract baseline stats for a feature index."""
    field_name = f"f_{idx}"
    struct = getattr(row, field_name, None)
    if struct is None:
        return {}
    return {
        "mean_val": struct.get("mean_val") if isinstance(struct, dict) else getattr(struct, "mean_val", None),
        "stddev_val": struct.get("stddev_val") if isinstance(struct, dict) else getattr(struct, "stddev_val", None),
    }


def main():
    parser = argparse.ArgumentParser(description="Feature Distribution Health Validator")
    parser.add_argument("--date", type=str, default=None, help="Target date (YYYY-MM-DD). Default: today")
    parser.add_argument("--lookback", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--verbose", action="store_true", help="Show PASS results too")
    args = parser.parse_args()

    target_date = args.date or date.today().isoformat()
    lookback_days = args.lookback
    verbose = args.verbose

    print(f"=== Feature Distribution Health Check ===")
    print(f"Date: {target_date} (lookback: {lookback_days} days)")
    print(f"Baseline: {lookback_days+1}-{lookback_days+28} days prior")
    print()

    client = bigquery.Client(project="nba-props-platform")

    # Run current period stats query
    print("Querying current period statistics...")
    current_query = build_current_stats_query(target_date, lookback_days)
    current_rows = list(client.query(current_query).result())

    if not current_rows:
        print("ERROR: No current period data found")
        sys.exit(1)

    current_row = current_rows[0]

    # Run baseline period stats query
    print("Querying baseline period statistics...")
    baseline_query = build_baseline_stats_query(target_date, lookback_days)
    baseline_rows = list(client.query(baseline_query).result())
    baseline_row = baseline_rows[0] if baseline_rows else None

    # Evaluate each feature
    all_results = []
    fail_count = 0
    warn_count = 0
    pass_count = 0
    skip_count = 0

    for idx in range(MAX_FEATURE_INDEX + 1):
        current_stats = parse_stats_row(current_row, idx)
        baseline_stats = parse_baseline_row(baseline_row, idx) if baseline_row else {}

        feature_results = evaluate_feature(idx, current_stats, baseline_stats, verbose)

        for severity, message in feature_results:
            all_results.append((severity, message))
            if severity == "FAIL":
                fail_count += 1
            elif severity == "WARN":
                warn_count += 1
            elif severity == "PASS":
                pass_count += 1
            elif severity == "SKIP":
                skip_count += 1

    # Run source cross-validation
    print("Running source cross-validation...")
    source_results = run_source_cross_validation(client, target_date, lookback_days, verbose)
    for severity, message in source_results:
        all_results.append((severity, message))
        if severity == "FAIL":
            fail_count += 1
        elif severity == "WARN":
            warn_count += 1
        elif severity == "PASS":
            pass_count += 1

    # Print results
    print()
    print("=" * 70)

    # Print FAILs first
    fails = [(s, m) for s, m in all_results if s == "FAIL"]
    if fails:
        print("\nFAILURES:")
        for _, msg in fails:
            print(f"  FAIL  {msg}")

    # Print WARNs
    warns = [(s, m) for s, m in all_results if s == "WARN"]
    if warns:
        print("\nWARNINGS:")
        for _, msg in warns:
            print(f"  WARN  {msg}")

    # Print PASSes if verbose
    if verbose:
        passes = [(s, m) for s, m in all_results if s == "PASS"]
        if passes:
            print("\nPASSED:")
            for _, msg in passes:
                print(f"  PASS  {msg}")

        skips = [(s, m) for s, m in all_results if s == "SKIP"]
        if skips:
            print("\nSKIPPED:")
            for _, msg in skips:
                print(f"  SKIP  {msg}")

    # Summary
    total_checked = MAX_FEATURE_INDEX + 1 - skip_count
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {total_checked} features checked, "
          f"{fail_count} FAIL, {warn_count} WARN, {skip_count} SKIP")

    if fail_count > 0:
        print("\nSTATUS: FAIL - Feature distribution anomalies detected")
        print("ACTION: Investigate failures above. Constant-value bugs need immediate fix + backfill.")
        sys.exit(1)
    elif warn_count > 0:
        print("\nSTATUS: WARN - Minor anomalies detected, review recommended")
        sys.exit(0)
    else:
        print("\nSTATUS: PASS - All features healthy")
        sys.exit(0)


if __name__ == "__main__":
    main()
