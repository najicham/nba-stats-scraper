#!/usr/bin/env python3
"""
Phase 3 Backfill Maintenance Job

Automatically finds and processes games that have Phase 2 data but are missing
Phase 3 analytics. Runs daily to ensure complete data coverage.

Usage:
    # Check and process backfill candidates (last 30 days)
    python bin/maintenance/phase3_backfill_check.py

    # Check only (dry run)
    python bin/maintenance/phase3_backfill_check.py --dry-run

    # Check with custom lookback
    python bin/maintenance/phase3_backfill_check.py --lookback-days 60

    # Process specific processor only
    python bin/maintenance/phase3_backfill_check.py --processor player_game_summary

Schedule with cron:
    # Run daily at 2 AM
    0 2 * * * cd /path/to/nba-stats-scraper && python bin/maintenance/phase3_backfill_check.py >> logs/backfill.log 2>&1
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Dict, List

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Processors that use standard dependency checking
# (upcoming_player_game_context and upcoming_team_game_context use custom patterns)
PROCESSORS = {
    'player_game_summary': {
        'class': PlayerGameSummaryProcessor,
        'priority': 1,  # Highest priority
        'description': 'Player game performance analytics'
    },
    'team_offense_game_summary': {
        'class': TeamOffenseGameSummaryProcessor,
        'priority': 2,
        'description': 'Team offensive analytics'
    },
    'team_defense_game_summary': {
        'class': TeamDefenseGameSummaryProcessor,
        'priority': 3,
        'description': 'Team defensive analytics'
    },
    'upcoming_team_game_context': {
        'class': UpcomingTeamGameContextProcessor,
        'priority': 4,
        'description': 'Upcoming team game context'
    }
}


def find_all_backfill_candidates(lookback_days: int = 30) -> Dict[str, List]:
    """Find backfill candidates for all processors."""
    logger.info("=" * 80)
    logger.info(f"PHASE 3 BACKFILL CHECK - Lookback: {lookback_days} days")
    logger.info("=" * 80)

    all_candidates = {}

    for processor_name, config in sorted(PROCESSORS.items(), key=lambda x: x[1]['priority']):
        logger.info(f"\nChecking: {processor_name}")
        logger.info(f"  Description: {config['description']}")

        try:
            processor = config['class']()
            processor.set_opts({'project_id': 'nba-props-platform'})
            processor.init_clients()

            candidates = processor.find_backfill_candidates(lookback_days=lookback_days)

            if candidates:
                logger.info(f"  ⚠️  Found {len(candidates)} games needing processing")
                # Show first 3
                for candidate in candidates[:3]:
                    logger.info(f"    - {candidate['game_date']}: {candidate['game_id']}")
                if len(candidates) > 3:
                    logger.info(f"    ... and {len(candidates) - 3} more")

                all_candidates[processor_name] = candidates
            else:
                logger.info(f"  ✅ All games processed (no backfill needed)")

        except Exception as e:
            logger.error(f"  ❌ Error checking {processor_name}: {e}", exc_info=True)
            all_candidates[processor_name] = []

    return all_candidates


def process_backfill_candidates(candidates_by_processor: Dict[str, List],
                                dry_run: bool = False) -> Dict:
    """Process all backfill candidates."""
    logger.info("\n" + "=" * 80)
    logger.info("PROCESSING BACKFILL CANDIDATES")
    logger.info("=" * 80)

    if dry_run:
        logger.info("DRY RUN MODE - No actual processing will occur\n")

    results = {
        'total_games': 0,
        'processed': 0,
        'failed': 0,
        'skipped': 0,
        'by_processor': {}
    }

    for processor_name, candidates in candidates_by_processor.items():
        if not candidates:
            continue

        logger.info(f"\nProcessing: {processor_name}")
        logger.info(f"  Candidates: {len(candidates)} games")

        processor_results = {
            'candidates': len(candidates),
            'processed': 0,
            'failed': 0,
            'skipped': 0
        }

        if dry_run:
            logger.info(f"  [DRY RUN] Would process {len(candidates)} games")
            processor_results['skipped'] = len(candidates)
            results['skipped'] += len(candidates)
        else:
            # Process each game
            processor_config = PROCESSORS[processor_name]
            processor = processor_config['class']()

            # Disable early exit checks for backfill
            if hasattr(processor, 'ENABLE_HISTORICAL_DATE_CHECK'):
                processor.ENABLE_HISTORICAL_DATE_CHECK = False
            if hasattr(processor, 'ENABLE_NO_GAMES_CHECK'):
                processor.ENABLE_NO_GAMES_CHECK = False
            if hasattr(processor, 'ENABLE_OFFSEASON_CHECK'):
                processor.ENABLE_OFFSEASON_CHECK = False

            for candidate in candidates:
                game_date = candidate['game_date']
                game_id = candidate['game_id']

                try:
                    logger.info(f"  Processing {game_date} - {game_id}...")

                    success = processor.run({
                        'start_date': game_date,
                        'end_date': game_date
                    })

                    if success:
                        processor_results['processed'] += 1
                        results['processed'] += 1
                        logger.info(f"    ✅ Success")
                    else:
                        processor_results['failed'] += 1
                        results['failed'] += 1
                        logger.warning(f"    ❌ Failed")

                except Exception as e:
                    processor_results['failed'] += 1
                    results['failed'] += 1
                    logger.error(f"    ❌ Error: {e}", exc_info=True)

        results['total_games'] += len(candidates)
        results['by_processor'][processor_name] = processor_results

    return results


def send_summary_notification(candidates: Dict, results: Dict):
    """Send summary notification via logging. Future: Could integrate with Slack/email."""
    # NOTE: Currently logs summary to stdout. Slack integration available via
    # shared/notifications if needed for alerting.
    logger.info("\n" + "=" * 80)
    logger.info("BACKFILL SUMMARY")
    logger.info("=" * 80)

    total_candidates = sum(len(c) for c in candidates.values())

    logger.info(f"\nTotal candidates found: {total_candidates}")
    logger.info(f"  Processed: {results['processed']}")
    logger.info(f"  Failed: {results['failed']}")
    logger.info(f"  Skipped (dry run): {results['skipped']}")

    if results['by_processor']:
        logger.info("\nBy Processor:")
        for processor_name, proc_results in results['by_processor'].items():
            logger.info(f"  {processor_name}:")
            logger.info(f"    Candidates: {proc_results['candidates']}")
            logger.info(f"    Processed: {proc_results['processed']}")
            logger.info(f"    Failed: {proc_results['failed']}")

    # Future: Send to Slack/Email if failures detected
    if results['failed'] > 0:
        logger.warning(f"\n⚠️  {results['failed']} games failed processing")
    elif total_candidates == 0:
        logger.info("\n✅ All Phase 3 data up to date!")
    elif results['processed'] > 0:
        logger.info(f"\n✅ Successfully processed {results['processed']} games")


def main():
    parser = argparse.ArgumentParser(description='Phase 3 Backfill Maintenance')
    parser.add_argument('--lookback-days', type=int, default=30,
                      help='How many days to look back (default: 30)')
    parser.add_argument('--dry-run', action='store_true',
                      help='Check only, do not process')
    parser.add_argument('--processor', type=str, choices=list(PROCESSORS.keys()),
                      help='Process specific processor only')
    args = parser.parse_args()

    logger.info(f"Starting Phase 3 backfill check at {datetime.now(timezone.utc).isoformat()}")

    # Find candidates
    if args.processor:
        # Single processor mode
        candidates = {args.processor: []}
        processor_config = PROCESSORS[args.processor]
        processor = processor_config['class']()
        processor.set_opts({'project_id': 'nba-props-platform'})
        processor.init_clients()
        candidates[args.processor] = processor.find_backfill_candidates(
            lookback_days=args.lookback_days
        )
    else:
        # All processors
        candidates = find_all_backfill_candidates(lookback_days=args.lookback_days)

    # Process candidates
    results = process_backfill_candidates(candidates, dry_run=args.dry_run)

    # Send summary
    send_summary_notification(candidates, results)

    # Exit code
    if results['failed'] > 0:
        logger.error("\n❌ Some games failed processing")
        sys.exit(1)
    else:
        logger.info("\n✅ Backfill check complete")
        sys.exit(0)


if __name__ == "__main__":
    main()
