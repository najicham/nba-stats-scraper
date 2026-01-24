"""
Schedule Context

Determines what games happened on a date and related context:
- Games scheduled
- Teams playing
- Bootstrap period detection
- Season context
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Set, Optional
import logging

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID, BOOTSTRAP_DAYS

logger = logging.getLogger(__name__)

# Import season dates utility
try:
    from shared.config.nba_season_dates import (
        get_season_start_date,
        get_season_year_from_date,
        is_early_season,
    )
except ImportError:
    logger.warning("Could not import nba_season_dates, using fallback")
    # Fallback implementations
    def get_season_year_from_date(game_date: date) -> int:
        return game_date.year if game_date.month >= 10 else game_date.year - 1

    def get_season_start_date(season_year: int, use_schedule_service: bool = True) -> date:
        # Fallback dates
        fallback = {
            2021: date(2021, 10, 19),
            2022: date(2022, 10, 18),
            2023: date(2023, 10, 24),
            2024: date(2024, 10, 22),
        }
        return fallback.get(season_year, date(season_year, 10, 22))

    def is_early_season(analysis_date: date, season_year: int, days_threshold: int = 14) -> bool:
        season_start = get_season_start_date(season_year)
        days_since_start = (analysis_date - season_start).days
        return 0 <= days_since_start < days_threshold


@dataclass
class GameInfo:
    """Information about a single game."""
    game_id: str
    game_date: date
    home_team: str
    away_team: str
    game_status: str = 'unknown'
    game_type: str = 'regular'  # 'regular', 'playoff', 'preseason', 'all_star'


@dataclass
class ScheduleContext:
    """Complete schedule context for a date."""
    game_date: date
    season_year: int
    season_string: str  # e.g., "2021-22"
    season_day: int  # Days since season opener (0 = opening night)
    is_bootstrap: bool  # Days 0 to BOOTSTRAP_DAYS-1
    date_type: str  # 'regular', 'playoff', 'preseason', 'offseason', 'all_star', 'no_games'

    games: List[GameInfo] = field(default_factory=list)
    teams_playing: Set[str] = field(default_factory=set)
    game_count: int = 0

    # For validation output
    is_valid_processing_date: bool = True
    skip_reason: Optional[str] = None

    def __post_init__(self):
        """Calculate derived fields."""
        self.game_count = len(self.games)
        if self.games:
            for game in self.games:
                self.teams_playing.add(game.home_team)
                self.teams_playing.add(game.away_team)


def get_schedule_context(game_date: date, client: Optional[bigquery.Client] = None) -> ScheduleContext:
    """
    Get complete schedule context for a date.

    Args:
        game_date: Date to get context for
        client: Optional BigQuery client (creates one if not provided)

    Returns:
        ScheduleContext with all relevant information
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    # Determine season year and string
    season_year = get_season_year_from_date(game_date)
    season_string = f"{season_year}-{str(season_year + 1)[-2:]}"

    # Calculate season day
    season_start = get_season_start_date(season_year)
    season_day = (game_date - season_start).days

    # Check if bootstrap period
    is_bootstrap = is_early_season(game_date, season_year, days_threshold=BOOTSTRAP_DAYS)

    # Query schedule for games
    games, date_type = _query_schedule(client, game_date)

    # Determine if this is a valid processing date
    is_valid = True
    skip_reason = None

    if date_type == 'offseason':
        is_valid = False
        skip_reason = "Offseason - no games scheduled"
    elif date_type == 'preseason':
        is_valid = False
        skip_reason = "Preseason - not processed"
    elif date_type == 'all_star':
        is_valid = False
        skip_reason = "All-Star game - not processed"
    elif date_type == 'no_games':
        is_valid = False
        skip_reason = "No games scheduled for this date"
    elif season_day < 0:
        is_valid = False
        skip_reason = f"Before season start ({season_start})"

    return ScheduleContext(
        game_date=game_date,
        season_year=season_year,
        season_string=season_string,
        season_day=season_day,
        is_bootstrap=is_bootstrap,
        date_type=date_type,
        games=games,
        is_valid_processing_date=is_valid,
        skip_reason=skip_reason,
    )


def _query_schedule(client: bigquery.Client, game_date: date) -> tuple:
    """
    Query the schedule for games on a date.

    Returns:
        Tuple of (list of GameInfo, date_type string)
    """
    query = f"""
    SELECT
        game_id,
        game_date,
        home_team_tricode as home_team,
        away_team_tricode as away_team,
        COALESCE(game_status_text, 'Unknown') as game_status,
        season_year
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = @game_date
    ORDER BY game_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)
        rows = list(result)

        if not rows:
            # No games - determine why
            date_type = _determine_no_games_type(game_date)
            return [], date_type

        games = []
        for row in rows:
            game_type = _determine_game_type(row.game_id, row.game_status)
            games.append(GameInfo(
                game_id=row.game_id,
                game_date=row.game_date,
                home_team=row.home_team,
                away_team=row.away_team,
                game_status=row.game_status,
                game_type=game_type,
            ))

        # Determine overall date type
        if all(g.game_type == 'preseason' for g in games):
            date_type = 'preseason'
        elif any(g.game_type == 'all_star' for g in games):
            date_type = 'all_star'
        elif any(g.game_type == 'playoff' for g in games):
            date_type = 'playoff'
        else:
            date_type = 'regular'

        return games, date_type

    except Exception as e:
        logger.error(f"Error querying schedule for {game_date}: {e}", exc_info=True)
        return [], 'error'


def _determine_game_type(game_id: str, game_status: str) -> str:
    """Determine game type from game_id pattern."""
    if not game_id:
        return 'unknown'

    # NBA game_id patterns:
    # 00 = preseason, 01 = regular, 02 = playoffs, 03 = all-star
    if len(game_id) >= 3:
        type_code = game_id[2:4] if len(game_id) >= 4 else game_id[2]
        if type_code in ('00',):
            return 'preseason'
        elif type_code in ('01', '02'):
            return 'regular'
        elif type_code in ('04', '05'):  # Playoffs/Play-In
            return 'playoff'
        elif type_code in ('03',):
            return 'all_star'

    return 'regular'


def _determine_no_games_type(game_date: date) -> str:
    """Determine why there are no games on a date."""
    month = game_date.month

    # Offseason: July, August, September
    if month in [7, 8, 9]:
        return 'offseason'

    # All-Star break: typically mid-February
    if month == 2 and 14 <= game_date.day <= 20:
        return 'all_star_break'

    # Otherwise just no games scheduled
    return 'no_games'


def format_schedule_summary(context: ScheduleContext) -> str:
    """Format schedule context for display."""
    lines = []

    if not context.is_valid_processing_date:
        lines.append(f"Status:     {context.skip_reason}")
        lines.append(f"Games:      0")
        return '\n'.join(lines)

    lines.append(f"Games:              {context.game_count}")
    if context.games:
        game_list = ', '.join(
            f"{g.away_team} @ {g.home_team}"
            for g in context.games
        )
        lines.append(f"Matchups:           {game_list}")

    lines.append(f"Teams Playing:      {len(context.teams_playing)} ({', '.join(sorted(context.teams_playing))})")
    lines.append(f"Season:             {context.season_string} (Day {context.season_day})")

    if context.is_bootstrap:
        lines.append(f"Bootstrap:          Yes (Days 0-{BOOTSTRAP_DAYS-1} - Phase 4/5 skip)")
    else:
        lines.append(f"Bootstrap:          No")

    if context.date_type != 'regular':
        lines.append(f"Game Type:          {context.date_type.title()}")

    return '\n'.join(lines)
