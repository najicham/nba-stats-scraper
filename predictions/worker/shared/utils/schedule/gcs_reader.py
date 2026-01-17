# ============================================================================
# FILE: shared/utils/schedule/gcs_reader.py
# ============================================================================
"""
Schedule GCS Reader - Reads NBA schedule data from Google Cloud Storage.

This module handles all GCS interactions for schedule data:
- Reading schedule JSON files from GCS
- Parsing both old (gameDates) and new (flat games) formats
- Extracting and classifying games
- Caching schedule data for performance
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import storage

from .models import NBAGame

logger = logging.getLogger(__name__)


class ScheduleGCSReader:
    """
    Reads NBA schedule data from GCS.
    
    Handles:
    - Reading schedule files from gs://nba-scraped-data/nba-com/schedule/
    - Parsing both old and new schedule formats
    - Game classification and filtering
    - Caching for performance
    """
    
    # NBA team code to full name mapping
    NBA_TEAMS = {
        'ATL': 'Atlanta Hawks',
        'BOS': 'Boston Celtics',
        'BKN': 'Brooklyn Nets',
        'CHA': 'Charlotte Hornets',
        'CHI': 'Chicago Bulls',
        'CLE': 'Cleveland Cavaliers',
        'DAL': 'Dallas Mavericks',
        'DEN': 'Denver Nuggets',
        'DET': 'Detroit Pistons',
        'GSW': 'Golden State Warriors',
        'HOU': 'Houston Rockets',
        'IND': 'Indiana Pacers',
        'LAC': 'Los Angeles Clippers',
        'LAL': 'Los Angeles Lakers',
        'MEM': 'Memphis Grizzlies',
        'MIA': 'Miami Heat',
        'MIL': 'Milwaukee Bucks',
        'MIN': 'Minnesota Timberwolves',
        'NOP': 'New Orleans Pelicans',
        'NYK': 'New York Knicks',
        'OKC': 'Oklahoma City Thunder',
        'ORL': 'Orlando Magic',
        'PHI': 'Philadelphia 76ers',
        'PHX': 'Phoenix Suns',
        'POR': 'Portland Trail Blazers',
        'SAC': 'Sacramento Kings',
        'SAS': 'San Antonio Spurs',
        'TOR': 'Toronto Raptors',
        'UTA': 'Utah Jazz',
        'WAS': 'Washington Wizards'
    }

    # Known exhibition/All-Star team codes (silently skip these)
    EXHIBITION_TEAMS = {
        # International exhibition teams
        'RMD', 'CNS', 'NZB', 'MRA', 'FLA', 'JAL', 'TAM', 'DLF', 'PAU',
        'ULM', 'KEN', 'CHK', 'CAN', 'SHQ',
        # All-Star teams
        'WST', 'EST',  # West/East
        'TMG', 'TMM', 'TMC', 'TML', 'TMD', 'TMS',  # Team variations
        # G-League and other exhibition
        'WOR', 'RIS',  # World, Rising Stars
    }
    
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        """
        Initialize GCS reader.
        
        Args:
            bucket_name: GCS bucket containing schedule files
        """
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Cache for schedule data and parsed games
        self._schedule_cache: Dict[int, Dict] = {}  # season_year -> schedule_data
        self._games_cache: Dict[int, List[NBAGame]] = {}  # season_year -> games list
        
        logger.info("ScheduleGCSReader initialized (bucket: %s)", bucket_name)
    
    def get_games_for_season(self, season_year: int) -> List[NBAGame]:
        """
        Get all games for a season from GCS.
        
        Args:
            season_year: Season year (e.g., 2024 for 2024-25)
            
        Returns:
            List of NBAGame objects for this season
        """
        # Check cache first
        if season_year in self._games_cache:
            logger.debug("Using cached games for season %d", season_year)
            return self._games_cache[season_year]
        
        # Read and parse schedule
        schedule_data = self._read_schedule_from_gcs(season_year)
        games = self._extract_games_from_schedule(schedule_data, season_year)
        
        # Cache results
        self._games_cache[season_year] = games
        
        logger.info("Loaded %d games for season %d from GCS", len(games), season_year)
        return games
    
    def clear_cache(self):
        """Clear all cached schedule data."""
        self._schedule_cache.clear()
        self._games_cache.clear()
        logger.info("GCS reader cache cleared")
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict:
        """
        Read NBA schedule JSON from GCS for a specific season.
        
        Uses the most recent schedule file if multiple exist.
        Path: gs://nba-scraped-data/nba-com/schedule/{season}/
        
        Args:
            season_year: Season year (e.g., 2024 for 2024-25)
            
        Returns:
            Schedule data dictionary
            
        Raises:
            FileNotFoundError: If no schedule files found for season
        """
        # Check cache first
        if season_year in self._schedule_cache:
            logger.debug("Using cached schedule data for season %d", season_year)
            return self._schedule_cache[season_year]
        
        # Convert season year to NBA format
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.debug("Looking for schedule files: %s", schedule_prefix)
        
        # List schedule files
        blobs = list(self.bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files found for season {season_str} at {schedule_prefix}")
        
        # Use most recent schedule file (sorted by timestamp in filename)
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.info("Reading schedule from: gs://%s/%s (created: %s)", 
                   self.bucket_name, latest_blob.name, latest_blob.time_created)
        
        schedule_data = json.loads(latest_blob.download_as_text())
        
        # Cache results
        self._schedule_cache[season_year] = schedule_data
        
        return schedule_data
    
    def _extract_games_from_schedule(self, schedule_data: Dict, season_year: int) -> List[NBAGame]:
        """
        Extract all games from schedule JSON.
        
        Handles both formats:
        - NEW (Sept 2025+): Flat 'games' array
        - OLD: 'gameDates' with nested 'games'
        
        Args:
            schedule_data: Schedule JSON data
            season_year: Season year for this schedule
            
        Returns:
            List of NBAGame objects
        """
        games = []
        
        # NEW FORMAT (Sept 2025+): Flat 'games' array
        if 'games' in schedule_data and isinstance(schedule_data['games'], list):
            logger.info("Detected new schedule format (flat games array)")
            for game in schedule_data.get('games', []):
                game_obj = self._parse_game_new_format(game, season_year)
                if game_obj:
                    games.append(game_obj)
            return games
        
        # OLD FORMAT: 'gameDates' with nested 'games'
        schedule_games = schedule_data.get('gameDates', [])
        if not schedule_games:
            logger.warning("No 'gameDates' or 'games' found in schedule data")
            return games
        
        logger.info("Detected old schedule format (gameDates structure)")
        for game_date_entry in schedule_games:
            # Extract date
            game_date = self._extract_date_from_entry(game_date_entry)
            if not game_date:
                continue
            
            # Process games for this date
            games_for_date = game_date_entry.get('games', [])
            for game in games_for_date:
                game_obj = self._parse_game_old_format(game, game_date, season_year)
                if game_obj:
                    games.append(game_obj)
        
        return games
    
    def _parse_game_new_format(self, game: Dict, season_year: int) -> Optional[NBAGame]:
        """Parse game from new format (flat games array)."""
        try:
            # Extract basic fields
            game_id = game.get('gameId', '')
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                return None
            
            # Extract date from game object
            game_date_str = game.get('gameDate', '') or game.get('gameDateEst', '')
            if not game_date_str:
                return None
            
            # Parse date (handles MM/DD/YYYY format)
            try:
                if ' ' in game_date_str:
                    date_part = game_date_str.split(' ')[0]
                else:
                    date_part = game_date_str
                date_obj = datetime.strptime(date_part, "%m/%d/%Y")
                game_date = date_obj.strftime("%Y-%m-%d")
            except ValueError as e:
                logger.warning("Failed to parse date '%s': %s", game_date_str, e)
                return None
            
            # Extract teams
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not away_team or not home_team:
                return None
            
            # Validate team codes
            if away_team in self.EXHIBITION_TEAMS or home_team in self.EXHIBITION_TEAMS:
                logger.debug("Skipping exhibition game: %s @ %s", away_team, home_team)
                return None
            
            # Validate team codes (only warn on truly unknown teams)
            if away_team not in self.NBA_TEAMS or home_team not in self.NBA_TEAMS:
                logger.warning("Unknown team codes: away=%s, home=%s", away_team, home_team)
                return None
            
            # Get full team names
            away_team_full = self.NBA_TEAMS[away_team]
            home_team_full = self.NBA_TEAMS[home_team]
            
            # Extract other fields
            game_status = game.get('gameStatus', 0)
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            week_name = game.get('weekName', '')
            week_number = game.get('weekNumber', -1)
            
            # Classify game type
            game_type = self._classify_game_type(game_label, game_sub_label, week_name, week_number)
            
            return NBAGame(
                game_id=game_id,
                game_code=game_code,
                game_date=game_date,
                away_team=away_team,
                home_team=home_team,
                away_team_full=away_team_full,
                home_team_full=home_team_full,
                game_status=game_status,
                completed=game_status == 3,
                game_label=game_label,
                game_sub_label=game_sub_label,
                week_name=week_name,
                week_number=week_number,
                game_type=game_type,
                commence_time=game.get('gameDateTimeUTC', ''),
                season_year=season_year
            )
            
        except Exception as e:
            logger.warning("Error parsing game (new format): %s", e)
            return None
    
    def _parse_game_old_format(self, game: Dict, game_date: str, season_year: int) -> Optional[NBAGame]:
        """Parse game from old format (gameDates nested structure)."""
        try:
            # Extract basic fields
            game_id = game.get('gameId', '')
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                return None
            
            # Extract teams
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not away_team or not home_team:
                return None
            
            # Validate team codes
            if away_team in self.EXHIBITION_TEAMS or home_team in self.EXHIBITION_TEAMS:
                logger.debug("Skipping exhibition game: %s @ %s", away_team, home_team)
                return None
            
            # Validate team codes (only warn on truly unknown teams)
            if away_team not in self.NBA_TEAMS or home_team not in self.NBA_TEAMS:
                logger.warning("Unknown team codes: away=%s, home=%s", away_team, home_team)
                return None
            
            # Get full team names
            away_team_full = self.NBA_TEAMS[away_team]
            home_team_full = self.NBA_TEAMS[home_team]
            
            # Extract other fields
            game_status = game.get('gameStatus', 0)
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            week_name = game.get('weekName', '')
            week_number = game.get('weekNumber', -1)
            
            # Classify game type
            game_type = self._classify_game_type(game_label, game_sub_label, week_name, week_number)
            
            return NBAGame(
                game_id=game_id,
                game_code=game_code,
                game_date=game_date,
                away_team=away_team,
                home_team=home_team,
                away_team_full=away_team_full,
                home_team_full=home_team_full,
                game_status=game_status,
                completed=game_status == 3,
                game_label=game_label,
                game_sub_label=game_sub_label,
                week_name=week_name,
                week_number=week_number,
                game_type=game_type,
                commence_time=game.get('gameDateTimeUTC', ''),
                season_year=season_year
            )
            
        except Exception as e:
            logger.warning("Error parsing game (old format): %s", e)
            return None
    
    def _extract_date_from_entry(self, entry: Dict) -> Optional[str]:
        """
        Extract date from game date entry (old format).
        
        Returns date in YYYY-MM-DD format.
        """
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format
                    if '/' in date_str and ' ' in date_str:
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y").strftime("%Y-%m-%d")
                    # Handle MM/DD/YYYY format
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
                    # Handle ISO format
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime("%Y-%m-%d")
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return date_str[:10]
                except ValueError:
                    continue
        
        return None
    
    def _classify_game_type(self, game_label: str, game_sub_label: str, 
                          week_name: str, week_number: int) -> str:
        """
        Classify game type based on labels and metadata.
        
        Returns:
            One of: 'regular_season', 'playoff', 'play_in', 'all_star_special', 'preseason'
        """
        label = (game_label or '').strip()
        sub_label = (game_sub_label or '').strip()
        
        # All-Star special events
        all_star_events = [
            'Rising Stars', 'All-Star Game', 'Celebrity Game',
            'Skills Challenge', 'Three-Point Contest', 'Slam Dunk Contest'
        ]
        
        for event in all_star_events:
            if event in label or event in sub_label:
                return 'all_star_special'
        
        # All-Star week
        if week_name == 'All-Star':
            return 'all_star_special'
        
        # Play-in games
        if 'Play-In' in label:
            return 'play_in'
        
        # Playoff rounds
        playoff_indicators = ['First Round', 'Conf. Semifinals', 'Conf. Finals', 'NBA Finals']
        for indicator in playoff_indicators:
            if indicator in label:
                return 'playoff'
        
        # Preseason (week 0 and not playoff)
        if week_number == 0:
            # Double-check it's not a playoff game with weird week number
            playoff_indicators_check = ['Play-In', 'First Round', 'Conf. Semifinals', 
                                       'Conf. Finals', 'NBA Finals']
            is_playoff = any(indicator in label for indicator in playoff_indicators_check)
            if not is_playoff:
                return 'preseason'
        
        # Default to regular season
        return 'regular_season'