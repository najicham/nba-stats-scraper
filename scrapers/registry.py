"""
Scraper Registry - Single Source of Truth for NBA Scrapers

This module provides centralized scraper configuration and instantiation for:
- Flask scraper service (main_scraper_service.py)
- Orchestration system (workflow_executor.py)
- Any other system that needs to dynamically load scrapers

Usage:
    from scrapers.registry import get_scraper_instance, SCRAPER_REGISTRY
    
    # Get list of available scrapers
    scrapers = list(SCRAPER_REGISTRY.keys())
    
    # Instantiate a scraper
    scraper = get_scraper_instance('oddsa_events_his')
    
Path: scrapers/registry.py
"""

import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# SCRAPER REGISTRY - Single Source of Truth
# ============================================================================
# Format: "scraper_name": ("module.path", "ClassName")
#
# When adding new scrapers:
# 1. Add entry here with correct module path and class name
# 2. Scraper will be automatically available in Flask app and orchestration
# 3. No other changes needed!
# ============================================================================

SCRAPER_REGISTRY: Dict[str, Tuple[str, str]] = {
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
    
    # ========================================================================
    # BettingPros Scrapers (2 total)
    # ========================================================================
    "bp_events": (
        "scrapers.bettingpros.bp_events", 
        "BettingProsEvents"
    ),
    "bp_player_props": (
        "scrapers.bettingpros.bp_player_props", 
        "BettingProsPlayerProps"
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
        "scrapers.nbacom.nbac_current_schedule_v2_1", 
        "GetDataNbaSeasonSchedule"
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
