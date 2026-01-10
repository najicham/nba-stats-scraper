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

Features:
- Completeness validation: Alerts and fails if < 25 teams scraped
- Automatic retry: Failed teams are retried with exponential backoff
- Configurable delay: Adjust inter-team delay to avoid rate limits

Usage:
    # Scrape all 30 teams (default)
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py

    # With debug logging
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py --debug

    # Specific teams only
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py --teams LAL,BOS,GSW

    # Custom settings
    python backfill_jobs/scrapers/espn_rosters/espn_rosters_scraper_backfill.py --delay 3.0 --retries 3 --min-teams 20
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

    Features:
    - Completeness validation: Fails if < min_teams_threshold scraped
    - Automatic retry: Failed teams retried with exponential backoff
    - Alerting: Sends notification on incomplete scrapes
    """

    # All 30 ESPN team codes
    ESPN_TEAMS = sorted(ESPN_TEAM_IDS.keys())

    # Default threshold for success (83% of 30 teams)
    DEFAULT_MIN_TEAMS = 25

    def __init__(
        self,
        teams: Optional[List[str]] = None,
        group: str = 'prod',
        delay_seconds: float = 2.0,
        debug: bool = False,
        max_retries: int = 2,
        min_teams_threshold: int = None
    ):
        self.teams = teams or self.ESPN_TEAMS
        self.group = group
        self.delay_seconds = delay_seconds
        self.debug = debug
        self.max_retries = max_retries
        # Default threshold: 83% of requested teams, minimum 1
        self.min_teams_threshold = min_teams_threshold if min_teams_threshold is not None else max(1, int(len(self.teams) * 0.83))

        # Stats tracking
        self.completed_teams = []
        self.failed_teams = []
        self.total_players = 0
        self.start_time = None
        self.end_time = None

        if debug:
            logging.getLogger().setLevel(logging.DEBUG)

    def run(self) -> bool:
        """Run the batch backfill for all teams with retry logic."""
        self.start_time = datetime.now(timezone.utc)

        logger.info("=" * 60)
        logger.info("ESPN ROSTERS BATCH BACKFILL")
        logger.info("=" * 60)
        logger.info(f"Teams to scrape: {len(self.teams)}")
        logger.info(f"Delay between teams: {self.delay_seconds}s")
        logger.info(f"Export group: {self.group}")
        logger.info(f"Min teams threshold: {self.min_teams_threshold}")
        logger.info(f"Max retries for failed teams: {self.max_retries}")
        logger.info("=" * 60)

        # Initial scrape of all teams
        self._scrape_teams_batch(self.teams, "Initial scrape")

        # Retry failed teams with exponential backoff
        retry_attempt = 0
        while self.failed_teams and retry_attempt < self.max_retries:
            retry_attempt += 1
            retry_delay = self.delay_seconds * (2 ** retry_attempt)  # Exponential backoff
            teams_to_retry = self.failed_teams.copy()
            self.failed_teams = []

            logger.info("=" * 60)
            logger.info(f"RETRY ATTEMPT {retry_attempt}/{self.max_retries}")
            logger.info(f"Teams to retry: {len(teams_to_retry)}")
            logger.info(f"Retry delay: {retry_delay}s between teams")
            logger.info("=" * 60)

            # Wait before retry batch
            time.sleep(retry_delay * 2)

            self._scrape_teams_batch(teams_to_retry, f"Retry {retry_attempt}", delay_override=retry_delay)

        self.end_time = datetime.now(timezone.utc)

        # Check completeness threshold
        is_complete = len(self.completed_teams) >= self.min_teams_threshold

        if not is_complete:
            self._send_incomplete_alert()

        # Publish batch completion with appropriate status
        if self.completed_teams:
            self._publish_batch_completion(is_complete)

        # Print summary
        self._print_summary()

        return is_complete

    def _scrape_teams_batch(self, teams: List[str], phase: str, delay_override: float = None):
        """Scrape a batch of teams."""
        delay = delay_override or self.delay_seconds
        logger.info(f"{phase}: Processing {len(teams)} teams...")

        for i, team_abbr in enumerate(teams, 1):
            try:
                logger.info(f"[{i}/{len(teams)}] Scraping {team_abbr}...")

                success, player_count = self._scrape_team(team_abbr)

                if success:
                    self.completed_teams.append(team_abbr)
                    self.total_players += player_count
                    logger.info(f"  ✓ {team_abbr}: {player_count} players")
                else:
                    self.failed_teams.append(team_abbr)
                    logger.error(f"  ✗ {team_abbr}: Failed")

                # Rate limiting (skip delay after last team)
                if i < len(teams):
                    time.sleep(delay)

            except Exception as e:
                self.failed_teams.append(team_abbr)
                logger.error(f"  ✗ {team_abbr}: {e}")
                continue

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

    def _send_incomplete_alert(self):
        """Send alert when scrape is incomplete (below threshold)."""
        try:
            from shared.utils.notification_system import notify_error

            notify_error(
                title="ESPN Roster Scrape Incomplete",
                message=f"Only {len(self.completed_teams)}/{len(self.teams)} teams scraped (threshold: {self.min_teams_threshold})",
                details={
                    'scraper': 'espn_roster_batch',
                    'teams_requested': len(self.teams),
                    'teams_scraped': len(self.completed_teams),
                    'teams_failed': len(self.failed_teams),
                    'min_threshold': self.min_teams_threshold,
                    'failed_teams': self.failed_teams,
                    'completed_teams': self.completed_teams,
                },
                processor_name="ESPN Roster Batch Backfill"
            )
            logger.warning(f"Sent incomplete scrape alert: {len(self.completed_teams)}/{len(self.teams)} teams")

        except ImportError:
            logger.warning("Notification system not available - skipping alert")
        except Exception as e:
            logger.error(f"Failed to send incomplete alert: {e}")

    def _publish_batch_completion(self, is_complete: bool = True):
        """Publish single Pub/Sub message to trigger batch processing."""
        try:
            from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

            # Use local date to match GCS path (GCS exporter uses local date)
            date_str = datetime.now().strftime('%Y-%m-%d')

            # Status reflects completeness - 'partial' triggers different downstream behavior
            status = 'success' if is_complete else 'partial'

            publisher = ScraperPubSubPublisher()
            message_id = publisher.publish_completion_event(
                scraper_name='espn_roster_batch',
                execution_id=f'batch_{date_str}_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                status=status,
                gcs_path=f'gs://nba-scraped-data/espn/rosters/{date_str}/',
                record_count=len(self.completed_teams),
                duration_seconds=int((self.end_time - self.start_time).total_seconds()),
                workflow='backfill',
                metadata={
                    'trigger_type': 'batch_processing',
                    'scraper_type': 'espn_roster',
                    'date': date_str,
                    'teams_scraped': len(self.completed_teams),
                    'teams_failed': len(self.failed_teams),
                    'teams': self.completed_teams,
                    'failed_teams': self.failed_teams,
                    'total_players': self.total_players,
                    'min_threshold': self.min_teams_threshold,
                    'is_complete': is_complete,
                }
            )

            status_emoji = "✅" if is_complete else "⚠️"
            logger.info(f"{status_emoji} Published batch completion: teams={len(self.completed_teams)}, "
                       f"status={status}, players={self.total_players}, message_id={message_id}")

        except Exception as e:
            logger.error(f"Failed to publish batch completion message: {e}")
            # Non-blocking - don't fail the entire backfill if Pub/Sub fails

    def _print_summary(self):
        """Print summary of backfill results."""
        duration = (self.end_time - self.start_time).total_seconds()
        is_complete = len(self.completed_teams) >= self.min_teams_threshold

        print("\n" + "=" * 60)
        print("ESPN ROSTERS BATCH BACKFILL SUMMARY")
        print("=" * 60)
        print(f"Duration: {duration:.1f} seconds")
        print(f"Teams scraped: {len(self.completed_teams)}/{len(self.teams)}")
        print(f"Completeness threshold: {self.min_teams_threshold} teams")
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
        elif is_complete:
            print(f"⚠️  {len(self.failed_teams)} teams failed, but threshold met ({len(self.completed_teams)} >= {self.min_teams_threshold})")
            print("📦 Batch completion message published (status: partial)")
        else:
            print(f"❌ INCOMPLETE: {len(self.completed_teams)} teams < {self.min_teams_threshold} threshold")
            print("🚨 Alert sent - downstream processing may be affected")


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
        '--retries',
        type=int,
        default=2,
        help='Max retry attempts for failed teams with exponential backoff (default: 2)'
    )

    parser.add_argument(
        '--min-teams',
        type=int,
        default=None,
        help='Minimum teams required for success (default: 83%% of requested teams, i.e., 25 for all 30)'
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
        debug=args.debug,
        max_retries=args.retries,
        min_teams_threshold=args.min_teams
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
