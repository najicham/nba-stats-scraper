"""
Path: data_processors/analytics/operations/failure_tracking.py

Failure tracking mixin for analytics processors.

Provides methods for:
- Recording registry lookup failures for reprocessing workflows
- Recording entity processing failures with classification
- Classifying failures (PLAYER_DNP vs DATA_GAP)
- Saving failures to BigQuery

Version: 1.0
Created: 2026-01-25
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
    Mixin for tracking and persisting processing failures in analytics processors.

    This mixin provides:
    1. Registry failure tracking - for player name resolution issues
    2. Entity failure recording - for data quality/completeness issues
    3. DNP classification - distinguishing player DNP from data gaps
    4. BigQuery persistence - saving failures for monitoring/reprocessing

    Required Dependencies (from base class):
    ---------------------------------------
    The base class must provide these attributes:

    - self.bq_client: BigQuery client instance
    - self.project_id: GCP project ID string
    - self.registry_failures: List for tracking registry failures
    - self.failed_entities: List for tracking entity failures
    - self.opts: Dict of processing options (must contain start_date/end_date)
    - self.run_id: String run identifier
    - self.stats: Dict for statistics tracking
    - self.completeness_checker: CompletenessChecker instance (optional, for DNP classification)
    - self.__class__.__name__: Processor name string

    Usage Example:
    -------------
    class MyAnalyticsProcessor(FailureTrackingMixin, AnalyticsProcessorBase):
        def calculate_analytics(self):
            # ... processing logic ...

            # Record a registry failure (name not found)
            if player_lookup not in registry:
                self.registry_failures.append({
                    'player_lookup': player_lookup,
                    'game_date': game_date,
                    'team_abbr': team_abbr,
                    'season': season,
                    'game_id': game_id
                })

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
            self.save_registry_failures()
            self.save_failures_to_bq()
            super().finalize()
    """

    def save_registry_failures(self) -> None:
        """
        Save registry failure records to BigQuery for reprocessing workflow.

        This enables tracking of players who couldn't be found in the registry
        during Phase 3 processing. The table supports a full lifecycle:
        - PENDING: created_at set, waiting for alias
        - RESOLVED: resolved_at set (by resolve_unresolved_batch.py)
        - REPROCESSED: reprocessed_at set (by reprocess_resolved.py)

        Each child processor should populate self.registry_failures with dicts containing:
        - player_lookup: raw name that failed lookup
        - game_date: when the player played
        - team_abbr: team context (optional)
        - season: season string (optional)
        - game_id: specific game ID (optional)
        """
        if not self.registry_failures:
            return

        try:
            table_id = f"{self.project_id}.nba_processing.registry_failures"

            # Deduplicate by (player_lookup, game_date) - keep first occurrence
            seen = set()
            unique_failures = []
            for failure in self.registry_failures:
                key = (failure.get('player_lookup'), str(failure.get('game_date')))
                if key not in seen:
                    seen.add(key)
                    unique_failures.append(failure)

            failure_records = []
            for failure in unique_failures:
                # Convert game_date to string if needed
                game_date = failure.get('game_date')
                if hasattr(game_date, 'isoformat'):
                    game_date_str = game_date.isoformat()
                else:
                    game_date_str = str(game_date)

                failure_records.append({
                    'player_lookup': failure.get('player_lookup', 'unknown'),
                    'game_date': game_date_str,
                    'processor_name': self.__class__.__name__,
                    'team_abbr': failure.get('team_abbr'),
                    'season': failure.get('season'),
                    'game_id': failure.get('game_id'),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'resolved_at': None,
                    'reprocessed_at': None,
                    'occurrence_count': 1,
                    'run_id': self.run_id
                })

            # Insert in batches of 500 to avoid hitting limits
            # Use batch loading to avoid streaming buffer issues
            # See: docs/05-development/guides/bigquery-best-practices.md
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

            logger.info(f"📊 Saved {len(failure_records)} registry failures to registry_failures table")

            # Store in stats for reporting
            self.stats['registry_failures_count'] = len(failure_records)
            self.stats['registry_failures_players'] = len(set(f.get('player_lookup') for f in unique_failures))

        except GoogleAPIError as e:
            logger.warning(f"Failed to save registry failure records: {e}")

    def record_failure(
        self,
        entity_id: str,
        entity_type: str,
        category: str,
        reason: str,
        can_retry: bool = False,
        **kwargs
    ) -> None:
        """
        Record an entity failure for later saving to analytics_failures table.

        Phase 3 equivalent of precompute_base.py's failure tracking.

        Args:
            entity_id: Player lookup, team abbr, or game_id
            entity_type: 'PLAYER', 'TEAM', or 'GAME'
            category: Failure category (e.g., 'MISSING_DATA', 'PROCESSING_ERROR')
            reason: Human-readable description
            can_retry: Whether reprocessing might succeed
            **kwargs: Optional enhanced fields:
                - failure_type: 'PLAYER_DNP', 'DATA_GAP', 'MIXED', 'UNKNOWN'
                - is_correctable: bool
                - expected_count: int
                - actual_count: int
                - missing_game_ids: List[str]

        Example:
            self.record_failure(
                entity_id='zachlavine',
                entity_type='PLAYER',
                category='INCOMPLETE_DATA',
                reason='Missing 2 games in lookback window',
                can_retry=True,
                failure_type='PLAYER_DNP',
                is_correctable=False,
                expected_count=5,
                actual_count=3
            )
        """
        failure = {
            'entity_id': entity_id,
            'entity_type': entity_type,
            'category': category,
            'reason': reason,
            'can_retry': can_retry
        }

        # Add optional enhanced fields
        for key in ['failure_type', 'is_correctable', 'expected_count', 'actual_count',
                    'missing_game_ids', 'raw_data_checked']:
            if key in kwargs:
                failure[key] = kwargs[key]

        self.failed_entities.append(failure)

    def classify_recorded_failures(self, analysis_date: Optional = None) -> int:
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
        Team-based failures are skipped since teams always play their games.

        Args:
            analysis_date: Date being analyzed. If None, uses self.opts['end_date'] or 'start_date'

        Returns:
            int: Number of failures that were classified

        Example:
            # In processor, after recording failures:
            num_classified = self.classify_recorded_failures()
            logger.info(f"Classified {num_classified} failures")
            self.save_failures_to_bq()
        """
        if not self.failed_entities:
            return 0

        # Get analysis date
        if analysis_date is None:
            analysis_date = self.opts.get('end_date') or self.opts.get('start_date')
        if hasattr(analysis_date, 'isoformat'):
            pass  # Already a date object
        elif isinstance(analysis_date, str):
            from datetime import datetime as dt
            analysis_date = dt.strptime(analysis_date, '%Y-%m-%d').date()

        if not analysis_date:
            logger.warning("classify_recorded_failures: No analysis_date available")
            return 0

        # Check if this is a player-based processor (not team-based)
        processor_name = self.__class__.__name__
        is_player_processor = any(x in processor_name.lower() for x in [
            'player', 'pgs', 'upgc', 'upcoming'
        ])

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
        Save failed entity records to analytics_failures BigQuery table.

        This method is called at the end of processing (in finalize() or manually)
        to persist any failures that were recorded during processing.

        Schema matches nba_processing.analytics_failures:
            - processor_name, run_id, analysis_date, entity_id, entity_type
            - failure_category, failure_reason, can_retry
            - failure_type, is_correctable (enhanced tracking)
            - expected_record_count, actual_record_count, missing_game_ids
            - resolution_status, created_at
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
            table_id = f"{self.project_id}.nba_processing.analytics_failures"
            analysis_date = self.opts.get('end_date') or self.opts.get('start_date')

            # Convert analysis_date to string if needed
            if hasattr(analysis_date, 'isoformat'):
                date_str = analysis_date.isoformat()
            else:
                date_str = str(analysis_date)

            failure_records = []
            for failure in self.failed_entities:
                # Build base record
                record = {
                    'processor_name': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': date_str,
                    'entity_id': failure.get('entity_id', 'unknown'),
                    'entity_type': failure.get('entity_type', 'UNKNOWN'),
                    'failure_category': failure.get('category', 'UNKNOWN'),
                    'failure_reason': str(failure.get('reason', ''))[:1000],
                    'can_retry': failure.get('can_retry', False),
                    'created_at': datetime.now(timezone.utc).isoformat()
                }

                # Add enhanced failure tracking fields (if provided)
                if 'failure_type' in failure:
                    record['failure_type'] = failure['failure_type']
                if 'is_correctable' in failure:
                    record['is_correctable'] = failure['is_correctable']
                if 'expected_count' in failure:
                    record['expected_record_count'] = failure['expected_count']
                if 'actual_count' in failure:
                    record['actual_record_count'] = failure['actual_count']
                if 'missing_game_ids' in failure:
                    missing = failure['missing_game_ids']
                    if isinstance(missing, list):
                        record['missing_game_ids'] = json.dumps(missing)
                    else:
                        record['missing_game_ids'] = str(missing)

                # Resolution tracking - default to UNRESOLVED
                record['resolution_status'] = failure.get('resolution_status', 'UNRESOLVED')

                failure_records.append(record)

            # Insert in batches of 500
            # Use batch loading to avoid streaming buffer issues
            # See: docs/05-development/guides/bigquery-best-practices.md
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

            logger.info(f"📊 Saved {len(failure_records)} failures to analytics_failures table")

            # Store in stats
            self.stats['failures_recorded'] = len(failure_records)

        except GoogleAPIError as e:
            logger.warning(f"Failed to save failure records to BQ: {e}")
