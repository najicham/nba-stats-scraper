"""
MLB Schedule Context

Determines what games happened on a date and related context:
- Games scheduled
- Teams playing
- Season context (regular season, playoffs, All-Star break)
- Bootstrap period detection for early season

MLB Season Characteristics:
- Regular season: Late March/April to late September/early October
- All-Star break: Mid-July (typically 3-4 days)
- Offseason: October to March
- Bootstrap period: First 14 days (limited historical data for rolling windows)
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Set, Optional
import logging

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# MLB Season Configuration
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
MLB_BOOTSTRAP_DAYS = 14  # Days for rolling window calculations to stabilize

# MLB Season date ranges (approximate - actual dates vary slightly each year)
MLB_SEASON_DATES = {
    2022: {"start": date(2022, 4, 7), "end": date(2022, 10, 5), "all_star_start": date(2022, 7, 18), "all_star_end": date(2022, 7, 21)},
    2023: {"start": date(2023, 3, 30), "end": date(2023, 10, 1), "all_star_start": date(2023, 7, 10), "all_star_end": date(2023, 7, 13)},
    2024: {"start": date(2024, 3, 28), "end": date(2024, 9, 29), "all_star_start": date(2024, 7, 15), "all_star_end": date(2024, 7, 18)},
    2025: {"start": date(2025, 3, 27), "end": date(2025, 9, 28), "all_star_start": date(2025, 7, 14), "all_star_end": date(2025, 7, 17)},
    2026: {"start": date(2026, 3, 26), "end": date(2026, 9, 27), "all_star_start": date(2026, 7, 13), "all_star_end": date(2026, 7, 16)},
}


@dataclass
class MlbGameInfo:
    """Information about a single MLB game."""
    game_pk: int
    game_date: date
    home_team: str
    away_team: str
    home_pitcher_id: Optional[int] = None
    home_pitcher_name: Optional[str] = None
    away_pitcher_id: Optional[int] = None
    away_pitcher_name: Optional[str] = None
    game_type: str = 'R'  # R=Regular, P=Playoff
    status: str = 'Scheduled'


@dataclass
class MlbScheduleContext:
    """Complete schedule context for an MLB date."""
    game_date: date
    season_year: int
    season_day: int  # Days since season opener (0 = opening day)
    is_bootstrap: bool  # Days 0 to MLB_BOOTSTRAP_DAYS-1
    date_type: str  # 'regular', 'playoff', 'all_star_break', 'offseason', 'no_games'

    games: List[MlbGameInfo] = field(default_factory=list)
    teams_playing: Set[str] = field(default_factory=set)
    game_count: int = 0
    pitchers_announced: int = 0

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
            self.pitchers_announced = sum(
                1 for g in self.games
                if g.home_pitcher_id or g.away_pitcher_id
            )


def get_mlb_season_year(game_date: date) -> int:
    """Get the MLB season year for a date."""
    # MLB season is within a single calendar year (unlike NBA)
    # Season starts in March/April and ends in September/October
    return game_date.year


def get_mlb_season_start(season_year: int) -> date:
    """Get the MLB season start date for a year."""
    if season_year in MLB_SEASON_DATES:
        return MLB_SEASON_DATES[season_year]["start"]
    # Fallback: assume late March
    return date(season_year, 3, 28)


def get_mlb_season_end(season_year: int) -> date:
    """Get the MLB season end date for a year."""
    if season_year in MLB_SEASON_DATES:
        return MLB_SEASON_DATES[season_year]["end"]
    # Fallback: assume late September
    return date(season_year, 9, 28)


def is_mlb_all_star_break(game_date: date) -> bool:
    """Check if date is during MLB All-Star break."""
    year = game_date.year
    if year in MLB_SEASON_DATES:
        start = MLB_SEASON_DATES[year]["all_star_start"]
        end = MLB_SEASON_DATES[year]["all_star_end"]
        return start <= game_date <= end
    # Fallback: mid-July
    return game_date.month == 7 and 12 <= game_date.day <= 17


def is_mlb_early_season(game_date: date, days_threshold: int = MLB_BOOTSTRAP_DAYS) -> bool:
    """Check if date is in MLB early season (bootstrap) period."""
    season_year = get_mlb_season_year(game_date)
    season_start = get_mlb_season_start(season_year)
    days_since_start = (game_date - season_start).days
    return 0 <= days_since_start < days_threshold


def is_mlb_offseason(game_date: date) -> bool:
    """Check if date is in MLB offseason."""
    season_year = get_mlb_season_year(game_date)
    season_start = get_mlb_season_start(season_year)
    season_end = get_mlb_season_end(season_year)

    # Before season start or after season end
    return game_date < season_start or game_date > season_end


def get_mlb_schedule_context(game_date: date, client: Optional[bigquery.Client] = None) -> MlbScheduleContext:
    """
    Get complete schedule context for an MLB date.

    Args:
        game_date: Date to get context for
        client: Optional BigQuery client (creates one if not provided)

    Returns:
        MlbScheduleContext with all relevant information
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    # Determine season year and day
    season_year = get_mlb_season_year(game_date)
    season_start = get_mlb_season_start(season_year)
    season_day = (game_date - season_start).days

    # Check if bootstrap period
    is_bootstrap = is_mlb_early_season(game_date)

    # Query schedule for games
    games, date_type = _query_mlb_schedule(client, game_date)

    # Determine if this is a valid processing date
    is_valid = True
    skip_reason = None

    if is_mlb_offseason(game_date):
        is_valid = False
        skip_reason = "MLB Offseason - no games scheduled"
        date_type = 'offseason'
    elif is_mlb_all_star_break(game_date):
        is_valid = False
        skip_reason = "MLB All-Star Break - no regular games"
        date_type = 'all_star_break'
    elif date_type == 'no_games':
        is_valid = False
        skip_reason = "No MLB games scheduled for this date"

    return MlbScheduleContext(
        game_date=game_date,
        season_year=season_year,
        season_day=season_day,
        is_bootstrap=is_bootstrap,
        date_type=date_type,
        games=games,
        is_valid_processing_date=is_valid,
        skip_reason=skip_reason,
    )


def _query_mlb_schedule(client: bigquery.Client, game_date: date) -> tuple:
    """
    Query the MLB schedule for games on a date.

    Returns:
        Tuple of (list of MlbGameInfo, date_type string)
    """
    query = f"""
    SELECT
        game_pk,
        game_date,
        home_team_abbr,
        away_team_abbr,
        home_probable_pitcher_id,
        home_probable_pitcher_name,
        away_probable_pitcher_id,
        away_probable_pitcher_name,
        game_type,
        status_detailed
    FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
    WHERE game_date = @game_date
    ORDER BY game_pk
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
            return [], 'no_games'

        games = []
        for row in rows:
            games.append(MlbGameInfo(
                game_pk=row.game_pk,
                game_date=row.game_date,
                home_team=row.home_team_abbr,
                away_team=row.away_team_abbr,
                home_pitcher_id=row.home_probable_pitcher_id,
                home_pitcher_name=row.home_probable_pitcher_name,
                away_pitcher_id=row.away_probable_pitcher_id,
                away_pitcher_name=row.away_probable_pitcher_name,
                game_type=row.game_type or 'R',
                status=row.status_detailed or 'Scheduled',
            ))

        # Determine overall date type
        if all(g.game_type == 'P' for g in games):
            date_type = 'playoff'
        else:
            date_type = 'regular'

        return games, date_type

    except Exception as e:
        logger.error(f"Error querying MLB schedule for {game_date}: {e}", exc_info=True)
        return [], 'error'


def has_mlb_games_on_date(game_date: date, client: Optional[bigquery.Client] = None) -> bool:
    """
    Quick check if any MLB games are scheduled on a date.

    This is a fast path for early exit checks.
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.mlb_raw.mlb_schedule`
    WHERE game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = list(client.query(query, job_config=job_config).result(timeout=30))
        count = int(result[0].cnt) if result else 0
        return count > 0
    except Exception as e:
        logger.error(f"Error checking MLB games on {game_date}: {e}", exc_info=True)
        return True  # Fail open


def format_mlb_schedule_summary(context: MlbScheduleContext) -> str:
    """Format MLB schedule context for display."""
    lines = []

    if not context.is_valid_processing_date:
        lines.append(f"Status:     {context.skip_reason}")
        lines.append(f"Games:      0")
        return '\n'.join(lines)

    lines.append(f"Games:              {context.game_count}")
    lines.append(f"Pitchers Announced: {context.pitchers_announced}")

    if context.games:
        game_list = ', '.join(
            f"{g.away_team} @ {g.home_team}"
            for g in context.games[:5]  # Limit display
        )
        if len(context.games) > 5:
            game_list += f" (+{len(context.games) - 5} more)"
        lines.append(f"Matchups:           {game_list}")

    lines.append(f"Teams Playing:      {len(context.teams_playing)}")
    lines.append(f"Season:             {context.season_year} (Day {context.season_day})")

    if context.is_bootstrap:
        lines.append(f"Bootstrap:          Yes (Days 0-{MLB_BOOTSTRAP_DAYS-1})")
    else:
        lines.append(f"Bootstrap:          No")

    if context.date_type != 'regular':
        lines.append(f"Game Type:          {context.date_type.replace('_', ' ').title()}")

    return '\n'.join(lines)
