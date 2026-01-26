#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/calculators/completeness_checker_helper.py

Completeness Checker Helper - Batch completeness checking for multiple windows.

This module runs completeness checks across multiple time windows in parallel:
- L5 games (last 5 games)
- L10 games (last 10 games)
- L7 days (last 7 calendar days)
- L14 days (last 14 calendar days)
- L30 days (last 30 calendar days)
"""

import logging
import time
from datetime import date
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

from shared.utils.completeness_checker import CompletenessChecker

logger = logging.getLogger(__name__)


class CompletenessCheckerHelper:
    """Helper for running batch completeness checks across multiple windows."""

    def __init__(self, completeness_checker: CompletenessChecker):
        """
        Initialize completeness checker helper.

        Args:
            completeness_checker: CompletenessChecker instance
        """
        self.completeness_checker = completeness_checker

    def run_batch_completeness_checks(
        self,
        player_lookups: List[str],
        target_date: date,
        season_start_date: date
    ) -> Tuple[Dict, Dict, Dict, Dict, Dict, bool, bool]:
        """
        Run completeness checks for all 5 windows in parallel.

        Args:
            player_lookups: List of player lookup keys
            target_date: Analysis date
            season_start_date: Season start date (for bootstrap mode detection)

        Returns:
            Tuple of:
            - comp_l5: L5 games completeness results
            - comp_l10: L10 games completeness results
            - comp_l7d: L7 days completeness results
            - comp_l14d: L14 days completeness results
            - comp_l30d: L30 days completeness results
            - is_bootstrap: Whether in bootstrap mode
            - is_season_boundary: Whether at season boundary

        Raises:
            GoogleAPIError: If BigQuery operations fail
            ValueError: If data validation fails
        """
        logger.info(f"Checking completeness for {len(player_lookups)} players across 5 windows...")

        completeness_start = time.time()

        # Define all completeness check configurations
        completeness_windows = [
            ('l5', 5, 'games'),      # Window 1: L5 games
            ('l10', 10, 'games'),    # Window 2: L10 games
            ('l7d', 7, 'days'),      # Window 3: L7 days
            ('l14d', 14, 'days'),    # Window 4: L14 days
            ('l30d', 30, 'days'),    # Window 5: L30 days
        ]

        # Helper function to run single completeness check
        def run_completeness_check(window_config):
            name, lookback, window_type = window_config
            return (name, self.completeness_checker.check_completeness_batch(
                entity_ids=list(player_lookups),
                entity_type='player',
                analysis_date=target_date,
                upstream_table='nba_raw.bdl_player_boxscores',
                upstream_entity_field='player_lookup',
                lookback_window=lookback,
                window_type=window_type,
                season_start_date=season_start_date,
                dnp_aware=True
            ))

        # Run all 5 completeness checks in parallel
        completeness_results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(run_completeness_check, config): config[0]
                      for config in completeness_windows}
            for future in as_completed(futures):
                window_name = futures[future]
                try:
                    name, result = future.result()
                    completeness_results[name] = result
                except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                    logger.warning(f"BigQuery error in completeness check for {window_name}: {e}")
                    completeness_results[window_name] = {}
                except (KeyError, AttributeError, TypeError, ValueError) as e:
                    logger.warning(f"Data error in completeness check for {window_name}: {e}")
                    completeness_results[window_name] = {}

        # Extract results with defaults
        comp_l5 = completeness_results.get('l5', {})
        comp_l10 = completeness_results.get('l10', {})
        comp_l7d = completeness_results.get('l7d', {})
        comp_l14d = completeness_results.get('l14d', {})
        comp_l30d = completeness_results.get('l30d', {})

        # Check bootstrap mode
        is_bootstrap = self.completeness_checker.is_bootstrap_mode(
            target_date, season_start_date
        )
        is_season_boundary = self.completeness_checker.is_season_boundary(target_date)

        completeness_elapsed = time.time() - completeness_start
        logger.info(
            f"Completeness check complete in {completeness_elapsed:.1f}s (5 windows, parallel). "
            f"Bootstrap mode: {is_bootstrap}, Season boundary: {is_season_boundary}"
        )

        return comp_l5, comp_l10, comp_l7d, comp_l14d, comp_l30d, is_bootstrap, is_season_boundary
