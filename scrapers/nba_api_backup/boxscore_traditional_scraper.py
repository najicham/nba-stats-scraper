#!/usr/bin/env python3
"""
NBA.com BoxScoreTraditionalV3 Scraper (via nba_api)

Backup source for player box scores using NBA.com's stats API.
This is a DIFFERENT endpoint than gamebook - provides redundancy.

Storage: BigQuery (actively compared against gamebook + BRef)

Created: 2026-01-28
"""

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery
from nba_api.stats.endpoints import BoxScoreTraditionalV3, ScoreboardV3
from nba_api.stats.static import teams

logger = logging.getLogger(__name__)

# Custom headers to avoid NBA.com blocking
CUSTOM_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) Gecko/20100101 Firefox/72.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Connection': 'keep-alive',
    'Referer': 'https://stats.nba.com/',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
}

# Rate limiting for NBA.com
REQUEST_DELAY_SECONDS = 1.0


class BoxScoreTraditionalScraper:
    """
    Scrapes player box scores from NBA.com stats API.

    Uses BoxScoreTraditionalV3 endpoint - different from gamebook PDF.
    """

    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.team_map = {t['id']: t['abbreviation'] for t in teams.get_teams()}
        self.stats = {
            'games_scraped': 0,
            'players_scraped': 0,
            'errors': 0
        }

    def get_games_for_date(self, game_date: date) -> List[str]:
        """Get list of game IDs for a specific date."""
        try:
            # Format date as required by API
            date_str = game_date.strftime('%Y-%m-%d')

            scoreboard = ScoreboardV3(
                game_date=date_str,
                league_id='00',
                headers=CUSTOM_HEADERS,
                timeout=60
            )

            games = scoreboard.get_dict()
            game_ids = []

            # Extract game IDs from scoreboard
            if 'scoreboard' in games and 'games' in games['scoreboard']:
                for game in games['scoreboard']['games']:
                    game_ids.append(game['gameId'])

            logger.info(f"Found {len(game_ids)} games on {game_date}")
            return game_ids

        except Exception as e:
            logger.error(f"Error getting games for {game_date}: {e}")
            return []

    def scrape_game(self, game_id: str, game_date: date) -> List[Dict]:
        """Scrape box score for a single game."""
        players = []

        try:
            time.sleep(REQUEST_DELAY_SECONDS)

            boxscore = BoxScoreTraditionalV3(
                game_id=game_id,
                headers=CUSTOM_HEADERS,
                timeout=60
            )
            data = boxscore.get_dict()

            # Extract player stats
            if 'boxScoreTraditional' in data:
                for team_key in ['homeTeam', 'awayTeam']:
                    team_data = data['boxScoreTraditional'].get(team_key, {})
                    team_id = team_data.get('teamId')
                    team_abbr = self.team_map.get(team_id, 'UNK')

                    for player in team_data.get('players', []):
                        stats = player.get('statistics', {})

                        # Parse minutes (format: "PT32M45S" or similar)
                        minutes = self._parse_minutes(stats.get('minutes', ''))

                        # Build full name from firstName + familyName
                        first_name = player.get('firstName', '')
                        family_name = player.get('familyName', '')
                        full_name = f"{first_name} {family_name}".strip()

                        processed = {
                            'source': 'nba_api_boxscore_v3',
                            'game_id': game_id,
                            'game_date': game_date.isoformat(),
                            'player_id': player.get('personId'),
                            'player_name': full_name,
                            'player_lookup': self._normalize_name(full_name),
                            'team_abbr': team_abbr,
                            'team_id': team_id,
                            'starter': player.get('starter') == '1',

                            # Core stats
                            'minutes_played': minutes,
                            'points': stats.get('points', 0),
                            'assists': stats.get('assists', 0),
                            'offensive_rebounds': stats.get('reboundsOffensive', 0),
                            'defensive_rebounds': stats.get('reboundsDefensive', 0),
                            'total_rebounds': stats.get('reboundsTotal', 0),
                            'steals': stats.get('steals', 0),
                            'blocks': stats.get('blocks', 0),
                            'turnovers': stats.get('turnovers', 0),
                            'personal_fouls': stats.get('foulsPersonal', 0),

                            # Shooting
                            'fg_made': stats.get('fieldGoalsMade', 0),
                            'fg_attempted': stats.get('fieldGoalsAttempted', 0),
                            'three_pt_made': stats.get('threePointersMade', 0),
                            'three_pt_attempted': stats.get('threePointersAttempted', 0),
                            'ft_made': stats.get('freeThrowsMade', 0),
                            'ft_attempted': stats.get('freeThrowsAttempted', 0),

                            # Additional
                            'plus_minus': stats.get('plusMinusPoints', 0),

                            # Metadata
                            'scraped_at': datetime.now(timezone.utc).isoformat()
                        }

                        players.append(processed)
                        self.stats['players_scraped'] += 1

            self.stats['games_scraped'] += 1

        except Exception as e:
            logger.error(f"Error scraping game {game_id}: {e}")
            self.stats['errors'] += 1

        return players

    def scrape_date(self, game_date: date) -> List[Dict]:
        """Scrape all games for a specific date."""
        logger.info(f"Scraping BoxScoreTraditionalV3 for {game_date}")

        all_players = []
        game_ids = self.get_games_for_date(game_date)

        for game_id in game_ids:
            players = self.scrape_game(game_id, game_date)
            all_players.extend(players)

        logger.info(f"Scraped {len(all_players)} players from {len(game_ids)} games")
        return all_players

    def _parse_minutes(self, minutes_str: str) -> Optional[int]:
        """Parse minutes from various formats."""
        if not minutes_str:
            return 0

        # Handle "PT32M45S" format
        if minutes_str.startswith('PT'):
            try:
                import re
                match = re.match(r'PT(\d+)M', minutes_str)
                if match:
                    return int(match.group(1))
            except:
                pass

        # Handle "32:45" format
        if ':' in str(minutes_str):
            try:
                parts = str(minutes_str).split(':')
                return int(parts[0])
            except:
                pass

        # Handle numeric
        try:
            return int(float(minutes_str))
        except:
            return 0

    def _normalize_name(self, name: str) -> str:
        """Normalize player name for matching."""
        if not name:
            return ''
        normalized = name.lower()
        for char in ['.', "'", '-', ' ', 'jr', 'sr', 'ii', 'iii', 'iv']:
            normalized = normalized.replace(char, '')
        return normalized

    def save_to_bigquery(self, players: List[Dict]) -> bool:
        """Save to BigQuery for comparison."""
        if not players:
            return True

        table_id = f"{self.project_id}.nba_raw.nba_api_player_boxscores"

        try:
            errors = self.bq_client.insert_rows_json(table_id, players)
            if errors:
                logger.error(f"BigQuery errors: {errors[:3]}")
                return False
            logger.info(f"Saved {len(players)} records to BigQuery")
            return True
        except Exception as e:
            logger.error(f"Error saving to BigQuery: {e}")
            return False

    def run(self, game_date: date = None) -> Dict:
        """Run scraper for a date."""
        if game_date is None:
            game_date = date.today() - timedelta(days=1)

        players = self.scrape_date(game_date)

        if players:
            self.save_to_bigquery(players)

        return {
            'success': True,
            'game_date': game_date.isoformat(),
            'stats': self.stats
        }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    game_date = date.fromisoformat(args.date) if args.date else None
    scraper = BoxScoreTraditionalScraper()

    if args.dry_run:
        players = scraper.scrape_date(game_date or (date.today() - timedelta(days=1)))
        print(f"\n[DRY RUN] Would save {len(players)} records")
        if players:
            print(f"Sample: {players[0]}")
    else:
        result = scraper.run(game_date)
        print(f"Result: {result}")


if __name__ == '__main__':
    main()
