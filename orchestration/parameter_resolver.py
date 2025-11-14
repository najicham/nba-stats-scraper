"""
orchestration/parameter_resolver.py

Parameter Resolver - Determines what parameters each scraper needs

Supports:
- Simple YAML-based parameter mappings (most scrapers)
- Complex code-based resolution (game-specific scrapers)
- Context building (season, date, games list)

Path: orchestration/parameter_resolver.py
"""

import logging
import yaml
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import pytz

from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger(__name__)


class ParameterResolver:
    """
    Resolves parameters for scraper execution.
    
    Strategy:
        1. Check if scraper has complex resolver (code-based)
        2. Otherwise use simple YAML config
        3. Build workflow context (season, date, games)
        4. Apply parameter mappings
    
    Design Principles:
        - Simple for 90% of scrapers (YAML config)
        - Flexible for complex cases (Python functions)
        - Context-aware (knows about current season, games, etc.)
    """
    
    def __init__(self, config_path: str = "config/scraper_parameters.yaml"):
        """
        Initialize resolver with config.
        
        Args:
            config_path: Path to scraper parameter config YAML
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.schedule_service = NBAScheduleService()
        self.ET = pytz.timezone('America/New_York')
        
        # Registry of complex resolvers (code-based)
        self.complex_resolvers = {
            'nbac_play_by_play': self._resolve_nbac_play_by_play,
            'nbac_player_boxscore': self._resolve_game_specific,
            'nbac_team_boxscore': self._resolve_game_specific_with_game_date,
            'bigdataball_pbp': self._resolve_game_specific,
            'br_season_roster': self._resolve_br_season_roster,
            'nbac_gamebook_pdf': self._resolve_nbac_gamebook_pdf,
            'nbac_injury_report': self._resolve_nbac_injury_report,
            'oddsa_player_props': self._resolve_odds_props,
            'oddsa_game_lines': self._resolve_odds_game_lines,
        }
    
    def _load_config(self) -> Dict[str, Any]:
        """Load parameter configuration from YAML."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            return {'simple_scrapers': {}, 'complex_scrapers': []}
        
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"✅ Loaded parameter config from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load parameter config: {e}")
            return {'simple_scrapers': {}, 'complex_scrapers': []}
    
    def build_workflow_context(
        self,
        workflow_name: str,
        target_games: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Build context for parameter resolution.
        
        Args:
            workflow_name: Workflow being executed
            target_games: Optional list of game IDs
        
        Returns:
            Dict with context information:
                - execution_date: Current date (YYYY-MM-DD)
                - season: Current NBA season in NBA format (e.g., "2024-25")
                - season_year: 4-digit ending year of season (e.g., "2025")
                - games_today: List of game objects for today
                - target_games: Game IDs to process (if provided)
        """
        current_time = datetime.now(self.ET)
        execution_date = current_time.date().strftime('%Y-%m-%d')
        
        # Determine current NBA season
        season = self.get_current_season(current_time)
        
        # Get games for today
        games_today = []
        try:
            games_today = self.schedule_service.get_games_for_date(execution_date)
        except Exception as e:
            logger.warning(f"Failed to get games for {execution_date}: {e}")
        
        # Extract 4-digit starting year from season (e.g., "2025-26" -> "2025")
        season_year = season.split('-')[0]  # "2025"

        context = {
            'workflow_name': workflow_name,
            'execution_date': execution_date,
            'season': season,  # NBA format: "2025-26"
            'season_year': season_year,  # 4-digit starting year: "2025"
            'games_today': games_today,
            'games_count': len(games_today)
        }
        
        if target_games:
            context['target_games'] = target_games
        
        logger.debug(f"Built context: {context}")
        
        return context
    
    def resolve_parameters(
        self,
        scraper_name: str,
        workflow_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve parameters for a scraper.
        
        Args:
            scraper_name: Name of scraper
            workflow_context: Context from build_workflow_context()
        
        Returns:
            Dict of parameters to pass to scraper
        """
        # Check if complex resolver exists
        if scraper_name in self.complex_resolvers:
            logger.debug(f"Using complex resolver for {scraper_name}")
            return self.complex_resolvers[scraper_name](workflow_context)
        
        # Check if in complex scrapers list (but no resolver yet)
        if scraper_name in self.config.get('complex_scrapers', []):
            logger.warning(f"Scraper {scraper_name} marked complex but no resolver implemented")
            return self._resolve_from_config(scraper_name, workflow_context)
        
        # Use simple YAML config
        return self._resolve_from_config(scraper_name, workflow_context)
    
    def _resolve_from_config(
        self,
        scraper_name: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve parameters from YAML config.
        
        Config format:
            simple_scrapers:
              scraper_name:
                param1: context.execution_date
                param2: context.season
                param3: "literal_value"
        
        Args:
            scraper_name: Name of scraper
            context: Workflow context
        
        Returns:
            Dict of resolved parameters
        """
        simple_scrapers = self.config.get('simple_scrapers', {})
        
        if scraper_name not in simple_scrapers:
            logger.warning(f"No parameter config for {scraper_name}, using defaults")
            return self._get_default_parameters(context)
        
        param_config = simple_scrapers[scraper_name]
        parameters = {}
        
        for param_name, value_expr in param_config.items():
            # Resolve value from context or use literal
            if isinstance(value_expr, str) and value_expr.startswith('context.'):
                # Extract from context
                context_key = value_expr.replace('context.', '')
                parameters[param_name] = context.get(context_key)
            else:
                # Literal value
                parameters[param_name] = value_expr
        
        return parameters
    
    def _get_default_parameters(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get default parameters if scraper not in config.
        
        Most scrapers need at least date and season.
        """
        return {
            'date': context['execution_date'],
            'season': context['season']
        }
    
    # ========================================================================
    # Complex Resolvers (Game-Specific Scrapers)
    # ========================================================================
    
    def _resolve_nbac_play_by_play(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolve parameters for play-by-play scraper.
        
        This scraper needs to be called once per game with game_id.
        Returns list of parameter sets (one per game).
        
        Note: The workflow executor will need to handle this specially
        (call scraper multiple times).
        
        For Phase 1, we'll just return params for first game.
        Phase 2 will handle per-game iteration.
        """
        games = context.get('games_today', [])
        
        if not games:
            logger.warning("No games today for play-by-play scraper")
            return {}
        
        # Phase 1: Just return first game
        # Phase 2: Return list of params for all games
        game = games[0]
        
        # Extract game_id from game object
        game_id = game.game_id
        game_date = game.game_date.replace('-', '')  # YYYYMMDD format
        
        return {
            'game_id': game_id,
            'gamedate': game_date,
            'season': context['season']
        }
    
    def _resolve_game_specific(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generic resolver for game-specific scrapers (nbac_player_boxscore, bigdataball_pbp).

        Uses 'gamedate' parameter (YYYYMMDD format).
        Returns parameters for first game (Phase 1).
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for game-specific scraper")
            return {'date': context['execution_date']}

        game = games[0]
        game_date = game.game_date.replace('-', '')  # YYYYMMDD format

        return {
            'game_id': game.game_id,
            'gamedate': game_date,
            'season': context['season']
        }

    def _resolve_game_specific_with_game_date(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolver for nbac_team_boxscore which uses 'game_date' (not 'gamedate').

        Returns parameters for first game (Phase 1).
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for game-specific scraper")
            return {'date': context['execution_date']}

        game = games[0]
        game_date = game.game_date  # YYYY-MM-DD format (with dashes)

        return {
            'game_id': game.game_id,
            'game_date': game_date,
            'season': context['season']
        }

    def _resolve_br_season_roster(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for Basketball Reference season rosters.

        Returns list of parameter sets for all 30 NBA teams.

        Params needed:
        - teamAbbr: 3-letter team code (e.g., "LAL")
        - year: Ending year (e.g., "2024" for 2023-24 season)
        """
        from shared.config.nba_teams import NBA_TEAMS

        # Basketball Reference uses different abbreviations for some teams
        NBA_TO_BR_TEAM_CODES = {
            'PHX': 'PHO',  # Phoenix Suns
            'BKN': 'BRK',  # Brooklyn Nets
            'CHA': 'CHO',  # Charlotte Hornets
            # All other teams use the same code
        }

        # Extract ending year from season (e.g., "2024-25" -> "2025")
        season = context['season']  # e.g., "2024-25"
        ending_year = season.split('-')[1]  # "25"
        full_ending_year = f"20{ending_year}"  # "2025"

        # Return parameter set for all 30 teams
        team_params = []
        for team in NBA_TEAMS:
            nba_abbr = team['abbr']
            br_abbr = NBA_TO_BR_TEAM_CODES.get(nba_abbr, nba_abbr)

            team_params.append({
                'teamAbbr': br_abbr,  # Use Basketball Reference abbreviation
                'year': full_ending_year
            })

        logger.info(f"Resolved br_season_roster for {len(team_params)} teams")
        return team_params

    def _resolve_nbac_injury_report(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolver for NBA.com injury report.

        Uses current execution hour to determine when report is being captured.
        NBA typically publishes injury reports around 5:30 PM ET.

        Params needed:
        - gamedate: YYYY-MM-DD or YYYYMMDD
        - hour: 1-12 (12-hour format)
        - period: "AM" or "PM"
        """
        current_time = datetime.now(self.ET)
        hour_24 = current_time.hour

        # Convert to 12-hour format
        if hour_24 == 0:
            hour = 12
            period = 'AM'
        elif hour_24 < 12:
            hour = hour_24
            period = 'AM'
        elif hour_24 == 12:
            hour = 12
            period = 'PM'
        else:
            hour = hour_24 - 12
            period = 'PM'

        return {
            'gamedate': context['execution_date'],
            'hour': hour,
            'period': period
        }

    def _resolve_nbac_gamebook_pdf(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolver for NBA.com gamebook PDF scraper.

        Needs game_code in format: "YYYYMMDD/AWYHOM"
        Example: "20240410/MEMCLE"

        Phase 1: Returns params for first game only.
        Phase 2: Will return list to iterate over all games.
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for gamebook PDF scraper")
            return {}

        game = games[0]

        # Extract game info
        game_date_yyyymmdd = game.game_date.replace('-', '')  # "20240410"
        away_team = getattr(game, 'away_team_abbr', 'UNK')[:3].upper()
        home_team = getattr(game, 'home_team_abbr', 'UNK')[:3].upper()

        # Build game_code
        game_code = f"{game_date_yyyymmdd}/{away_team}{home_team}"

        return {
            'game_code': game_code
        }

    def _resolve_odds_props(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for Odds API player props scraper.

        CRITICAL: This scraper needs event_id from oddsa_events scraper.

        For LIVE workflows: event_ids come from context (captured from oddsa_events response)
        For BACKFILL workflows: event_ids would need to be queried from BigQuery

        Returns list of parameter sets (one per event).
        """
        event_ids = context.get('event_ids', [])

        if not event_ids:
            logger.warning("oddsa_player_props: No event_ids in context")
            logger.warning("  → oddsa_events must run first in workflow")
            logger.warning("  → Returning empty list (scraper will be skipped)")
            return []

        # Return parameter set for each event
        params_list = []
        for event_id in event_ids:
            params_list.append({
                'event_id': event_id,
                'game_date': context['execution_date'],
                'sport': 'basketball_nba'
            })

        logger.info(f"Resolved oddsa_player_props for {len(params_list)} events")
        return params_list

    def _resolve_odds_game_lines(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for Odds API game lines scraper.

        CRITICAL: This scraper needs event_id from oddsa_events scraper.

        Same dependency as oddsa_player_props.
        """
        event_ids = context.get('event_ids', [])

        if not event_ids:
            logger.warning("oddsa_game_lines: No event_ids in context")
            logger.warning("  → oddsa_events must run first in workflow")
            logger.warning("  → Returning empty list (scraper will be skipped)")
            return []

        # Return parameter set for each event
        params_list = []
        for event_id in event_ids:
            params_list.append({
                'event_id': event_id,
                'game_date': context['execution_date'],
                'sport': 'basketball_nba'
            })

        logger.info(f"Resolved oddsa_game_lines for {len(params_list)} events")
        return params_list
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def get_current_season(self, current_time: datetime) -> str:
        """
        Determine current NBA season based on date.
        
        NBA season logic:
        - Oct-Dec: Current year season (e.g., 2024-25)
        - Jan-Sep: Previous year season (e.g., 2023-24)
        
        Args:
            current_time: Current datetime
        
        Returns:
            Season string (e.g., "2024-25")
        """
        year = current_time.year
        month = current_time.month
        
        if month >= 10:  # Oct-Dec
            season_start = year
        else:  # Jan-Sep
            season_start = year - 1
        
        season_end = (season_start + 1) % 100
        
        return f"{season_start}-{season_end:02d}"
    
    def get_games_for_date(self, date_str: str) -> List:
        """
        Get games for a specific date.
        
        Args:
            date_str: Date string (YYYY-MM-DD)
        
        Returns:
            List of game objects
        """
        try:
            return self.schedule_service.get_games_for_date(date_str)
        except Exception as e:
            logger.error(f"Failed to get games for {date_str}: {e}")
            return []
