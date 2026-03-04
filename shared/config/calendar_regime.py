"""
NBA Calendar Regime Configuration

Defines key calendar events (trade deadline, All-Star break) and toxic windows
that cause predictable model degradation. Used by bin/regime_analyzer.py for
daily regime detection and by filters for calendar-aware decision making.

Session 395: Created based on calendar regime analysis findings.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class SeasonCalendar:
    """Key calendar dates for an NBA season."""
    season_year: int  # e.g., 2025 for 2025-26
    trade_deadline: date
    asb_start: date  # First day of All-Star break (no games)
    asb_end: date  # Last day of All-Star break
    games_resume: date  # First game day after ASB

    # Derived toxic window (configurable override)
    toxic_start: Optional[date] = None
    toxic_end: Optional[date] = None

    def __post_init__(self):
        """Set default toxic window if not explicitly overridden."""
        if self.toxic_start is None:
            # Toxic starts ~1 week before trade deadline
            from datetime import timedelta
            self.toxic_start = self.trade_deadline - timedelta(days=7)
        if self.toxic_end is None:
            # Toxic ends ~7 days after games resume
            from datetime import timedelta
            self.toxic_end = self.games_resume + timedelta(days=6)


# Historical calendar data per season
SEASON_CALENDARS = {
    2025: SeasonCalendar(
        season_year=2025,
        trade_deadline=date(2026, 2, 6),
        asb_start=date(2026, 2, 13),
        asb_end=date(2026, 2, 15),
        games_resume=date(2026, 2, 19),
        # Empirically validated toxic window (Session 395)
        toxic_start=date(2026, 1, 30),
        toxic_end=date(2026, 2, 25),
    ),
    2024: SeasonCalendar(
        season_year=2024,
        trade_deadline=date(2025, 2, 6),
        asb_start=date(2025, 2, 14),
        asb_end=date(2025, 2, 16),
        games_resume=date(2025, 2, 20),
        # 2024-25 had smaller dips (2-4pp vs 10-15pp)
        toxic_start=date(2025, 1, 30),
        toxic_end=date(2025, 2, 26),
    ),
}


@dataclass
class RegimeInfo:
    """Current calendar regime classification."""
    name: str  # normal, pre_deadline, trade_deadline, post_deadline, asb, post_asb, recovery
    label: str  # Human-readable label
    is_toxic: bool
    days_into_regime: int
    days_until_next: Optional[int]  # Days until regime changes
    season_calendar: Optional[SeasonCalendar]


# Regime definitions with expected HR impact (from Session 395 findings)
REGIME_HR_NORMS = {
    'normal': {'hr': 62.2, 'over_hr': 63.5, 'under_hr': 61.6},
    'pre_deadline': {'hr': 46.6, 'over_hr': 57.6, 'under_hr': 43.1},
    'trade_deadline': {'hr': 43.2, 'over_hr': 33.3, 'under_hr': 50.0},
    'post_deadline': {'hr': 49.1, 'over_hr': 45.9, 'under_hr': 50.3},
    'asb': {'hr': None, 'over_hr': None, 'under_hr': None},  # No games
    'post_asb': {'hr': 50.7, 'over_hr': 48.4, 'under_hr': 51.4},
    'recovery': {'hr': 64.9, 'over_hr': None, 'under_hr': None},
}

# Tier x direction norms during toxic window (from Session 395 findings)
TOXIC_TIER_DIRECTION_NORMS = {
    ('Star', 'OVER'): {'normal_hr': 61.8, 'toxic_hr': 33.3, 'delta': -28.5, 'verdict': 'BLOCK'},
    ('Bench', 'UNDER'): {'normal_hr': 65.5, 'toxic_hr': 46.3, 'delta': -19.2, 'verdict': 'BELOW_BREAKEVEN'},
    ('Role', 'UNDER'): {'normal_hr': 59.0, 'toxic_hr': 41.8, 'delta': -17.2, 'verdict': 'BELOW_BREAKEVEN'},
    ('Star', 'UNDER'): {'normal_hr': 64.8, 'toxic_hr': 49.5, 'delta': -15.2, 'verdict': 'BELOW_BREAKEVEN'},
    ('Role', 'OVER'): {'normal_hr': 63.9, 'toxic_hr': 49.4, 'delta': -14.5, 'verdict': 'BELOW_BREAKEVEN'},
    ('Starter', 'OVER'): {'normal_hr': 59.4, 'toxic_hr': 47.2, 'delta': -12.2, 'verdict': 'BELOW_BREAKEVEN'},
    ('Bench', 'OVER'): {'normal_hr': 69.7, 'toxic_hr': 58.8, 'delta': -10.9, 'verdict': 'PROFITABLE'},
    ('Starter', 'UNDER'): {'normal_hr': 61.7, 'toxic_hr': 54.4, 'delta': -7.3, 'verdict': 'PROFITABLE'},
}

# Edge compression norms
EDGE_COMPRESSION_NORMS = {
    'normal': {'avg_edge': 5.85, 'std_edge': 3.48, 'avg_mae': 6.16},
    'toxic': {'avg_edge': 4.63, 'std_edge': 1.72, 'avg_mae': 6.62},
}

# Recovery timeline (days post-ASB resume)
RECOVERY_DAYS = 8  # HR returns to normal ~8 days after games resume (2025-26 data)


def get_season_calendar(game_date: date) -> Optional[SeasonCalendar]:
    """Get the season calendar for a given date."""
    # NBA season: Oct-Jun. Oct-Dec = same year, Jan-Sep = previous year
    season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
    return SEASON_CALENDARS.get(season_year)


def detect_regime(game_date: date) -> RegimeInfo:
    """
    Detect the current calendar regime for a given date.

    Returns RegimeInfo with regime classification and metadata.
    """
    cal = get_season_calendar(game_date)

    if cal is None:
        return RegimeInfo(
            name='normal', label='Normal (no calendar data)',
            is_toxic=False, days_into_regime=0,
            days_until_next=None, season_calendar=None
        )

    # Check specific sub-regimes in order
    if game_date == cal.trade_deadline:
        return RegimeInfo(
            name='trade_deadline', label='Trade Deadline Day',
            is_toxic=True, days_into_regime=0,
            days_until_next=(cal.asb_start - game_date).days,
            season_calendar=cal
        )

    if cal.asb_start <= game_date < cal.games_resume:
        return RegimeInfo(
            name='asb', label='All-Star Break',
            is_toxic=True,
            days_into_regime=(game_date - cal.asb_start).days,
            days_until_next=(cal.games_resume - game_date).days,
            season_calendar=cal
        )

    if cal.toxic_start <= game_date < cal.trade_deadline:
        return RegimeInfo(
            name='pre_deadline', label='Pre-Trade Deadline',
            is_toxic=True,
            days_into_regime=(game_date - cal.toxic_start).days,
            days_until_next=(cal.trade_deadline - game_date).days,
            season_calendar=cal
        )

    if cal.trade_deadline < game_date < cal.asb_start:
        return RegimeInfo(
            name='post_deadline', label='Post-Deadline → ASB',
            is_toxic=True,
            days_into_regime=(game_date - cal.trade_deadline).days,
            days_until_next=(cal.asb_start - game_date).days,
            season_calendar=cal
        )

    if cal.games_resume <= game_date <= cal.toxic_end:
        days_post = (game_date - cal.games_resume).days
        if days_post >= RECOVERY_DAYS:
            return RegimeInfo(
                name='recovery', label='Recovery (post-toxic)',
                is_toxic=False, days_into_regime=days_post - RECOVERY_DAYS,
                days_until_next=None, season_calendar=cal
            )
        return RegimeInfo(
            name='post_asb', label='Post-ASB (still toxic)',
            is_toxic=True, days_into_regime=days_post,
            days_until_next=RECOVERY_DAYS - days_post,
            season_calendar=cal
        )

    # Normal regime — find next toxic window
    days_until_toxic = None
    if game_date < cal.toxic_start:
        days_until_toxic = (cal.toxic_start - game_date).days

    return RegimeInfo(
        name='normal', label='Normal',
        is_toxic=False, days_into_regime=0,
        days_until_next=days_until_toxic,
        season_calendar=cal
    )
