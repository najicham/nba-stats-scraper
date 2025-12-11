#!/usr/bin/env python3
# File: processors/nbacom/nbac_player_movement_processor.py
# Description: Processor for NBA.com Player Movement data transformation
# Integrated notification system for monitoring and alerts

import logging
import os
from google.cloud import bigquery
from datetime import datetime, date
from typing import Dict, List, Optional, Set, Tuple
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

class NbacPlayerMovementProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    NBA.com Player Movement Processor

    Processing Strategy: APPEND_ALWAYS
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: player_lookup, transaction_date, transaction_type, team_abbr, transaction_description
        Expected Skip Rate: N/A (APPEND_ALWAYS always writes, hash for monitoring only)
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'player_lookup',
        'transaction_date',
        'transaction_type',
        'team_abbr',
        'transaction_description'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_player_movement'
        self.processing_strategy = 'INSERT_NEW_ONLY'  # Custom strategy
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Team slug to abbreviation mapping
        self.team_slug_to_abbr = {
            'hawks': 'ATL', 'celtics': 'BOS', 'nets': 'BKN', 'hornets': 'CHA',
            'bulls': 'CHI', 'cavaliers': 'CLE', 'mavericks': 'DAL', 'nuggets': 'DEN', 
            'pistons': 'DET', 'warriors': 'GSW', 'rockets': 'HOU', 'pacers': 'IND',
            'clippers': 'LAC', 'lakers': 'LAL', 'grizzlies': 'MEM', 'heat': 'MIA',
            'bucks': 'MIL', 'timberwolves': 'MIN', 'pelicans': 'NOP', 'knicks': 'NYK',
            'thunder': 'OKC', 'magic': 'ORL', 'sixers': 'PHI', 'suns': 'PHX',
            'blazers': 'POR', 'kings': 'SAC', 'spurs': 'SAS', 'raptors': 'TOR',
            'jazz': 'UTA', 'wizards': 'WAS'
        }
        
        # Tracking counters
        self.transactions_processed = 0
        self.transactions_failed = 0
    
    def normalize_player_slug(self, slug: str) -> Tuple[str, str]:
        """Convert player slug to full name and lookup."""
        if not slug:
            return "", ""
        
        # "haywood-highsmith" -> "Haywood Highsmith" 
        full_name = slug.replace('-', ' ').title()
        
        # "Haywood Highsmith" -> "haywoodhighsmith"
        lookup = full_name.lower().replace(' ', '').replace("'", "")
        
        return full_name, lookup
    
    def calculate_season_year(self, transaction_date: str) -> int:
        """Calculate NBA season year from transaction date."""
        dt = datetime.fromisoformat(transaction_date.replace('T00:00:00', ''))
        year = dt.year
        
        # NBA season starts in October, so October+ = new season
        if dt.month >= 10:
            return year
        else:
            return year - 1
    
    def get_existing_records(self) -> Set[Tuple]:
        """Query BigQuery for existing primary keys to avoid duplicates."""
        query = f"""
        SELECT 
            player_id,
            team_id, 
            transaction_date,
            transaction_type,
            group_sort
        FROM `{self.project_id}.{self.table_name}`
        """
        
        try:
            result = self.bq_client.query(query)
            existing_keys = set()
            for row in result:
                key = (row.player_id, row.team_id, row.transaction_date, 
                      row.transaction_type, row.group_sort)
                existing_keys.add(key)
            
            logger.info(f"Found {len(existing_keys)} existing records in BigQuery")
            return existing_keys
            
        except Exception as e:
            logger.warning(f"Could not query existing records: {e}")
            
            # Notify about query failure
            try:
                notify_error(
                    title="Player Movement Query Failed",
                    message=f"Failed to query existing records: {str(e)}",
                    details={
                        'table': self.table_name,
                        'error_type': type(e).__name__,
                        'query': query[:200]
                    },
                    processor_name="NBA.com Player Movement Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return set()
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the player movement data structure."""
        errors = []
        
        if 'metadata' not in data:
            errors.append("Missing metadata section")
            return errors
        
        if 'rows' not in data:
            errors.append("Missing rows section")
            return errors
        
        metadata = data['metadata']
        if 'recordCount' not in metadata:
            errors.append("Missing recordCount in metadata")
        
        if 'fetchedUtc' not in metadata:
            errors.append("Missing fetchedUtc in metadata")
        
        # Notify about validation failures
        if errors:
            try:
                notify_warning(
                    title="Player Movement Data Validation Failed",
                    message=f"Found {len(errors)} validation errors",
                    details={
                        'errors': errors,
                        'has_metadata': 'metadata' in data,
                        'has_rows': 'rows' in data,
                        'record_count': metadata.get('recordCount') if 'metadata' in data else None
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform player movement data into BigQuery format."""
        try:
            if not raw_data.get('rows'):
                logger.warning("No rows found in data")
                
                # Notify about no rows
                try:
                    notify_warning(
                        title="Player Movement No Rows Found",
                        message="Player movement data contains no transaction rows",
                        details={
                            'file_path': file_path,
                            'has_metadata': 'metadata' in raw_data,
                            'record_count': raw_data.get('metadata', {}).get('recordCount')
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return []
            
            metadata = raw_data.get('metadata', {})
            scrape_timestamp = metadata.get('fetchedUtc', datetime.utcnow().isoformat())
            
            # Get existing records to avoid duplicates
            existing_keys = self.get_existing_records()
            
            rows = []
            skipped_count = 0
            old_transactions = 0
            self.transactions_processed = 0
            self.transactions_failed = 0
            
            for transaction in raw_data['rows']:
                try:
                    # Filter to 2021+ transactions only
                    transaction_date_str = transaction['TRANSACTION_DATE']
                    transaction_dt = datetime.fromisoformat(transaction_date_str.replace('T00:00:00', ''))
                    
                    if transaction_dt.date() < date(2021, 1, 1):
                        old_transactions += 1
                        continue
                    
                    # Check if this record already exists
                    primary_key = (
                        transaction['PLAYER_ID'],
                        transaction['TEAM_ID'],
                        transaction_dt.date(),
                        transaction['Transaction_Type'],
                        transaction['GroupSort']
                    )
                    
                    if primary_key in existing_keys:
                        skipped_count += 1
                        continue
                    
                    # Parse player information
                    player_full_name, player_lookup = self.normalize_player_slug(
                        transaction.get('PLAYER_SLUG', '')
                    )
                    
                    # Map team slug to abbreviation
                    team_slug = transaction.get('TEAM_SLUG', '').lower()
                    team_abbr = self.team_slug_to_abbr.get(team_slug, team_slug.upper())
                    
                    # Calculate season year
                    season_year = self.calculate_season_year(transaction_date_str)
                    
                    row = {
                        'transaction_type': transaction['Transaction_Type'],
                        'transaction_date': transaction_dt.date().isoformat(),
                        'season_year': season_year,
                        'player_id': transaction['PLAYER_ID'],
                        'player_slug': transaction.get('PLAYER_SLUG', ''),
                        'player_full_name': player_full_name,
                        'player_lookup': player_lookup,
                        'is_player_transaction': transaction['PLAYER_ID'] != 0,
                        'team_id': transaction['TEAM_ID'],
                        'team_slug': team_slug,
                        'team_abbr': team_abbr,
                        'transaction_description': transaction['TRANSACTION_DESCRIPTION'],
                        'additional_sort': transaction.get('Additional_Sort', 0),
                        'group_sort': transaction['GroupSort'],
                        'source_file_path': file_path,
                        'scrape_timestamp': scrape_timestamp,
                        'created_at': datetime.utcnow().isoformat()
                    }
                    
                    rows.append(row)
                    self.transactions_processed += 1
                    
                except Exception as e:
                    self.transactions_failed += 1
                    logger.error(f"Error transforming transaction: {e}")
                    
                    # Notify on first transaction processing failure
                    if self.transactions_failed == 1:
                        try:
                            notify_error(
                                title="Player Movement Transaction Processing Failed",
                                message=f"Failed to process transaction: {str(e)}",
                                details={
                                    'error_type': type(e).__name__,
                                    'transaction': str(transaction)[:200]
                                },
                                processor_name="NBA.com Player Movement Processor"
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                    continue
            
            # Check for unusually high skip rate (might indicate data issues)
            total_recent_transactions = len(raw_data['rows']) - old_transactions
            if total_recent_transactions > 0:
                skip_rate = skipped_count / total_recent_transactions
                if skip_rate > 0.5:  # More than 50% skipped
                    try:
                        notify_warning(
                            title="High Player Movement Skip Rate",
                            message=f"Skipped {skip_rate:.1%} of transactions (already exist)",
                            details={
                                'total_transactions': len(raw_data['rows']),
                                'recent_transactions': total_recent_transactions,
                                'skipped_count': skipped_count,
                                'skip_rate': f"{skip_rate:.1%}",
                                'new_records': len(rows)
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Check for high failure rate
            if total_recent_transactions > 0:
                failure_rate = self.transactions_failed / total_recent_transactions
                if failure_rate > 0.05:  # More than 5% failures
                    try:
                        notify_warning(
                            title="High Player Movement Failure Rate",
                            message=f"Failed to process {failure_rate:.1%} of transactions",
                            details={
                                'total_recent_transactions': total_recent_transactions,
                                'transactions_failed': self.transactions_failed,
                                'transactions_processed': self.transactions_processed,
                                'failure_rate': f"{failure_rate:.1%}"
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info(f"Transformed {len(rows)} new records, skipped {skipped_count} existing, "
                       f"filtered {old_transactions} pre-2021 transactions")

            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()
        except Exception as e:
            logger.error(f"Critical error in transform_data: {e}")
            
            # Notify about critical transformation failure
            try:
                notify_error(
                    title="Player Movement Transformation Failed",
                    message=f"Critical error transforming player movement data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'transactions_processed': self.transactions_processed,
                        'transactions_failed': self.transactions_failed
                    },
                    processor_name="NBA.com Player Movement Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise e
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load new records into BigQuery (INSERT_NEW_ONLY strategy)."""
        if not rows:
            logger.warning("No rows to load")
            return {'rows_processed': 0, 'errors': [], 'skipped': 0}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result()

            if load_job.errors:
                errors.extend([str(e) for e in load_job.errors])
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")

                # Notify about load errors
                try:
                    notify_error(
                        title="BigQuery Load Errors",
                        message=f"Encountered {len(load_job.errors)} errors loading player movement data",
                        details={
                            'table_id': table_id,
                            'rows_attempted': len(rows),
                            'error_count': len(load_job.errors),
                            'errors': str(load_job.errors)[:500]
                        },
                        processor_name="NBA.com Player Movement Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

                return {'rows_processed': 0, 'errors': errors}
            
            logger.info(f"Successfully inserted {len(rows)} new records")
            
            # Send success notification
            try:
                notify_info(
                    title="Player Movement Processing Complete",
                    message=f"Successfully processed {len(rows)} player movement transactions",
                    details={
                        'rows_processed': len(rows),
                        'transactions_failed': self.transactions_failed
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': len(rows), 'errors': []}
            
        except Exception as e:
            error_msg = f"Failed to insert rows: {str(e)}"
            logger.error(error_msg)
            
            # Notify about load failure
            try:
                notify_error(
                    title="Player Movement Load Failed",
                    message=f"Failed to load player movement data to BigQuery: {error_msg}",
                    details={
                        'table_id': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Player Movement Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': 0, 'errors': [error_msg]}