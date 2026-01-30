#!/usr/bin/env python3
"""
Daily Prediction Quality Checks

Run this after each game day to check for prediction quality issues:
- Extreme predictions (>55 or <5 points)
- Predictions clamped at 60
- Large deviations from Vegas lines
- Missing or invalid line sources

Usage:
    python monitoring/daily_prediction_quality.py [YYYY-MM-DD]
    python monitoring/daily_prediction_quality.py  # defaults to yesterday
"""

import sys
from datetime import date, timedelta
from google.cloud import bigquery
from typing import Dict, Tuple


def check_daily_quality(game_date: date) -> Tuple[Dict, bool]:
    """
    Run daily quality checks on predictions

    Returns:
        (results dict, passed bool)
    """
    client = bigquery.Client()
    checks = {}
    all_passed = True

    # Check 1: Extreme predictions
    query = f"""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN predicted_points >= 55 THEN 1 ELSE 0 END) as extreme_high,
        SUM(CASE WHEN predicted_points <= 5 THEN 1 ELSE 0 END) as extreme_low
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
    """
    result = list(client.query(query))[0]
    extreme_count = result.extreme_high + result.extreme_low

    status = 'ERROR' if extreme_count > 10 else 'WARNING' if extreme_count > 3 else 'OK'
    if status != 'OK':
        all_passed = False

    checks['extreme_predictions'] = {
        'total': result.total,
        'extreme_high': result.extreme_high,
        'extreme_low': result.extreme_low,
        'status': status,
        'threshold': '<=10 for OK, <=3 for WARNING',
    }

    # Check 2: Clamped at maximum
    query = f"""
    SELECT COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND predicted_points = 60.0
    """
    result = list(client.query(query))[0]

    status = 'ERROR' if result.count > 5 else 'WARNING' if result.count > 0 else 'OK'
    if status == 'ERROR':
        all_passed = False

    checks['clamped_predictions'] = {
        'count': result.count,
        'status': status,
        'threshold': '0 for OK, <=5 for WARNING',
    }

    # Check 3: Average diff from Vegas
    query = f"""
    SELECT
        ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_diff,
        ROUND(AVG(predicted_points - current_points_line), 2) as avg_bias,
        COUNT(*) as with_vegas
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND current_points_line IS NOT NULL
      AND has_prop_line = TRUE
    """
    result = list(client.query(query))[0]

    avg_diff = result.avg_diff or 0
    status = 'ERROR' if avg_diff > 10 else 'WARNING' if avg_diff > 6 else 'OK'
    if status == 'ERROR':
        all_passed = False

    checks['vegas_diff'] = {
        'avg_abs_diff': result.avg_diff,
        'avg_bias': result.avg_bias,
        'predictions_with_vegas': result.with_vegas,
        'status': status,
        'threshold': '<=6 for OK, <=10 for WARNING',
    }

    # Check 4: Line source distribution
    query = f"""
    SELECT
        line_source_api,
        COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
    GROUP BY line_source_api
    """
    results_list = list(client.query(query))
    source_dist = {row.line_source_api or 'NULL': row.count for row in results_list}

    # Check if we have any ODDS_API data
    odds_api_count = source_dist.get('ODDS_API', 0)
    total = sum(source_dist.values())
    odds_api_pct = 100 * odds_api_count / total if total > 0 else 0

    status = 'ERROR' if odds_api_pct < 10 else 'WARNING' if odds_api_pct < 25 else 'OK'
    if status == 'ERROR':
        all_passed = False

    checks['line_source_coverage'] = {
        'distribution': source_dist,
        'odds_api_pct': round(odds_api_pct, 1),
        'status': status,
        'threshold': '>=25% ODDS_API for OK, >=10% for WARNING',
    }

    # Check 5: Has prop line rate
    query = f"""
    SELECT
        SUM(CASE WHEN has_prop_line = TRUE THEN 1 ELSE 0 END) as with_prop,
        COUNT(*) as total
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
    """
    result = list(client.query(query))[0]
    prop_rate = 100 * result.with_prop / result.total if result.total > 0 else 0

    status = 'WARNING' if prop_rate < 30 else 'OK'

    checks['prop_line_coverage'] = {
        'with_prop_line': result.with_prop,
        'total': result.total,
        'rate_pct': round(prop_rate, 1),
        'status': status,
        'threshold': '>=30% for OK',
    }

    # Check 6: Sentinel values (line = 20.0 exactly)
    query = f"""
    SELECT COUNT(*) as count
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND current_points_line = 20.0
    """
    result = list(client.query(query))[0]

    status = 'ERROR' if result.count > 0 else 'OK'
    if status == 'ERROR':
        all_passed = False

    checks['sentinel_values'] = {
        'count': result.count,
        'status': status,
        'note': 'Line=20.0 is a legacy sentinel value, should be 0',
    }

    # Check 7: Top outliers (biggest diffs from Vegas)
    query = f"""
    SELECT
        player_lookup,
        predicted_points,
        current_points_line,
        ROUND(predicted_points - current_points_line, 1) as diff
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = '{game_date}'
      AND system_id = 'catboost_v8'
      AND current_points_line IS NOT NULL
      AND has_prop_line = TRUE
    ORDER BY ABS(predicted_points - current_points_line) DESC
    LIMIT 5
    """
    results_list = list(client.query(query))
    outliers = [
        {
            'player': row.player_lookup,
            'predicted': row.predicted_points,
            'vegas': row.current_points_line,
            'diff': row.diff
        }
        for row in results_list
    ]

    checks['top_outliers'] = {
        'outliers': outliers,
        'status': 'INFO',
    }

    return checks, all_passed


def print_results(game_date: date, checks: Dict, passed: bool):
    """Print formatted results"""
    print(f"\n{'='*60}")
    print(f"Daily Prediction Quality Check - {game_date}")
    print(f"{'='*60}")

    status_emoji = {
        'OK': '✓',
        'WARNING': '⚠',
        'ERROR': '✗',
        'INFO': 'ℹ',
    }

    for check_name, data in checks.items():
        status = data.get('status', 'INFO')
        emoji = status_emoji.get(status, '?')
        print(f"\n[{emoji}] {check_name.upper()} ({status})")

        for key, value in data.items():
            if key == 'status':
                continue
            if isinstance(value, dict):
                print(f"  {key}:")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            elif isinstance(value, list):
                print(f"  {key}:")
                for item in value:
                    if isinstance(item, dict):
                        print(f"    - {item}")
                    else:
                        print(f"    - {item}")
            else:
                print(f"  {key}: {value}")

    print(f"\n{'='*60}")
    overall = "PASSED" if passed else "FAILED"
    emoji = "✓" if passed else "✗"
    print(f"Overall: [{emoji}] {overall}")
    print(f"{'='*60}\n")


def main():
    # Parse date argument
    if len(sys.argv) > 1:
        try:
            game_date = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date format: {sys.argv[1]}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        # Default to yesterday
        game_date = date.today() - timedelta(days=1)

    checks, passed = check_daily_quality(game_date)
    print_results(game_date, checks, passed)

    # Exit with error code if checks failed
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
