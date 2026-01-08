"""
MLB Scraper Registry - Single Source of Truth for MLB Scrapers

This module provides centralized scraper configuration and instantiation for:
- Flask scraper service (main_scraper_service.py with SPORT=mlb)
- Orchestration system
- Any other system that needs to dynamically load scrapers

Usage:
    from scrapers.mlb.registry import get_scraper_instance, MLB_SCRAPER_REGISTRY

    # Get list of available scrapers
    scrapers = list(MLB_SCRAPER_REGISTRY.keys())

    # Instantiate a scraper
    scraper = get_scraper_instance('mlb_schedule')

Path: scrapers/mlb/registry.py
Created: 2026-01-07
"""

import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# MLB SCRAPER REGISTRY - Single Source of Truth
# ============================================================================
# Format: "scraper_name": ("module.path", "ClassName")
# ============================================================================

MLB_SCRAPER_REGISTRY: Dict[str, Tuple[str, str]] = {
    # ========================================================================
    # Ball Don't Lie Scrapers (13 total)
    # ========================================================================
    "mlb_games": (
        "scrapers.mlb.balldontlie.mlb_games",
        "MlbGamesScraper"
    ),
    "mlb_box_scores": (
        "scrapers.mlb.balldontlie.mlb_box_scores",
        "MlbBoxScoresScraper"
    ),
    "mlb_live_box_scores": (
        "scrapers.mlb.balldontlie.mlb_live_box_scores",
        "MlbLiveBoxScoresScraper"
    ),
    "mlb_pitcher_stats": (
        "scrapers.mlb.balldontlie.mlb_pitcher_stats",
        "MlbPitcherStatsScraper"
    ),
    "mlb_batter_stats": (
        "scrapers.mlb.balldontlie.mlb_batter_stats",
        "MlbBatterStatsScraper"
    ),
    "mlb_active_players": (
        "scrapers.mlb.balldontlie.mlb_active_players",
        "MlbActivePlayersScraper"
    ),
    "mlb_injuries": (
        "scrapers.mlb.balldontlie.mlb_injuries",
        "MlbInjuriesScraper"
    ),
    "mlb_player_splits": (
        "scrapers.mlb.balldontlie.mlb_player_splits",
        "MlbPlayerSplitsScraper"
    ),
    "mlb_player_versus": (
        "scrapers.mlb.balldontlie.mlb_player_versus",
        "MlbPlayerVersusScraper"
    ),
    "mlb_season_stats": (
        "scrapers.mlb.balldontlie.mlb_season_stats",
        "MlbSeasonStatsScraper"
    ),
    "mlb_standings": (
        "scrapers.mlb.balldontlie.mlb_standings",
        "MlbStandingsScraper"
    ),
    "mlb_team_season_stats": (
        "scrapers.mlb.balldontlie.mlb_team_season_stats",
        "MlbTeamSeasonStatsScraper"
    ),
    "mlb_teams": (
        "scrapers.mlb.balldontlie.mlb_teams",
        "MlbTeamsScraper"
    ),

    # ========================================================================
    # MLB Stats API Scrapers (3 total)
    # ========================================================================
    "mlb_schedule": (
        "scrapers.mlb.mlbstatsapi.mlb_schedule",
        "MlbScheduleScraper"
    ),
    "mlb_lineups": (
        "scrapers.mlb.mlbstatsapi.mlb_lineups",
        "MlbLineupsScraper"
    ),
    "mlb_game_feed": (
        "scrapers.mlb.mlbstatsapi.mlb_game_feed",
        "MlbGameFeedScraper"
    ),

    # ========================================================================
    # Odds API Scrapers (8 total)
    # ========================================================================
    "mlb_events": (
        "scrapers.mlb.oddsapi.mlb_events",
        "MlbEventsOddsScraper"
    ),
    "mlb_events_his": (
        "scrapers.mlb.oddsapi.mlb_events_his",
        "MlbEventsHistoricalScraper"
    ),
    "mlb_game_lines": (
        "scrapers.mlb.oddsapi.mlb_game_lines",
        "MlbGameLinesScraper"
    ),
    "mlb_game_lines_his": (
        "scrapers.mlb.oddsapi.mlb_game_lines_his",
        "MlbGameLinesHistoricalScraper"
    ),
    "mlb_pitcher_props": (
        "scrapers.mlb.oddsapi.mlb_pitcher_props",
        "MlbPitcherPropsScraper"
    ),
    "mlb_pitcher_props_his": (
        "scrapers.mlb.oddsapi.mlb_pitcher_props_his",
        "MlbPitcherPropsHistoricalScraper"
    ),
    "mlb_batter_props": (
        "scrapers.mlb.oddsapi.mlb_batter_props",
        "MlbBatterPropsScraper"
    ),
    "mlb_batter_props_his": (
        "scrapers.mlb.oddsapi.mlb_batter_props_his",
        "MlbBatterPropsHistoricalScraper"
    ),

    # ========================================================================
    # External Data Scrapers (3 total)
    # ========================================================================
    "mlb_weather": (
        "scrapers.mlb.external.mlb_weather",
        "MlbWeatherScraper"
    ),
    "mlb_ballpark_factors": (
        "scrapers.mlb.external.mlb_ballpark_factors",
        "MlbBallparkFactorsScraper"
    ),
    "mlb_umpire_stats": (
        "scrapers.mlb.external.mlb_umpire_stats",
        "MlbUmpireStatsScraper"
    ),

    # ========================================================================
    # Statcast Scrapers (1 total)
    # ========================================================================
    "mlb_statcast_pitcher": (
        "scrapers.mlb.statcast.mlb_statcast_pitcher",
        "MlbStatcastPitcherScraper"
    ),
}


def get_scraper_instance(scraper_name: str):
    """
    Dynamically load and instantiate a scraper by name.

    Args:
        scraper_name: Name of the scraper (e.g., 'mlb_schedule')

    Returns:
        Instantiated scraper object

    Raises:
        ValueError: If scraper not found in registry
        ImportError: If scraper module cannot be imported
    """
    if scraper_name not in MLB_SCRAPER_REGISTRY:
        raise ValueError(
            f"Unknown MLB scraper: {scraper_name}. "
            f"Available: {list(MLB_SCRAPER_REGISTRY.keys())}"
        )

    module_path, class_name = MLB_SCRAPER_REGISTRY[scraper_name]

    try:
        import importlib
        module = importlib.import_module(module_path)
        scraper_class = getattr(module, class_name)
        return scraper_class()
    except ImportError as e:
        logger.error(f"Failed to import {module_path}: {e}")
        raise
    except AttributeError as e:
        logger.error(f"Class {class_name} not found in {module_path}: {e}")
        raise


def get_all_scraper_names() -> list:
    """Get list of all registered MLB scraper names."""
    return list(MLB_SCRAPER_REGISTRY.keys())


def get_scrapers_by_source(source: str) -> list:
    """
    Get scrapers filtered by data source.

    Args:
        source: One of 'balldontlie', 'mlbstatsapi', 'oddsapi', 'external', 'statcast'

    Returns:
        List of scraper names for that source
    """
    source_map = {
        'balldontlie': ['mlb_games', 'mlb_box_scores', 'mlb_live_box_scores',
                        'mlb_pitcher_stats', 'mlb_batter_stats', 'mlb_active_players',
                        'mlb_injuries', 'mlb_player_splits', 'mlb_player_versus',
                        'mlb_season_stats', 'mlb_standings', 'mlb_team_season_stats',
                        'mlb_teams'],
        'mlbstatsapi': ['mlb_schedule', 'mlb_lineups', 'mlb_game_feed'],
        'oddsapi': ['mlb_events', 'mlb_events_his', 'mlb_game_lines',
                    'mlb_game_lines_his', 'mlb_pitcher_props', 'mlb_pitcher_props_his',
                    'mlb_batter_props', 'mlb_batter_props_his'],
        'external': ['mlb_weather', 'mlb_ballpark_factors', 'mlb_umpire_stats'],
        'statcast': ['mlb_statcast_pitcher'],
    }
    return source_map.get(source, [])


# Priority scrapers for minimum viable pipeline
PRIORITY_SCRAPERS = [
    'mlb_schedule',      # What games today
    'mlb_lineups',       # Starting pitchers
    'mlb_pitcher_props', # Strikeout lines
    'mlb_game_feed',     # Live game data
    'mlb_games',         # Game results
]
