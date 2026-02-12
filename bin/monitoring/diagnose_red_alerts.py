#!/usr/bin/env python3
"""
Red Alert Player Diagnostic Tool

Quickly diagnose which features failed and which processors need investigation
for players with red quality alerts.

Usage:
    python bin/monitoring/diagnose_red_alerts.py --date 2026-02-11
    python bin/monitoring/diagnose_red_alerts.py  # Defaults to today
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from google.cloud import bigquery
from typing import Dict, List

# Import upstream table mappings
from data_processors.precompute.ml_feature_store.quality_scorer import FEATURE_UPSTREAM_TABLES


def diagnose_red_alerts(game_date: str) -> None:
    """
    Diagnose red alert players and identify processor failures.

    Args:
        game_date: Date to analyze (YYYY-MM-DD format)
    """
    client = bigquery.Client(project='nba-props-platform')

    query = f"""
    SELECT
        player_lookup,
        default_feature_indices,
        quality_alert_level,
        quality_alerts,
        matchup_quality_pct,
        player_history_quality_pct,
        team_context_quality_pct,
        game_context_quality_pct,
        default_feature_count,
        feature_quality_score
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date = '{game_date}'
      AND quality_alert_level = 'red'
    ORDER BY default_feature_count DESC
    """

    print(f"Querying red alert players for {game_date}...")
    results = list(client.query(query))

    if not results:
        print(f"\n✅ No red alert players found for {game_date}")
        return

    # Group by processor failure pattern
    processor_failures = defaultdict(lambda: {
        'count': 0,
        'players': [],
        'feature_indices': set(),
        'avg_quality': 0.0
    })

    for row in results:
        indices = row.default_feature_indices

        # Map indices to upstream processors
        processors = set()
        for idx in indices:
            table = FEATURE_UPSTREAM_TABLES.get(idx, 'unknown')
            processors.add(table)

        # Create pattern key from sorted processor list
        pattern_key = ','.join(sorted(processors))

        processor_failures[pattern_key]['count'] += 1
        processor_failures[pattern_key]['players'].append(row.player_lookup)
        processor_failures[pattern_key]['feature_indices'].update(indices)
        processor_failures[pattern_key]['avg_quality'] += float(row.feature_quality_score)

    # Print diagnostic report
    print("\n" + "=" * 70)
    print(f"RED ALERT PLAYERS DIAGNOSTIC - {game_date}")
    print("=" * 70)
    print(f"\nTotal red alert players: {len(results)}")
    print(f"Unique failure patterns: {len(processor_failures)}")

    # Sort patterns by frequency (most common first)
    sorted_patterns = sorted(
        processor_failures.items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )

    for i, (pattern, data) in enumerate(sorted_patterns, 1):
        avg_quality = data['avg_quality'] / data['count']

        print(f"\n{'─' * 70}")
        print(f"Pattern {i}: {data['count']} players affected")
        print(f"{'─' * 70}")
        print(f"  Missing processors:")
        for proc in sorted(pattern.split(',')):
            print(f"    • {proc}")

        print(f"\n  Affected features (indices): {sorted(data['feature_indices'])}")
        print(f"  Average quality score: {avg_quality:.1f}")
        print(f"\n  Sample players ({min(5, len(data['players']))}):")
        for player in data['players'][:5]:
            print(f"    • {player}")

        if data['count'] > 5:
            print(f"    ... and {data['count'] - 5} more")

        # Actionable recommendation
        print(f"\n  ⚠️  ACTION: Investigate why these processors didn't run:")
        if 'calculated' in pattern:
            print(f"      - 'calculated' should never fail - indicates logic bug")
        if 'player_shot_zone_analysis' in pattern:
            print(f"      - Check Phase 4 shot zone processor logs")
        if 'team_defense_zone_analysis' in pattern:
            print(f"      - Check Phase 4 defense zone processor logs")
        if 'player_composite_factors' in pattern:
            print(f"      - Check Phase 4 composite factors processor logs")

    # Print category quality summary
    print(f"\n{'=' * 70}")
    print("CATEGORY QUALITY SUMMARY")
    print("=" * 70)

    avg_matchup = sum(float(r.matchup_quality_pct) for r in results) / len(results)
    avg_player_hist = sum(float(r.player_history_quality_pct) for r in results) / len(results)
    avg_team_ctx = sum(float(r.team_context_quality_pct) for r in results) / len(results)
    avg_game_ctx = sum(float(r.game_context_quality_pct) for r in results) / len(results)

    print(f"  Matchup quality:        {avg_matchup:5.1f}%")
    print(f"  Player history quality: {avg_player_hist:5.1f}%")
    print(f"  Team context quality:   {avg_team_ctx:5.1f}%")
    print(f"  Game context quality:   {avg_game_ctx:5.1f}%")

    # Print most common alerts
    print(f"\n{'=' * 70}")
    print("COMMON ALERTS")
    print("=" * 70)

    alert_counts = defaultdict(int)
    for row in results:
        for alert in row.quality_alerts:
            alert_counts[alert] += 1

    for alert, count in sorted(alert_counts.items(), key=lambda x: x[1], reverse=True):
        pct = 100.0 * count / len(results)
        print(f"  {alert:40s} {count:3d} ({pct:5.1f}%)")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Diagnose red alert players and identify processor failures'
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

    diagnose_red_alerts(args.date)


if __name__ == '__main__':
    main()
