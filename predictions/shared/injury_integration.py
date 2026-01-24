# predictions/shared/injury_integration.py

"""
Injury Integration Module for Predictions Pipeline

Provides comprehensive injury data handling for predictions:
1. Multi-source injury data loading (NBA.com + Ball Don't Lie)
2. Player status tracking with confidence levels
3. Teammate availability impact calculation
4. Usage projection adjustments for injured starters
5. Filtering of injured players from predictions

Data Sources:
- nba_raw.nbac_injury_report: Official NBA.com injury reports (primary)
- nba_raw.bdl_injuries: Ball Don't Lie backup source (validation)

Status Levels:
- OUT: Skip prediction entirely (player will not play)
- DOUBTFUL: High risk, consider skipping or flagging
- QUESTIONABLE: Medium risk, flag prediction with warning
- PROBABLE: Low risk, proceed normally
- AVAILABLE: No issues, proceed normally

Usage:
    from predictions.shared.injury_integration import InjuryIntegration

    integration = InjuryIntegration()

    # Load all injury data for a game date
    injury_data = integration.load_injuries_for_date(game_date)

    # Check team's injured players and calculate impact
    team_impact = integration.calculate_teammate_impact(
        player_lookup='lebron-james',
        team_abbr='LAL',
        game_date=game_date
    )

    # Adjust usage projections based on injured teammates
    adjusted_usage = integration.adjust_usage_projection(
        player_lookup='lebron-james',
        base_usage=0.28,
        injured_teammates=['anthony-davis', 'dangelo-russell'],
        game_date=game_date
    )
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Set
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PlayerInjuryInfo:
    """Complete injury information for a player"""
    player_lookup: str
    status: str  # 'out', 'doubtful', 'questionable', 'probable', 'available'
    reason: Optional[str]
    reason_category: Optional[str]
    team_abbr: Optional[str]
    game_date: date
    source: str  # 'nba_com', 'bdl', 'combined'
    confidence: float  # 0.0-1.0 based on source quality and recency
    report_hour: Optional[int]  # Hour of latest report (for recency)

    @property
    def should_skip(self) -> bool:
        """Player should be skipped from predictions"""
        return self.status in ('out',)

    @property
    def has_warning(self) -> bool:
        """Prediction should include injury warning"""
        return self.status in ('doubtful', 'questionable')

    @property
    def is_risky(self) -> bool:
        """Any injury risk level"""
        return self.status in ('out', 'doubtful', 'questionable')


@dataclass
class TeammateImpact:
    """Impact of injured teammates on a player's projections"""
    player_lookup: str
    team_abbr: str
    game_date: date

    # Injured teammates summary
    out_teammates: List[str] = field(default_factory=list)
    doubtful_teammates: List[str] = field(default_factory=list)
    questionable_teammates: List[str] = field(default_factory=list)

    # Key player injuries
    out_starters: List[str] = field(default_factory=list)
    out_star_players: List[str] = field(default_factory=list)

    # Usage impact factors
    usage_boost_factor: float = 1.0  # Multiplier for usage projection
    minutes_boost_factor: float = 1.0  # Multiplier for minutes projection
    opportunity_score: float = 0.0  # 0-100 score for increased opportunity

    # Confidence in impact calculation
    impact_confidence: float = 0.8

    @property
    def has_significant_impact(self) -> bool:
        """Whether teammate injuries should significantly affect projections"""
        return len(self.out_starters) > 0 or len(self.out_star_players) > 0

    @property
    def total_injured(self) -> int:
        return len(self.out_teammates) + len(self.doubtful_teammates) + len(self.questionable_teammates)


@dataclass
class InjuryFilterResult:
    """Result of injury filtering for a list of players"""
    date: date
    players_checked: int
    players_skipped: int  # OUT status
    players_warned: int   # DOUBTFUL/QUESTIONABLE
    players_ok: int       # PROBABLE/AVAILABLE or no injury
    skipped_players: List[str]
    warned_players: List[str]


# =============================================================================
# MAIN CLASS
# =============================================================================

class InjuryIntegration:
    """
    Comprehensive injury data integration for predictions pipeline

    Combines data from multiple sources, calculates teammate impact,
    and provides usage adjustments based on injury context.
    """

    # Status levels for filtering
    SKIP_STATUSES = {'out'}
    WARNING_STATUSES = {'doubtful', 'questionable'}
    SAFE_STATUSES = {'probable', 'available'}

    # Known star players (high usage, significant impact when injured)
    # This is used for calculating opportunity boost when stars are out
    STAR_PLAYER_LOOKUPS = {
        'lebronjames', 'stephencurry', 'kevindurant', 'giannisantetokounmpo',
        'joelEmbiid', 'jokicnikola', 'jaysonTatum', 'lukadonnic',
        'damianLillard', 'anthonydavis', 'sgiAntetokounmpo', 'domanisabonis',
        'trae-young', 'devinbooker', 'bradleybeal', 'paulgeorge', 'kawhileonard',
        'jimmybutler', 'bamadebayo', 'paolobanchero', 'tyresehaliburton',
        'shaigilgeousalexander', 'chetholmgren', 'victorthewembanyama',
        'jalenjohnson', 'anthonyedwards', 'lamelo-ball', 'dearonFox'
    }

    # Average usage rates by position (for estimating boost when player is out)
    POSITION_USAGE_RATES = {
        'C': 0.20,
        'PF': 0.18,
        'SF': 0.19,
        'SG': 0.18,
        'PG': 0.21,
        'default': 0.19
    }

    def __init__(self, project_id: str = "nba-props-platform"):
        """
        Initialize injury integration

        Args:
            project_id: GCP project ID for BigQuery
        """
        self.project_id = project_id
        self._client = None

        # Caches
        self._injury_cache: Dict[date, Dict[str, PlayerInjuryInfo]] = {}
        self._team_roster_cache: Dict[str, List[str]] = {}  # team -> players
        self._player_usage_cache: Dict[str, float] = {}  # player -> usage rate
        self._player_starter_cache: Dict[str, bool] = {}  # player -> is_starter

    @property
    def client(self) -> bigquery.Client:
        """Lazy-load BigQuery client"""
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    # =========================================================================
    # INJURY DATA LOADING
    # =========================================================================

    def load_injuries_for_date(
        self,
        game_date: date,
        force_refresh: bool = False
    ) -> Dict[str, PlayerInjuryInfo]:
        """
        Load all injury data for a game date

        Combines NBA.com and Ball Don't Lie sources, preferring the most recent
        and highest confidence data when sources conflict.

        Args:
            game_date: Date to load injuries for
            force_refresh: Force reload from BigQuery even if cached

        Returns:
            Dict mapping player_lookup to PlayerInjuryInfo
        """
        cache_key = game_date
        if not force_refresh and cache_key in self._injury_cache:
            return self._injury_cache[cache_key]

        injuries = {}

        # Load from NBA.com (primary source)
        nba_injuries = self._load_nba_com_injuries(game_date)
        for player, info in nba_injuries.items():
            injuries[player] = info

        # Load from Ball Don't Lie (backup/validation)
        bdl_injuries = self._load_bdl_injuries(game_date)
        for player, info in bdl_injuries.items():
            if player not in injuries:
                # NBA.com doesn't have this player - use BDL data
                info.source = 'bdl'
                injuries[player] = info
            else:
                # Both sources have data - validate and enhance confidence
                existing = injuries[player]
                if existing.status == info.status:
                    # Sources agree - boost confidence
                    existing.confidence = min(1.0, existing.confidence + 0.1)
                    existing.source = 'combined'
                else:
                    # Sources disagree - prefer more recent report
                    if (info.report_hour or 0) > (existing.report_hour or 0):
                        # BDL is more recent, but keep NBA.com as primary
                        logger.warning(
                            f"Injury status conflict for {player}: "
                            f"NBA.com={existing.status}, BDL={info.status}"
                        )

        logger.info(
            f"Loaded {len(injuries)} injury records for {game_date} "
            f"(NBA.com: {len(nba_injuries)}, BDL: {len(bdl_injuries)})"
        )

        self._injury_cache[cache_key] = injuries
        return injuries

    def _load_nba_com_injuries(self, game_date: date) -> Dict[str, PlayerInjuryInfo]:
        """Load injuries from NBA.com injury report table"""
        query = """
        SELECT
            player_lookup,
            injury_status,
            reason,
            reason_category,
            team,
            game_date,
            report_hour,
            confidence_score
        FROM `nba-props-platform.nba_raw.nbac_injury_report`
        WHERE game_date = @game_date
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY report_date DESC, report_hour DESC
        ) = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        injuries = {}
        try:
            result = self.client.query(query, job_config=job_config).result()

            for row in result:
                status = row.injury_status.lower() if row.injury_status else 'unknown'
                injuries[row.player_lookup] = PlayerInjuryInfo(
                    player_lookup=row.player_lookup,
                    status=status,
                    reason=row.reason,
                    reason_category=row.reason_category,
                    team_abbr=row.team,
                    game_date=row.game_date,
                    source='nba_com',
                    confidence=row.confidence_score or 0.9,
                    report_hour=row.report_hour
                )

        except Exception as e:
            logger.error(f"Error loading NBA.com injuries for {game_date}: {e}", exc_info=True)

        return injuries

    def _load_bdl_injuries(self, game_date: date) -> Dict[str, PlayerInjuryInfo]:
        """Load injuries from Ball Don't Lie table"""
        query = """
        SELECT
            player_lookup,
            injury_status_normalized as injury_status,
            injury_description as reason,
            reason_category,
            team_abbr,
            scrape_date,
            parsing_confidence
        FROM `nba-props-platform.nba_raw.bdl_injuries`
        WHERE scrape_date = @game_date
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY scrape_timestamp DESC
        ) = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        injuries = {}
        try:
            result = self.client.query(query, job_config=job_config).result()

            for row in result:
                status = row.injury_status.lower() if row.injury_status else 'unknown'
                injuries[row.player_lookup] = PlayerInjuryInfo(
                    player_lookup=row.player_lookup,
                    status=status,
                    reason=row.reason,
                    reason_category=row.reason_category,
                    team_abbr=row.team_abbr,
                    game_date=row.scrape_date,
                    source='bdl',
                    confidence=row.parsing_confidence or 0.7,
                    report_hour=None
                )

        except Exception as e:
            logger.error(f"Error loading BDL injuries for {game_date}: {e}", exc_info=True)

        return injuries

    # =========================================================================
    # PLAYER STATUS CHECKING
    # =========================================================================

    def check_player(
        self,
        player_lookup: str,
        game_date: date
    ) -> PlayerInjuryInfo:
        """
        Check injury status for a single player

        Args:
            player_lookup: Player identifier
            game_date: Date of the game

        Returns:
            PlayerInjuryInfo with status and metadata
        """
        injuries = self.load_injuries_for_date(game_date)

        if player_lookup in injuries:
            return injuries[player_lookup]

        # No injury report = available
        return PlayerInjuryInfo(
            player_lookup=player_lookup,
            status='available',
            reason=None,
            reason_category=None,
            team_abbr=None,
            game_date=game_date,
            source='none',
            confidence=1.0,
            report_hour=None
        )

    def check_players_batch(
        self,
        player_lookups: List[str],
        game_date: date
    ) -> Dict[str, PlayerInjuryInfo]:
        """
        Check injury status for multiple players efficiently

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game

        Returns:
            Dict mapping player_lookup to PlayerInjuryInfo
        """
        injuries = self.load_injuries_for_date(game_date)

        result = {}
        for player in player_lookups:
            if player in injuries:
                result[player] = injuries[player]
            else:
                result[player] = PlayerInjuryInfo(
                    player_lookup=player,
                    status='available',
                    reason=None,
                    reason_category=None,
                    team_abbr=None,
                    game_date=game_date,
                    source='none',
                    confidence=1.0,
                    report_hour=None
                )

        return result

    def filter_injured_players(
        self,
        player_lookups: List[str],
        game_date: date,
        skip_doubtful: bool = False
    ) -> InjuryFilterResult:
        """
        Filter out injured players from a list

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game
            skip_doubtful: If True, also skip DOUBTFUL players (not just OUT)

        Returns:
            InjuryFilterResult with categorized players
        """
        injuries = self.check_players_batch(player_lookups, game_date)

        skipped = []
        warned = []
        ok = []

        skip_statuses = self.SKIP_STATUSES.copy()
        if skip_doubtful:
            skip_statuses.add('doubtful')

        for player, info in injuries.items():
            if info.status in skip_statuses:
                skipped.append(player)
            elif info.status in self.WARNING_STATUSES:
                warned.append(player)
            else:
                ok.append(player)

        return InjuryFilterResult(
            date=game_date,
            players_checked=len(player_lookups),
            players_skipped=len(skipped),
            players_warned=len(warned),
            players_ok=len(ok),
            skipped_players=skipped,
            warned_players=warned
        )

    # =========================================================================
    # TEAMMATE IMPACT CALCULATION
    # =========================================================================

    def calculate_teammate_impact(
        self,
        player_lookup: str,
        team_abbr: str,
        game_date: date
    ) -> TeammateImpact:
        """
        Calculate impact of injured teammates on a player's projections

        When key teammates are injured, remaining players typically see:
        - Increased usage rate
        - More minutes
        - Different shot distribution

        Args:
            player_lookup: Player to calculate impact for
            team_abbr: Player's team abbreviation
            game_date: Date of the game

        Returns:
            TeammateImpact with boost factors
        """
        # Get all injured players on this team
        injuries = self.load_injuries_for_date(game_date)

        team_injuries = {
            lookup: info for lookup, info in injuries.items()
            if info.team_abbr == team_abbr and lookup != player_lookup
        }

        # Categorize by status
        out_teammates = [p for p, i in team_injuries.items() if i.status == 'out']
        doubtful_teammates = [p for p, i in team_injuries.items() if i.status == 'doubtful']
        questionable_teammates = [p for p, i in team_injuries.items() if i.status == 'questionable']

        # Identify starters and star players among injured
        out_starters = [p for p in out_teammates if self._is_starter(p, team_abbr)]
        out_star_players = [p for p in out_teammates if self._is_star_player(p)]

        # Calculate usage boost
        usage_boost = self._calculate_usage_boost(
            player_lookup, out_teammates, out_starters, out_star_players, team_abbr
        )

        # Calculate minutes boost (more conservative)
        minutes_boost = 1.0 + (usage_boost - 1.0) * 0.5  # Half the usage boost

        # Calculate opportunity score (0-100)
        opportunity_score = self._calculate_opportunity_score(
            out_starters, out_star_players, doubtful_teammates
        )

        impact = TeammateImpact(
            player_lookup=player_lookup,
            team_abbr=team_abbr,
            game_date=game_date,
            out_teammates=out_teammates,
            doubtful_teammates=doubtful_teammates,
            questionable_teammates=questionable_teammates,
            out_starters=out_starters,
            out_star_players=out_star_players,
            usage_boost_factor=usage_boost,
            minutes_boost_factor=minutes_boost,
            opportunity_score=opportunity_score,
            impact_confidence=0.8 if len(out_starters) > 0 else 0.6
        )

        if impact.has_significant_impact:
            logger.info(
                f"Significant teammate impact for {player_lookup} on {team_abbr}: "
                f"out_starters={out_starters}, usage_boost={usage_boost:.2f}"
            )

        return impact

    def _calculate_usage_boost(
        self,
        player_lookup: str,
        out_teammates: List[str],
        out_starters: List[str],
        out_star_players: List[str],
        team_abbr: str
    ) -> float:
        """
        Calculate usage boost factor when teammates are out

        Usage redistribution model:
        - When a player is out, their usage is redistributed to remaining players
        - Star/starter players receive larger share of redistribution
        - Capped at 1.25x to avoid unrealistic projections
        """
        if not out_teammates:
            return 1.0

        # Get base usage rates
        player_usage = self._get_player_usage(player_lookup) or 0.19
        player_is_starter = self._is_starter(player_lookup, team_abbr)
        player_is_star = self._is_star_player(player_lookup)

        # Calculate total usage freed up
        freed_usage = 0.0
        for teammate in out_teammates:
            teammate_usage = self._get_player_usage(teammate) or self.POSITION_USAGE_RATES['default']
            freed_usage += teammate_usage

        # Estimate how much of freed usage goes to this player
        # Starters get ~40% of redistribution, bench gets ~20%
        if player_is_star:
            redistribution_share = 0.35
        elif player_is_starter:
            redistribution_share = 0.25
        else:
            redistribution_share = 0.15

        # Calculate boost
        additional_usage = freed_usage * redistribution_share
        usage_boost = 1.0 + (additional_usage / player_usage) if player_usage > 0 else 1.0

        # Cap at reasonable level
        return min(1.25, max(1.0, usage_boost))

    def _calculate_opportunity_score(
        self,
        out_starters: List[str],
        out_star_players: List[str],
        doubtful_teammates: List[str]
    ) -> float:
        """
        Calculate opportunity score (0-100) based on injured teammates

        Higher score = more opportunity for production boost
        """
        score = 0.0

        # Each out starter adds 15 points
        score += len(out_starters) * 15

        # Each out star player adds 25 points
        score += len(out_star_players) * 25

        # Each doubtful player adds 5 points (might not play)
        score += len(doubtful_teammates) * 5

        return min(100.0, score)

    def _is_starter(self, player_lookup: str, team_abbr: str) -> bool:
        """Check if player is a starter (cached)"""
        cache_key = f"{player_lookup}_{team_abbr}"
        if cache_key in self._player_starter_cache:
            return self._player_starter_cache[cache_key]

        # Query player_game_summary for recent starts
        query = """
        SELECT
            COUNTIF(starter = TRUE) / COUNT(*) as start_rate
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            ]
        )

        try:
            result = list(self.client.query(query, job_config=job_config).result())
            if result and result[0].start_rate is not None:
                is_starter = result[0].start_rate > 0.5
                self._player_starter_cache[cache_key] = is_starter
                return is_starter
        except Exception as e:
            logger.debug(f"Could not determine starter status for {player_lookup}: {e}")

        self._player_starter_cache[cache_key] = False
        return False

    def _is_star_player(self, player_lookup: str) -> bool:
        """Check if player is a known star player"""
        # Normalize for comparison
        normalized = player_lookup.replace('-', '').replace("'", '').lower()
        return normalized in self.STAR_PLAYER_LOOKUPS

    def _get_player_usage(self, player_lookup: str) -> Optional[float]:
        """Get player's usage rate (cached)"""
        if player_lookup in self._player_usage_cache:
            return self._player_usage_cache[player_lookup]

        # Query recent usage rate
        query = """
        SELECT AVG(usage_pct) as avg_usage
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
          AND minutes > 10
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            ]
        )

        try:
            result = list(self.client.query(query, job_config=job_config).result())
            if result and result[0].avg_usage is not None:
                usage = float(result[0].avg_usage)
                self._player_usage_cache[player_lookup] = usage
                return usage
        except Exception as e:
            logger.debug(f"Could not get usage for {player_lookup}: {e}")

        return None

    # =========================================================================
    # USAGE PROJECTION ADJUSTMENTS
    # =========================================================================

    def adjust_usage_projection(
        self,
        player_lookup: str,
        base_usage: float,
        team_abbr: str,
        game_date: date
    ) -> Tuple[float, float, str]:
        """
        Adjust usage projection based on injured teammates

        Args:
            player_lookup: Player to adjust projection for
            base_usage: Original usage projection (0.0-1.0)
            team_abbr: Player's team
            game_date: Date of the game

        Returns:
            Tuple of (adjusted_usage, confidence, reason)
        """
        impact = self.calculate_teammate_impact(player_lookup, team_abbr, game_date)

        if not impact.has_significant_impact:
            return base_usage, 0.9, "no_significant_teammate_injuries"

        adjusted = base_usage * impact.usage_boost_factor

        # Cap at reasonable usage rate
        adjusted = min(0.35, adjusted)  # No player should have >35% usage

        reason = f"teammate_injuries:out_starters={impact.out_starters}"

        return adjusted, impact.impact_confidence, reason

    def adjust_points_projection(
        self,
        player_lookup: str,
        base_projection: float,
        team_abbr: str,
        game_date: date
    ) -> Tuple[float, float, str]:
        """
        Adjust points projection based on injured teammates

        Uses a more conservative boost than pure usage rate changes,
        since points depend on shot efficiency which may not improve.

        Args:
            player_lookup: Player to adjust projection for
            base_projection: Original points projection
            team_abbr: Player's team
            game_date: Date of the game

        Returns:
            Tuple of (adjusted_projection, confidence, reason)
        """
        impact = self.calculate_teammate_impact(player_lookup, team_abbr, game_date)

        if not impact.has_significant_impact:
            return base_projection, 0.9, "no_significant_teammate_injuries"

        # Use opportunity score to calculate boost
        # Max boost is 15% for very high opportunity (opportunity_score=100)
        boost_factor = 1.0 + (impact.opportunity_score / 100.0) * 0.15

        adjusted = base_projection * boost_factor

        reason = f"teammate_opportunity:score={impact.opportunity_score:.0f}"

        return adjusted, impact.impact_confidence * 0.8, reason

    # =========================================================================
    # CACHE MANAGEMENT
    # =========================================================================

    def clear_cache(self, game_date: Optional[date] = None):
        """Clear cached injury data"""
        if game_date:
            self._injury_cache.pop(game_date, None)
        else:
            self._injury_cache.clear()
            self._player_usage_cache.clear()
            self._player_starter_cache.clear()
            self._team_roster_cache.clear()

    def get_stats(self) -> Dict:
        """Get statistics about cached data"""
        return {
            "cached_dates": len(self._injury_cache),
            "cached_players_usage": len(self._player_usage_cache),
            "cached_players_starter": len(self._player_starter_cache),
            "total_injuries_cached": sum(
                len(injuries) for injuries in self._injury_cache.values()
            )
        }


# =============================================================================
# SINGLETON AND CONVENIENCE FUNCTIONS
# =============================================================================

_default_integration: Optional[InjuryIntegration] = None


def get_injury_integration() -> InjuryIntegration:
    """Get the default injury integration instance"""
    global _default_integration
    if _default_integration is None:
        _default_integration = InjuryIntegration()
    return _default_integration


def check_player_injury(player_lookup: str, game_date: date) -> PlayerInjuryInfo:
    """Convenience function to check player injury status"""
    return get_injury_integration().check_player(player_lookup, game_date)


def get_teammate_impact(
    player_lookup: str,
    team_abbr: str,
    game_date: date
) -> TeammateImpact:
    """Convenience function to get teammate impact"""
    return get_injury_integration().calculate_teammate_impact(
        player_lookup, team_abbr, game_date
    )


def filter_out_injured(
    player_lookups: List[str],
    game_date: date,
    skip_doubtful: bool = False
) -> InjuryFilterResult:
    """Convenience function to filter injured players"""
    return get_injury_integration().filter_injured_players(
        player_lookups, game_date, skip_doubtful
    )
