"""Multi-window completeness checker for player daily cache.

Runs parallel completeness checks across 4 windows:
- L5: Last 5 games
- L10: Last 10 games
- L7d: Last 7 days
- L14d: Last 14 days
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Dict, List
from shared.utils.completeness_checker import CompletenessChecker

logger = logging.getLogger(__name__)


class MultiWindowCompletenessChecker:
    """Orchestrate parallel completeness checks across multiple windows."""

    # Window configurations: (name, lookback, window_type)
    WINDOWS = [
        ('L5', 5, 'games'),      # Window 1: Last 5 games
        ('L10', 10, 'games'),    # Window 2: Last 10 games
        ('L7d', 7, 'days'),      # Window 3: Last 7 days
        ('L14d', 14, 'days'),    # Window 4: Last 14 days
    ]

    def __init__(self, completeness_checker: CompletenessChecker):
        """Initialize with a CompletenessChecker instance.

        Args:
            completeness_checker: Configured CompletenessChecker instance
        """
        self.completeness_checker = completeness_checker

    def check_all_windows(
        self,
        player_ids: List[str],
        analysis_date: date,
        season_start_date: date
    ) -> Dict[str, dict]:
        """Run completeness checks for all windows in parallel.

        Uses DNP-aware mode to exclude Did Not Play games (0 minutes) from
        expected count, preventing penalization for legitimate absences.

        Args:
            player_ids: List of player IDs to check
            analysis_date: Date to check completeness for
            season_start_date: Season start date for boundary detection

        Returns:
            Dictionary mapping window names (L5, L10, L7d, L14d) to results
        """
        def run_check(window_config):
            """Helper to run single completeness check."""
            name, lookback, window_type = window_config
            return (name, self.completeness_checker.check_completeness_batch(
                entity_ids=player_ids,
                entity_type='player',
                analysis_date=analysis_date,
                upstream_table='nba_analytics.player_game_summary',
                upstream_entity_field='player_lookup',
                lookback_window=lookback,
                window_type=window_type,
                season_start_date=season_start_date,
                dnp_aware=True  # Exclude DNP games from expected count
            ))

        # Run all 4 completeness checks in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(run_check, config): config[0]
                      for config in self.WINDOWS}
            for future in as_completed(futures):
                window_name = futures[future]
                try:
                    name, result = future.result()
                    results[name] = result
                except Exception as e:
                    logger.warning(f"Completeness check for {window_name} failed: {e}")
                    results[window_name] = {}

        return results

    def check_bootstrap_and_boundary(
        self,
        analysis_date: date,
        season_start_date: date
    ) -> tuple[bool, bool]:
        """Check if in bootstrap mode or at season boundary.

        Args:
            analysis_date: Date to check
            season_start_date: Season start date

        Returns:
            Tuple of (is_bootstrap, is_season_boundary)
        """
        is_bootstrap = self.completeness_checker.is_bootstrap_mode(
            analysis_date, season_start_date
        )
        is_season_boundary = self.completeness_checker.is_season_boundary(analysis_date)
        return is_bootstrap, is_season_boundary

    @staticmethod
    def all_windows_production_ready(completeness_results: dict) -> bool:
        """Check if all windows are production ready.

        Args:
            completeness_results: Results from check_all_windows()

        Returns:
            True if all 4 windows are production ready
        """
        return all(
            completeness_results.get(window, {}).get('is_production_ready', False)
            for window, _, _ in MultiWindowCompletenessChecker.WINDOWS
        )
