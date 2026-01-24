"""
OddsAPI Batch Processor
=======================

Processes all OddsAPI files for a date in a single batch operation.
Triggered by any OddsAPI file arrival, uses Firestore lock to ensure
only ONE processor runs the batch.

Benefits:
- 90%+ reduction in MERGE operations (14 → 1-2)
- Eliminates BigQuery serialization conflicts
- Reduces processing time from 60+ minutes to <5 minutes

Usage:
    Automatically triggered via Firestore locking in main_processor_service.py
    when any odds-api file arrives for a date.

Version: 1.0
Created: 2026-01-14
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery, storage

from data_processors.raw.processor_base import ProcessorBase
from shared.clients.bigquery_pool import get_bigquery_client
from data_processors.raw.oddsapi.odds_api_props_processor import OddsApiPropsProcessor
from data_processors.raw.oddsapi.odds_game_lines_processor import OddsGameLinesProcessor

logger = logging.getLogger(__name__)


class OddsApiGameLinesBatchProcessor(ProcessorBase):
    """
    Batch processor for OddsAPI game lines.

    Reads all game-lines files for a date from GCS and processes them
    in a single BigQuery MERGE operation for maximum efficiency.
    """

    # Skip ProcessorBase deduplication - batch processors use Firestore locks instead
    # This prevents conflicts between Firestore lock (batch coordination) and
    # run_history deduplication (single-file processors)
    SKIP_DEDUPLICATION = True

    def __init__(self):
        super().__init__()
        self.processor_name = "oddsapi_game_lines_batch_processor"
        self.all_rows = []
        self.gcs_client = storage.Client()
        # Use connection pool for BigQuery (reduces connection overhead by 40%+)
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = get_bigquery_client(self.project_id)
        self.table_name = 'nba_raw.odds_api_game_lines'
        self.files_processed = 0

    def load_data(self) -> None:
        """Load all game-lines files for the date from GCS."""
        game_date = self.opts.get('game_date')
        bucket_name = self.opts.get('bucket', 'nba-scraped-data')

        if not game_date:
            raise ValueError("game_date required for batch processing")

        logger.info(f"📦 Loading batch: game_date={game_date} for game-lines")

        # List all game-lines files for this date
        # Pattern: odds-api/game-lines/{date}/{event_id-teams}/{timestamp}.json
        prefix = f'odds-api/game-lines/{game_date}/'

        bucket = self.gcs_client.bucket(bucket_name)
        # NOTE: Iterate directly over list_blobs() to ensure all pages are consumed.
        # Converting to list() immediately may only capture the first page of results.
        blobs = bucket.list_blobs(prefix=prefix)

        file_count = 0
        for blob in blobs:
            # Skip non-JSON files
            if not blob.name.endswith('.json'):
                continue

            try:
                content = blob.download_as_text()
                raw_data = json.loads(content)

                # Use the existing processor's transform logic
                processor = OddsGameLinesProcessor()
                processor.opts = {
                    'file_path': blob.name,
                    'bucket': bucket_name,
                    'project_id': self.project_id
                }
                processor.raw_data = raw_data
                processor.transform_data()

                if processor.transformed_data:
                    self.all_rows.extend(processor.transformed_data)
                    file_count += 1

            except Exception as e:
                logger.error(f"Failed to process game-lines file {blob.name}: {e}")
                # Continue with other files

        logger.info(f"✅ Loaded {file_count} game-lines files, {len(self.all_rows)} total rows")

        self.files_processed = file_count
        self.raw_data = self.all_rows
        self.stats['files_loaded'] = file_count
        self.stats['rows_loaded'] = len(self.all_rows)

    def transform_data(self) -> None:
        """Transform data - already done during load_data()."""
        self.transformed_data = self.raw_data

    def save_data(self) -> None:
        """Save all game-lines in a single MERGE operation."""
        if not self.all_rows:
            logger.warning("No game-lines data to save")
            self.stats['rows_inserted'] = 0
            return

        table_id = f"{self.project_id}.{self.table_name}"
        temp_table_id = f"{table_id}_batch_{uuid.uuid4().hex[:8]}"

        try:
            # Get target table schema
            target_table = self.bq_client.get_table(table_id)

            # Create temp table with same schema
            temp_table = bigquery.Table(temp_table_id, schema=target_table.schema)
            self.bq_client.create_table(temp_table)
            logger.info(f"Created temp table: {temp_table_id}")

            # Batch load to temp table
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
            )

            load_job = self.bq_client.load_table_from_json(
                self.all_rows,
                temp_table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)

            logger.info(f"✅ Batch loaded {len(self.all_rows)} rows to temp table")

            # Extract game_date for partition filter
            game_date = self.opts.get('game_date')

            # Single MERGE operation for all games
            self._execute_merge(temp_table_id, table_id, game_date)

            self.stats['rows_inserted'] = len(self.all_rows)

        except Exception as e:
            logger.error(f"Failed to save game-lines batch: {e}")
            self.stats['rows_inserted'] = 0
            raise

        finally:
            # Clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id)
                logger.info(f"✅ Cleaned up temp table: {temp_table_id}")
            except Exception as e:
                logger.warning(f"Failed to delete temp table: {e}")

    def _execute_merge(self, temp_table_id: str, target_table_id: str, game_date: str = None):
        """Execute single MERGE operation for all game lines."""
        import re

        # Validate game_date to prevent SQL injection (must be YYYY-MM-DD format)
        if not game_date:
            raise ValueError("game_date is required for MERGE operation on partitioned table")
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', game_date):
            raise ValueError(f"Invalid game_date format: {game_date}. Expected YYYY-MM-DD")

        # CRITICAL: For BigQuery tables with require_partition_filter=true,
        # the partition filter MUST come FIRST in the ON clause and use a literal value.
        # Using DATE() function ensures proper type casting.
        merge_query = f"""
        MERGE `{target_table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.game_date = DATE('{game_date}')
           AND target.game_id = source.game_id
           AND COALESCE(target.snapshot_timestamp, TIMESTAMP('1970-01-01')) = COALESCE(source.snapshot_timestamp, TIMESTAMP('1970-01-01'))
           AND target.bookmaker_key = source.bookmaker_key
           AND target.market_key = source.market_key
           AND target.outcome_name = source.outcome_name

        WHEN MATCHED THEN
            UPDATE SET
                snapshot_timestamp = source.snapshot_timestamp,
                previous_snapshot_timestamp = source.previous_snapshot_timestamp,
                next_snapshot_timestamp = source.next_snapshot_timestamp,
                sport_key = source.sport_key,
                sport_title = source.sport_title,
                commence_time = source.commence_time,
                game_date = source.game_date,
                home_team = source.home_team,
                away_team = source.away_team,
                home_team_abbr = source.home_team_abbr,
                away_team_abbr = source.away_team_abbr,
                bookmaker_title = source.bookmaker_title,
                bookmaker_last_update = source.bookmaker_last_update,
                market_last_update = source.market_last_update,
                outcome_price = source.outcome_price,
                outcome_point = source.outcome_point,
                data_source = source.data_source,
                processed_at = source.processed_at

        WHEN NOT MATCHED THEN
            INSERT (
                snapshot_timestamp, previous_snapshot_timestamp, next_snapshot_timestamp,
                game_id, sport_key, sport_title, commence_time, game_date,
                home_team, away_team, home_team_abbr, away_team_abbr,
                bookmaker_key, bookmaker_title, bookmaker_last_update,
                market_key, market_last_update,
                outcome_name, outcome_price, outcome_point,
                source_file_path, data_source, created_at, processed_at, data_hash
            )
            VALUES (
                source.snapshot_timestamp, source.previous_snapshot_timestamp, source.next_snapshot_timestamp,
                source.game_id, source.sport_key, source.sport_title, source.commence_time, source.game_date,
                source.home_team, source.away_team, source.home_team_abbr, source.away_team_abbr,
                source.bookmaker_key, source.bookmaker_title, source.bookmaker_last_update,
                source.market_key, source.market_last_update,
                source.outcome_name, source.outcome_price, source.outcome_point,
                source.source_file_path, source.data_source, source.created_at, source.processed_at, source.data_hash
            )
        """

        logger.info(f"Executing batch MERGE from {temp_table_id} to {target_table_id}")

        merge_job = self.bq_client.query(merge_query)
        result = merge_job.result()

        rows_affected = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0
        logger.info(f"✅ Batch MERGE complete - {rows_affected} rows affected")

        self.stats['rows_merged'] = rows_affected
        self.stats['files_processed'] = self.files_processed


class OddsApiPropsBatchProcessor(ProcessorBase):
    """
    Batch processor for OddsAPI player props.

    Reads all player-props files for a date from GCS and processes them
    in a single BigQuery APPEND operation for maximum efficiency.
    """

    # Skip ProcessorBase deduplication - batch processors use Firestore locks instead
    # This prevents conflicts between Firestore lock (batch coordination) and
    # run_history deduplication (single-file processors)
    SKIP_DEDUPLICATION = True

    def __init__(self):
        super().__init__()
        self.processor_name = "oddsapi_props_batch_processor"
        self.all_rows = []
        self.gcs_client = storage.Client()
        # Use connection pool for BigQuery (reduces connection overhead by 40%+)
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = get_bigquery_client(self.project_id)
        self.table_name = 'nba_raw.odds_api_player_points_props'
        self.files_processed = 0

    def load_data(self) -> None:
        """Load all player-props files for the date from GCS."""
        game_date = self.opts.get('game_date')
        bucket_name = self.opts.get('bucket', 'nba-scraped-data')

        if not game_date:
            raise ValueError("game_date required for batch processing")

        logger.info(f"📦 Loading batch: game_date={game_date} for player-props")

        # List all player-props files for this date
        # Pattern: odds-api/player-props/{date}/{event_id-teams}/{timestamp}.json
        prefix = f'odds-api/player-props/{game_date}/'

        bucket = self.gcs_client.bucket(bucket_name)
        # NOTE: Iterate directly over list_blobs() to ensure all pages are consumed.
        # Converting to list() immediately may only capture the first page of results.
        blobs = bucket.list_blobs(prefix=prefix)

        file_count = 0
        for blob in blobs:
            # Skip non-JSON files
            if not blob.name.endswith('.json'):
                continue

            try:
                content = blob.download_as_text()
                raw_data = json.loads(content)

                # Use the existing processor's transform logic
                processor = OddsApiPropsProcessor()
                processor.opts = {
                    'file_path': blob.name,
                    'bucket': bucket_name,
                    'project_id': self.project_id
                }
                processor.raw_data = raw_data
                processor.transform_data()

                if processor.transformed_data:
                    self.all_rows.extend(processor.transformed_data)
                    file_count += 1

            except Exception as e:
                logger.error(f"Failed to process player-props file {blob.name}: {e}")
                # Continue with other files

        logger.info(f"✅ Loaded {file_count} player-props files, {len(self.all_rows)} total rows")

        self.files_processed = file_count
        self.raw_data = self.all_rows
        self.stats['files_loaded'] = file_count
        self.stats['rows_loaded'] = len(self.all_rows)

    def transform_data(self) -> None:
        """Transform data - already done during load_data()."""
        self.transformed_data = self.raw_data

    def save_data(self) -> None:
        """Save all props in a single APPEND operation."""
        import datetime as dt

        if not self.all_rows:
            logger.warning("No player-props data to save")
            self.stats['rows_inserted'] = 0
            return

        # Convert datetime objects to ISO format strings
        for row in self.all_rows:
            for key, value in row.items():
                if isinstance(value, (dt.date, dt.datetime)):
                    row[key] = value.isoformat()

        table_id = f"{self.project_id}.{self.table_name}"

        try:
            # Get target table for schema
            target_table = self.bq_client.get_table(table_id)

            # Use batch loading with APPEND
            job_config = bigquery.LoadJobConfig(
                schema=target_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(
                self.all_rows,
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=120)

            if load_job.errors:
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")
                self.stats['rows_inserted'] = 0
                raise Exception(f"BigQuery load errors: {load_job.errors}")

            logger.info(f"✅ Batch loaded {len(self.all_rows)} prop records")

            self.stats['rows_inserted'] = len(self.all_rows)
            self.stats['files_processed'] = self.files_processed

            # Update predictions that were waiting for lines
            if len(self.all_rows) > 0:
                self._update_predictions_with_new_lines()

        except Exception as e:
            logger.error(f"Failed to save props batch: {e}")
            self.stats['rows_inserted'] = 0
            raise

    def _update_predictions_with_new_lines(self) -> None:
        """
        Update NO_PROP_LINE predictions with newly loaded betting lines.

        When predictions run before lines are available, they're marked as NO_PROP_LINE.
        This method updates those predictions once lines are loaded, filling in:
        - current_points_line
        - line_margin
        - has_prop_line
        - line_source
        - recommendation
        """
        game_date = self.opts.get('game_date')
        if not game_date:
            return

        try:
            # Only update predictions for today or future (not historical)
            from datetime import date
            if isinstance(game_date, str):
                from datetime import datetime
                game_date_obj = datetime.strptime(game_date, '%Y-%m-%d').date()
            else:
                game_date_obj = game_date

            if game_date_obj < date.today():
                logger.debug(f"Skipping prediction update for historical date {game_date}")
                return

            # Update predictions that have NO_PROP_LINE with newly available lines
            update_query = """
            UPDATE `{project}.nba_predictions.player_prop_predictions` pred
            SET
                current_points_line = lines.points_line,
                line_margin = ROUND(pred.predicted_points - lines.points_line, 2),
                has_prop_line = TRUE,
                line_source = 'ACTUAL_PROP',
                line_source_api = 'ODDS_API',
                sportsbook = UPPER(lines.bookmaker),
                line_minutes_before_game = lines.minutes_before_tipoff,
                recommendation = CASE
                    WHEN pred.predicted_points - lines.points_line > 2.0 THEN 'OVER'
                    WHEN lines.points_line - pred.predicted_points > 2.0 THEN 'UNDER'
                    ELSE 'HOLD'
                END,
                updated_at = CURRENT_TIMESTAMP()
            FROM (
                SELECT player_lookup, game_date, points_line, bookmaker, minutes_before_tipoff,
                       ROW_NUMBER() OVER (
                           PARTITION BY player_lookup
                           ORDER BY
                               CASE bookmaker WHEN 'draftkings' THEN 1 WHEN 'fanduel' THEN 2 ELSE 99 END,
                               snapshot_timestamp DESC
                       ) as rn
                FROM `{project}.nba_raw.odds_api_player_points_props`
                WHERE game_date = @game_date
            ) lines
            WHERE pred.game_date = @game_date
              AND pred.is_active = TRUE
              AND pred.line_source = 'NO_PROP_LINE'
              AND pred.player_lookup = lines.player_lookup
              AND lines.rn = 1
            """.format(project=self.project_id)

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", str(game_date))
                ]
            )

            result = self.bq_client.query(update_query, job_config=job_config).result(timeout=60)
            rows_updated = result.num_dml_affected_rows or 0

            if rows_updated > 0:
                logger.info(f"📊 Updated {rows_updated} predictions with new betting lines for {game_date}")
                self.stats['predictions_updated'] = rows_updated
            else:
                logger.debug(f"No NO_PROP_LINE predictions to update for {game_date}")

        except Exception as e:
            # Don't fail the batch if prediction update fails
            logger.warning(f"Failed to update predictions with new lines: {e}")
