"""
Failure Tracking Mixin for Precompute Processors

Extracted from precompute_base.py to separate failure tracking logic.

Provides methods for:
- Recording entity processing failures with classification
- Classifying failures (PLAYER_DNP vs DATA_GAP)
- Saving failures to BigQuery

Version: 1.0
Created: 2026-01-25 - Extracted from precompute_base.py
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

# Configure logging
logger = logging.getLogger("failure_tracking_mixin")


class FailureTrackingMixin:
    """
    Mixin for tracking and persisting processing failures in precompute processors.

    This mixin provides:
    1. Entity failure recording - for data quality/completeness issues
    2. DNP classification - distinguishing player DNP from data gaps
    3. BigQuery persistence - saving failures for monitoring/reprocessing

    Required Dependencies (from base class):
    ---------------------------------------
    The base class must provide these attributes:

    - self.bq_client: BigQuery client instance
    - self.project_id: GCP project ID string
    - self.failed_entities: List for tracking entity failures
    - self.opts: Dict of processing options (must contain analysis_date)
    - self.run_id: String run identifier
    - self.completeness_checker: CompletenessChecker instance (optional, for DNP classification)
    - self.__class__.__name__: Processor name string

    Usage Example:
    -------------
    class MyPrecomputeProcessor(FailureTrackingMixin, PrecomputeProcessorBase):
        def calculate_precompute(self):
            # ... processing logic ...

            # Record an entity failure (incomplete data)
            if len(player_games) < expected_games:
                self.record_failure(
                    entity_id='zachlavine',
                    entity_type='PLAYER',
                    category='INCOMPLETE_DATA',
                    reason='Missing 2 games in lookback window',
                    can_retry=True,
                    expected_count=5,
                    actual_count=3
                )

        def finalize(self):
            # Save failures at the end
            self.save_failures_to_bq()
            super().finalize()
    """

    def classify_recorded_failures(self, analysis_date=None) -> int:
        """
        Enrich INCOMPLETE_DATA failures with DNP vs DATA_GAP classification.

        This method should be called after processing but before save_failures_to_bq().
        It queries expected vs actual game dates for each failed player entity and
        determines if the failure is due to:
        - PLAYER_DNP: Player didn't play (expected, not correctable)
        - DATA_GAP: Player played but data is missing (correctable)
        - MIXED: Some games DNP, some gaps
        - INSUFFICIENT_HISTORY: Early season, not enough games yet

        Only processes INCOMPLETE_DATA failures for player entities.
        Team-based failures (TDZA) are skipped since teams always play their games.

        Args:
            analysis_date: Date being analyzed. If None, uses self.opts['analysis_date']

        Returns:
            int: Number of failures that were classified

        Example:
            # In processor, after completeness checks:
            num_classified = self.classify_recorded_failures()
            logger.info(f"Classified {num_classified} failures")
            self.save_failures_to_bq()
        """
        if not self.failed_entities:
            return 0

        # Get analysis date
        if analysis_date is None:
            analysis_date = self.opts.get('analysis_date')
        if hasattr(analysis_date, 'isoformat'):
            pass  # Already a date object
        elif isinstance(analysis_date, str):
            from datetime import datetime
            analysis_date = datetime.strptime(analysis_date, '%Y-%m-%d').date()

        if not analysis_date:
            logger.warning("classify_recorded_failures: No analysis_date available")
            return 0

        # Check if this is a player-based processor (not team-based like TDZA)
        processor_name = self.__class__.__name__
        is_player_processor = any(x in processor_name.lower() for x in ['player', 'pdc', 'pcf', 'psza', 'mlfs'])

        if not is_player_processor:
            logger.debug(f"Skipping failure classification for non-player processor: {processor_name}")
            return 0

        # Find INCOMPLETE_DATA failures that need classification
        failures_to_classify = []
        for i, failure in enumerate(self.failed_entities):
            if failure.get('category') == 'INCOMPLETE_DATA':
                if 'failure_type' not in failure:  # Not already classified
                    failures_to_classify.append((i, failure))

        if not failures_to_classify:
            return 0

        try:
            # Get completeness checker
            if not hasattr(self, 'completeness_checker') or self.completeness_checker is None:
                from shared.utils.completeness_checker import CompletenessChecker
                self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

            # Batch get game dates for all failed players
            player_lookups = [f.get('entity_id') for _, f in failures_to_classify if f.get('entity_id')]

            if not player_lookups:
                return 0

            # Get expected and actual game dates for all failed players
            game_dates_batch = self.completeness_checker.get_player_game_dates_batch(
                player_lookups=player_lookups,
                analysis_date=analysis_date,
                lookback_days=14  # Standard L14 lookback
            )

            classified_count = 0
            for idx, failure in failures_to_classify:
                entity_id = failure.get('entity_id')
                if not entity_id:
                    continue

                # Normalize to match batch results
                from shared.utils.player_name_normalizer import normalize_name_for_lookup
                normalized_id = normalize_name_for_lookup(entity_id)

                game_dates = game_dates_batch.get(normalized_id, {})
                if game_dates.get('error'):
                    continue

                expected_games = game_dates.get('expected_games', [])
                actual_games = game_dates.get('actual_games', [])

                if not expected_games:
                    # Can't classify without expected games
                    continue

                # Classify the failure
                classification = self.completeness_checker.classify_failure(
                    player_lookup=entity_id,
                    analysis_date=analysis_date,
                    expected_games=expected_games,
                    actual_games=actual_games,
                    check_raw_data=True
                )

                # Update the failure record with classification data
                self.failed_entities[idx].update({
                    'failure_type': classification['failure_type'],
                    'is_correctable': classification['is_correctable'],
                    'expected_count': classification['expected_count'],
                    'actual_count': classification['actual_count'],
                    'missing_dates': classification['missing_dates'],
                    'raw_data_checked': classification['raw_data_checked']
                })
                classified_count += 1

            logger.info(
                f"Classified {classified_count}/{len(failures_to_classify)} "
                f"INCOMPLETE_DATA failures for {processor_name}"
            )
            return classified_count

        except GoogleAPIError as e:
            logger.warning(f"Error classifying failures: {e}")
            return 0

    def save_failures_to_bq(self) -> None:
        """
        Save failed entity records to BigQuery for auditing.

        Uses delete-then-insert pattern to prevent duplicate records on reruns.

        This enables visibility into WHY records are missing:
        - INSUFFICIENT_DATA: Player doesn't have enough game history (expected in early season)
        - INCOMPLETE_DATA: Upstream data incomplete (expected during bootstrap)
        - MISSING_DEPENDENCY: Required upstream data not available (standardized singular form)
        - PROCESSING_ERROR: Actual error during processing (needs investigation)
        - UNKNOWN: Uncategorized failure (needs investigation)

        Each child processor should populate self.failed_entities with dicts containing:
        - entity_id: player_lookup or other identifier
        - category: failure category (see above)
        - reason: detailed reason string
        - can_retry: bool indicating if reprocessing might succeed
        """
        if not self.failed_entities:
            return

        # Auto-classify INCOMPLETE_DATA failures before saving
        # This adds DNP vs DATA_GAP classification for player processors
        try:
            self.classify_recorded_failures()
        except Exception as classify_e:
            logger.warning(f"Could not classify failures (continuing anyway): {classify_e}")

        try:
            table_id = f"{self.project_id}.nba_processing.precompute_failures"
            analysis_date = self.opts.get('analysis_date')

            # Convert date to string if needed
            if hasattr(analysis_date, 'isoformat'):
                date_str = analysis_date.isoformat()
            else:
                date_str = str(analysis_date)

            # Delete existing failures for this processor/date to prevent duplicates
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE processor_name = '{self.__class__.__name__}'
              AND analysis_date = '{date_str}'
            """
            try:
                delete_job = self.bq_client.query(delete_query)
                delete_job.result(timeout=300)
                if delete_job.num_dml_affected_rows:
                    logger.debug(f"Deleted {delete_job.num_dml_affected_rows} existing failure records")
            except Exception as del_e:
                logger.warning(f"Could not delete existing failures (may be in streaming buffer): {del_e}")

            failure_records = []
            for failure in self.failed_entities:
                # Standardize category naming (singular form)
                category = failure.get('category', 'UNKNOWN')
                if category == 'MISSING_DEPENDENCIES':
                    category = 'MISSING_DEPENDENCY'

                # Build base record
                record = {
                    'processor_name': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': date_str,
                    'entity_id': failure.get('entity_id', 'unknown'),
                    'failure_category': category,
                    'failure_reason': str(failure.get('reason', ''))[:1000],  # Truncate long reasons
                    'can_retry': failure.get('can_retry', False),
                    'created_at': datetime.now(timezone.utc).isoformat()
                }

                # Add enhanced failure tracking fields (if provided)
                # These enable DNP vs Data Gap detection
                if 'failure_type' in failure:
                    record['failure_type'] = failure['failure_type']
                if 'is_correctable' in failure:
                    record['is_correctable'] = failure['is_correctable']
                if 'expected_count' in failure:
                    record['expected_game_count'] = failure['expected_count']
                if 'actual_count' in failure:
                    record['actual_game_count'] = failure['actual_count']
                if 'missing_dates' in failure:
                    # Convert list to JSON string for storage
                    missing_dates = failure['missing_dates']
                    if isinstance(missing_dates, list):
                        record['missing_game_dates'] = json.dumps([
                            d.isoformat() if hasattr(d, 'isoformat') else str(d)
                            for d in missing_dates
                        ])
                    else:
                        record['missing_game_dates'] = str(missing_dates)
                if 'raw_data_checked' in failure:
                    record['raw_data_checked'] = failure['raw_data_checked']

                # Resolution tracking - default to UNRESOLVED for new failures
                record['resolution_status'] = failure.get('resolution_status', 'UNRESOLVED')

                failure_records.append(record)

            # Insert in batches of 500 to avoid hitting limits
            # See docs/05-development/guides/bigquery-best-practices.md for batching rationale
            batch_size = 500
            for i in range(0, len(failure_records), batch_size):
                batch = failure_records[i:i + batch_size]

                # Get table reference for schema
                table_ref = self.bq_client.get_table(table_id)

                # Use batch loading instead of streaming inserts
                # This avoids the 90-minute streaming buffer that blocks DML operations
                job_config = bigquery.LoadJobConfig(
                    schema=table_ref.schema,
                    autodetect=False,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    ignore_unknown_values=True
                )

                load_job = self.bq_client.load_table_from_json(batch, table_id, job_config=job_config)
                load_job.result(timeout=300)

                if load_job.errors:
                    logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            logger.info(f"Saved {len(failure_records)} failure records to precompute_failures")

        except GoogleAPIError as e:
            logger.warning(f"Failed to save failure records: {e}")
