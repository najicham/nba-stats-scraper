"""
Source handlers for roster registry data fetching.

Each source handler is responsible for fetching and parsing roster data
from a specific data source (ESPN, NBA.com, Basketball Reference).
"""

from .espn_source import ESPNSourceHandler
from .nba_source import NBASourceHandler
from .br_source import BRSourceHandler

__all__ = [
    'ESPNSourceHandler',
    'NBASourceHandler',
    'BRSourceHandler',
]
