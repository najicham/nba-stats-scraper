#!/usr/bin/env python3
# File: data_processors/raw/espn/espn_scoreboard_processor.py
# Description: Processor for ESPN scoreboard data transformation
# UPDATED: Production-safe with staging table + batch loading (no streaming buffer)

import json
import logging
import os
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class EspnScoreboardProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.espn_scoreboard'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # Initialize BigQuery client and project_id
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # ESPN team abbreviation mapping to standard NBA codes
        self.team_mapping = {
            'ATL': 'ATL', 'BKN': 'BKN', 'BOS': 'BOS', 'CHA': 'CHA',
            'CHI': 'CHI', 'CLE': 'CLE', 'DAL': 'DAL', 'DEN': 'DEN',
            'DET': 'DET', 'GS': 'GSW',  # ESPN uses GS
            'HOU': 'HOU', 'IND': 'IND', 'LAC': 'LAC', 'LAL': 'LAL',
            'MEM': 'MEM', 'MIA': 'MIA', 'MIL': 'MIL', 'MIN': 'MIN',
            'NO': 'NOP',   # ESPN uses NO
            'NY': 'NYK',   # ESPN uses NY
            'OKC': 'OKC', 'ORL': 'ORL', 'PHI': 'PHI', 'PHX': 'PHX',
            'POR': 'POR', 'SA': 'SAS',  # ESPN uses SA
            'SAC': 'SAC', 'TOR': 'TOR', 'UTAH': 'UTA',  # ESPN uses UTAH
            'WAS': 'WAS'
        }
    
    def map_team_abbreviation(self, espn_abbr: str) -> str:
        """Map ESPN team abbreviations to standard NBA codes."""
        return self.team_mapping.get(espn_abbr, espn_abbr)
    
    def extract_game_date_from_path(self, file_path: str) -> Optional[date]:
        """Extract game date from ESPN scoreboard file path."""
        # Path: espn/scoreboard/{date}/{timestamp}.json
        try:
            parts = file_path.split('/')
            date_str = parts[-2]  # Get date part
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, IndexError):
            return None
    
    def construct_game_id(self, game_date: date, away_team: str, home_team: str) -> str:
        """Construct standardized game_id format."""
        date_str = game_date.strftime('%Y%m%d')
        return f"{date_str}_{away_team}_{home_team}"
    
    def parse_season_year(self, game_date: date) -> int:
        """Calculate NBA season year (starting year of season)."""
        # NBA season runs Oct-June, so games before July belong to previous season
        if game_date.month >= 10:  # Oct-Dec
            return game_date.year
        else:  # Jan-June
            return game_date.year - 1
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate ESPN scoreboard data structure."""
        errors = []
        
        if 'games' not in data:
            errors.append("Missing 'games' field")
            return errors
        
        if 'gamedate' not in data:
            errors.append("Missing 'gamedate' field")
        
        for i, game in enumerate(data.get('games', [])):
            if 'teams' not in game:
                errors.append(f"Game {i}: Missing 'teams' field")
                continue
            
            if len(game['teams']) != 2:
                errors.append(f"Game {i}: Expected 2 teams, got {len(game['teams'])}")
            
            for j, team in enumerate(game['teams']):
                if 'homeAway' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing 'homeAway' field")
                if 'score' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing 'score' field")
                if 'abbreviation' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing 'abbreviation' field")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform ESPN scoreboard data to BigQuery format."""
        rows = []
        
        # Extract game date from file path
        game_date = self.extract_game_date_from_path(file_path)
        if not game_date:
            logging.error(f"Could not extract game date from path: {file_path}")
            
            # Send warning notification for missing game date
            try:
                notify_warning(
                    title="ESPN Scoreboard: Missing Game Date",
                    message=f"Could not extract game date from file path",
                    details={
                        'file_path': file_path,
                        'processor': 'ESPN Scoreboard'
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
            
            return rows
        
        season_year = self.parse_season_year(game_date)
        scrape_timestamp = raw_data.get('timestamp')
        games_in_file = len(raw_data.get('games', []))
        skipped_games = 0
        
        for game in raw_data.get('games', []):
            try:
                # Parse teams - find home and away
                home_team = None
                away_team = None
                
                for team in game.get('teams', []):
                    team_data = {
                        'espn_team_id': team.get('teamId'),
                        'team_name': team.get('displayName'),
                        'espn_abbr': team.get('abbreviation'),
                        'team_abbr': self.map_team_abbreviation(team.get('abbreviation', '')),
                        'score': int(team.get('score', '0')) if team.get('score', '').isdigit() else 0,
                        'winner': team.get('winner', False)
                    }
                    
                    if team.get('homeAway') == 'home':
                        home_team = team_data
                    elif team.get('homeAway') == 'away':
                        away_team = team_data
                
                if not home_team or not away_team:
                    logging.warning(f"Could not identify home/away teams for game {game.get('gameId')}")
                    skipped_games += 1
                    continue
                
                # Construct standardized game_id
                game_id = self.construct_game_id(game_date, away_team['team_abbr'], home_team['team_abbr'])
                
                # Parse game status
                game_status = game.get('status', '').lower()
                is_completed = game_status == 'final' or game.get('state') == 'post'
                
                # Parse start time
                start_time = None
                if game.get('startTime'):
                    try:
                        start_time = datetime.fromisoformat(game['startTime'].replace('Z', '+00:00')).isoformat()
                    except ValueError:
                        logging.warning(f"Could not parse start time: {game.get('startTime')}")
                
                # Create row
                row = {
                    # Core identifiers
                    'game_id': game_id,
                    'espn_game_id': game.get('gameId'),
                    'game_date': game_date.isoformat(),
                    'season_year': season_year,
                    
                    # Team information
                    'home_team_abbr': home_team['team_abbr'],
                    'away_team_abbr': away_team['team_abbr'],
                    'home_team_name': home_team['team_name'],
                    'away_team_name': away_team['team_name'],
                    'home_team_espn_id': home_team['espn_team_id'],
                    'away_team_espn_id': away_team['espn_team_id'],
                    'home_team_espn_abbr': home_team['espn_abbr'],
                    'away_team_espn_abbr': away_team['espn_abbr'],
                    
                    # Game status
                    'game_status': game_status,
                    'game_status_detail': game.get('status'),  # Original status
                    'espn_status_id': game.get('statusId'),
                    'espn_state': game.get('state'),
                    'is_completed': is_completed,
                    'scheduled_start_time': start_time,
                    
                    # Scoring
                    'home_team_score': home_team['score'],
                    'away_team_score': away_team['score'],
                    'home_team_winner': home_team['winner'],
                    'away_team_winner': away_team['winner'],
                    
                    # Processing metadata
                    'scrape_timestamp': scrape_timestamp,
                    'source_file_path': file_path,
                    'processing_confidence': 1.0,  # ESPN data is reliable
                    'data_quality_flags': '',
                    'created_at': datetime.utcnow().isoformat(),
                    'processed_at': datetime.utcnow().isoformat()
                }
                
                rows.append(row)
                
            except Exception as e:
                logging.error(f"Error processing game {game.get('gameId', 'unknown')}: {str(e)}")
                skipped_games += 1
                continue
        
        # Send warning if significant games were skipped
        if skipped_games > 0 and skipped_games >= games_in_file * 0.3:  # 30% threshold
            try:
                notify_warning(
                    title="ESPN Scoreboard: High Game Skip Rate",
                    message=f"Skipped {skipped_games} of {games_in_file} games during transformation",
                    details={
                        'games_total': games_in_file,
                        'games_skipped': skipped_games,
                        'games_processed': len(rows),
                        'skip_rate': f"{(skipped_games/games_in_file)*100:.1f}%",
                        'game_date': game_date.isoformat(),
                        'file_path': file_path
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
        
        logging.info(f"Transformed {len(rows)} games from ESPN scoreboard data")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """
        Production-safe loading using staging table + MERGE.
        
        Pattern from BigQuery Lessons Learned:
        - Batch loading (no streaming buffer)
        - Schema enforcement
        - Atomic MERGE operation
        - Graceful failure handling
        """
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        temp_table_id = None
        
        try:
            # 1. Create temporary table name
            temp_table_name = f"{self.table_name}_temp_{uuid.uuid4().hex[:8]}"
            temp_table_id = f"{self.project_id}.{temp_table_name}"
            
            logging.info(f"Creating temporary table: {temp_table_id}")
            
            # 2. Get target table schema for enforcement
            try:
                target_table = self.bq_client.get_table(table_id)
                target_schema = target_table.schema
            except Exception as e:
                logging.warning(f"Could not get target table schema: {e}")
                target_schema = None
            
            # 3. Configure batch loading job (NO streaming buffer!)
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            )
            
            # Enforce schema if available
            if target_schema:
                job_config.schema = target_schema
                job_config.autodetect = False
                logging.debug("Using schema enforcement for temp table")
            else:
                job_config.autodetect = True
                logging.debug("Using schema autodetection for temp table")
            
            # 4. Batch load to temporary table
            logging.info(f"Loading {len(rows)} rows to temporary table via batch loading")
            load_job = self.bq_client.load_table_from_json(
                rows, 
                temp_table_id, 
                job_config=job_config
            )
            
            # Wait for load to complete
            load_job.result()
            logging.info(f"✅ Batch loaded {len(rows)} rows to {temp_table_id}")
            
            # 5. Execute MERGE operation with explicit partition filter
            game_date = rows[0]['game_date']
            
            # Filter source to specific partition to enable partition elimination
            merge_query = f"""
                MERGE `{table_id}` AS target
                USING (
                    SELECT * FROM `{temp_table_id}`
                    WHERE game_date = '{game_date}'
                ) AS source
                ON target.game_id = source.game_id
                   AND target.game_date = '{game_date}'
                WHEN MATCHED THEN
                    UPDATE SET
                        home_team_score = source.home_team_score,
                        away_team_score = source.away_team_score,
                        home_team_winner = source.home_team_winner,
                        away_team_winner = source.away_team_winner,
                        is_completed = source.is_completed,
                        game_status = source.game_status,
                        game_status_detail = source.game_status_detail,
                        espn_status_id = source.espn_status_id,
                        espn_state = source.espn_state,
                        scrape_timestamp = source.scrape_timestamp,
                        source_file_path = source.source_file_path,
                        processed_at = source.processed_at
                WHEN NOT MATCHED THEN
                    INSERT ROW
            """
            
            logging.info(f"Executing MERGE for game_date={game_date}")
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            
            # Get affected rows count
            rows_affected = merge_result.total_rows if hasattr(merge_result, 'total_rows') else len(rows)
            
            logging.info(f"✅ MERGE completed successfully: {rows_affected} rows affected")
            
            return {
                'rows_processed': len(rows),
                'rows_affected': rows_affected,
                'errors': []
            }
            
        except Exception as e:
            error_msg = str(e)
            
            # Graceful failure for streaming buffer conflicts
            if "streaming buffer" in error_msg.lower():
                logging.warning(f"⚠️ MERGE blocked by streaming buffer - {len(rows)} records skipped")
                logging.info("Records will be processed on next run when buffer clears (graceful failure)")
                
                try:
                    notify_warning(
                        title="ESPN Scoreboard: Streaming Buffer Conflict",
                        message=f"MERGE blocked by streaming buffer - data skipped for this run",
                        details={
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'game_date': rows[0].get('game_date') if rows else 'unknown',
                            'resolution': 'Will retry on next run (self-healing)'
                        }
                    )
                except Exception as notify_ex:
                    logging.warning(f"Failed to send notification: {notify_ex}")
                
                # Return graceful failure (not an error)
                return {
                    'rows_processed': 0,
                    'rows_affected': 0,
                    'errors': [],
                    'skipped_due_to_streaming_buffer': True
                }
            
            # Other errors are genuine problems
            logging.error(f"Error loading data to BigQuery: {error_msg}", exc_info=True)
            
            try:
                notify_error(
                    title="ESPN Scoreboard: BigQuery Load Failed",
                    message=f"Database operation failed: {error_msg[:200]}",
                    details={
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error_message': error_msg[:500],
                        'game_date': rows[0].get('game_date') if rows else 'unknown',
                        'temp_table': temp_table_id
                    },
                    processor_name="ESPN Scoreboard Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'rows_processed': 0,
                'rows_affected': 0,
                'errors': [error_msg]
            }
        
        finally:
            # 6. Always cleanup temporary table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logging.debug(f"Cleaned up temporary table: {temp_table_id}")
                except Exception as cleanup_error:
                    logging.warning(f"Failed to cleanup temp table {temp_table_id}: {cleanup_error}")
    
    def process_file(self, json_content: str, file_path: str) -> Dict:
        """Process a single ESPN scoreboard file end-to-end."""
        try:
            # Parse JSON
            raw_data = json.loads(json_content)
            
            # Validate data structure
            errors = self.validate_data(raw_data)
            if errors:
                logging.warning(f"Validation errors for {file_path}: {errors}")
                
                # Send warning for validation issues
                try:
                    notify_warning(
                        title="ESPN Scoreboard: Validation Issues",
                        message=f"Data validation found {len(errors)} issues",
                        details={
                            'file_path': file_path,
                            'error_count': len(errors),
                            'errors': errors[:5]  # First 5 errors
                        }
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
            
            # Transform data
            rows = self.transform_data(raw_data, file_path)
            
            # Load to BigQuery (production-safe with staging table)
            load_result = self.load_data(rows)
            
            return {
                'rows_processed': load_result.get('rows_processed', 0),
                'rows_affected': load_result.get('rows_affected', 0),
                'errors': errors + load_result.get('errors', []),
                'skipped_due_to_streaming_buffer': load_result.get('skipped_due_to_streaming_buffer', False)
            }
            
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in file {file_path}: {str(e)}"
            logging.error(error_msg)
            
            # Send error notification for JSON parse failures
            try:
                notify_error(
                    title="ESPN Scoreboard: JSON Parse Failed",
                    message=f"Failed to parse JSON content",
                    details={
                        'file_path': file_path,
                        'error_type': 'JSONDecodeError',
                        'error_message': str(e)
                    },
                    processor_name="ESPN Scoreboard Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': 0, 'errors': [error_msg]}
            
        except Exception as e:
            error_msg = f"Error processing file {file_path}: {str(e)}"
            logging.error(error_msg, exc_info=True)
            
            # Send error notification for general processing failures
            try:
                notify_error(
                    title="ESPN Scoreboard: Processing Failed",
                    message=f"Unexpected processing failure: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="ESPN Scoreboard Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {'rows_processed': 0, 'errors': [error_msg]}