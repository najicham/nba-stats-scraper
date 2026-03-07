"""
MLB Raw Data Processors

This package contains processors for MLB scraped data from GCS → BigQuery.

Processors:
- MlbPitcherStatsProcessor: BDL pitcher game stats (strikeouts, IP, etc.)
- MlbBatterStatsProcessor: BDL batter game stats (strikeouts, AB - for bottom-up model)
- MlbApiPitcherStatsProcessor: MLB Stats API pitcher stats (strikeouts, IP, K/9, etc.)
- MlbApiBatterStatsProcessor: MLB Stats API batter stats (strikeouts, AB, K rate, etc.)
- MlbScheduleProcessor: MLB Stats API schedule (probable pitchers - CRITICAL)
- MlbLineupsProcessor: MLB Stats API lineups (batting order - for bottom-up model)
- MlbPitcherPropsProcessor: Odds API pitcher props (strikeout lines)
- MlbBatterPropsProcessor: Odds API batter props (strikeout lines for bottom-up model)
- MlbEventsProcessor: Odds API event IDs (for joining props to games)
- MlbGameLinesProcessor: Odds API game lines (moneyline, spread, totals)
- MlbStatcastDailyProcessor: Statcast daily pitcher summaries (SwStr%, CSW%, whiff rate)
"""

from .mlb_pitcher_stats_processor import MlbPitcherStatsProcessor
from .mlb_batter_stats_processor import MlbBatterStatsProcessor
from .mlbapi_pitcher_stats_processor import MlbApiPitcherStatsProcessor
from .mlbapi_batter_stats_processor import MlbApiBatterStatsProcessor
from .mlb_schedule_processor import MlbScheduleProcessor
from .mlb_lineups_processor import MlbLineupsProcessor
from .mlb_pitcher_props_processor import MlbPitcherPropsProcessor
from .mlb_batter_props_processor import MlbBatterPropsProcessor
from .mlb_events_processor import MlbEventsProcessor
from .mlb_game_lines_processor import MlbGameLinesProcessor
from .mlb_statcast_daily_processor import MlbStatcastDailyProcessor

__all__ = [
    'MlbPitcherStatsProcessor',
    'MlbBatterStatsProcessor',
    'MlbApiPitcherStatsProcessor',
    'MlbApiBatterStatsProcessor',
    'MlbScheduleProcessor',
    'MlbLineupsProcessor',
    'MlbPitcherPropsProcessor',
    'MlbBatterPropsProcessor',
    'MlbEventsProcessor',
    'MlbGameLinesProcessor',
    'MlbStatcastDailyProcessor',
]
