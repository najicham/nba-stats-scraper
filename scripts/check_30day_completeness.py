#!/usr/bin/env python3
"""
scripts/check_30day_completeness.py

Check data completeness for the past 30 days (Dec 22, 2025 - Jan 21, 2026).
Verifies:
1. Raw boxscore data coverage
2. Analytics pipeline completeness
3. Predictions coverage
4. Comparison to NBA schedule

Usage:
    PYTHONPATH=. python scripts/check_30day_completeness.py
    PYTHONPATH=. python scripts/check_30day_completeness.py --json > report.json
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from collections import defaultdict

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataCompletenessChecker:
    """Check data completeness across all pipeline stages."""

    def __init__(self):
        self.bq_client = bigquery.Client()
        self.project_id = self.bq_client.project

    def check_raw_boxscore_coverage(self, start_date: str, end_date: str) -> Dict:
        """
        Check raw boxscore data coverage.

        Returns:
            Dict with daily stats including game counts and player records
        """
        logger.info("Checking raw boxscore coverage...")

        query = f"""
        WITH daily_stats AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as game_count,
                COUNT(*) as player_records,
                COUNT(DISTINCT player_lookup) as unique_players
            FROM nba_raw.bdl_player_boxscores
            WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            GROUP BY game_date
        )
        SELECT
            game_date,
            game_count,
            player_records,
            unique_players
        FROM daily_stats
        ORDER BY game_date
        """

        result = self.bq_client.query(query).result(timeout=60)

        daily_data = {}
        for row in result:
            daily_data[row.game_date.isoformat()] = {
                'game_count': row.game_count,
                'player_records': row.player_records,
                'unique_players': row.unique_players
            }

        return daily_data

    def check_gamebook_coverage(self, start_date: str, end_date: str) -> Dict:
        """Check gamebook data coverage."""
        logger.info("Checking gamebook coverage...")

        query = f"""
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as game_count,
            COUNT(*) as player_records
        FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_date >= '{start_date}'
        AND game_date <= '{end_date}'
        GROUP BY game_date
        ORDER BY game_date
        """

        result = self.bq_client.query(query).result(timeout=60)

        daily_data = {}
        for row in result:
            daily_data[row.game_date.isoformat()] = {
                'game_count': row.game_count,
                'player_records': row.player_records
            }

        return daily_data

    def check_schedule_coverage(self, start_date: str, end_date: str) -> Dict:
        """Check NBA schedule for games that should have data."""
        logger.info("Checking NBA schedule...")

        query = f"""
        SELECT
            game_date,
            COUNT(*) as total_games,
            SUM(CASE WHEN game_status = 3 THEN 1 ELSE 0 END) as final_games,
            SUM(CASE WHEN game_status = 1 THEN 1 ELSE 0 END) as scheduled_games,
            SUM(CASE WHEN game_status = 2 THEN 1 ELSE 0 END) as live_games
        FROM nba_raw.nbac_schedule
        WHERE game_date >= '{start_date}'
        AND game_date <= '{end_date}'
        GROUP BY game_date
        ORDER BY game_date
        """

        result = self.bq_client.query(query).result(timeout=60)

        daily_data = {}
        for row in result:
            daily_data[row.game_date.isoformat()] = {
                'total_games': row.total_games,
                'final_games': row.final_games,
                'scheduled_games': row.scheduled_games,
                'live_games': row.live_games
            }

        return daily_data

    def check_analytics_coverage(self, start_date: str, end_date: str) -> Dict:
        """Check analytics pipeline coverage."""
        logger.info("Checking analytics pipeline coverage...")

        # Check key analytics tables
        tables_to_check = [
            'nba_analytics.player_game_summary',
            'nba_analytics.team_offense_game_summary',
            'nba_analytics.team_defense_game_summary'
        ]

        results = {}

        for table in tables_to_check:
            table_name = table.split('.')[-1]
            try:
                query = f"""
                SELECT
                    game_date,
                    COUNT(*) as record_count,
                    COUNT(DISTINCT game_id) as game_count
                FROM {table}
                WHERE game_date >= '{start_date}'
                AND game_date <= '{end_date}'
                GROUP BY game_date
                ORDER BY game_date
                """

                result = self.bq_client.query(query).result(timeout=60)

                daily_data = {}
                for row in result:
                    daily_data[row.game_date.isoformat()] = {
                        'record_count': row.record_count,
                        'game_count': row.game_count
                    }

                results[table_name] = daily_data

            except Exception as e:
                logger.warning(f"Failed to query {table}: {e}")
                results[table_name] = {}

        return results

    def check_feature_store_coverage(self, start_date: str, end_date: str) -> Dict:
        """Check feature store data."""
        logger.info("Checking feature store coverage...")

        try:
            query = f"""
            SELECT
                game_date,
                COUNT(*) as record_count,
                COUNT(DISTINCT player_lookup) as player_count
            FROM nba_predictions.ml_feature_store_v2
            WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            GROUP BY game_date
            ORDER BY game_date
            """

            result = self.bq_client.query(query).result(timeout=60)

            daily_data = {}
            for row in result:
                daily_data[row.game_date.isoformat()] = {
                    'record_count': row.record_count,
                    'player_count': row.player_count
                }

            return daily_data

        except Exception as e:
            logger.warning(f"Failed to query feature store: {e}")
            return {}

    def check_predictions_coverage(self, start_date: str, end_date: str) -> Dict:
        """Check predictions coverage."""
        logger.info("Checking predictions coverage...")

        try:
            query = f"""
            SELECT
                game_date,
                COUNT(*) as prediction_count,
                COUNT(DISTINCT player_lookup) as player_count,
                COUNT(DISTINCT game_id) as game_count
            FROM nba_predictions.player_prop_predictions
            WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            GROUP BY game_date
            ORDER BY game_date
            """

            result = self.bq_client.query(query).result(timeout=60)

            daily_data = {}
            for row in result:
                daily_data[row.game_date.isoformat()] = {
                    'prediction_count': row.prediction_count,
                    'player_count': row.player_count,
                    'game_count': row.game_count
                }

            return daily_data

        except Exception as e:
            logger.warning(f"Failed to query predictions: {e}")
            return {}

    def identify_data_gaps(self, schedule_data: Dict, boxscore_data: Dict,
                          gamebook_data: Dict, analytics_data: Dict,
                          predictions_data: Dict) -> List[Dict]:
        """
        Identify dates with missing or incomplete data.

        Returns:
            List of gaps with details
        """
        gaps = []

        # Get all dates from schedule
        all_dates = sorted(set(schedule_data.keys()))

        for date_str in all_dates:
            schedule = schedule_data.get(date_str, {})
            final_games = schedule.get('final_games', 0)

            # Skip if no final games (no games or games not finished yet)
            if final_games == 0:
                continue

            boxscore = boxscore_data.get(date_str, {})
            gamebook = gamebook_data.get(date_str, {})

            boxscore_games = boxscore.get('game_count', 0)
            gamebook_games = gamebook.get('game_count', 0)

            # Check for gaps
            gap_info = {
                'date': date_str,
                'expected_games': final_games,
                'issues': []
            }

            # Raw data gaps
            if boxscore_games < final_games:
                gap_info['issues'].append({
                    'type': 'missing_boxscores',
                    'expected': final_games,
                    'actual': boxscore_games,
                    'missing': final_games - boxscore_games
                })

            if gamebook_games < final_games:
                gap_info['issues'].append({
                    'type': 'missing_gamebooks',
                    'expected': final_games,
                    'actual': gamebook_games,
                    'missing': final_games - gamebook_games
                })

            # Analytics gaps
            player_stats = analytics_data.get('player_game_summary', {}).get(date_str, {})
            if player_stats.get('game_count', 0) < final_games:
                gap_info['issues'].append({
                    'type': 'missing_player_analytics',
                    'expected': final_games,
                    'actual': player_stats.get('game_count', 0),
                    'missing': final_games - player_stats.get('game_count', 0)
                })

            # Predictions gaps
            pred_data = predictions_data.get(date_str, {})
            if pred_data.get('prediction_count', 0) == 0:
                gap_info['issues'].append({
                    'type': 'missing_predictions',
                    'expected': '> 0',
                    'actual': 0
                })

            if gap_info['issues']:
                gaps.append(gap_info)

        return gaps

    def check_data_volume_anomalies(self, boxscore_data: Dict) -> List[Dict]:
        """
        Check for unusual drops in data volume.

        Returns:
            List of anomalies detected
        """
        anomalies = []

        # Calculate average player records per game
        player_records_per_game = []
        for date_str, data in boxscore_data.items():
            if data['game_count'] > 0:
                avg = data['player_records'] / data['game_count']
                player_records_per_game.append(avg)

        if not player_records_per_game:
            return anomalies

        avg_records = sum(player_records_per_game) / len(player_records_per_game)
        threshold = avg_records * 0.7  # 30% drop is anomalous

        for date_str, data in sorted(boxscore_data.items()):
            if data['game_count'] > 0:
                records_per_game = data['player_records'] / data['game_count']
                if records_per_game < threshold:
                    anomalies.append({
                        'date': date_str,
                        'type': 'low_player_records',
                        'expected_avg': round(avg_records, 1),
                        'actual_avg': round(records_per_game, 1),
                        'drop_pct': round((1 - records_per_game / avg_records) * 100, 1)
                    })

        return anomalies

    def generate_report(self, start_date: str, end_date: str) -> Dict:
        """Generate comprehensive data completeness report."""
        logger.info(f"Generating report for {start_date} to {end_date}")

        # Gather all data
        schedule_data = self.check_schedule_coverage(start_date, end_date)
        boxscore_data = self.check_raw_boxscore_coverage(start_date, end_date)
        gamebook_data = self.check_gamebook_coverage(start_date, end_date)
        analytics_data = self.check_analytics_coverage(start_date, end_date)
        feature_store_data = self.check_feature_store_coverage(start_date, end_date)
        predictions_data = self.check_predictions_coverage(start_date, end_date)

        # Identify gaps and anomalies
        gaps = self.identify_data_gaps(
            schedule_data, boxscore_data, gamebook_data,
            analytics_data, predictions_data
        )
        anomalies = self.check_data_volume_anomalies(boxscore_data)

        # Calculate summary statistics
        total_scheduled_games = sum(d.get('final_games', 0) for d in schedule_data.values())
        total_boxscore_games = sum(d.get('game_count', 0) for d in boxscore_data.values())
        total_gamebook_games = sum(d.get('game_count', 0) for d in gamebook_data.values())
        total_predictions = sum(d.get('prediction_count', 0) for d in predictions_data.values())

        dates_with_games = sum(1 for d in schedule_data.values() if d.get('final_games', 0) > 0)
        dates_with_boxscores = len(boxscore_data)
        dates_with_predictions = len(predictions_data)

        return {
            'report_metadata': {
                'start_date': start_date,
                'end_date': end_date,
                'generated_at': datetime.now().isoformat(),
                'days_checked': (datetime.fromisoformat(end_date) -
                               datetime.fromisoformat(start_date)).days + 1
            },
            'summary': {
                'total_scheduled_games': total_scheduled_games,
                'total_boxscore_games': total_boxscore_games,
                'total_gamebook_games': total_gamebook_games,
                'total_predictions': total_predictions,
                'dates_with_games': dates_with_games,
                'dates_with_boxscores': dates_with_boxscores,
                'dates_with_predictions': dates_with_predictions,
                'boxscore_coverage_pct': round(total_boxscore_games / total_scheduled_games * 100, 1) if total_scheduled_games > 0 else 0,
                'gamebook_coverage_pct': round(total_gamebook_games / total_scheduled_games * 100, 1) if total_scheduled_games > 0 else 0,
            },
            'data_gaps': gaps,
            'anomalies': anomalies,
            'daily_details': {
                'schedule': schedule_data,
                'boxscores': boxscore_data,
                'gamebooks': gamebook_data,
                'analytics': analytics_data,
                'feature_store': feature_store_data,
                'predictions': predictions_data
            }
        }

    def print_report(self, report: Dict):
        """Print human-readable report."""
        print("\n" + "=" * 80)
        print("DATA COMPLETENESS REPORT: PAST 30 DAYS")
        print("=" * 80)

        meta = report['report_metadata']
        print(f"\nDate Range: {meta['start_date']} to {meta['end_date']} ({meta['days_checked']} days)")
        print(f"Generated: {meta['generated_at']}")

        summary = report['summary']
        print("\n" + "-" * 80)
        print("SUMMARY STATISTICS")
        print("-" * 80)
        print(f"Total scheduled final games:  {summary['total_scheduled_games']:,}")
        print(f"Total boxscore games:         {summary['total_boxscore_games']:,} ({summary['boxscore_coverage_pct']}%)")
        print(f"Total gamebook games:         {summary['total_gamebook_games']:,} ({summary['gamebook_coverage_pct']}%)")
        print(f"Total predictions:            {summary['total_predictions']:,}")
        print(f"\nDates with final games:       {summary['dates_with_games']}")
        print(f"Dates with boxscore data:     {summary['dates_with_boxscores']}")
        print(f"Dates with predictions:       {summary['dates_with_predictions']}")

        # Data Gaps
        print("\n" + "-" * 80)
        print("DATA GAPS REQUIRING BACKFILL")
        print("-" * 80)

        gaps = report['data_gaps']
        if not gaps:
            print("✅ No data gaps detected!")
        else:
            print(f"⚠️  Found {len(gaps)} dates with missing data:\n")

            for gap in gaps:
                print(f"Date: {gap['date']} (Expected {gap['expected_games']} games)")
                for issue in gap['issues']:
                    issue_type = issue['type'].replace('_', ' ').title()
                    if 'missing' in issue:
                        print(f"  - {issue_type}: {issue['actual']}/{issue['expected']} (missing {issue['missing']})")
                    else:
                        print(f"  - {issue_type}: {issue['actual']} (expected {issue['expected']})")
                print()

        # Anomalies
        print("-" * 80)
        print("DATA VOLUME ANOMALIES")
        print("-" * 80)

        anomalies = report['anomalies']
        if not anomalies:
            print("✅ No unusual data volume drops detected!")
        else:
            print(f"⚠️  Found {len(anomalies)} dates with anomalous data volumes:\n")

            for anomaly in anomalies:
                print(f"Date: {anomaly['date']}")
                print(f"  Type: {anomaly['type']}")
                print(f"  Expected avg: {anomaly['expected_avg']} player records/game")
                print(f"  Actual avg: {anomaly['actual_avg']} player records/game")
                print(f"  Drop: {anomaly['drop_pct']}%")
                print()

        # Recommendations
        print("-" * 80)
        print("RECOMMENDATIONS")
        print("-" * 80)

        if gaps or anomalies:
            print("\n⚠️  Data quality issues detected. Recommended actions:")
            print()

            if gaps:
                # Group gaps by issue type
                missing_boxscores = [g for g in gaps if any(i['type'] == 'missing_boxscores' for i in g['issues'])]
                missing_gamebooks = [g for g in gaps if any(i['type'] == 'missing_gamebooks' for i in g['issues'])]
                missing_analytics = [g for g in gaps if any(i['type'] == 'missing_player_analytics' for i in g['issues'])]
                missing_predictions = [g for g in gaps if any(i['type'] == 'missing_predictions' for i in g['issues'])]

                if missing_boxscores:
                    print(f"1. Backfill {len(missing_boxscores)} dates with missing boxscores:")
                    dates = [g['date'] for g in missing_boxscores[:5]]
                    print(f"   Dates: {', '.join(dates)}")
                    if len(missing_boxscores) > 5:
                        print(f"   ... and {len(missing_boxscores) - 5} more")
                    print()

                if missing_gamebooks:
                    print(f"2. Backfill {len(missing_gamebooks)} dates with missing gamebooks:")
                    dates = [g['date'] for g in missing_gamebooks[:5]]
                    print(f"   Dates: {', '.join(dates)}")
                    if len(missing_gamebooks) > 5:
                        print(f"   ... and {len(missing_gamebooks) - 5} more")
                    print(f"   Command: PYTHONPATH=. python scripts/backfill_gamebooks.py --date YYYY-MM-DD")
                    print()

                if missing_analytics:
                    print(f"3. Re-run analytics for {len(missing_analytics)} dates:")
                    dates = [g['date'] for g in missing_analytics[:5]]
                    print(f"   Dates: {', '.join(dates)}")
                    if len(missing_analytics) > 5:
                        print(f"   ... and {len(missing_analytics) - 5} more")
                    print()

                if missing_predictions:
                    print(f"4. Generate predictions for {len(missing_predictions)} dates:")
                    dates = [g['date'] for g in missing_predictions[:5]]
                    print(f"   Dates: {', '.join(dates)}")
                    if len(missing_predictions) > 5:
                        print(f"   ... and {len(missing_predictions) - 5} more")
                    print()

            if anomalies:
                print(f"5. Investigate {len(anomalies)} dates with unusual data volumes")
                print("   These may indicate incomplete scrapes or data quality issues")
                print()
        else:
            print("\n✅ No action needed - all data is complete and healthy!")

        print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Check 30-day data completeness (Dec 22, 2025 - Jan 21, 2026)'
    )
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--start-date', type=str, default='2025-12-22',
                       help='Start date (default: 2025-12-22)')
    parser.add_argument('--end-date', type=str, default='2026-01-21',
                       help='End date (default: 2026-01-21)')

    args = parser.parse_args()

    checker = DataCompletenessChecker()
    report = checker.generate_report(args.start_date, args.end_date)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        checker.print_report(report)

    # Exit with error code if there are gaps
    if report['data_gaps'] or report['anomalies']:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
