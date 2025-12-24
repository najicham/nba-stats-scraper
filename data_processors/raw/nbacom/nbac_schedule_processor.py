#!/usr/bin/env python3
# File: processors/nbacom/nbac_schedule_processor.py
# Description: Processor for NBA.com enhanced schedule data transformation
# UPDATED: Added source tracking (API vs CDN) for dual scraper support
# Integrated notification system for monitoring and alerts

import json
import logging
import os
import re
from datetime import datetime, date
from typing import Dict, List, Optional
import pytz
from google.cloud import bigquery, storage
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class NbacScheduleProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    NBA.com Schedule Processor

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: game_id, game_date, game_date_est, home_team_tricode, away_team_tricode, game_status
        Expected Skip Rate: 20% when schedules unchanged
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    # Note: Uses game_date_est (includes time) instead of game_time_utc (which doesn't exist in transformed data)
    HASH_FIELDS = [
        'game_id',
        'game_date',
        'game_date_est',
        'home_team_tricode',
        'away_team_tricode',
        'game_status'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_schedule'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # CRITICAL: Initialize BigQuery and Storage clients
        self.bq_client = bigquery.Client()
        self.storage_client = storage.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Tracking counters
        self.games_processed = 0
        self.games_failed = 0
        
        # NEW: Source tracking
        self.data_source = None  # Will be set from file path

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def detect_data_source(self, file_path: str) -> str:
        """
        Detect data source from GCS file path.
        
        Paths:
        - nba-com/schedule/... = "api_stats" (API scraper)
        - nba-com/schedule-cdn/... = "cdn_static" (CDN scraper)
        
        Returns:
            "api_stats" or "cdn_static"
        """
        if '/schedule-cdn/' in file_path:
            return "cdn_static"
        elif '/schedule/' in file_path:
            return "api_stats"
        else:
            # Default to api_stats for backwards compatibility
            logging.warning(f"Could not detect source from path: {file_path}, defaulting to api_stats")
            return "api_stats"
    
    def get_file_content(self, file_path: str) -> Dict:
        """Read and parse JSON file from GCS."""
        try:
            # Parse GCS path: gs://bucket-name/path/to/file.json
            if not file_path.startswith('gs://'):
                raise ValueError(f"Invalid GCS path: {file_path}")
            
            path_parts = file_path[5:].split('/', 1)  # Remove 'gs://' and split
            bucket_name = path_parts[0]
            blob_name = path_parts[1]
            
            # Get the file content
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            
            if not blob.exists():
                error_msg = f"File not found: {file_path}"
                
                # Notify about missing file
                try:
                    notify_error(
                        title="Schedule File Not Found",
                        message=f"Schedule file does not exist in GCS: {file_path}",
                        details={
                            'file_path': file_path,
                            'bucket': bucket_name,
                            'blob_name': blob_name,
                            'data_source': self.data_source
                        },
                        processor_name="NBA.com Schedule Processor"
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                raise FileNotFoundError(error_msg)
            
            # Download and parse JSON
            content = blob.download_as_text()
            return json.loads(content)
            
        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error for {file_path}: {e}")
            
            # Notify about JSON parsing failure
            try:
                notify_error(
                    title="Schedule JSON Parse Error",
                    message=f"Failed to parse schedule JSON file: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': 'JSONDecodeError',
                        'data_source': self.data_source
                    },
                    processor_name="NBA.com Schedule Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            raise
            
        except Exception as e:
            logging.error(f"Error reading file {file_path}: {e}")
            
            # Notify about file reading failure
            try:
                notify_error(
                    title="Schedule File Read Failed",
                    message=f"Failed to read schedule file from GCS: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'data_source': self.data_source
                    },
                    processor_name="NBA.com Schedule Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            raise
    
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
            elif '+' in timestamp_str:
                return datetime.fromisoformat(timestamp_str)
            else:
                return datetime.fromisoformat(timestamp_str)
        except (ValueError, AttributeError):
            logging.warning(f"Could not parse timestamp: {timestamp_str}")
            return None
    
    def calculate_season_year(self, game_date_str: str) -> int:
        """Calculate NBA season year from game date."""
        try:
            if game_date_str.endswith('Z'):
                game_date = datetime.fromisoformat(game_date_str.replace('Z', '+00:00')).date()
            else:
                game_date = datetime.fromisoformat(game_date_str.split('T')[0]).date()
            
            # NBA season runs Oct-June, so games in Oct+ are start of new season
            return game_date.year if game_date.month >= 10 else game_date.year - 1
        except (ValueError, AttributeError):
            logging.warning(f"Could not parse game date: {game_date_str}")
            return None
    
    def determine_game_status_text(self, status_id: int) -> str:
        """Convert numeric game status to text."""
        status_map = {
            1: "Scheduled",
            2: "In Progress", 
            3: "Final"
        }
        return status_map.get(status_id, "Unknown")
    
    def is_business_relevant_game(self, game: Dict) -> bool:
        """
        Determine if game should be included in database based on business rules.

        Only include games that we actually process for predictions:
        - Regular Season: Competitive games
        - Playoffs: Competitive playoff games (including Play-In)

        Exclude exhibition games:
        - Pre-Season: Not competitive, rosters not finalized
        - All-Star: Exhibition games, not useful for predictions
        """
        return (
            game.get('isRegularSeason', False) or
            game.get('isPlayoffs', False)
        )
        # Note: All-Star and Pre-Season excluded to match raw data processor filtering
    
    def extract_enhanced_fields(self, game_data: Dict) -> Dict:
        """Extract the 18 enhanced fields provided by the scraper."""
        enhanced_fields = {}
        
        # Core Broadcaster Context (5 fields)
        enhanced_fields['is_primetime'] = game_data.get('isPrimetime', False)
        enhanced_fields['has_national_tv'] = game_data.get('hasNationalTV', False)
        enhanced_fields['primary_network'] = game_data.get('primaryNetwork')
        
        # Convert arrays to JSON strings for BigQuery storage
        traditional_networks = game_data.get('traditionalNetworks', [])
        enhanced_fields['traditional_networks'] = json.dumps(traditional_networks) if traditional_networks else None
        
        streaming_platforms = game_data.get('streamingPlatforms', [])
        enhanced_fields['streaming_platforms'] = json.dumps(streaming_platforms) if streaming_platforms else None
        
        # Core Game Type Classification (7 fields)
        enhanced_fields['is_regular_season'] = game_data.get('isRegularSeason', False)
        enhanced_fields['is_playoffs'] = game_data.get('isPlayoffs', False)
        enhanced_fields['is_all_star'] = game_data.get('isAllStar', False)
        enhanced_fields['is_emirates_cup'] = game_data.get('isEmiratesCup', False)
        enhanced_fields['playoff_round'] = game_data.get('playoffRound')
        enhanced_fields['is_christmas'] = game_data.get('isChristmas', False)
        enhanced_fields['is_mlk_day'] = game_data.get('isMLKDay', False)
        
        # Core Scheduling Context (3 fields)
        enhanced_fields['day_of_week'] = game_data.get('dayOfWeek')
        enhanced_fields['is_weekend'] = game_data.get('isWeekend', False)
        enhanced_fields['time_slot'] = game_data.get('timeSlot')
        
        # Special Venue Context (3 additional fields)
        enhanced_fields['neutral_site_flag'] = game_data.get('neutralSite', False)
        enhanced_fields['international_game'] = game_data.get('internationalGame', False)
        enhanced_fields['arena_timezone'] = game_data.get('arenaTimezone')
        
        return enhanced_fields
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the schedule data structure."""
        errors = []
        
        # Check required top-level fields
        required_fields = ['season', 'season_nba_format', 'game_count', 'games']
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")
        
        # Validate games array
        if 'games' in data:
            if not isinstance(data['games'], list):
                errors.append("'games' field must be a list")
            elif len(data['games']) == 0:
                errors.append("'games' list is empty")
                
                # Notify about empty games list
                try:
                    notify_warning(
                        title="Empty Schedule Games List",
                        message="Schedule data contains no games",
                        details={
                            'season': data.get('season'),
                            'has_season': 'season' in data,
                            'has_game_count': 'game_count' in data,
                            'game_count_value': data.get('game_count'),
                            'data_source': self.data_source
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
            else:
                # Validate first few games structure
                for i, game in enumerate(data['games'][:3]):
                    game_errors = self.validate_game_structure(game, i)
                    errors.extend(game_errors)
        
        # Validate game count consistency
        if 'games' in data and 'game_count' in data:
            expected_count = data['game_count']
            actual_count = len(data['games'])
            if actual_count != expected_count:
                errors.append(f"Game count mismatch: expected {expected_count}, got {actual_count}")
                
                # Notify about count mismatch
                try:
                    notify_warning(
                        title="Schedule Game Count Mismatch",
                        message=f"Game count mismatch: expected {expected_count}, got {actual_count}",
                        details={
                            'expected_count': expected_count,
                            'actual_count': actual_count,
                            'difference': abs(expected_count - actual_count),
                            'season': data.get('season'),
                            'data_source': self.data_source
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
        
        # Notify about validation failures
        if errors:
            try:
                notify_warning(
                    title="Schedule Data Validation Failed",
                    message=f"Found {len(errors)} validation errors in schedule data",
                    details={
                        'errors': errors[:5],  # First 5 errors
                        'total_errors': len(errors),
                        'season': data.get('season'),
                        'data_source': self.data_source
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
                
        return errors
    
    def validate_game_structure(self, game: Dict, index: int) -> List[str]:
        """Validate individual game structure including enhanced fields."""
        errors = []
        
        required_game_fields = ['gameId', 'gameCode', 'gameDateEst', 'homeTeam', 'awayTeam']
        for field in required_game_fields:
            if field not in game:
                errors.append(f"Game {index}: Missing required field '{field}'")
        
        # Validate team structures
        for team_type in ['homeTeam', 'awayTeam']:
            if team_type in game:
                team = game[team_type]
                required_team_fields = ['teamId', 'teamTricode', 'teamName']
                for field in required_team_fields:
                    if field not in team:
                        errors.append(f"Game {index}: {team_type} missing field '{field}'")
        
        # Validate enhanced fields (optional but if present, check types)
        enhanced_boolean_fields = [
            'isPrimetime', 'hasNationalTV', 'isRegularSeason', 'isPlayoffs', 
            'isAllStar', 'isEmiratesCup', 'isChristmas', 'isMLKDay', 'isWeekend',
            'neutralSite', 'internationalGame'
        ]
        
        for field in enhanced_boolean_fields:
            if field in game and not isinstance(game[field], bool):
                errors.append(f"Game {index}: Enhanced field '{field}' should be boolean")
        
        enhanced_array_fields = ['traditionalNetworks', 'streamingPlatforms']
        for field in enhanced_array_fields:
            if field in game and not isinstance(game[field], list):
                errors.append(f"Game {index}: Enhanced field '{field}' should be array")
        
        enhanced_string_fields = ['primaryNetwork', 'playoffRound', 'dayOfWeek', 'timeSlot', 'arenaTimezone']
        for field in enhanced_string_fields:
            if field in game and game[field] is not None and not isinstance(game[field], str):
                errors.append(f"Game {index}: Enhanced field '{field}' should be string or null")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform raw schedule data into BigQuery format."""
        rows = []
        
        try:
            # Extract metadata
            scrape_timestamp = self.extract_scrape_timestamp(raw_data)
            season = raw_data.get('season', '')
            season_nba_format = raw_data.get('season_nba_format', '')
            
            # NEW: Current timestamp for source tracking
            current_timestamp = datetime.utcnow()
            
            total_games = len(raw_data.get('games', []))
            business_relevant_games = 0
            self.games_processed = 0
            self.games_failed = 0
            
            # Process each game
            for game in raw_data.get('games', []):
                try:
                    # Apply business filter - exclude preseason games
                    if not self.is_business_relevant_game(game):
                        continue
                    
                    business_relevant_games += 1
                    
                    # Parse game date and time
                    # Use gameDateTimeEst (has actual game time) instead of gameDateEst (date only at midnight)
                    # NOTE: NBA API uses 'Z' suffix but gameDateTimeEst is actually Eastern time (not UTC)
                    # The gameStatusText confirms this (e.g., "12:00 pm ET" matches gameDateTimeEst: "2025-12-25T12:00:00Z")
                    game_datetime_str = game.get('gameDateTimeEst') or game.get('gameDateEst', '')
                    if game_datetime_str.endswith('Z'):
                        # Parse as naive datetime, then localize to Eastern (handles DST automatically)
                        naive_dt = datetime.fromisoformat(game_datetime_str.replace('Z', ''))
                        eastern = pytz.timezone('America/New_York')
                        game_datetime = eastern.localize(naive_dt)
                    else:
                        game_datetime = datetime.fromisoformat(game_datetime_str)
                    
                    game_date = game_datetime.date()
                    season_year = self.calculate_season_year(game_datetime_str)
                    
                    # Extract team data
                    home_team = game.get('homeTeam', {})
                    away_team = game.get('awayTeam', {})
                    
                    # Extract enhanced fields from scraper
                    enhanced_fields = self.extract_enhanced_fields(game)
                    
                    # Game results (for completed games)
                    home_score = None
                    away_score = None
                    winning_team = None
                    
                    if game.get('gameStatus') == 3:  # Final
                        home_score = home_team.get('score')
                        away_score = away_team.get('score')
                        if home_score is not None and away_score is not None:
                            winning_team = home_team.get('teamTricode') if home_score > away_score else away_team.get('teamTricode')
                    
                    row = {
                        # Core identifiers
                        'game_id': game.get('gameId'),
                        'game_code': game.get('gameCode'),
                        'season': season,
                        'season_nba_format': season_nba_format,
                        'season_year': season_year,
                        
                        # Game details
                        'game_date': game_date.isoformat(),
                        'game_date_est': game_datetime.isoformat(),
                        'game_status': game.get('gameStatus'),
                        'game_status_text': self.determine_game_status_text(game.get('gameStatus', 0)),
                        
                        # Teams
                        'home_team_id': home_team.get('teamId'),
                        'home_team_tricode': home_team.get('teamTricode'),
                        'home_team_name': self.normalize_text(home_team.get('teamName', '')),
                        'away_team_id': away_team.get('teamId'),
                        'away_team_tricode': away_team.get('teamTricode'),
                        'away_team_name': self.normalize_text(away_team.get('teamName', '')),
                        
                        # Venue
                        'arena_name': self.normalize_text(game.get('arenaName', '')),
                        'arena_city': self.normalize_text(game.get('arenaCity', '')),
                        'arena_state': self.normalize_text(game.get('arenaState', '')),
                        
                        # Enhanced fields from scraper (18 fields)
                        **enhanced_fields,
                        
                        # Game results
                        'home_team_score': home_score,
                        'away_team_score': away_score,
                        'winning_team_tricode': winning_team,
                        
                        # NEW: Source tracking fields
                        'data_source': self.data_source,
                        'source_updated_at': current_timestamp.isoformat(),
                        
                        # Standard metadata
                        'source_file_path': file_path,
                        'scrape_timestamp': scrape_timestamp.isoformat() if scrape_timestamp else None,
                        'created_at': current_timestamp.isoformat(),
                        'processed_at': current_timestamp.isoformat()
                    }
                    rows.append(row)
                    self.games_processed += 1
                    
                except Exception as e:
                    self.games_failed += 1
                    logging.warning(f"Error processing game {game.get('gameId', 'unknown')}: {e}")
                    
                    # Notify on first game failure
                    if self.games_failed == 1:
                        try:
                            notify_error(
                                title="Schedule Game Processing Failed",
                                message=f"Failed to process individual game: {str(e)}",
                                details={
                                    'game_id': game.get('gameId', 'unknown'),
                                    'error_type': type(e).__name__,
                                    'season': season,
                                    'data_source': self.data_source
                                },
                                processor_name="NBA.com Schedule Processor"
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                    continue
            
            # Check for high failure rate
            if business_relevant_games > 0:
                failure_rate = self.games_failed / business_relevant_games
                if failure_rate > 0.1:  # More than 10% failures
                    try:
                        notify_warning(
                            title="High Schedule Game Failure Rate",
                            message=f"Failed to process {failure_rate:.1%} of schedule games",
                            details={
                                'total_business_games': business_relevant_games,
                                'games_failed': self.games_failed,
                                'games_processed': self.games_processed,
                                'failure_rate': f"{failure_rate:.1%}",
                                'season': season,
                                'data_source': self.data_source
                            }
                        )
                    except Exception as notify_ex:
                        logging.warning(f"Failed to send notification: {notify_ex}")
            
            # Log filtering summary
            excluded_games = total_games - business_relevant_games
            if excluded_games > 0:
                logging.info(f"Filtered out {excluded_games} preseason games, processing {business_relevant_games} business-relevant games")

            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()

        except Exception as e:
            logging.error(f"Critical error in transform_data: {e}")
            
            # Notify about critical transformation failure
            try:
                notify_error(
                    title="Schedule Transformation Failed",
                    message=f"Critical error transforming schedule data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'games_processed': self.games_processed,
                        'games_failed': self.games_failed,
                        'data_source': self.data_source
                    },
                    processor_name="NBA.com Schedule Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            raise e
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load transformed data into BigQuery."""
        if not rows:
            logging.warning("No rows to load")
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing season data with partition filter
                season_year = rows[0].get('season_year')
                if season_year:
                    # Calculate season date range for partition elimination
                    # NBA season runs from October of season_year to June of season_year+1
                    start_date = f"{season_year}-07-01"  # Start from July 1st to catch any early events
                    end_date = f"{season_year + 1}-09-30"  # End at September 30th to catch any late events
                    
                    delete_query = f"""
                    DELETE FROM `{table_id}` 
                    WHERE season_year = {season_year}
                      AND game_date >= '{start_date}'
                      AND game_date <= '{end_date}'
                    """
                    
                    try:
                        self.bq_client.query(delete_query).result()
                        logging.info(f"Deleted existing records for season {season_year} (date range: {start_date} to {end_date})")
                    except Exception as e:
                        logging.error(f"Error deleting existing data: {e}")
                        
                        # Notify about delete failure
                        try:
                            notify_error(
                                title="BigQuery Delete Failed",
                                message=f"Failed to delete existing schedule data: {str(e)}",
                                details={
                                    'season_year': season_year,
                                    'date_range': f"{start_date} to {end_date}",
                                    'table_id': table_id,
                                    'error_type': type(e).__name__,
                                    'data_source': self.data_source
                                },
                                processor_name="NBA.com Schedule Processor"
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                        
                        raise e
            
            # Insert new data using batch loading (not streaming insert)
            # This avoids the 20 DML limit and streaming buffer issues
            logging.info(f"Loading {len(rows)} rows to {table_id} using batch load")

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
            logging.info(f"Successfully loaded {len(rows)} rows to {self.table_name} (source: {self.data_source})")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data to BigQuery: {error_msg}")
            
            # Notify about load failure
            try:
                notify_error(
                    title="Schedule Load Failed",
                    message=f"Failed to load schedule data to BigQuery: {error_msg}",
                    details={
                        'table_id': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'season': rows[0].get('season') if rows else None,
                        'data_source': self.data_source
                    },
                    processor_name="NBA.com Schedule Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}
    
    def process_file(self, file_path: str, **kwargs) -> Dict:
        """Process a single file - CRITICAL method for backfill integration."""
        try:
            # NEW: Detect data source from file path
            self.data_source = self.detect_data_source(file_path)
            logging.info(f"Processing file: {file_path} (source: {self.data_source})")
            
            # Get and validate data
            raw_data = self.get_file_content(file_path)
            validation_errors = self.validate_data(raw_data)
            
            if validation_errors:
                logging.warning(f"Validation errors for {file_path}: {validation_errors}")
                return {
                    'file_path': file_path,
                    'status': 'validation_failed',
                    'errors': validation_errors,
                    'rows_processed': 0,
                    'data_source': self.data_source
                }
            
            # Transform and load
            rows = self.transform_data(raw_data, file_path)
            result = self.load_data(rows, **kwargs)
            
            if result.get('errors'):
                status = 'partial_success' if result.get('rows_processed', 0) > 0 else 'failed'
                logging.warning(f"{status.title()}: {len(result['errors'])} errors for {file_path}")
            else:
                status = 'success'
                logging.info(f"Successfully processed {file_path}: {result['rows_processed']} rows from {self.data_source}")
                
                # Send success notification
                try:
                    notify_info(
                        title="Schedule Processing Complete",
                        message=f"Successfully processed {result['rows_processed']} schedule games from {self.data_source}",
                        details={
                            'file_path': file_path,
                            'rows_processed': result['rows_processed'],
                            'games_failed': self.games_failed,
                            'season': rows[0].get('season') if rows else None,
                            'data_source': self.data_source
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'file_path': file_path,
                'status': status,
                'rows_processed': result.get('rows_processed', 0),
                'errors': result.get('errors', []),
                'data_source': self.data_source
            }
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error processing file {file_path}: {error_msg}")
            
            # Notify about general processing failure
            try:
                notify_error(
                    title="Schedule File Processing Failed",
                    message=f"Error processing schedule file: {error_msg}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'data_source': self.data_source
                    },
                    processor_name="NBA.com Schedule Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'file_path': file_path,
                'status': 'error',
                'error': error_msg,
                'rows_processed': 0,
                'data_source': self.data_source if hasattr(self, 'data_source') else None
            }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }



# CLI entry point for testing
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python nbac_schedule_processor.py <gcs_file_path>")
        print("Example: python nbac_schedule_processor.py gs://nba-scraped-data/nba-com/schedule/2024/schedule_2024.json")
        sys.exit(1)

    file_path = sys.argv[1]

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize processor
    processor = NbacScheduleProcessor()

    # Process file
    result = processor.process_file(file_path, dry_run=False)

    # Print results
    print("\n" + "="*70)
    print("SCHEDULE PROCESSING RESULTS")
    print("="*70)
    print(f"File: {result['file_path']}")
    print(f"Status: {result['status']}")
    print(f"Rows Processed: {result['rows_processed']}")
    print(f"Data Source: {result.get('data_source', 'unknown')}")

    if result.get('errors'):
        print(f"\nErrors ({len(result['errors'])}):")
        for error in result['errors'][:10]:  # Show first 10
            print(f"  - {error}")

    print("="*70)