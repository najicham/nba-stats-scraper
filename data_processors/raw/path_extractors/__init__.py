"""
Path extractors for extracting metadata from GCS file paths.

This module provides a registry-based system for extracting options from file paths.
Each extractor is responsible for matching and extracting metadata from specific path patterns.
"""

from .registry import ExtractorRegistry
from .base import PathExtractor

# Import all extractors
from .bdl_extractors import (
    BDLStandingsExtractor,
    BDLInjuriesExtractor,
    BDLLiveBoxscoresExtractor,
    BDLPlayerBoxScoresExtractor,
    BDLBoxscoresExtractor,
    BDLActivePlayersExtractor,
)
from .nba_extractors import (
    NBAScoreboardV2Extractor,
    NBAPlayerBoxscoresExtractor,
    NBAPlayByPlayExtractor,
    NBARefereeAssignmentsExtractor,
    NBAScheduleExtractor,
    NBAGamebooksDataExtractor,
    NBAPlayerMovementExtractor,
    NBATeamBoxscoreExtractor,
    NBAInjuryReportExtractor,
    NBAPlayerListExtractor,
)
from .espn_extractors import (
    ESPNBoxscoresExtractor,
    ESPNRostersExtractor,
    ESPNScoreboardExtractor,
)
from .odds_extractors import (
    OddsAPIGameLinesHistoryExtractor,
    BettingPropsExtractor,
)
from .bigdataball_extractors import (
    BigDataBallPbpExtractor,
    BasketballRefRosterExtractor,
)
from .external_extractors import (
    NumberFireProjectionsExtractor,
    FantasyProsProjectionsExtractor,
    TeamRankingsStatsExtractor,
    HashtagBasketballDvpExtractor,
    RotoWireLineupsExtractor,
    CoversRefereeStatsExtractor,
    NBATrackingStatsExtractor,
    VSiNBettingSplitsExtractor,
    DailyFantasyFuelProjectionsExtractor,
    DimersProjectionsExtractor,
)
from .mlb_extractors import (
    MLBBDLStatsExtractor,
    MLBStatsAPIExtractor,
    MLBOddsAPIPropsExtractor,
    MLBOddsAPIGameLinesExtractor,
    MLBOddsAPIEventsExtractor,
)


def create_registry() -> ExtractorRegistry:
    """
    Create and populate the extractor registry.

    The order of registration matters for extractors that may have overlapping patterns.
    More specific patterns should be registered first.

    Returns:
        Populated ExtractorRegistry instance
    """
    registry = ExtractorRegistry()

    # Ball-Don't-Lie extractors
    # IMPORTANT: player-box-scores MUST come before boxscores due to substring matching
    registry.register(BDLPlayerBoxScoresExtractor())
    registry.register(BDLLiveBoxscoresExtractor())
    registry.register(BDLBoxscoresExtractor())
    registry.register(BDLStandingsExtractor())
    registry.register(BDLInjuriesExtractor())
    registry.register(BDLActivePlayersExtractor())

    # NBA.com extractors
    registry.register(NBAScoreboardV2Extractor())
    registry.register(NBAPlayerBoxscoresExtractor())
    registry.register(NBAPlayByPlayExtractor())
    registry.register(NBARefereeAssignmentsExtractor())
    registry.register(NBAScheduleExtractor())
    registry.register(NBAGamebooksDataExtractor())
    registry.register(NBAPlayerMovementExtractor())
    registry.register(NBATeamBoxscoreExtractor())
    registry.register(NBAInjuryReportExtractor())
    registry.register(NBAPlayerListExtractor())

    # ESPN extractors
    registry.register(ESPNBoxscoresExtractor())
    registry.register(ESPNRostersExtractor())
    registry.register(ESPNScoreboardExtractor())

    # Odds extractors
    registry.register(OddsAPIGameLinesHistoryExtractor())
    registry.register(BettingPropsExtractor())

    # BigDataBall and Basketball Reference extractors
    registry.register(BasketballRefRosterExtractor())
    registry.register(BigDataBallPbpExtractor())

    # Projection extractors (Session 401)
    registry.register(NumberFireProjectionsExtractor())
    registry.register(FantasyProsProjectionsExtractor())

    # External data source extractors (Session 401)
    # DvP MUST come before generic hashtagbasketball due to substring matching
    registry.register(HashtagBasketballDvpExtractor())
    registry.register(TeamRankingsStatsExtractor())
    registry.register(RotoWireLineupsExtractor())
    registry.register(CoversRefereeStatsExtractor())
    registry.register(NBATrackingStatsExtractor())
    # VSiN betting-splits MUST come before generic vsin due to substring matching
    registry.register(VSiNBettingSplitsExtractor())
    registry.register(DailyFantasyFuelProjectionsExtractor())
    registry.register(DimersProjectionsExtractor())

    # MLB extractors
    registry.register(MLBBDLStatsExtractor())
    registry.register(MLBStatsAPIExtractor())
    registry.register(MLBOddsAPIPropsExtractor())
    registry.register(MLBOddsAPIGameLinesExtractor())
    registry.register(MLBOddsAPIEventsExtractor())

    return registry


__all__ = [
    'PathExtractor',
    'ExtractorRegistry',
    'create_registry',
]
