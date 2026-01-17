"""
Pattern #1: Smart Skip Mixin

Provides source-level filtering to skip irrelevant processor invocations.

Example:
    class PlayerGameSummaryProcessor(SmartSkipMixin, AnalyticsProcessorBase):
        RELEVANT_SOURCES = {
            'nbac_gamebook_player_stats': True,
            'bdl_player_boxscores': True,
            'odds_api_spreads': False  # Not relevant to player stats
        }

When triggered by odds_api_spreads update, processor skips execution.
"""

from typing import Dict
import logging

logger = logging.getLogger(__name__)


class SmartSkipMixin:
    """
    Mixin to add smart skip pattern to processors.

    Provides source-level filtering to skip irrelevant invocations.
    """

    # Define in subclass - which sources are relevant
    # Format: {'source_table_name': True/False}
    RELEVANT_SOURCES = {}

    def should_process_source(self, source_table: str) -> bool:
        """
        Check if this source is relevant to the processor.

        Args:
            source_table: Name of the source table that triggered this run

        Returns:
            bool: True if should process, False if should skip
        """
        if not source_table:
            # No source specified - safe to process (fail open)
            return True

        if source_table not in self.RELEVANT_SOURCES:
            # Unknown source - safe to process (fail open)
            logger.info(f"Unknown source '{source_table}', processing")
            return True

        is_relevant = self.RELEVANT_SOURCES[source_table]

        if not is_relevant:
            logger.info(
                f"Skipping - {source_table} not relevant to {self.__class__.__name__}"
            )
            return False

        logger.debug(f"Source '{source_table}' is relevant, continuing")
        return True

    def run(self, opts: Dict) -> bool:
        """
        Enhanced run method with smart skip.

        Checks source relevance before delegating to parent run().
        """
        source_table = opts.get('source_table')

        # SMART SKIP: Check relevance first
        if source_table and not self.should_process_source(source_table):
            # Log the skip for monitoring
            logger.info(
                f"Smart skip: {source_table} → {self.__class__.__name__} (irrelevant)"
            )

            # Track skip in execution log if possible
            # This will write to skip_reason column in processing tables
            if hasattr(self, 'log_processing_run'):
                try:
                    # Create a minimal stats dict for logging
                    self.stats = getattr(self, 'stats', {})
                    self.stats['run_id'] = getattr(self, 'run_id', 'unknown')

                    # Log the skip
                    self.log_processing_run(
                        success=True,
                        skip_reason='irrelevant_source'
                    )
                except Exception as e:
                    logger.warning(f"Failed to log smart skip: {e}")

            return True  # Success (skipped)

        # Continue with normal processing
        return super().run(opts)
