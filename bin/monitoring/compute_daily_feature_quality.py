#!/usr/bin/env python3
"""
Compute and store daily feature quality metrics.

This script computes aggregated feature quality metrics from ml_feature_store_v2
and stores them in nba_monitoring.ml_feature_quality_trends for historical tracking.

Session 209: Priority 2 - Feature Quality Daily Trend Tracking

Usage:
    python bin/monitoring/compute_daily_feature_quality.py --date 2026-02-11
    python bin/monitoring/compute_daily_feature_quality.py  # Defaults to today
"""

import argparse
import sys
import json
from datetime import datetime
from google.cloud import bigquery


def compute_quality_metrics(game_date: str) -> dict:
    """
    Compute feature quality metrics for a given game date.

    Args:
        game_date: Date to analyze (YYYY-MM-DD format)

    Returns:
        dict: Quality metrics for the date
    """
    client = bigquery.Client(project='nba-props-platform')

    query = f"""
    WITH metrics AS (
      SELECT
        COUNT(*) as total_players,
        COUNTIF(is_quality_ready) as quality_ready_count,
        ROUND(100.0 * COUNTIF(is_quality_ready) / NULLIF(COUNT(*), 0), 2) as quality_ready_pct,
        ROUND(AVG(feature_quality_score), 2) as avg_feature_quality_score,
        COUNTIF(quality_alert_level = 'red') as red_alert_count,
        COUNTIF(quality_alert_level = 'yellow') as yellow_alert_count,
        COUNTIF(quality_alert_level = 'green') as green_alert_count,
        ROUND(AVG(matchup_quality_pct), 2) as avg_matchup_quality_pct,
        ROUND(AVG(player_history_quality_pct), 2) as avg_player_history_quality_pct,
        ROUND(AVG(team_context_quality_pct), 2) as avg_team_context_quality_pct,
        ROUND(AVG(vegas_quality_pct), 2) as avg_vegas_quality_pct,
        ROUND(AVG(game_context_quality_pct), 2) as avg_game_context_quality_pct,
        COUNTIF(default_feature_count > 0) as players_with_defaults,
        ROUND(AVG(default_feature_count), 2) as avg_default_feature_count
      FROM nba_predictions.ml_feature_store_v2
      WHERE game_date = '{game_date}'
    ),
    top_patterns AS (
      -- Find most common missing processor patterns (from red alerts only)
      SELECT
        default_feature_indices,
        COUNT(*) as player_count
      FROM nba_predictions.ml_feature_store_v2
      WHERE game_date = '{game_date}'
        AND quality_alert_level = 'red'
      GROUP BY default_feature_indices
      ORDER BY player_count DESC
      LIMIT 5
    )
    SELECT
      '{game_date}' as report_date,
      m.*,
      ARRAY_AGG(
        STRUCT(
          CAST(p.player_count AS INT64) as player_count,
          p.default_feature_indices
        )
        ORDER BY p.player_count DESC
      ) as top_missing_processors,
      CURRENT_TIMESTAMP() as computation_timestamp
    FROM metrics m
    LEFT JOIN top_patterns p ON TRUE
    GROUP BY
      report_date, total_players, quality_ready_count, quality_ready_pct,
      avg_feature_quality_score, red_alert_count, yellow_alert_count,
      green_alert_count, avg_matchup_quality_pct, avg_player_history_quality_pct,
      avg_team_context_quality_pct, avg_vegas_quality_pct, avg_game_context_quality_pct,
      players_with_defaults, avg_default_feature_count, computation_timestamp
    """

    result = list(client.query(query))
    if not result:
        print(f"❌ No feature store data found for {game_date}")
        return None

    row = result[0]

    # Convert top_missing_processors to JSON
    top_patterns_json = []
    if row.top_missing_processors:
        for pattern in row.top_missing_processors:
            # Pattern is already a dict from BigQuery STRUCT
            if isinstance(pattern, dict):
                top_patterns_json.append({
                    'player_count': pattern.get('player_count', 0),
                    'feature_indices': pattern.get('default_feature_indices', [])
                })
            else:
                # Handle Row object case
                top_patterns_json.append({
                    'player_count': pattern.player_count,
                    'feature_indices': pattern.default_feature_indices
                })

    metrics = {
        'report_date': game_date,
        'total_players': row.total_players,
        'quality_ready_count': row.quality_ready_count,
        'quality_ready_pct': float(row.quality_ready_pct) if row.quality_ready_pct else 0.0,
        'avg_feature_quality_score': float(row.avg_feature_quality_score) if row.avg_feature_quality_score else 0.0,
        'red_alert_count': row.red_alert_count,
        'yellow_alert_count': row.yellow_alert_count,
        'green_alert_count': row.green_alert_count,
        'avg_matchup_quality_pct': float(row.avg_matchup_quality_pct) if row.avg_matchup_quality_pct else 0.0,
        'avg_player_history_quality_pct': float(row.avg_player_history_quality_pct) if row.avg_player_history_quality_pct else 0.0,
        'avg_team_context_quality_pct': float(row.avg_team_context_quality_pct) if row.avg_team_context_quality_pct else 0.0,
        'avg_vegas_quality_pct': float(row.avg_vegas_quality_pct) if row.avg_vegas_quality_pct else 0.0,
        'avg_game_context_quality_pct': float(row.avg_game_context_quality_pct) if row.avg_game_context_quality_pct else 0.0,
        'players_with_defaults': row.players_with_defaults,
        'avg_default_feature_count': float(row.avg_default_feature_count) if row.avg_default_feature_count else 0.0,
        'top_missing_processors': json.dumps(top_patterns_json),
        'computation_timestamp': row.computation_timestamp.isoformat()
    }

    return metrics


def insert_metrics(metrics: dict) -> None:
    """
    Insert metrics into nba_monitoring.ml_feature_quality_trends.

    Args:
        metrics: Metrics dictionary to insert
    """
    client = bigquery.Client(project='nba-props-platform')
    table_id = 'nba-props-platform.nba_monitoring.ml_feature_quality_trends'

    # Check if record already exists for this date
    check_query = f"""
    SELECT COUNT(*) as count
    FROM nba_monitoring.ml_feature_quality_trends
    WHERE report_date = '{metrics['report_date']}'
    """

    result = list(client.query(check_query))
    if result[0].count > 0:
        print(f"⚠️  Record already exists for {metrics['report_date']}. Deleting old record...")
        delete_query = f"""
        DELETE FROM nba_monitoring.ml_feature_quality_trends
        WHERE report_date = '{metrics['report_date']}'
        """
        client.query(delete_query).result()

    # Insert new record
    errors = client.insert_rows_json(table_id, [metrics])

    if errors:
        print(f"❌ Errors inserting metrics: {errors}")
        sys.exit(1)
    else:
        print(f"✅ Metrics stored successfully for {metrics['report_date']}")


def main():
    parser = argparse.ArgumentParser(
        description='Compute and store daily feature quality metrics'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Game date to analyze (YYYY-MM-DD). Defaults to today.'
    )

    args = parser.parse_args()

    # Validate date format
    try:
        datetime.strptime(args.date, '%Y-%m-%d')
    except ValueError:
        print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD.")
        sys.exit(1)

    print(f"Computing feature quality metrics for {args.date}...")
    metrics = compute_quality_metrics(args.date)

    if metrics:
        print(f"\nMetrics Summary:")
        print(f"  Total players:      {metrics['total_players']}")
        print(f"  Quality ready:      {metrics['quality_ready_count']} ({metrics['quality_ready_pct']:.1f}%)")
        print(f"  Avg quality score:  {metrics['avg_feature_quality_score']:.1f}")
        print(f"  Alert levels:       {metrics['green_alert_count']} green, {metrics['yellow_alert_count']} yellow, {metrics['red_alert_count']} red")
        print()

        insert_metrics(metrics)

        print()
        print("To view trends:")
        print(f"  bq query \"SELECT * FROM nba_monitoring.ml_feature_quality_trends WHERE report_date >= DATE_SUB('{args.date}', INTERVAL 7 DAY) ORDER BY report_date DESC\"")
    else:
        print("❌ No metrics to insert")
        sys.exit(1)


if __name__ == '__main__':
    main()
