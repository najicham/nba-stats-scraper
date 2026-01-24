"""
Player Universe

Single source of truth for determining which players should be processed for a given date.

Supports multiple modes:
- BACKFILL mode: Uses gamebook (post-game actual data) → BDL fallback
- DAILY mode: Uses schedule + roster (pre-game data)

All components (validation, predictions, processors) should use get_player_universe()
to ensure consistent player sets across the system.

Issue 5 Fix: This module is now the canonical source for player universe.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Set, Dict, Optional, List
import logging

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID, get_processing_mode

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

    # Source tracking (for fallback awareness)
    source: str = 'gamebook'  # 'gamebook', 'bdl_fallback', or 'roster'
    has_dnp_tracking: bool = True  # False when using BDL fallback or roster
    roster_date: Optional[date] = None  # Date of roster data used (for freshness tracking)

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
    client: Optional[bigquery.Client] = None,
    mode: Optional[str] = None
) -> PlayerUniverse:
    """
    Get complete player universe for a date.

    This is the SINGLE SOURCE OF TRUTH for player universe across all components.
    Use this function instead of querying player data directly.

    Supports two modes:
    - 'backfill' (default): Uses gamebook (post-game data) → BDL fallback
    - 'daily': Uses schedule + roster (pre-game data, for today's games)

    Mode is auto-detected if not specified:
    - If gamebook has data → backfill mode
    - If gamebook empty AND date is today/future → daily mode
    - Explicit mode can be set via PROCESSING_MODE env var

    Args:
        game_date: Date to get players for
        client: Optional BigQuery client
        mode: Optional mode override ('daily' or 'backfill')

    Returns:
        PlayerUniverse with all player sets
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    universe = PlayerUniverse(game_date=game_date)

    # Determine mode if not explicitly specified
    # Uses shared get_processing_mode() from config.py for consistency
    if mode is None:
        mode = get_processing_mode(game_date)

    logger.debug(f"Using {mode} mode for player universe on {game_date}")

    if mode == 'daily':
        # Daily mode: Use schedule + roster (pre-game data)
        _query_roster_players(client, game_date, universe)
        universe.source = 'roster'
        universe.has_dnp_tracking = False
    else:
        # Backfill mode: Try gamebook first (gold source - has DNP/inactive tracking)
        _query_gamebook_players(client, game_date, universe)

        # Fallback to BDL if gamebook is empty
        if len(universe.all_rostered) == 0:
            logger.warning(
                f"No gamebook data for {game_date}, falling back to BDL "
                "(note: DNP/inactive players will not be tracked)"
            )
            _query_bdl_players(client, game_date, universe)
            universe.source = 'bdl_fallback'
            universe.has_dnp_tracking = False
        else:
            universe.source = 'gamebook'
            universe.has_dnp_tracking = True

    # Get players with prop lines
    _query_prop_players(client, game_date, universe)

    # Update counts
    universe._update_counts()

    logger.debug(
        f"Player universe for {game_date}: "
        f"{universe.total_rostered} rostered, "
        f"{universe.total_active} active, "
        f"{universe.total_with_props} with props "
        f"(source: {universe.source})"
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
        result = client.query(query, job_config=job_config).result(timeout=60)

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
        logger.error(f"Error querying gamebook for {game_date}: {e}", exc_info=True)


def _query_bdl_players(
    client: bigquery.Client,
    game_date: date,
    universe: PlayerUniverse
) -> None:
    """
    Query BDL boxscores for players on a date (fallback source).

    Note: BDL only contains players who actually played - no DNP/inactive tracking.
    All players from BDL are marked as 'active'.
    """
    query = f"""
    SELECT DISTINCT
        player_lookup,
        team_abbr
    FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
    WHERE game_date = @game_date
      AND player_lookup IS NOT NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)

        for row in result:
            player_lookup = row.player_lookup

            # Add to sets - all BDL players are active (they played)
            universe.all_rostered.add(player_lookup)
            universe.active_players.add(player_lookup)
            universe.teams.add(row.team_abbr)

            # Store detailed info (no DNP/inactive info available)
            universe.player_details[player_lookup] = PlayerInfo(
                player_lookup=player_lookup,
                team_abbr=row.team_abbr,
                player_status='active',  # BDL only has players who played
            )

    except Exception as e:
        logger.error(f"Error querying BDL boxscores for {game_date}: {e}", exc_info=True)


def _query_roster_players(
    client: bigquery.Client,
    game_date: date,
    universe: PlayerUniverse
) -> None:
    """
    Query roster for players on teams playing a given date (daily mode).

    Uses schedule + roster to get players for pre-game predictions.
    This is used when gamebook data doesn't exist yet (today's games).

    Note: This won't include injury filtering as that's handled by
    the calling processor. All rostered players are marked 'active'.
    """
    # Calculate roster date range (90 days to handle stale data)
    roster_start = (game_date - timedelta(days=90)).isoformat()
    roster_end = game_date.isoformat()

    query = f"""
    WITH games_on_date AS (
        SELECT
            game_id,
            home_team_tricode as home_team,
            away_team_tricode as away_team
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = @game_date
    ),
    teams_playing AS (
        SELECT DISTINCT home_team as team_abbr FROM games_on_date
        UNION DISTINCT
        SELECT DISTINCT away_team as team_abbr FROM games_on_date
    ),
    latest_roster AS (
        SELECT MAX(roster_date) as roster_date
        FROM `{PROJECT_ID}.nba_raw.espn_team_rosters`
        WHERE roster_date >= @roster_start
          AND roster_date <= @roster_end
    ),
    roster_players AS (
        SELECT DISTINCT
            r.player_lookup,
            r.team_abbr,
            lr.roster_date
        FROM `{PROJECT_ID}.nba_raw.espn_team_rosters` r
        INNER JOIN latest_roster lr ON r.roster_date = lr.roster_date
        WHERE r.roster_date >= @roster_start
          AND r.roster_date <= @roster_end
          AND r.team_abbr IN (SELECT team_abbr FROM teams_playing)
          AND r.player_lookup IS NOT NULL
    )
    SELECT
        player_lookup,
        team_abbr,
        roster_date
    FROM roster_players
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("roster_start", "STRING", roster_start),
            bigquery.ScalarQueryParameter("roster_end", "STRING", roster_end),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        roster_date_used = None

        for row in result:
            player_lookup = row.player_lookup

            # Add to sets - all roster players are considered 'active' (available)
            universe.all_rostered.add(player_lookup)
            universe.active_players.add(player_lookup)
            universe.teams.add(row.team_abbr)

            # Store detailed info
            universe.player_details[player_lookup] = PlayerInfo(
                player_lookup=player_lookup,
                team_abbr=row.team_abbr,
                player_status='active',  # Roster doesn't have DNP/inactive
            )

            # Track the roster date used
            if roster_date_used is None:
                roster_date_used = row.roster_date

        # Store roster date for freshness tracking (Issue 6)
        universe.roster_date = roster_date_used

        if roster_date_used:
            days_stale = (game_date - roster_date_used).days
            if days_stale > 7:
                logger.warning(
                    f"Roster data is {days_stale} days stale "
                    f"(roster from {roster_date_used}, game date {game_date})"
                )

    except Exception as e:
        logger.error(f"Error querying roster for {game_date}: {e}", exc_info=True)


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
        result = client.query(query, job_config=job_config).result(timeout=60)

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
        logger.error(f"Error querying props for {game_date}: {e}", exc_info=True)


def format_player_universe(universe: PlayerUniverse) -> str:
    """Format player universe for display."""
    # Show source-specific info
    if universe.source == 'bdl_fallback':
        roster_line = f"Total Rostered:     {universe.total_rostered} players across {len(universe.teams)} teams  ⚠️ BDL fallback"
        dnp_line = "  DNP:              — (unavailable)"
        inactive_line = "  Inactive:         — (unavailable)"
    elif universe.source == 'roster':
        stale_info = ""
        if universe.roster_date:
            days_stale = (universe.game_date - universe.roster_date).days
            if days_stale > 7:
                stale_info = f"  ⚠️ {days_stale} days stale"
            else:
                stale_info = f" (roster: {universe.roster_date})"
        roster_line = f"Total Rostered:     {universe.total_rostered} players across {len(universe.teams)} teams  📋 Roster mode{stale_info}"
        dnp_line = "  DNP:              — (pre-game)"
        inactive_line = "  Inactive:         — (pre-game)"
    else:
        roster_line = f"Total Rostered:     {universe.total_rostered} players across {len(universe.teams)} teams"
        dnp_line = f"  DNP:              {universe.total_dnp}"
        inactive_line = f"  Inactive:         {universe.total_inactive}"

    lines = [
        roster_line,
        f"  Active (played):  {universe.total_active}",
        dnp_line,
        inactive_line,
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
