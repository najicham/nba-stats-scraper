#!/usr/bin/env python3
# File: processors/espn/espn_boxscore_processor.py
# Description: Processor for ESPN boxscore data transformation

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

from processors.processor_base import ProcessorBase
from shared.utils.nba_team_mapper import NBATeamMapper

class EspnBoxscoreProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.espn_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'
        self.team_mapper = NBATeamMapper()
        
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
        if 'gamepackageJSON' not in data:
            errors.append("Missing gamepackageJSON")
        elif 'boxscore' not in data.get('gamepackageJSON', {}):
            errors.append("Missing boxscore data")
            
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform ESPN boxscore data into BigQuery format."""
        validation_errors = self.validate_data(raw_data)
        if validation_errors:
            logging.error(f"Validation failed for {file_path}: {validation_errors}")
            return []
        
        # Extract game info from file path
        game_info = self.extract_game_info_from_path(file_path)
        if not game_info.get('date') or not game_info.get('espn_game_id'):
            logging.error(f"Could not extract game info from path: {file_path}")
            return []
        
        try:
            # Navigate ESPN JSON structure
            game_package = raw_data['gamepackageJSON']
            boxscore = game_package['boxscore']
            header = game_package.get('header', {})
            
            # Extract game-level info
            competition = header.get('competitions', [{}])[0]
            competitors = competition.get('competitors', [])
            
            if len(competitors) != 2:
                logging.error(f"Expected 2 competitors, found {len(competitors)}")
                return []
            
            # Determine home/away teams
            home_team_data = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away_team_data = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            
            if not home_team_data or not away_team_data:
                logging.error("Could not identify home/away teams")
                return []
            
            # Map team names to standard abbreviations
            home_team_name = home_team_data['team'].get('displayName', '')
            away_team_name = away_team_data['team'].get('displayName', '')
            
            home_team_abbr = self.team_mapper.get_team_abbreviation(home_team_name)
            away_team_abbr = self.team_mapper.get_team_abbreviation(away_team_name)
            
            if not home_team_abbr or not away_team_abbr:
                logging.error(f"Could not map teams: {home_team_name} -> {home_team_abbr}, {away_team_name} -> {away_team_abbr}")
                return []
            
            # Extract game details
            game_date = game_info['date']
            game_id = self.construct_game_id(game_date, home_team_abbr, away_team_abbr)
            
            # Extract season year (assume games in Oct+ are new season)
            year = int(game_date[:4])
            month = int(game_date[5:7])
            season_year = year if month < 10 else year + 1
            
            # Game status and scores
            game_status = competition.get('status', {}).get('type', {}).get('description', 'Unknown')
            home_score = int(home_team_data.get('score', 0))
            away_score = int(away_team_data.get('score', 0))
            
            rows = []
            
            # Process players for both teams
            teams_data = boxscore.get('teams', [])
            for team_data in teams_data:
                team_name = team_data.get('team', {}).get('displayName', '')
                team_abbr = self.team_mapper.get_team_abbreviation(team_name)
                
                if not team_abbr:
                    logging.warning(f"Could not map team: {team_name}")
                    continue
                
                # Process player statistics
                player_stats = team_data.get('statistics', [])
                for stat_category in player_stats:
                    if stat_category.get('name') == 'General':
                        athletes = stat_category.get('athletes', [])
                        
                        for athlete_data in athletes:
                            athlete = athlete_data.get('athlete', {})
                            stats = athlete_data.get('stats', [])
                            
                            # Convert stats array to dictionary
                            stat_dict = {}
                            stat_names = stat_category.get('names', [])
                            for i, stat_value in enumerate(stats):
                                if i < len(stat_names):
                                    stat_dict[stat_names[i]] = stat_value
                            
                            # Build player record
                            player_record = {
                                # Core identifiers
                                'game_id': game_id,
                                'espn_game_id': game_info['espn_game_id'],
                                'game_date': game_date,
                                'season_year': season_year,
                                'game_status': game_status,
                                'period': self.safe_int_conversion(stat_dict.get('PERIOD')),
                                'is_postseason': False,  # TODO: Detect postseason
                                
                                # Team information
                                'home_team_abbr': home_team_abbr,
                                'away_team_abbr': away_team_abbr,
                                'home_team_score': home_score,
                                'away_team_score': away_score,
                                'home_team_espn_id': home_team_data['team'].get('id', ''),
                                'away_team_espn_id': away_team_data['team'].get('id', ''),
                                
                                # Player information
                                'team_abbr': team_abbr,
                                'player_full_name': athlete.get('displayName', ''),
                                'player_lookup': self.normalize_player_name(athlete.get('displayName', '')),
                                'espn_player_id': str(athlete.get('id', '')),
                                'jersey_number': str(athlete.get('jersey', '')),
                                'position': athlete.get('position', {}).get('abbreviation', ''),
                                'starter': athlete_data.get('starter', False),
                                
                                # Core statistics
                                'minutes': self.parse_minutes(stat_dict.get('MIN', '0:00')),
                                'points': self.safe_int_conversion(stat_dict.get('PTS')),
                                'field_goals_made': self.safe_int_conversion(stat_dict.get('FGM')),
                                'field_goals_attempted': self.safe_int_conversion(stat_dict.get('FGA')),
                                'field_goal_percentage': self.safe_float_conversion(stat_dict.get('FG%')),
                                'three_pointers_made': self.safe_int_conversion(stat_dict.get('3PM')),
                                'three_pointers_attempted': self.safe_int_conversion(stat_dict.get('3PA')),
                                'three_point_percentage': self.safe_float_conversion(stat_dict.get('3P%')),
                                'free_throws_made': self.safe_int_conversion(stat_dict.get('FTM')),
                                'free_throws_attempted': self.safe_int_conversion(stat_dict.get('FTA')),
                                'free_throw_percentage': self.safe_float_conversion(stat_dict.get('FT%')),
                                
                                # Additional statistics
                                'rebounds': self.safe_int_conversion(stat_dict.get('REB')),
                                'offensive_rebounds': self.safe_int_conversion(stat_dict.get('OREB')),
                                'defensive_rebounds': self.safe_int_conversion(stat_dict.get('DREB')),
                                'assists': self.safe_int_conversion(stat_dict.get('AST')),
                                'steals': self.safe_int_conversion(stat_dict.get('STL')),
                                'blocks': self.safe_int_conversion(stat_dict.get('BLK')),
                                'turnovers': self.safe_int_conversion(stat_dict.get('TO')),
                                'fouls': self.safe_int_conversion(stat_dict.get('PF')),
                                'plus_minus': self.safe_int_conversion(stat_dict.get('+/-')),
                                
                                # Processing metadata
                                'source_file_path': file_path,
                                'created_at': datetime.now(timezone.utc).isoformat(),
                                'processed_at': datetime.now(timezone.utc).isoformat()
                            }
                            
                            rows.append(player_record)
            
            logging.info(f"Transformed {len(rows)} player records from {file_path}")
            return rows
            
        except Exception as e:
            logging.error(f"Error transforming data from {file_path}: {str(e)}")
            return []
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery with MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this game first
                game_id = rows[0]['game_id']
                delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}'"
                logging.info(f"Deleting existing data for game_id: {game_id}")
                self.bq_client.query(delete_query).result()
            
            # Insert new data
            logging.info(f"Inserting {len(rows)} rows to {table_id}")
            result = self.bq_client.insert_rows_json(table_id, rows)
            
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully loaded {len(rows)} rows")
        
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }