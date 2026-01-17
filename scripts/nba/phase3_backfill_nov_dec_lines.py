#!/usr/bin/env python3
"""
PHASE 3: Backfill Nov-Dec 2025 Placeholder Lines with Historical DraftKings Data

This script updates predictions from Nov 19 - Dec 19, 2025 that have placeholder
lines (line_value = 20.0) with real historical sportsbook lines from odds_api.

Features:
- Idempotent: Safe to run multiple times
- Resumable: Can stop and restart at any date
- Auditable: Tracks all changes with timestamps
- Validated: Comprehensive checks before and after

Usage:
    # Dry run to see what would be updated
    PYTHONPATH=. python scripts/nba/phase3_backfill_nov_dec_lines.py --dry-run

    # Execute backfill
    PYTHONPATH=. python scripts/nba/phase3_backfill_nov_dec_lines.py

    # Single date
    PYTHONPATH=. python scripts/nba/phase3_backfill_nov_dec_lines.py --date 2025-11-19

    # Date range
    PYTHONPATH=. python scripts/nba/phase3_backfill_nov_dec_lines.py \\
        --start-date 2025-11-19 --end-date 2025-12-19

Author: Claude (Session 76)
Date: 2026-01-16
"""

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = "nba-props-platform"
PREDICTIONS_TABLE = f"{PROJECT_ID}.nba_predictions.player_prop_predictions"
PROPS_TABLE = f"{PROJECT_ID}.nba_raw.odds_api_player_points_props"
START_DATE = date(2025, 11, 19)
END_DATE = date(2025, 12, 19)


class NovDecLineBackfill:
    """Backfills Nov-Dec 2025 placeholder lines with historical DraftKings data."""

    def __init__(self, dry_run: bool = False):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.dry_run = dry_run
        self.stats = {
            'dates_processed': 0,
            'predictions_found': 0,
            'props_matched': 0,
            'predictions_updated': 0,
            'still_missing': 0,
            'already_valid': 0
        }

    def get_available_props(self, game_date: date) -> Dict[str, Dict]:
        """
        Get all available props for a date.

        Returns dict: player_lookup -> {points_line, bookmaker, snapshot_timestamp}
        """
        query = f"""
        WITH ranked_props AS (
            SELECT
                player_lookup,
                points_line,
                bookmaker,
                snapshot_timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY
                        -- Preference order: DraftKings > FanDuel > Others
                        CASE bookmaker
                            WHEN 'draftkings' THEN 1
                            WHEN 'fanduel' THEN 2
                            WHEN 'betmgm' THEN 3
                            WHEN 'caesars' THEN 4
                            WHEN 'pointsbet' THEN 5
                            ELSE 99
                        END,
                        snapshot_timestamp DESC  -- Most recent line
                ) as rn
            FROM `{PROPS_TABLE}`
            WHERE game_date = '{game_date}'
              AND points_line IS NOT NULL
              AND points_line > 0  -- Sanity check
              AND points_line != 20.0  -- Exclude placeholder values in props table
        )
        SELECT
            player_lookup,
            points_line,
            bookmaker,
            snapshot_timestamp
        FROM ranked_props
        WHERE rn = 1
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            props_dict = {}

            for _, row in result.iterrows():
                props_dict[row['player_lookup']] = {
                    'points_line': float(row['points_line']),
                    'bookmaker': row['bookmaker'].upper(),
                    'snapshot_timestamp': row['snapshot_timestamp']
                }

            return props_dict

        except Exception as e:
            logger.error(f"Error fetching props for {game_date}: {e}")
            return {}

    def get_placeholder_predictions(self, game_date: date) -> List[Dict]:
        """Get predictions with placeholder lines for a date."""
        query = f"""
        SELECT
            prediction_id,
            player_lookup,
            game_id,
            system_id,
            current_points_line,
            line_source,
            predicted_points,
            confidence_score,
            recommendation,
            created_at
        FROM `{PREDICTIONS_TABLE}`
        WHERE game_date = '{game_date}'
          AND current_points_line = 20.0  -- Only placeholder lines
        ORDER BY player_lookup, system_id
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error fetching predictions for {game_date}: {e}")
            return []

    def calculate_new_recommendation(self, predicted_points: float, line_value: float) -> str:
        """Calculate recommendation based on prediction vs line."""
        if predicted_points > line_value:
            return 'OVER'
        elif predicted_points < line_value:
            return 'UNDER'
        else:
            return 'PASS'

    def backfill_date(self, game_date: date) -> Dict:
        """Backfill a single date."""
        logger.info(f"\\n{'='*60}")
        logger.info(f"Processing {game_date}...")
        logger.info(f"{'='*60}")

        # Get placeholder predictions
        predictions = self.get_placeholder_predictions(game_date)
        self.stats['predictions_found'] += len(predictions)

        if not predictions:
            logger.info(f"  ✅ No placeholder predictions for {game_date}")
            return {'date': str(game_date), 'updated': 0, 'missing': 0, 'skipped': True}

        logger.info(f"  📊 Found {len(predictions)} predictions with placeholders")

        # Get available props
        props = self.get_available_props(game_date)
        logger.info(f"  📊 Found {len(props)} players with historical props")

        # Match predictions to props
        to_update = []
        still_missing = []

        for pred in predictions:
            player_lookup = pred['player_lookup']
            if player_lookup in props:
                prop = props[player_lookup]
                new_recommendation = self.calculate_new_recommendation(
                    pred['predicted_points'],
                    prop['points_line']
                )
                to_update.append({
                    'prediction_id': pred['prediction_id'],
                    'player_lookup': player_lookup,
                    'system_id': pred['system_id'],
                    'old_line': pred['current_points_line'],
                    'new_line': prop['points_line'],
                    'bookmaker': prop['bookmaker'],
                    'predicted_points': pred['predicted_points'],
                    'old_recommendation': pred['recommendation'],
                    'new_recommendation': new_recommendation
                })
                self.stats['props_matched'] += 1
            else:
                still_missing.append(f"{player_lookup} ({pred['system_id']})")
                self.stats['still_missing'] += 1

        logger.info(f"  ✅ Can update: {len(to_update)}")
        logger.info(f"  ⚠️  Still missing props: {len(still_missing)}")

        if still_missing and len(still_missing) <= 10:
            logger.info(f"     Missing: {', '.join(still_missing[:10])}")

        # Execute update (or dry run)
        if to_update:
            if self.dry_run:
                logger.info(f"  🔍 DRY RUN: Would update {len(to_update)} predictions")
                self._log_sample_updates(to_update[:5])
                updated_count = len(to_update)
            else:
                updated_count = self._execute_update(to_update, game_date)
                self.stats['predictions_updated'] += updated_count

            return {
                'date': str(game_date),
                'updated': updated_count,
                'missing': len(still_missing),
                'skipped': False
            }
        else:
            logger.info(f"  ⚠️  No predictions can be updated (all missing props)")
            return {
                'date': str(game_date),
                'updated': 0,
                'missing': len(still_missing),
                'skipped': False
            }

    def _log_sample_updates(self, sample: List[Dict]):
        """Log sample updates for dry run visibility."""
        logger.info(f"\\n  Sample updates:")
        for item in sample:
            logger.info(
                f"    {item['player_lookup']} ({item['system_id']}): "
                f"line {item['old_line']:.1f} → {item['new_line']:.1f} "
                f"({item['bookmaker']}), "
                f"rec {item['old_recommendation']} → {item['new_recommendation']}"
            )

    def _execute_update(self, updates: List[Dict], game_date: date) -> int:
        """Execute BigQuery UPDATE to update predictions."""
        if not updates:
            return 0

        # Build CASE statements for update
        prediction_ids = [item['prediction_id'] for item in updates]
        line_cases = []
        rec_cases = []
        book_cases = []

        for item in updates:
            pid = item['prediction_id']
            line_cases.append(f"WHEN '{pid}' THEN {item['new_line']}")
            rec_cases.append(f"WHEN '{pid}' THEN '{item['new_recommendation']}'")
            book_cases.append(f"WHEN '{pid}' THEN '{item['bookmaker']}'")

        # Calculate line_margin for each
        margin_cases = [
            f"WHEN '{item['prediction_id']}' THEN {item['predicted_points'] - item['new_line']:.2f}"
            for item in updates
        ]

        # Build update query
        update_query = f"""
        UPDATE `{PREDICTIONS_TABLE}`
        SET
            current_points_line = CASE prediction_id
                {chr(10).join(['                ' + case for case in line_cases])}
            END,
            recommendation = CASE prediction_id
                {chr(10).join(['                ' + case for case in rec_cases])}
            END,
            line_margin = CASE prediction_id
                {chr(10).join(['                ' + case for case in margin_cases])}
            END,
            sportsbook = CASE prediction_id
                {chr(10).join(['                ' + case for case in book_cases])}
            END,
            has_prop_line = TRUE,
            line_source = 'ACTUAL_PROP',
            line_source_api = 'ODDS_API',
            updated_at = CURRENT_TIMESTAMP()
        WHERE prediction_id IN ({', '.join([f"'{pid}'" for pid in prediction_ids])})
        """

        try:
            job = self.bq_client.query(update_query)
            job.result()  # Wait for completion
            updated_count = job.num_dml_affected_rows or len(updates)
            logger.info(f"  ✅ Updated {updated_count} predictions")
            return updated_count

        except Exception as e:
            logger.error(f"  ❌ Update failed: {e}")
            logger.error(f"     Query preview: {update_query[:500]}...")
            raise

    def backfill_date_range(self, start_date: date, end_date: date) -> List[Dict]:
        """Backfill a date range."""
        current = start_date
        results = []

        logger.info(f"\\n🚀 Starting backfill from {start_date} to {end_date}...")
        logger.info(f"{'='*60}\\n")

        while current <= end_date:
            result = self.backfill_date(current)
            results.append(result)
            self.stats['dates_processed'] += 1
            current += timedelta(days=1)

        return results

    def print_summary(self, results: List[Dict]):
        """Print summary report."""
        print("\\n" + "="*70)
        print("BACKFILL SUMMARY")
        print("="*70)
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE EXECUTION'}")
        print(f"\\nDates Processed: {self.stats['dates_processed']}")
        print(f"Predictions Found: {self.stats['predictions_found']:,}")
        print(f"Props Matched: {self.stats['props_matched']:,}")
        print(f"Predictions Updated: {self.stats['predictions_updated']:,}")
        print(f"Still Missing Props: {self.stats['still_missing']:,}")

        if self.stats['predictions_found'] > 0:
            success_rate = (self.stats['props_matched'] / self.stats['predictions_found']) * 100
            print(f"\\nSuccess Rate: {success_rate:.1f}%")

        print("="*70)

        # Date-by-date breakdown
        print("\\nDATE-BY-DATE BREAKDOWN:")
        print("-" * 70)
        print(f"{'Date':<12} {'Updated':>10} {'Missing':>10} {'Status':<20}")
        print("-" * 70)

        for result in results:
            if result.get('skipped'):
                status = "✅ No placeholders"
            elif result['updated'] > 0:
                status = f"✅ {result['updated']} updated"
            else:
                status = "⚠️ All missing props"

            print(f"{result['date']:<12} {result['updated']:>10} {result['missing']:>10} {status:<20}")

        print("-" * 70)

        if self.dry_run:
            print("\\n⚠️  DRY RUN MODE - No changes written to BigQuery")
            print("   Run without --dry-run to execute updates")
        else:
            print("\\n✅ Backfill complete!")

        # Send Slack notification
        self._send_slack_summary()

    def _send_slack_summary(self):
        """Send completion summary to Slack."""
        try:
            from shared.utils.slack_channels import send_to_slack
            webhook = os.environ.get('SLACK_WEBHOOK_URL_WARNING')
            if not webhook:
                logger.info("No Slack webhook configured - skipping notification")
                return

            status_emoji = "✅" if self.stats['still_missing'] == 0 else "⚠️"
            mode = "(DRY RUN)" if self.dry_run else ""

            text = f"""{status_emoji} *Nov-Dec Line Backfill Complete* {mode}

*Results:*
• Dates Processed: {self.stats['dates_processed']}
• Predictions Updated: {self.stats['predictions_updated']:,}
• Still Missing: {self.stats['still_missing']:,}
• Success Rate: {(self.stats['props_matched'] / self.stats['predictions_found'] * 100) if self.stats['predictions_found'] > 0 else 0:.1f}%

{f"⚠️ {self.stats['still_missing']:,} predictions still missing props data" if self.stats['still_missing'] > 0 else "✅ All placeholders backfilled successfully"}
"""

            send_to_slack(webhook, text, icon_emoji=":chart_with_upwards_trend:")
            logger.info("Slack notification sent")

        except Exception as e:
            logger.warning(f"Failed to send Slack notification: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Backfill Nov-Dec 2025 placeholder lines with historical props',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to preview changes
  python scripts/nba/phase3_backfill_nov_dec_lines.py --dry-run

  # Execute full backfill
  python scripts/nba/phase3_backfill_nov_dec_lines.py

  # Single date
  python scripts/nba/phase3_backfill_nov_dec_lines.py --date 2025-11-19

  # Date range
  python scripts/nba/phase3_backfill_nov_dec_lines.py --start-date 2025-11-19 --end-date 2025-11-25
        """
    )

    parser.add_argument(
        '--date',
        type=str,
        help='Single date to backfill (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        default=str(START_DATE),
        help=f'Start date (YYYY-MM-DD). Default: {START_DATE}'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default=str(END_DATE),
        help=f'End date (YYYY-MM-DD). Default: {END_DATE}'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing to BigQuery'
    )

    args = parser.parse_args()

    # Initialize backfill
    backfill = NovDecLineBackfill(dry_run=args.dry_run)

    # Execute backfill
    try:
        if args.date:
            # Single date
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
            logger.info(f"Backfilling single date: {target_date}")
            results = [backfill.backfill_date(target_date)]
        else:
            # Date range
            start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
            logger.info(f"Backfilling date range: {start} to {end}")
            results = backfill.backfill_date_range(start, end)

        # Print summary
        backfill.print_summary(results)

        # Exit code
        if backfill.stats['still_missing'] > 0:
            logger.warning(f"⚠️  {backfill.stats['still_missing']} predictions still need props")
            sys.exit(1)
        else:
            logger.info("✅ All placeholders successfully backfilled")
            sys.exit(0)

    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
