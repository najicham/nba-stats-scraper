#!/usr/bin/env python3
# File: processors/nbacom/nbac_referee_processor.py
# Description: Processor for NBA.com referee assignments data transformation
# Version 2.0 - Refactored to use batch loading + MERGE pattern
# Follows best practices from BigQuery Lessons Learned document

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
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
        
        # Initialize BigQuery client and project ID
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Get table schemas for enforcement
        self.main_table = None
        self.replay_table = None
        self._load_table_schemas()
    
    def _load_table_schemas(self):
        """Load table schemas for schema enforcement."""
        try:
            main_table_id = f"{self.project_id}.{self.table_name}"
            self.main_table = self.bq_client.get_table(main_table_id)
            
            replay_table_id = f"{self.project_id}.{self.replay_table_name}"
            self.replay_table = self.bq_client.get_table(replay_table_id)
            
            logging.info(f"Loaded schemas for {self.table_name} and {self.replay_table_name}")
        except NotFound as e:
            logging.error(f"Table not found: {e}")
            raise
    
    def normalize_text(self, text: str) -> str:
        """Normalize text for data consistency."""
        if not text:
            return ""
        normalized = text.strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized
    
    def extract_scrape_timestamp(self, raw_data: Dict) -> Optional[datetime]:
        """Extract scrape timestamp from raw data if available."""
        timestamp_str = raw_data.get('timestamp') or raw_data.get('fetchedUtc')
        if not timestamp_str:
            return None
            
        try:
            if timestamp_str.endswith('Z'):
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            elif '+' in timestamp_str or timestamp_str.endswith('+00:00'):
                return datetime.fromisoformat(timestamp_str)
            else:
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
    
    def ensure_required_defaults(self, record: Dict, table_schema: bigquery.Table) -> Dict:
        """Ensure all REQUIRED fields have non-null values."""
        output = dict(record)
        current_utc = datetime.now(timezone.utc)
        
        # Get required field names from schema
        required_fields = {
            field.name: field for field in table_schema.schema 
            if field.mode == 'REQUIRED'
        }
        
        # Ensure required timestamp fields have values
        if 'created_at' in required_fields and not output.get('created_at'):
            output['created_at'] = current_utc
        if 'processed_at' in required_fields and not output.get('processed_at'):
            output['processed_at'] = current_utc
            
        # Ensure other required fields have non-null values
        for field_name, field in required_fields.items():
            if not output.get(field_name):
                if field.field_type == 'STRING':
                    output[field_name] = ''
                elif field.field_type == 'INT64':
                    output[field_name] = 0
                # Don't default DATE or TIMESTAMP - these should be present
                    
        return output
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform game referee assignments into normalized rows."""
        rows = []
        
        try:
            scrape_timestamp = self.extract_scrape_timestamp(raw_data)
            nba_assignments = raw_data['refereeAssignments']['nba']['Table']['rows']
            
            for game_row in nba_assignments:
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
                        
                season = game_row.get('season', '')
                
                # Process each official (1-4 officials per game)
                for official_num in range(1, 5):
                    official_key = f'official{official_num}'
                    official_code_key = f'official{official_num}_code'
                    official_jnum_key = f'official{official_num}_JNum'
                    
                    official_name = game_row.get(official_key)
                    official_code = game_row.get(official_code_key)
                    official_jersey = game_row.get(official_jnum_key)
                    
                    if not official_name or not official_code:
                        continue
                    
                    row = {
                        'game_id': game_id,
                        'game_date': game_date.isoformat() if game_date else None,
                        'season': season,
                        'game_code': game_row.get('game_code', ''),
                        'home_team_id': game_row.get('home_team_id'),
                        'home_team': self.normalize_text(game_row.get('home_team', '')),
                        'home_team_abbr': game_row.get('home_team_abbr', ''),
                        'away_team_id': game_row.get('away_team_id'),
                        'away_team': self.normalize_text(game_row.get('away_team', '')),
                        'away_team_abbr': game_row.get('away_team_abbr', ''),
                        'official_position': official_num,
                        'official_name': self.normalize_text(official_name),
                        'official_code': official_code,
                        'official_jersey_number': official_jersey,
                        'source_file_path': file_path,
                        'scrape_timestamp': scrape_timestamp.isoformat() if scrape_timestamp else None,
                        'created_at': datetime.utcnow().isoformat(),
                        'processed_at': datetime.utcnow().isoformat()
                    }
                    
                    rows.append(row)
            
            return rows
            
        except Exception as e:
            logging.error(f"Error in transform_data: {e}")
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
            scrape_timestamp = self.extract_scrape_timestamp(raw_data)
            
            nba_data = raw_data.get('refereeAssignments', {}).get('nba', {})
            if 'Table1' not in nba_data or 'rows' not in nba_data['Table1']:
                return rows
                
            replay_rows = nba_data['Table1']['rows']
            
            for replay_row in replay_rows:
                game_date_str = replay_row.get('game_date', '')
                
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
    
    def load_data_with_merge(self, rows: List[Dict], table_id: str, table_schema: bigquery.Table) -> Dict:
        """
        Load data using batch loading + MERGE pattern.
        Follows best practices from BigQuery Lessons Learned document.
        """
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        temp_table_id = None
        
        try:
            # 1. Create temporary table
            temp_table_name = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
            temp_table_id = f"{self.project_id}.{temp_table_name}"
            
            temp_table = bigquery.Table(temp_table_id, schema=table_schema.schema)
            self.bq_client.create_table(temp_table)
            logging.info(f"Created temp table: {temp_table_id}")
            
            # 2. Validate and prepare data
            validated_rows = [
                self.ensure_required_defaults(row, table_schema) 
                for row in rows
            ]
            
            # 3. Batch load to temp table (NO streaming buffer)
            job_config = bigquery.LoadJobConfig(
                schema=table_schema.schema,  # Enforce exact schema
                autodetect=False,            # No inference
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                ignore_unknown_values=True
            )
            
            load_start = datetime.utcnow()
            load_job = self.bq_client.load_table_from_json(
                validated_rows, 
                temp_table_id, 
                job_config=job_config
            )
            load_job.result()  # Wait for completion
            load_duration = (datetime.utcnow() - load_start).total_seconds()
            
            logging.info(f"✅ Data loaded to temp table: {len(rows)} rows ({load_duration:.2f}s)")
            
            # 4. MERGE from temp table to target table
            full_table_id = f"{self.project_id}.{table_id}"
            
            # Get unique game dates for partition filter
            game_dates = list(set(row['game_date'] for row in rows if row['game_date']))
            if not game_dates:
                logging.error("No valid game_dates found in rows")
                return {'rows_processed': 0, 'errors': ['No valid game_dates']}
            
            game_dates_str = "', '".join(game_dates)
            
            # Determine merge key and query based on table
            if 'replay_center' in table_id:
                merge_key = "T.game_date = S.game_date AND T.official_code = S.official_code"
                
                # For replay center, use filtered MERGE to satisfy partition requirement
                merge_query = f"""
                MERGE `{full_table_id}` AS T
                USING (
                    SELECT * FROM `{temp_table_id}`
                ) AS S
                ON {merge_key}
                    AND T.game_date IN ('{game_dates_str}')
                WHEN MATCHED THEN
                    UPDATE SET
                        official_name = S.official_name,
                        source_file_path = S.source_file_path,
                        scrape_timestamp = S.scrape_timestamp,
                        processed_at = S.processed_at
                WHEN NOT MATCHED BY TARGET THEN
                    INSERT ROW
                """
            else:
                merge_key = """
                    T.game_id = S.game_id 
                    AND T.official_position = S.official_position 
                    AND T.official_code = S.official_code
                """
                
                # For game assignments, use filtered MERGE to satisfy partition requirement
                merge_query = f"""
                MERGE `{full_table_id}` AS T
                USING (
                    SELECT * FROM `{temp_table_id}`
                ) AS S
                ON {merge_key}
                    AND T.game_date IN ('{game_dates_str}')
                WHEN MATCHED THEN
                    UPDATE SET
                        game_date = S.game_date,
                        season = S.season,
                        game_code = S.game_code,
                        home_team_id = S.home_team_id,
                        home_team = S.home_team,
                        home_team_abbr = S.home_team_abbr,
                        away_team_id = S.away_team_id,
                        away_team = S.away_team,
                        away_team_abbr = S.away_team_abbr,
                        official_name = S.official_name,
                        official_jersey_number = S.official_jersey_number,
                        source_file_path = S.source_file_path,
                        scrape_timestamp = S.scrape_timestamp,
                        processed_at = S.processed_at
                WHEN NOT MATCHED BY TARGET THEN
                    INSERT ROW
                """
            
            merge_start = datetime.utcnow()
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            merge_duration = (datetime.utcnow() - merge_start).total_seconds()
            
            logging.info(f"✅ MERGE completed successfully ({merge_duration:.2f}s)")
            
            return {
                'rows_processed': len(rows),
                'errors': [],
                'merge_stats': {
                    'rows_inserted': merge_result.num_dml_affected_rows if hasattr(merge_result, 'num_dml_affected_rows') else None
                }
            }
            
        except Exception as e:
            error_msg = str(e)
            
            # Check for streaming buffer conflict
            if "streaming buffer" in error_msg.lower():
                logging.warning(f"⚠️  MERGE blocked by streaming buffer - {len(rows)} records skipped")
                logging.info("Records will be processed on next run when buffer clears")
                
                try:
                    notify_warning(
                        title="Referee MERGE Blocked by Streaming Buffer",
                        message=f"MERGE operation blocked - {len(rows)} records skipped (will retry next run)",
                        details={
                            'table_id': table_id,
                            'rows_skipped': len(rows),
                            'reason': 'streaming_buffer_conflict'
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                # Graceful failure - return success with note
                return {
                    'rows_processed': 0,
                    'errors': [],
                    'skipped': len(rows),
                    'reason': 'streaming_buffer'
                }
            else:
                # Real error - log and notify
                logging.error(f"Error in MERGE operation: {error_msg}")
                
                try:
                    notify_error(
                        title="Referee MERGE Failed",
                        message=f"Failed to merge referee data: {error_msg}",
                        details={
                            'table_id': table_id,
                            'rows_attempted': len(rows),
                            'error_type': type(e).__name__
                        },
                        processor_name="NBA.com Referee Processor"
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                return {
                    'rows_processed': 0,
                    'errors': [error_msg]
                }
        
        finally:
            # 5. Always cleanup temp table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logging.info(f"Cleaned up temp table: {temp_table_id}")
                except Exception as cleanup_error:
                    logging.warning(f"Failed to cleanup temp table: {cleanup_error}")
    
    def process_file(self, file_path: str, **kwargs) -> Dict:
        """Process a single referee assignments file."""
        try:
            logging.info(f"Processing referee file: {file_path}")
            
            # Read file content
            from google.cloud import storage
            storage_client = storage.Client()
            
            if file_path.startswith('gs://'):
                path_parts = file_path[5:].split('/', 1)
                bucket_name = path_parts[0]
                blob_path = path_parts[1]
            else:
                raise ValueError(f"Invalid file path format: {file_path}")
            
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
                    'replay_center_processed': 0
                }
            
            # Transform data
            game_rows = self.transform_data(raw_data, file_path)
            replay_rows = self.transform_replay_center_data(raw_data, file_path)
            
            logging.info(f"Transformed: {len(game_rows)} game assignments, {len(replay_rows)} replay center records")
            
            # Load game assignments using MERGE
            game_result = self.load_data_with_merge(
                game_rows, 
                self.table_name, 
                self.main_table
            )
            
            # Load replay center data using MERGE
            replay_result = self.load_data_with_merge(
                replay_rows, 
                self.replay_table_name, 
                self.replay_table
            )
            
            # Process results
            game_processed = game_result.get('rows_processed', 0)
            replay_processed = replay_result.get('rows_processed', 0)
            game_skipped = game_result.get('skipped', 0)
            replay_skipped = replay_result.get('skipped', 0)
            
            all_errors = game_result.get('errors', []) + replay_result.get('errors', [])
            
            if all_errors:
                status = 'failed'
            elif game_skipped > 0 or replay_skipped > 0:
                status = 'skipped'
            else:
                status = 'success'
            
            logging.info(
                f"Processed {file_path}: {game_processed} game assignments, "
                f"{replay_processed} replay center records (status: {status})"
            )
            
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
                'game_assignments_skipped': game_skipped,
                'replay_center_skipped': replay_skipped,
                'errors': all_errors
            }
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error processing referee file {file_path}: {error_msg}")
            
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
                'replay_center_processed': 0
            }