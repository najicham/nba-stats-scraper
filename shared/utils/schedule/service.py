# ============================================================================
# FILE: shared/utils/schedule/service.py
# ============================================================================
"""
NBA Schedule Service - Main schedule interface.

Provides unified access to NBA schedule data with automatic optimization:
- Database queries for fast checks (default)
- GCS fallback for source of truth
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any

from .models import NBAGame, GameType
from .database_reader import ScheduleDatabaseReader
from .gcs_reader import ScheduleGCSReader

logger = logging.getLogger(__name__)


class NBAScheduleService:
    """
    Service for reading and querying NBA schedule data.
    
    Default mode: Database-first with GCS fallback (optimal for most use cases)
    GCS-only mode: Available for backfills that need source of truth
    """
    
    # Expose team mapping for convenience
    NBA_TEAMS = ScheduleGCSReader.NBA_TEAMS
    
    def __init__(self, 
                 bucket_name: str = 'nba-scraped-data',
                 use_database: bool = True,  # DEFAULT: True for performance
                 database_table: str = 'nba_reference.nba_schedule',
                 project_id: str = None):
        """
        Initialize NBA Schedule Service.

        Args:
            bucket_name: GCS bucket containing schedule files
            use_database: If True, check database first for fast queries (DEFAULT)
            database_table: BigQuery table with schedule data (dataset.table)
            project_id: GCP project ID (defaults to centralized config)
        """
        self.use_database = use_database
        
        # Always initialize GCS reader (source of truth)
        self.gcs_reader = ScheduleGCSReader(bucket_name=bucket_name)
        
        # Initialize database reader if enabled
        self.db_reader = None
        if use_database:
            self.db_reader = ScheduleDatabaseReader(
                project_id=project_id,
                table_name=database_table
            )
            logger.info("NBAScheduleService initialized (mode: database-first with GCS fallback)")
        else:
            logger.info("NBAScheduleService initialized (mode: GCS-only)")
    
    @classmethod
    def from_gcs_only(cls, bucket_name: str = 'nba-scraped-data'):
        """
        Create service that only uses GCS (no database checks).
        
        Best for:
        - Backfill jobs needing full game metadata
        - Data validation against source of truth
        - When database is not available
        
        Usage:
            schedule = NBAScheduleService.from_gcs_only()
        """
        return cls(bucket_name=bucket_name, use_database=False)
    
    def has_games_on_date(self, game_date: str, game_type: GameType = GameType.REGULAR_PLAYOFF) -> bool:
        """
        Check if there are games on a specific date.
        
        Fast path: Database query (~10-50ms)
        Fallback: GCS read if database unavailable
        
        Args:
            game_date: Date string in YYYY-MM-DD format
            game_type: Type of games to check for
            
        Returns:
            True if games exist on this date, False otherwise
        """
        # Try database first if enabled
        if self.use_database and self.db_reader:
            game_types = self._game_type_to_list(game_type)
            db_result = self.db_reader.has_games_on_date(game_date, game_types)
            if db_result is not None:  # None means fallback to GCS
                return db_result
            logger.debug("Database unavailable for %s, using GCS fallback", game_date)
        
        # Fallback to GCS
        return self.get_game_count(game_date, game_type) > 0
    
    def get_game_count(self, game_date: str, game_type: GameType = GameType.REGULAR_PLAYOFF) -> int:
        """
        Get count of games on a specific date.
        
        Args:
            game_date: Date string in YYYY-MM-DD format
            game_type: Type of games to count
            
        Returns:
            Number of games on this date
        """
        # Try database first if enabled
        if self.use_database and self.db_reader:
            game_types = self._game_type_to_list(game_type)
            db_count = self.db_reader.get_game_count(game_date, game_types)
            if db_count is not None:
                return db_count
            logger.debug("Database unavailable for %s, using GCS fallback", game_date)
        
        # Fallback to GCS
        games = self.get_games_for_date(game_date, game_type)
        return len(games)
    
    def get_games_for_date(self, game_date: str, game_type: GameType = GameType.REGULAR_PLAYOFF) -> List[NBAGame]:
        """
        Get all games for a specific date.
        
        Always uses GCS for detailed game data.
        
        Args:
            game_date: Date string in YYYY-MM-DD format
            game_type: Type of games to return
            
        Returns:
            List of NBAGame objects for this date
        """
        # Determine which season this date belongs to
        date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
        season_year = self._get_season_for_date(date_obj)
        
        # Get all games for this season from GCS
        all_games = self.gcs_reader.get_games_for_season(season_year)
        
        # Filter by date and game type
        filtered_games = [
            game for game in all_games
            if game.game_date == game_date and self._matches_game_type(game, game_type)
        ]
        
        return filtered_games
    
    def get_season_date_map(self, season: int, game_type: GameType = GameType.REGULAR_PLAYOFF) -> Dict[str, int]:
        """
        Get map of all dates to game counts for a season.
        
        Args:
            season: Season year (e.g., 2024 for 2024-25 season)
            game_type: Type of games to include
            
        Returns:
            Dictionary mapping date strings to game counts
        """
        # Try database first if enabled
        if self.use_database and self.db_reader:
            game_types = self._game_type_to_list(game_type)
            db_map = self.db_reader.get_season_date_map(season, game_types)
            if db_map is not None:
                return db_map
            logger.debug("Database unavailable for season %d, using GCS fallback", season)
        
        # Fallback to GCS
        all_games = self.gcs_reader.get_games_for_season(season)
        
        # Build date map
        date_map: Dict[str, int] = {}
        for game in all_games:
            if self._matches_game_type(game, game_type):
                date_map[game.game_date] = date_map.get(game.game_date, 0) + 1
        
        return date_map
    
    def get_all_game_dates(self, seasons: List[int], 
                          game_type: GameType = GameType.REGULAR_PLAYOFF,
                          start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all game dates across multiple seasons with full game info.
        
        Always uses GCS for comprehensive game data.
        
        Args:
            seasons: List of season years (e.g., [2021, 2022, 2023, 2024])
            game_type: Type of games to include
            start_date: Optional filter - only dates >= this (YYYY-MM-DD)
            end_date: Optional filter - only dates <= this (YYYY-MM-DD)
            
        Returns:
            List of dicts with format:
            [
                {
                    'date': '2024-01-15',
                    'games': [NBAGame, NBAGame, ...],
                    'season': 2024
                },
                ...
            ]
        """
        all_date_info = []
        
        for season in seasons:
            try:
                logger.info("Processing season %d (%d-%02d)...", 
                           season, season, (season+1)%100)
                
                # Get all games for this season from GCS
                games = self.gcs_reader.get_games_for_season(season)
                
                # Filter by game type
                filtered_games = [
                    game for game in games 
                    if self._matches_game_type(game, game_type)
                ]
                
                # Group by date
                date_game_map: Dict[str, List[NBAGame]] = {}
                for game in filtered_games:
                    if game.game_date not in date_game_map:
                        date_game_map[game.game_date] = []
                    date_game_map[game.game_date].append(game)
                
                # Apply date range filters
                for game_date, games_on_date in date_game_map.items():
                    if start_date and game_date < start_date:
                        continue
                    if end_date and game_date > end_date:
                        continue
                    
                    all_date_info.append({
                        'date': game_date,
                        'games': games_on_date,
                        'season': season
                    })
                
                logger.info("Season %d: %d game dates", season, len(date_game_map))
                
            except Exception as e:
                logger.error("Error processing season %d: %s", season, e)
                continue
        
        # Sort by date
        all_date_info.sort(key=lambda x: x['date'])
        
        logger.info("Total game dates across all seasons: %d", len(all_date_info))
        return all_date_info
    
    def get_team_full_name(self, team_code: str) -> Optional[str]:
        """Get full team name from team code."""
        return self.NBA_TEAMS.get(team_code)

    def get_season_type_for_date(self, game_date: str, default: str = "Regular Season") -> str:
        """
        Get the NBA.com API season_type for a specific date.

        This method queries the schedule database to determine the correct
        season_type parameter for NBA.com stats API calls.

        Args:
            game_date: Date string in YYYY-MM-DD format
            default: Default value if no games found (default: "Regular Season")

        Returns:
            NBA.com API season_type string:
            - "All Star" for All-Star Weekend games
            - "PlayIn" for Play-In Tournament games
            - "Playoffs" for playoff games (first round through finals)
            - "Pre Season" for preseason games
            - "Regular Season" for regular season (including Emirates Cup)

        Example:
            >>> schedule = NBAScheduleService()
            >>> schedule.get_season_type_for_date('2024-02-18')
            'All Star'
            >>> schedule.get_season_type_for_date('2024-04-16')
            'PlayIn'
            >>> schedule.get_season_type_for_date('2024-04-20')
            'Playoffs'
        """
        # Try database first (fast path)
        if self.db_reader:
            season_type = self.db_reader.get_nba_api_season_type(game_date)
            if season_type:
                return season_type

        # Fallback to GCS-based detection
        try:
            games = self.get_games_for_date(game_date, game_type=GameType.ALL)
            if not games:
                logger.debug("No games found for %s, using default: %s", game_date, default)
                return default

            game = games[0]

            # Map game_type to NBA.com API season_type
            game_type_map = {
                'all_star_special': 'All Star',
                'play_in': 'PlayIn',
                'playoff': 'Playoffs',
                'preseason': 'Pre Season',
                'regular_season': 'Regular Season',
            }
            return game_type_map.get(game.game_type, default)

        except Exception as e:
            logger.warning("Error getting season type for %s: %s", game_date, e)
            return default

    def get_season_start_date(self, season_year: int) -> Optional[str]:
        """
        Get the first regular season game date for a given season.

        Uses database for fast lookup, with fallback to GCS if needed.

        Args:
            season_year: Season year (e.g., 2024 for 2024-25 season)

        Returns:
            Date string in YYYY-MM-DD format (e.g., '2024-10-22'), or None if not found

        Example:
            >>> schedule = NBAScheduleService()
            >>> schedule.get_season_start_date(2024)
            '2024-10-22'
            >>> schedule.get_season_start_date(2023)
            '2023-10-24'
        """
        # Try database first (fast)
        if self.use_database and self.db_reader:
            db_result = self.db_reader.get_season_start_date(season_year)
            if db_result is not None:
                return db_result
            logger.debug("Database unavailable for season %d, using GCS fallback", season_year)

        # Fallback to GCS: get all games and find first regular season game
        try:
            all_games = self.gcs_reader.get_games_for_season(season_year)
            regular_season_games = [
                game for game in all_games
                if game.game_type == 'regular_season' and game.completed
            ]

            if regular_season_games:
                # Sort by date and return earliest
                regular_season_games.sort(key=lambda g: g.game_date)
                return regular_season_games[0].game_date

            logger.warning("No regular season games found for season %d", season_year)
            return None

        except Exception as e:
            logger.error("Error getting season start for %d: %s", season_year, e)
            return None

    def clear_cache(self):
        """Clear all cached schedule data."""
        self.gcs_reader.clear_cache()
        logger.info("Schedule service cache cleared")
    
    # Private helper methods
    
    def _game_type_to_list(self, game_type: GameType) -> Optional[List[str]]:
        """Convert GameType enum to list of game type strings for database query."""
        if game_type == GameType.ALL:
            return None  # No filter
        elif game_type == GameType.PLAYOFF_ONLY:
            return ['playoff', 'play_in']
        elif game_type == GameType.REGULAR_ONLY:
            return ['regular_season']
        elif game_type == GameType.REGULAR_PLAYOFF:
            return ['regular_season', 'playoff', 'play_in']
        return None
    
    def _matches_game_type(self, game: NBAGame, game_type: GameType) -> bool:
        """Check if game matches the requested game type filter."""
        if game_type == GameType.ALL:
            return True
        elif game_type == GameType.REGULAR_PLAYOFF:
            return game.game_type in ['regular_season', 'playoff', 'play_in']
        elif game_type == GameType.PLAYOFF_ONLY:
            return game.game_type in ['playoff', 'play_in']
        elif game_type == GameType.REGULAR_ONLY:
            return game.game_type == 'regular_season'
        return True
    
    def _get_season_for_date(self, date_obj: date) -> int:
        """
        Determine which NBA season a date belongs to.
        
        NBA seasons run from October (year N) to June (year N+1).
        
        Args:
            date_obj: Date to check
            
        Returns:
            Season year (e.g., 2024 for 2024-25 season)
        """
        # NBA season starts in October
        if date_obj.month >= 10:
            return date_obj.year
        else:
            return date_obj.year - 1