# predictions/shared/injury_filter.py

"""
Injury Report Filter for Inference-Time Prediction Filtering

Checks player injury status before generating predictions to:
1. Skip predictions for players listed as OUT (prevents DNP errors)
2. Flag predictions for QUESTIONABLE/DOUBTFUL players (high uncertainty)
3. Pass through all other players normally
4. Calculate teammate injury impact for usage adjustments (v2.0)
5. Check historical DNP patterns from gamebook data (v2.1)

Data Sources (v2.1):
- nba_raw.nbac_injury_report: NBA.com official injury reports (primary)
- nba_analytics.player_game_summary: Historical DNP data from gamebooks (v2.1)
- nba_raw.bdl_injuries: Ball Don't Lie backup source (validation)

Based on analysis of 2024-25 season:
- 28.6% of DNPs (1,833) were catchable by checking OUT status
- 8.8% of DNPs (567) were QUESTIONABLE (flag but don't skip)
- 58.6% of DNPs had no injury report entry (late scratches, can't catch)

V2.1 Enhancement: Historical DNP Pattern Detection
- Queries player_game_summary for recent DNP history
- Flags players with 2+ DNPs in last 5 games as "dnp_risk"
- Captures late scratches, coach decisions not in injury report
- Analysis shows 35%+ of DNPs can be caught via gamebook history

Usage:
    from predictions.shared.injury_filter import InjuryFilter

    filter = InjuryFilter()
    status = filter.check_player(player_lookup, game_date)

    if status.should_skip:
        # Don't generate prediction
    elif status.has_warning:
        # Generate prediction but flag uncertainty

    # v2.1: Check DNP history for additional risk signal
    dnp_history = filter.check_dnp_history(player_lookup, game_date)
    if dnp_history.has_dnp_risk:
        # Player has recent DNP pattern - flag for uncertainty

    # v2.0: Get teammate impact for usage adjustments
    impact = filter.get_teammate_impact(player_lookup, team_abbr, game_date)
    if impact.has_significant_impact:
        adjusted_usage = base_usage * impact.usage_boost_factor
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Dict, List, Tuple
from google.cloud import bigquery
import logging

from shared.config.gcp_config import get_project_id

logger = logging.getLogger(__name__)


@dataclass
class InjuryStatus:
    """Result of injury check for a player"""
    player_lookup: str
    game_date: date
    injury_status: Optional[str]  # 'out', 'doubtful', 'questionable', 'probable', 'available', None
    reason: Optional[str]
    should_skip: bool  # True if prediction should be skipped
    has_warning: bool  # True if prediction should be flagged
    message: str  # Human-readable status message


@dataclass
class DNPHistory:
    """
    Historical DNP pattern for a player (v2.1)

    Provides supplemental signal from gamebook data that captures:
    - Late scratches not in pre-game injury report
    - Coach decisions that become patterns
    - Recurring injuries that weren't reported pre-game
    """
    player_lookup: str
    game_date: date
    games_checked: int  # Number of recent games analyzed
    dnp_count: int  # DNPs in the window
    dnp_rate: float  # DNP rate (0.0-1.0)
    recent_dnp_reasons: List[str]  # Last few DNP reasons
    last_dnp_date: Optional[date]  # Most recent DNP
    has_dnp_risk: bool  # True if pattern suggests DNP risk
    risk_category: Optional[str]  # 'injury', 'coach_decision', 'recurring', None
    message: str  # Human-readable summary

    @property
    def days_since_last_dnp(self) -> Optional[int]:
        """Days since last DNP, or None if no recent DNPs"""
        if self.last_dnp_date:
            return (self.game_date - self.last_dnp_date).days
        return None


class InjuryFilter:
    """
    Filter predictions based on injury report status

    Queries the injury report table to check player status before predictions.
    """

    # Status levels that should skip prediction entirely
    SKIP_STATUSES = {'out'}

    # Status levels that should flag uncertainty (but still predict)
    WARNING_STATUSES = {'doubtful', 'questionable'}

    def __init__(self, project_id: str = None):
        """
        Initialize injury filter

        Args:
            project_id: GCP project ID for BigQuery (defaults to shared.config)
        """
        self.project_id = project_id or get_project_id()
        self._client = None
        self._cache: Dict[str, InjuryStatus] = {}  # Cache for batch operations

    @property
    def client(self) -> bigquery.Client:
        """Lazy-load BigQuery client via pool"""
        if self._client is None:
            from shared.clients import get_bigquery_client
            self._client = get_bigquery_client(self.project_id)
        return self._client

    def check_player(
        self,
        player_lookup: str,
        game_date: date
    ) -> InjuryStatus:
        """
        Check injury status for a single player

        Args:
            player_lookup: Player identifier (e.g., 'lebron-james')
            game_date: Date of the game

        Returns:
            InjuryStatus with skip/warning flags
        """
        cache_key = f"{player_lookup}_{game_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        query = """
        SELECT
            player_lookup,
            game_date,
            injury_status,
            reason
        FROM `nba-props-platform.nba_raw.nbac_injury_report`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY report_hour DESC
        ) = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result()
            rows = list(result)

            if not rows:
                status = InjuryStatus(
                    player_lookup=player_lookup,
                    game_date=game_date,
                    injury_status=None,
                    reason=None,
                    should_skip=False,
                    has_warning=False,
                    message="OK: No injury report entry"
                )
            else:
                row = rows[0]
                injury_status = row.injury_status.lower() if row.injury_status else None

                should_skip = injury_status in self.SKIP_STATUSES
                has_warning = injury_status in self.WARNING_STATUSES

                if should_skip:
                    message = f"SKIP: Player listed as {injury_status.upper()}"
                elif has_warning:
                    message = f"WARNING: Player listed as {injury_status.upper()}"
                else:
                    message = f"OK: Player status is {injury_status or 'unknown'}"

                status = InjuryStatus(
                    player_lookup=player_lookup,
                    game_date=game_date,
                    injury_status=injury_status,
                    reason=row.reason,
                    should_skip=should_skip,
                    has_warning=has_warning,
                    message=message
                )

            self._cache[cache_key] = status
            return status

        except Exception as e:
            logger.error(f"Error checking injury status for {player_lookup}: {e}", exc_info=True)
            # Fail-open: if we can't check, allow prediction
            return InjuryStatus(
                player_lookup=player_lookup,
                game_date=game_date,
                injury_status=None,
                reason=None,
                should_skip=False,
                has_warning=False,
                message=f"OK: Error checking injury status (fail-open): {e}"
            )

    def check_players_batch(
        self,
        player_lookups: List[str],
        game_date: date
    ) -> Dict[str, InjuryStatus]:
        """
        Check injury status for multiple players efficiently

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game

        Returns:
            Dict mapping player_lookup to InjuryStatus
        """
        # Filter out already cached players
        uncached = [p for p in player_lookups if f"{p}_{game_date}" not in self._cache]

        if uncached:
            query = """
            SELECT
                player_lookup,
                game_date,
                injury_status,
                reason
            FROM `nba-props-platform.nba_raw.nbac_injury_report`
            WHERE game_date = @game_date
              AND player_lookup IN UNNEST(@player_lookups)
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY report_hour DESC
            ) = 1
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                    bigquery.ArrayQueryParameter("player_lookups", "STRING", uncached),
                ]
            )

            try:
                result = self.client.query(query, job_config=job_config).result()

                # Process results
                found_players = set()
                for row in result:
                    player = row.player_lookup
                    found_players.add(player)
                    injury_status = row.injury_status.lower() if row.injury_status else None

                    should_skip = injury_status in self.SKIP_STATUSES
                    has_warning = injury_status in self.WARNING_STATUSES

                    if should_skip:
                        message = f"SKIP: Player listed as {injury_status.upper()}"
                    elif has_warning:
                        message = f"WARNING: Player listed as {injury_status.upper()}"
                    else:
                        message = f"OK: Player status is {injury_status or 'unknown'}"

                    self._cache[f"{player}_{game_date}"] = InjuryStatus(
                        player_lookup=player,
                        game_date=game_date,
                        injury_status=injury_status,
                        reason=row.reason,
                        should_skip=should_skip,
                        has_warning=has_warning,
                        message=message
                    )

                # Players not in injury report
                for player in uncached:
                    if player not in found_players:
                        self._cache[f"{player}_{game_date}"] = InjuryStatus(
                            player_lookup=player,
                            game_date=game_date,
                            injury_status=None,
                            reason=None,
                            should_skip=False,
                            has_warning=False,
                            message="OK: No injury report entry"
                        )

            except Exception as e:
                logger.error(f"Error batch checking injury status: {e}", exc_info=True)
                # Fail-open for all uncached players
                for player in uncached:
                    self._cache[f"{player}_{game_date}"] = InjuryStatus(
                        player_lookup=player,
                        game_date=game_date,
                        injury_status=None,
                        reason=None,
                        should_skip=False,
                        has_warning=False,
                        message=f"OK: Error checking (fail-open): {e}"
                    )

        # Return all requested players
        return {p: self._cache[f"{p}_{game_date}"] for p in player_lookups}

    def clear_cache(self):
        """Clear the internal cache"""
        self._cache.clear()

    def get_stats(self) -> Dict:
        """Get statistics about cached injury checks"""
        if not self._cache:
            return {"cached_checks": 0}

        statuses = list(self._cache.values())
        return {
            "cached_checks": len(statuses),
            "skip_count": sum(1 for s in statuses if s.should_skip),
            "warning_count": sum(1 for s in statuses if s.has_warning),
            "ok_count": sum(1 for s in statuses if not s.should_skip and not s.has_warning),
        }

    # =========================================================================
    # V2.1: HISTORICAL DNP PATTERN CHECKING
    # =========================================================================

    # Configuration for DNP risk detection
    DNP_HISTORY_WINDOW = 5  # Number of recent games to check
    DNP_RISK_THRESHOLD = 2  # DNPs in window that trigger risk flag

    def check_dnp_history(
        self,
        player_lookup: str,
        game_date: date,
        window_games: int = None
    ) -> DNPHistory:
        """
        Check player's recent DNP history from gamebook data (v2.1)

        Queries player_game_summary for DNP patterns that may not be
        in the pre-game injury report (coach decisions, late scratches, etc.)

        Args:
            player_lookup: Player identifier
            game_date: Date of the upcoming game
            window_games: Number of recent games to check (default: DNP_HISTORY_WINDOW)

        Returns:
            DNPHistory with risk assessment
        """
        window = window_games or self.DNP_HISTORY_WINDOW

        query = """
        SELECT
            player_lookup,
            game_date,
            is_dnp,
            dnp_reason,
            dnp_reason_category
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date < @game_date
          AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
        ORDER BY game_date DESC
        LIMIT @window_games
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("window_games", "INT64", window),
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result()
            rows = list(result)

            if not rows:
                return DNPHistory(
                    player_lookup=player_lookup,
                    game_date=game_date,
                    games_checked=0,
                    dnp_count=0,
                    dnp_rate=0.0,
                    recent_dnp_reasons=[],
                    last_dnp_date=None,
                    has_dnp_risk=False,
                    risk_category=None,
                    message="OK: No recent game history found"
                )

            games_checked = len(rows)
            dnp_games = [r for r in rows if r.is_dnp]
            dnp_count = len(dnp_games)
            dnp_rate = dnp_count / games_checked if games_checked > 0 else 0.0

            # Get DNP reasons and dates
            recent_reasons = [r.dnp_reason for r in dnp_games if r.dnp_reason][:3]
            last_dnp_date = dnp_games[0].game_date if dnp_games else None

            # Determine risk category based on DNP reason categories
            risk_category = None
            if dnp_games:
                categories = [r.dnp_reason_category for r in dnp_games if r.dnp_reason_category]
                if categories:
                    # Find most common category
                    category_counts = {}
                    for cat in categories:
                        category_counts[cat] = category_counts.get(cat, 0) + 1
                    risk_category = max(category_counts.keys(), key=lambda k: category_counts[k])

            # Determine if has DNP risk
            has_dnp_risk = dnp_count >= self.DNP_RISK_THRESHOLD

            # Build message
            if has_dnp_risk:
                message = f"DNP_RISK: {dnp_count}/{games_checked} recent games DNP"
                if risk_category:
                    message += f" ({risk_category})"
            elif dnp_count > 0:
                message = f"LOW_RISK: {dnp_count}/{games_checked} recent games DNP"
            else:
                message = f"OK: No DNPs in last {games_checked} games"

            return DNPHistory(
                player_lookup=player_lookup,
                game_date=game_date,
                games_checked=games_checked,
                dnp_count=dnp_count,
                dnp_rate=dnp_rate,
                recent_dnp_reasons=recent_reasons,
                last_dnp_date=last_dnp_date,
                has_dnp_risk=has_dnp_risk,
                risk_category=risk_category,
                message=message
            )

        except Exception as e:
            logger.error(f"Error checking DNP history for {player_lookup}: {e}", exc_info=True)
            return DNPHistory(
                player_lookup=player_lookup,
                game_date=game_date,
                games_checked=0,
                dnp_count=0,
                dnp_rate=0.0,
                recent_dnp_reasons=[],
                last_dnp_date=None,
                has_dnp_risk=False,
                risk_category=None,
                message=f"OK: Error checking DNP history (fail-open): {e}"
            )

    def check_dnp_history_batch(
        self,
        player_lookups: List[str],
        game_date: date,
        window_games: int = None
    ) -> Dict[str, DNPHistory]:
        """
        Check DNP history for multiple players efficiently (v2.1)

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the upcoming game
            window_games: Number of recent games to check

        Returns:
            Dict mapping player_lookup to DNPHistory
        """
        window = window_games or self.DNP_HISTORY_WINDOW

        if not player_lookups:
            return {}

        query = """
        WITH ranked_games AS (
            SELECT
                player_lookup,
                game_date,
                is_dnp,
                dnp_reason,
                dnp_reason_category,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date < @game_date
              AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
        )
        SELECT
            player_lookup,
            game_date,
            is_dnp,
            dnp_reason,
            dnp_reason_category
        FROM ranked_games
        WHERE game_rank <= @window_games
        ORDER BY player_lookup, game_date DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("window_games", "INT64", window),
            ]
        )

        try:
            result = self.client.query(query, job_config=job_config).result()

            # Group rows by player
            player_rows: Dict[str, List] = {p: [] for p in player_lookups}
            for row in result:
                if row.player_lookup in player_rows:
                    player_rows[row.player_lookup].append(row)

            # Build DNPHistory for each player
            histories = {}
            for player in player_lookups:
                rows = player_rows.get(player, [])

                if not rows:
                    histories[player] = DNPHistory(
                        player_lookup=player,
                        game_date=game_date,
                        games_checked=0,
                        dnp_count=0,
                        dnp_rate=0.0,
                        recent_dnp_reasons=[],
                        last_dnp_date=None,
                        has_dnp_risk=False,
                        risk_category=None,
                        message="OK: No recent game history found"
                    )
                    continue

                games_checked = len(rows)
                dnp_games = [r for r in rows if r.is_dnp]
                dnp_count = len(dnp_games)
                dnp_rate = dnp_count / games_checked if games_checked > 0 else 0.0

                recent_reasons = [r.dnp_reason for r in dnp_games if r.dnp_reason][:3]
                last_dnp_date = dnp_games[0].game_date if dnp_games else None

                risk_category = None
                if dnp_games:
                    categories = [r.dnp_reason_category for r in dnp_games if r.dnp_reason_category]
                    if categories:
                        category_counts = {}
                        for cat in categories:
                            category_counts[cat] = category_counts.get(cat, 0) + 1
                        risk_category = max(category_counts.keys(), key=lambda k: category_counts[k])

                has_dnp_risk = dnp_count >= self.DNP_RISK_THRESHOLD

                if has_dnp_risk:
                    message = f"DNP_RISK: {dnp_count}/{games_checked} recent games DNP"
                    if risk_category:
                        message += f" ({risk_category})"
                elif dnp_count > 0:
                    message = f"LOW_RISK: {dnp_count}/{games_checked} recent games DNP"
                else:
                    message = f"OK: No DNPs in last {games_checked} games"

                histories[player] = DNPHistory(
                    player_lookup=player,
                    game_date=game_date,
                    games_checked=games_checked,
                    dnp_count=dnp_count,
                    dnp_rate=dnp_rate,
                    recent_dnp_reasons=recent_reasons,
                    last_dnp_date=last_dnp_date,
                    has_dnp_risk=has_dnp_risk,
                    risk_category=risk_category,
                    message=message
                )

            return histories

        except Exception as e:
            logger.error(f"Error batch checking DNP history: {e}", exc_info=True)
            # Fail-open for all players
            return {
                p: DNPHistory(
                    player_lookup=p,
                    game_date=game_date,
                    games_checked=0,
                    dnp_count=0,
                    dnp_rate=0.0,
                    recent_dnp_reasons=[],
                    last_dnp_date=None,
                    has_dnp_risk=False,
                    risk_category=None,
                    message=f"OK: Error checking (fail-open): {e}"
                )
                for p in player_lookups
            }

    def get_combined_risk(
        self,
        player_lookup: str,
        game_date: date
    ) -> Tuple[InjuryStatus, DNPHistory]:
        """
        Get both injury status and DNP history for comprehensive risk assessment (v2.1)

        Args:
            player_lookup: Player identifier
            game_date: Date of the game

        Returns:
            Tuple of (InjuryStatus, DNPHistory)
        """
        injury_status = self.check_player(player_lookup, game_date)
        dnp_history = self.check_dnp_history(player_lookup, game_date)
        return injury_status, dnp_history

    def get_combined_risk_batch(
        self,
        player_lookups: List[str],
        game_date: date
    ) -> Dict[str, Tuple[InjuryStatus, DNPHistory]]:
        """
        Get both injury status and DNP history for multiple players (v2.1)

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game

        Returns:
            Dict mapping player_lookup to (InjuryStatus, DNPHistory) tuple
        """
        injury_statuses = self.check_players_batch(player_lookups, game_date)
        dnp_histories = self.check_dnp_history_batch(player_lookups, game_date)

        return {
            p: (injury_statuses[p], dnp_histories[p])
            for p in player_lookups
        }

    # =========================================================================
    # V2.0: TEAMMATE IMPACT AND USAGE ADJUSTMENTS
    # =========================================================================

    def get_teammate_impact(
        self,
        player_lookup: str,
        team_abbr: str,
        game_date: date
    ) -> 'TeammateImpact':
        """
        Calculate impact of injured teammates on player's projections (v2.0)

        When key teammates are injured, remaining players typically see:
        - Increased usage rate
        - More minutes
        - Different shot distribution

        Args:
            player_lookup: Player to calculate impact for
            team_abbr: Player's team abbreviation
            game_date: Date of the game

        Returns:
            TeammateImpact with boost factors and injured teammate lists
        """
        try:
            from predictions.shared.injury_integration import get_injury_integration
            return get_injury_integration().calculate_teammate_impact(
                player_lookup, team_abbr, game_date
            )
        except ImportError:
            logger.warning("injury_integration module not available, returning default impact")
            return TeammateImpact(
                player_lookup=player_lookup,
                team_abbr=team_abbr,
                game_date=game_date
            )

    def adjust_usage_for_injuries(
        self,
        player_lookup: str,
        base_usage: float,
        team_abbr: str,
        game_date: date
    ) -> Tuple[float, float, str]:
        """
        Adjust usage projection based on injured teammates (v2.0)

        Args:
            player_lookup: Player to adjust projection for
            base_usage: Original usage projection (0.0-1.0)
            team_abbr: Player's team
            game_date: Date of the game

        Returns:
            Tuple of (adjusted_usage, confidence, reason)
        """
        try:
            from predictions.shared.injury_integration import get_injury_integration
            return get_injury_integration().adjust_usage_projection(
                player_lookup, base_usage, team_abbr, game_date
            )
        except ImportError:
            logger.warning("injury_integration module not available, returning base usage")
            return base_usage, 0.9, "no_injury_integration"

    def adjust_points_for_injuries(
        self,
        player_lookup: str,
        base_projection: float,
        team_abbr: str,
        game_date: date
    ) -> Tuple[float, float, str]:
        """
        Adjust points projection based on injured teammates (v2.0)

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
        try:
            from predictions.shared.injury_integration import get_injury_integration
            return get_injury_integration().adjust_points_projection(
                player_lookup, base_projection, team_abbr, game_date
            )
        except ImportError:
            logger.warning("injury_integration module not available, returning base projection")
            return base_projection, 0.9, "no_injury_integration"

    def get_team_injury_summary(
        self,
        team_abbr: str,
        game_date: date
    ) -> Dict:
        """
        Get summary of all injuries for a team (v2.0)

        Args:
            team_abbr: Team abbreviation
            game_date: Date of the game

        Returns:
            Dict with injury counts and lists by status
        """
        try:
            from predictions.shared.injury_integration import get_injury_integration
            integration = get_injury_integration()
            injuries = integration.load_injuries_for_date(game_date)

            team_injuries = {
                p: info for p, info in injuries.items()
                if info.team_abbr == team_abbr
            }

            return {
                'team': team_abbr,
                'game_date': game_date.isoformat(),
                'total_injured': len(team_injuries),
                'out': [p for p, i in team_injuries.items() if i.status == 'out'],
                'doubtful': [p for p, i in team_injuries.items() if i.status == 'doubtful'],
                'questionable': [p for p, i in team_injuries.items() if i.status == 'questionable'],
                'probable': [p for p, i in team_injuries.items() if i.status == 'probable'],
            }
        except ImportError:
            logger.warning("injury_integration module not available")
            return {
                'team': team_abbr,
                'game_date': game_date.isoformat(),
                'total_injured': 0,
                'out': [],
                'doubtful': [],
                'questionable': [],
                'probable': [],
            }


# =============================================================================
# V2.0: TEAMMATE IMPACT DATA CLASS
# =============================================================================

@dataclass
class TeammateImpact:
    """
    Impact of injured teammates on a player's projections

    This is the fallback version used when injury_integration is not available.
    The full version with calculation logic is in injury_integration.py
    """
    player_lookup: str
    team_abbr: str
    game_date: date
    out_teammates: List[str] = field(default_factory=list)
    doubtful_teammates: List[str] = field(default_factory=list)
    questionable_teammates: List[str] = field(default_factory=list)
    out_starters: List[str] = field(default_factory=list)
    out_star_players: List[str] = field(default_factory=list)
    usage_boost_factor: float = 1.0
    minutes_boost_factor: float = 1.0
    opportunity_score: float = 0.0
    impact_confidence: float = 0.8

    @property
    def has_significant_impact(self) -> bool:
        """Whether teammate injuries should significantly affect projections"""
        return len(self.out_starters) > 0 or len(self.out_star_players) > 0

    @property
    def total_injured(self) -> int:
        return len(self.out_teammates) + len(self.doubtful_teammates) + len(self.questionable_teammates)


# Singleton instance for convenience
_default_filter: Optional[InjuryFilter] = None


def get_injury_filter() -> InjuryFilter:
    """Get the default injury filter instance"""
    global _default_filter
    if _default_filter is None:
        _default_filter = InjuryFilter()
    return _default_filter


def check_injury_status(player_lookup: str, game_date: date) -> InjuryStatus:
    """
    Convenience function to check injury status

    Args:
        player_lookup: Player identifier
        game_date: Date of the game

    Returns:
        InjuryStatus with skip/warning flags
    """
    return get_injury_filter().check_player(player_lookup, game_date)


def check_dnp_history(player_lookup: str, game_date: date) -> DNPHistory:
    """
    Convenience function to check DNP history (v2.1)

    Args:
        player_lookup: Player identifier
        game_date: Date of the upcoming game

    Returns:
        DNPHistory with risk assessment
    """
    return get_injury_filter().check_dnp_history(player_lookup, game_date)


def get_combined_player_risk(
    player_lookup: str,
    game_date: date
) -> Tuple[InjuryStatus, DNPHistory]:
    """
    Convenience function to get combined risk assessment (v2.1)

    Args:
        player_lookup: Player identifier
        game_date: Date of the game

    Returns:
        Tuple of (InjuryStatus, DNPHistory)
    """
    return get_injury_filter().get_combined_risk(player_lookup, game_date)
