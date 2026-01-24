#!/usr/bin/env python3
"""
Roster Manager - Unified roster extraction and tracking functionality.

This module provides:
1. RosterChangeTracker - Track trades, signings, waivers from player movement data
2. ActiveRosterCalculator - Calculate "active roster" combining roster + injuries
3. RosterManager - High-level interface for roster operations used in predictions

Usage:
    from shared.utils.roster_manager import RosterManager

    manager = RosterManager()

    # Get active roster for a team on a specific date
    active_roster = manager.get_active_roster('LAL', game_date)

    # Get roster changes for a team
    changes = manager.get_roster_changes('LAL', start_date, end_date)

    # Check if player is available for prediction
    availability = manager.check_player_availability('lebron-james', game_date)
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
from google.cloud import bigquery

logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

class TransactionType(Enum):
    """Types of roster transactions."""
    TRADE = "trade"
    SIGNING = "signing"
    WAIVER = "waiver"
    TWO_WAY_CONTRACT = "two_way"
    TEN_DAY_CONTRACT = "10_day"
    G_LEAGUE_ASSIGNMENT = "g_league_assignment"
    G_LEAGUE_RECALL = "g_league_recall"
    RELEASE = "release"
    RETIREMENT = "retirement"
    SUSPENSION = "suspension"
    OTHER = "other"


class AvailabilityStatus(Enum):
    """Player availability status for predictions."""
    AVAILABLE = "available"
    QUESTIONABLE = "questionable"
    DOUBTFUL = "doubtful"
    OUT = "out"
    NOT_ON_ROSTER = "not_on_roster"
    SUSPENDED = "suspended"
    G_LEAGUE = "g_league"
    UNKNOWN = "unknown"


@dataclass
class RosterChange:
    """Represents a single roster change event."""
    player_lookup: str
    player_full_name: str
    team_abbr: str
    transaction_type: TransactionType
    transaction_date: date
    description: str
    from_team: Optional[str] = None  # For trades
    to_team: Optional[str] = None    # For trades
    additional_info: Dict = field(default_factory=dict)


@dataclass
class PlayerAvailability:
    """Player availability status for a specific game."""
    player_lookup: str
    team_abbr: str
    game_date: date
    status: AvailabilityStatus
    is_on_roster: bool
    injury_status: Optional[str] = None
    injury_reason: Optional[str] = None
    roster_status: Optional[str] = None  # Active, Two-Way, G-League, etc.
    last_roster_change: Optional[RosterChange] = None
    confidence: float = 1.0
    message: str = ""


@dataclass
class TeamRoster:
    """Complete team roster with player details."""
    team_abbr: str
    roster_date: date
    season_year: int
    players: List[Dict]
    active_count: int
    injured_count: int
    g_league_count: int
    two_way_count: int


# ============================================================================
# ROSTER CHANGE TRACKER
# ============================================================================

class RosterChangeTracker:
    """
    Tracks roster changes (trades, signings, waivers) from player movement data.

    Data Source: nba_raw.nbac_player_movement (NBA.com player movement feed)

    Transaction types tracked:
    - Trades (player exchanged between teams)
    - Signings (free agent signings, contract extensions)
    - Waivers (player released/waived)
    - Two-way contracts
    - 10-day contracts
    - G-League assignments/recalls
    """

    # Map raw transaction descriptions to transaction types
    TRANSACTION_TYPE_MAPPING = {
        'Signed': TransactionType.SIGNING,
        'Waived': TransactionType.WAIVER,
        'Traded': TransactionType.TRADE,
        'Released': TransactionType.RELEASE,
        'Two-Way': TransactionType.TWO_WAY_CONTRACT,
        '10-Day': TransactionType.TEN_DAY_CONTRACT,
        'G League': TransactionType.G_LEAGUE_ASSIGNMENT,
        'Recalled': TransactionType.G_LEAGUE_RECALL,
        'Retired': TransactionType.RETIREMENT,
        'Suspended': TransactionType.SUSPENSION,
    }

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self._client = None
        self._cache: Dict[str, List[RosterChange]] = {}

    @property
    def client(self) -> bigquery.Client:
        """Lazy-load BigQuery client."""
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def get_roster_changes(
        self,
        team_abbr: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        player_lookup: Optional[str] = None,
        transaction_types: Optional[List[TransactionType]] = None
    ) -> List[RosterChange]:
        """
        Get roster changes for a team or player within a date range.

        Args:
            team_abbr: Filter by team (optional)
            start_date: Start of date range (defaults to 30 days ago)
            end_date: End of date range (defaults to today)
            player_lookup: Filter by specific player (optional)
            transaction_types: Filter by transaction types (optional)

        Returns:
            List of RosterChange objects
        """
        if start_date is None:
            start_date = date.today() - timedelta(days=30)
        if end_date is None:
            end_date = date.today()

        # Build query with filters
        query = """
        SELECT
            player_lookup,
            player_full_name,
            team_abbr,
            transaction_type,
            transaction_date,
            transaction_description
        FROM `{project}.nba_raw.nbac_player_movement`
        WHERE transaction_date BETWEEN @start_date AND @end_date
          AND is_player_transaction = TRUE
        """.format(project=self.project_id)

        params = [
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]

        if team_abbr:
            query += " AND team_abbr = @team_abbr"
            params.append(bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr))

        if player_lookup:
            query += " AND player_lookup = @player_lookup"
            params.append(bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup))

        query += " ORDER BY transaction_date DESC"

        job_config = bigquery.QueryJobConfig(query_parameters=params)

        try:
            result = self.client.query(query, job_config=job_config).result()
            changes = []

            for row in result:
                transaction_type = self._classify_transaction(
                    row.transaction_type,
                    row.transaction_description
                )

                # Filter by transaction type if specified
                if transaction_types and transaction_type not in transaction_types:
                    continue

                # Parse trade details from description
                from_team, to_team = self._parse_trade_details(
                    row.transaction_description
                )

                change = RosterChange(
                    player_lookup=row.player_lookup,
                    player_full_name=row.player_full_name,
                    team_abbr=row.team_abbr,
                    transaction_type=transaction_type,
                    transaction_date=row.transaction_date,
                    description=row.transaction_description,
                    from_team=from_team,
                    to_team=to_team,
                )
                changes.append(change)

            logger.info(
                f"Found {len(changes)} roster changes "
                f"({start_date} to {end_date})"
                + (f" for {team_abbr}" if team_abbr else "")
            )
            return changes

        except Exception as e:
            logger.error(f"Error fetching roster changes: {e}")
            return []

    def get_recent_changes_for_player(
        self,
        player_lookup: str,
        days_back: int = 30
    ) -> List[RosterChange]:
        """
        Get recent roster changes for a specific player.

        Useful for determining current team and roster status.
        """
        start_date = date.today() - timedelta(days=days_back)
        return self.get_roster_changes(
            player_lookup=player_lookup,
            start_date=start_date
        )

    def get_player_current_team(
        self,
        player_lookup: str,
        as_of_date: Optional[date] = None
    ) -> Optional[str]:
        """
        Determine a player's current team based on most recent transaction.

        Returns None if player has no transactions or was waived/released.
        """
        if as_of_date is None:
            as_of_date = date.today()

        changes = self.get_roster_changes(
            player_lookup=player_lookup,
            start_date=as_of_date - timedelta(days=365),  # Look back 1 year
            end_date=as_of_date
        )

        if not changes:
            return None

        # Most recent change first
        latest_change = changes[0]

        # If waived/released, player has no team
        if latest_change.transaction_type in [
            TransactionType.WAIVER,
            TransactionType.RELEASE,
            TransactionType.RETIREMENT
        ]:
            return None

        # For trades, use to_team if available
        if latest_change.to_team:
            return latest_change.to_team

        return latest_change.team_abbr

    def _classify_transaction(
        self,
        transaction_type_raw: str,
        description: str
    ) -> TransactionType:
        """Classify transaction based on type and description text."""
        # Check raw transaction type first
        for keyword, tx_type in self.TRANSACTION_TYPE_MAPPING.items():
            if keyword.lower() in transaction_type_raw.lower():
                return tx_type

        # Fall back to description analysis
        # NOTE: Order matters - check more specific patterns first
        description_lower = description.lower()

        if 'trade' in description_lower or 'acquired' in description_lower:
            return TransactionType.TRADE
        if 'waive' in description_lower:
            return TransactionType.WAIVER
        # Check G-League BEFORE signing (because "assigned" contains "sign")
        if 'g league' in description_lower or 'g-league' in description_lower:
            if 'recall' in description_lower:
                return TransactionType.G_LEAGUE_RECALL
            return TransactionType.G_LEAGUE_ASSIGNMENT
        if 'assigned' in description_lower:
            # Typically G-League assignment
            return TransactionType.G_LEAGUE_ASSIGNMENT
        if 'two-way' in description_lower or '2-way' in description_lower:
            return TransactionType.TWO_WAY_CONTRACT
        if '10-day' in description_lower or 'ten-day' in description_lower:
            return TransactionType.TEN_DAY_CONTRACT
        # Check signing after G-League/assignment checks
        if 'sign' in description_lower:
            return TransactionType.SIGNING
        if 'release' in description_lower:
            return TransactionType.RELEASE
        if 'retire' in description_lower:
            return TransactionType.RETIREMENT
        if 'suspend' in description_lower:
            return TransactionType.SUSPENSION

        return TransactionType.OTHER

    def _parse_trade_details(
        self,
        description: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Parse trade from/to teams from description."""
        # Common patterns:
        # "Traded to LAL from BOS"
        # "Acquired from PHI"
        # "Sent to MIA in trade"

        import re

        # Pattern: "to TEAM from TEAM"
        match = re.search(r'to\s+([A-Z]{2,3})\s+from\s+([A-Z]{2,3})', description, re.I)
        if match:
            return match.group(2).upper(), match.group(1).upper()

        # Pattern: "from TEAM"
        match = re.search(r'from\s+([A-Z]{2,3})', description, re.I)
        if match:
            return match.group(1).upper(), None

        # Pattern: "to TEAM"
        match = re.search(r'to\s+([A-Z]{2,3})', description, re.I)
        if match:
            return None, match.group(1).upper()

        return None, None


# ============================================================================
# ACTIVE ROSTER CALCULATOR
# ============================================================================

class ActiveRosterCalculator:
    """
    Calculates "active roster" by combining roster data with injury status.

    Data Sources:
    - nba_raw.espn_team_rosters (current roster)
    - nba_raw.nbac_injury_report (injury status)
    - nba_raw.nbac_player_movement (recent transactions)

    Active roster excludes:
    - Players listed as OUT in injury report
    - Players on G-League assignment
    - Suspended players
    """

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self._client = None

    @property
    def client(self) -> bigquery.Client:
        """Lazy-load BigQuery client."""
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def get_active_roster(
        self,
        team_abbr: str,
        game_date: date,
        include_questionable: bool = True
    ) -> TeamRoster:
        """
        Get active roster for a team on a specific game date.

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Date of the game
            include_questionable: Include QUESTIONABLE players in active count

        Returns:
            TeamRoster with active/injured/g-league counts
        """
        # Get roster data (most recent roster for team)
        roster_query = """
        WITH latest_roster AS (
            SELECT
                r.*,
                ROW_NUMBER() OVER (
                    PARTITION BY r.player_lookup
                    ORDER BY r.roster_date DESC
                ) as rn
            FROM `{project}.nba_raw.espn_team_rosters` r
            WHERE r.team_abbr = @team_abbr
              AND r.roster_date <= @game_date
              AND r.roster_date >= DATE_SUB(@game_date, INTERVAL 7 DAY)
        ),
        injuries AS (
            SELECT
                player_lookup,
                injury_status,
                reason,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) as rn
            FROM `{project}.nba_raw.nbac_injury_report`
            WHERE game_date = @game_date
        )
        SELECT
            lr.player_lookup,
            lr.player_full_name,
            lr.jersey_number,
            lr.position,
            lr.height,
            lr.weight,
            lr.status as roster_status,
            lr.roster_date,
            lr.season_year,
            COALESCE(i.injury_status, 'healthy') as injury_status,
            i.reason as injury_reason
        FROM latest_roster lr
        LEFT JOIN injuries i ON lr.player_lookup = i.player_lookup AND i.rn = 1
        WHERE lr.rn = 1
        ORDER BY lr.jersey_number
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ])

        try:
            result = self.client.query(roster_query, job_config=job_config).result()

            players = []
            active_count = 0
            injured_count = 0
            g_league_count = 0
            two_way_count = 0
            season_year = None
            roster_date = None

            for row in result:
                player = {
                    'player_lookup': row.player_lookup,
                    'player_full_name': row.player_full_name,
                    'jersey_number': row.jersey_number,
                    'position': row.position,
                    'height': row.height,
                    'weight': row.weight,
                    'roster_status': row.roster_status,
                    'injury_status': row.injury_status,
                    'injury_reason': row.injury_reason,
                    'is_active': self._is_player_active(
                        row.injury_status,
                        row.roster_status,
                        include_questionable
                    )
                }
                players.append(player)

                if season_year is None:
                    season_year = row.season_year
                if roster_date is None:
                    roster_date = row.roster_date

                # Categorize player
                injury_lower = (row.injury_status or '').lower()
                roster_lower = (row.roster_status or '').lower()

                if injury_lower == 'out':
                    injured_count += 1
                elif 'g league' in roster_lower or 'g-league' in roster_lower:
                    g_league_count += 1
                elif 'two-way' in roster_lower or 'two way' in roster_lower:
                    two_way_count += 1
                    if player['is_active']:
                        active_count += 1
                elif player['is_active']:
                    active_count += 1

            logger.info(
                f"Active roster for {team_abbr} on {game_date}: "
                f"{active_count} active, {injured_count} injured, "
                f"{g_league_count} G-League, {two_way_count} two-way"
            )

            return TeamRoster(
                team_abbr=team_abbr,
                roster_date=roster_date or game_date,
                season_year=season_year or self._calculate_season_year(game_date),
                players=players,
                active_count=active_count,
                injured_count=injured_count,
                g_league_count=g_league_count,
                two_way_count=two_way_count
            )

        except Exception as e:
            logger.error(f"Error fetching active roster for {team_abbr}: {e}")
            return TeamRoster(
                team_abbr=team_abbr,
                roster_date=game_date,
                season_year=self._calculate_season_year(game_date),
                players=[],
                active_count=0,
                injured_count=0,
                g_league_count=0,
                two_way_count=0
            )

    def get_active_players(
        self,
        team_abbr: str,
        game_date: date
    ) -> List[str]:
        """
        Get list of player_lookup values for active players only.

        Useful for filtering predictions.
        """
        roster = self.get_active_roster(team_abbr, game_date)
        return [p['player_lookup'] for p in roster.players if p['is_active']]

    def _is_player_active(
        self,
        injury_status: Optional[str],
        roster_status: Optional[str],
        include_questionable: bool = True
    ) -> bool:
        """Determine if player should be considered active."""
        injury_lower = (injury_status or '').lower()
        roster_lower = (roster_status or '').lower()

        # Definitely not active
        if injury_lower == 'out':
            return False
        if 'g league' in roster_lower or 'g-league' in roster_lower:
            return False
        if 'suspended' in roster_lower:
            return False

        # Questionable depends on flag
        if injury_lower == 'doubtful':
            return include_questionable
        if injury_lower == 'questionable':
            return include_questionable

        return True

    def _calculate_season_year(self, game_date: date) -> int:
        """Calculate NBA season year from date."""
        if game_date.month >= 10:
            return game_date.year
        return game_date.year - 1


# ============================================================================
# ROSTER MANAGER - HIGH-LEVEL INTERFACE
# ============================================================================

class RosterManager:
    """
    High-level interface for roster operations used in predictions.

    Combines RosterChangeTracker and ActiveRosterCalculator to provide:
    - Active roster calculation
    - Player availability checking
    - Roster change history
    """

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.change_tracker = RosterChangeTracker(project_id)
        self.roster_calculator = ActiveRosterCalculator(project_id)
        self._availability_cache: Dict[str, PlayerAvailability] = {}

    def get_active_roster(
        self,
        team_abbr: str,
        game_date: date,
        include_questionable: bool = True
    ) -> TeamRoster:
        """Get active roster for a team on a game date."""
        return self.roster_calculator.get_active_roster(
            team_abbr, game_date, include_questionable
        )

    def get_active_players(
        self,
        team_abbr: str,
        game_date: date
    ) -> List[str]:
        """Get list of active player_lookup values for a team."""
        return self.roster_calculator.get_active_players(team_abbr, game_date)

    def get_roster_changes(
        self,
        team_abbr: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        player_lookup: Optional[str] = None,
        transaction_types: Optional[List[TransactionType]] = None
    ) -> List[RosterChange]:
        """Get roster changes within a date range."""
        return self.change_tracker.get_roster_changes(
            team_abbr=team_abbr,
            start_date=start_date,
            end_date=end_date,
            player_lookup=player_lookup,
            transaction_types=transaction_types
        )

    def check_player_availability(
        self,
        player_lookup: str,
        game_date: date,
        team_abbr: Optional[str] = None
    ) -> PlayerAvailability:
        """
        Check if a player is available for predictions on a specific game date.

        Checks:
        1. Is player on team roster?
        2. What is their injury status?
        3. Any recent roster changes?

        Args:
            player_lookup: Player identifier
            game_date: Date of the game
            team_abbr: Optional team filter (if player's team is known)

        Returns:
            PlayerAvailability with status and details
        """
        cache_key = f"{player_lookup}_{game_date}_{team_abbr or 'any'}"
        if cache_key in self._availability_cache:
            return self._availability_cache[cache_key]

        # Get player's current team if not specified
        if team_abbr is None:
            team_abbr = self.change_tracker.get_player_current_team(
                player_lookup, game_date
            )

        if team_abbr is None:
            # No team found - player might not be in league
            availability = PlayerAvailability(
                player_lookup=player_lookup,
                team_abbr="",
                game_date=game_date,
                status=AvailabilityStatus.NOT_ON_ROSTER,
                is_on_roster=False,
                confidence=0.5,
                message="Player not found on any roster"
            )
            self._availability_cache[cache_key] = availability
            return availability

        # Get active roster for the team
        roster = self.get_active_roster(team_abbr, game_date)

        # Find player in roster
        player_info = None
        for p in roster.players:
            if p['player_lookup'] == player_lookup:
                player_info = p
                break

        if player_info is None:
            # Check recent transactions for this player
            recent_changes = self.change_tracker.get_recent_changes_for_player(
                player_lookup, days_back=7
            )

            last_change = recent_changes[0] if recent_changes else None

            availability = PlayerAvailability(
                player_lookup=player_lookup,
                team_abbr=team_abbr,
                game_date=game_date,
                status=AvailabilityStatus.NOT_ON_ROSTER,
                is_on_roster=False,
                last_roster_change=last_change,
                confidence=0.7,
                message=f"Player not found on {team_abbr} roster"
            )
            self._availability_cache[cache_key] = availability
            return availability

        # Map injury status to availability
        injury_status = (player_info.get('injury_status') or '').lower()
        roster_status = (player_info.get('roster_status') or '').lower()

        if injury_status == 'out':
            status = AvailabilityStatus.OUT
            message = f"OUT: {player_info.get('injury_reason', 'Injury')}"
        elif injury_status == 'doubtful':
            status = AvailabilityStatus.DOUBTFUL
            message = f"DOUBTFUL: {player_info.get('injury_reason', 'Injury')}"
        elif injury_status == 'questionable':
            status = AvailabilityStatus.QUESTIONABLE
            message = f"QUESTIONABLE: {player_info.get('injury_reason', 'Injury')}"
        elif 'g league' in roster_status or 'g-league' in roster_status:
            status = AvailabilityStatus.G_LEAGUE
            message = "On G-League assignment"
        elif 'suspended' in roster_status:
            status = AvailabilityStatus.SUSPENDED
            message = "Suspended"
        else:
            status = AvailabilityStatus.AVAILABLE
            message = "Available"

        # Get recent roster changes for context
        recent_changes = self.change_tracker.get_recent_changes_for_player(
            player_lookup, days_back=7
        )
        last_change = recent_changes[0] if recent_changes else None

        availability = PlayerAvailability(
            player_lookup=player_lookup,
            team_abbr=team_abbr,
            game_date=game_date,
            status=status,
            is_on_roster=True,
            injury_status=player_info.get('injury_status'),
            injury_reason=player_info.get('injury_reason'),
            roster_status=player_info.get('roster_status'),
            last_roster_change=last_change,
            confidence=1.0 if injury_status in ['out', 'healthy', ''] else 0.8,
            message=message
        )

        self._availability_cache[cache_key] = availability
        return availability

    def check_players_batch(
        self,
        player_lookups: List[str],
        game_date: date,
        team_abbr: Optional[str] = None
    ) -> Dict[str, PlayerAvailability]:
        """
        Check availability for multiple players efficiently.

        Args:
            player_lookups: List of player identifiers
            game_date: Date of the game
            team_abbr: Optional team filter

        Returns:
            Dict mapping player_lookup to PlayerAvailability
        """
        results = {}

        # If team is specified, get roster once
        if team_abbr:
            roster = self.get_active_roster(team_abbr, game_date)
            roster_by_player = {p['player_lookup']: p for p in roster.players}

            for player_lookup in player_lookups:
                if player_lookup in roster_by_player:
                    # Player is on roster - check their status
                    results[player_lookup] = self.check_player_availability(
                        player_lookup, game_date, team_abbr
                    )
                else:
                    # Player not on specified team
                    results[player_lookup] = PlayerAvailability(
                        player_lookup=player_lookup,
                        team_abbr=team_abbr,
                        game_date=game_date,
                        status=AvailabilityStatus.NOT_ON_ROSTER,
                        is_on_roster=False,
                        confidence=0.9,
                        message=f"Player not on {team_abbr} roster"
                    )
        else:
            # Check each player individually
            for player_lookup in player_lookups:
                results[player_lookup] = self.check_player_availability(
                    player_lookup, game_date
                )

        return results

    def should_skip_prediction(
        self,
        player_lookup: str,
        game_date: date,
        team_abbr: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Convenience method: Should we skip generating a prediction for this player?

        Returns:
            Tuple of (should_skip, reason)
        """
        availability = self.check_player_availability(
            player_lookup, game_date, team_abbr
        )

        if availability.status == AvailabilityStatus.OUT:
            return True, f"SKIP: {availability.message}"

        if availability.status == AvailabilityStatus.NOT_ON_ROSTER:
            return True, f"SKIP: {availability.message}"

        if availability.status == AvailabilityStatus.G_LEAGUE:
            return True, f"SKIP: {availability.message}"

        if availability.status == AvailabilityStatus.SUSPENDED:
            return True, f"SKIP: {availability.message}"

        # For questionable/doubtful, generate prediction but flag it
        if availability.status in [
            AvailabilityStatus.QUESTIONABLE,
            AvailabilityStatus.DOUBTFUL
        ]:
            return False, f"WARNING: {availability.message}"

        return False, "OK"

    def clear_cache(self):
        """Clear the availability cache."""
        self._availability_cache.clear()

    def get_stats(self) -> Dict:
        """Get statistics about cached availability checks."""
        if not self._availability_cache:
            return {"cached_checks": 0}

        statuses = list(self._availability_cache.values())
        return {
            "cached_checks": len(statuses),
            "available": sum(1 for s in statuses if s.status == AvailabilityStatus.AVAILABLE),
            "out": sum(1 for s in statuses if s.status == AvailabilityStatus.OUT),
            "questionable": sum(1 for s in statuses if s.status == AvailabilityStatus.QUESTIONABLE),
            "doubtful": sum(1 for s in statuses if s.status == AvailabilityStatus.DOUBTFUL),
            "not_on_roster": sum(1 for s in statuses if s.status == AvailabilityStatus.NOT_ON_ROSTER),
            "g_league": sum(1 for s in statuses if s.status == AvailabilityStatus.G_LEAGUE),
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

# Singleton instance
_default_manager: Optional[RosterManager] = None


def get_roster_manager() -> RosterManager:
    """Get the default roster manager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = RosterManager()
    return _default_manager


def get_active_roster(team_abbr: str, game_date: date) -> TeamRoster:
    """Convenience function to get active roster."""
    return get_roster_manager().get_active_roster(team_abbr, game_date)


def check_player_availability(
    player_lookup: str,
    game_date: date,
    team_abbr: Optional[str] = None
) -> PlayerAvailability:
    """Convenience function to check player availability."""
    return get_roster_manager().check_player_availability(
        player_lookup, game_date, team_abbr
    )


def get_roster_changes(
    team_abbr: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[RosterChange]:
    """Convenience function to get roster changes."""
    return get_roster_manager().get_roster_changes(
        team_abbr=team_abbr,
        start_date=start_date,
        end_date=end_date
    )
