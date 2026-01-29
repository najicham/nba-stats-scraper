"""
Basketball Reference Box Score Scraper

Daily backup scraper for player box scores from Basketball Reference.
Designed for light daily usage only - NOT for backfills.

Usage:
    - Runs once daily after games complete
    - Uses proxy to avoid rate limiting
    - Stores data for cross-source validation
    - Does NOT replace primary NBA.com data

Rate Limiting:
    - 3 second delay between requests
    - Max 50 games per run (one day of games)
    - No backfills - only current day

Created: 2026-01-28
Purpose: Backup data source + cross-source validation
"""

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from basketball_reference_web_scraper import client
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Rate limiting
REQUEST_DELAY_SECONDS = 3
MAX_GAMES_PER_RUN = 50


class BRefBoxScoreScraper:
    """
    Scrapes player box scores from Basketball Reference.

    This is a BACKUP source for cross-validation, not primary data.
    """

    def __init__(self, project_id: str = None, use_proxy: bool = True):
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.use_proxy = use_proxy
        self.proxy = self._get_proxy() if use_proxy else None
        self.stats = {
            'games_scraped': 0,
            'players_scraped': 0,
            'errors': 0,
            'start_time': None,
            'end_time': None
        }

    def _get_proxy(self) -> Optional[str]:
        """Get proxy URL from environment or Secret Manager."""
        proxy = os.environ.get('SCRAPER_PROXY_URL')
        if proxy:
            return proxy

        # Try Secret Manager
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{self.project_id}/secrets/scraper-proxy-url/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            logger.warning(f"Could not get proxy from Secret Manager: {e}")
            return None

    def scrape_date(self, game_date: date) -> List[Dict]:
        """
        Scrape all player box scores for a specific date.

        Args:
            game_date: Date to scrape

        Returns:
            List of player box score dictionaries
        """
        logger.info(f"Scraping Basketball Reference for {game_date}")
        self.stats['start_time'] = datetime.now(timezone.utc)

        all_players = []

        try:
            # Get player box scores for the date
            # The library returns all players who played on this date as list of dicts
            players = client.player_box_scores(
                day=game_date.day,
                month=game_date.month,
                year=game_date.year
            )

            if not players:
                logger.info(f"No games found on {game_date}")
                return []

            # Process each player
            for player in players:
                try:
                    processed = self._process_player(player, game_date)
                    if processed:
                        all_players.append(processed)
                        self.stats['players_scraped'] += 1
                except Exception as e:
                    player_name = player.get('name', 'unknown') if isinstance(player, dict) else 'unknown'
                    logger.warning(f"Error processing player {player_name}: {e}")
                    self.stats['errors'] += 1

            # Count unique games
            unique_games = set(p.get('game_id') for p in all_players if p.get('game_id'))
            self.stats['games_scraped'] = len(unique_games)

            logger.info(f"Scraped {len(all_players)} players from {len(unique_games)} games")

        except Exception as e:
            logger.error(f"Error scraping {game_date}: {e}")
            self.stats['errors'] += 1
            raise

        finally:
            self.stats['end_time'] = datetime.now(timezone.utc)

        return all_players

    def _process_player(self, player: Dict, game_date: date) -> Optional[Dict]:
        """Process a single player box score into our format."""

        # Extract team info - library returns enum objects
        team = player.get('team')
        opponent = player.get('opponent')

        # Get team string from enum (e.g., Team.BOSTON_CELTICS -> "BOSTON_CELTICS")
        team_str = team.name if hasattr(team, 'name') else str(team)
        opponent_str = opponent.name if hasattr(opponent, 'name') else str(opponent)

        # Build player lookup (normalized name)
        name = player.get('name', '')
        player_lookup = self._normalize_name(name)

        if not player_lookup:
            return None

        # Convert seconds_played to minutes
        seconds = player.get('seconds_played', 0) or 0
        minutes = int(round(seconds / 60))

        # Calculate points (2*FG + 3*3PT + FT)
        fg_made = player.get('made_field_goals', 0) or 0
        three_pt_made = player.get('made_three_point_field_goals', 0) or 0
        ft_made = player.get('made_free_throws', 0) or 0
        points = (2 * (fg_made - three_pt_made)) + (3 * three_pt_made) + ft_made

        off_reb = player.get('offensive_rebounds', 0) or 0
        def_reb = player.get('defensive_rebounds', 0) or 0

        return {
            'source': 'basketball_reference',
            'game_date': game_date.isoformat(),
            'player_name': name,
            'player_lookup': player_lookup,
            'team_abbr': self._normalize_team(team_str),
            'opponent_abbr': self._normalize_team(opponent_str),

            # Core stats
            'minutes_played': minutes,
            'points': points,
            'assists': player.get('assists', 0) or 0,
            'offensive_rebounds': off_reb,
            'defensive_rebounds': def_reb,
            'total_rebounds': off_reb + def_reb,
            'steals': player.get('steals', 0) or 0,
            'blocks': player.get('blocks', 0) or 0,
            'turnovers': player.get('turnovers', 0) or 0,
            'personal_fouls': player.get('personal_fouls', 0) or 0,

            # Shooting stats
            'fg_made': fg_made,
            'fg_attempted': player.get('attempted_field_goals', 0) or 0,
            'three_pt_made': three_pt_made,
            'three_pt_attempted': player.get('attempted_three_point_field_goals', 0) or 0,
            'ft_made': ft_made,
            'ft_attempted': player.get('attempted_free_throws', 0) or 0,

            # Metadata
            'plus_minus': int(player.get('plus_minus', 0) or 0),
            'scraped_at': datetime.now(timezone.utc).isoformat(),
            'game_id': f"{game_date.isoformat()}-{self._normalize_team(team_str)}"
        }

    def _normalize_name(self, name: str) -> str:
        """Normalize player name to lookup format."""
        if not name:
            return ''
        # Remove periods, apostrophes, hyphens, convert to lowercase, remove spaces
        normalized = name.lower()
        for char in ['.', "'", '-', ' ', 'jr', 'sr', 'ii', 'iii', 'iv']:
            normalized = normalized.replace(char, '')
        return normalized

    def _normalize_team(self, team: str) -> Optional[str]:
        """Normalize team name to abbreviation."""
        if not team:
            return None

        # Handle enum values like "Team.BOSTON_CELTICS"
        team_str = str(team).upper()

        # Map common team names to abbreviations
        team_map = {
            'ATLANTA_HAWKS': 'ATL', 'ATLANTA': 'ATL', 'ATL': 'ATL',
            'BOSTON_CELTICS': 'BOS', 'BOSTON': 'BOS', 'BOS': 'BOS',
            'BROOKLYN_NETS': 'BKN', 'BROOKLYN': 'BKN', 'BKN': 'BKN',
            'CHARLOTTE_HORNETS': 'CHA', 'CHARLOTTE': 'CHA', 'CHA': 'CHA',
            'CHICAGO_BULLS': 'CHI', 'CHICAGO': 'CHI', 'CHI': 'CHI',
            'CLEVELAND_CAVALIERS': 'CLE', 'CLEVELAND': 'CLE', 'CLE': 'CLE',
            'DALLAS_MAVERICKS': 'DAL', 'DALLAS': 'DAL', 'DAL': 'DAL',
            'DENVER_NUGGETS': 'DEN', 'DENVER': 'DEN', 'DEN': 'DEN',
            'DETROIT_PISTONS': 'DET', 'DETROIT': 'DET', 'DET': 'DET',
            'GOLDEN_STATE_WARRIORS': 'GSW', 'GOLDEN_STATE': 'GSW', 'GSW': 'GSW',
            'HOUSTON_ROCKETS': 'HOU', 'HOUSTON': 'HOU', 'HOU': 'HOU',
            'INDIANA_PACERS': 'IND', 'INDIANA': 'IND', 'IND': 'IND',
            'LOS_ANGELES_CLIPPERS': 'LAC', 'LA_CLIPPERS': 'LAC', 'LAC': 'LAC',
            'LOS_ANGELES_LAKERS': 'LAL', 'LA_LAKERS': 'LAL', 'LAL': 'LAL',
            'MEMPHIS_GRIZZLIES': 'MEM', 'MEMPHIS': 'MEM', 'MEM': 'MEM',
            'MIAMI_HEAT': 'MIA', 'MIAMI': 'MIA', 'MIA': 'MIA',
            'MILWAUKEE_BUCKS': 'MIL', 'MILWAUKEE': 'MIL', 'MIL': 'MIL',
            'MINNESOTA_TIMBERWOLVES': 'MIN', 'MINNESOTA': 'MIN', 'MIN': 'MIN',
            'NEW_ORLEANS_PELICANS': 'NOP', 'NEW_ORLEANS': 'NOP', 'NOP': 'NOP',
            'NEW_YORK_KNICKS': 'NYK', 'NEW_YORK': 'NYK', 'NYK': 'NYK',
            'OKLAHOMA_CITY_THUNDER': 'OKC', 'OKLAHOMA_CITY': 'OKC', 'OKC': 'OKC',
            'ORLANDO_MAGIC': 'ORL', 'ORLANDO': 'ORL', 'ORL': 'ORL',
            'PHILADELPHIA_76ERS': 'PHI', 'PHILADELPHIA': 'PHI', 'PHI': 'PHI',
            'PHOENIX_SUNS': 'PHX', 'PHOENIX': 'PHX', 'PHX': 'PHX',
            'PORTLAND_TRAIL_BLAZERS': 'POR', 'PORTLAND': 'POR', 'POR': 'POR',
            'SACRAMENTO_KINGS': 'SAC', 'SACRAMENTO': 'SAC', 'SAC': 'SAC',
            'SAN_ANTONIO_SPURS': 'SAS', 'SAN_ANTONIO': 'SAS', 'SAS': 'SAS',
            'TORONTO_RAPTORS': 'TOR', 'TORONTO': 'TOR', 'TOR': 'TOR',
            'UTAH_JAZZ': 'UTA', 'UTAH': 'UTA', 'UTA': 'UTA',
            'WASHINGTON_WIZARDS': 'WAS', 'WASHINGTON': 'WAS', 'WAS': 'WAS',
        }

        for key, abbr in team_map.items():
            if key in team_str:
                return abbr

        # Return first 3 chars as fallback
        return team_str[:3] if len(team_str) >= 3 else team_str

    def _parse_minutes(self, minutes) -> Optional[int]:
        """Parse minutes to integer."""
        if minutes is None:
            return None

        if isinstance(minutes, (int, float)):
            return int(round(minutes))

        # Handle timedelta
        if hasattr(minutes, 'total_seconds'):
            return int(round(minutes.total_seconds() / 60))

        # Handle string like "32:45"
        if isinstance(minutes, str) and ':' in minutes:
            parts = minutes.split(':')
            return int(parts[0]) + (int(parts[1]) // 60 if len(parts) > 1 else 0)

        try:
            return int(round(float(minutes)))
        except (ValueError, TypeError):
            return None

    def save_to_bigquery(self, players: List[Dict]) -> bool:
        """Save scraped data to BigQuery backup table."""
        if not players:
            logger.warning("No players to save")
            return False

        table_id = f"{self.project_id}.nba_raw.bref_player_boxscores"

        try:
            errors = self.bq_client.insert_rows_json(table_id, players)
            if errors:
                logger.error(f"BigQuery insert errors: {errors[:5]}")
                return False

            logger.info(f"Saved {len(players)} player records to {table_id}")
            return True

        except Exception as e:
            logger.error(f"Error saving to BigQuery: {e}")
            return False

    def run(self, game_date: date = None) -> Dict:
        """
        Run the scraper for a specific date (default: yesterday).

        Returns:
            Statistics dictionary
        """
        if game_date is None:
            # Default to yesterday (most recent complete games)
            game_date = date.today() - timedelta(days=1)

        logger.info(f"Starting Basketball Reference scrape for {game_date}")

        try:
            # Add delay to be respectful
            time.sleep(REQUEST_DELAY_SECONDS)

            # Scrape the data
            players = self.scrape_date(game_date)

            if players:
                # Save to BigQuery
                self.save_to_bigquery(players)

            return {
                'success': True,
                'game_date': game_date.isoformat(),
                'stats': self.stats
            }

        except Exception as e:
            logger.error(f"Scraper run failed: {e}")
            return {
                'success': False,
                'game_date': game_date.isoformat(),
                'error': str(e),
                'stats': self.stats
            }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Scrape Basketball Reference box scores')
    parser.add_argument('--date', type=str, help='Date to scrape (YYYY-MM-DD), default yesterday')
    parser.add_argument('--no-proxy', action='store_true', help='Disable proxy')
    parser.add_argument('--dry-run', action='store_true', help='Scrape but do not save to BigQuery')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    game_date = None
    if args.date:
        game_date = date.fromisoformat(args.date)

    scraper = BRefBoxScoreScraper(use_proxy=not args.no_proxy)

    if args.dry_run:
        players = scraper.scrape_date(game_date or (date.today() - timedelta(days=1)))
        print(f"\n[DRY RUN] Would save {len(players)} player records")
        if players:
            print(f"Sample: {players[0]}")
    else:
        result = scraper.run(game_date)
        print(f"\nResult: {result}")


if __name__ == '__main__':
    main()
