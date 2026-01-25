#!/usr/bin/env python3
# File: validation/validators/raw/props_availability_validator.py
# Description: Validator for props availability - alerts when games have insufficient betting lines
"""
Props Availability Validator

Critical validator for alerting when games have missing or insufficient betting lines.
This is a HIGH PRIORITY validator requested by the user to catch situations where
we have no props data for scheduled games.

Key features:
- Alerts when games have ZERO betting lines (CRITICAL)
- Warns when games have < 3 players with props (CRITICAL threshold)
- Warns when games have < 8 players with props (WARNING threshold)
- Tracks which bookmakers/sources were checked
- Provides actionable recommendations
- Returns results suitable for automated alerting

Alert message format example:
    🚨 CRITICAL: BOS @ CHI has ZERO betting lines from any source
    - Checked: BettingPros, Odds API
    - Game time: 7:00 PM ET
    - Recommendation: Manually verify on DraftKings app if props are offered
    - Possible causes: Scraper bug, DraftKings not offering props, API outage
"""

import sys
import os
import time
from typing import Optional, List, Dict
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from validation.base_validator import BaseValidator, ValidationResult
import logging

logger = logging.getLogger(__name__)


class PropsAvailabilityValidator(BaseValidator):
    """
    Validator for props availability across scheduled games.

    Thresholds:
    - CRITICAL: 0 props (game has no betting lines at all)
    - CRITICAL: < 3 players with props
    - WARNING: < 8 players with props
    - INFO: >= 8 players with props

    Checks:
    1. Games with zero props from any source
    2. Games with insufficient player coverage
    3. Bookmaker coverage per game
    4. Source availability tracking
    """

    # Alert thresholds
    CRITICAL_PLAYER_THRESHOLD = 3   # < 3 players is critical
    WARNING_PLAYER_THRESHOLD = 8    # < 8 players is warning

    def _run_custom_validations(
        self,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Run props availability-specific validations"""

        logger.info("Running props availability custom validations...")

        # Check 1: Games with ZERO props (most critical)
        self._validate_zero_props_games(start_date, end_date)

        # Check 2: Games with insufficient player coverage
        self._validate_player_coverage(start_date, end_date)

        # Check 3: Bookmaker coverage (which sources have data)
        self._validate_bookmaker_coverage(start_date, end_date)

        # Check 4: Props freshness (are lines stale?)
        self._validate_props_freshness(start_date, end_date)

        logger.info("Completed props availability validations")

    def _validate_zero_props_games(self, start_date: str, end_date: str):
        """Check for games with ZERO betting lines from any source - CRITICAL"""

        check_start = time.time()

        query = f"""
        WITH scheduled_games AS (
          SELECT
            s.game_id,
            s.game_date,
            s.home_team_tricode,
            s.away_team_tricode,
            s.game_time_et,
            s.game_status_text
          FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest` s
          WHERE s.game_date >= '{start_date}'
            AND s.game_date <= '{end_date}'
            AND s.game_status_text IN ('Scheduled', 'InProgress')
        ),
        props_games AS (
          SELECT DISTINCT
            game_id,
            COUNT(DISTINCT player_lookup) as player_count,
            COUNT(DISTINCT bookmaker) as bookmaker_count,
            STRING_AGG(DISTINCT bookmaker ORDER BY bookmaker LIMIT 5) as bookmakers
          FROM `{self.project_id}.nba_raw.odds_api_props`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          GROUP BY game_id
        )
        SELECT
          s.game_id,
          s.game_date,
          s.home_team_tricode,
          s.away_team_tricode,
          s.game_time_et,
          s.game_status_text,
          COALESCE(p.player_count, 0) as player_count,
          COALESCE(p.bookmaker_count, 0) as bookmaker_count,
          COALESCE(p.bookmakers, 'None') as bookmakers_found
        FROM scheduled_games s
        LEFT JOIN props_games p ON s.game_id = p.game_id
        WHERE p.game_id IS NULL  -- Games with NO props at all
        ORDER BY s.game_date, s.game_time_et
        LIMIT 30
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            zero_props_games = []

            for row in result:
                game_detail = {
                    'game_id': row.game_id,
                    'game_date': str(row.game_date),
                    'matchup': f"{row.away_team_tricode} @ {row.home_team_tricode}",
                    'game_time': row.game_time_et.strftime('%I:%M %p ET') if row.game_time_et else 'TBD',
                    'status': row.game_status_text,
                    'bookmakers_checked': row.bookmakers_found
                }
                zero_props_games.append(game_detail)

            passed = len(zero_props_games) == 0
            duration = time.time() - check_start

            # Build detailed alert messages
            affected_items = []
            for game in zero_props_games[:10]:  # First 10 games
                alert_msg = (
                    f"{game['matchup']} ({game['game_date']}) - "
                    f"Game time: {game['game_time']} - "
                    f"Status: {game['status']}"
                )
                affected_items.append(alert_msg)

            # Build remediation
            remediation = []
            if zero_props_games:
                remediation.extend([
                    "🚨 CRITICAL: Games with ZERO betting lines detected",
                    "",
                    "Immediate Actions:",
                    "1. Manually verify on DraftKings app if props are being offered",
                    "2. Check if BettingPros API is operational",
                    "3. Check Odds API status and quota limits",
                    "4. Verify scraper logs for errors",
                    "",
                    "Possible Causes:",
                    "- Scraper bug preventing data collection",
                    "- DraftKings/bookmakers not offering props for these games",
                    "- API outage or rate limiting",
                    "- Network connectivity issues",
                    "- Game postponed/cancelled (check schedule status)",
                    "",
                    "Investigation Commands:",
                    f"# Check scraper logs",
                    f"gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=odds-api-scraper' --limit 50",
                    f"",
                    f"# Manually trigger scraper for {zero_props_games[0]['game_date']}",
                    f"python scrapers/odds_api/odds_api_props.py --date {zero_props_games[0]['game_date']} --force"
                ])

            self.results.append(ValidationResult(
                check_name="zero_props_games",
                check_type="availability",
                layer="bigquery",
                passed=passed,
                severity="critical" if not passed else "info",
                message=f"🚨 CRITICAL: {len(zero_props_games)} games have ZERO betting lines" if not passed else "All scheduled games have betting lines",
                affected_count=len(zero_props_games),
                affected_items=affected_items,
                remediation=remediation if not passed else [],
                query_used=query,
                execution_duration=duration
            ))

            if not passed:
                logger.critical(f"🚨 Zero props alert: {len(zero_props_games)} games missing ALL betting lines")
                for game in zero_props_games[:5]:
                    logger.critical(f"  - {game['matchup']} on {game['game_date']} at {game['game_time']}")

        except Exception as e:
            logger.error(f"Zero props validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="zero_props_games",
                check_type="availability",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_player_coverage(self, start_date: str, end_date: str):
        """Check for games with insufficient player props coverage"""

        check_start = time.time()

        query = f"""
        WITH scheduled_games AS (
          SELECT
            s.game_id,
            s.game_date,
            s.home_team_tricode,
            s.away_team_tricode,
            s.game_time_et,
            s.game_status_text
          FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest` s
          WHERE s.game_date >= '{start_date}'
            AND s.game_date <= '{end_date}'
            AND s.game_status_text IN ('Scheduled', 'InProgress')
        ),
        props_coverage AS (
          SELECT
            game_id,
            COUNT(DISTINCT player_lookup) as player_count,
            COUNT(DISTINCT bookmaker) as bookmaker_count,
            STRING_AGG(DISTINCT bookmaker ORDER BY bookmaker LIMIT 5) as bookmakers,
            ARRAY_AGG(DISTINCT player_name ORDER BY player_name LIMIT 20) as sample_players
          FROM `{self.project_id}.nba_raw.odds_api_props`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          GROUP BY game_id
        )
        SELECT
          s.game_id,
          s.game_date,
          s.home_team_tricode,
          s.away_team_tricode,
          s.game_time_et,
          s.game_status_text,
          COALESCE(p.player_count, 0) as player_count,
          COALESCE(p.bookmaker_count, 0) as bookmaker_count,
          COALESCE(p.bookmakers, 'None') as bookmakers,
          p.sample_players
        FROM scheduled_games s
        LEFT JOIN props_coverage p ON s.game_id = p.game_id
        WHERE COALESCE(p.player_count, 0) < {self.WARNING_PLAYER_THRESHOLD}
        ORDER BY COALESCE(p.player_count, 0) ASC, s.game_date, s.game_time_et
        LIMIT 50
        """

        try:
            result = self._execute_query(query, start_date, end_date)

            critical_games = []  # < 3 players
            warning_games = []   # < 8 players

            for row in result:
                game_detail = {
                    'game_id': row.game_id,
                    'game_date': str(row.game_date),
                    'matchup': f"{row.away_team_tricode} @ {row.home_team_tricode}",
                    'game_time': row.game_time_et.strftime('%I:%M %p ET') if row.game_time_et else 'TBD',
                    'player_count': row.player_count,
                    'bookmaker_count': row.bookmaker_count,
                    'bookmakers': row.bookmakers,
                    'sample_players': ', '.join(row.sample_players[:5]) if row.sample_players else 'None'
                }

                if row.player_count < self.CRITICAL_PLAYER_THRESHOLD:
                    critical_games.append(game_detail)
                else:
                    warning_games.append(game_detail)

            # Determine severity
            if critical_games:
                severity = "critical"
                passed = False
                message = f"🚨 CRITICAL: {len(critical_games)} games have < {self.CRITICAL_PLAYER_THRESHOLD} players with props"
            elif warning_games:
                severity = "warning"
                passed = False
                message = f"⚠️ WARNING: {len(warning_games)} games have < {self.WARNING_PLAYER_THRESHOLD} players with props"
            else:
                severity = "info"
                passed = True
                message = f"All games have adequate player props coverage (>= {self.WARNING_PLAYER_THRESHOLD} players)"

            # Build affected items
            affected_items = []

            if critical_games:
                affected_items.append("🚨 CRITICAL (< 3 players):")
                for game in critical_games[:5]:
                    affected_items.append(
                        f"  {game['matchup']} ({game['game_date']}) - "
                        f"{game['player_count']} players - "
                        f"Bookmakers: {game['bookmakers']}"
                    )

            if warning_games:
                affected_items.append("")
                affected_items.append("⚠️ WARNING (3-7 players):")
                for game in warning_games[:5]:
                    affected_items.append(
                        f"  {game['matchup']} ({game['game_date']}) - "
                        f"{game['player_count']} players - "
                        f"Bookmakers: {game['bookmakers']}"
                    )

            # Build remediation
            remediation = []
            if critical_games or warning_games:
                remediation.extend([
                    "Recommended Actions:",
                    "1. Check if DraftKings app shows props for these games",
                    "2. Verify injury reports - star players out reduces prop offerings",
                    "3. Check game status - some bookmakers don't offer props for certain game types",
                    "4. Run manual scraper for affected dates",
                    "",
                    "Common Causes:",
                    "- Bookmakers limiting props due to injury uncertainty",
                    "- Back-to-back games (reduced offerings)",
                    "- National TV games (sometimes delayed prop postings)",
                    "- Scraper captured data before full props posted",
                    "",
                    "Quick Fix:",
                    f"python scrapers/odds_api/odds_api_props.py --date {critical_games[0]['game_date'] if critical_games else warning_games[0]['game_date']} --force"
                ])

            duration = time.time() - check_start

            self.results.append(ValidationResult(
                check_name="player_props_coverage",
                check_type="availability",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=message,
                affected_count=len(critical_games) + len(warning_games),
                affected_items=affected_items[:30],
                remediation=remediation if not passed else [],
                query_used=query,
                execution_duration=duration
            ))

            if critical_games:
                logger.critical(f"🚨 Insufficient props: {len(critical_games)} games with < 3 players")
            elif warning_games:
                logger.warning(f"⚠️ Low props coverage: {len(warning_games)} games with < 8 players")

        except Exception as e:
            logger.error(f"Player coverage validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="player_props_coverage",
                check_type="availability",
                layer="bigquery",
                passed=False,
                severity="error",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_bookmaker_coverage(self, start_date: str, end_date: str):
        """Check which bookmakers/sources have data - diagnostic info"""

        check_start = time.time()

        query = f"""
        SELECT
          bookmaker,
          COUNT(DISTINCT game_id) as games_covered,
          COUNT(DISTINCT player_lookup) as players_covered,
          COUNT(*) as total_props,
          MIN(scraped_at) as earliest_scrape,
          MAX(scraped_at) as latest_scrape
        FROM `{self.project_id}.nba_raw.odds_api_props`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY bookmaker
        ORDER BY games_covered DESC, total_props DESC
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            bookmaker_stats = []

            for row in result:
                stat = {
                    'bookmaker': row.bookmaker,
                    'games': row.games_covered,
                    'players': row.players_covered,
                    'props': row.total_props,
                    'latest_scrape': row.latest_scrape.strftime('%Y-%m-%d %H:%M:%S') if row.latest_scrape else 'Unknown'
                }
                bookmaker_stats.append(stat)

            passed = len(bookmaker_stats) >= 1  # At least one bookmaker should have data
            duration = time.time() - check_start

            affected_items = [
                f"{stat['bookmaker']}: {stat['games']} games, {stat['players']} players, "
                f"{stat['props']} props (last: {stat['latest_scrape']})"
                for stat in bookmaker_stats
            ]

            self.results.append(ValidationResult(
                check_name="bookmaker_coverage",
                check_type="availability",
                layer="bigquery",
                passed=passed,
                severity="info",
                message=f"Bookmaker coverage: {len(bookmaker_stats)} sources with data" if passed else "No bookmaker data found",
                affected_count=len(bookmaker_stats),
                affected_items=affected_items,
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Bookmaker coverage validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="bookmaker_coverage",
                check_type="availability",
                layer="bigquery",
                passed=False,
                severity="warning",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))

    def _validate_props_freshness(self, start_date: str, end_date: str):
        """Check if props data is fresh (not stale)"""

        check_start = time.time()

        query = f"""
        WITH game_props AS (
          SELECT
            game_id,
            game_date,
            MAX(scraped_at) as latest_scrape,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(scraped_at), HOUR) as hours_old
          FROM `{self.project_id}.nba_raw.odds_api_props`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
          GROUP BY game_id, game_date
        ),
        scheduled AS (
          SELECT
            game_id,
            game_date,
            game_time_et,
            home_team_tricode,
            away_team_tricode
          FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
          WHERE game_date >= '{start_date}'
            AND game_date <= '{end_date}'
            AND game_status_text IN ('Scheduled', 'InProgress')
        )
        SELECT
          s.game_id,
          s.game_date,
          s.home_team_tricode,
          s.away_team_tricode,
          p.hours_old,
          p.latest_scrape
        FROM scheduled s
        JOIN game_props p ON s.game_id = p.game_id
        WHERE p.hours_old > 6  -- Props older than 6 hours
        ORDER BY p.hours_old DESC
        LIMIT 20
        """

        try:
            result = self._execute_query(query, start_date, end_date)
            stale_games = []

            for row in result:
                game_detail = {
                    'game_id': row.game_id,
                    'matchup': f"{row.away_team_tricode} @ {row.home_team_tricode}",
                    'game_date': str(row.game_date),
                    'hours_old': row.hours_old,
                    'latest_scrape': row.latest_scrape.strftime('%Y-%m-%d %H:%M:%S') if row.latest_scrape else 'Unknown'
                }
                stale_games.append(game_detail)

            passed = len(stale_games) == 0
            duration = time.time() - check_start

            severity = "warning" if len(stale_games) > 3 else "info" if not passed else "info"

            affected_items = [
                f"{game['matchup']} ({game['game_date']}) - "
                f"{game['hours_old']:.1f} hours old (scraped: {game['latest_scrape']})"
                for game in stale_games[:10]
            ]

            remediation = []
            if stale_games:
                remediation = [
                    "Props data is stale - consider re-scraping:",
                    f"python scrapers/odds_api/odds_api_props.py --date {stale_games[0]['game_date']} --force"
                ]

            self.results.append(ValidationResult(
                check_name="props_freshness",
                check_type="freshness",
                layer="bigquery",
                passed=passed,
                severity=severity,
                message=f"{len(stale_games)} games have props data >6 hours old" if not passed else "All props data is fresh",
                affected_count=len(stale_games),
                affected_items=affected_items,
                remediation=remediation,
                query_used=query,
                execution_duration=duration
            ))

        except Exception as e:
            logger.error(f"Props freshness validation failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="props_freshness",
                check_type="freshness",
                layer="bigquery",
                passed=False,
                severity="warning",
                message=f"Validation failed: {str(e)}",
                execution_duration=duration
            ))


def main():
    """Run validation from command line"""
    import argparse
    from datetime import date, timedelta

    parser = argparse.ArgumentParser(
        description='Validate props availability for scheduled games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check today's games
  python props_availability_validator.py --last-days 1

  # Check next 3 days (for upcoming games)
  python props_availability_validator.py --start-date 2026-01-25 --end-date 2026-01-28

  # Check without sending alerts
  python props_availability_validator.py --last-days 3 --no-notify

  # Verbose mode for debugging
  python props_availability_validator.py --last-days 1 --verbose

Alert Thresholds:
  - CRITICAL: Games with 0 props or < 3 players with props
  - WARNING: Games with < 8 players with props
  - INFO: Games with adequate coverage (>= 8 players)
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--last-days', type=int, default=3, help='Validate last N days (default: 3)')
    parser.add_argument('--no-notify', action='store_true', help='Disable notifications')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Initialize validator
    config_path = 'validation/configs/raw/props_availability.yaml'

    try:
        validator = PropsAvailabilityValidator(config_path)
    except Exception as e:
        logger.error(f"Failed to initialize validator: {e}")
        logger.info("Note: You may need to create the config file first")
        sys.exit(1)

    # Determine date range
    if args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        # Default: last N days (usually check recent + upcoming)
        end_date = (date.today() + timedelta(days=1)).isoformat()  # Include tomorrow
        start_date = (date.today() - timedelta(days=args.last_days)).isoformat()

    logger.info(f"Checking props availability from {start_date} to {end_date}")

    # Run validation
    try:
        report = validator.validate(
            start_date=start_date,
            end_date=end_date,
            notify=not args.no_notify,
            output_mode='detailed'
        )

        # Exit with appropriate code
        if report.overall_status == 'fail':
            logger.error("Validation FAILED - critical issues detected")
            sys.exit(1)
        elif report.overall_status == 'warn':
            logger.warning("Validation WARNED - some issues detected")
            sys.exit(2)
        else:
            logger.info("Validation PASSED - all checks successful")
            sys.exit(0)

    except Exception as e:
        logger.error(f"Validation execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
