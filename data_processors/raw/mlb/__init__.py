"""
MLB Raw Data Processors

This package contains processors for MLB scraped data from GCS → BigQuery.

Processors:
- MlbPitcherStatsProcessor: BDL pitcher game stats (strikeouts, IP, etc.)
- MlbBatterStatsProcessor: BDL batter game stats (strikeouts, AB - for bottom-up model)
- MlbScheduleProcessor: MLB Stats API schedule (probable pitchers - CRITICAL)
- MlbLineupsProcessor: MLB Stats API lineups (batting order - for bottom-up model)
- MlbPitcherPropsProcessor: Odds API pitcher props (strikeout lines)
- MlbBatterPropsProcessor: Odds API batter props (strikeout lines for bottom-up model)
- MlbEventsProcessor: Odds API event IDs (for joining props to games)
- MlbGameLinesProcessor: Odds API game lines (moneyline, spread, totals)
"""

from .mlb_pitcher_stats_processor import MlbPitcherStatsProcessor
from .mlb_batter_stats_processor import MlbBatterStatsProcessor
from .mlb_schedule_processor import MlbScheduleProcessor
from .mlb_lineups_processor import MlbLineupsProcessor
from .mlb_pitcher_props_processor import MlbPitcherPropsProcessor
from .mlb_batter_props_processor import MlbBatterPropsProcessor
from .mlb_events_processor import MlbEventsProcessor
from .mlb_game_lines_processor import MlbGameLinesProcessor

__all__ = [
    'MlbPitcherStatsProcessor',
    'MlbBatterStatsProcessor',
    'MlbScheduleProcessor',
    'MlbLineupsProcessor',
    'MlbPitcherPropsProcessor',
    'MlbBatterPropsProcessor',
    'MlbEventsProcessor',
    'MlbGameLinesProcessor',
]
