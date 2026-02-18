#!/usr/bin/env python3
"""
Model Drift Detection System

Monitors prediction performance and player behavior patterns to detect
when model accuracy starts degrading. Provides early warning signals
before drift causes significant losses.

Signals monitored:
1. Rolling hit rate (7-day, 14-day)
2. Star player performance deviation
3. Surprise game percentage (>10pt swing from L5 avg)
4. Prediction error distribution shifts

Usage:
    PYTHONPATH=. python bin/monitoring/model_drift_detection.py

    # Check specific date range
    PYTHONPATH=. python bin/monitoring/model_drift_detection.py \
        --start-date 2026-01-01 --end-date 2026-01-30

    # JSON output for automation
    PYTHONPATH=. python bin/monitoring/model_drift_detection.py --json
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import datetime, timedelta
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"


def get_rolling_hit_rate(client: bigquery.Client, end_date: str = None) -> dict:
    """Calculate rolling hit rates for different windows."""
    date_filter = f"AND game_date <= '{end_date}'" if end_date else ""

    query = f"""
    WITH daily_stats AS (
      SELECT
        game_date,
        COUNT(*) as total_bets,
        COUNTIF(prediction_correct) as correct_bets,
        ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
      FROM nba_predictions.prediction_accuracy
      WHERE system_id = 'catboost_v8'
        AND ABS(predicted_points - line_value) >= 3  -- 3+ edge only
        {date_filter}
      GROUP BY game_date
    )
    SELECT
      -- 7-day rolling
      (SELECT ROUND(100.0 * SUM(correct_bets) / SUM(total_bets), 1)
       FROM daily_stats
       WHERE game_date >= DATE_SUB((SELECT MAX(game_date) FROM daily_stats), INTERVAL 7 DAY)) as hit_rate_7d,
      (SELECT SUM(total_bets)
       FROM daily_stats
       WHERE game_date >= DATE_SUB((SELECT MAX(game_date) FROM daily_stats), INTERVAL 7 DAY)) as bets_7d,

      -- 14-day rolling
      (SELECT ROUND(100.0 * SUM(correct_bets) / SUM(total_bets), 1)
       FROM daily_stats
       WHERE game_date >= DATE_SUB((SELECT MAX(game_date) FROM daily_stats), INTERVAL 14 DAY)) as hit_rate_14d,
      (SELECT SUM(total_bets)
       FROM daily_stats
       WHERE game_date >= DATE_SUB((SELECT MAX(game_date) FROM daily_stats), INTERVAL 14 DAY)) as bets_14d,

      -- 30-day rolling
      (SELECT ROUND(100.0 * SUM(correct_bets) / SUM(total_bets), 1)
       FROM daily_stats
       WHERE game_date >= DATE_SUB((SELECT MAX(game_date) FROM daily_stats), INTERVAL 30 DAY)) as hit_rate_30d,
      (SELECT SUM(total_bets)
       FROM daily_stats
       WHERE game_date >= DATE_SUB((SELECT MAX(game_date) FROM daily_stats), INTERVAL 30 DAY)) as bets_30d,

      -- Breakeven threshold
      52.4 as breakeven_threshold
    """
    result = list(client.query(query).result())[0]

    return {
        "7_day": {
            "hit_rate": float(result.hit_rate_7d) if result.hit_rate_7d else None,
            "bets": int(result.bets_7d) if result.bets_7d else 0,
            "status": "ALERT" if result.hit_rate_7d and result.hit_rate_7d < 52.4 else "OK"
        },
        "14_day": {
            "hit_rate": float(result.hit_rate_14d) if result.hit_rate_14d else None,
            "bets": int(result.bets_14d) if result.bets_14d else 0,
            "status": "ALERT" if result.hit_rate_14d and result.hit_rate_14d < 52.4 else "OK"
        },
        "30_day": {
            "hit_rate": float(result.hit_rate_30d) if result.hit_rate_30d else None,
            "bets": int(result.bets_30d) if result.bets_30d else 0,
            "status": "ALERT" if result.hit_rate_30d and result.hit_rate_30d < 52.4 else "OK"
        },
        "breakeven_threshold": 52.4
    }


def get_star_performance_deviation(client: bigquery.Client, end_date: str = None) -> dict:
    """Check if star players are underperforming their season averages."""
    date_filter = f"AND game_date <= '{end_date}'" if end_date else ""

    query = f"""
    WITH star_players AS (
      -- Identify star players (avg 22+ ppg this season)
      SELECT player_lookup
      FROM nba_analytics.player_game_summary
      WHERE game_date >= '2025-10-01'
        AND minutes_played > 20
      GROUP BY player_lookup
      HAVING AVG(points) >= 22
    ),
    recent_star_games AS (
      -- Last 14 days of star player games
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.points as actual_points,
        mf.feature_1_value as points_avg_last_10  -- Individual column for points_avg_last_10
      FROM nba_analytics.player_game_summary pgs
      INNER JOIN star_players sp ON pgs.player_lookup = sp.player_lookup
      LEFT JOIN nba_predictions.ml_feature_store_v2 mf
        ON pgs.player_lookup = mf.player_lookup AND pgs.game_date = mf.game_date
      WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
        {date_filter}
        AND pgs.minutes_played > 10
    )
    SELECT
      COUNT(*) as star_games,
      ROUND(AVG(actual_points), 1) as avg_actual,
      ROUND(AVG(CAST(points_avg_last_10 AS FLOAT64)), 1) as avg_expected,
      ROUND(AVG(actual_points) - AVG(CAST(points_avg_last_10 AS FLOAT64)), 2) as deviation,
      COUNTIF(actual_points < CAST(points_avg_last_10 AS FLOAT64) - 5) as underperformed_5plus
    FROM recent_star_games
    WHERE points_avg_last_10 IS NOT NULL
    """
    result = list(client.query(query).result())[0]

    deviation = float(result.deviation) if result.deviation else 0
    underperformed_pct = (int(result.underperformed_5plus or 0) / int(result.star_games or 1)) * 100

    return {
        "star_games": int(result.star_games or 0),
        "avg_actual": float(result.avg_actual) if result.avg_actual else None,
        "avg_expected": float(result.avg_expected) if result.avg_expected else None,
        "deviation": deviation,
        "underperformed_5plus_pct": round(underperformed_pct, 1),
        "status": "ALERT" if deviation < -2.0 else "OK"  # Stars underperforming by 2+ pts
    }


def get_surprise_game_rate(client: bigquery.Client, end_date: str = None) -> dict:
    """Calculate percentage of games with >10pt swing from L5 average."""
    date_filter = f"AND game_date <= '{end_date}'" if end_date else ""

    query = f"""
    WITH recent_games AS (
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.points as actual_points,
        mf.feature_0_value as points_avg_last_5  -- Individual column for points_avg_last_5
      FROM nba_analytics.player_game_summary pgs
      LEFT JOIN nba_predictions.ml_feature_store_v2 mf
        ON pgs.player_lookup = mf.player_lookup AND pgs.game_date = mf.game_date
      WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
        {date_filter}
        AND pgs.minutes_played > 10
        AND mf.feature_0_value IS NOT NULL
    )
    SELECT
      COUNT(*) as total_games,
      COUNTIF(ABS(actual_points - CAST(points_avg_last_5 AS FLOAT64)) > 10) as surprise_games,
      ROUND(100.0 * COUNTIF(ABS(actual_points - CAST(points_avg_last_5 AS FLOAT64)) > 10) / COUNT(*), 1) as surprise_pct,
      -- Compare to baseline (8% is normal based on historical data)
      8.0 as baseline_pct
    FROM recent_games
    """
    result = list(client.query(query).result())[0]

    surprise_pct = float(result.surprise_pct) if result.surprise_pct else 0

    return {
        "total_games": int(result.total_games or 0),
        "surprise_games": int(result.surprise_games or 0),
        "surprise_pct": surprise_pct,
        "baseline_pct": 8.0,
        "status": "ALERT" if surprise_pct > 12.0 else "OK"  # 50% above baseline is concerning
    }


def get_prediction_error_distribution(client: bigquery.Client, end_date: str = None) -> dict:
    """Analyze prediction error distribution for shifts."""
    date_filter = f"AND game_date <= '{end_date}'" if end_date else ""

    query = f"""
    WITH errors AS (
      SELECT
        game_date,
        (predicted_points - actual_points) as error,  -- Positive = overpredicted
        ABS(predicted_points - actual_points) as abs_error
      FROM nba_predictions.prediction_accuracy
      WHERE system_id = 'catboost_v8'
        AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
        {date_filter}
    ),
    stats AS (
      SELECT
        COUNT(*) as predictions,
        ROUND(AVG(error), 2) as mean_error,  -- Bias direction
        ROUND(AVG(abs_error), 2) as mae,
        ROUND(STDDEV(error), 2) as error_std,
        COUNTIF(error > 5) as overpredicted_5plus,
        COUNTIF(error < -5) as underpredicted_5plus
      FROM errors
    ),
    percentiles AS (
      SELECT
        ROUND(APPROX_QUANTILES(abs_error, 100)[OFFSET(50)], 2) as median_abs_error,
        ROUND(APPROX_QUANTILES(abs_error, 100)[OFFSET(90)], 2) as p90_abs_error
      FROM errors
    )
    SELECT s.*, p.median_abs_error, p.p90_abs_error
    FROM stats s, percentiles p
    """
    result = list(client.query(query).result())[0]

    mean_error = float(result.mean_error) if result.mean_error else 0
    mae = float(result.mae) if result.mae else 0

    return {
        "predictions": int(result.predictions or 0),
        "mean_error": mean_error,  # Positive = overpredicting
        "mae": mae,
        "error_std": float(result.error_std) if result.error_std else None,
        "overpredicted_5plus": int(result.overpredicted_5plus or 0),
        "underpredicted_5plus": int(result.underpredicted_5plus or 0),
        "median_abs_error": float(result.median_abs_error) if result.median_abs_error else None,
        "p90_abs_error": float(result.p90_abs_error) if result.p90_abs_error else None,
        "bias_direction": "OVER" if mean_error > 0.5 else "UNDER" if mean_error < -0.5 else "NEUTRAL",
        "status": "ALERT" if mae > 5.5 or abs(mean_error) > 1.0 else "OK"
    }


def get_tier_performance(client: bigquery.Client, end_date: str = None) -> dict:
    """Check performance by player tier."""
    date_filter = f"AND pa.game_date <= '{end_date}'" if end_date else ""

    query = f"""
    WITH player_tiers AS (
      SELECT player_lookup,
        CASE
          WHEN AVG(points) >= 22 THEN 'Star'
          WHEN AVG(points) >= 14 THEN 'Starter'
          WHEN AVG(points) >= 6 THEN 'Rotation'
          ELSE 'Bench'
        END as tier
      FROM nba_analytics.player_game_summary
      WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
      GROUP BY player_lookup
    )
    SELECT
      pt.tier,
      COUNT(*) as bets,
      ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate,
      ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)), 2) as mae
    FROM nba_predictions.prediction_accuracy pa
    INNER JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
    WHERE pa.system_id = 'catboost_v8'
      AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
      AND ABS(pa.predicted_points - pa.line_value) >= 3
      {date_filter}
    GROUP BY pt.tier
    ORDER BY
      CASE pt.tier
        WHEN 'Star' THEN 1
        WHEN 'Starter' THEN 2
        WHEN 'Rotation' THEN 3
        ELSE 4
      END
    """
    results = list(client.query(query).result())

    tier_data = {}
    for row in results:
        tier_data[row.tier] = {
            "bets": int(row.bets),
            "hit_rate": float(row.hit_rate),
            "mae": float(row.mae),
            "status": "ALERT" if row.hit_rate < 50.0 else "OK"
        }

    return tier_data


def calculate_drift_score(signals: dict) -> dict:
    """Calculate overall drift score and recommendation."""
    alert_count = 0
    total_signals = 0

    # Count alerts from each signal
    if signals.get("rolling_hit_rate"):
        for window in ["7_day", "14_day", "30_day"]:
            if signals["rolling_hit_rate"].get(window, {}).get("status") == "ALERT":
                alert_count += 1
            total_signals += 1

    if signals.get("star_performance", {}).get("status") == "ALERT":
        alert_count += 1
    total_signals += 1

    if signals.get("surprise_rate", {}).get("status") == "ALERT":
        alert_count += 1
    total_signals += 1

    if signals.get("error_distribution", {}).get("status") == "ALERT":
        alert_count += 1
    total_signals += 1

    # Calculate tier alerts
    for tier, data in signals.get("tier_performance", {}).items():
        if data.get("status") == "ALERT":
            alert_count += 1
        total_signals += 1

    # Calculate drift score (0-100)
    drift_score = round((alert_count / total_signals) * 100, 1) if total_signals > 0 else 0

    # Determine recommendation
    if drift_score >= 60:
        recommendation = "URGENT: Significant drift detected. Consider immediate model retraining."
        severity = "CRITICAL"
    elif drift_score >= 40:
        recommendation = "WARNING: Multiple drift signals. Plan for model retraining within 1 week."
        severity = "HIGH"
    elif drift_score >= 20:
        recommendation = "CAUTION: Some drift signals. Monitor closely over next few days."
        severity = "MEDIUM"
    else:
        recommendation = "OK: Model performance within expected range."
        severity = "LOW"

    return {
        "drift_score": drift_score,
        "alerts": alert_count,
        "total_signals": total_signals,
        "severity": severity,
        "recommendation": recommendation
    }


def main():
    parser = argparse.ArgumentParser(description="Model drift detection system")
    parser.add_argument("--start-date", help="Analysis start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Analysis end date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    end_date = args.end_date

    # Collect all signals
    signals = {}

    print("Collecting drift signals...")
    signals["rolling_hit_rate"] = get_rolling_hit_rate(client, end_date)
    signals["star_performance"] = get_star_performance_deviation(client, end_date)
    signals["surprise_rate"] = get_surprise_game_rate(client, end_date)
    signals["error_distribution"] = get_prediction_error_distribution(client, end_date)
    signals["tier_performance"] = get_tier_performance(client, end_date)

    # Calculate overall drift score
    drift_summary = calculate_drift_score(signals)
    signals["summary"] = drift_summary

    # Add metadata
    signals["generated_at"] = datetime.now().isoformat()
    signals["date_range"] = {"end": end_date or "current"}

    if args.json:
        print(json.dumps(signals, indent=2, default=str))
    else:
        print_report(signals)


def print_report(signals: dict):
    """Print human-readable report."""
    print("\n" + "=" * 80)
    print(" MODEL DRIFT DETECTION REPORT")
    print("=" * 80)
    print(f"Generated: {signals['generated_at']}")
    print()

    # Summary
    summary = signals["summary"]
    print(f"DRIFT SCORE: {summary['drift_score']}% ({summary['severity']})")
    print(f"Alerts: {summary['alerts']}/{summary['total_signals']} signals")
    print(f"\nRecommendation: {summary['recommendation']}")

    # Rolling hit rate
    print("\n" + "-" * 40)
    print("ROLLING HIT RATE (3+ Edge)")
    print("-" * 40)
    hr = signals["rolling_hit_rate"]
    for window in ["7_day", "14_day", "30_day"]:
        data = hr[window]
        status_marker = " [ALERT]" if data["status"] == "ALERT" else ""
        print(f"  {window.replace('_', ' ')}: {data['hit_rate']}% ({data['bets']} bets){status_marker}")
    print(f"  Breakeven: {hr['breakeven_threshold']}%")

    # Star performance
    print("\n" + "-" * 40)
    print("STAR PLAYER PERFORMANCE (14-day)")
    print("-" * 40)
    sp = signals["star_performance"]
    status_marker = " [ALERT]" if sp["status"] == "ALERT" else ""
    print(f"  Games: {sp['star_games']}")
    print(f"  Avg actual: {sp['avg_actual']} pts")
    print(f"  Avg expected: {sp['avg_expected']} pts")
    print(f"  Deviation: {sp['deviation']:+.1f} pts{status_marker}")
    print(f"  Underperformed 5+: {sp['underperformed_5plus_pct']}%")

    # Surprise rate
    print("\n" + "-" * 40)
    print("SURPRISE GAME RATE (14-day)")
    print("-" * 40)
    sr = signals["surprise_rate"]
    status_marker = " [ALERT]" if sr["status"] == "ALERT" else ""
    print(f"  Total games: {sr['total_games']}")
    print(f"  Surprise games (>10pt swing): {sr['surprise_games']} ({sr['surprise_pct']}%){status_marker}")
    print(f"  Baseline: {sr['baseline_pct']}%")

    # Error distribution
    print("\n" + "-" * 40)
    print("PREDICTION ERROR DISTRIBUTION (14-day)")
    print("-" * 40)
    ed = signals["error_distribution"]
    status_marker = " [ALERT]" if ed["status"] == "ALERT" else ""
    print(f"  Predictions: {ed['predictions']}")
    print(f"  Mean error: {ed['mean_error']:+.2f} pts ({ed['bias_direction']}){status_marker}")
    print(f"  MAE: {ed['mae']}")
    print(f"  Median abs error: {ed['median_abs_error']}")
    print(f"  90th percentile: {ed['p90_abs_error']}")

    # Tier performance
    print("\n" + "-" * 40)
    print("TIER PERFORMANCE (14-day, 3+ Edge)")
    print("-" * 40)
    for tier, data in signals["tier_performance"].items():
        status_marker = " [ALERT]" if data["status"] == "ALERT" else ""
        print(f"  {tier}: {data['hit_rate']}% ({data['bets']} bets), MAE={data['mae']}{status_marker}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
