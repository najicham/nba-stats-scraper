"""
MLB Scrapers Package

Contains all MLB data scrapers organized by source:
- balldontlie: Ball Don't Lie API (stats, injuries, standings, etc.)
- mlbstatsapi: Official MLB Stats API (schedule, lineups, game feed)
- oddsapi: The Odds API (betting lines, props)
- statcast: Baseball Savant via pybaseball (advanced metrics)

Total: 26+ scrapers for comprehensive MLB data collection.
"""

# Ball Don't Lie scrapers
from .balldontlie import (
    MlbPitcherStatsScraper,
    MlbBatterStatsScraper,
    MlbGamesScraper,
    MlbActivePlayersScraper,
    MlbSeasonStatsScraper,
    MlbInjuriesScraper,
    MlbPlayerSplitsScraper,
    MlbStandingsScraper,
    MlbBoxScoresScraper,
    MlbLiveBoxScoresScraper,
    MlbTeamSeasonStatsScraper,
    MlbPlayerVersusScraper,
    MlbTeamsScraper,
)

# MLB Stats API scrapers
from .mlbstatsapi import (
    MlbScheduleScraper,
    MlbLineupsScraper,
    MlbGameFeedScraper,
)

# Odds API scrapers
from .oddsapi import (
    MlbEventsOddsScraper,
    MlbGameLinesScraper,
    MlbPitcherPropsScraper,
    MlbBatterPropsScraper,
    MlbEventsHistoricalScraper,
    MlbGameLinesHistoricalScraper,
    MlbPitcherPropsHistoricalScraper,
    MlbBatterPropsHistoricalScraper,
)

# Statcast scrapers (requires pybaseball)
try:
    from .statcast import MlbStatcastPitcherScraper
    _STATCAST_AVAILABLE = True
except ImportError:
    _STATCAST_AVAILABLE = False

# External data scrapers
from .external import (
    MlbUmpireStatsScraper,
    MlbBallparkFactorsScraper,
    MlbWeatherScraper,
)

__all__ = [
    # BDL
    'MlbPitcherStatsScraper',
    'MlbBatterStatsScraper',
    'MlbGamesScraper',
    'MlbActivePlayersScraper',
    'MlbSeasonStatsScraper',
    'MlbInjuriesScraper',
    'MlbPlayerSplitsScraper',
    'MlbStandingsScraper',
    'MlbBoxScoresScraper',
    'MlbLiveBoxScoresScraper',
    'MlbTeamSeasonStatsScraper',
    'MlbPlayerVersusScraper',
    'MlbTeamsScraper',
    # MLB Stats API
    'MlbScheduleScraper',
    'MlbLineupsScraper',
    'MlbGameFeedScraper',
    # Odds API (current)
    'MlbEventsOddsScraper',
    'MlbGameLinesScraper',
    'MlbPitcherPropsScraper',
    'MlbBatterPropsScraper',
    # Odds API (historical)
    'MlbEventsHistoricalScraper',
    'MlbGameLinesHistoricalScraper',
    'MlbPitcherPropsHistoricalScraper',
    'MlbBatterPropsHistoricalScraper',
    # External data
    'MlbUmpireStatsScraper',
    'MlbBallparkFactorsScraper',
    'MlbWeatherScraper',
]

if _STATCAST_AVAILABLE:
    __all__.append('MlbStatcastPitcherScraper')
