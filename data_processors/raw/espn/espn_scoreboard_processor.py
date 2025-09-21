#!/usr/bin/env python3
# File: processors/espn/espn_scoreboard_processor.py
# Description: Processor for ESPN scoreboard data transformation

import json
import logging
import os
import re
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase

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
            return rows
        
        season_year = self.parse_season_year(game_date)
        scrape_timestamp = raw_data.get('timestamp')
        
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
                continue
        
        logging.info(f"Transformed {len(rows)} games from ESPN scoreboard data")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load transformed data to BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this date first
                game_date = rows[0]['game_date']
                delete_query = f"DELETE FROM `{table_id}` WHERE game_date = '{game_date}'"
                logging.info(f"Deleting existing data for date {game_date}")
                self.bq_client.query(delete_query).result()
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully loaded {len(rows)} rows to {self.table_name}")
        
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data to BigQuery: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }
    
    def process_file(self, json_content: str, file_path: str) -> Dict:
        """Process a single ESPN scoreboard file end-to-end."""
        try:
            # Parse JSON
            raw_data = json.loads(json_content)
            
            # Validate data structure
            errors = self.validate_data(raw_data)
            if errors:
                logging.warning(f"Validation errors for {file_path}: {errors}")
            
            # Transform data
            rows = self.transform_data(raw_data, file_path)
            
            # Load to BigQuery
            load_result = self.load_data(rows)
            
            return {
                'rows_processed': load_result.get('rows_processed', 0),
                'errors': errors + load_result.get('errors', [])
            }
            
        except Exception as e:
            error_msg = f"Error processing file {file_path}: {str(e)}"
            logging.error(error_msg)
            return {'rows_processed': 0, 'errors': [error_msg]}