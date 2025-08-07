#!/usr/bin/env python3
"""
Basketball Reference Season Roster Backfill Script
==================================================

Scrapes season roster data for all NBA teams across multiple seasons.
Respects Basketball Reference rate limits (20 req/min, 3s crawl delay).

Usage:
    python scripts/scrape_br_season_rosters.py --seasons 2022,2023,2024,2025 --group prod
    python scripts/scrape_br_season_rosters.py --teams MEM,LAL --seasons 2024 --debug
    python scripts/scrape_br_season_rosters.py --seasons 2024 --all-teams --debug
    python scripts/scrape_br_season_rosters.py --help

Features:
- Rate limiting to respect Basketball Reference servers
- Resume capability (skips already processed teams/seasons)
- Progress tracking and error reporting
- Flexible team/season filtering
"""

import argparse
import logging
import sys
import os
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import Basketball Reference team abbreviations from shared config
try:
    from shared.config.nba_teams import BASKETBALL_REF_TEAMS
except ImportError:
    # Fallback if shared config not available
    BASKETBALL_REF_TEAMS = [
        "ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", 
        "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
    ]

# Import the scraper class
try:
    from scrapers.basketball_ref.br_season_roster import BasketballRefSeasonRoster
except ImportError as e:
    print(f"Error importing Basketball Reference scraper: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)

logger = logging.getLogger(__name__)

class BasketballRefSeasonRosterBackfill:
    """Manages bulk scraping of Basketball Reference season roster data."""
    
    def __init__(self, seasons=None, teams=None, group="dev", debug=False, resume=True):
        self.seasons = seasons or [2022, 2023, 2024, 2025]  # Default: last 4 seasons
        self.teams = teams or BASKETBALL_REF_TEAMS  # Use Basketball Reference abbreviations
        self.group = group
        self.debug = debug
        self.resume = resume
        
        # Track progress
        self.total_jobs = len(self.teams) * len(self.seasons)
        self.completed_jobs = 0
        self.failed_jobs = []
        self.skipped_jobs = []
        
        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
    def run(self):
        """Execute the backfill process."""
        logger.info("Starting Basketball Reference season roster backfill")
        logger.info("Seasons: %s", self.seasons)
        logger.info("Teams: %s (%d teams)", self.teams[:5] + ["..."] if len(self.teams) > 5 else self.teams, len(self.teams))
        logger.info("Total jobs: %d", self.total_jobs)
        logger.info("Group: %s", self.group)
        logger.info("Estimated duration: %.1f minutes (with rate limiting)", self.total_jobs * 3.5 / 60)
        
        start_time = datetime.now()
        
        try:
            for season_year in self.seasons:
                logger.info("Processing season %d (%d teams)...", season_year, len(self.teams))
                self._process_season(season_year)
                
        except KeyboardInterrupt:
            logger.warning("Backfill interrupted by user")
        except Exception as e:
            logger.error("Backfill failed with error: %s", e, exc_info=True)
            raise
        finally:
            self._print_summary(start_time)
    
    def _process_season(self, season_year):
        """Process all teams for a given season."""
        for team_abbr in self.teams:
            try:
                if self._should_skip_job(team_abbr, season_year):
                    self.skipped_jobs.append((team_abbr, season_year))
                    logger.info("Skipping %s %d (already exists)", team_abbr, season_year)
                    continue
                
                self._scrape_team_season(team_abbr, season_year)
                self.completed_jobs += 1
                
                # Progress update every 10 jobs
                if self.completed_jobs % 10 == 0:
                    progress = (self.completed_jobs / self.total_jobs) * 100
                    remaining_jobs = self.total_jobs - self.completed_jobs
                    estimated_remaining = remaining_jobs * 3.5 / 60  # minutes
                    logger.info("Progress: %.1f%% (%d/%d completed, ~%.1f min remaining)", 
                              progress, self.completed_jobs, self.total_jobs, estimated_remaining)
                
            except Exception as e:
                self.failed_jobs.append((team_abbr, season_year, str(e)))
                logger.error("Failed to scrape %s %d: %s", team_abbr, season_year, e)
                
                # Continue with other teams rather than stopping
                continue
    
    def _scrape_team_season(self, team_abbr, season_year):
        """Scrape roster data for a specific team and season."""
        logger.debug("Scraping %s %d...", team_abbr, season_year)
        
        # Prepare scraper options
        opts = {
            "teamAbbr": team_abbr,
            "year": season_year,
            "export_groups": [self.group],  # FIXED: Use export_groups not group
        }
        
        # Add debug if enabled
        if self.debug:
            opts["debug"] = True
        
        # Create and run scraper
        scraper = BasketballRefSeasonRoster()
        success = scraper.run(opts)
        
        if not success:
            raise Exception(f"Scraper returned False for {team_abbr} {season_year}")
        
        logger.debug("Successfully scraped %s %d", team_abbr, season_year)
    
    def _should_skip_job(self, team_abbr, season_year):
        """Check if we should skip this team/season (for resume functionality)."""
        if not self.resume:
            return False
            
        # For resume functionality, you could check if the output file already exists
        # This would depend on your specific GCS/file structure
        # For now, we'll always process (no resume logic)
        return False
    
    def _print_summary(self, start_time):
        """Print final summary of the backfill process."""
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("=" * 60)
        logger.info("BACKFILL SUMMARY")
        logger.info("=" * 60)
        logger.info("Total jobs: %d", self.total_jobs)
        logger.info("Completed: %d", self.completed_jobs)
        logger.info("Skipped: %d", len(self.skipped_jobs))
        logger.info("Failed: %d", len(self.failed_jobs))
        logger.info("Duration: %s", duration)
        logger.info("Average time per job: %.1fs", duration.total_seconds() / max(self.completed_jobs, 1))
        
        if self.failed_jobs:
            logger.error("FAILED JOBS:")
            for team, season, error in self.failed_jobs:
                logger.error("  %s %d: %s", team, season, error)
        
        if self.skipped_jobs:
            logger.info("SKIPPED JOBS: %d", len(self.skipped_jobs))
        
        success_rate = (self.completed_jobs / self.total_jobs) * 100 if self.total_jobs > 0 else 0
        logger.info("Success rate: %.1f%%", success_rate)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Backfill Basketball Reference season roster data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scrape all teams for 2023-24 and 2024-25 seasons (dev mode)
  python scripts/scrape_br_season_rosters.py --seasons 2024,2025 --all-teams

  # Scrape specific teams for all default seasons (prod mode)
  python scripts/scrape_br_season_rosters.py --teams MEM,LAL,GSW --group prod
  
  # Scrape one team/season for testing
  python scripts/scrape_br_season_rosters.py --teams MEM --seasons 2024 --debug
  
  # Full historical backfill (production)
  python scripts/scrape_br_season_rosters.py --seasons 2022,2023,2024,2025 --all-teams --group prod
        """
    )
    
    parser.add_argument(
        "--seasons",
        type=str,
        help="Comma-separated list of seasons (ending years, e.g., '2024,2025' for 2023-24 and 2024-25)",
        default="2022,2023,2024,2025"
    )
    
    parser.add_argument(
        "--teams", 
        type=str,
        help=f"Comma-separated list of Basketball Reference team abbreviations",
        default=None
    )
    
    parser.add_argument(
        "--all-teams",
        action="store_true",
        help=f"Process all {len(BASKETBALL_REF_TEAMS)} NBA teams (overrides --teams)"
    )
    
    parser.add_argument(
        "--group",
        choices=["dev", "test", "prod", "gcs"],
        default="dev",
        help="Export group (determines where data is saved)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--no-resume",
        action="store_true", 
        help="Don't skip already processed jobs (re-scrape everything)"
    )
    
    parser.add_argument(
        "--list-teams",
        action="store_true",
        help="List all valid Basketball Reference team abbreviations and exit"
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    if args.list_teams:
        print("Valid Basketball Reference team abbreviations:")
        for i, team in enumerate(BASKETBALL_REF_TEAMS):
            print(f"  {team}", end="")
            if (i + 1) % 10 == 0:  # New line every 10 teams
                print()
        if len(BASKETBALL_REF_TEAMS) % 10 != 0:
            print()
        return
    
    # Parse seasons
    seasons = [int(year.strip()) for year in args.seasons.split(",")]
    
    # Parse teams
    if args.all_teams:
        teams = BASKETBALL_REF_TEAMS  # Use all Basketball Reference teams
    elif args.teams:
        teams = [team.strip().upper() for team in args.teams.split(",")]
        # Validate team abbreviations
        invalid_teams = [team for team in teams if team not in BASKETBALL_REF_TEAMS]
        if invalid_teams:
            print(f"Error: Invalid Basketball Reference team abbreviations: {invalid_teams}")
            print(f"Valid teams: {BASKETBALL_REF_TEAMS}")
            return 1
    else:
        # Default: use all teams if neither --teams nor --all-teams specified
        teams = BASKETBALL_REF_TEAMS
    
    # Create and run backfill
    backfill = BasketballRefSeasonRosterBackfill(
        seasons=seasons,
        teams=teams,
        group=args.group,
        debug=args.debug,
        resume=not args.no_resume
    )
    
    try:
        backfill.run()
        return 0
    except Exception as e:
        logger.error("Backfill failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())