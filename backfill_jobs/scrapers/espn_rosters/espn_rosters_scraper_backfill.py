#!/usr/bin/env python3
"""
ESPN Rosters Scraper Backfill - BATCH PROCESSING MODE
======================================================
Scrapes all 30 NBA team rosters from ESPN API and publishes ONE batch
completion message instead of 30 individual messages.

Benefits:
- 96.7% Pub/Sub reduction (30 messages → 1 message)
- 100% elimination of concurrent processor conflicts
- Single batch MERGE operation instead of 30 separate MERGEs

Usage:
    # Scrape all 30 teams (default)
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py

    # With debug logging
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py --debug

    # Specific teams only
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py --teams LAL,BOS,GSW
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from scrapers.espn.espn_roster_api import GetEspnTeamRosterAPI, ESPN_TEAM_IDS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EspnRostersBatchBackfill:
    """
    Batch backfill for ESPN rosters.

    Scrapes all 30 teams and publishes ONE batch completion message
    instead of 30 individual Pub/Sub messages.
    """

    # All 30 ESPN team codes
    ESPN_TEAMS = sorted(ESPN_TEAM_IDS.keys())

    def __init__(
        self,
        teams: Optional[List[str]] = None,
        group: str = 'prod',
        delay_seconds: float = 2.0,
        debug: bool = False
    ):
        self.teams = teams or self.ESPN_TEAMS
        self.group = group
        self.delay_seconds = delay_seconds
        self.debug = debug

        # Stats tracking
        self.completed_teams = []
        self.failed_teams = []
        self.total_players = 0
        self.start_time = None
        self.end_time = None

        if debug:
            logging.getLogger().setLevel(logging.DEBUG)

    def run(self) -> bool:
        """Run the batch backfill for all teams."""
        self.start_time = datetime.now(timezone.utc)

        logger.info("=" * 60)
        logger.info("ESPN ROSTERS BATCH BACKFILL")
        logger.info("=" * 60)
        logger.info(f"Teams to scrape: {len(self.teams)}")
        logger.info(f"Delay between teams: {self.delay_seconds}s")
        logger.info(f"Export group: {self.group}")
        logger.info("=" * 60)

        # Scrape all teams
        for i, team_abbr in enumerate(self.teams, 1):
            try:
                logger.info(f"[{i}/{len(self.teams)}] Scraping {team_abbr}...")

                success, player_count = self._scrape_team(team_abbr)

                if success:
                    self.completed_teams.append(team_abbr)
                    self.total_players += player_count
                    logger.info(f"  ✓ {team_abbr}: {player_count} players")
                else:
                    self.failed_teams.append(team_abbr)
                    logger.error(f"  ✗ {team_abbr}: Failed")

                # Rate limiting (skip delay after last team)
                if i < len(self.teams):
                    time.sleep(self.delay_seconds)

            except Exception as e:
                self.failed_teams.append(team_abbr)
                logger.error(f"  ✗ {team_abbr}: {e}")
                continue

        self.end_time = datetime.now(timezone.utc)

        # Publish batch completion if any teams succeeded
        if self.completed_teams:
            self._publish_batch_completion()

        # Print summary
        self._print_summary()

        return len(self.failed_teams) == 0

    def _scrape_team(self, team_abbr: str) -> tuple:
        """
        Scrape a single team's roster.

        Returns:
            (success: bool, player_count: int)
        """
        opts = {
            'team_abbr': team_abbr,
            'export_groups': [self.group],
            'skip_pubsub': True,  # DON'T publish per-team (batch will publish once)
        }

        if self.debug:
            opts['debug'] = True

        scraper = GetEspnTeamRosterAPI()
        success = scraper.run(opts)

        if success and scraper.data:
            return True, scraper.data.get('playerCount', 0)

        return False, 0

    def _publish_batch_completion(self):
        """Publish single Pub/Sub message to trigger batch processing."""
        try:
            from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

            date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            publisher = ScraperPubSubPublisher()
            message_id = publisher.publish_completion_event(
                scraper_name='espn_roster_batch',
                execution_id=f'batch_{date_str}_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                status='success',
                gcs_path=f'gs://nba-scraped-data/espn/rosters/{date_str}/',
                record_count=len(self.completed_teams),
                duration_seconds=int((self.end_time - self.start_time).total_seconds()),
                workflow='backfill',
                metadata={
                    'trigger_type': 'batch_processing',
                    'scraper_type': 'espn_roster',
                    'date': date_str,
                    'teams_scraped': len(self.completed_teams),
                    'teams': self.completed_teams,
                    'total_players': self.total_players,
                }
            )

            logger.info(f"✅ Published batch completion: teams={len(self.completed_teams)}, "
                       f"players={self.total_players}, message_id={message_id}")

        except Exception as e:
            logger.error(f"Failed to publish batch completion message: {e}")
            # Non-blocking - don't fail the entire backfill if Pub/Sub fails

    def _print_summary(self):
        """Print summary of backfill results."""
        duration = (self.end_time - self.start_time).total_seconds()

        print("\n" + "=" * 60)
        print("ESPN ROSTERS BATCH BACKFILL SUMMARY")
        print("=" * 60)
        print(f"Duration: {duration:.1f} seconds")
        print(f"Teams scraped: {len(self.completed_teams)}/{len(self.teams)}")
        print(f"Total players: {self.total_players}")

        if self.completed_teams:
            print(f"\n✓ Successful teams ({len(self.completed_teams)}):")
            print(f"  {', '.join(sorted(self.completed_teams))}")

        if self.failed_teams:
            print(f"\n✗ Failed teams ({len(self.failed_teams)}):")
            print(f"  {', '.join(sorted(self.failed_teams))}")

        print("=" * 60)

        if len(self.failed_teams) == 0:
            print("✅ ALL TEAMS SCRAPED SUCCESSFULLY")
            print("📦 Batch completion message published - processor will execute ONE MERGE")
        else:
            print(f"⚠️  {len(self.failed_teams)} teams failed")


def main():
    parser = argparse.ArgumentParser(
        description='ESPN Rosters Batch Backfill - scrapes all 30 teams with ONE batch message'
    )

    parser.add_argument(
        '--teams',
        type=str,
        help='Comma-separated list of ESPN team codes (default: all 30 teams). '
             'Use ESPN codes: GS, NY, NO, SA, UTAH (not GSW, NYK, etc.)'
    )

    parser.add_argument(
        '--group',
        type=str,
        default='prod',
        choices=['prod', 'dev', 'test'],
        help='Export group for GCS (default: prod)'
    )

    parser.add_argument(
        '--delay',
        type=float,
        default=2.0,
        help='Delay between teams in seconds (default: 2.0)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    # Parse team list if provided
    teams = None
    if args.teams:
        teams = [t.strip().upper() for t in args.teams.split(',')]
        # Validate teams
        invalid = [t for t in teams if t not in ESPN_TEAM_IDS]
        if invalid:
            print(f"Error: Invalid ESPN team codes: {invalid}")
            print(f"Valid codes: {sorted(ESPN_TEAM_IDS.keys())}")
            sys.exit(1)

    # Run backfill
    backfill = EspnRostersBatchBackfill(
        teams=teams,
        group=args.group,
        delay_seconds=args.delay,
        debug=args.debug
    )

    try:
        success = backfill.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.warning("\nBackfill interrupted by user")
        backfill._print_summary()
        sys.exit(130)


if __name__ == "__main__":
    main()
