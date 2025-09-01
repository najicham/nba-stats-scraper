#!/usr/bin/env python3
# File: processors/nbacom/nbac_scoreboard_v2_processor.py
# Description: Processor for NBA.com Scoreboard V2 data transformation

import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class NbacScoreboardV2Processor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_scoreboard_v2'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # Team abbreviation normalization mapping
        self.team_abbr_mapping = {
            'NY': 'NYK',      # New York Knicks
            'GS': 'GSW',      # Golden State Warriors  
            'SA': 'SAS',      # San Antonio Spurs
            'NO': 'NOP',      # New Orleans Pelicans
            'UTAH': 'UTA',    # Utah Jazz
            'BKN': 'BRK',     # Brooklyn Nets (sometimes appears as BRK)
        }
    
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
        
        for i, game in enumerate(data['games']):
            if 'gameId' not in game:
                errors.append(f"Game {i}: Missing gameId")
            
            if 'teams' not in game:
                errors.append(f"Game {i}: Missing teams")
                continue
                
            if not isinstance(game['teams'], list) or len(game['teams']) != 2:
                errors.append(f"Game {i}: teams must be list of exactly 2 teams")
                continue
            
            for j, team in enumerate(game['teams']):
                if 'abbreviation' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing abbreviation")
                if 'score' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing score")
                if 'homeAway' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing homeAway")
                if 'winner' not in team:
                    errors.append(f"Game {i}, Team {j}: Missing winner")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform scoreboard data into BigQuery format."""
        rows = []
        
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
        
        season_year = self.extract_season_year(gamedate) if gamedate else 2024
        
        for game in raw_data.get('games', []):
            try:
                # Identify home and away teams
                home_team = None
                away_team = None
                
                for team in game.get('teams', []):
                    if team.get('homeAway') == 'home':
                        home_team = team
                    elif team.get('homeAway') == 'away':
                        away_team = team
                
                if not home_team or not away_team:
                    logging.warning(f"Game {game.get('gameId')}: Could not identify home/away teams")
                    continue
                
                # Determine winner
                winning_team_abbr = None
                winning_team_side = None
                
                if home_team.get('winner'):
                    winning_team_abbr = self.normalize_team_abbreviation(home_team.get('abbreviation', ''))
                    winning_team_side = 'home'
                elif away_team.get('winner'):
                    winning_team_abbr = self.normalize_team_abbreviation(away_team.get('abbreviation', ''))
                    winning_team_side = 'away'
                
                # Parse start time
                start_time = None
                if game.get('startTime'):
                    try:
                        start_time = datetime.fromisoformat(game['startTime'].replace('Z', '+00:00'))
                    except ValueError:
                        logging.warning(f"Could not parse startTime: {game.get('startTime')}")
                
                # Convert scores to integers
                home_score = None
                away_score = None
                try:
                    home_score = int(home_team.get('score', 0))
                    away_score = int(away_team.get('score', 0))
                except (ValueError, TypeError):
                    logging.warning(f"Game {game.get('gameId')}: Could not convert scores to integers")
                
                row = {
                    'game_id': game.get('gameId', ''),
                    'game_date': game_date.isoformat() if game_date else None,
                    'season_year': season_year,
                    'start_time': start_time.isoformat() if start_time else None,
                    
                    # Game status
                    'game_status_id': game.get('statusId', ''),
                    'game_state': game.get('state', ''),
                    'game_status_text': game.get('status', ''),
                    
                    # Home team
                    'home_team_id': home_team.get('teamId', ''),
                    'home_team_abbr': self.normalize_team_abbreviation(home_team.get('abbreviation', '')),
                    'home_team_abbr_raw': home_team.get('abbreviation', ''),
                    'home_score': home_score,
                    
                    # Away team
                    'away_team_id': away_team.get('teamId', ''),
                    'away_team_abbr': self.normalize_team_abbreviation(away_team.get('abbreviation', '')),
                    'away_team_abbr_raw': away_team.get('abbreviation', ''),
                    'away_score': away_score,
                    
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
                
            except Exception as e:
                logging.error(f"Error processing game {game.get('gameId', 'unknown')}: {str(e)}")
                continue
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load transformed data into BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing games for the same date
                game_date = rows[0]['game_date']
                if game_date:
                    delete_query = f"""
                    DELETE FROM `{table_id}` 
                    WHERE game_date = '{game_date}'
                    """
                    self.bq_client.query(delete_query).result()
                    logging.info(f"Deleted existing records for date: {game_date}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully inserted {len(rows)} rows")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data to BigQuery: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0, 
            'errors': errors
        }