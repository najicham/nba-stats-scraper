#!/usr/bin/env python3
# File: processors/nbacom/nbac_schedule_processor.py
# Description: Processor for NBA.com enhanced schedule data transformation
# UPDATED: Added source tracking (API vs CDN) for dual scraper support
# Integrated notification system for monitoring and alerts

import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional
import pytz
from google.cloud import bigquery, storage
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.clients.bigquery_pool import get_bigquery_client
from shared.config.gcp_config import get_project_id
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


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

    # Primary key fields for MERGE operations (prevents duplicates)
    # game_id uniquely identifies a game; game_date included for partition awareness
    PRIMARY_KEY_FIELDS = ['game_id', 'game_date']

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_schedule'
        self.processing_strategy = 'MERGE_UPDATE'

        # CRITICAL: Initialize BigQuery and Storage clients
        # Use connection pool for BigQuery (reduces connection overhead by 40%+)
        self.project_id = get_project_id()
        self.bq_client = get_bigquery_client(self.project_id)
        self.storage_client = storage.Client()
        
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
            logger.warning(f"Could not detect source from path: {file_path}, defaulting to api_stats")
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
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise FileNotFoundError(error_msg)
            
            # Download and parse JSON
            content = blob.download_as_text()
            return json.loads(content)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for {file_path}: {e}")
            
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
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise
            
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            
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
                logger.warning(f"Failed to send notification: {notify_ex}")
            
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
            logger.warning(f"Could not parse timestamp: {timestamp_str}")
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
            logger.warning(f"Could not parse game date: {game_date_str}")
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
                    logger.warning(f"Failed to send notification: {notify_ex}")
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
                    logger.warning(f"Failed to send notification: {notify_ex}")
        
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
                logger.warning(f"Failed to send notification: {notify_ex}")
                
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
        """Transform raw schedule data into BigQuery format.

        Uses self.raw_data (loaded by load_data()) and self.opts['file_path'].
        Sets self.transformed_data with the result.
        """
        rows = []

        # Get raw_data and file_path from instance attributes
        raw_data = self.raw_data
        file_path = self.opts.get('file_path', '')

        # Detect data source from file path if not already set
        if not self.data_source:
            self.data_source = self.detect_data_source(f"gs://{self.opts.get('bucket', 'nba-scraped-data')}/{file_path}")

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
                    logger.warning(f"Error processing game {game.get('gameId', 'unknown')}: {e}")
                    
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
                            logger.warning(f"Failed to send notification: {notify_ex}")
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
                        logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Log filtering summary
            excluded_games = total_games - business_relevant_games
            if excluded_games > 0:
                logger.info(f"Filtered out {excluded_games} preseason games, processing {business_relevant_games} business-relevant games")

            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()

            # Note: Base class expects transform_data() to set self.transformed_data, not return
            return

        except Exception as e:
            logger.error(f"Critical error in transform_data: {e}")
            
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
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise e
    
    def save_data(self) -> None:
        """
        Save transformed data to BigQuery using proper SQL MERGE.

        This method uses atomic MERGE instead of DELETE + APPEND to prevent
        duplicate rows with conflicting game statuses.

        Pattern: Load to temp table → MERGE on primary keys → Cleanup temp table
        """
        rows = self.transformed_data
        if not rows:
            logger.warning("No rows to load")
            return {'rows_processed': 0, 'errors': []}

        table_id = f"{self.project_id}.{self.table_name}"
        errors = []

        # Create unique temp table name
        temp_table_name = f"nbac_schedule_temp_{uuid.uuid4().hex[:8]}"
        temp_table_id = f"{self.project_id}.nba_raw.{temp_table_name}"

        try:
            # Get target table schema
            table = self.bq_client.get_table(table_id)
            table_schema = table.schema

            logger.info(f"Using SQL MERGE to load {len(rows)} rows to {table_id}")
            logger.info(f"Primary keys for MERGE: {self.PRIMARY_KEY_FIELDS}")

            # Step 1: Sanitize rows for JSON serialization
            sanitized_rows = []
            for i, row in enumerate(rows):
                try:
                    sanitized = self._sanitize_row_for_bq(row)
                    json.dumps(sanitized)  # Validate JSON serialization
                    sanitized_rows.append(sanitized)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Skipping row {i} due to JSON error: {e}")
                    continue

            if not sanitized_rows:
                logger.warning("No valid rows after sanitization")
                return {'rows_processed': 0, 'errors': ['No valid rows after sanitization']}

            # Step 2: Load data into temp table
            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')

            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=False
            )

            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                temp_table_id,
                job_config=job_config
            )

            load_job.result(timeout=300)
            logger.info(f"Loaded {len(sanitized_rows)} rows into temp table {temp_table_name}")

            # Step 3: Build and execute MERGE statement
            primary_keys = self.PRIMARY_KEY_FIELDS
            on_clause = ' AND '.join([f"target.{key} = source.{key}" for key in primary_keys])

            # Get all field names from schema
            all_fields = [field.name for field in table_schema]

            # Fields to update (all except primary keys)
            update_fields = [f for f in all_fields if f not in primary_keys]

            # Build UPDATE SET clause
            update_set = ', '.join([f"{field} = source.{field}" for field in update_fields])

            # Build INSERT clause
            insert_fields = ', '.join(all_fields)
            insert_values = ', '.join([f"source.{field}" for field in all_fields])

            # Get date range for partition filter (required by table)
            game_dates = [row.get('game_date') for row in sanitized_rows if row.get('game_date')]
            if game_dates:
                min_date = min(game_dates)
                max_date = max(game_dates)
                partition_filter = f"AND target.game_date >= '{min_date}' AND target.game_date <= '{max_date}'"
            else:
                partition_filter = ""

            merge_query = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON {on_clause} {partition_filter}
            WHEN MATCHED THEN
                UPDATE SET {update_set}
            WHEN NOT MATCHED THEN
                INSERT ({insert_fields})
                VALUES ({insert_values})
            """

            logger.info(f"Executing MERGE on primary keys: {', '.join(primary_keys)}")
            merge_job = self.bq_client.query(merge_query)
            merge_job.result(timeout=300)

            # Get stats
            if merge_job.num_dml_affected_rows is not None:
                logger.info(f"MERGE completed: {merge_job.num_dml_affected_rows} rows affected")
            else:
                logger.info("MERGE completed successfully")

            # CRITICAL: Update stats for tracking (required by base class and Layer 5 validation)
            self.stats["rows_inserted"] = len(sanitized_rows)
            logger.info(f"Successfully merged {len(sanitized_rows)} rows to {self.table_name} (source: {self.data_source})")

        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data to BigQuery: {error_msg}")

            # Notify about load failure
            try:
                notify_error(
                    title="Schedule MERGE Failed",
                    message=f"Failed to merge schedule data to BigQuery: {error_msg}",
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
                logger.warning(f"Failed to send notification: {notify_ex}")

        finally:
            # Always clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                logger.debug(f"Cleaned up temp table: {temp_table_name}")
            except Exception as cleanup_e:
                logger.warning(f"Could not clean up temp table: {cleanup_e}")

        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}

    def _sanitize_row_for_bq(self, row: Dict) -> Dict:
        """Sanitize a row for BigQuery JSON loading."""
        sanitized = {}
        for key, value in row.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, datetime):
                sanitized[key] = value.isoformat()
            elif isinstance(value, date):
                sanitized[key] = value.isoformat()
            elif isinstance(value, (list, dict)):
                sanitized[key] = json.dumps(value) if isinstance(value, (list, dict)) else value
            else:
                sanitized[key] = value
        return sanitized
    
    def process_file(self, file_path: str, **kwargs) -> Dict:
        """Process a single file - CRITICAL method for backfill integration."""
        try:
            # NEW: Detect data source from file path
            self.data_source = self.detect_data_source(file_path)
            logger.info(f"Processing file: {file_path} (source: {self.data_source})")
            
            # Get and validate data
            raw_data = self.get_file_content(file_path)
            validation_errors = self.validate_data(raw_data)
            
            if validation_errors:
                logger.warning(f"Validation errors for {file_path}: {validation_errors}")
                return {
                    'file_path': file_path,
                    'status': 'validation_failed',
                    'errors': validation_errors,
                    'rows_processed': 0,
                    'data_source': self.data_source
                }
            
            # Transform and load - set raw_data and file_path for transform_data()
            self.raw_data = raw_data
            if not hasattr(self, 'opts') or self.opts is None:
                self.opts = {}
            self.opts['file_path'] = file_path.replace('gs://', '').split('/', 1)[-1] if file_path.startswith('gs://') else file_path
            self.opts['bucket'] = file_path.replace('gs://', '').split('/')[0] if file_path.startswith('gs://') else 'nba-scraped-data'
            self.transform_data()
            result = self.save_data()

            if result.get('errors'):
                status = 'partial_success' if result.get('rows_processed', 0) > 0 else 'failed'
                logger.warning(f"{status.title()}: {len(result['errors'])} errors for {file_path}")
            else:
                status = 'success'
                logger.info(f"Successfully processed {file_path}: {result['rows_processed']} rows from {self.data_source}")

                # Send success notification
                try:
                    notify_info(
                        title="Schedule Processing Complete",
                        message=f"Successfully processed {result['rows_processed']} schedule games from {self.data_source}",
                        details={
                            'file_path': file_path,
                            'rows_processed': result['rows_processed'],
                            'games_failed': self.games_failed,
                            'season': self.transformed_data[0].get('season') if self.transformed_data else None,
                            'data_source': self.data_source
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'file_path': file_path,
                'status': status,
                'rows_processed': result.get('rows_processed', 0),
                'errors': result.get('errors', []),
                'data_source': self.data_source
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error processing file {file_path}: {error_msg}")
            
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
                logger.warning(f"Failed to send notification: {notify_ex}")
            
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