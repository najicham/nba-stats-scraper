#!/usr/bin/env python3
# File: data_processors/raw/kalshi/kalshi_props_processor.py
# Strategy: CHECK_BEFORE_INSERT - Track processed files, preserve time-series data

"""
Kalshi Player Props Processor

Processes player props data from Kalshi prediction markets.
Kalshi offers CFTC-regulated binary contracts for NBA player stats.

GCS Path: gs://nba-scraped-data/kalshi/player-props/{date}/{timestamp}.json
BigQuery Table: nba_raw.kalshi_player_props

Processing Strategy: CHECK_BEFORE_INSERT
- Preserves time-series data for price history tracking
- Tracks processed files to prevent duplicate processing
- Allows multiple scrapes per day to track price movements
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from data_processors.raw.utils.name_utils import normalize_name
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class KalshiPropsProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Kalshi Player Props Processor

    Processing Strategy: CHECK_BEFORE_INSERT
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: player_lookup, game_date, prop_type, line_value, yes_ask, no_ask
        Expected Skip Rate: N/A (CHECK_BEFORE_INSERT, hash for monitoring only)
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'player_lookup',
        'game_date',
        'prop_type',
        'line_value',
        'yes_ask',
        'no_ask'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.kalshi_player_props'
        self.processing_strategy = 'CHECK_BEFORE_INSERT'  # Preserve time-series data

        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def file_already_processed(self, file_path: str) -> bool:
        """
        Check if this specific GCS file has already been processed.

        This prevents duplicate processing of the same scrape snapshot
        while allowing multiple scrapes per day to track price movements.
        """
        table_id = f"{self.project_id}.{self.table_name}"

        # Query to check if this file path exists
        query = f"""
        SELECT COUNT(*) as count
        FROM `{table_id}`
        WHERE source_file_path = @file_path
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("file_path", "STRING", file_path)
            ]
        )

        try:
            query_job = self.bq_client.query(query, job_config=job_config)
            results = list(query_job.result(timeout=60))

            if results and results[0]['count'] > 0:
                logger.info(f"File already processed, skipping: {file_path}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking if file processed: {e}")
            # If check fails, assume not processed to avoid data loss
            return False

    def extract_game_date_from_path(self, file_path: str) -> Optional[str]:
        """Extract game date from Kalshi file path.

        Expected path format: kalshi/player-props/{date}/{timestamp}.json
        """
        try:
            parts = file_path.split('/')
            for part in parts:
                # Look for YYYY-MM-DD format
                if len(part) == 10 and part[4] == '-' and part[7] == '-':
                    return part
            return None
        except Exception as e:
            logger.warning(f"Could not parse game date from {file_path}: {e}")
            return None

    def validate_data(self, data: Dict) -> List[str]:
        """Validate Kalshi JSON structure."""
        errors = []

        if 'props' not in data:
            errors.append("Missing 'props' array")
        elif not isinstance(data['props'], list):
            errors.append("'props' is not an array")

        if 'date' not in data:
            errors.append("Missing 'date' field")

        return errors

    def calculate_liquidity_score(self, total_volume: Optional[int], open_interest: Optional[int]) -> str:
        """Calculate liquidity score based on volume and open interest.

        Args:
            total_volume: Total contracts traded
            open_interest: Outstanding contracts

        Returns:
            "HIGH", "MEDIUM", or "LOW"
        """
        volume = total_volume or 0
        oi = open_interest or 0
        total = volume + oi

        if total >= 1000:
            return "HIGH"
        elif total >= 100:
            return "MEDIUM"
        else:
            return "LOW"

    def transform_data(self) -> None:
        """Transform raw Kalshi data into BigQuery rows."""
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', 'unknown')
        rows = []

        try:
            # Validate data first
            validation_errors = self.validate_data(raw_data)
            if validation_errors:
                logger.error(f"Validation errors for {file_path}: {validation_errors}")

                try:
                    notify_warning(
                        title="Kalshi Props Data Validation Errors",
                        message=f"Validation errors: {', '.join(validation_errors[:3])}",
                        details={
                            'processor': 'KalshiPropsProcessor',
                            'file_path': file_path,
                            'error_count': len(validation_errors),
                            'errors': validation_errors
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

                self.transformed_data = rows
                return

            # Get game date from data or path
            game_date = raw_data.get('date')
            if not game_date:
                game_date = self.extract_game_date_from_path(file_path)

            if not game_date:
                raise ValueError(f"Could not determine game_date from data or path: {file_path}")

            # Get scrape timestamp
            scraped_at_str = raw_data.get('scraped_at')
            if scraped_at_str:
                try:
                    scraped_at = datetime.fromisoformat(scraped_at_str.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    scraped_at = datetime.now(timezone.utc)
            else:
                scraped_at = datetime.now(timezone.utc)

            current_time = datetime.now(timezone.utc)

            # Process each prop
            for prop in raw_data.get('props', []):
                # Normalize player name using shared utility
                kalshi_player_name = prop.get('kalshi_player_name', '')
                player_lookup = normalize_name(kalshi_player_name)

                if not player_lookup:
                    # Try player_lookup from scraper if already computed
                    player_lookup = prop.get('player_lookup')

                if not player_lookup:
                    logger.warning(f"Skipping prop with no player name: {prop.get('market_ticker')}")
                    continue

                # Calculate liquidity score if not present
                liquidity_score = prop.get('liquidity_score')
                if not liquidity_score:
                    liquidity_score = self.calculate_liquidity_score(
                        prop.get('total_volume'),
                        prop.get('open_interest')
                    )

                row = {
                    # Partition key
                    'game_date': game_date,

                    # Kalshi Identifiers
                    'series_ticker': prop.get('series_ticker'),
                    'event_ticker': prop.get('event_ticker'),
                    'market_ticker': prop.get('market_ticker'),

                    # Market Type
                    'prop_type': prop.get('prop_type'),

                    # Player Identification
                    'kalshi_player_name': kalshi_player_name,
                    'player_lookup': player_lookup,
                    'player_team': prop.get('player_team'),

                    # Game Identification
                    'home_team': prop.get('home_team'),
                    'away_team': prop.get('away_team'),
                    'game_id': prop.get('game_id'),

                    # Line Information
                    'line_value': prop.get('line_value'),

                    # Contract Pricing (in cents, 0-100)
                    'yes_bid': prop.get('yes_bid'),
                    'yes_ask': prop.get('yes_ask'),
                    'no_bid': prop.get('no_bid'),
                    'no_ask': prop.get('no_ask'),

                    # Derived Pricing
                    'implied_over_prob': prop.get('implied_over_prob'),
                    'implied_under_prob': prop.get('implied_under_prob'),
                    'equivalent_over_odds': prop.get('equivalent_over_odds'),
                    'equivalent_under_odds': prop.get('equivalent_under_odds'),

                    # Liquidity Metrics
                    'yes_bid_size': prop.get('yes_bid_size'),
                    'yes_ask_size': prop.get('yes_ask_size'),
                    'no_bid_size': prop.get('no_bid_size'),
                    'no_ask_size': prop.get('no_ask_size'),
                    'total_volume': prop.get('total_volume'),
                    'open_interest': prop.get('open_interest'),
                    'liquidity_score': liquidity_score,

                    # Market Status
                    'market_status': prop.get('market_status'),
                    'can_close_early': prop.get('can_close_early'),
                    'close_time': prop.get('close_time'),

                    # Team Validation (default to has_team_issues=True)
                    'has_team_issues': prop.get('has_team_issues', True),
                    'validated_team': prop.get('validated_team'),
                    'validation_confidence': prop.get('validation_confidence'),
                    'validation_method': prop.get('validation_method'),

                    # Metadata
                    'source_file_path': file_path,
                    'scraped_at': scraped_at.isoformat(),
                    'processed_at': current_time.isoformat()
                }

                rows.append(row)

            logger.info(f"Transformed {len(rows)} Kalshi props from {file_path}")

        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)

            try:
                notify_error(
                    title="Kalshi Props Transform Failed",
                    message=f"Failed to transform Kalshi props data: {str(e)}",
                    details={
                        'processor': 'KalshiPropsProcessor',
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="Kalshi Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            raise

        self.transformed_data = rows

        # Smart Idempotency: Add data_hash to all records
        self.add_data_hash()

    def save_data(self) -> None:
        """Save transformed data to BigQuery using batch loading."""
        rows = self.transformed_data

        if not rows:
            self.stats['rows_inserted'] = 0
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.table_name}"
        errors = []

        try:
            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result(timeout=60)  # Wait for completion

            # Check for errors
            if load_job.errors:
                errors.extend([str(e) for e in load_job.errors])
                logger.error(f"BigQuery batch load errors: {errors}")

                try:
                    notify_error(
                        title="Kalshi Props BigQuery Batch Load Failed",
                        message=f"Failed to batch load {len(rows)} Kalshi prop records",
                        details={
                            'processor': 'KalshiPropsProcessor',
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'error_count': len(load_job.errors),
                            'errors': [str(e) for e in load_job.errors[:3]]
                        },
                        processor_name="Kalshi Props Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            else:
                # Success
                unique_players = len(set(row['player_lookup'] for row in rows if row.get('player_lookup')))
                unique_prop_types = len(set(row['prop_type'] for row in rows if row.get('prop_type')))
                game_date = rows[0].get('game_date') if rows else None

                logger.info(f"Successfully batch loaded {len(rows)} Kalshi prop rows")

                # Update stats for processor_base tracking
                self.stats['rows_inserted'] = len(rows)
                self.stats['rows_processed'] = len(rows)
                self.stats['rows_failed'] = 0

                try:
                    notify_info(
                        title="Kalshi Props Processing Complete",
                        message=f"Successfully processed {len(rows)} Kalshi prop records",
                        details={
                            'processor': 'KalshiPropsProcessor',
                            'rows_processed': len(rows),
                            'unique_players': unique_players,
                            'unique_prop_types': unique_prop_types,
                            'game_date': game_date,
                            'table': self.table_name,
                            'strategy': 'CHECK_BEFORE_INSERT (Batch Loading)'
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Failed to load to BigQuery: {error_msg}", exc_info=True)

            # Update stats for failure tracking
            self.stats['rows_inserted'] = 0
            self.stats['rows_processed'] = 0
            self.stats['rows_failed'] = len(rows)

            try:
                notify_error(
                    title="Kalshi Props Load Exception",
                    message=f"Critical failure loading Kalshi props data: {str(e)}",
                    details={
                        'processor': 'KalshiPropsProcessor',
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="Kalshi Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors,
            'unique_players': len(set(row['player_lookup'] for row in rows if row.get('player_lookup'))) if not errors else 0
        }

    def process_file_content(self, json_content: str, file_path: str) -> Dict:
        """
        Main processing method called by backfill jobs.

        Checks if file already processed to prevent duplicates while
        allowing multiple scrapes per day for price movement tracking.
        """
        try:
            # CHECK: Has this specific file been processed before?
            if self.file_already_processed(file_path):
                return {
                    'rows_processed': 0,
                    'errors': [],
                    'unique_players': 0,
                    'skipped': True,
                    'reason': 'file_already_processed'
                }

            # Parse JSON
            raw_data = json.loads(json_content)

            # Store for transform
            self.raw_data = raw_data
            self.opts['file_path'] = file_path

            # Validate
            validation_errors = self.validate_data(raw_data)
            if validation_errors:
                logger.error(f"Validation errors for {file_path}: {validation_errors}")

                try:
                    notify_warning(
                        title="Kalshi Props Data Validation Errors",
                        message=f"Validation errors: {', '.join(validation_errors[:3])}",
                        details={
                            'processor': 'KalshiPropsProcessor',
                            'file_path': file_path,
                            'error_count': len(validation_errors),
                            'errors': validation_errors
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

                return {
                    'rows_processed': 0,
                    'errors': validation_errors,
                    'unique_players': 0
                }

            # Transform
            self.transform_data()

            # Save
            result = self.save_data()

            return result

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON: {str(e)}"
            logger.error(f"{error_msg} in {file_path}")

            try:
                notify_error(
                    title="Kalshi Props JSON Parse Failed",
                    message=f"Failed to parse JSON from file",
                    details={
                        'processor': 'KalshiPropsProcessor',
                        'file_path': file_path,
                        'error': str(e)
                    },
                    processor_name="Kalshi Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            return {
                'rows_processed': 0,
                'errors': [error_msg],
                'unique_players': 0
            }
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            logger.error(f"{error_msg} in {file_path}", exc_info=True)

            try:
                notify_error(
                    title="Kalshi Props Processing Failed",
                    message=f"Unexpected error processing file: {str(e)}",
                    details={
                        'processor': 'KalshiPropsProcessor',
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="Kalshi Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            return {
                'rows_processed': 0,
                'errors': [error_msg],
                'unique_players': 0
            }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }
