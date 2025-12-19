#!/usr/bin/env python3
# File: processors/bigdataball/bigdataball_pbp_processor.py
# Description: Processor for BigDataBall play-by-play data transformation
# UPDATED: Now handles both CSV and JSON formats

import os
import json
import logging
import re
import io
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Notification imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class BigDataBallPbpProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process BigDataBall play-by-play data with smart idempotency.
    """

    # Smart idempotency: Hash meaningful play-by-play event fields only
    HASH_FIELDS = [
        'game_id',
        'event_sequence',
        'period',
        'game_clock',
        'event_type',
        'event_subtype',
        'score_home',
        'score_away',
        'player_1_name',
        'player_2_name',
        'player_3_name',
        'shot_made',
        'shot_type',
        'points_scored'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bigdataball_play_by_play'
        self.processing_strategy = 'MERGE_UPDATE'

        # CRITICAL: These two lines are REQUIRED for all processors
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
    def parse_json(self, json_content: str, file_path: str) -> Dict:
        """
        Parse BigDataBall data - handles BOTH JSON and CSV formats.
        
        Args:
            json_content: File content (either JSON or CSV format)
            file_path: GCS file path for context
            
        Returns:
            Standardized dict with 'game_info' and 'playByPlay' keys
        """
        try:
            # Try JSON first (backward compatibility with existing files)
            data = json.loads(json_content)
            logging.info(f"Parsed as JSON format: {file_path}")
            return data
            
        except json.JSONDecodeError:
            # Not JSON - try CSV format
            logging.info(f"JSON parse failed, trying CSV format: {file_path}")
            
            try:
                # Read CSV content
                df = pd.read_csv(io.StringIO(json_content))
                
                if df.empty:
                    raise ValueError("CSV file is empty")
                
                # Extract game info from first row
                first_row = df.iloc[0]
                
                # Extract team names from filename
                # Pattern: [2024-10-22]-0022400001-NYK@BOS.csv
                filename = os.path.basename(file_path)
                teams = self._extract_teams_from_filename(filename)
                
                # Build standardized structure matching JSON format
                game_info = {
                    'game_id': str(first_row.get('game_id', '')),
                    'date': str(first_row.get('date', '')),
                    'data_set': str(first_row.get('data_set', '')),
                    'away_team': teams['away_team'],
                    'home_team': teams['home_team']
                }
                
                # Convert DataFrame to dict records, handling NaN values
                play_records = df.to_dict('records')
                
                # Clean up NaN values
                import math
                for record in play_records:
                    for key, value in record.items():
                        if pd.isna(value) or (isinstance(value, float) and math.isnan(value)):
                            record[key] = None
                
                # Return in same format as JSON files
                data = {
                    'file_info': {
                        'name': filename,
                        'processed_at': datetime.utcnow().isoformat(),
                        'total_plays': len(df),
                        'columns': df.columns.tolist()
                    },
                    'game_info': game_info,
                    'playByPlay': play_records
                }
                
                logging.info(f"Successfully parsed CSV: {len(play_records)} plays")
                return data
                
            except Exception as csv_error:
                logging.error(f"Failed to parse as CSV: {csv_error}")
                
                # Notify parse failure
                try:
                    notify_error(
                        title="BigDataBall Play-by-Play Parse Failed",
                        message=f"Failed to parse file as both JSON and CSV: {str(csv_error)}",
                        details={
                            'file_path': file_path,
                            'json_error': 'JSONDecodeError',
                            'csv_error': str(csv_error),
                            'content_preview': json_content[:200]
                        },
                        processor_name="BigDataBall Play-by-Play Processor"
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(f"Could not parse file as JSON or CSV: {csv_error}")
    
    def _extract_teams_from_filename(self, filename: str) -> Dict[str, str]:
        """
        Extract team abbreviations from filename.
        Pattern: [2024-10-22]-0022400001-NYK@BOS.csv
        """
        import re
        
        # Try to match the standard pattern
        pattern = r'\[[\d-]+\]-\d+-(.+)@(.+)\.csv'
        match = re.search(pattern, filename)
        
        if match:
            return {
                'away_team': match.group(1),
                'home_team': match.group(2)
            }
        
        # Fallback if pattern doesn't match
        logging.warning(f"Could not extract teams from filename: {filename}")
        return {
            'away_team': 'UNK',
            'home_team': 'UNK'
        }
    
    def normalize_player_name(self, name: str) -> str:
        """Convert player name to lookup format: 'LeBron James' -> 'lebronjames'"""
        if not name:
            return ""
        
        # Remove common suffixes
        name = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV)$', '', name, flags=re.IGNORECASE)
        
        # Convert to lowercase and remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', name.lower())
        return normalized
    
    def construct_game_id(self, game_date: str, away_team: str, home_team: str) -> str:
        """Construct consistent game_id format: '20241101_NYK_DET'"""
        date_part = game_date.replace('-', '')
        return f"{date_part}_{away_team}_{home_team}"
    
    def parse_game_date(self, date_str: str) -> tuple:
        """
        Parse game date and return (iso_date_string, season_year)
        Handles both formats: '11/12/2024' and '2024-11-12'
        """
        if '/' in date_str:
            # Format: MM/DD/YYYY
            month, day, year = date_str.split('/')
            iso_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            year_int = int(year)
        else:
            # Format: YYYY-MM-DD
            iso_date = date_str
            year_int = int(date_str.split('-')[0])
        
        # Extract month for season determination
        month_int = int(iso_date.split('-')[1])
        
        # Determine season year (October+ = new season starts)
        if month_int >= 10:
            season_year = year_int
        else:
            season_year = year_int - 1
        
        return iso_date, season_year
    
    def determine_player_role(self, event: Dict) -> Optional[str]:
        """Determine the role of player_2 based on event data"""
        if event.get('assist'):
            return 'assist'
        elif event.get('block'):
            return 'block'
        elif event.get('steal'):
            return 'steal'
        elif event.get('away') and event.get('event_type') == 'jump ball':
            return 'jump_ball_away'
        elif event.get('entered'):
            return 'substitution_in'
        elif event.get('possession'):
            return 'possession'
        return None
    
    def determine_player_3_role(self, event: Dict) -> Optional[str]:
        """Determine the role of player_3 based on event data"""
        if event.get('home') and event.get('event_type') == 'jump ball':
            return 'jump_ball_home'
        elif event.get('left'):
            return 'substitution_out'
        return None
    
    def get_player_2_name(self, event: Dict) -> Optional[str]:
        """Get player_2 name based on event context"""
        if event.get('assist'):
            return event.get('assist')
        elif event.get('block'):
            return event.get('block')
        elif event.get('steal'):
            return event.get('steal')
        elif event.get('away') and event.get('event_type') == 'jump ball':
            return event.get('away')
        elif event.get('entered'):
            return event.get('entered')
        elif event.get('possession'):
            return event.get('possession')
        return None
    
    def get_player_3_name(self, event: Dict) -> Optional[str]:
        """Get player_3 name based on event context"""
        if event.get('home') and event.get('event_type') == 'jump ball':
            return event.get('home')
        elif event.get('left'):
            return event.get('left')
        return None
    
    def convert_time_to_seconds(self, time_str: str) -> Optional[int]:
        """Convert time string '0:11:40' to seconds"""
        if not time_str:
            return None
        try:
            parts = time_str.split(':')
            if len(parts) == 3:  # H:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            return None
        except (ValueError, IndexError):
            return None
    
    def determine_shot_type(self, event_type: str) -> Optional[str]:
        """Map BigDataBall shot types to standard format"""
        if not event_type:
            return None
        
        event_type_lower = event_type.lower()
        
        if '3pt' in event_type_lower:
            return '3PT'
        elif 'free throw' in event_type_lower or 'ft' in event_type_lower:
            return 'FT'
        else:
            return '2PT'
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate required fields in BigDataBall data"""
        errors = []
        
        if 'game_info' not in data:
            errors.append("Missing game_info")
            return errors
            
        game_info = data['game_info']
        required_fields = ['game_id', 'date', 'away_team', 'home_team']
        for field in required_fields:
            if field not in game_info:
                errors.append(f"Missing game_info.{field}")
        
        if 'playByPlay' not in data:
            errors.append("Missing playByPlay")
        elif not isinstance(data['playByPlay'], list):
            errors.append("playByPlay is not a list")
        elif len(data['playByPlay']) == 0:
            errors.append("playByPlay is empty")
        
        # Notify if validation errors found
        if errors:
            try:
                notify_error(
                    title="BigDataBall Play-by-Play Validation Failed",
                    message=f"Data validation errors: {', '.join(errors)}",
                    details={
                        'game_id': game_info.get('game_id') if 'game_info' in data else 'unknown',
                        'errors': errors,
                        'has_game_info': 'game_info' in data,
                        'has_playbyplay': 'playByPlay' in data
                    },
                    processor_name="BigDataBall Play-by-Play Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform BigDataBall JSON to BigQuery rows"""
        game_info = raw_data['game_info']
        play_by_play = raw_data['playByPlay']
        
        # Parse date and determine season
        game_date_raw = game_info['date']
        game_date, season_year = self.parse_game_date(game_date_raw)

        # Construct consistent game_id
        game_id = self.construct_game_id(
            game_date,  # Use ISO format date
            game_info['away_team'], 
            game_info['home_team']
        )
        
        rows = []
        
        for event in play_by_play:
            # Determine player roles and names
            player_2_name = self.get_player_2_name(event)
            player_2_role = self.determine_player_role(event)
            player_3_name = self.get_player_3_name(event)
            player_3_role = self.determine_player_3_role(event)
            
            row = {
                # Core Game Identifiers
                'game_id': game_id,
                'bdb_game_id': event.get('game_id'),
                'game_date': game_date,
                'season_year': season_year,
                'data_set': event.get('data_set'),
                'home_team_abbr': game_info['home_team'],
                'away_team_abbr': game_info['away_team'],
                
                # Event Identifiers
                'event_id': f"{game_id}_{event.get('play_id')}",
                'event_sequence': int(event.get('play_id')) if event.get('play_id') is not None else None,
                'period': int(event.get('period')) if event.get('period') is not None else None,
                
                # Game Clock
                'game_clock': event.get('remaining_time'),
                'game_clock_seconds': self.convert_time_to_seconds(event.get('remaining_time')),
                'elapsed_time': event.get('elapsed'),
                'elapsed_seconds': self.convert_time_to_seconds(event.get('elapsed')),
                'play_length': event.get('play_length'),
                'play_length_seconds': self.convert_time_to_seconds(event.get('play_length')),
                
                # Event Details
                'event_type': event.get('event_type'),
                'event_subtype': event.get('type'),
                'event_description': event.get('description'),
                
                # Score Tracking
                'score_home': int(event.get('home_score')) if event.get('home_score') is not None else None,
                'score_away': int(event.get('away_score')) if event.get('away_score') is not None else None,
                
                # Primary Player
                'player_1_name': event.get('player'),
                'player_1_lookup': self.normalize_player_name(event.get('player')) if event.get('player') else None,
                'player_1_team_abbr': event.get('team'),
                
                # Secondary Player
                'player_2_name': player_2_name,
                'player_2_lookup': self.normalize_player_name(player_2_name) if player_2_name else None,
                'player_2_team_abbr': None,
                'player_2_role': player_2_role,
                
                # Tertiary Player
                'player_3_name': player_3_name,
                'player_3_lookup': self.normalize_player_name(player_3_name) if player_3_name else None,
                'player_3_team_abbr': None,
                'player_3_role': player_3_role,
                
                # Shot Details
                'shot_made': event.get('result') == 'made' if event.get('event_type') == 'shot' else None,
                'shot_type': self.determine_shot_type(event.get('type')) if event.get('event_type') == 'shot' else None,
                'shot_distance': event.get('shot_distance'),
                'points_scored': int(event.get('points')) if event.get('points') is not None else None,
                
                # Shot Coordinates
                'original_x': event.get('original_x'),
                'original_y': event.get('original_y'),
                'converted_x': event.get('converted_x'),
                'converted_y': event.get('converted_y'),
                
                # Lineup Data (lookup-only)
                'away_player_1_lookup': self.normalize_player_name(event.get('a1')) if event.get('a1') else None,
                'away_player_2_lookup': self.normalize_player_name(event.get('a2')) if event.get('a2') else None,
                'away_player_3_lookup': self.normalize_player_name(event.get('a3')) if event.get('a3') else None,
                'away_player_4_lookup': self.normalize_player_name(event.get('a4')) if event.get('a4') else None,
                'away_player_5_lookup': self.normalize_player_name(event.get('a5')) if event.get('a5') else None,
                'home_player_1_lookup': self.normalize_player_name(event.get('h1')) if event.get('h1') else None,
                'home_player_2_lookup': self.normalize_player_name(event.get('h2')) if event.get('h2') else None,
                'home_player_3_lookup': self.normalize_player_name(event.get('h3')) if event.get('h3') else None,
                'home_player_4_lookup': self.normalize_player_name(event.get('h4')) if event.get('h4') else None,
                'home_player_5_lookup': self.normalize_player_name(event.get('h5')) if event.get('h5') else None,
                
                # Additional BigDataBall Fields
                'possession_player_name': event.get('possession'),
                'possession_player_lookup': self.normalize_player_name(event.get('possession')) if event.get('possession') else None,
                'reason': event.get('reason'),
                'opponent': event.get('opponent'),
                'num': event.get('num'),
                'outof': event.get('outof'),
                
                # Processing Metadata
                'source_file_path': file_path,
                'csv_filename': raw_data.get('file_info', {}).get('name'),
                'csv_row_number': None,
                'processed_at': datetime.utcnow().isoformat(),
                'created_at': datetime.utcnow().isoformat()
            }
            
            rows.append(row)

        self.transformed_data = rows

        # Add smart idempotency hash to each row
        self.add_data_hash()

    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load data to BigQuery using streaming-compatible strategy"""
        if not rows:
            logging.warning("No rows to load")
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            game_id = rows[0]['game_id']
            game_date = rows[0]['game_date']
            
            # Check if this is the first file for this game today
            check_query = f"""
            SELECT COUNT(*) as existing_rows
            FROM `{table_id}` 
            WHERE game_id = '{game_id}' AND game_date = '{game_date}'
            """
            
            query_job = self.bq_client.query(check_query)
            result = query_job.result()
            existing_rows = next(result).existing_rows
            
            if existing_rows > 0:
                # Data already exists - this is likely a duplicate file for the same game
                logging.info(f"Game {game_id} already has {existing_rows} rows - skipping to avoid streaming buffer conflict")
                
                # Notify duplicate processing attempt
                try:
                    notify_warning(
                        title="BigDataBall Play-by-Play Duplicate Game Skipped",
                        message=f"Game {game_id} already processed with {existing_rows} rows - skipping to avoid conflicts",
                        details={
                            'game_id': game_id,
                            'game_date': game_date,
                            'existing_rows': existing_rows,
                            'attempted_rows': len(rows)
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                return {
                    'rows_processed': 0, 
                    'errors': [],
                    'game_id': game_id,
                    'message': f'Skipped - game already processed with {existing_rows} rows'
                }
            else:
                # First time processing this game - safe to insert
                # Use batch loading (not streaming insert) to avoid DML limit and streaming buffer issues
                logging.info(f"Loading {len(rows)} rows for new game {game_id} using batch load")

                # Get table schema for load job
                table = self.bq_client.get_table(table_id)

                # Configure batch load job
                job_config = bigquery.LoadJobConfig(
                    schema=table.schema,
                    autodetect=False,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
                )

                # Load using batch job
                load_job = self.bq_client.load_table_from_json(
                    rows,
                    table_id,
                    job_config=job_config
                )

                # Wait for completion
                load_job.result()
                logging.info(f"Successfully loaded {len(rows)} play-by-play events for game {game_id}")

                # Success - send info notification
                try:
                    notify_info(
                        title="BigDataBall Play-by-Play Processing Complete",
                        message=f"Successfully processed {len(rows)} play-by-play events for game {game_id}",
                        details={
                            'game_id': game_id,
                            'game_date': game_date,
                            'rows_processed': len(rows),
                            'away_team': rows[0]['away_team_abbr'],
                            'home_team': rows[0]['home_team_abbr']
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                        
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data: {error_msg}")
            
            # Notify unexpected error
            try:
                notify_error(
                    title="BigDataBall Play-by-Play Processing Failed",
                    message=f"Unexpected error during processing: {error_msg}",
                    details={
                        'game_id': rows[0]['game_id'] if rows else 'unknown',
                        'error_type': type(e).__name__,
                        'error_message': error_msg,
                        'rows_attempted': len(rows)
                    },
                    processor_name="BigDataBall Play-by-Play Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'rows_processed': len(rows) if not errors else 0, 
            'errors': errors,
            'game_id': rows[0]['game_id'] if rows else None
        }