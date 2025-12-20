#!/usr/bin/env python3
# File: processors/nbacom/nbac_scoreboard_v2_processor.py
# Description: Processor for NBA.com Scoreboard V2 data transformation
# Integrated notification system for monitoring and alerts

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class NbacScoreboardV2Processor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process NBA.com Scoreboard V2 data with smart idempotency.
    """

    # Smart idempotency: Hash meaningful scoreboard fields only
    HASH_FIELDS = [
        'game_id',
        'game_date',
        'season_year',
        'game_status_id',
        'game_state',
        'game_status_text',
        'home_team_abbr',
        'home_score',
        'away_team_abbr',
        'away_score',
        'winning_team_abbr',
        'winning_team_side'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_scoreboard_v2'
        self.processing_strategy = 'MERGE_UPDATE'
        # Initialize BigQuery client and project ID
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Team abbreviation normalization mapping
        self.team_abbr_mapping = {
            'NY': 'NYK',      # New York Knicks
            'GS': 'GSW',      # Golden State Warriors  
            'SA': 'SAS',      # San Antonio Spurs
            'NO': 'NOP',      # New Orleans Pelicans
            'UTAH': 'UTA',    # Utah Jazz
            'BKN': 'BRK',     # Brooklyn Nets (sometimes appears as BRK)
        }
        
        # Tracking counters
        self.games_processed = 0
        self.games_failed = 0

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_team_abbreviation(self, abbr: str) -> str:
        """Normalize team abbreviation to standard format."""
        if not abbr:
            return ""
        
        abbr_upper = abbr.upper()
        return self.team_abbr_mapping.get(abbr_upper, abbr_upper)
    
    def extract_season_year(self, game_date_str: str) -> int:
        """Extract NBA season year from game date."""
        try:
            game_date = datetime.strptime(game_date_str, '%Y%m%d').date()
            # NBA season starts in October
            # Oct-Dec = current year season, Jan-June = previous year season
            if game_date.month >= 10:
                return game_date.year
            else:
                return game_date.year - 1
        except ValueError:
            logging.warning(f"Could not parse game date: {game_date_str}")
            return 2024  # Default fallback
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the scoreboard data structure."""
        errors = []
        
        if 'games' not in data:
            errors.append("Missing 'games' field")
            return errors
        
        if not isinstance(data['games'], list):
            errors.append("'games' field must be a list")
            return errors
        
        if len(data['games']) == 0:
            errors.append("'games' list is empty")
            
            # Notify about empty games list
            try:
                notify_warning(
                    title="Empty Scoreboard Games List",
                    message="Scoreboard data contains no games",
                    details={
                        'gamedate': data.get('gamedate'),
                        'has_games_field': 'games' in data
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return errors
        
        for i, game in enumerate(data['games']):
            if 'gameId' not in game:
                errors.append(f"Game {i}: Missing gameId")
            
            if 'teams' not in game:
                errors.append(f"Game {i}: Missing teams")
                continue
                
            if not isinstance(game['teams'], dict):
                errors.append(f"Game {i}: teams must be an object")
                continue
            
            teams = game['teams']
            if 'home' not in teams:
                errors.append(f"Game {i}: Missing home team in teams")
            if 'away' not in teams:
                errors.append(f"Game {i}: Missing away team in teams")
            
            # Check home team structure
            if 'home' in teams:
                home_team = teams['home']
                if 'abbreviation' not in home_team:
                    errors.append(f"Game {i}: Home team missing abbreviation")
                if 'points' not in home_team:
                    errors.append(f"Game {i}: Home team missing points")
            
            # Check away team structure
            if 'away' in teams:
                away_team = teams['away']
                if 'abbreviation' not in away_team:
                    errors.append(f"Game {i}: Away team missing abbreviation")
                if 'points' not in away_team:
                    errors.append(f"Game {i}: Away team missing points")
        
        # Notify about validation failures
        if errors:
            try:
                notify_warning(
                    title="Scoreboard Data Validation Failed",
                    message=f"Found {len(errors)} validation errors in scoreboard data",
                    details={
                        'errors': errors[:5],  # First 5 errors
                        'total_errors': len(errors),
                        'gamedate': data.get('gamedate'),
                        'games_count': len(data.get('games', []))
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform scoreboard data into BigQuery format."""
        rows = []
        
        try:
            gamedate = raw_data.get('gamedate', '')
            scrape_timestamp_str = raw_data.get('timestamp', '')
            
            # Parse scrape timestamp
            scrape_timestamp = None
            if scrape_timestamp_str:
                try:
                    scrape_timestamp = datetime.fromisoformat(scrape_timestamp_str.replace('Z', '+00:00'))
                except ValueError:
                    logging.warning(f"Could not parse timestamp: {scrape_timestamp_str}")
            
            # Parse game date
            game_date = None
            if gamedate:
                try:
                    game_date = datetime.strptime(gamedate, '%Y%m%d').date()
                except ValueError:
                    logging.warning(f"Could not parse gamedate: {gamedate}")
                    
                    # Notify about date parsing failure
                    try:
                        notify_warning(
                            title="Invalid Scoreboard Game Date",
                            message=f"Could not parse game date: {gamedate}",
                            details={
                                'gamedate': gamedate,
                                'file_path': file_path
                            }
                        )
                    except Exception as notify_ex:
                        logging.warning(f"Failed to send notification: {notify_ex}")
            
            season_year = self.extract_season_year(gamedate) if gamedate else 2024
            
            self.games_processed = 0
            self.games_failed = 0
            
            for game in raw_data.get('games', []):
                try:
                    # Get team data
                    teams = game.get('teams', {})
                    home_team = teams.get('home', {})
                    away_team = teams.get('away', {})
                    
                    if not home_team or not away_team:
                        self.games_failed += 1
                        logging.warning(f"Game {game.get('gameId')}: Missing team data")
                        
                        # Notify on first missing team data
                        if self.games_failed == 1:
                            try:
                                notify_warning(
                                    title="Scoreboard Missing Team Data",
                                    message=f"Game missing team data: {game.get('gameId')}",
                                    details={
                                        'game_id': game.get('gameId'),
                                        'has_home_team': bool(home_team),
                                        'has_away_team': bool(away_team),
                                        'gamedate': gamedate
                                    }
                                )
                            except Exception as notify_ex:
                                logging.warning(f"Failed to send notification: {notify_ex}")
                        continue
                    
                    # Determine winner by comparing points
                    home_points = home_team.get('points', 0)
                    away_points = away_team.get('points', 0)
                    
                    winning_team_abbr = None
                    winning_team_side = None
                    
                    if home_points > away_points:
                        winning_team_abbr = self.normalize_team_abbreviation(home_team.get('abbreviation', ''))
                        winning_team_side = 'home'
                    elif away_points > home_points:
                        winning_team_abbr = self.normalize_team_abbreviation(away_team.get('abbreviation', ''))
                        winning_team_side = 'away'
                    # If tied, leave winner fields as None
                    
                    # Parse start time
                    start_time = None
                    start_time_str = game.get('startTimeET', '')
                    if start_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str)
                        except ValueError:
                            logging.warning(f"Could not parse startTimeET: {start_time_str}")
                    
                    row = {
                        'game_id': game.get('gameId', ''),
                        'game_date': game_date.isoformat() if game_date else None,
                        'season_year': season_year,
                        'start_time': start_time.isoformat() if start_time else None,
                        
                        # Game status
                        'game_status_id': str(game.get('gameStatus', '')),
                        'game_state': game.get('state', ''),
                        'game_status_text': game.get('gameStatusText', ''),
                        
                        # Home team
                        'home_team_id': str(home_team.get('teamId', '')),
                        'home_team_abbr': self.normalize_team_abbreviation(home_team.get('abbreviation', '')),
                        'home_team_abbr_raw': home_team.get('abbreviation', ''),
                        'home_score': home_points,
                        
                        # Away team
                        'away_team_id': str(away_team.get('teamId', '')),
                        'away_team_abbr': self.normalize_team_abbreviation(away_team.get('abbreviation', '')),
                        'away_team_abbr_raw': away_team.get('abbreviation', ''),
                        'away_score': away_points,
                        
                        # Game outcome
                        'winning_team_abbr': winning_team_abbr,
                        'winning_team_side': winning_team_side,
                        
                        # Processing metadata
                        'source_file_path': file_path,
                        'scrape_timestamp': scrape_timestamp.isoformat() if scrape_timestamp else None,
                        'created_at': datetime.utcnow().isoformat(),
                        'processed_at': datetime.utcnow().isoformat()
                    }
                    
                    rows.append(row)
                    self.games_processed += 1
                    
                except Exception as e:
                    self.games_failed += 1
                    logging.error(f"Error processing game {game.get('gameId', 'unknown')}: {str(e)}")
                    
                    # Notify on first game processing failure
                    if self.games_failed == 1:
                        try:
                            notify_error(
                                title="Scoreboard Game Processing Failed",
                                message=f"Failed to process scoreboard game: {str(e)}",
                                details={
                                    'game_id': game.get('gameId', 'unknown'),
                                    'error_type': type(e).__name__,
                                    'gamedate': gamedate
                                },
                                processor_name="NBA.com Scoreboard V2 Processor"
                            )
                        except Exception as notify_ex:
                            logging.warning(f"Failed to send notification: {notify_ex}")
                    continue
            
            # Check for high failure rate
            total_games = len(raw_data.get('games', []))
            if total_games > 0:
                failure_rate = self.games_failed / total_games
                if failure_rate > 0.1:  # More than 10% failures
                    try:
                        notify_warning(
                            title="High Scoreboard Game Failure Rate",
                            message=f"Failed to process {failure_rate:.1%} of scoreboard games",
                            details={
                                'total_games': total_games,
                                'games_failed': self.games_failed,
                                'games_processed': self.games_processed,
                                'failure_rate': f"{failure_rate:.1%}",
                                'gamedate': gamedate
                            }
                        )
                    except Exception as notify_ex:
                        logging.warning(f"Failed to send notification: {notify_ex}")
            
            logging.info(f"Transformed {len(rows)} scoreboard games (failed: {self.games_failed})")
            self.transformed_data = rows

            # Add smart idempotency hash to each row
            self.add_data_hash()

        except Exception as e:
            logging.error(f"Critical error in transform_data: {e}")
            
            # Notify about critical transformation failure
            try:
                notify_error(
                    title="Scoreboard Transformation Failed",
                    message=f"Critical error transforming scoreboard data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'games_processed': self.games_processed,
                        'games_failed': self.games_failed,
                        'gamedate': raw_data.get('gamedate')
                    },
                    processor_name="NBA.com Scoreboard V2 Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            raise e
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load transformed data into BigQuery using MERGE."""
        if not rows:
            logging.warning("No rows to load")
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Create a temporary table for the new data
            temp_table_name = f"nbac_scoreboard_v2_temp_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            temp_table_id = f"{self.project_id}.nba_raw.{temp_table_name}"
            
            logging.info(f"Loading data to temporary table: {temp_table_id}")
            
            # Get the schema from the main table
            main_table = self.bq_client.get_table(table_id)
            
            # Create temp table with same schema
            temp_table = bigquery.Table(temp_table_id, schema=main_table.schema)
            temp_table = self.bq_client.create_table(temp_table)
            
            # Load data into temp table using load_table_from_json
            job_config = bigquery.LoadJobConfig(
                schema=main_table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            
            load_job = self.bq_client.load_table_from_json(
                rows, temp_table_id, job_config=job_config
            )
            load_job.result()  # Wait for completion
            
            if load_job.errors:
                errors.extend([str(e) for e in load_job.errors])
                logging.error(f"Failed to load into temp table: {errors}")
                
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                except Exception:
                    pass
                
                return {'rows_processed': 0, 'errors': errors}
            
            logging.info(f"Loaded {len(rows)} rows into temp table")
            
            # Get the game_date for partition filter
            game_date = rows[0]['game_date']
            
            # Use MERGE with CTE to satisfy partition filter requirement
            merge_query = f"""
            MERGE `{table_id}` T
            USING (
              SELECT * FROM `{temp_table_id}`
            ) S
            ON T.game_id = S.game_id 
               AND T.game_date = S.game_date
               AND T.game_date = '{game_date}'
            WHEN MATCHED THEN
              UPDATE SET
                season_year = S.season_year,
                start_time = S.start_time,
                game_status_id = S.game_status_id,
                game_state = S.game_state,
                game_status_text = S.game_status_text,
                home_team_id = S.home_team_id,
                home_team_abbr = S.home_team_abbr,
                home_team_abbr_raw = S.home_team_abbr_raw,
                home_score = S.home_score,
                away_team_id = S.away_team_id,
                away_team_abbr = S.away_team_abbr,
                away_team_abbr_raw = S.away_team_abbr_raw,
                away_score = S.away_score,
                winning_team_abbr = S.winning_team_abbr,
                winning_team_side = S.winning_team_side,
                source_file_path = S.source_file_path,
                scrape_timestamp = S.scrape_timestamp,
                processed_at = S.processed_at
            WHEN NOT MATCHED THEN
              INSERT (
                game_id, game_date, season_year, start_time,
                game_status_id, game_state, game_status_text,
                home_team_id, home_team_abbr, home_team_abbr_raw, home_score,
                away_team_id, away_team_abbr, away_team_abbr_raw, away_score,
                winning_team_abbr, winning_team_side,
                source_file_path, scrape_timestamp, created_at, processed_at
              )
              VALUES (
                S.game_id, S.game_date, S.season_year, S.start_time,
                S.game_status_id, S.game_state, S.game_status_text,
                S.home_team_id, S.home_team_abbr, S.home_team_abbr_raw, S.home_score,
                S.away_team_id, S.away_team_abbr, S.away_team_abbr_raw, S.away_score,
                S.winning_team_abbr, S.winning_team_side,
                S.source_file_path, S.scrape_timestamp, S.created_at, S.processed_at
              )
            """
            
            logging.info("Executing MERGE query")
            merge_job = self.bq_client.query(merge_query)
            merge_job.result()  # Wait for completion
            
            logging.info(f"MERGE completed: {merge_job.num_dml_affected_rows} rows affected")
            
            # Clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                logging.info(f"Deleted temporary table: {temp_table_id}")
            except Exception as e:
                logging.warning(f"Failed to delete temp table: {e}")
            
            logging.info(f"Successfully loaded {len(rows)} rows using MERGE")
            
            # Send success notification
            try:
                notify_info(
                    title="Scoreboard Processing Complete",
                    message=f"Successfully processed {len(rows)} scoreboard games using MERGE",
                    details={
                        'rows_processed': len(rows),
                        'games_failed': self.games_failed,
                        'game_date': rows[0].get('game_date') if rows else None,
                        'rows_affected': merge_job.num_dml_affected_rows
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': len(rows), 'errors': []}
            
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data to BigQuery: {error_msg}")
            
            # Notify about load failure
            try:
                notify_error(
                    title="Scoreboard Load Failed",
                    message=f"Failed to load scoreboard data to BigQuery: {error_msg}",
                    details={
                        'table_id': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'game_date': rows[0].get('game_date') if rows else None
                    },
                    processor_name="NBA.com Scoreboard V2 Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': 0, 'errors': errors}

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }

    
if __name__ == "__main__":
    import argparse
    import sys
    from google.cloud import storage
    
    parser = argparse.ArgumentParser(description="Process NBA.com Scoreboard V2 data")
    parser.add_argument('--file-path', required=True, help='GCS file path (gs://bucket/path/file.json)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        processor = NbacScoreboardV2Processor()
        
        logging.info(f"Processing file: {args.file_path}")
        
        # Parse GCS path: gs://bucket-name/path/to/file.json
        if not args.file_path.startswith('gs://'):
            raise ValueError(f"Invalid GCS path: {args.file_path}")
        
        path_parts = args.file_path[5:].split('/', 1)  # Remove 'gs://' and split
        bucket_name = path_parts[0]
        blob_name = path_parts[1]
        
        # Read file directly from GCS
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        if not blob.exists():
            raise FileNotFoundError(f"File not found: {args.file_path}")
        
        content = blob.download_as_text()
        raw_data = json.loads(content)
        
        logging.info(f"Loaded JSON with {len(raw_data.get('games', []))} games")
        
        # Validate
        validation_errors = processor.validate_data(raw_data)
        if validation_errors:
            logging.error(f"Validation failed: {validation_errors}")
            sys.exit(1)
        
        logging.info("Validation passed")
        
        # Transform
        rows = processor.transform_data(raw_data, args.file_path)
        logging.info(f"Transformed {len(rows)} rows")
        
        # Load to BigQuery
        result = processor.load_data(rows)
        
        if result.get('errors'):
            logging.error(f"Load errors: {result['errors']}")
            sys.exit(1)
        
        logging.info(f"Successfully processed {result.get('rows_processed', 0)} rows")
        sys.exit(0)
        
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)