"""
Player Universe

Determines which players should be processed for a given date:
- All rostered players (from gamebook)
- Active players (who played)
- Players with prop lines
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Set, Dict, Optional, List
import logging

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID

logger = logging.getLogger(__name__)


@dataclass
class PlayerInfo:
    """Information about a single player."""
    player_lookup: str
    team_abbr: str
    player_status: str  # 'active', 'dnp', 'inactive'
    has_prop_line: bool = False
    prop_line_value: Optional[float] = None


@dataclass
class PlayerUniverse:
    """Complete player universe for a date."""
    game_date: date

    # Player sets
    all_rostered: Set[str] = field(default_factory=set)
    active_players: Set[str] = field(default_factory=set)
    dnp_players: Set[str] = field(default_factory=set)
    inactive_players: Set[str] = field(default_factory=set)
    players_with_props: Set[str] = field(default_factory=set)

    # Detailed player info
    player_details: Dict[str, PlayerInfo] = field(default_factory=dict)

    # Counts
    total_rostered: int = 0
    total_active: int = 0
    total_dnp: int = 0
    total_inactive: int = 0
    total_with_props: int = 0

    # Teams
    teams: Set[str] = field(default_factory=set)

    def __post_init__(self):
        """Calculate counts from sets."""
        self._update_counts()

    def _update_counts(self):
        """Update count fields from sets."""
        self.total_rostered = len(self.all_rostered)
        self.total_active = len(self.active_players)
        self.total_dnp = len(self.dnp_players)
        self.total_inactive = len(self.inactive_players)
        self.total_with_props = len(self.players_with_props)

    def get_expected_for_phase(self, phase: int, table_scope: str) -> Set[str]:
        """
        Get expected players for a given phase and table scope.

        Args:
            phase: Phase number (3, 4, or 5)
            table_scope: 'all_players', 'prop_players', 'teams'

        Returns:
            Set of player_lookups expected for this scope
        """
        if table_scope == 'teams':
            return self.teams
        elif table_scope == 'all_players':
            # Target state: all active players
            return self.active_players
        elif table_scope == 'prop_players':
            # Current limitation: only prop players
            return self.players_with_props
        else:
            return self.active_players


def get_player_universe(
    game_date: date,
    client: Optional[bigquery.Client] = None
) -> PlayerUniverse:
    """
    Get complete player universe for a date.

    Args:
        game_date: Date to get players for
        client: Optional BigQuery client

    Returns:
        PlayerUniverse with all player sets
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    universe = PlayerUniverse(game_date=game_date)

    # Get all players from gamebook
    _query_gamebook_players(client, game_date, universe)

    # Get players with prop lines
    _query_prop_players(client, game_date, universe)

    # Update counts
    universe._update_counts()

    logger.debug(
        f"Player universe for {game_date}: "
        f"{universe.total_rostered} rostered, "
        f"{universe.total_active} active, "
        f"{universe.total_with_props} with props"
    )

    return universe


def _query_gamebook_players(
    client: bigquery.Client,
    game_date: date,
    universe: PlayerUniverse
) -> None:
    """Query gamebook for all players on a date."""
    query = f"""
    SELECT DISTINCT
        player_lookup,
        team_abbr,
        player_status
    FROM `{PROJECT_ID}.nba_raw.nbac_gamebook_player_stats`
    WHERE game_date = @game_date
      AND player_lookup IS NOT NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()

        for row in result:
            player_lookup = row.player_lookup
            status = row.player_status or 'unknown'

            # Add to appropriate sets
            universe.all_rostered.add(player_lookup)
            universe.teams.add(row.team_abbr)

            if status == 'active':
                universe.active_players.add(player_lookup)
            elif status == 'dnp':
                universe.dnp_players.add(player_lookup)
            elif status == 'inactive':
                universe.inactive_players.add(player_lookup)

            # Store detailed info
            universe.player_details[player_lookup] = PlayerInfo(
                player_lookup=player_lookup,
                team_abbr=row.team_abbr,
                player_status=status,
            )

    except Exception as e:
        logger.error(f"Error querying gamebook for {game_date}: {e}")


def _query_prop_players(
    client: bigquery.Client,
    game_date: date,
    universe: PlayerUniverse
) -> None:
    """Query prop tables for players with betting lines."""
    # Try BettingPros first (99.7% coverage), then Odds API
    query = f"""
    WITH props AS (
        SELECT DISTINCT
            player_lookup,
            points_line
        FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
        WHERE game_date = @game_date
          AND player_lookup IS NOT NULL

        UNION DISTINCT

        SELECT DISTINCT
            player_lookup,
            points_line
        FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
        WHERE game_date = @game_date
          AND player_lookup IS NOT NULL
    )
    SELECT
        player_lookup,
        MAX(points_line) as points_line
    FROM props
    GROUP BY player_lookup
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()

        for row in result:
            player_lookup = row.player_lookup
            universe.players_with_props.add(player_lookup)

            # Update detailed info if exists
            if player_lookup in universe.player_details:
                universe.player_details[player_lookup].has_prop_line = True
                universe.player_details[player_lookup].prop_line_value = row.points_line
            else:
                # Player has prop but not in gamebook (rare)
                universe.player_details[player_lookup] = PlayerInfo(
                    player_lookup=player_lookup,
                    team_abbr='UNK',
                    player_status='unknown',
                    has_prop_line=True,
                    prop_line_value=row.points_line,
                )

    except Exception as e:
        logger.error(f"Error querying props for {game_date}: {e}")


def format_player_universe(universe: PlayerUniverse) -> str:
    """Format player universe for display."""
    lines = [
        f"Total Rostered:     {universe.total_rostered} players across {len(universe.teams)} teams",
        f"  Active (played):  {universe.total_active}",
        f"  DNP:              {universe.total_dnp}",
        f"  Inactive:         {universe.total_inactive}",
        f"With Prop Lines:    {universe.total_with_props}",
    ]

    # Show prop coverage percentage
    if universe.total_active > 0:
        prop_pct = (universe.total_with_props / universe.total_active) * 100
        lines.append(f"Prop Coverage:      {prop_pct:.1f}% of active players")

    return '\n'.join(lines)


def get_missing_players(
    universe: PlayerUniverse,
    actual_players: Set[str],
    scope: str = 'all_players'
) -> List[str]:
    """
    Get list of missing players.

    Args:
        universe: Player universe
        actual_players: Set of players actually processed
        scope: 'all_players', 'prop_players', or 'active_players'

    Returns:
        List of missing player_lookups
    """
    if scope == 'all_players':
        expected = universe.active_players
    elif scope == 'prop_players':
        expected = universe.players_with_props
    else:
        expected = universe.active_players

    missing = expected - actual_players
    return sorted(list(missing))
