#!/usr/bin/env python3
# processors/balldontlie/bdl_boxscores_processor.py

import json
import os
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime, date, timezone
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

logger = logging.getLogger(__name__)

class BdlBoxscoresProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_player_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Team abbreviation mapping for consistency
        self.team_mapping = {
            'atlanta hawks': 'ATL', 'boston celtics': 'BOS', 'brooklyn nets': 'BKN',
            'charlotte hornets': 'CHA', 'chicago bulls': 'CHI', 'cleveland cavaliers': 'CLE',
            'dallas mavericks': 'DAL', 'denver nuggets': 'DEN', 'detroit pistons': 'DET',
            'golden state warriors': 'GSW', 'houston rockets': 'HOU', 'indiana pacers': 'IND',
            'los angeles clippers': 'LAC', 'los angeles lakers': 'LAL', 'memphis grizzlies': 'MEM',
            'miami heat': 'MIA', 'milwaukee bucks': 'MIL', 'minnesota timberwolves': 'MIN',
            'new orleans pelicans': 'NOP', 'new york knicks': 'NYK', 'oklahoma city thunder': 'OKC',
            'orlando magic': 'ORL', 'philadelphia 76ers': 'PHI', 'phoenix suns': 'PHX',
            'portland trail blazers': 'POR', 'sacramento kings': 'SAC', 'san antonio spurs': 'SAS',
            'toronto raptors': 'TOR', 'utah jazz': 'UTA', 'washington wizards': 'WAS'
        }
        
        # Standard NBA team abbreviations for validation
        self.valid_team_abbrevs = set(self.team_mapping.values())
    
    def normalize_team_name(self, team_name: str) -> str:
        """Normalize team name to standard abbreviation."""
        if not team_name:
            return ""
        
        # Convert to lowercase and remove extra whitespace
        normalized = team_name.lower().strip()
        
        # Handle common aliases
        aliases = {
            'la lakers': 'los angeles lakers',
            'la clippers': 'los angeles clippers'
        }
        
        if normalized in aliases:
            normalized = aliases[normalized]
            
        mapped_abbrev = self.team_mapping.get(normalized, "")
        
        # If mapping failed, try extracting from original team name
        if not mapped_abbrev:
            # Fallback: use first 3 characters of team name in uppercase
            fallback_abbrev = team_name.upper()[:3]
            logger.warning(f"Unknown team name '{team_name}', using fallback abbreviation '{fallback_abbrev}'")
            return fallback_abbrev
            
        return mapped_abbrev
    
    def extract_team_abbreviation(self, team_data: Dict) -> str:
        """Extract team abbreviation with multiple fallback strategies."""
        if not team_data:
            return ""
        
        # Strategy 1: Use full_name mapping
        full_name = team_data.get('full_name', '')
        if full_name:
            abbrev = self.normalize_team_name(full_name)
            if abbrev and abbrev in self.valid_team_abbrevs:
                return abbrev
        
        # Strategy 2: Use abbreviation field directly
        direct_abbrev = team_data.get('abbreviation', '')
        if direct_abbrev and direct_abbrev.upper() in self.valid_team_abbrevs:
            return direct_abbrev.upper()
        
        # Strategy 3: Use city + name combination
        city = team_data.get('city', '')
        name = team_data.get('name', '')
        if city and name:
            combined_name = f"{city} {name}"
            abbrev = self.normalize_team_name(combined_name)
            if abbrev and abbrev in self.valid_team_abbrevs:
                return abbrev
        
        # Log detailed error for debugging
        logger.error(f"Failed to extract team abbreviation from: {team_data}")
        return ""
    
    def normalize_player_name(self, first_name: str, last_name: str) -> str:
        """Create normalized player lookup string."""
        full_name = f"{first_name} {last_name}".strip()
        # Remove spaces, punctuation, and convert to lowercase
        normalized = re.sub(r'[^a-z0-9]', '', full_name.lower())
        return normalized
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON structure."""
        errors = []
        
        if 'boxScores' not in data:
            errors.append("Missing 'boxScores' field")
            return errors
            
        if not isinstance(data['boxScores'], list):
            errors.append("'boxScores' is not a list")
            return errors
            
        if not data['boxScores']:
            errors.append("Empty boxScores array")
            
        return errors
    
    def extract_season_year(self, game_date: str, season_field: Optional[int] = None) -> int:
        """Extract season year from date or season field."""
        if season_field:
            return season_field
            
        # Fall back to date-based calculation
        game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
        if game_dt.month >= 10:  # October or later = start of season
            return game_dt.year
        else:  # Before October = second year of season
            return game_dt.year - 1
    
    def validate_game_id_format(self, game_id: str) -> bool:
        """Validate that game ID follows YYYYMMDD_AWAY_HOME format."""
        parts = game_id.split('_')
        if len(parts) != 3:
            return False
        
        date_part, away_team, home_team = parts
        
        # Validate date part (8 digits)
        if len(date_part) != 8 or not date_part.isdigit():
            return False
        
        # Validate team abbreviations (3 characters each)
        if len(away_team) != 3 or len(home_team) != 3:
            return False
        
        # Validate teams are known abbreviations
        if away_team not in self.valid_team_abbrevs or home_team not in self.valid_team_abbrevs:
            logger.warning(f"Unknown team abbreviations in game_id {game_id}: {away_team}, {home_team}")
        
        return True
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform BDL box scores JSON to BigQuery rows."""
        rows = []
        
        box_scores = raw_data.get('boxScores', [])
        
        for game_idx, game in enumerate(box_scores):
            # Extract game-level data
            game_date_str = game.get('date')
            if not game_date_str:
                logger.warning(f"Skipping game {game_idx} with no date in {file_path}")
                continue
                
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
            game_date_str = game_date.strftime('%Y-%m-%d')
            season_year = self.extract_season_year(game_date_str, game.get('season'))
            
            # Extract team information - improved extraction
            home_team = game.get('home_team', {})
            away_team = game.get('visitor_team', {})  # Note: BDL calls it visitor_team
            
            home_team_abbr = self.extract_team_abbreviation(home_team)
            away_team_abbr = self.extract_team_abbreviation(away_team)
            
            # Validate both teams were successfully extracted
            if not home_team_abbr or not away_team_abbr:
                logger.error(f"Failed to extract team abbreviations for game {game_idx} in {file_path}")
                logger.error(f"Home team data: {home_team}")
                logger.error(f"Away team data: {away_team}")
                continue
            
            # CRITICAL FIX: Create game_id in CORRECT format: YYYYMMDD_AWAY_HOME
            game_id = f"{game_date.strftime('%Y%m%d')}_{away_team_abbr}_{home_team_abbr}"
            
            # Validate game ID format
            if not self.validate_game_id_format(game_id):
                logger.error(f"Invalid game_id format generated: {game_id}")
                continue
            
            logger.info(f"Processing game {game_id} ({away_team_abbr} @ {home_team_abbr})")
            
            # Process home team players
            home_players = home_team.get('players', [])
            for player_stats in home_players:
                player_info = player_stats.get('player', {})
                
                # Create player row
                row = self.create_player_row(
                    game_id=game_id,
                    game_date=game_date_str,
                    season_year=season_year,
                    game_status=game.get('status', ''),
                    period=game.get('period'),
                    is_postseason=game.get('postseason', False),
                    home_team_abbr=home_team_abbr,
                    away_team_abbr=away_team_abbr,
                    home_team_score=game.get('home_team_score'),
                    away_team_score=game.get('visitor_team_score'),
                    team_abbr=home_team_abbr,
                    player_info=player_info,
                    player_stats=player_stats,
                    file_path=file_path
                )
                
                if row:
                    rows.append(row)
            
            # Process away team players (renamed from visitor for clarity)
            away_players = away_team.get('players', [])
            for player_stats in away_players:
                player_info = player_stats.get('player', {})
                
                # Create player row
                row = self.create_player_row(
                    game_id=game_id,
                    game_date=game_date_str,
                    season_year=season_year,
                    game_status=game.get('status', ''),
                    period=game.get('period'),
                    is_postseason=game.get('postseason', False),
                    home_team_abbr=home_team_abbr,
                    away_team_abbr=away_team_abbr,
                    home_team_score=game.get('home_team_score'),
                    away_team_score=game.get('visitor_team_score'),
                    team_abbr=away_team_abbr,
                    player_info=player_info,
                    player_stats=player_stats,
                    file_path=file_path
                )
                
                if row:
                    rows.append(row)
        
        logger.info(f"Generated {len(rows)} player records from {len(box_scores)} games in {file_path}")
        return rows
    
    def create_player_row(self, **kwargs) -> Optional[Dict]:
        """Create a single player performance row."""
        try:
            player_info = kwargs['player_info']
            player_stats = kwargs['player_stats']
            
            first_name = player_info.get('first_name', '')
            last_name = player_info.get('last_name', '')
            
            if not first_name or not last_name:
                logger.warning(f"Skipping player with incomplete name: {player_info}")
                return None
            
            player_full_name = f"{first_name} {last_name}"
            player_lookup = self.normalize_player_name(first_name, last_name)
            
            # Handle nullable percentage fields
            def safe_float(value):
                return float(value) if value is not None else None
            
            def safe_int(value):
                return int(value) if value is not None else 0
            
            row = {
                # Core identifiers
                'game_id': kwargs['game_id'],
                'game_date': kwargs['game_date'],
                'season_year': kwargs['season_year'],
                'game_status': kwargs['game_status'],
                'period': kwargs['period'],
                'is_postseason': kwargs['is_postseason'],
                
                # Team context
                'home_team_abbr': kwargs['home_team_abbr'],
                'away_team_abbr': kwargs['away_team_abbr'],
                'home_team_score': kwargs['home_team_score'],
                'away_team_score': kwargs['away_team_score'],
                'team_abbr': kwargs['team_abbr'],
                
                # Player identification
                'player_full_name': player_full_name,
                'player_lookup': player_lookup,
                'bdl_player_id': player_info.get('id'),
                'jersey_number': player_info.get('jersey_number'),
                'position': player_info.get('position'),
                
                # Performance stats
                'minutes': player_stats.get('min'),
                'points': safe_int(player_stats.get('pts')),
                'assists': safe_int(player_stats.get('ast')),
                'rebounds': safe_int(player_stats.get('reb')),
                'offensive_rebounds': safe_int(player_stats.get('oreb')),
                'defensive_rebounds': safe_int(player_stats.get('dreb')),
                'steals': safe_int(player_stats.get('stl')),
                'blocks': safe_int(player_stats.get('blk')),
                'turnovers': safe_int(player_stats.get('turnover')),
                'personal_fouls': safe_int(player_stats.get('pf')),
                
                # Shooting stats
                'field_goals_made': safe_int(player_stats.get('fgm')),
                'field_goals_attempted': safe_int(player_stats.get('fga')),
                'field_goal_pct': safe_float(player_stats.get('fg_pct')),
                'three_pointers_made': safe_int(player_stats.get('fg3m')),
                'three_pointers_attempted': safe_int(player_stats.get('fg3a')),
                'three_point_pct': safe_float(player_stats.get('fg3_pct')),
                'free_throws_made': safe_int(player_stats.get('ftm')),
                'free_throws_attempted': safe_int(player_stats.get('fta')),
                'free_throw_pct': safe_float(player_stats.get('ft_pct')),
                
                # Processing metadata
                'source_file_path': kwargs['file_path'],
                'created_at': datetime.now(timezone.utc).isoformat(),
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            
            return row
            
        except Exception as e:
            logger.error(f"Error creating player row: {e}")
            logger.error(f"Player info: {kwargs.get('player_info', {})}")
            logger.error(f"Player stats: {kwargs.get('player_stats', {})}")
            return None
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load transformed data to BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Get all unique game_ids in this batch
                game_ids = set(row['game_id'] for row in rows)
                
                for game_id in game_ids:
                    # Get the game_date for this game_id (all rows with same game_id have same date)
                    game_date = next(row['game_date'] for row in rows if row['game_id'] == game_id)
                    
                    # Delete existing data for this game (WITH PARTITION FILTER)
                    delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}' AND game_date = '{game_date}'"
                    self.bq_client.query(delete_query).result()
                    logger.info(f"Deleted existing data for game {game_id}")
            
            # Validate all game IDs before inserting
            invalid_game_ids = []
            for row in rows:
                if not self.validate_game_id_format(row['game_id']):
                    invalid_game_ids.append(row['game_id'])
            
            if invalid_game_ids:
                error_msg = f"Invalid game_id formats detected: {invalid_game_ids[:5]}"
                errors.append(error_msg)
                logger.error(error_msg)
                return {'rows_processed': 0, 'errors': errors}
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logger.error(f"BigQuery insert errors: {result}")
            else:
                logger.info(f"Successfully inserted {len(rows)} rows for {len(game_ids)} games")
                
                # Log game ID format compliance
                sample_game_ids = list(set(row['game_id'] for row in rows))[:3]
                logger.info(f"Sample game IDs inserted (AWAY_HOME format): {sample_game_ids}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading data: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }