"""
Window Completeness Validator
==============================

Focused validator for rolling window calculations.

Verifies N games exist before computing last-N average to prevent
contaminated rolling statistics from incomplete data windows.

Decision Logic:
- 100% complete: compute normally
- 70-99% complete: compute but flag as incomplete
- <70% complete: return NULL, don't compute

Usage:
    validator = WindowCompletenessValidator(completeness_checker)

    # Check multiple windows for a player
    window_results = validator.check_player_windows(
        player_id='lebron_james',
        game_date=date(2026, 1, 26),
        window_sizes=[5, 10, 15, 20]
    )

    # Partition players into computable vs skip
    computable, skip = validator.get_computable_players(
        player_ids=['lebron_james', 'stephen_curry'],
        game_date=date(2026, 1, 26),
        window_size=10
    )

Created: 2026-01-26
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Tuple, Optional

from shared.utils.completeness_checker import CompletenessChecker

logger = logging.getLogger(__name__)


@dataclass
class WindowResult:
    """Result from window completeness check."""
    is_complete: bool
    completeness_ratio: float  # 0-1 scale
    games_available: int
    games_required: int
    recommendation: str  # 'compute', 'compute_with_flag', 'skip'
    dnp_count: int = 0  # DNP games excluded from expected
    gap_classification: str = 'NO_GAP'  # NO_GAP | DATA_GAP | NAME_UNRESOLVED


class WindowCompletenessValidator:
    """
    Validates rolling window completeness before computation.

    Prevents contaminated rolling averages by checking data availability
    before computing last-N statistics.

    Decision Thresholds:
    - compute_threshold: 0.7 (70%) - Below this, return NULL
    - flag_threshold: 1.0 (100%) - Below this, flag as incomplete
    """

    def __init__(
        self,
        completeness_checker: CompletenessChecker,
        compute_threshold: float = 0.7,
        upstream_table: str = 'nba_analytics.player_game_summary',
        upstream_entity_field: str = 'player_lookup'
    ):
        """
        Initialize window validator.

        Args:
            completeness_checker: CompletenessChecker instance
            compute_threshold: Minimum completeness to compute (0-1 scale)
            upstream_table: Upstream table to check
            upstream_entity_field: Entity field in upstream table
        """
        self.checker = completeness_checker
        self.compute_threshold = compute_threshold
        self.upstream_table = upstream_table
        self.upstream_entity_field = upstream_entity_field

    def check_player_windows(
        self,
        player_id: str,
        game_date: date,
        window_sizes: List[int] = [5, 10, 15, 20],
        season_start_date: Optional[date] = None
    ) -> Dict[int, WindowResult]:
        """
        Check completeness for multiple window sizes for a single player.

        Args:
            player_id: Player lookup ID
            game_date: Date being processed
            window_sizes: List of window sizes to check
            season_start_date: Season start date for completeness check

        Returns:
            Dict mapping window_size to WindowResult
        """
        results = {}

        for window_size in window_sizes:
            try:
                # Check completeness with DNP awareness
                completeness = self.checker.check_completeness_batch(
                    entity_ids=[player_id],
                    entity_type='player',
                    analysis_date=game_date,
                    upstream_table=self.upstream_table,
                    upstream_entity_field=self.upstream_entity_field,
                    lookback_window=window_size,
                    window_type='games',
                    season_start_date=season_start_date,
                    fail_on_incomplete=False,
                    dnp_aware=True  # Exclude DNP games from expected count
                )

                if player_id in completeness:
                    metrics = completeness[player_id]
                    completeness_ratio = metrics['completeness_pct'] / 100.0

                    # Determine recommendation
                    if completeness_ratio < self.compute_threshold:
                        recommendation = 'skip'
                    elif completeness_ratio < 1.0:
                        recommendation = 'compute_with_flag'
                    else:
                        recommendation = 'compute'

                    results[window_size] = WindowResult(
                        is_complete=metrics['is_complete'],
                        completeness_ratio=completeness_ratio,
                        games_available=metrics['actual_count'],
                        games_required=metrics['expected_count'] - metrics.get('dnp_count', 0),
                        recommendation=recommendation,
                        dnp_count=metrics.get('dnp_count', 0),
                        gap_classification=metrics.get('gap_classification', 'NO_GAP')
                    )
                else:
                    # No data for player
                    results[window_size] = WindowResult(
                        is_complete=False,
                        completeness_ratio=0.0,
                        games_available=0,
                        games_required=window_size,
                        recommendation='skip'
                    )

            except Exception as e:
                logger.error(f"Error checking window {window_size} for {player_id}: {e}", exc_info=True)
                results[window_size] = WindowResult(
                    is_complete=False,
                    completeness_ratio=0.0,
                    games_available=0,
                    games_required=window_size,
                    recommendation='skip'
                )

        return results

    def get_computable_players(
        self,
        player_ids: List[str],
        game_date: date,
        window_size: int,
        season_start_date: Optional[date] = None
    ) -> Tuple[List[str], List[str]]:
        """
        Partition players into computable vs skip based on window completeness.

        Args:
            player_ids: List of player IDs to check
            game_date: Date being processed
            window_size: Window size to check
            season_start_date: Season start date

        Returns:
            Tuple of (computable_ids, skip_ids)
        """
        computable = []
        skip = []

        try:
            # Batch check completeness for all players
            completeness_results = self.checker.check_completeness_batch(
                entity_ids=player_ids,
                entity_type='player',
                analysis_date=game_date,
                upstream_table=self.upstream_table,
                upstream_entity_field=self.upstream_entity_field,
                lookback_window=window_size,
                window_type='games',
                season_start_date=season_start_date,
                fail_on_incomplete=False,
                dnp_aware=True
            )

            for player_id in player_ids:
                if player_id in completeness_results:
                    metrics = completeness_results[player_id]
                    completeness_ratio = metrics['completeness_pct'] / 100.0

                    if completeness_ratio >= self.compute_threshold:
                        computable.append(player_id)
                    else:
                        skip.append(player_id)
                else:
                    # No data for player
                    skip.append(player_id)

        except Exception as e:
            logger.error(f"Error in get_computable_players: {e}", exc_info=True)
            # On error, skip all players to be safe
            skip = player_ids

        logger.info(
            f"Window {window_size} completeness: {len(computable)} computable, "
            f"{len(skip)} skip (threshold={self.compute_threshold:.0%})"
        )

        return computable, skip

    def check_batch_windows(
        self,
        player_ids: List[str],
        game_date: date,
        window_sizes: List[int] = [5, 10, 15, 20],
        season_start_date: Optional[date] = None
    ) -> Dict[str, Dict[int, WindowResult]]:
        """
        Check completeness for multiple players and window sizes efficiently.

        Args:
            player_ids: List of player IDs to check
            game_date: Date being processed
            window_sizes: List of window sizes to check
            season_start_date: Season start date

        Returns:
            Dict mapping player_id -> window_size -> WindowResult
        """
        results = {}

        for player_id in player_ids:
            results[player_id] = self.check_player_windows(
                player_id=player_id,
                game_date=game_date,
                window_sizes=window_sizes,
                season_start_date=season_start_date
            )

        return results

    def get_window_quality_summary(
        self,
        window_results: Dict[int, WindowResult]
    ) -> Dict:
        """
        Generate quality summary from window results.

        Args:
            window_results: Dict of window_size -> WindowResult

        Returns:
            Summary dict with aggregate quality metrics
        """
        if not window_results:
            return {
                'min_completeness': 0.0,
                'max_completeness': 0.0,
                'avg_completeness': 0.0,
                'computable_windows': 0,
                'total_windows': 0,
                'all_complete': False
            }

        completeness_values = [r.completeness_ratio for r in window_results.values()]
        computable_count = sum(1 for r in window_results.values() if r.recommendation != 'skip')

        return {
            'min_completeness': min(completeness_values),
            'max_completeness': max(completeness_values),
            'avg_completeness': sum(completeness_values) / len(completeness_values),
            'computable_windows': computable_count,
            'total_windows': len(window_results),
            'all_complete': all(r.is_complete for r in window_results.values()),
            'dnp_games': sum(r.dnp_count for r in window_results.values())
        }

    def should_compute_window(
        self,
        player_id: str,
        game_date: date,
        window_size: int,
        season_start_date: Optional[date] = None
    ) -> Tuple[bool, Optional[WindowResult]]:
        """
        Quick check if a window should be computed for a player.

        Args:
            player_id: Player lookup ID
            game_date: Date being processed
            window_size: Window size to check
            season_start_date: Season start date

        Returns:
            Tuple of (should_compute: bool, result: WindowResult)
        """
        window_results = self.check_player_windows(
            player_id=player_id,
            game_date=game_date,
            window_sizes=[window_size],
            season_start_date=season_start_date
        )

        if window_size in window_results:
            result = window_results[window_size]
            should_compute = result.recommendation != 'skip'
            return should_compute, result
        else:
            return False, None
