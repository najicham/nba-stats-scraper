"""
orchestration/parameter_resolver.py

Parameter Resolver - Determines what parameters each scraper needs

Supports:
- Simple YAML-based parameter mappings (most scrapers)
- Complex code-based resolution (game-specific scrapers)
- Context building (season, date, games list)
- Target date awareness for post-game workflows

Path: orchestration/parameter_resolver.py

IMPORTANT: This module handles date targeting for workflows:
- post_game_* workflows target YESTERDAY's games (games that finished)
- late_games workflow targets YESTERDAY's games
- All other workflows target TODAY's games

See build_workflow_context() and _determine_target_date() for details.
"""

import logging
import yaml
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
import pytz

from shared.utils.schedule import NBAScheduleService

logger = logging.getLogger(__name__)


# ============================================================================
# WORKFLOW TARGET DATE CONFIGURATION
# ============================================================================
# Workflows that should fetch games from YESTERDAY instead of TODAY.
# These are post-game collection workflows that run after games finish.
#
# CRITICAL: If you add a new post-game workflow, add it here!
# Failure to do so will cause the workflow to look for TODAY's games
# instead of YESTERDAY's finished games.
# ============================================================================
YESTERDAY_TARGET_WORKFLOWS = [
    'post_game_window_1',    # 10 PM ET - first collection attempt
    'post_game_window_2',    # 1 AM ET - second collection attempt
    'post_game_window_3',    # 4 AM ET - final collection (gamebooks, etc.)
    'late_games',            # Late night game collection
]


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
        # Note: Scrapers that need per-game invocation return List[Dict]
        # Scrapers that work on date-level return Dict
        self.complex_resolvers = {
            'nbac_play_by_play': self._resolve_nbac_play_by_play,  # Per-game (returns list)
            'nbac_player_boxscore': self._resolve_game_specific,   # Date-based (returns dict)
            'nbac_team_boxscore': self._resolve_game_specific_with_game_date,  # Per-game (returns list)
            'bigdataball_pbp': self._resolve_bigdataball_pbp,      # Per-game (returns list)
            'br_season_roster': self._resolve_br_season_roster,
            'espn_roster': self._resolve_espn_roster,              # Per-team (returns list)
            'nbac_gamebook_pdf': self._resolve_nbac_gamebook_pdf,  # Per-game (returns list)
            'nbac_injury_report': self._resolve_nbac_injury_report,
            'oddsa_player_props': self._resolve_odds_props,
            'oddsa_game_lines': self._resolve_odds_game_lines,
        }

        # Validate workflow config on startup (non-blocking warning)
        self._validate_workflow_date_config()

    def _validate_workflow_date_config(self) -> None:
        """
        Validate that YESTERDAY_TARGET_WORKFLOWS matches workflows.yaml config.

        This catches configuration mismatches early, before they cause
        data staleness issues like Session 165.

        Checks:
        1. All decision_type="game_aware_yesterday" workflows are in YESTERDAY_TARGET_WORKFLOWS
        2. All YESTERDAY_TARGET_WORKFLOWS entries have decision_type="game_aware_yesterday"
        """
        try:
            workflows_path = "config/workflows.yaml"
            if not os.path.exists(workflows_path):
                logger.debug("workflows.yaml not found, skipping date config validation")
                return

            with open(workflows_path, 'r') as f:
                workflows_config = yaml.safe_load(f)

            workflows = workflows_config.get('workflows', {})

            # Find all workflows with game_aware_yesterday decision type
            yaml_yesterday_workflows = set()
            for name, config in workflows.items():
                if config.get('decision_type') == 'game_aware_yesterday':
                    yaml_yesterday_workflows.add(name)

            code_yesterday_workflows = set(YESTERDAY_TARGET_WORKFLOWS)

            # Check for mismatches
            in_yaml_not_code = yaml_yesterday_workflows - code_yesterday_workflows
            in_code_not_yaml = code_yesterday_workflows - yaml_yesterday_workflows

            if in_yaml_not_code:
                logger.warning(
                    f"⚠️  WORKFLOW CONFIG MISMATCH: These workflows have "
                    f"decision_type='game_aware_yesterday' in workflows.yaml but are "
                    f"NOT in YESTERDAY_TARGET_WORKFLOWS: {in_yaml_not_code}. "
                    f"Add them to YESTERDAY_TARGET_WORKFLOWS in parameter_resolver.py!"
                )

            if in_code_not_yaml:
                # This is less critical - the workflow might have been removed from YAML
                logger.info(
                    f"Note: These workflows are in YESTERDAY_TARGET_WORKFLOWS but not "
                    f"configured as game_aware_yesterday in workflows.yaml: {in_code_not_yaml}"
                )

            if not in_yaml_not_code and not in_code_not_yaml:
                logger.info("✅ Workflow date targeting config validated successfully")

        except Exception as e:
            # Non-blocking - just log and continue
            logger.warning(f"Could not validate workflow date config: {e}")
    
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
    
    def _determine_target_date(
        self,
        workflow_name: str,
        current_time: datetime,
        explicit_target_date: Optional[str] = None
    ) -> str:
        """
        Determine the target date for game fetching based on workflow type.

        This is CRITICAL for post-game workflows which need YESTERDAY's games,
        not today's games. Without this logic, gamebook scrapers would try to
        fetch gamebooks for games that haven't finished yet.

        Args:
            workflow_name: Name of workflow being executed
            current_time: Current datetime in ET
            explicit_target_date: If provided, use this date (for backfills)

        Returns:
            Target date string in YYYY-MM-DD format

        Examples:
            - post_game_window_3 at 4 AM on Dec 25 → returns Dec 24
            - betting_lines at 8 AM on Dec 25 → returns Dec 25
            - Any workflow with explicit_target_date="2025-12-23" → returns 2025-12-23
        """
        # Explicit date takes precedence (for backfills)
        if explicit_target_date:
            logger.info(f"Using explicit target_date: {explicit_target_date}")
            return explicit_target_date

        today = current_time.date().strftime('%Y-%m-%d')
        yesterday = (current_time.date() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Check if this is a post-game workflow that targets yesterday's games
        if workflow_name in YESTERDAY_TARGET_WORKFLOWS:
            logger.info(
                f"Workflow '{workflow_name}' targets YESTERDAY's games. "
                f"Target date: {yesterday} (today is {today})"
            )
            return yesterday

        # Default: target today's games
        return today

    def build_workflow_context(
        self,
        workflow_name: str,
        target_games: Optional[List[str]] = None,
        target_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build context for parameter resolution.

        IMPORTANT: This method now correctly handles post-game workflows
        by targeting YESTERDAY's games instead of today's games.

        Args:
            workflow_name: Workflow being executed
            target_games: Optional list of game IDs
            target_date: Optional explicit target date (for backfills).
                         If not provided, determined from workflow_name.

        Returns:
            Dict with context information:
                - execution_date: Current date (YYYY-MM-DD)
                - target_date: Date to fetch games for (may differ from execution_date)
                - season: Current NBA season in NBA format (e.g., "2024-25")
                - season_year: 4-digit ending year of season (e.g., "2025")
                - games_today: List of game objects for TARGET date
                - games_count: Number of games on target date
                - target_games: Game IDs to process (if provided)
        """
        current_time = datetime.now(self.ET)
        execution_date = current_time.date().strftime('%Y-%m-%d')

        # Determine target date based on workflow type
        resolved_target_date = self._determine_target_date(
            workflow_name=workflow_name,
            current_time=current_time,
            explicit_target_date=target_date
        )

        # Determine current NBA season
        season = self.get_current_season(current_time)

        # Get games for TARGET date (not necessarily today!)
        games_for_target_date = []
        try:
            games_for_target_date = self.schedule_service.get_games_for_date(resolved_target_date)
            logger.info(
                f"Fetched {len(games_for_target_date)} games for target date {resolved_target_date}"
            )
        except Exception as e:
            logger.warning(f"Failed to get games for {resolved_target_date}: {e}")

        # Extract 4-digit starting year from season (e.g., "2025-26" -> "2025")
        season_year = season.split('-')[0]  # "2025"

        context = {
            'workflow_name': workflow_name,
            'execution_date': execution_date,
            'target_date': resolved_target_date,  # NEW: May differ from execution_date
            'season': season,  # NBA format: "2025-26"
            'season_year': season_year,  # 4-digit starting year: "2025"
            'games_today': games_for_target_date,  # Games for TARGET date
            'games_count': len(games_for_target_date)
        }

        if target_games:
            context['target_games'] = target_games

        # Log warning if no games found for yesterday-targeting workflows
        if (workflow_name in YESTERDAY_TARGET_WORKFLOWS
            and len(games_for_target_date) == 0):
            logger.warning(
                f"⚠️  Workflow '{workflow_name}' targets yesterday ({resolved_target_date}) "
                f"but no games found. This may be expected if there were no games."
            )

        logger.info(
            f"Built context for {workflow_name}: execution_date={execution_date}, "
            f"target_date={resolved_target_date}, games={len(games_for_target_date)}"
        )

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
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for play-by-play scraper")
            return []

        params_list = []
        for game in games:
            game_id = game.game_id
            game_date = game.game_date.replace('-', '')  # YYYYMMDD format

            params_list.append({
                'game_id': game_id,
                'gamedate': game_date,
                'season': context['season']
            })

        logger.info(f"Resolved nbac_play_by_play for {len(params_list)} games")
        return params_list
    
    def _resolve_game_specific(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolver for nbac_player_boxscore (date-based API).

        Uses 'gamedate' parameter (YYYYMMDD format).
        This scraper uses leaguegamelog API which returns ALL players for a date,
        so we only need to pass the date, not iterate per game.
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

    def _resolve_bigdataball_pbp(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for bigdataball_pbp scraper.

        This scraper downloads from Google Drive by game_id.
        Returns list of parameter sets (one per game).
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for bigdataball_pbp scraper")
            return []

        params_list = []
        for game in games:
            game_id = game.game_id
            game_date = game.game_date.replace('-', '')  # YYYYMMDD format

            params_list.append({
                'game_id': game_id,
                'gamedate': game_date,
                'season': context['season']
            })

        logger.info(f"Resolved bigdataball_pbp for {len(params_list)} games")
        return params_list

    def _resolve_game_specific_with_game_date(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for nbac_team_boxscore which uses 'game_date' (not 'gamedate').

        Returns list of parameter sets (one per game).
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for nbac_team_boxscore scraper")
            return []

        params_list = []
        for game in games:
            game_date = game.game_date  # YYYY-MM-DD format (with dashes)

            params_list.append({
                'game_id': game.game_id,
                'game_date': game_date,
                'season': context['season']
            })

        logger.info(f"Resolved nbac_team_boxscore for {len(params_list)} games")
        return params_list

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

    def _resolve_espn_roster(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for ESPN team rosters.

        Returns list of parameter sets for all 30 NBA teams.
        Uses ESPN team abbreviations which differ from NBA.com codes for some teams.

        ESPN codes that differ from NBA.com:
        - GS (not GSW) - Golden State Warriors
        - NO (not NOP) - New Orleans Pelicans
        - NY (not NYK) - New York Knicks
        - SA (not SAS) - San Antonio Spurs
        - UTAH (not UTA) - Utah Jazz

        Params needed:
        - team_abbr: ESPN team code (e.g., "GS", "LAL")
        """
        # ESPN team abbreviations (all 30 teams)
        ESPN_TEAM_ABBRS = [
            "ATL", "BOS", "BKN", "CHA", "CHI",
            "CLE", "DAL", "DEN", "DET", "GS",      # Note: GS not GSW
            "HOU", "IND", "LAC", "LAL", "MEM",
            "MIA", "MIL", "MIN", "NO", "NY",       # Note: NO not NOP, NY not NYK
            "OKC", "ORL", "PHI", "PHX", "POR",
            "SAC", "SA", "TOR", "UTAH", "WAS"      # Note: SA not SAS, UTAH not UTA
        ]

        # Return parameter set for all 30 teams
        team_params = []
        for team_abbr in ESPN_TEAM_ABBRS:
            team_params.append({
                'team_abbr': team_abbr
            })

        logger.info(f"Resolved espn_roster for {len(team_params)} teams")
        return team_params

    def _resolve_nbac_injury_report(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolver for NBA.com injury report.

        Uses current execution hour to determine when report is being captured.
        NBA typically publishes injury reports around 5:30 PM ET.

        As of ~Dec 23, 2025, NBA.com changed URL format to include minutes
        and publishes reports every 15 minutes (00, 15, 30, 45).

        Params needed:
        - gamedate: YYYY-MM-DD or YYYYMMDD
        - hour: 1-12 (12-hour format)
        - period: "AM" or "PM"
        - minute: "00", "15", "30", or "45" (rounded down to nearest 15-min interval)
        """
        current_time = datetime.now(self.ET)
        hour_24 = current_time.hour
        current_minute = current_time.minute

        # Round down to nearest 15-minute interval
        # Examples: 6:07 → :00, 6:23 → :15, 6:38 → :30, 6:52 → :45
        minute_interval = (current_minute // 15) * 15

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
            'period': period,
            'minute': f"{minute_interval:02d}"  # Format as 00, 15, 30, or 45
        }

    def _resolve_nbac_gamebook_pdf(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Resolver for NBA.com gamebook PDF scraper.

        Needs game_code in format: "YYYYMMDD/AWYHOM"
        Example: "20240410/MEMCLE"

        Returns list of parameter sets to iterate over ALL games.
        """
        games = context.get('games_today', [])

        if not games:
            logger.warning("No games today for gamebook PDF scraper")
            return []

        params_list = []
        for game in games:
            # Extract game info
            game_date_yyyymmdd = game.game_date.replace('-', '')  # "20240410"
            # Use correct attribute names - 'away_team' and 'home_team'
            away_team = getattr(game, 'away_team', 'UNK')[:3].upper()
            home_team = getattr(game, 'home_team', 'UNK')[:3].upper()

            # Build game_code
            game_code = f"{game_date_yyyymmdd}/{away_team}{home_team}"

            params_list.append({
                'game_code': game_code
            })

        logger.info(f"Resolved nbac_gamebook_pdf for {len(params_list)} games")
        return params_list

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
