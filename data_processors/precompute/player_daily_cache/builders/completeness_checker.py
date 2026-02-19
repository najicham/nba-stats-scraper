"""Multi-window completeness checker for player daily cache.

Runs parallel completeness checks across 4 windows:
- L5: Last 5 games
- L10: Last 10 games
- L7d: Last 7 days (extended after multi-day breaks)
- L14d: Last 14 days (extended after multi-day breaks)
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Dict, List
from shared.utils.completeness_checker import CompletenessChecker

logger = logging.getLogger(__name__)


class MultiWindowCompletenessChecker:
    """Orchestrate parallel completeness checks across multiple windows."""

    # Baseline window configurations: (name, lookback, window_type)
    # Note: L7d and L14d lookbacks are extended dynamically after multi-day breaks.
    # See check_all_windows() for adaptive lookback logic.
    WINDOWS = [
        ('L5', 5, 'games'),      # Window 1: Last 5 games
        ('L10', 10, 'games'),    # Window 2: Last 10 games
        ('L7d', 7, 'days'),      # Window 3: Last 7 days (baseline; extended post-break)
        ('L14d', 14, 'days'),    # Window 4: Last 14 days (baseline; extended post-break)
    ]

    def __init__(self, completeness_checker: CompletenessChecker):
        """Initialize with a CompletenessChecker instance.

        Args:
            completeness_checker: Configured CompletenessChecker instance
        """
        self.completeness_checker = completeness_checker

    @staticmethod
    def _detect_break_days(game_date: date, bq_client) -> int:
        """Return the number of consecutive no-game calendar days immediately before game_date.

        Uses a single BQ query to find the most recent regular-season game day
        within the 30 days before game_date. Returns 0 on any error (fail-open).

        Examples:
            ASB (Feb 13-19, return Feb 19): returns 6 (Feb 13 was last game day)
            Normal back-to-back game day: returns 0

        Args:
            game_date: The date being processed (cache_date / analysis_date)
            bq_client: BigQuery client for schedule lookup

        Returns:
            Number of consecutive no-game days before game_date (0 on normal game days)
        """
        try:
            window_start = (game_date - timedelta(days=30)).isoformat()
            window_end = (game_date - timedelta(days=1)).isoformat()
            query = f"""
            SELECT MAX(game_date) as last_game_date
            FROM `nba-props-platform.nba_reference.nba_schedule`
            WHERE game_date BETWEEN '{window_start}' AND '{window_end}'
              AND (game_id LIKE '002%' OR game_id LIKE '004%')
            """
            result = list(bq_client.query(query).result())
            if not result or result[0].last_game_date is None:
                return 0
            last_game_date = result[0].last_game_date
            # Handle BigQuery DATE vs datetime.date
            if hasattr(last_game_date, 'date'):
                last_game_date = last_game_date.date()
            break_days = (game_date - last_game_date).days - 1
            return max(0, break_days)
        except Exception as e:
            logger.warning(f"Break detection failed for {game_date}, assuming no break: {e}")
            return 0

    def check_all_windows(
        self,
        player_ids: List[str],
        analysis_date: date,
        season_start_date: date
    ) -> Dict[str, dict]:
        """Run completeness checks for all windows in parallel.

        Uses DNP-aware mode to exclude Did Not Play games (0 minutes) from
        expected count, preventing penalization for legitimate absences.

        After multi-day breaks (e.g. All-Star break, Christmas), the day-based
        windows (L7d, L14d) are extended by the number of break days so that
        pre-break game data is found and cache entries are populated with real
        values rather than nulls/zeros.

        Args:
            player_ids: List of player IDs to check
            analysis_date: Date to check completeness for
            season_start_date: Season start date for boundary detection

        Returns:
            Dictionary mapping window names (L5, L10, L7d, L14d) to results
        """
        # Detect multi-day break and extend day-based windows accordingly.
        # Only activates when break_days > 0; normal season behavior is unchanged.
        break_days = self._detect_break_days(analysis_date, self.completeness_checker.bq_client)
        if break_days > 0:
            logger.info(
                f"Post-break detected: {break_days} consecutive no-game day(s) before "
                f"{analysis_date}. Extending L7d: 7→{7 + break_days} days, "
                f"L14d: 14→{14 + break_days} days."
            )

        effective_windows = [
            ('L5', 5, 'games'),
            ('L10', 10, 'games'),
            ('L7d', 7 + break_days, 'days'),
            ('L14d', 14 + break_days, 'days'),
        ]

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
                      for config in effective_windows}
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
