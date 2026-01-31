"""
Path: data_processors/analytics/upcoming_player_game_context/player_stats.py

Player Stats Module - Performance and Fatigue Metrics

Extracted from upcoming_player_game_context_processor.py for maintainability.
Contains functions for calculating player-level statistics and metrics.
"""

import logging
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_fatigue_metrics(
    player_lookup: str,
    team_abbr: str,
    historical_data: pd.DataFrame,
    target_date: date
) -> Dict:
    """
    Calculate fatigue-related metrics.

    Args:
        player_lookup: Player identifier
        team_abbr: Player's team
        historical_data: DataFrame of historical boxscores
        target_date: Target game date

    Returns:
        Dict with fatigue metrics
    """
    if historical_data.empty:
        return {
            'days_rest': None,
            'days_rest_before_last_game': None,
            'days_since_2_plus_days_rest': None,
            'games_in_last_7_days': 0,
            'games_in_last_14_days': 0,
            'minutes_in_last_7_days': 0,
            'minutes_in_last_14_days': 0,
            'avg_minutes_per_game_last_7': None,
            'back_to_backs_last_14_days': 0,
            'avg_usage_rate_last_7_games': None,  # TODO: future
            'fourth_quarter_minutes_last_7': None,  # TODO: future
            'clutch_minutes_last_7_games': None,  # TODO: future
            'back_to_back': False
        }

    # Get most recent game date
    last_game_date = historical_data.iloc[0]['game_date']

    # Days rest
    days_rest = (target_date - last_game_date).days

    # Back-to-back (consecutive days = 1 day apart, not 0)
    # Bug fix Session 49: was days_rest == 0, but that means same-day (impossible)
    back_to_back = (days_rest == 1)

    # Games in windows (strictly before target_date, within N days)
    # Bug fix Session 50: was >= which included boundary, causing values > 7
    last_7_days = target_date - timedelta(days=7)
    last_14_days = target_date - timedelta(days=14)

    games_last_7 = historical_data[
        (historical_data['game_date'] > last_7_days) &
        (historical_data['game_date'] < target_date)
    ]
    games_last_14 = historical_data[
        (historical_data['game_date'] > last_14_days) &
        (historical_data['game_date'] < target_date)
    ]

    # Minutes totals
    minutes_last_7 = games_last_7['minutes_decimal'].sum() if 'minutes_decimal' in games_last_7.columns else 0
    minutes_last_14 = games_last_14['minutes_decimal'].sum() if 'minutes_decimal' in games_last_14.columns else 0

    # Average minutes per game
    avg_minutes_last_7 = minutes_last_7 / len(games_last_7) if len(games_last_7) > 0 else None

    # Back-to-backs in last 14 days
    back_to_backs_count = 0
    if len(games_last_14) > 1:
        dates = sorted(games_last_14['game_date'].tolist())
        for i in range(len(dates) - 1):
            if (dates[i + 1] - dates[i]).days == 1:
                back_to_backs_count += 1

    # Days rest before last game (if have at least 2 games)
    days_rest_before_last = None
    if len(historical_data) >= 2:
        second_last_date = historical_data.iloc[1]['game_date']
        days_rest_before_last = (last_game_date - second_last_date).days

    # Days since 2+ days rest
    days_since_2_plus_rest = None
    for i in range(len(historical_data) - 1):
        current_date = historical_data.iloc[i]['game_date']
        next_date = historical_data.iloc[i + 1]['game_date']
        days_diff = (current_date - next_date).days

        if days_diff >= 2:
            days_since_2_plus_rest = (target_date - current_date).days
            break

    return {
        'days_rest': days_rest,
        'days_rest_before_last_game': days_rest_before_last,
        'days_since_2_plus_days_rest': days_since_2_plus_rest,
        'games_in_last_7_days': len(games_last_7),
        'games_in_last_14_days': len(games_last_14),
        'minutes_in_last_7_days': int(minutes_last_7),
        'minutes_in_last_14_days': int(minutes_last_14),
        'avg_minutes_per_game_last_7': round(avg_minutes_last_7, 1) if avg_minutes_last_7 else None,
        'back_to_backs_last_14_days': back_to_backs_count,
        'avg_usage_rate_last_7_games': None,  # TODO: future (needs play-by-play)
        'fourth_quarter_minutes_last_7': None,  # TODO: future
        'clutch_minutes_last_7_games': None,  # TODO: future
        'back_to_back': back_to_back
    }


def calculate_performance_metrics(
    historical_data: pd.DataFrame,
    current_points_line: Optional[float] = None
) -> Dict:
    """
    Calculate recent performance metrics.

    Args:
        historical_data: DataFrame of historical boxscores
        current_points_line: Current prop line for streak calculation (optional)

    Returns:
        Dict with performance metrics
    """
    if historical_data.empty:
        return {
            'points_avg_last_5': None,
            'points_avg_last_10': None,
            'l5_games_used': 0,
            'l5_sample_quality': 'insufficient',
            'l10_games_used': 0,
            'l10_sample_quality': 'insufficient',
            'prop_over_streak': 0,
            'prop_under_streak': 0,
            'opponent_def_rating_last_10': None,
            'shooting_pct_decline_last_5': None,
            'fourth_quarter_production_last_7': None
        }

    # Points averages
    last_5 = historical_data.head(5)
    last_10 = historical_data.head(10)

    points_avg_5 = last_5['points'].mean() if len(last_5) > 0 else None
    points_avg_10 = last_10['points'].mean() if len(last_10) > 0 else None

    # Calculate prop streaks (consecutive games over/under the current line)
    prop_over_streak, prop_under_streak = calculate_prop_streaks(
        historical_data, current_points_line
    )

    # Track how many games were actually used for sample size transparency
    l5_games_used = len(last_5)
    l10_games_used = len(last_10)

    return {
        'points_avg_last_5': round(points_avg_5, 1) if points_avg_5 else None,
        'points_avg_last_10': round(points_avg_10, 1) if points_avg_10 else None,
        'l5_games_used': l5_games_used,
        'l5_sample_quality': determine_sample_quality(l5_games_used, 5),
        'l10_games_used': l10_games_used,
        'l10_sample_quality': determine_sample_quality(l10_games_used, 10),
        'prop_over_streak': prop_over_streak,
        'prop_under_streak': prop_under_streak,
        'opponent_def_rating_last_10': None,
        'shooting_pct_decline_last_5': None,
        'fourth_quarter_production_last_7': None
    }


def determine_sample_quality(games_count: int, target_window: int) -> str:
    """
    Assess sample quality relative to target window.

    Follows the same pattern as precompute/player_shot_zone_analysis.

    Args:
        games_count: Number of games in sample
        target_window: Target number of games (5 or 10)

    Returns:
        str: 'excellent', 'good', 'limited', or 'insufficient'
    """
    if games_count >= target_window:
        return 'excellent'
    elif games_count >= int(target_window * 0.7):
        return 'good'
    elif games_count >= int(target_window * 0.5):
        return 'limited'
    else:
        return 'insufficient'


def calculate_prop_streaks(
    historical_data: pd.DataFrame,
    current_points_line: Optional[float]
) -> Tuple[int, int]:
    """
    Calculate consecutive games over/under the current prop line.

    Args:
        historical_data: DataFrame of historical boxscores (sorted by most recent first)
        current_points_line: The current prop line to compare against

    Returns:
        Tuple of (over_streak, under_streak)
        - over_streak: Consecutive games scoring OVER the line (ends when player goes under)
        - under_streak: Consecutive games scoring UNDER the line (ends when player goes over)
        Only one can be non-zero at a time; if 0, the streak is broken.
    """
    # No line or no data = no streak
    if current_points_line is None or historical_data.empty:
        return 0, 0

    over_streak = 0
    under_streak = 0

    # Iterate through games (most recent first)
    for _, row in historical_data.iterrows():
        points = row.get('points')
        if points is None or pd.isna(points):
            break  # Can't compare, streak ends

        if points > current_points_line:
            if under_streak > 0:
                break  # Was on an under streak, now it's broken
            over_streak += 1
        elif points < current_points_line:
            if over_streak > 0:
                break  # Was on an over streak, now it's broken
            under_streak += 1
        else:
            # Exact match (push) - streak continues but doesn't increment
            continue

    return over_streak, under_streak


def parse_minutes(minutes_str: str) -> float:
    """
    Parse minutes string "MM:SS" to decimal.

    Args:
        minutes_str: Minutes in "MM:SS" format

    Returns:
        Decimal minutes
    """
    if not minutes_str or pd.isna(minutes_str):
        return 0.0

    try:
        if ':' in str(minutes_str):
            parts = str(minutes_str).split(':')
            minutes = int(parts[0])
            seconds = int(parts[1])
            return minutes + (seconds / 60.0)
        else:
            return float(minutes_str)
    except (ValueError, IndexError):
        logger.warning(f"Could not parse minutes: {minutes_str}")
        return 0.0
