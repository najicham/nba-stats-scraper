"""
Temporal ordering and date validation for precompute processors.

Provides date normalization, early season detection, and temporal validation
for Phase 4 precompute processors.

Version: 1.0
Created: 2026-01-25
"""

import logging
from datetime import date, datetime
from typing import Dict, Optional

# Import season date utilities for early season detection
try:
    from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
    SEASON_UTILS_AVAILABLE = True
except ImportError:
    SEASON_UTILS_AVAILABLE = False
    is_early_season = None
    get_season_year_from_date = None

logger = logging.getLogger(__name__)


class TemporalMixin:
    """
    Temporal ordering and date validation for precompute processors.

    Handles date normalization, early season detection, and temporal constraints
    for historical data processing.

    Requires from base class:
    - self.opts: Processing options dict
    - self.stats: Statistics dictionary
    """

    def _normalize_analysis_date(self) -> None:
        """
        Normalize analysis_date from string to date object.

        Converts string dates to proper date objects early in processing
        to ensure all processors receive consistent date types.

        Updates self.opts['analysis_date'] in place.
        """
        if 'analysis_date' in self.opts and isinstance(self.opts['analysis_date'], str):
            self.opts['analysis_date'] = date.fromisoformat(self.opts['analysis_date'])
            logger.debug(f"Normalized analysis_date to date object: {self.opts['analysis_date']}")

    def _check_early_season(self, analysis_date: date, dep_check: Optional[Dict] = None) -> bool:
        """
        Check if the analysis date falls within the early season period.

        Early season is typically the first 14 days when data may be sparse
        or missing. This helps distinguish expected failures from real errors.

        Args:
            analysis_date: Date to check
            dep_check: Optional dependency check result to update with early season flag

        Returns:
            bool: True if early season period, False otherwise
        """
        if not SEASON_UTILS_AVAILABLE:
            logger.debug("Season utils not available - skipping early season check")
            return False

        try:
            season_year = get_season_year_from_date(analysis_date)
            early_season = is_early_season(analysis_date, season_year, days_threshold=14)

            if early_season and dep_check:
                dep_check['is_early_season'] = True
                dep_check['early_season_reason'] = f'bootstrap_period_first_14_days_of_season_{season_year}'
                logger.info(f"Early season detected for {analysis_date} (season {season_year})")

            return early_season
        except Exception as e:
            logger.debug(f"Could not determine early season status: {e}")
            return False

    def _handle_early_season_skip(self, reason: str) -> None:
        """
        Record early season skip decision in stats.

        When processing is skipped due to early season conditions,
        this method records the decision for audit trail.

        Args:
            reason: Reason for skipping (e.g., 'early_season_missing_deps')
        """
        logger.info(f"Early season skip: {reason}")
        self.stats['processing_decision'] = 'skipped_early_season'
        self.stats['processing_decision_reason'] = reason

    def _convert_date_for_bigquery(self, date_obj: Optional[date]) -> Optional[str]:
        """
        Convert date object to BigQuery DATE string format.

        Args:
            date_obj: Date object to convert (or None)

        Returns:
            ISO format date string (YYYY-MM-DD) or None
        """
        if date_obj is None:
            return None

        if hasattr(date_obj, 'isoformat'):
            return date_obj.isoformat()

        return str(date_obj)

    def _parse_date_string(self, date_str: str) -> date:
        """
        Parse date string to date object.

        Handles both ISO format (YYYY-MM-DD) and datetime strings.

        Args:
            date_str: Date string to parse

        Returns:
            date object

        Raises:
            ValueError: If date string format is invalid
        """
        if isinstance(date_str, date):
            return date_str

        try:
            # Try ISO format first (YYYY-MM-DD)
            return date.fromisoformat(date_str)
        except (ValueError, AttributeError):
            # Fall back to datetime parsing
            try:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError as e:
                raise ValueError(f"Invalid date format: {date_str}") from e
