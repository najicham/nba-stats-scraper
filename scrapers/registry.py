"""
Scraper Registry - Single Source of Truth for Sports Scrapers

This module provides centralized scraper configuration and instantiation for:
- Flask scraper service (main_scraper_service.py)
- Orchestration system (workflow_executor.py)
- Any other system that needs to dynamically load scrapers

Supports multiple sports via SPORT environment variable:
- SPORT=nba (default): NBA scrapers
- SPORT=mlb: MLB scrapers

Usage:
    from scrapers.registry import get_scraper_instance, SCRAPER_REGISTRY

    # Get list of available scrapers
    scrapers = list(SCRAPER_REGISTRY.keys())

    # Instantiate a scraper
    scraper = get_scraper_instance('oddsa_events_his')  # NBA
    scraper = get_scraper_instance('mlb_schedule')       # MLB (when SPORT=mlb)

Path: scrapers/registry.py
"""

import os
import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# Get current sport from environment (default to NBA for backward compatibility)
CURRENT_SPORT = os.environ.get('SPORT', 'nba').lower()

# ============================================================================
# NBA SCRAPER REGISTRY
# ============================================================================
# Format: "scraper_name": ("module.path", "ClassName")
# ============================================================================

NBA_SCRAPER_REGISTRY: Dict[str, Tuple[str, str]] = {
    # ========================================================================
    # Odds API Scrapers (7 total)
    # ========================================================================
    "oddsa_events_his": (
        "scrapers.oddsapi.oddsa_events_his", 
        "GetOddsApiHistoricalEvents"
    ),
    "oddsa_events": (
        "scrapers.oddsapi.oddsa_events", 
        "GetOddsApiEvents"
    ),
    "oddsa_player_props": (
        "scrapers.oddsapi.oddsa_player_props", 
        "GetOddsApiCurrentEventOdds"
    ),
    "oddsa_player_props_his": (
        "scrapers.oddsapi.oddsa_player_props_his", 
        "GetOddsApiHistoricalEventOdds"
    ),
    "oddsa_game_lines": (
        "scrapers.oddsapi.oddsa_game_lines", 
        "GetOddsApiCurrentGameLines"
    ),
    "oddsa_game_lines_his": (
        "scrapers.oddsapi.oddsa_game_lines_his", 
        "GetOddsApiHistoricalGameLines"
    ),
    "oddsa_team_players": (
        "scrapers.oddsapi.oddsa_team_players", 
        "GetOddsApiTeamPlayers"
    ),
    
    # ========================================================================
    # Ball Don't Lie Scrapers (6 total)
    # ========================================================================
    "bdl_games": (
        "scrapers.balldontlie.bdl_games", 
        "BdlGamesScraper"
    ),
    "bdl_box_scores": (
        "scrapers.balldontlie.bdl_box_scores", 
        "BdlBoxScoresScraper"
    ),
    "bdl_player_box_scores": (
        "scrapers.balldontlie.bdl_player_box_scores", 
        "BdlPlayerBoxScoresScraper"
    ),
    "bdl_active_players": (
        "scrapers.balldontlie.bdl_active_players", 
        "BdlActivePlayersScraper"
    ),
    "bdl_injuries": (
        "scrapers.balldontlie.bdl_injuries", 
        "BdlInjuriesScraper"
    ),
    "bdl_standings": (
        "scrapers.balldontlie.bdl_standings",
        "BdlStandingsScraper"
    ),
    "bdl_live_box_scores": (
        "scrapers.balldontlie.bdl_live_box_scores",
        "BdlLiveBoxScoresScraper"
    ),

    # ========================================================================
    # BettingPros Scrapers (4 total: 2 NBA + 2 MLB)
    # ========================================================================
    # NBA
    "bp_events": (
        "scrapers.bettingpros.bp_events",
        "BettingProsEvents"
    ),
    "bp_player_props": (
        "scrapers.bettingpros.bp_player_props",
        "BettingProsPlayerProps"
    ),
    # MLB
    "bp_mlb_player_props": (
        "scrapers.bettingpros.bp_mlb_player_props",
        "BettingProsMLBPlayerProps"
    ),
    "bp_mlb_props_historical": (
        "scrapers.bettingpros.bp_mlb_props_historical",
        "BettingProsMLBHistoricalProps"
    ),

    # ========================================================================
    # Basketball Reference Scrapers (1 total)
    # ========================================================================
    "br_season_roster": (
        "scrapers.basketball_ref.br_season_roster", 
        "BasketballRefSeasonRoster"
    ),
    
    # ========================================================================
    # BigDataBall Scrapers (2 total)
    # ========================================================================
    "bigdataball_discovery": (
        "scrapers.bigdataball.bigdataball_discovery", 
        "BigDataBallDiscoveryScraper"
    ),
    "bigdataball_pbp": (
        "scrapers.bigdataball.bigdataball_pbp", 
        "BigDataBallPbpScraper"
    ),
    
    # ========================================================================
    # NBA.com Scrapers (13 total)
    # ========================================================================
    "nbac_schedule_api": (
        "scrapers.nbacom.nbac_schedule_api", 
        "GetNbaComScheduleApi"
    ),
    "nbac_player_list": (
        "scrapers.nbacom.nbac_player_list", 
        "GetNbaComPlayerList"
    ),
    "nbac_player_movement": (
        "scrapers.nbacom.nbac_player_movement", 
        "GetNbaComPlayerMovement"
    ),
    "nbac_schedule": (
        "scrapers.nbacom.nbac_schedule_cdn",
        "GetNbaComScheduleCdn"
    ),
    "nbac_schedule_cdn": (
        "scrapers.nbacom.nbac_schedule_cdn", 
        "GetNbaComScheduleCdn"
    ),
    "nbac_scoreboard_v2": (
        "scrapers.nbacom.nbac_scoreboard_v2", 
        "GetNbaComScoreboardV2"
    ),
    "nbac_injury_report": (
        "scrapers.nbacom.nbac_injury_report", 
        "GetNbaComInjuryReport"
    ),
    "nbac_play_by_play": (
        "scrapers.nbacom.nbac_play_by_play", 
        "GetNbaComPlayByPlay"
    ),
    "nbac_player_boxscore": (
        "scrapers.nbacom.nbac_player_boxscore", 
        "GetNbaComPlayerBoxscore"
    ),
    "nbac_roster": (
        "scrapers.nbacom.nbac_roster", 
        "GetNbaTeamRoster"
    ),
    "nbac_gamebook_pdf": (
        "scrapers.nbacom.nbac_gamebook_pdf", 
        "GetNbaComGamebookPdf"
    ),
    "nbac_referee_assignments": (
        "scrapers.nbacom.nbac_referee_assignments",
        "GetNbaComRefereeAssignments"
    ),
    "nbac_team_boxscore": (
        "scrapers.nbacom.nbac_team_boxscore",
        "GetNbaComTeamBoxscore"
    ),

    # ========================================================================
    # ESPN Scrapers (3 total)
    # ========================================================================
    "espn_roster": (
        "scrapers.espn.espn_roster_api", 
        "GetEspnTeamRosterAPI"
    ),
    "espn_scoreboard": (
        "scrapers.espn.espn_scoreboard_api", 
        "GetEspnScoreboard"
    ),
    "espn_game_boxscore": (
        "scrapers.espn.espn_game_boxscore",
        "GetEspnBoxscore"
    ),
}


# ============================================================================
# MLB SCRAPER REGISTRY
# ============================================================================

MLB_SCRAPER_REGISTRY: Dict[str, Tuple[str, str]] = {
    # ========================================================================
    # Ball Don't Lie Scrapers (13 total)
    # ========================================================================
    "mlb_games": ("scrapers.mlb.balldontlie.mlb_games", "MlbGamesScraper"),
    "mlb_box_scores": ("scrapers.mlb.balldontlie.mlb_box_scores", "MlbBoxScoresScraper"),
    "mlb_live_box_scores": ("scrapers.mlb.balldontlie.mlb_live_box_scores", "MlbLiveBoxScoresScraper"),
    "mlb_pitcher_stats": ("scrapers.mlb.balldontlie.mlb_pitcher_stats", "MlbPitcherStatsScraper"),
    "mlb_batter_stats": ("scrapers.mlb.balldontlie.mlb_batter_stats", "MlbBatterStatsScraper"),
    "mlb_active_players": ("scrapers.mlb.balldontlie.mlb_active_players", "MlbActivePlayersScraper"),
    "mlb_injuries": ("scrapers.mlb.balldontlie.mlb_injuries", "MlbInjuriesScraper"),
    "mlb_player_splits": ("scrapers.mlb.balldontlie.mlb_player_splits", "MlbPlayerSplitsScraper"),
    "mlb_player_versus": ("scrapers.mlb.balldontlie.mlb_player_versus", "MlbPlayerVersusScraper"),
    "mlb_season_stats": ("scrapers.mlb.balldontlie.mlb_season_stats", "MlbSeasonStatsScraper"),
    "mlb_standings": ("scrapers.mlb.balldontlie.mlb_standings", "MlbStandingsScraper"),
    "mlb_team_season_stats": ("scrapers.mlb.balldontlie.mlb_team_season_stats", "MlbTeamSeasonStatsScraper"),
    "mlb_teams": ("scrapers.mlb.balldontlie.mlb_teams", "MlbTeamsScraper"),

    # ========================================================================
    # MLB Stats API Scrapers (3 total)
    # ========================================================================
    "mlb_schedule": ("scrapers.mlb.mlbstatsapi.mlb_schedule", "MlbScheduleScraper"),
    "mlb_lineups": ("scrapers.mlb.mlbstatsapi.mlb_lineups", "MlbLineupsScraper"),
    "mlb_game_feed": ("scrapers.mlb.mlbstatsapi.mlb_game_feed", "MlbGameFeedScraper"),

    # ========================================================================
    # Odds API Scrapers (8 total)
    # ========================================================================
    "mlb_events": ("scrapers.mlb.oddsapi.mlb_events", "MlbEventsOddsScraper"),
    "mlb_events_his": ("scrapers.mlb.oddsapi.mlb_events_his", "MlbEventsHistoricalScraper"),
    "mlb_game_lines": ("scrapers.mlb.oddsapi.mlb_game_lines", "MlbGameLinesScraper"),
    "mlb_game_lines_his": ("scrapers.mlb.oddsapi.mlb_game_lines_his", "MlbGameLinesHistoricalScraper"),
    "mlb_pitcher_props": ("scrapers.mlb.oddsapi.mlb_pitcher_props", "MlbPitcherPropsScraper"),
    "mlb_pitcher_props_his": ("scrapers.mlb.oddsapi.mlb_pitcher_props_his", "MlbPitcherPropsHistoricalScraper"),
    "mlb_batter_props": ("scrapers.mlb.oddsapi.mlb_batter_props", "MlbBatterPropsScraper"),
    "mlb_batter_props_his": ("scrapers.mlb.oddsapi.mlb_batter_props_his", "MlbBatterPropsHistoricalScraper"),

    # ========================================================================
    # External Data Scrapers (3 total)
    # ========================================================================
    "mlb_weather": ("scrapers.mlb.external.mlb_weather", "MlbWeatherScraper"),
    "mlb_ballpark_factors": ("scrapers.mlb.external.mlb_ballpark_factors", "MlbBallparkFactorsScraper"),
    "mlb_umpire_stats": ("scrapers.mlb.external.mlb_umpire_stats", "MlbUmpireStatsScraper"),

    # ========================================================================
    # Statcast Scrapers (1 total)
    # ========================================================================
    "mlb_statcast_pitcher": ("scrapers.mlb.statcast.mlb_statcast_pitcher", "MlbStatcastPitcherScraper"),
}


# ============================================================================
# DYNAMIC REGISTRY SELECTION
# ============================================================================
# Select registry based on SPORT environment variable

if CURRENT_SPORT == 'mlb':
    SCRAPER_REGISTRY = MLB_SCRAPER_REGISTRY
    logger.info(f"Loaded MLB scraper registry ({len(MLB_SCRAPER_REGISTRY)} scrapers)")
else:
    SCRAPER_REGISTRY = NBA_SCRAPER_REGISTRY
    logger.info(f"Loaded NBA scraper registry ({len(NBA_SCRAPER_REGISTRY)} scrapers)")


# ============================================================================
# SCRAPER INSTANTIATION
# ============================================================================

def get_scraper_instance(scraper_name: str):
    """
    Dynamically load and instantiate a scraper by name.
    
    Args:
        scraper_name: Name of the scraper (must be in SCRAPER_REGISTRY)
        
    Returns:
        Instance of the scraper class
        
    Raises:
        ValueError: If scraper_name not found in registry
        ImportError: If module or class cannot be imported
        
    Example:
        >>> scraper = get_scraper_instance('oddsa_events_his')
        >>> result = scraper.run({'date': '2025-01-15'})
    """
    if scraper_name not in SCRAPER_REGISTRY:
        available = list(SCRAPER_REGISTRY.keys())
        raise ValueError(
            f"Unknown scraper: {scraper_name}. "
            f"Available scrapers: {available}"
        )
    
    module_path, class_name = SCRAPER_REGISTRY[scraper_name]
    
    try:
        logger.debug(f"Loading scraper: {scraper_name} from {module_path}")
        module = __import__(module_path, fromlist=[class_name])
        scraper_class = getattr(module, class_name)
        logger.debug(f"Successfully loaded {class_name}")
        
        # Instantiate and return
        return scraper_class()
        
    except ImportError as e:
        logger.error(f"Failed to import module {module_path}: {e}")
        raise ImportError(
            f"Failed to load scraper {scraper_name}: "
            f"Module '{module_path}' not found. Error: {e}"
        )
    except AttributeError as e:
        logger.error(f"Class {class_name} not found in module {module_path}: {e}")
        raise ImportError(
            f"Failed to load scraper {scraper_name}: "
            f"Class '{class_name}' not found in module '{module_path}'. Error: {e}"
        )


def get_scraper_info(scraper_name: Optional[str] = None) -> Dict:
    """
    Get information about one or all scrapers.
    
    Args:
        scraper_name: Optional scraper name. If None, returns info for all scrapers.
        
    Returns:
        Dictionary with scraper information
        
    Example:
        >>> # Get info for one scraper
        >>> info = get_scraper_info('oddsa_events_his')
        >>> print(info['module'], info['class'])
        
        >>> # Get info for all scrapers
        >>> all_info = get_scraper_info()
        >>> print(f"Total scrapers: {all_info['count']}")
    """
    if scraper_name:
        if scraper_name not in SCRAPER_REGISTRY:
            raise ValueError(f"Unknown scraper: {scraper_name}")
        
        module_path, class_name = SCRAPER_REGISTRY[scraper_name]
        return {
            "name": scraper_name,
            "module": module_path,
            "class": class_name
        }
    else:
        # Return info for all scrapers
        scrapers = []
        for name, (module_path, class_name) in SCRAPER_REGISTRY.items():
            scrapers.append({
                "name": name,
                "module": module_path,
                "class": class_name
            })
        
        return {
            "scrapers": scrapers,
            "count": len(scrapers)
        }


def list_scrapers() -> list:
    """
    Get list of all available scraper names.
    
    Returns:
        List of scraper names (strings)
        
    Example:
        >>> scrapers = list_scrapers()
        >>> print(f"Available scrapers ({len(scrapers)}): {scrapers[:5]}...")
    """
    return list(SCRAPER_REGISTRY.keys())


def scraper_exists(scraper_name: str) -> bool:
    """
    Check if a scraper exists in the registry.
    
    Args:
        scraper_name: Name to check
        
    Returns:
        True if scraper exists, False otherwise
        
    Example:
        >>> if scraper_exists('oddsa_events_his'):
        ...     scraper = get_scraper_instance('oddsa_events_his')
    """
    return scraper_name in SCRAPER_REGISTRY


# ============================================================================
# SCRAPER GROUPS (for orchestration workflows)
# ============================================================================

SCRAPER_GROUPS = {
    "odds_api": [
        "oddsa_events_his",
        "oddsa_events",
        "oddsa_player_props",
        "oddsa_player_props_his",
        "oddsa_game_lines",
        "oddsa_game_lines_his",
        "oddsa_team_players",
    ],
    "ball_dont_lie": [
        "bdl_games",
        "bdl_box_scores",
        "bdl_player_box_scores",
        "bdl_active_players",
        "bdl_injuries",
        "bdl_standings",
    ],
    "nba_com": [
        "nbac_schedule_api",
        "nbac_player_list",
        "nbac_player_movement",
        "nbac_schedule",
        "nbac_schedule_cdn",
        "nbac_scoreboard_v2",
        "nbac_injury_report",
        "nbac_play_by_play",
        "nbac_player_boxscore",
        "nbac_team_boxscore",
        "nbac_roster",
        "nbac_gamebook_pdf",
        "nbac_referee_assignments",
    ],
    "espn": [
        "espn_roster",
        "espn_scoreboard",
        "espn_game_boxscore",
    ],
    "discovery": [
        "bigdataball_discovery",
        "br_season_roster",
    ]
}


def get_scrapers_by_group(group_name: str) -> list:
    """
    Get all scrapers belonging to a specific group.
    
    Args:
        group_name: Name of the group (e.g., 'odds_api', 'nba_com')
        
    Returns:
        List of scraper names in that group
        
    Raises:
        ValueError: If group_name not found
        
    Example:
        >>> odds_scrapers = get_scrapers_by_group('odds_api')
        >>> for scraper_name in odds_scrapers:
        ...     scraper = get_scraper_instance(scraper_name)
    """
    if group_name not in SCRAPER_GROUPS:
        available = list(SCRAPER_GROUPS.keys())
        raise ValueError(
            f"Unknown scraper group: {group_name}. "
            f"Available groups: {available}"
        )
    
    return SCRAPER_GROUPS[group_name]
