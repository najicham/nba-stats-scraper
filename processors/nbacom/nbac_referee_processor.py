#!/usr/bin/env python3
# File: processors/nbacom/nbac_referee_processor.py
# Description: Processor for NBA.com referee assignments data transformation

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

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
            
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform game referee assignments into normalized rows."""
        rows = []
        
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
    
    def transform_replay_center_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform replay center officials data."""
        rows = []
        
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
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load game assignment data into BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Get unique game_dates from the data to delete
                game_dates = set(row['game_date'] for row in rows if row['game_date'])
                
                for game_date in game_dates:
                    delete_query = f"""
                    DELETE FROM `{table_id}` 
                    WHERE game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result()
                    logging.info(f"Deleted existing referee assignments for {game_date}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully inserted {len(rows)} rows to {self.table_name}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading referee assignments data: {error_msg}")
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}
    
    def load_replay_center_data(self, replay_rows: List[Dict]) -> Dict:
        """Load replay center data into separate table."""
        if not replay_rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.replay_table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Get unique game_dates from the data to delete
                game_dates = set(row['game_date'] for row in replay_rows if row['game_date'])
                
                for game_date in game_dates:
                    delete_query = f"""
                    DELETE FROM `{table_id}` 
                    WHERE game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result()
                    logging.info(f"Deleted existing replay center data for {game_date}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, replay_rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully inserted {len(replay_rows)} rows to {self.replay_table_name}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading replay center data: {error_msg}")
        
        return {'rows_processed': len(replay_rows) if not errors else 0, 'errors': errors}
    
    def process_file(self, file_path: str, **kwargs) -> Dict:
        """Process a single referee assignments file."""
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
                    'replay_center_processed': 0
                }
            
            # Transform and load game assignments
            game_rows = self.transform_data(raw_data, file_path)
            game_result = self.load_data(game_rows, **kwargs)
            
            # Transform and load replay center data
            replay_rows = self.transform_replay_center_data(raw_data, file_path)
            replay_result = self.load_replay_center_data(replay_rows)
            
            all_errors = game_result.get('errors', []) + replay_result.get('errors', [])
            status = 'success' if not all_errors else 'partial_success' if (game_result.get('rows_processed', 0) > 0 or replay_result.get('rows_processed', 0) > 0) else 'failed'
            
            logging.info(f"Processed {file_path}: {game_result.get('rows_processed', 0)} game assignments, {replay_result.get('rows_processed', 0)} replay center records")
            
            return {
                'file_path': file_path,
                'status': status,
                'game_assignments_processed': game_result.get('rows_processed', 0),
                'replay_center_processed': replay_result.get('rows_processed', 0),
                'errors': all_errors
            }
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error processing referee file {file_path}: {error_msg}")
            return {
                'file_path': file_path,
                'status': 'error',
                'error': error_msg,
                'game_assignments_processed': 0,
                'replay_center_processed': 0
            }