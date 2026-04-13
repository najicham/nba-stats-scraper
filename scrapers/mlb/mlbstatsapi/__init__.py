"""
MLB Stats API Scrapers

Scrapers for the official MLB Stats API (https://statsapi.mlb.com).
Free, no auth required, cloud-friendly.

Available Scrapers:
- mlb_schedule: Daily schedule with probable pitchers (CRITICAL for predictions)
- mlb_lineups: Game lineups with batting order (for bottom-up model)
- mlb_game_feed: Play-by-play pitch data (for detailed K analysis)
- mlb_game_feed_daily: Daily batch per-pitch scraper (all Final games for a date)
"""

from .mlb_schedule import MlbScheduleScraper
from .mlb_lineups import MlbLineupsScraper
from .mlb_game_feed import MlbGameFeedScraper
from .mlb_game_feed_daily import MlbGameFeedDailyScraper

__all__ = [
    'MlbScheduleScraper',
    'MlbLineupsScraper',
    'MlbGameFeedScraper',
    'MlbGameFeedDailyScraper',
]
