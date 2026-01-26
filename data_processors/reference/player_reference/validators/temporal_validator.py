"""
Temporal Validator

Wraps the base class temporal ordering validation to prevent
processing earlier dates after later dates have been processed.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)


class TemporalValidator:
    """
    Validates temporal ordering of processing runs.

    Delegates to base class RegistryProcessorBase.validate_temporal_ordering()
    """

    def __init__(self, processor):
        """
        Initialize temporal validator.

        Args:
            processor: The processor instance (needs validate_temporal_ordering method)
        """
        self.processor = processor

    def validate(self, season: str, data_date: date, allow_backfill: bool = False) -> None:
        """
        Validate temporal ordering for a processing run.

        Args:
            season: Season string (e.g., "2024-2025")
            data_date: Date being processed
            allow_backfill: If True, allow processing earlier dates (insert-only mode)

        Raises:
            TemporalOrderingError: If temporal ordering is violated
        """
        self.processor.validate_temporal_ordering(
            season=season,
            data_date=data_date,
            allow_backfill=allow_backfill
        )
