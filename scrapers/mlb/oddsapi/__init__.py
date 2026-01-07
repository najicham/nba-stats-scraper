"""
MLB Odds API Scrapers

Scrapers for collecting MLB betting odds data from The Odds API.

Current Scrapers (live data):
- mlb_events: Get event IDs for MLB games
- mlb_game_lines: Get moneyline, spread, and totals
- mlb_pitcher_props: Get pitcher strikeout and other props
- mlb_batter_props: Get batter strikeout and other props

Historical Scrapers (for backfilling/training):
- mlb_events_his: Get historical event IDs at snapshot
- mlb_game_lines_his: Get historical game lines at snapshot
- mlb_pitcher_props_his: Get historical pitcher props at snapshot
- mlb_batter_props_his: Get historical batter props at snapshot
"""

# Current scrapers
from .mlb_events import MlbEventsOddsScraper
from .mlb_game_lines import MlbGameLinesScraper
from .mlb_pitcher_props import MlbPitcherPropsScraper
from .mlb_batter_props import MlbBatterPropsScraper

# Historical scrapers
from .mlb_events_his import MlbEventsHistoricalScraper
from .mlb_game_lines_his import MlbGameLinesHistoricalScraper
from .mlb_pitcher_props_his import MlbPitcherPropsHistoricalScraper
from .mlb_batter_props_his import MlbBatterPropsHistoricalScraper

__all__ = [
    # Current
    'MlbEventsOddsScraper',
    'MlbGameLinesScraper',
    'MlbPitcherPropsScraper',
    'MlbBatterPropsScraper',
    # Historical
    'MlbEventsHistoricalScraper',
    'MlbGameLinesHistoricalScraper',
    'MlbPitcherPropsHistoricalScraper',
    'MlbBatterPropsHistoricalScraper',
]
