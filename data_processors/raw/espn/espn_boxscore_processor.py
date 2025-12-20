#!/usr/bin/env python3
# File: processors/espn/espn_boxscore_processor.py
# Description: Processor for ESPN boxscore data transformation

import json
import logging
import re
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.nba_team_mapper import NBATeamMapper
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Schedule service for season type detection
from shared.utils.schedule import NBAScheduleService

class EspnBoxscoreProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    ESPN Boxscore Processor

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: game_id, player_lookup, points, rebounds, assists, field_goals_made, field_goals_attempted
        Expected Skip Rate: 30% when boxscores unchanged
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'game_id',
        'player_lookup',
        'points',
        'rebounds',
        'assists',
        'field_goals_made',
        'field_goals_attempted'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.espn_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'
        self.team_mapper = NBATeamMapper()
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

        # Schedule service for season type detection
        self.schedule_service = NBAScheduleService()

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def normalize_player_name(self, name: str) -> str:
        """Normalize player name for cross-source matching."""
        if not name:
            return ""
        
        # Convert to lowercase and remove special characters
        normalized = name.lower().strip()
        # Remove suffixes like Jr, Sr, II, III, IV
        normalized = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', normalized)
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def parse_minutes(self, minutes_str: str) -> str:
        """Parse and validate minutes string."""
        if not minutes_str or minutes_str == "00:00":
            return "0:00"
        return minutes_str
    
    def safe_int_conversion(self, value, default: int = 0) -> int:
        """Safely convert value to integer."""
        if value is None or value == "":
            return default
        try:
            if isinstance(value, str):
                # Handle percentage strings like "50.0%"
                value = value.replace('%', '')
            return int(float(value))
        except (ValueError, TypeError):
            return default
    
    def safe_float_conversion(self, value, default: float = 0.0) -> float:
        """Safely convert value to float."""
        if value is None or value == "":
            return default
        try:
            if isinstance(value, str):
                value = value.replace('%', '')
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def extract_game_info_from_path(self, file_path: str) -> Dict:
        """Extract game date and ESPN game ID from file path."""
        # Path format: /espn/boxscores/{date}/game_{id}/{timestamp}.json
        parts = file_path.split('/')
        
        game_info = {}
        for i, part in enumerate(parts):
            if part == 'boxscores' and i + 1 < len(parts):
                game_info['date'] = parts[i + 1]
            elif part.startswith('game_') and i + 1 < len(parts):
                game_info['espn_game_id'] = part.replace('game_', '')
                
        return game_info
    
    def construct_game_id(self, game_date: str, home_team: str, away_team: str) -> str:
        """Construct standardized game ID."""
        # Format: YYYYMMDD_AWAY_HOME
        date_formatted = game_date.replace('-', '')
        return f"{date_formatted}_{away_team}_{home_team}"
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate ESPN boxscore data structure."""
        errors = []
        
        if not isinstance(data, dict):
            errors.append("Data is not a dictionary")
            return errors
            
        # Check for required ESPN boxscore structure
        required_fields = ['game_id', 'gamedate', 'teams', 'players']
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing {field}")
        
        # Validate teams structure
        if 'teams' in data:
            teams = data['teams']
            if not isinstance(teams, dict) or 'home' not in teams or 'away' not in teams:
                errors.append("Invalid teams structure - need home/away")
                
        # Validate players array
        if 'players' in data:
            if not isinstance(data['players'], list):
                errors.append("Players field is not a list")
            elif len(data['players']) == 0:
                errors.append("No players found")
                
        return errors
    
    def parse_stats_array(self, stats_array: List[str]) -> Dict:
        """Parse ESPN stats array into structured data."""
        # Default values
        parsed_stats = {
            'minutes': '0:00',
            'points': 0,
            'field_goals_made': 0,
            'field_goals_attempted': 0,
            'field_goal_percentage': 0.0,
            'three_pointers_made': 0,
            'three_pointers_attempted': 0,
            'three_point_percentage': 0.0,
            'free_throws_made': 0,
            'free_throws_attempted': 0,
            'free_throw_percentage': 0.0,
            'rebounds': 0,
            'offensive_rebounds': 0,
            'defensive_rebounds': 0,
            'assists': 0,
            'steals': 0,
            'blocks': 0,
            'turnovers': 0,
            'fouls': 0,
            'plus_minus': 0
        }
        
        if not stats_array or len(stats_array) < 14:
            return parsed_stats
        
        try:
            # Parse each stat position based on observed format
            parsed_stats['minutes'] = stats_array[0] or '0:00'
            
            # Field Goals (format: "5-9")
            fg_parts = stats_array[1].split('-') if stats_array[1] else ['0', '0']
            parsed_stats['field_goals_made'] = self.safe_int_conversion(fg_parts[0])
            parsed_stats['field_goals_attempted'] = self.safe_int_conversion(fg_parts[1] if len(fg_parts) > 1 else '0')
            
            # Three Pointers (format: "0-1")
            tp_parts = stats_array[2].split('-') if stats_array[2] else ['0', '0']
            parsed_stats['three_pointers_made'] = self.safe_int_conversion(tp_parts[0])
            parsed_stats['three_pointers_attempted'] = self.safe_int_conversion(tp_parts[1] if len(tp_parts) > 1 else '0')
            
            # Free Throws (format: "3-5")
            ft_parts = stats_array[3].split('-') if stats_array[3] else ['0', '0']
            parsed_stats['free_throws_made'] = self.safe_int_conversion(ft_parts[0])
            parsed_stats['free_throws_attempted'] = self.safe_int_conversion(ft_parts[1] if len(ft_parts) > 1 else '0')
            
            # Individual stats
            parsed_stats['offensive_rebounds'] = self.safe_int_conversion(stats_array[4])
            parsed_stats['defensive_rebounds'] = self.safe_int_conversion(stats_array[5])
            parsed_stats['rebounds'] = self.safe_int_conversion(stats_array[6])
            parsed_stats['assists'] = self.safe_int_conversion(stats_array[7])
            parsed_stats['steals'] = self.safe_int_conversion(stats_array[8])
            parsed_stats['blocks'] = self.safe_int_conversion(stats_array[9])
            parsed_stats['turnovers'] = self.safe_int_conversion(stats_array[10])
            parsed_stats['fouls'] = self.safe_int_conversion(stats_array[11])
            
            # Plus/minus (can be negative, format: "-8" or "+15")
            plus_minus_str = stats_array[12].replace('+', '') if stats_array[12] else '0'
            parsed_stats['plus_minus'] = self.safe_int_conversion(plus_minus_str)
            
            # Points (last element)
            parsed_stats['points'] = self.safe_int_conversion(stats_array[13])
            
            # Calculate percentages
            if parsed_stats['field_goals_attempted'] > 0:
                parsed_stats['field_goal_percentage'] = round(
                    parsed_stats['field_goals_made'] / parsed_stats['field_goals_attempted'] * 100, 1
                )
            
            if parsed_stats['three_pointers_attempted'] > 0:
                parsed_stats['three_point_percentage'] = round(
                    parsed_stats['three_pointers_made'] / parsed_stats['three_pointers_attempted'] * 100, 1
                )
            
            if parsed_stats['free_throws_attempted'] > 0:
                parsed_stats['free_throw_percentage'] = round(
                    parsed_stats['free_throws_made'] / parsed_stats['free_throws_attempted'] * 100, 1
                )
                
        except (IndexError, ValueError, AttributeError) as e:
            logging.warning(f"Error parsing stats array {stats_array}: {str(e)}")
        
        return parsed_stats
    
    def detect_postseason(self, game_date: str) -> bool:
        """Detect if game is in postseason based on date."""
        # Simple heuristic: games after April 15 are likely playoffs
        month = int(game_date[5:7])
        day = int(game_date[8:10])
        return month > 4 or (month == 4 and day > 15)
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform ESPN boxscore data into BigQuery format."""
        validation_errors = self.validate_data(raw_data)
        if validation_errors:
            logging.error(f"Validation failed for {file_path}: {validation_errors}")
            
            # Send warning for validation failures
            try:
                notify_warning(
                    title="ESPN Boxscore: Validation Failed",
                    message=f"Data validation found {len(validation_errors)} critical issues",
                    details={
                        'file_path': file_path,
                        'error_count': len(validation_errors),
                        'errors': validation_errors[:5]  # First 5 errors
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
            
            return []
        
        try:
            # Extract basic game info
            espn_game_id = raw_data['game_id']
            game_date_str = raw_data['gamedate']  # Format: "20250115"

            # Parse game date
            game_date = f"{game_date_str[:4]}-{game_date_str[4:6]}-{game_date_str[6:8]}"

            # Check game type - skip exhibition games (All-Star and Pre-Season)
            season_type = self.schedule_service.get_season_type_for_date(game_date)

            # Skip exhibition games - they aren't useful for predictions
            # All-Star: Uses non-NBA teams (Team LeBron, Team Giannis, etc.)
            # Pre-Season: Teams rest starters, rosters not finalized, stats not indicative
            if season_type in ["All Star", "Pre Season"]:
                logging.info(f"Skipping {season_type} game data for {game_date} (ESPN ID: {espn_game_id}) - "
                           "exhibition games not processed")
                self.transformed_data = []
                return

            # Extract teams
            teams = raw_data['teams']
            home_team_abbr = teams['home']
            away_team_abbr = teams['away']

            # Construct standardized game ID
            game_id = self.construct_game_id(game_date, home_team_abbr, away_team_abbr)
            
            # Extract season year (assume games in Oct+ are new season)
            year = int(game_date[:4])
            month = int(game_date[5:7])
            season_year = year if month < 10 else year + 1
            
            # Process players
            rows = []
            players = raw_data.get('players', [])
            total_players = len(players)
            failed_players = 0
            
            # Check for no players
            if total_players == 0:
                try:
                    notify_warning(
                        title="ESPN Boxscore: No Player Data",
                        message=f"No players found in boxscore data",
                        details={
                            'file_path': file_path,
                            'game_id': game_id,
                            'game_date': game_date,
                            'espn_game_id': espn_game_id
                        }
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
            
            for player_data in players:
                try:
                    # Basic player info
                    player_name = player_data.get('playerName', '')
                    team_abbr = player_data.get('team', '')
                    player_type = player_data.get('type', '')  # "starters" or "bench"
                    stats_array = player_data.get('stats', [])
                    dnp_reason = player_data.get('dnpReason', '')
                    
                    # Parse stats (empty for DNP players)
                    parsed_stats = self.parse_stats_array(stats_array)
                    
                    # Determine if player was active
                    is_active = len(stats_array) > 0
                    starter = player_type == 'starters' if is_active else False
                    
                    # Build player record
                    player_record = {
                        # Core identifiers
                        'game_id': game_id,
                        'espn_game_id': espn_game_id,
                        'game_date': game_date,
                        'season_year': season_year,
                        'game_status': 'Final',  # ESPN data is post-game
                        'period': 4,  # Assume regulation game
                        'is_postseason': self.detect_postseason(game_date),
                        
                        # Team information
                        'home_team_abbr': home_team_abbr,
                        'away_team_abbr': away_team_abbr,
                        'home_team_score': 0,  # Not provided in this format
                        'away_team_score': 0,  # Not provided in this format
                        'home_team_espn_id': '',
                        'away_team_espn_id': '',
                        
                        # Player information
                        'team_abbr': team_abbr,
                        'player_full_name': player_name,
                        'player_lookup': self.normalize_player_name(player_name),
                        'espn_player_id': str(player_data.get('playerId', '')),
                        'jersey_number': str(player_data.get('jersey', '')),
                        'position': '',  # Not provided in this format
                        'starter': starter,
                        
                        # Core statistics
                        'minutes': parsed_stats['minutes'],
                        'points': parsed_stats['points'],
                        'field_goals_made': parsed_stats['field_goals_made'],
                        'field_goals_attempted': parsed_stats['field_goals_attempted'],
                        'field_goal_percentage': parsed_stats['field_goal_percentage'],
                        'three_pointers_made': parsed_stats['three_pointers_made'],
                        'three_pointers_attempted': parsed_stats['three_pointers_attempted'],
                        'three_point_percentage': parsed_stats['three_point_percentage'],
                        'free_throws_made': parsed_stats['free_throws_made'],
                        'free_throws_attempted': parsed_stats['free_throws_attempted'],
                        'free_throw_percentage': parsed_stats['free_throw_percentage'],
                        
                        # Additional statistics
                        'rebounds': parsed_stats['rebounds'],
                        'offensive_rebounds': parsed_stats['offensive_rebounds'],
                        'defensive_rebounds': parsed_stats['defensive_rebounds'],
                        'assists': parsed_stats['assists'],
                        'steals': parsed_stats['steals'],
                        'blocks': parsed_stats['blocks'],
                        'turnovers': parsed_stats['turnovers'],
                        'fouls': parsed_stats['fouls'],
                        'plus_minus': parsed_stats['plus_minus'],
                        
                        # Processing metadata
                        'source_file_path': file_path,
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'processed_at': datetime.now(timezone.utc).isoformat()
                    }
                    
                    rows.append(player_record)
                    
                except Exception as e:
                    logging.warning(f"Error processing player {player_data.get('playerName', 'Unknown')}: {str(e)}")
                    failed_players += 1
                    continue
            
            # Send warning if high player failure rate
            if total_players > 0 and failed_players >= total_players * 0.3:  # 30% threshold
                try:
                    notify_warning(
                        title="ESPN Boxscore: High Player Processing Failure Rate",
                        message=f"Failed to process {failed_players} of {total_players} players",
                        details={
                            'file_path': file_path,
                            'game_id': game_id,
                            'game_date': game_date,
                            'total_players': total_players,
                            'failed_players': failed_players,
                            'success_players': len(rows),
                            'failure_rate': f"{(failed_players/total_players)*100:.1f}%"
                        }
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
            
            logging.info(f"Transformed {len(rows)} player records from {file_path}")
            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()
        except Exception as e:
            logging.error(f"Error transforming data from {file_path}: {str(e)}")
            
            # Send error notification for transformation failures
            try:
                notify_error(
                    title="ESPN Boxscore: Transformation Failed",
                    message=f"Failed to transform boxscore data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="ESPN Boxscore Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return []
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load data to BigQuery with MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this game first
                # MUST include game_date filter for partitioned table
                game_id = rows[0]['game_id']
                game_date = rows[0]['game_date']
                delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}' AND game_date = '{game_date}'"
                logging.info(f"Deleting existing data for game_id: {game_id}, game_date: {game_date}")
                self.bq_client.query(delete_query).result()
            
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
            logging.info(f"Successfully loaded {len(rows)} rows")
        
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data: {error_msg}")
            
            # Send error notification for general BigQuery failures
            try:
                notify_error(
                    title="ESPN Boxscore: BigQuery Load Failed",
                    message=f"Database operation failed: {error_msg}",
                    details={
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error_message': error_msg,
                        'game_id': rows[0].get('game_id') if rows else 'unknown',
                        'game_date': rows[0].get('game_date') if rows else 'unknown'
                    },
                    processor_name="ESPN Boxscore Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }
