"""
Path: data_processors/analytics/upcoming_player_game_context/travel_context.py

Travel Context Module - Distance and Timezone Calculations

Extracted from upcoming_player_game_context_processor.py for maintainability.
Contains functions for calculating travel-related context metrics.
"""

import logging
from datetime import date, datetime
from typing import Dict, Optional

from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

logger = logging.getLogger(__name__)


class TravelContextCalculator:
    """
    Calculator for travel-related context metrics.

    Uses NBATravel utility to get distance and timezone data for teams.
    Caches results to avoid repeated lookups for the same team/date.
    """

    def __init__(self, project_id: str):
        """
        Initialize the calculator.

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        self._travel_utils = None  # Lazy-loaded
        self._team_travel_cache: Dict[str, Dict] = {}

    def _get_travel_utils(self):
        """Lazy-load travel utilities."""
        if self._travel_utils is None:
            from data_processors.analytics.utils.travel_utils import NBATravel
            self._travel_utils = NBATravel(self.project_id)
        return self._travel_utils

    def calculate_travel_context(
        self,
        team_abbr: str,
        target_date: date,
        game_info: Dict
    ) -> Dict:
        """
        Calculate travel-related context metrics for the team.

        Uses NBATravel utility to get distance and timezone data.

        Args:
            team_abbr: Team abbreviation
            target_date: Target game date
            game_info: Dict with game info including home/away status

        Returns:
            Dict with travel metrics
        """
        default_metrics = {
            'travel_miles': None,
            'time_zone_changes': None,
            'consecutive_road_games': None,
            'miles_traveled_last_14_days': None,
            'time_zones_crossed_last_14_days': None,
        }

        try:
            # Check cache first
            cache_key = f"{team_abbr}_{target_date}"
            if cache_key in self._team_travel_cache:
                return self._team_travel_cache[cache_key]

            # Get travel utilities
            travel_utils = self._get_travel_utils()

            # Get 14-day travel metrics
            travel_14d = travel_utils.get_travel_last_n_days(
                team_abbr=team_abbr,
                current_date=datetime.combine(target_date, datetime.min.time()),
                days=14
            )

            if travel_14d:
                metrics = {
                    'travel_miles': None,  # Single game travel TBD
                    'time_zone_changes': None,  # Single game TZ TBD
                    'consecutive_road_games': travel_14d.get('consecutive_away_games', 0),
                    'miles_traveled_last_14_days': travel_14d.get('miles_traveled', 0),
                    'time_zones_crossed_last_14_days': travel_14d.get('time_zones_crossed', 0),
                }
            else:
                metrics = default_metrics

            # Cache result
            self._team_travel_cache[cache_key] = metrics
            return metrics

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.debug(f"BigQuery error calculating travel context for {team_abbr}: {e}")
            return default_metrics
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Data error calculating travel context for {team_abbr}: {e}")
            return default_metrics
        except ImportError as e:
            logger.warning(f"Could not import travel_utils: {e}")
            return default_metrics

    def clear_cache(self):
        """Clear the travel cache."""
        self._team_travel_cache.clear()
