# File: shared/validation/historical_completeness.py
"""
Historical Completeness Tracking for ML Feature Pipeline.

This module provides utilities for tracking whether rolling window calculations
(like last-10-game averages) had all required historical data.

IMPORTANT DISTINCTION:
- "Schedule completeness" (existing): "Did we get today's games from upstream?"
- "Historical completeness" (this module): "Did rolling windows have all required data?"

Use Cases:
1. Detect features calculated with incomplete data (biased rolling averages)
2. Enable cascade detection: Which features need reprocessing after a backfill?
3. Distinguish bootstrap (new player/early season) from actual data gaps

Created: January 2026
Architecture: Data Cascade Architecture Project
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict, Any


# Configuration
WINDOW_SIZE = 10  # Target number of games for rolling averages
MINIMUM_GAMES_THRESHOLD = 5  # Below this, don't generate features (too sparse)


@dataclass
class HistoricalCompletenessResult:
    """
    Result of historical completeness assessment for a single feature record.

    Attributes:
        games_found: Number of games actually retrieved from player_game_summary
        games_expected: Number of games player could have (min of available, window_size)
        is_complete: True if games_found >= games_expected (have all required data)
        is_bootstrap: True if games_expected < window_size (player has limited history)
        contributing_game_dates: Dates of games used in calculation (for cascade detection)
    """
    games_found: int
    games_expected: int
    is_complete: bool
    is_bootstrap: bool
    contributing_game_dates: List[date] = field(default_factory=list)

    def to_bq_struct(self) -> Dict[str, Any]:
        """
        Convert to BigQuery STRUCT format for storage.

        Returns:
            Dict matching the historical_completeness STRUCT schema.
        """
        return {
            'games_found': self.games_found,
            'games_expected': self.games_expected,
            'is_complete': self.is_complete,
            'is_bootstrap': self.is_bootstrap,
            'contributing_game_dates': [
                d.isoformat() if isinstance(d, date) else str(d)
                for d in self.contributing_game_dates
            ]
        }

    @property
    def games_missing(self) -> int:
        """Number of games missing from the rolling window."""
        return max(0, self.games_expected - self.games_found)

    @property
    def completeness_pct(self) -> float:
        """Completeness percentage (0-100)."""
        if self.games_expected == 0:
            return 100.0  # No games expected = complete
        return min(100.0, (self.games_found / self.games_expected) * 100)

    @property
    def is_data_gap(self) -> bool:
        """True if this is an actual data gap (incomplete AND not bootstrap)."""
        return not self.is_complete and not self.is_bootstrap

    def __str__(self) -> str:
        status = "COMPLETE" if self.is_complete else ("BOOTSTRAP" if self.is_bootstrap else "INCOMPLETE")
        return f"HistoricalCompleteness({self.games_found}/{self.games_expected} games, {status})"


def assess_historical_completeness(
    games_found: int,
    games_available: int,
    contributing_dates: Optional[List[date]] = None,
    window_size: int = WINDOW_SIZE
) -> HistoricalCompletenessResult:
    """
    Assess historical completeness for a player's feature calculation.

    This is the main entry point for completeness assessment.

    Args:
        games_found: Actual number of games retrieved from player_game_summary
        games_available: Total games available for this player in the lookback window
        contributing_dates: List of game dates that were used in the calculation
        window_size: Target window size (default: 10 games)

    Returns:
        HistoricalCompletenessResult with all completeness metadata

    Examples:
        >>> # Normal complete case: veteran with 10 games
        >>> assess_historical_completeness(10, 50)
        HistoricalCompleteness(10/10 games, COMPLETE)

        >>> # Data gap: should have 10 but only got 8
        >>> assess_historical_completeness(8, 50)
        HistoricalCompleteness(8/10 games, INCOMPLETE)

        >>> # Bootstrap: new player with only 5 games total
        >>> assess_historical_completeness(5, 5)
        HistoricalCompleteness(5/5 games, COMPLETE)  # is_bootstrap=True

        >>> # New player with zero games
        >>> assess_historical_completeness(0, 0)
        HistoricalCompleteness(0/0 games, COMPLETE)  # is_bootstrap=True
    """
    # Calculate expected games (capped at window size)
    games_expected = min(games_available, window_size)

    # Determine completeness
    is_complete = games_found >= games_expected

    # Bootstrap = player has fewer games available than window size
    # This is NOT a data gap - it's expected for new players / early season
    is_bootstrap = games_expected < window_size

    return HistoricalCompletenessResult(
        games_found=games_found,
        games_expected=games_expected,
        is_complete=is_complete,
        is_bootstrap=is_bootstrap,
        contributing_game_dates=contributing_dates or []
    )


def should_skip_feature_generation(games_found: int, minimum_threshold: int = MINIMUM_GAMES_THRESHOLD) -> bool:
    """
    Determine if feature generation should be skipped due to insufficient data.

    Args:
        games_found: Number of games actually found
        minimum_threshold: Minimum games required (default: 5)

    Returns:
        True if feature should be skipped (too sparse)
    """
    return games_found < minimum_threshold


def find_features_affected_by_backfill(
    backfilled_date: date,
    forward_window_days: int = 21
) -> str:
    """
    Generate SQL to find features affected by backfilling a specific date.

    After backfilling data for a date, features that used that date in their
    rolling window need to be reprocessed.

    Args:
        backfilled_date: The date that was backfilled
        forward_window_days: How many days forward to look (default: 21, ~3 weeks)

    Returns:
        SQL query string to find affected features
    """
    return f"""
    -- Find features affected by backfilling {backfilled_date}
    -- These features used {backfilled_date} in their rolling window calculation

    SELECT
        game_date,
        player_lookup,
        historical_completeness.games_found,
        historical_completeness.games_expected,
        historical_completeness.is_complete
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE DATE('{backfilled_date}') IN UNNEST(historical_completeness.contributing_game_dates)
      AND game_date > DATE('{backfilled_date}')
      AND game_date <= DATE_ADD(DATE('{backfilled_date}'), INTERVAL {forward_window_days} DAY)
    ORDER BY game_date, player_lookup
    """


def find_incomplete_features_for_date_range(
    start_date: date,
    end_date: date
) -> str:
    """
    Generate SQL to find incomplete features in a date range.

    Useful for finding features that might benefit from a backfill.

    Args:
        start_date: Start of date range
        end_date: End of date range

    Returns:
        SQL query string to find incomplete features
    """
    return f"""
    -- Find incomplete features (not bootstrap) in date range
    -- These have actual data gaps that a backfill might fix

    SELECT
        game_date,
        player_lookup,
        historical_completeness.games_found,
        historical_completeness.games_expected,
        historical_completeness.games_expected - historical_completeness.games_found as games_missing
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN DATE('{start_date}') AND DATE('{end_date}')
      AND NOT historical_completeness.is_complete
      AND NOT historical_completeness.is_bootstrap
    ORDER BY game_date DESC, games_missing DESC
    """


def get_daily_completeness_summary_sql(days_back: int = 30) -> str:
    """
    Generate SQL for daily completeness summary.

    Args:
        days_back: Number of days to look back (default: 30)

    Returns:
        SQL query string for daily summary
    """
    return f"""
    -- Daily historical completeness summary (last {days_back} days)

    SELECT
        game_date,
        COUNT(*) as total_features,
        COUNTIF(historical_completeness.is_complete) as complete,
        COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) as incomplete,
        COUNTIF(historical_completeness.is_bootstrap) as bootstrap,
        ROUND(COUNTIF(historical_completeness.is_complete) / COUNT(*) * 100, 1) as complete_pct
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
      AND historical_completeness IS NOT NULL
    GROUP BY game_date
    ORDER BY game_date DESC
    """
