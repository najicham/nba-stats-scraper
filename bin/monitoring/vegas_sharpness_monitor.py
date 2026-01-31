#!/usr/bin/env python3
"""
Vegas Line Sharpness Monitor

Tracks how accurate Vegas lines are over time and by player tier.
When Vegas gets sharper (more accurate), it's harder for our model to find edge.

Key Metrics:
1. Vegas MAE by tier - How accurate are Vegas lines?
2. Model vs Vegas - Is our model beating Vegas?
3. Edge availability - How many high-edge opportunities exist?

Usage:
    PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py

    # Specific date range
    PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py \
        --start-date 2025-12-01 --end-date 2026-01-31

    # JSON output for automation
    PYTHONPATH=. python bin/monitoring/vegas_sharpness_monitor.py --json
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
from datetime import datetime
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"


def get_vegas_sharpness_by_tier(client: bigquery.Client, start_date: str = None, end_date: str = None) -> dict:
    """Get Vegas accuracy metrics by player tier."""

    date_filter = ""
    if start_date:
        date_filter += f" AND pa.game_date >= '{start_date}'"
    if end_date:
        date_filter += f" AND pa.game_date <= '{end_date}'"

    query = f"""
    WITH player_tiers AS (
      SELECT
        player_lookup,
        CASE
          WHEN AVG(points) >= 22 THEN 'Star'
          WHEN AVG(points) >= 14 THEN 'Starter'
          WHEN AVG(points) >= 6 THEN 'Rotation'
          ELSE 'Bench'
        END as tier
      FROM nba_analytics.player_game_summary
      WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
        AND minutes_played > 10
      GROUP BY 1
    )
    SELECT
      pt.tier,
      COUNT(*) as games,

      -- Vegas accuracy
      ROUND(AVG(ABS(pa.line_value - pa.actual_points)), 2) as vegas_mae,
      ROUND(STDDEV(pa.line_value - pa.actual_points), 2) as vegas_std,

      -- Model accuracy
      ROUND(AVG(pa.absolute_error), 2) as model_mae,

      -- Comparison
      ROUND(AVG(ABS(pa.line_value - pa.actual_points)) - AVG(pa.absolute_error), 2) as vegas_minus_model,
      ROUND(100.0 * COUNTIF(pa.absolute_error < ABS(pa.line_value - pa.actual_points)) / COUNT(*), 1) as model_beats_vegas_pct,

      -- Vegas precision (within X points)
      ROUND(100.0 * COUNTIF(ABS(pa.line_value - pa.actual_points) <= 3) / COUNT(*), 1) as vegas_within_3pts,
      ROUND(100.0 * COUNTIF(ABS(pa.line_value - pa.actual_points) <= 5) / COUNT(*), 1) as vegas_within_5pts,

      -- Edge availability
      ROUND(100.0 * COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 3) / COUNT(*), 1) as pct_3plus_edge,
      ROUND(100.0 * COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 5) / COUNT(*), 1) as pct_5plus_edge

    FROM nba_predictions.prediction_accuracy pa
    LEFT JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
    WHERE pa.system_id = 'catboost_v8'
      AND pa.line_value IS NOT NULL
      {date_filter}
    GROUP BY 1
    ORDER BY CASE tier WHEN 'Star' THEN 1 WHEN 'Starter' THEN 2 WHEN 'Rotation' THEN 3 ELSE 4 END
    """

    results = list(client.query(query).result())

    tier_data = {}
    for row in results:
        if row.tier is None:
            continue
        tier_data[row.tier] = {
            "games": int(row.games),
            "vegas_mae": float(row.vegas_mae),
            "vegas_std": float(row.vegas_std) if row.vegas_std else None,
            "model_mae": float(row.model_mae),
            "vegas_minus_model": float(row.vegas_minus_model),
            "model_beats_vegas_pct": float(row.model_beats_vegas_pct),
            "vegas_within_3pts": float(row.vegas_within_3pts),
            "vegas_within_5pts": float(row.vegas_within_5pts),
            "pct_3plus_edge": float(row.pct_3plus_edge),
            "pct_5plus_edge": float(row.pct_5plus_edge),
            "status": "SHARP" if row.model_beats_vegas_pct < 45 else "NORMAL" if row.model_beats_vegas_pct < 55 else "SOFT"
        }

    return tier_data


def get_vegas_trend(client: bigquery.Client, months: int = 3) -> dict:
    """Get Vegas sharpness trend over recent months."""

    query = f"""
    WITH player_tiers AS (
      SELECT
        player_lookup,
        CASE
          WHEN AVG(points) >= 22 THEN 'Star'
          WHEN AVG(points) >= 14 THEN 'Starter'
          WHEN AVG(points) >= 6 THEN 'Rotation'
          ELSE 'Bench'
        END as tier
      FROM nba_analytics.player_game_summary
      WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 120 DAY)
        AND minutes_played > 10
      GROUP BY 1
    )
    SELECT
      FORMAT_DATE('%Y-%m', pa.game_date) as month,
      pt.tier,
      COUNT(*) as games,
      ROUND(AVG(ABS(pa.line_value - pa.actual_points)), 2) as vegas_mae,
      ROUND(AVG(pa.absolute_error), 2) as model_mae,
      ROUND(100.0 * COUNTIF(pa.absolute_error < ABS(pa.line_value - pa.actual_points)) / COUNT(*), 1) as model_beats_vegas_pct,
      ROUND(100.0 * COUNTIF(ABS(pa.predicted_points - pa.line_value) >= 3) / COUNT(*), 1) as pct_3plus_edge

    FROM nba_predictions.prediction_accuracy pa
    LEFT JOIN player_tiers pt ON pa.player_lookup = pt.player_lookup
    WHERE pa.system_id = 'catboost_v8'
      AND pa.line_value IS NOT NULL
      AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {months} MONTH)
    GROUP BY 1, 2
    HAVING games >= 20
    ORDER BY 1, CASE tier WHEN 'Star' THEN 1 WHEN 'Starter' THEN 2 WHEN 'Rotation' THEN 3 ELSE 4 END
    """

    results = list(client.query(query).result())

    trend_data = {}
    for row in results:
        if row.tier is None:
            continue
        if row.month not in trend_data:
            trend_data[row.month] = {}
        trend_data[row.month][row.tier] = {
            "games": int(row.games),
            "vegas_mae": float(row.vegas_mae),
            "model_mae": float(row.model_mae),
            "model_beats_vegas_pct": float(row.model_beats_vegas_pct),
            "pct_3plus_edge": float(row.pct_3plus_edge),
        }

    return trend_data


def get_sharpest_lines(client: bigquery.Client, limit: int = 20) -> list:
    """Find players where Vegas is most accurate (hardest to beat)."""

    query = f"""
    SELECT
      pa.player_lookup,
      COUNT(*) as games,
      ROUND(AVG(ABS(pa.line_value - pa.actual_points)), 2) as vegas_mae,
      ROUND(AVG(pa.absolute_error), 2) as model_mae,
      ROUND(100.0 * COUNTIF(pa.absolute_error < ABS(pa.line_value - pa.actual_points)) / COUNT(*), 1) as model_beats_vegas_pct,
      ROUND(AVG(pa.line_value), 1) as avg_line
    FROM nba_predictions.prediction_accuracy pa
    WHERE pa.system_id = 'catboost_v8'
      AND pa.line_value IS NOT NULL
      AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY 1
    HAVING games >= 5
    ORDER BY vegas_mae ASC
    LIMIT {limit}
    """

    results = list(client.query(query).result())
    return [
        {
            "player": row.player_lookup,
            "games": int(row.games),
            "vegas_mae": float(row.vegas_mae),
            "model_mae": float(row.model_mae),
            "model_beats_vegas_pct": float(row.model_beats_vegas_pct),
            "avg_line": float(row.avg_line),
        }
        for row in results
    ]


def get_softest_lines(client: bigquery.Client, limit: int = 20) -> list:
    """Find players where Vegas is least accurate (easiest to beat)."""

    query = f"""
    SELECT
      pa.player_lookup,
      COUNT(*) as games,
      ROUND(AVG(ABS(pa.line_value - pa.actual_points)), 2) as vegas_mae,
      ROUND(AVG(pa.absolute_error), 2) as model_mae,
      ROUND(100.0 * COUNTIF(pa.absolute_error < ABS(pa.line_value - pa.actual_points)) / COUNT(*), 1) as model_beats_vegas_pct,
      ROUND(AVG(pa.line_value), 1) as avg_line
    FROM nba_predictions.prediction_accuracy pa
    WHERE pa.system_id = 'catboost_v8'
      AND pa.line_value IS NOT NULL
      AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY 1
    HAVING games >= 5
    ORDER BY vegas_mae DESC
    LIMIT {limit}
    """

    results = list(client.query(query).result())
    return [
        {
            "player": row.player_lookup,
            "games": int(row.games),
            "vegas_mae": float(row.vegas_mae),
            "model_mae": float(row.model_mae),
            "model_beats_vegas_pct": float(row.model_beats_vegas_pct),
            "avg_line": float(row.avg_line),
        }
        for row in results
    ]


def calculate_sharpness_score(tier_data: dict) -> dict:
    """Calculate overall Vegas sharpness score."""

    total_games = sum(t.get("games", 0) for t in tier_data.values())

    if total_games == 0:
        return {"score": 0, "status": "NO_DATA"}

    # Weighted average of model_beats_vegas_pct (lower = sharper Vegas)
    weighted_sum = sum(
        t.get("model_beats_vegas_pct", 50) * t.get("games", 0)
        for t in tier_data.values()
    )
    avg_model_beats = weighted_sum / total_games

    # Sharpness score: 0 = very sharp (model never beats), 100 = very soft (model always beats)
    sharpness_score = round(avg_model_beats, 1)

    if sharpness_score < 45:
        status = "VERY_SHARP"
        recommendation = "Vegas is very accurate. Raise edge threshold to 5+ or reduce bet size."
    elif sharpness_score < 50:
        status = "SHARP"
        recommendation = "Vegas is sharp. Use only high-confidence (90+) picks."
    elif sharpness_score < 55:
        status = "NORMAL"
        recommendation = "Vegas accuracy is normal. Standard filters apply."
    else:
        status = "SOFT"
        recommendation = "Vegas is less accurate. Good opportunity window."

    return {
        "score": sharpness_score,
        "status": status,
        "total_games": total_games,
        "recommendation": recommendation
    }


def main():
    parser = argparse.ArgumentParser(description="Monitor Vegas line sharpness")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    # Collect metrics
    print("Analyzing Vegas line sharpness...")

    tier_data = get_vegas_sharpness_by_tier(client, args.start_date, args.end_date)
    trend_data = get_vegas_trend(client)
    sharpest = get_sharpest_lines(client, 10)
    softest = get_softest_lines(client, 10)
    sharpness_score = calculate_sharpness_score(tier_data)

    report = {
        "generated_at": datetime.now().isoformat(),
        "date_range": {"start": args.start_date, "end": args.end_date},
        "sharpness_score": sharpness_score,
        "by_tier": tier_data,
        "trend": trend_data,
        "sharpest_lines": sharpest,
        "softest_lines": softest,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)


def print_report(report: dict):
    """Print human-readable report."""

    print("\n" + "=" * 80)
    print(" VEGAS LINE SHARPNESS REPORT")
    print("=" * 80)
    print(f"Generated: {report['generated_at']}")

    # Overall score
    score = report["sharpness_score"]
    print(f"\nOVERALL SHARPNESS: {score['score']}% model beats Vegas ({score['status']})")
    print(f"Recommendation: {score['recommendation']}")

    # By tier
    print("\n" + "-" * 40)
    print("SHARPNESS BY PLAYER TIER")
    print("-" * 40)
    print(f"{'Tier':<10} | {'Games':>6} | {'Vegas MAE':>9} | {'Model MAE':>9} | {'Model Beats':>11} | {'Status':>8}")
    print("-" * 70)

    for tier in ['Star', 'Starter', 'Rotation', 'Bench']:
        if tier in report['by_tier']:
            t = report['by_tier'][tier]
            status_marker = "←SHARP" if t['status'] == 'SHARP' else ""
            print(f"{tier:<10} | {t['games']:>6} | {t['vegas_mae']:>9.2f} | {t['model_mae']:>9.2f} | {t['model_beats_vegas_pct']:>10.1f}% | {t['status']:>8}")

    # Edge availability
    print("\n" + "-" * 40)
    print("EDGE AVAILABILITY BY TIER")
    print("-" * 40)
    print(f"{'Tier':<10} | {'3+ Edge %':>10} | {'5+ Edge %':>10} | {'Vegas Within 3pt':>16}")
    print("-" * 55)

    for tier in ['Star', 'Starter', 'Rotation', 'Bench']:
        if tier in report['by_tier']:
            t = report['by_tier'][tier]
            print(f"{tier:<10} | {t['pct_3plus_edge']:>9.1f}% | {t['pct_5plus_edge']:>9.1f}% | {t['vegas_within_3pts']:>15.1f}%")

    # Trend
    print("\n" + "-" * 40)
    print("MONTHLY TREND (Model Beats Vegas %)")
    print("-" * 40)

    months = sorted(report['trend'].keys())
    if months:
        print(f"{'Month':<8} | {'Star':>8} | {'Starter':>8} | {'Rotation':>8} | {'Bench':>8}")
        print("-" * 50)
        for month in months:
            row = report['trend'][month]
            star = f"{row.get('Star', {}).get('model_beats_vegas_pct', 'N/A')}%" if 'Star' in row else 'N/A'
            starter = f"{row.get('Starter', {}).get('model_beats_vegas_pct', 'N/A')}%" if 'Starter' in row else 'N/A'
            rotation = f"{row.get('Rotation', {}).get('model_beats_vegas_pct', 'N/A')}%" if 'Rotation' in row else 'N/A'
            bench = f"{row.get('Bench', {}).get('model_beats_vegas_pct', 'N/A')}%" if 'Bench' in row else 'N/A'
            print(f"{month:<8} | {star:>8} | {starter:>8} | {rotation:>8} | {bench:>8}")

    # Sharpest lines (hardest to beat)
    print("\n" + "-" * 40)
    print("SHARPEST LINES (Hardest to Beat)")
    print("-" * 40)
    print(f"{'Player':<20} | {'Games':>5} | {'Vegas MAE':>9} | {'Model Beats':>11}")
    print("-" * 55)
    for p in report['sharpest_lines'][:7]:
        print(f"{p['player']:<20} | {p['games']:>5} | {p['vegas_mae']:>9.2f} | {p['model_beats_vegas_pct']:>10.1f}%")

    # Softest lines (easiest to beat)
    print("\n" + "-" * 40)
    print("SOFTEST LINES (Potential Opportunities)")
    print("-" * 40)
    print(f"{'Player':<20} | {'Games':>5} | {'Vegas MAE':>9} | {'Model Beats':>11}")
    print("-" * 55)
    for p in report['softest_lines'][:7]:
        print(f"{p['player']:<20} | {p['games']:>5} | {p['vegas_mae']:>9.2f} | {p['model_beats_vegas_pct']:>10.1f}%")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
