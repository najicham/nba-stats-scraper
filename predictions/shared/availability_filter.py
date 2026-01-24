# predictions/shared/availability_filter.py

"""
Player Availability Filter for Inference-Time Prediction Filtering

Enhanced version that combines:
1. Injury report status (from InjuryFilter)
2. Roster status (from RosterManager)
3. Recent roster changes (trades, waivers, G-League assignments)

This provides a more comprehensive check than injury-only filtering.

Usage:
    from predictions.shared.availability_filter import AvailabilityFilter

    filter = AvailabilityFilter()
    status = filter.check_player(player_lookup, game_date, team_abbr)

    if status.should_skip:
        # Don't generate prediction
    elif status.has_warning:
        # Generate prediction but flag uncertainty
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, List, Tuple
from google.cloud import bigquery
import logging

# Import injury filter for backward compatibility
from predictions.shared.injury_filter import (
    InjuryFilter,
    InjuryStatus,
    get_injury_filter,
    check_injury_status
)

logger = logging.getLogger(__name__)


@dataclass
class AvailabilityStatus:
    """Result of availability check for a player."""
    player_lookup: str
    game_date: date
    team_abbr: Optional[str]

    # Status flags
    is_on_roster: bool
    injury_status: Optional[str]  # 'out', 'doubtful', 'questionable', etc.
    roster_status: Optional[str]  # 'active', 'g_league', 'two_way', etc.

    # Decision flags
    should_skip: bool
    has_warning: bool

    # Details
    injury_reason: Optional[str]
    recent_transaction: Optional[str]  # Description of recent roster change
    message: str

    # Confidence in status (0.0-1.0)
    confidence: float = 1.0


class AvailabilityFilter:
    """
    Enhanced filter combining injury and roster status for predictions.

    More comprehensive than InjuryFilter alone:
    - Checks roster membership (player might not be on team anymore)
    - Checks G-League assignments (player on roster but not with NBA team)
    - Checks recent transactions (trades, waivers)
    - Combines with injury status
    """

    # Injury statuses that skip prediction
    SKIP_INJURY_STATUSES = {'out'}

    # Injury statuses that warn but allow prediction
    WARNING_INJURY_STATUSES = {'doubtful', 'questionable'}

    # Roster statuses that skip prediction
    SKIP_ROSTER_STATUSES = {'g_league', 'suspended', 'inactive'}

    def __init__(self, project_id: str = "nba-props-platform"):
        """Initialize availability filter."""
        self.project_id = project_id
        self._client = None
        self._injury_filter = InjuryFilter(project_id)
        self._cache: Dict[str, AvailabilityStatus] = {}

    @property
    def client(self) -> bigquery.Client:
        """Lazy-load BigQuery client."""
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def check_player(
        self,
        player_lookup: str,
        game_date: date,
        team_abbr: Optional[str] = None
    ) -> AvailabilityStatus:
        """
        Check full availability for a player.

        Args:
            player_lookup: Player identifier
            game_date: Date of the game
            team_abbr: Optional team (for roster check)

        Returns:
            AvailabilityStatus with complete status info
        """
        cache_key = f"{player_lookup}_{game_date}_{team_abbr or 'any'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Get injury status
        injury_status = self._injury_filter.check_player(player_lookup, game_date)

        # Get roster status
        roster_info = self._check_roster_status(
            player_lookup, game_date, team_abbr
        )

        # Get recent transactions
        recent_tx = self._get_recent_transaction(player_lookup, game_date)

        # Determine overall status
        should_skip, has_warning, message, confidence = self._determine_status(
            injury_status,
            roster_info,
            recent_tx
        )

        status = AvailabilityStatus(
            player_lookup=player_lookup,
            game_date=game_date,
            team_abbr=roster_info.get('team_abbr') or team_abbr,
            is_on_roster=roster_info.get('is_on_roster', False),
            injury_status=injury_status.injury_status,
            roster_status=roster_info.get('roster_status'),
            should_skip=should_skip,
            has_warning=has_warning,
            injury_reason=injury_status.reason,
            recent_transaction=recent_tx,
            message=message,
            confidence=confidence
        )

        self._cache[cache_key] = status
        return status

    def check_players_batch(
        self,
        player_lookups: List[str],
        game_date: date,
        team_abbr: Optional[str] = None
    ) -> Dict[str, AvailabilityStatus]:
        """
        Check availability for multiple players efficiently.

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game
            team_abbr: Optional team filter

        Returns:
            Dict mapping player_lookup to AvailabilityStatus
        """
        # Get batch injury status
        injury_statuses = self._injury_filter.check_players_batch(
            player_lookups, game_date
        )

        # Get batch roster status
        roster_infos = self._check_roster_status_batch(
            player_lookups, game_date, team_abbr
        )

        # Get batch transactions
        recent_txs = self._get_recent_transactions_batch(
            player_lookups, game_date
        )

        # Build results
        results = {}
        for player in player_lookups:
            injury_status = injury_statuses.get(player)
            roster_info = roster_infos.get(player, {})
            recent_tx = recent_txs.get(player)

            should_skip, has_warning, message, confidence = self._determine_status(
                injury_status,
                roster_info,
                recent_tx
            )

            results[player] = AvailabilityStatus(
                player_lookup=player,
                game_date=game_date,
                team_abbr=roster_info.get('team_abbr') or team_abbr,
                is_on_roster=roster_info.get('is_on_roster', False),
                injury_status=injury_status.injury_status if injury_status else None,
                roster_status=roster_info.get('roster_status'),
                should_skip=should_skip,
                has_warning=has_warning,
                injury_reason=injury_status.reason if injury_status else None,
                recent_transaction=recent_tx,
                message=message,
                confidence=confidence
            )

        return results

    def _check_roster_status(
        self,
        player_lookup: str,
        game_date: date,
        team_abbr: Optional[str]
    ) -> Dict:
        """Check if player is on roster and their status."""
        query = """
        WITH latest_roster AS (
            SELECT
                player_lookup,
                team_abbr,
                status,
                roster_status,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY roster_date DESC, scrape_hour DESC
                ) as rn
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE player_lookup = @player_lookup
              AND roster_date <= @game_date
              AND roster_date >= DATE_SUB(@game_date, INTERVAL 7 DAY)
        )
        SELECT
            player_lookup,
            team_abbr,
            status,
            roster_status
        FROM latest_roster
        WHERE rn = 1
        """.format(project=self.project_id)

        params = [
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]

        if team_abbr:
            query = query.replace(
                "WHERE player_lookup = @player_lookup",
                "WHERE player_lookup = @player_lookup AND team_abbr = @team_abbr"
            )
            params.append(bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr))

        job_config = bigquery.QueryJobConfig(query_parameters=params)

        try:
            result = self.client.query(query, job_config=job_config).result()
            rows = list(result)

            if not rows:
                return {
                    'is_on_roster': False,
                    'team_abbr': team_abbr,
                    'roster_status': None
                }

            row = rows[0]
            roster_status = self._normalize_roster_status(
                row.status, row.roster_status
            )

            return {
                'is_on_roster': True,
                'team_abbr': row.team_abbr,
                'roster_status': roster_status
            }

        except Exception as e:
            logger.error(f"Error checking roster status for {player_lookup}: {e}")
            return {
                'is_on_roster': True,  # Fail-open
                'team_abbr': team_abbr,
                'roster_status': None
            }

    def _check_roster_status_batch(
        self,
        player_lookups: List[str],
        game_date: date,
        team_abbr: Optional[str]
    ) -> Dict[str, Dict]:
        """Check roster status for multiple players."""
        query = """
        WITH latest_roster AS (
            SELECT
                player_lookup,
                team_abbr,
                status,
                roster_status,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY roster_date DESC, scrape_hour DESC
                ) as rn
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND roster_date <= @game_date
              AND roster_date >= DATE_SUB(@game_date, INTERVAL 7 DAY)
        )
        SELECT
            player_lookup,
            team_abbr,
            status,
            roster_status
        FROM latest_roster
        WHERE rn = 1
        """.format(project=self.project_id)

        params = [
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]

        if team_abbr:
            query = query.replace(
                "WHERE player_lookup IN UNNEST(@player_lookups)",
                "WHERE player_lookup IN UNNEST(@player_lookups) AND team_abbr = @team_abbr"
            )
            params.append(bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr))

        job_config = bigquery.QueryJobConfig(query_parameters=params)

        try:
            result = self.client.query(query, job_config=job_config).result()

            roster_infos = {}
            found_players = set()

            for row in result:
                found_players.add(row.player_lookup)
                roster_status = self._normalize_roster_status(
                    row.status, row.roster_status
                )
                roster_infos[row.player_lookup] = {
                    'is_on_roster': True,
                    'team_abbr': row.team_abbr,
                    'roster_status': roster_status
                }

            # Players not found on roster
            for player in player_lookups:
                if player not in found_players:
                    roster_infos[player] = {
                        'is_on_roster': False,
                        'team_abbr': team_abbr,
                        'roster_status': None
                    }

            return roster_infos

        except Exception as e:
            logger.error(f"Error batch checking roster status: {e}")
            # Fail-open for all players
            return {
                p: {'is_on_roster': True, 'team_abbr': team_abbr, 'roster_status': None}
                for p in player_lookups
            }

    def _get_recent_transaction(
        self,
        player_lookup: str,
        game_date: date
    ) -> Optional[str]:
        """Get most recent transaction for player within last 7 days."""
        query = """
        SELECT transaction_description
        FROM `{project}.nba_raw.nbac_player_movement`
        WHERE player_lookup = @player_lookup
          AND transaction_date BETWEEN DATE_SUB(@game_date, INTERVAL 7 DAY) AND @game_date
          AND is_player_transaction = TRUE
        ORDER BY transaction_date DESC
        LIMIT 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ])

        try:
            result = self.client.query(query, job_config=job_config).result()
            rows = list(result)
            return rows[0].transaction_description if rows else None
        except Exception as e:
            logger.debug(f"Error getting recent transaction: {e}")
            return None

    def _get_recent_transactions_batch(
        self,
        player_lookups: List[str],
        game_date: date
    ) -> Dict[str, Optional[str]]:
        """Get recent transactions for multiple players."""
        query = """
        WITH ranked AS (
            SELECT
                player_lookup,
                transaction_description,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY transaction_date DESC
                ) as rn
            FROM `{project}.nba_raw.nbac_player_movement`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND transaction_date BETWEEN DATE_SUB(@game_date, INTERVAL 7 DAY) AND @game_date
              AND is_player_transaction = TRUE
        )
        SELECT player_lookup, transaction_description
        FROM ranked
        WHERE rn = 1
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ])

        try:
            result = self.client.query(query, job_config=job_config).result()
            return {row.player_lookup: row.transaction_description for row in result}
        except Exception as e:
            logger.debug(f"Error batch getting transactions: {e}")
            return {}

    def _normalize_roster_status(
        self,
        status: Optional[str],
        roster_status: Optional[str]
    ) -> Optional[str]:
        """Normalize roster status to standard categories."""
        status_lower = (status or '').lower()
        roster_lower = (roster_status or '').lower()

        # Check for G-League
        if 'g league' in status_lower or 'g-league' in roster_lower:
            return 'g_league'

        # Check for suspension
        if 'suspend' in status_lower or 'suspend' in roster_lower:
            return 'suspended'

        # Check for two-way
        if 'two-way' in status_lower or 'two way' in roster_lower:
            return 'two_way'

        # Check for inactive
        if 'inactive' in status_lower:
            return 'inactive'

        return 'active'

    def _determine_status(
        self,
        injury_status: Optional[InjuryStatus],
        roster_info: Dict,
        recent_tx: Optional[str]
    ) -> Tuple[bool, bool, str, float]:
        """
        Determine overall skip/warning status.

        Returns:
            (should_skip, has_warning, message, confidence)
        """
        # Check roster first
        if not roster_info.get('is_on_roster', True):
            return (
                True,
                False,
                f"SKIP: Player not found on roster",
                0.9
            )

        roster_status = roster_info.get('roster_status')
        if roster_status in self.SKIP_ROSTER_STATUSES:
            return (
                True,
                False,
                f"SKIP: Player status is {roster_status.upper()}",
                0.95
            )

        # Check injury status
        if injury_status:
            inj_lower = (injury_status.injury_status or '').lower()

            if inj_lower in self.SKIP_INJURY_STATUSES:
                return (
                    True,
                    False,
                    f"SKIP: Player listed as {inj_lower.upper()}"
                    + (f" - {injury_status.reason}" if injury_status.reason else ""),
                    1.0
                )

            if inj_lower in self.WARNING_INJURY_STATUSES:
                return (
                    False,
                    True,
                    f"WARNING: Player listed as {inj_lower.upper()}"
                    + (f" - {injury_status.reason}" if injury_status.reason else ""),
                    0.7
                )

        # Check recent transactions for context
        if recent_tx:
            tx_lower = recent_tx.lower()
            if 'waive' in tx_lower or 'release' in tx_lower:
                return (
                    True,
                    False,
                    f"SKIP: Recent transaction - {recent_tx[:50]}",
                    0.85
                )

            # Trade or signing doesn't skip but adds context
            if 'trade' in tx_lower or 'sign' in tx_lower:
                return (
                    False,
                    True,
                    f"WARNING: Recent transaction - {recent_tx[:50]}",
                    0.85
                )

        # All clear
        return (
            False,
            False,
            "OK: Available",
            1.0
        )

    def should_skip_prediction(
        self,
        player_lookup: str,
        game_date: date,
        team_abbr: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Convenience method: Should we skip generating a prediction?

        Returns:
            Tuple of (should_skip, reason)
        """
        status = self.check_player(player_lookup, game_date, team_abbr)
        return status.should_skip, status.message

    def clear_cache(self):
        """Clear the internal cache."""
        self._cache.clear()
        self._injury_filter.clear_cache()

    def get_stats(self) -> Dict:
        """Get statistics about cached availability checks."""
        if not self._cache:
            return {"cached_checks": 0}

        statuses = list(self._cache.values())
        return {
            "cached_checks": len(statuses),
            "skip_count": sum(1 for s in statuses if s.should_skip),
            "warning_count": sum(1 for s in statuses if s.has_warning),
            "ok_count": sum(1 for s in statuses if not s.should_skip and not s.has_warning),
            "on_roster_count": sum(1 for s in statuses if s.is_on_roster),
            "not_on_roster_count": sum(1 for s in statuses if not s.is_on_roster),
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

_default_filter: Optional[AvailabilityFilter] = None


def get_availability_filter() -> AvailabilityFilter:
    """Get the default availability filter instance."""
    global _default_filter
    if _default_filter is None:
        _default_filter = AvailabilityFilter()
    return _default_filter


def check_player_availability(
    player_lookup: str,
    game_date: date,
    team_abbr: Optional[str] = None
) -> AvailabilityStatus:
    """
    Convenience function to check full player availability.

    Args:
        player_lookup: Player identifier
        game_date: Date of the game
        team_abbr: Optional team filter

    Returns:
        AvailabilityStatus with complete status info
    """
    return get_availability_filter().check_player(player_lookup, game_date, team_abbr)


def should_skip_prediction(
    player_lookup: str,
    game_date: date,
    team_abbr: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Convenience function to check if prediction should be skipped.

    Returns:
        Tuple of (should_skip, reason)
    """
    return get_availability_filter().should_skip_prediction(
        player_lookup, game_date, team_abbr
    )
