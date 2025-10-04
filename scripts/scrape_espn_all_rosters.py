#!/usr/bin/env python3
"""
FILE: scripts/scrape_espn_all_rosters.py
ESPN All Teams Roster Scraper
Scrapes roster data for all 30 NBA teams serially with rate limiting.

Usage:
    python scripts/scrape_espn_all_rosters.py [options]

Options:
    --delay SECONDS     Delay between teams (default: 3)
    --teams ABBR,...    Comma-separated team list (default: all 30)
    --retry-failed      Retry failed teams with longer delay
    --debug             Enable debug logging
    --dry-run           Show what would be scraped without executing

Examples:
    # Scrape all teams with 3 second delay
    python scripts/scrape_espn_all_rosters.py

    # Scrape specific teams with 5 second delay
    python scripts/scrape_espn_all_rosters.py --teams LAL,BOS,GSW --delay 5

    # Retry only previously failed teams
    python scripts/scrape_espn_all_rosters.py --retry-failed --delay 10

    # Test run without actually scraping
    python scripts/scrape_espn_all_rosters.py --dry-run
"""

import sys
import os
import time
import logging
import argparse
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ESPN team abbreviations (we only need the keys for iteration)
ESPN_TEAM_IDS = {
    "ATL": 1,   "BOS": 2,   "BKN": 17,  "CHA": 30,  "CHI": 4,
    "CLE": 5,   "DAL": 6,   "DEN": 7,   "DET": 8,   "GSW": 9,
    "HOU": 10,  "IND": 11,  "LAC": 12,  "LAL": 13,  "MEM": 29,
    "MIA": 14,  "MIL": 15,  "MIN": 16,  "NOP": 3,   "NYK": 18,
    "OKC": 25,  "ORL": 19,  "PHI": 20,  "PHX": 21,  "POR": 22,
    "SAC": 23,  "SAS": 24,  "TOR": 28,  "UTA": 26,  "WAS": 27
}

# Import notification system if available
try:
    from shared.utils.notification_system import notify_error, notify_info, notify_warning
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False
    def notify_error(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EspnRosterCoordinator:
    """Coordinates scraping of all NBA team rosters from ESPN."""
    
    def __init__(self, delay_seconds: int = 3, debug: bool = False, dry_run: bool = False):
        self.delay_seconds = delay_seconds
        self.dry_run = dry_run
        self.debug = debug
        
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)
            logger.setLevel(logging.DEBUG)
        
        self.results = {
            'success': [],
            'failed': [],
            'skipped': []
        }
        
        self.start_time = None
        self.end_time = None
    
    def scrape_team(self, team_abbr: str) -> Dict:
        """Scrape roster for a single team using subprocess.
        
        Returns:
            Dict with keys: team, status, player_count, error (if failed)
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would scrape {team_abbr}")
            return {
                'team': team_abbr,
                'status': 'dry_run',
                'player_count': 0
            }
        
        try:
            logger.info(f"Scraping roster for {team_abbr}...")
            
            # Build command to run scraper
            cmd = [
                sys.executable,  # Use same Python interpreter
                '-m', 'scrapers.espn.espn_roster_api',
                '--team_abbr', team_abbr,
                '--group', 'prod'  # Enable GCS export
            ]
            
            if self.debug:
                cmd.append('--debug')
            
            # Run scraper as subprocess
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..')  # Run from project root
            )
            
            if result.returncode == 0:
                # Parse player count from stdout or stderr (logs might go to either)
                player_count = 0
                import re
                
                # Check both stdout and stderr for the log line
                combined_output = result.stdout + "\n" + result.stderr
                
                for line in combined_output.split('\n'):
                    # Look for "Parsed X players for TEAM"
                    if 'Parsed' in line and 'players for' in line and team_abbr in line:
                        match = re.search(r'Parsed (\d+) players', line)
                        if match:
                            player_count = int(match.group(1))
                            break
                
                # Fallback: Check the exported JSON file if we couldn't parse from logs
                if player_count == 0:
                    try:
                        import json
                        json_file = f"/tmp/espn_roster_api_{team_abbr}.json"
                        if os.path.exists(json_file):
                            with open(json_file, 'r') as f:
                                data = json.load(f)
                                player_count = data.get('playerCount', 0)
                    except Exception as e:
                        logger.debug(f"Could not read JSON file for player count: {e}")
                
                logger.info(f"✓ {team_abbr} complete - {player_count} players")
                
                return {
                    'team': team_abbr,
                    'status': 'success',
                    'player_count': player_count
                }
            else:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                logger.error(f"✗ {team_abbr} failed: {error_msg}")
                return {
                    'team': team_abbr,
                    'status': 'failed',
                    'error': error_msg[:200]  # Truncate long errors
                }
            
        except Exception as e:
            logger.error(f"✗ {team_abbr} failed: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
            return {
                'team': team_abbr,
                'status': 'failed',
                'error': str(e)
            }
    
    def scrape_teams(self, team_list: Optional[List[str]] = None) -> Dict:
        """Scrape rosters for multiple teams serially.
        
        Args:
            team_list: List of team abbreviations. If None, scrapes all 30 teams.
        
        Returns:
            Results dict with success/failed/skipped lists
        """
        # Use all teams if none specified
        if team_list is None:
            team_list = sorted(ESPN_TEAM_IDS.keys())
        
        # Validate team abbreviations
        invalid_teams = [t for t in team_list if t not in ESPN_TEAM_IDS]
        if invalid_teams:
            logger.warning(f"Invalid team abbreviations: {invalid_teams}")
            self.results['skipped'].extend(invalid_teams)
            team_list = [t for t in team_list if t in ESPN_TEAM_IDS]
        
        if not team_list:
            logger.error("No valid teams to scrape")
            return self.results
        
        logger.info(f"Starting scrape of {len(team_list)} teams with {self.delay_seconds}s delay")
        self.start_time = datetime.now(timezone.utc)
        
        # Scrape each team
        for i, team_abbr in enumerate(team_list, 1):
            logger.info(f"[{i}/{len(team_list)}] Processing {team_abbr}...")
            
            result = self.scrape_team(team_abbr)
            
            if result['status'] == 'success':
                self.results['success'].append(result)
            elif result['status'] == 'failed':
                self.results['failed'].append(result)
            
            # Rate limiting: sleep between teams (but not after the last one)
            if i < len(team_list):
                logger.debug(f"Waiting {self.delay_seconds}s before next team...")
                time.sleep(self.delay_seconds)
        
        self.end_time = datetime.now(timezone.utc)
        return self.results
    
    def retry_failed(self, extended_delay: int = 10) -> Dict:
        """Retry teams that failed on first attempt.
        
        Args:
            extended_delay: Longer delay for retry attempts
        """
        if not self.results['failed']:
            logger.info("No failed teams to retry")
            return self.results
        
        failed_teams = [r['team'] for r in self.results['failed']]
        logger.info(f"Retrying {len(failed_teams)} failed teams with {extended_delay}s delay")
        
        # Clear failed list for retry
        retry_results = self.results['failed']
        self.results['failed'] = []
        
        # Use extended delay for retries
        original_delay = self.delay_seconds
        self.delay_seconds = extended_delay
        
        # Retry each failed team
        self.scrape_teams(failed_teams)
        
        # Restore original delay
        self.delay_seconds = original_delay
        
        return self.results
    
    def print_summary(self):
        """Print summary of scraping results."""
        if not self.start_time:
            logger.warning("No scraping performed yet")
            return
        
        # Calculate duration (handle case where end_time might be None due to interrupt)
        if self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        else:
            duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        print("\n" + "="*60)
        print("ESPN ROSTER SCRAPING SUMMARY")
        print("="*60)
        
        # Success summary
        success_count = len(self.results['success'])
        total_players = sum(r['player_count'] for r in self.results['success'])
        print(f"\n✓ Successful: {success_count} teams, {total_players} total players")
        if self.results['success']:
            print("  Teams:", ", ".join(r['team'] for r in self.results['success']))
        
        # Failed summary
        failed_count = len(self.results['failed'])
        if failed_count > 0:
            print(f"\n✗ Failed: {failed_count} teams")
            for result in self.results['failed']:
                print(f"  {result['team']}: {result.get('error', 'Unknown error')}")
        
        # Skipped summary
        skipped_count = len(self.results['skipped'])
        if skipped_count > 0:
            print(f"\n⊘ Skipped: {skipped_count} teams (invalid abbreviations)")
            print("  Teams:", ", ".join(self.results['skipped']))
        
        # Timing
        print(f"\nDuration: {duration:.1f} seconds")
        total_attempts = success_count + failed_count
        if total_attempts > 0:
            print(f"Average: {duration/total_attempts:.1f}s per team")
        
        print("="*60 + "\n")
    
    def send_notification(self):
        """Send notification about scraping results."""
        if not NOTIFICATIONS_AVAILABLE or self.dry_run:
            return
        
        success_count = len(self.results['success'])
        failed_count = len(self.results['failed'])
        total_teams = success_count + failed_count
        
        if total_teams == 0:
            return
        
        # Determine notification type
        if failed_count == 0:
            # Complete success
            notify_info(
                title="ESPN Rosters: All Teams Scraped",
                message=f"Successfully scraped rosters for all {success_count} teams",
                details={
                    'success_count': success_count,
                    'total_players': sum(r['player_count'] for r in self.results['success']),
                    'duration_seconds': (self.end_time - self.start_time).total_seconds(),
                    'teams': [r['team'] for r in self.results['success']]
                }
            )
        elif success_count == 0:
            # Complete failure
            notify_error(
                title="ESPN Rosters: All Teams Failed",
                message=f"Failed to scrape all {failed_count} teams",
                details={
                    'failed_count': failed_count,
                    'errors': self.results['failed']
                },
                processor_name="ESPN All Rosters Scraper"
            )
        else:
            # Partial success
            notify_warning(
                title="ESPN Rosters: Partial Success",
                message=f"Scraped {success_count}/{total_teams} teams successfully",
                details={
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'successful_teams': [r['team'] for r in self.results['success']],
                    'failed_teams': [r['team'] for r in self.results['failed']]
                }
            )


def main():
    parser = argparse.ArgumentParser(
        description='Scrape ESPN rosters for all NBA teams',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--delay',
        type=int,
        default=3,
        help='Delay between teams in seconds (default: 3)'
    )
    
    parser.add_argument(
        '--teams',
        type=str,
        help='Comma-separated list of team abbreviations (default: all 30 teams)'
    )
    
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Retry teams that failed on previous run'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be scraped without executing'
    )
    
    args = parser.parse_args()
    
    # Parse team list if provided
    team_list = None
    if args.teams:
        team_list = [t.strip().upper() for t in args.teams.split(',')]
    
    # Create coordinator
    coordinator = EspnRosterCoordinator(
        delay_seconds=args.delay,
        debug=args.debug,
        dry_run=args.dry_run
    )
    
    try:
        # Scrape teams
        coordinator.scrape_teams(team_list)
        
        # Retry failed if requested
        if args.retry_failed and coordinator.results['failed']:
            logger.info("\nRetrying failed teams...")
            coordinator.retry_failed(extended_delay=args.delay * 2)
        
        # Print summary
        coordinator.print_summary()
        
        # Send notification
        coordinator.send_notification()
        
        # Exit code based on results
        if coordinator.results['failed']:
            logger.warning("Some teams failed to scrape")
            sys.exit(1)
        else:
            logger.info("All teams scraped successfully")
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.warning("\nScraping interrupted by user")
        coordinator.print_summary()
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
FILE: scripts/scrape_espn_all_rosters.py
ESPN All Teams Roster Scraper
Scrapes roster data for all 30 NBA teams serially with rate limiting.

Usage:
    python scripts/scrape_espn_all_rosters.py [options]

Options:
    --delay SECONDS     Delay between teams (default: 3)
    --teams ABBR,...    Comma-separated team list (default: all 30)
    --retry-failed      Retry failed teams with longer delay
    --debug             Enable debug logging
    --dry-run           Show what would be scraped without executing

Examples:
    # Scrape all teams with 3 second delay
    python scripts/scrape_espn_all_rosters.py

    # Scrape specific teams with 5 second delay
    python scripts/scrape_espn_all_rosters.py --teams LAL,BOS,GSW --delay 5

    # Retry only previously failed teams
    python scripts/scrape_espn_all_rosters.py --retry-failed --delay 10

    # Test run without actually scraping
    python scripts/scrape_espn_all_rosters.py --dry-run
"""

import sys
import os
import time
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scrapers.espn.espn_roster_api import GetEspnTeamRosterAPI, ESPN_TEAM_IDS

# Import notification system if available
try:
    from shared.utils.notification_system import notify_error, notify_info, notify_warning
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False
    def notify_error(*args, **kwargs): pass
    def notify_info(*args, **kwargs): pass
    def notify_warning(*args, **kwargs): pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EspnRosterCoordinator:
    """Coordinates scraping of all NBA team rosters from ESPN."""
    
    def __init__(self, delay_seconds: int = 3, debug: bool = False, dry_run: bool = False):
        self.delay_seconds = delay_seconds
        self.dry_run = dry_run
        
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)
            logger.setLevel(logging.DEBUG)
        
        self.results = {
            'success': [],
            'failed': [],
            'skipped': []
        }
        
        self.start_time = None
        self.end_time = None
    
    def scrape_team(self, team_abbr: str) -> Dict:
        """Scrape roster for a single team.
        
        Returns:
            Dict with keys: team, status, player_count, error (if failed)
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would scrape {team_abbr}")
            return {
                'team': team_abbr,
                'status': 'dry_run',
                'player_count': 0
            }
        
        try:
            logger.info(f"Scraping roster for {team_abbr}...")
            
            # Create scraper instance and set options
            scraper = GetEspnTeamRosterAPI()
            
            # CRITICAL: Must set opts BEFORE calling run()
            scraper.opts = {'team_abbr': team_abbr}
            
            # Run the complete scraper workflow
            scraper.run()
            
            # Check if data was successfully scraped
            if not scraper.data:
                raise ValueError(f"No data returned for {team_abbr}")
            
            # Get player count from transformed data
            player_count = scraper.data.get('playerCount', 0)
            
            logger.info(f"✓ {team_abbr} complete - {player_count} players")
            
            return {
                'team': team_abbr,
                'status': 'success',
                'player_count': player_count
            }
            
        except Exception as e:
            logger.error(f"✗ {team_abbr} failed: {str(e)}", exc_info=logger.isEnabledFor(logging.DEBUG))
            return {
                'team': team_abbr,
                'status': 'failed',
                'error': str(e)
            }
    
    def scrape_teams(self, team_list: Optional[List[str]] = None) -> Dict:
        """Scrape rosters for multiple teams serially.
        
        Args:
            team_list: List of team abbreviations. If None, scrapes all 30 teams.
        
        Returns:
            Results dict with success/failed/skipped lists
        """
        # Use all teams if none specified
        if team_list is None:
            team_list = sorted(ESPN_TEAM_IDS.keys())
        
        # Validate team abbreviations
        invalid_teams = [t for t in team_list if t not in ESPN_TEAM_IDS]
        if invalid_teams:
            logger.warning(f"Invalid team abbreviations: {invalid_teams}")
            self.results['skipped'].extend(invalid_teams)
            team_list = [t for t in team_list if t in ESPN_TEAM_IDS]
        
        if not team_list:
            logger.error("No valid teams to scrape")
            return self.results
        
        logger.info(f"Starting scrape of {len(team_list)} teams with {self.delay_seconds}s delay")
        self.start_time = datetime.now(timezone.utc)
        
        # Scrape each team
        for i, team_abbr in enumerate(team_list, 1):
            logger.info(f"[{i}/{len(team_list)}] Processing {team_abbr}...")
            
            result = self.scrape_team(team_abbr)
            
            if result['status'] == 'success':
                self.results['success'].append(result)
            elif result['status'] == 'failed':
                self.results['failed'].append(result)
            
            # Rate limiting: sleep between teams (but not after the last one)
            if i < len(team_list):
                logger.debug(f"Waiting {self.delay_seconds}s before next team...")
                time.sleep(self.delay_seconds)
        
        self.end_time = datetime.now(timezone.utc)
        return self.results
    
    def retry_failed(self, extended_delay: int = 10) -> Dict:
        """Retry teams that failed on first attempt.
        
        Args:
            extended_delay: Longer delay for retry attempts
        """
        if not self.results['failed']:
            logger.info("No failed teams to retry")
            return self.results
        
        failed_teams = [r['team'] for r in self.results['failed']]
        logger.info(f"Retrying {len(failed_teams)} failed teams with {extended_delay}s delay")
        
        # Clear failed list for retry
        retry_results = self.results['failed']
        self.results['failed'] = []
        
        # Use extended delay for retries
        original_delay = self.delay_seconds
        self.delay_seconds = extended_delay
        
        # Retry each failed team
        self.scrape_teams(failed_teams)
        
        # Restore original delay
        self.delay_seconds = original_delay
        
        return self.results
    
    def print_summary(self):
        """Print summary of scraping results."""
        if not self.start_time:
            logger.warning("No scraping performed yet")
            return
        
        # Calculate duration (handle case where end_time might be None due to interrupt)
        if self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        else:
            duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        print("\n" + "="*60)
        print("ESPN ROSTER SCRAPING SUMMARY")
        print("="*60)
        
        # Success summary
        success_count = len(self.results['success'])
        total_players = sum(r['player_count'] for r in self.results['success'])
        print(f"\n✓ Successful: {success_count} teams, {total_players} total players")
        if self.results['success']:
            print("  Teams:", ", ".join(r['team'] for r in self.results['success']))
        
        # Failed summary
        failed_count = len(self.results['failed'])
        if failed_count > 0:
            print(f"\n✗ Failed: {failed_count} teams")
            for result in self.results['failed']:
                print(f"  {result['team']}: {result.get('error', 'Unknown error')}")
        
        # Skipped summary
        skipped_count = len(self.results['skipped'])
        if skipped_count > 0:
            print(f"\n⊘ Skipped: {skipped_count} teams (invalid abbreviations)")
            print("  Teams:", ", ".join(self.results['skipped']))
        
        # Timing
        print(f"\nDuration: {duration:.1f} seconds")
        total_attempts = success_count + failed_count
        if total_attempts > 0:
            print(f"Average: {duration/total_attempts:.1f}s per team")
        
        print("="*60 + "\n")
    
    def send_notification(self):
        """Send notification about scraping results."""
        if not NOTIFICATIONS_AVAILABLE or self.dry_run:
            return
        
        success_count = len(self.results['success'])
        failed_count = len(self.results['failed'])
        total_teams = success_count + failed_count
        
        if total_teams == 0:
            return
        
        # Determine notification type
        if failed_count == 0:
            # Complete success
            notify_info(
                title="ESPN Rosters: All Teams Scraped",
                message=f"Successfully scraped rosters for all {success_count} teams",
                details={
                    'success_count': success_count,
                    'total_players': sum(r['player_count'] for r in self.results['success']),
                    'duration_seconds': (self.end_time - self.start_time).total_seconds(),
                    'teams': [r['team'] for r in self.results['success']]
                }
            )
        elif success_count == 0:
            # Complete failure
            notify_error(
                title="ESPN Rosters: All Teams Failed",
                message=f"Failed to scrape all {failed_count} teams",
                details={
                    'failed_count': failed_count,
                    'errors': self.results['failed']
                },
                processor_name="ESPN All Rosters Scraper"
            )
        else:
            # Partial success
            notify_warning(
                title="ESPN Rosters: Partial Success",
                message=f"Scraped {success_count}/{total_teams} teams successfully",
                details={
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'successful_teams': [r['team'] for r in self.results['success']],
                    'failed_teams': [r['team'] for r in self.results['failed']]
                }
            )


def main():
    parser = argparse.ArgumentParser(
        description='Scrape ESPN rosters for all NBA teams',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--delay',
        type=int,
        default=3,
        help='Delay between teams in seconds (default: 3)'
    )
    
    parser.add_argument(
        '--teams',
        type=str,
        help='Comma-separated list of team abbreviations (default: all 30 teams)'
    )
    
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Retry teams that failed on previous run'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be scraped without executing'
    )
    
    args = parser.parse_args()
    
    # Parse team list if provided
    team_list = None
    if args.teams:
        team_list = [t.strip().upper() for t in args.teams.split(',')]
    
    # Create coordinator
    coordinator = EspnRosterCoordinator(
        delay_seconds=args.delay,
        debug=args.debug,
        dry_run=args.dry_run
    )
    
    try:
        # Scrape teams
        coordinator.scrape_teams(team_list)
        
        # Retry failed if requested
        if args.retry_failed and coordinator.results['failed']:
            logger.info("\nRetrying failed teams...")
            coordinator.retry_failed(extended_delay=args.delay * 2)
        
        # Print summary
        coordinator.print_summary()
        
        # Send notification
        coordinator.send_notification()
        
        # Exit code based on results
        if coordinator.results['failed']:
            logger.warning("Some teams failed to scrape")
            sys.exit(1)
        else:
            logger.info("All teams scraped successfully")
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.warning("\nScraping interrupted by user")
        coordinator.print_summary()
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()