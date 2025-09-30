#!/usr/bin/env python3
# File: processors/nbacom/nbac_referee_processor.py
# Description: Processor for NBA.com referee assignments data transformation
# Enhanced with monitoring to detect duplication issues
# Integrated notification system for monitoring and alerts

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class NbacRefereeProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_referee_game_assignments'
        self.replay_table_name = 'nba_raw.nbac_referee_replay_center'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # Initialize BigQuery client and project ID
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
    
    def normalize_text(self, text: str) -> str:
        """Normalize text for data consistency."""
        if not text:
            return ""
        normalized = text.strip()
        # Remove extra spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized
    
    def extract_scrape_timestamp(self, raw_data: Dict) -> Optional[datetime]:
        """Extract scrape timestamp from raw data if available."""
        timestamp_str = raw_data.get('timestamp') or raw_data.get('fetchedUtc')
        if not timestamp_str:
            return None
            
        try:
            # Handle different timestamp formats
            if timestamp_str.endswith('Z'):
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            elif '+' in timestamp_str or timestamp_str.endswith('+00:00'):
                return datetime.fromisoformat(timestamp_str)
            else:
                # Try parsing as ISO format
                return datetime.fromisoformat(timestamp_str)
        except (ValueError, AttributeError):
            logging.warning(f"Could not parse timestamp: {timestamp_str}")
            return None
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the referee assignments data structure."""
        errors = []
        
        if 'refereeAssignments' not in data:
            errors.append("Missing refereeAssignments in data")
            return errors
            
        if 'nba' not in data['refereeAssignments']:
            errors.append("Missing nba section in refereeAssignments")
            return errors
            
        nba_data = data['refereeAssignments']['nba']
        if 'Table' not in nba_data or 'rows' not in nba_data['Table']:
            errors.append("Missing Table/rows in NBA referee data")
        
        # Notify about validation failures
        if errors:
            try:
                notify_warning(
                    title="Referee Data Validation Failed",
                    message=f"Found {len(errors)} validation errors in referee data",
                    details={
                        'errors': errors,
                        'has_refereeAssignments': 'refereeAssignments' in data,
                        'has_nba': 'nba' in data.get('refereeAssignments', {})
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform game referee assignments into normalized rows."""
        rows = []
        
        try:
            # Extract scrape timestamp
            scrape_timestamp = self.extract_scrape_timestamp(raw_data)
            
            nba_assignments = raw_data['refereeAssignments']['nba']['Table']['rows']
            
            for game_row in nba_assignments:
                # Extract game information
                game_id = game_row.get('game_id', '')
                game_date_str = game_row.get('game_date', '')
                
                # Parse game date
                game_date = None
                if game_date_str:
                    try:
                        game_date = datetime.strptime(game_date_str, '%m/%d/%Y').date()
                    except (ValueError, TypeError):
                        logging.warning(f"Invalid game_date format: {game_date_str}")
                        continue
                        
                # Extract season info
                season = game_row.get('season', '')
                
                # Process each official (1-4 officials per game)
                for official_num in range(1, 5):  # officials 1-4
                    official_key = f'official{official_num}'
                    official_code_key = f'official{official_num}_code'
                    official_jnum_key = f'official{official_num}_JNum'
                    
                    official_name = game_row.get(official_key)
                    official_code = game_row.get(official_code_key)
                    official_jersey = game_row.get(official_jnum_key)
                    
                    # Skip if no official assigned to this position
                    if not official_name or not official_code:
                        continue
                    
                    row = {
                        # Game identifiers
                        'game_id': game_id,
                        'game_date': game_date.isoformat() if game_date else None,
                        'season': season,
                        'game_code': game_row.get('game_code', ''),
                        
                        # Team information
                        'home_team_id': game_row.get('home_team_id'),
                        'home_team': self.normalize_text(game_row.get('home_team', '')),
                        'home_team_abbr': game_row.get('home_team_abbr', ''),
                        'away_team_id': game_row.get('away_team_id'),
                        'away_team': self.normalize_text(game_row.get('away_team', '')),
                        'away_team_abbr': game_row.get('away_team_abbr', ''),
                        
                        # Official information
                        'official_position': official_num,
                        'official_name': self.normalize_text(official_name),
                        'official_code': official_code,
                        'official_jersey_number': official_jersey,
                        
                        # Processing metadata
                        'source_file_path': file_path,
                        'scrape_timestamp': scrape_timestamp.isoformat() if scrape_timestamp else None,
                        'created_at': datetime.utcnow().isoformat(),
                        'processed_at': datetime.utcnow().isoformat()
                    }
                    
                    rows.append(row)
            
            return rows
            
        except Exception as e:
            logging.error(f"Error in transform_data: {e}")
            
            # Notify about transformation failure
            try:
                notify_error(
                    title="Referee Data Transformation Failed",
                    message=f"Failed to transform referee data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Referee Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            raise e
    
    def transform_replay_center_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform replay center officials data."""
        rows = []
        
        try:
            # Extract scrape timestamp
            scrape_timestamp = self.extract_scrape_timestamp(raw_data)
            
            # Check if replay center data exists
            nba_data = raw_data.get('refereeAssignments', {}).get('nba', {})
            if 'Table1' not in nba_data or 'rows' not in nba_data['Table1']:
                return rows
                
            replay_rows = nba_data['Table1']['rows']
            
            for replay_row in replay_rows:
                game_date_str = replay_row.get('game_date', '')
                
                # Parse game date
                game_date = None
                if game_date_str:
                    try:
                        game_date = datetime.strptime(game_date_str, '%m/%d/%Y').date()
                    except (ValueError, TypeError):
                        logging.warning(f"Invalid replay center game_date format: {game_date_str}")
                        continue
                
                row = {
                    'game_date': game_date.isoformat() if game_date else None,
                    'official_code': replay_row.get('official_code'),
                    'official_name': self.normalize_text(replay_row.get('replaycenter_official', '')),
                    'source_file_path': file_path,
                    'scrape_timestamp': scrape_timestamp.isoformat() if scrape_timestamp else None,
                    'created_at': datetime.utcnow().isoformat(),
                    'processed_at': datetime.utcnow().isoformat()
                }
                
                rows.append(row)
            
            return rows
            
        except Exception as e:
            logging.error(f"Error in transform_replay_center_data: {e}")
            
            # Notify about replay center transformation failure
            try:
                notify_error(
                    title="Replay Center Data Transformation Failed",
                    message=f"Failed to transform replay center data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Referee Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load game assignment data into BigQuery with duplicate detection and verification."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        # Check for duplicates in input data
        unique_keys = set()
        duplicates = []
        for row in rows:
            key = (row['game_id'], row['official_position'], row['official_code'])
            if key in unique_keys:
                duplicates.append(key)
            unique_keys.add(key)
        
        if duplicates:
            logging.warning(f"Found {len(duplicates)} duplicate keys in input data: {duplicates[:3]}...")
            
            # Notify about duplicates
            try:
                notify_warning(
                    title="Referee Assignment Duplicates Detected",
                    message=f"Found {len(duplicates)} duplicate referee assignments in input data",
                    details={
                        'duplicate_count': len(duplicates),
                        'sample_duplicates': str(duplicates[:3]),
                        'total_rows': len(rows)
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        file_path = rows[0].get('source_file_path', 'unknown') if rows else 'unknown'
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Get unique game_dates from the data to delete
                game_dates = set(row['game_date'] for row in rows if row['game_date'])
                
                for game_date in game_dates:
                    # Log delete operation with timing
                    delete_start = datetime.utcnow()
                    delete_query = f"""
                    DELETE FROM `{table_id}` 
                    WHERE game_date = '{game_date}'
                    """
                    
                    try:
                        self.bq_client.query(delete_query).result()
                        delete_duration = (datetime.utcnow() - delete_start).total_seconds()
                        logging.info(f"Deleted existing referee assignments for {game_date} ({delete_duration:.2f}s)")
                    except Exception as e:
                        logging.error(f"Error deleting existing data: {e}")
                        
                        # Notify about delete failure
                        try:
                            notify_error(
                                title="BigQuery Delete Failed",
                                message=f"Failed to delete existing referee data: {str(e)}",
                                details={
                                    'game_date': game_date,
                                    'table_id': table_id,
                                    'error_type': type(e).__name__
                                },
                                processor_name="NBA.com Referee Processor"
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                        
                        raise e
            
            # Log insert operation with timing
            insert_start = datetime.utcnow()
            logging.info(f"Inserting {len(rows)} rows into {self.table_name}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            insert_duration = (datetime.utcnow() - insert_start).total_seconds()
            
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
                
                # Notify about insert errors
                try:
                    notify_error(
                        title="BigQuery Insert Errors",
                        message=f"Encountered {len(result)} errors inserting referee data",
                        details={
                            'table_id': table_id,
                            'rows_attempted': len(rows),
                            'error_count': len(result),
                            'errors': str(result)[:500]
                        },
                        processor_name="NBA.com Referee Processor"
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
            else:
                logging.info(f"Successfully inserted {len(rows)} rows to {self.table_name} ({insert_duration:.2f}s)")
                
                # Verify row count post-insertion
                game_date = rows[0].get('game_date') if rows else None
                verify_query = f"""
                SELECT COUNT(*) as count 
                FROM `{table_id}` 
                WHERE source_file_path = '{file_path}'
                AND game_date = '{game_date}'
                """
                try:
                    actual_count = list(self.bq_client.query(verify_query))[0].count
                    if actual_count != len(rows):
                        logging.error(f"ROW COUNT MISMATCH! Expected {len(rows)}, got {actual_count}")
                        
                        # Notify about row count mismatch
                        try:
                            notify_warning(
                                title="Referee Row Count Mismatch",
                                message=f"Row count mismatch after insert: expected {len(rows)}, got {actual_count}",
                                details={
                                    'expected': len(rows),
                                    'actual': actual_count,
                                    'difference': abs(len(rows) - actual_count),
                                    'game_date': game_date
                                }
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                    else:
                        logging.info(f"Row count verified: {actual_count} rows")
                except Exception as verify_error:
                    logging.warning(f"Could not verify row count: {verify_error}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading referee assignments data: {error_msg}")
            
            # Notify about load failure
            try:
                notify_error(
                    title="Referee Data Load Failed",
                    message=f"Failed to load referee assignment data: {error_msg}",
                    details={
                        'table_id': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Referee Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}
    
    def load_replay_center_data(self, replay_rows: List[Dict]) -> Dict:
        """Load replay center data with duplicate detection and verification."""
        if not replay_rows:
            return {'rows_processed': 0, 'errors': []}
        
        # Check for duplicates in replay center data
        unique_keys = set()
        duplicates = []
        for row in replay_rows:
            key = (row['game_date'], row['official_code'])
            if key in unique_keys:
                duplicates.append(key)
            unique_keys.add(key)
        
        if duplicates:
            logging.warning(f"Found {len(duplicates)} duplicate replay center keys: {duplicates}")
            
            # Notify about replay center duplicates
            try:
                notify_warning(
                    title="Replay Center Duplicates Detected",
                    message=f"Found {len(duplicates)} duplicate replay center records",
                    details={
                        'duplicate_count': len(duplicates),
                        'sample_duplicates': str(duplicates[:3]),
                        'total_rows': len(replay_rows)
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        table_id = f"{self.project_id}.{self.replay_table_name}"
        errors = []
        file_path = replay_rows[0].get('source_file_path', 'unknown') if replay_rows else 'unknown'
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Get unique game_dates from the data to delete
                game_dates = set(row['game_date'] for row in replay_rows if row['game_date'])
                
                for game_date in game_dates:
                    delete_start = datetime.utcnow()
                    delete_query = f"""
                    DELETE FROM `{table_id}` 
                    WHERE game_date = '{game_date}'
                    """
                    
                    try:
                        self.bq_client.query(delete_query).result()
                        delete_duration = (datetime.utcnow() - delete_start).total_seconds()
                        logging.info(f"Deleted existing replay center data for {game_date} ({delete_duration:.2f}s)")
                    except Exception as e:
                        logging.error(f"Error deleting replay center data: {e}")
                        
                        # Notify about delete failure
                        try:
                            notify_error(
                                title="Replay Center Delete Failed",
                                message=f"Failed to delete existing replay center data: {str(e)}",
                                details={
                                    'game_date': game_date,
                                    'table_id': table_id,
                                    'error_type': type(e).__name__
                                },
                                processor_name="NBA.com Referee Processor"
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                        
                        raise e
            
            # Enhanced insert logging with timing
            insert_start = datetime.utcnow()
            logging.info(f"Inserting {len(replay_rows)} replay center rows")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, replay_rows)
            insert_duration = (datetime.utcnow() - insert_start).total_seconds()
            
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery replay center insert errors: {errors}")
                
                # Notify about replay center insert errors
                try:
                    notify_error(
                        title="Replay Center Insert Errors",
                        message=f"Encountered {len(result)} errors inserting replay center data",
                        details={
                            'table_id': table_id,
                            'rows_attempted': len(replay_rows),
                            'error_count': len(result),
                            'errors': str(result)[:500]
                        },
                        processor_name="NBA.com Referee Processor"
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
            else:
                logging.info(f"Successfully inserted {len(replay_rows)} rows to {self.replay_table_name} ({insert_duration:.2f}s)")
                
                # Verify replay center row count
                verify_query = f"""
                SELECT COUNT(*) as count 
                FROM `{table_id}` 
                WHERE source_file_path = '{file_path}'
                """
                try:
                    actual_count = list(self.bq_client.query(verify_query))[0].count
                    if actual_count != len(replay_rows):
                        logging.error(f"REPLAY CENTER ROW COUNT MISMATCH! Expected {len(replay_rows)}, got {actual_count}")
                        
                        # Notify about replay center row count mismatch
                        try:
                            notify_warning(
                                title="Replay Center Row Count Mismatch",
                                message=f"Row count mismatch: expected {len(replay_rows)}, got {actual_count}",
                                details={
                                    'expected': len(replay_rows),
                                    'actual': actual_count,
                                    'difference': abs(len(replay_rows) - actual_count)
                                }
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                    else:
                        logging.info(f"Replay center row count verified: {actual_count} rows")
                except Exception as verify_error:
                    logging.warning(f"Could not verify replay center row count: {verify_error}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading replay center data: {error_msg}")
            
            # Notify about replay center load failure
            try:
                notify_error(
                    title="Replay Center Load Failed",
                    message=f"Failed to load replay center data: {error_msg}",
                    details={
                        'table_id': table_id,
                        'rows_attempted': len(replay_rows),
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Referee Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {'rows_processed': len(replay_rows) if not errors else 0, 'errors': errors}
    
    def process_file(self, file_path: str, **kwargs) -> Dict:
        """Process a single referee assignments file with enhanced validation."""
        try:
            logging.info(f"Processing referee file: {file_path}")
            
            # Read file content directly
            from google.cloud import storage
            storage_client = storage.Client()
            
            # Parse file path to get bucket and blob path
            if file_path.startswith('gs://'):
                path_parts = file_path[5:].split('/', 1)  # Remove 'gs://' and split once
                bucket_name = path_parts[0]
                blob_path = path_parts[1]
            else:
                raise ValueError(f"Invalid file path format: {file_path}")
            
            # Read file
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            content = blob.download_as_text()
            raw_data = json.loads(content)
            
            # Validate data
            validation_errors = self.validate_data(raw_data)
            
            if validation_errors:
                logging.warning(f"Validation errors for {file_path}: {validation_errors}")
                return {
                    'file_path': file_path,
                    'status': 'validation_failed',
                    'errors': validation_errors,
                    'game_assignments_processed': 0,
                    'replay_center_processed': 0,
                    'expected_game_assignments': 0,
                    'expected_replay_center': 0
                }
            
            # Transform data
            game_rows = self.transform_data(raw_data, file_path)
            replay_rows = self.transform_replay_center_data(raw_data, file_path)
            
            # Log expected counts before processing
            logging.info(f"Expected: {len(game_rows)} game assignments, {len(replay_rows)} replay center records")
            
            # Transform and load game assignments
            game_result = self.load_data(game_rows, **kwargs)
            
            # Transform and load replay center data
            replay_result = self.load_replay_center_data(replay_rows)
            
            # Enhanced result validation
            game_processed = game_result.get('rows_processed', 0)
            replay_processed = replay_result.get('rows_processed', 0)
            
            # Validate expectations vs actuals
            if game_processed != len(game_rows):
                logging.warning(f"GAME ASSIGNMENT COUNT MISMATCH! Expected {len(game_rows)}, processed {game_processed}")
            
            if replay_processed != len(replay_rows):
                logging.warning(f"REPLAY CENTER COUNT MISMATCH! Expected {len(replay_rows)}, processed {replay_processed}")
            
            all_errors = game_result.get('errors', []) + replay_result.get('errors', [])
            status = 'success' if not all_errors else 'partial_success' if (game_processed > 0 or replay_processed > 0) else 'failed'
            
            # Enhanced completion logging
            logging.info(f"Processed {file_path}: {game_processed} game assignments, {replay_processed} replay center records (status: {status})")
            
            # Send success notification if no errors
            if status == 'success':
                try:
                    notify_info(
                        title="Referee Processing Complete",
                        message=f"Successfully processed referee data",
                        details={
                            'file_path': file_path,
                            'game_assignments': game_processed,
                            'replay_center': replay_processed
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'file_path': file_path,
                'status': status,
                'game_assignments_processed': game_processed,
                'replay_center_processed': replay_processed,
                'expected_game_assignments': len(game_rows),
                'expected_replay_center': len(replay_rows),
                'errors': all_errors
            }
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error processing referee file {file_path}: {error_msg}")
            
            # Notify about file processing failure
            try:
                notify_error(
                    title="Referee File Processing Failed",
                    message=f"Error processing referee file: {error_msg}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__
                    },
                    processor_name="NBA.com Referee Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'file_path': file_path,
                'status': 'error',
                'error': error_msg,
                'game_assignments_processed': 0,
                'replay_center_processed': 0,
                'expected_game_assignments': 0,
                'expected_replay_center': 0
            }