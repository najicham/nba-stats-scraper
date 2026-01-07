"""
MLB External Data Scrapers

Scrapers for external MLB data sources beyond the core APIs.

Available Scrapers:
- mlb_umpire_stats: Umpire accuracy and K zone tendencies (UmpScorecards)
- mlb_ballpark_factors: Park-specific K factors (static data)
- mlb_weather: Stadium weather conditions (OpenWeatherMap)

These scrapers provide supplementary data for fine-tuning K predictions.
"""

from .mlb_umpire_stats import MlbUmpireStatsScraper
from .mlb_ballpark_factors import MlbBallparkFactorsScraper
from .mlb_weather import MlbWeatherScraper

__all__ = [
    'MlbUmpireStatsScraper',
    'MlbBallparkFactorsScraper',
    'MlbWeatherScraper',
]
