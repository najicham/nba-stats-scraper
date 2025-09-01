#!/usr/bin/env python3
# File: processors/bigdataball/bigdataball_pbp_processor.py
# Description: Processor for BigDataBall play-by-play data transformation

import json, logging, re
from typing import Dict, List, Optional
from datetime import datetime
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class BigDataBallPbpProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bigdataball_play_by_play'
        self.processing_strategy = 'MERGE_UPDATE'  # Replace existing game data
        
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
        # Convert date from 2024-11-01 to 20241101
        date_part = game_date.replace('-', '')
        return f"{date_part}_{away_team}_{home_team}"
    
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
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform BigDataBall JSON to BigQuery rows"""
        game_info = raw_data['game_info']
        play_by_play = raw_data['playByPlay']
        
        # Construct consistent game_id
        game_id = self.construct_game_id(
            game_info['date'], 
            game_info['away_team'], 
            game_info['home_team']
        )
        
        # Extract season year (2024 for 2024-25 season)
        game_date = game_info['date']
        season_year = int(game_date.split('-')[0])
        if int(game_date.split('-')[1]) < 10:  # Before October = previous season
            season_year -= 1
        
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
                'event_sequence': event.get('play_id'),
                'period': event.get('period'),
                
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
                'score_home': event.get('home_score'),
                'score_away': event.get('away_score'),
                
                # Primary Player
                'player_1_name': event.get('player'),
                'player_1_lookup': self.normalize_player_name(event.get('player')) if event.get('player') else None,
                'player_1_team_abbr': event.get('team'),
                
                # Secondary Player
                'player_2_name': player_2_name,
                'player_2_lookup': self.normalize_player_name(player_2_name) if player_2_name else None,
                'player_2_team_abbr': None,  # Context-dependent, would need team lookup
                'player_2_role': player_2_role,
                
                # Tertiary Player
                'player_3_name': player_3_name,
                'player_3_lookup': self.normalize_player_name(player_3_name) if player_3_name else None,
                'player_3_team_abbr': None,  # Context-dependent, would need team lookup
                'player_3_role': player_3_role,
                
                # Shot Details
                'shot_made': event.get('result') == 'made' if event.get('event_type') == 'shot' else None,
                'shot_type': self.determine_shot_type(event.get('type')) if event.get('event_type') == 'shot' else None,
                'shot_distance': event.get('shot_distance'),
                'points_scored': event.get('points'),
                
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
                'csv_row_number': None,  # Would need to track during CSV parsing
                'processed_at': datetime.utcnow().isoformat(),
                'created_at': datetime.utcnow().isoformat()
            }
            
            rows.append(row)
        
        return rows
    
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
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery using MERGE_UPDATE strategy"""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # MERGE_UPDATE: Delete existing data for this game first
            game_id = rows[0]['game_id']
            delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}'"
            logging.info(f"Deleting existing data for game {game_id}")
            self.bq_client.query(delete_query).result()
            
            # Insert new data
            logging.info(f"Inserting {len(rows)} rows for game {game_id}")
            result = self.bq_client.insert_rows_json(table_id, rows)
            
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Error loading data: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0, 
            'errors': errors,
            'game_id': rows[0]['game_id'] if rows else None
        }