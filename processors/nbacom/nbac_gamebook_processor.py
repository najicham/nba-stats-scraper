#!/usr/bin/env python3
"""
File: processors/nbacom/nbac_gamebook_processor.py

Process NBA.com gamebook data (box scores with DNP/inactive players) for BigQuery storage.
Resolves inactive player names using Basketball Reference rosters.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

logger = logging.getLogger(__name__)

class NbacGamebookProcessor(ProcessorBase):
    """Process NBA.com gamebook data including active, DNP, and inactive players."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_gamebook_player_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.br_roster_cache = {}  # Cache for Basketball Reference rosters
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        
    def load_br_rosters_for_season(self, season_year: int) -> None:
        """Cache Basketball Reference rosters for a season to resolve inactive player names."""
        if season_year in self.br_roster_cache:
            return
            
        try:
            query = f"""
            SELECT 
                team_abbrev,
                player_last_name,
                player_full_name,
                player_lookup
            FROM `{self.project_id}.nba_raw.br_rosters_current`
            WHERE season_year = {season_year}
            """
            
            results = self.bq_client.query(query).to_dataframe()
            
            # Build lookup: {(team, last_name): [list of players]}
            roster_lookup = defaultdict(list)
            for _, row in results.iterrows():
                key = (row['team_abbrev'], row['player_last_name'])
                roster_lookup[key].append({
                    'full_name': row['player_full_name'],
                    'lookup': row['player_lookup']
                })
            
            self.br_roster_cache[season_year] = roster_lookup
            logger.info(f"Cached {len(results)} roster entries for season {season_year}")
            
        except Exception as e:
            logger.warning(f"Could not load BR rosters for season {season_year}: {e}")
            self.br_roster_cache[season_year] = {}
    
    def extract_opts_from_path(self, file_path: str) -> Dict:
        """Extract metadata from file path.
        Path formats: 
        - nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL/timestamp.json
        - nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL
        """
        try:
            parts = file_path.rstrip('/').split('/')
            
            # Handle different path depths
            if len(parts) >= 4:  # Has game code
                date_str = parts[2]  # "2021-10-19"
                game_code = parts[3]  # "20211019-BKNMIL"
                
                # Extract teams from game code
                game_parts = game_code.split('-')
                if len(game_parts) >= 2:
                    date_compact = game_parts[0]  # "20211019"
                    teams = game_parts[1]  # "BKNMIL"
                    
                    away_team = teams[:3] if len(teams) >= 6 else 'UNK'
                    home_team = teams[3:6] if len(teams) >= 6 else 'UNK'
                else:
                    # Fallback if format is unexpected
                    date_compact = date_str.replace('-', '')
                    away_team = 'UNK'
                    home_team = 'UNK'
            else:
                # Fallback for unexpected structure
                date_str = parts[-2] if len(parts) >= 3 else '2021-01-01'
                date_compact = date_str.replace('-', '')
                away_team = 'UNK'
                home_team = 'UNK'
            
            # Determine season year (Oct-Dec is current year, Jan-Sep is previous year)
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            season_year = date_obj.year if date_obj.month >= 10 else date_obj.year - 1
            
            return {
                'game_date': date_str,
                'game_id': f"{date_compact}_{away_team}_{home_team}",
                'away_team_abbr': away_team,
                'home_team_abbr': home_team,
                'season_year': season_year,
                'source_file_path': file_path
            }
        except Exception as e:
            logger.error(f"Error parsing path {file_path}: {e}")
            return {}
    
    def normalize_player_name(self, name: str) -> str:
        """Create normalized player lookup key."""
        if not name:
            return ''
        # Remove punctuation and spaces, lowercase
        return ''.join(c.lower() for c in name if c.isalnum())
    
    def get_team_abbrev(self, team_name: str) -> str:
        """Extract team abbreviation from full team name.
        This is a placeholder - actual mapping may be needed.
        """
        # NBA.com usually includes team names like "Brooklyn Nets"
        # For now, we'll extract from the game context
        # In production, use a proper team mapping
        return team_name[:3].upper() if team_name else 'UNK'
    
    def resolve_inactive_player(self, last_name: str, team_abbr: str, season_year: int) -> Tuple[str, str]:
        """Resolve inactive player's full name using BR rosters.
        Returns: (full_name, resolution_status)
        """
        self.load_br_rosters_for_season(season_year)
        
        roster_lookup = self.br_roster_cache.get(season_year, {})
        matches = roster_lookup.get((team_abbr, last_name), [])
        
        if len(matches) == 1:
            return matches[0]['full_name'], 'resolved'
        elif len(matches) > 1:
            # Multiple players with same last name on team
            logger.warning(f"Multiple players named {last_name} on {team_abbr}")
            return last_name, 'multiple_matches'
        else:
            # No match found - possibly traded or roster not updated
            logger.debug(f"Could not resolve {last_name} on {team_abbr}")
            return last_name, 'not_found'
    
    def convert_minutes(self, minutes_str: str) -> Optional[float]:
        """Convert minutes string "30:15" to decimal 30.25."""
        if not minutes_str or minutes_str == 'None':
            return None
        try:
            parts = minutes_str.split(':')
            if len(parts) == 2:
                return float(parts[0]) + float(parts[1]) / 60
        except:
            return None
        return None
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the gamebook data structure."""
        errors = []
        
        if not data:
            errors.append("Empty data")
            return errors
            
        if 'game_code' not in data:
            errors.append("Missing game_code")
        
        # At least one of these arrays should exist
        if not any(key in data for key in ['active_players', 'dnp_players', 'inactive_players']):
            errors.append("No player arrays found")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform gamebook data to BigQuery rows."""
        rows = []
        opts = self.extract_opts_from_path(file_path)
        
        if not opts:
            logger.error(f"Could not extract metadata from path: {file_path}")
            return rows
        
        game_code = raw_data.get('game_code', '')
        
        # Process active players
        for player in raw_data.get('active_players', []):
            stats = player.get('stats', {})
            team_name = player.get('team', '')
            
            # Determine which team this player is on
            # This is simplified - in production, use proper team resolution
            team_abbr = self.get_team_abbrev(team_name)
            
            row = {
                'game_id': opts['game_id'],
                'game_code': game_code,
                'game_date': opts['game_date'],
                'season_year': opts['season_year'],
                'home_team_abbr': opts['home_team_abbr'],
                'away_team_abbr': opts['away_team_abbr'],
                'player_name': player.get('name', ''),
                'player_name_original': player.get('name', ''),
                'player_lookup': self.normalize_player_name(player.get('name', '')),
                'team_name': team_name,
                'team_abbr': team_abbr,
                'player_status': 'active',
                'dnp_reason': None,
                'name_resolution_status': None,
                # Stats
                'minutes': stats.get('minutes'),
                'minutes_decimal': self.convert_minutes(stats.get('minutes')),
                'points': stats.get('points'),
                'field_goals_made': stats.get('field_goals_made'),
                'field_goals_attempted': stats.get('field_goals_attempted'),
                'field_goal_percentage': stats.get('field_goal_percentage'),
                'three_pointers_made': stats.get('three_pointers_made'),
                'three_pointers_attempted': stats.get('three_pointers_attempted'),
                'three_point_percentage': stats.get('three_point_percentage'),
                'free_throws_made': stats.get('free_throws_made'),
                'free_throws_attempted': stats.get('free_throws_attempted'),
                'free_throw_percentage': stats.get('free_throw_percentage'),
                'offensive_rebounds': stats.get('offensive_rebounds'),
                'defensive_rebounds': stats.get('defensive_rebounds'),
                'total_rebounds': stats.get('total_rebounds'),
                'assists': stats.get('assists'),
                'steals': stats.get('steals'),
                'blocks': stats.get('blocks'),
                'turnovers': stats.get('turnovers'),
                'personal_fouls': stats.get('personal_fouls'),
                'plus_minus': stats.get('plus_minus'),
                'source_file_path': opts['source_file_path'],
                'processed_at': datetime.utcnow().isoformat()
            }
            rows.append(row)
        
        # Process DNP players
        for player in raw_data.get('dnp_players', []):
            row = {
                'game_id': opts['game_id'],
                'game_code': game_code,
                'game_date': opts['game_date'],
                'season_year': opts['season_year'],
                'home_team_abbr': opts['home_team_abbr'],
                'away_team_abbr': opts['away_team_abbr'],
                'player_name': player.get('name', ''),
                'player_name_original': player.get('name', ''),
                'player_lookup': self.normalize_player_name(player.get('name', '')),
                'team_name': player.get('team', ''),
                'team_abbr': self.get_team_abbrev(player.get('team', '')),
                'player_status': 'dnp',
                'dnp_reason': player.get('dnp_reason', ''),
                'name_resolution_status': None,
                # All stats NULL for DNP
                'minutes': None,
                'minutes_decimal': None,
                'points': None,
                'field_goals_made': None,
                'field_goals_attempted': None,
                'field_goal_percentage': None,
                'three_pointers_made': None,
                'three_pointers_attempted': None,
                'three_point_percentage': None,
                'free_throws_made': None,
                'free_throws_attempted': None,
                'free_throw_percentage': None,
                'offensive_rebounds': None,
                'defensive_rebounds': None,
                'total_rebounds': None,
                'assists': None,
                'steals': None,
                'blocks': None,
                'turnovers': None,
                'personal_fouls': None,
                'plus_minus': None,
                'source_file_path': opts['source_file_path'],
                'processed_at': datetime.utcnow().isoformat()
            }
            rows.append(row)
        
        # Process inactive players with name resolution
        for player in raw_data.get('inactive_players', []):
            original_name = player.get('name', '')
            team_name = player.get('team', '')
            team_abbr = self.get_team_abbrev(team_name)
            
            # Try to resolve full name if only last name provided
            if ' ' not in original_name:  # Likely just a last name
                resolved_name, resolution_status = self.resolve_inactive_player(
                    original_name, team_abbr, opts['season_year']
                )
            else:
                resolved_name = original_name
                resolution_status = None
            
            row = {
                'game_id': opts['game_id'],
                'game_code': game_code,
                'game_date': opts['game_date'],
                'season_year': opts['season_year'],
                'home_team_abbr': opts['home_team_abbr'],
                'away_team_abbr': opts['away_team_abbr'],
                'player_name': resolved_name,
                'player_name_original': original_name,
                'player_lookup': self.normalize_player_name(resolved_name),
                'team_name': team_name,
                'team_abbr': team_abbr,
                'player_status': 'inactive',
                'dnp_reason': player.get('reason', ''),
                'name_resolution_status': resolution_status,
                # All stats NULL for inactive
                'minutes': None,
                'minutes_decimal': None,
                'points': None,
                'field_goals_made': None,
                'field_goals_attempted': None,
                'field_goal_percentage': None,
                'three_pointers_made': None,
                'three_pointers_attempted': None,
                'three_point_percentage': None,
                'free_throws_made': None,
                'free_throws_attempted': None,
                'free_throw_percentage': None,
                'offensive_rebounds': None,
                'defensive_rebounds': None,
                'total_rebounds': None,
                'assists': None,
                'steals': None,
                'blocks': None,
                'turnovers': None,
                'personal_fouls': None,
                'plus_minus': None,
                'source_file_path': opts['source_file_path'],
                'processed_at': datetime.utcnow().isoformat()
            }
            rows.append(row)
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery using MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # For MERGE_UPDATE, we'll delete existing game data and insert new
            if rows:
                game_id = rows[0]['game_id']
                
                # Delete existing data for this game
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE game_id = '{game_id}'
                """
                self.bq_client.query(delete_query).result()
                
                # Insert new data
                result = self.bq_client.insert_rows_json(table_id, rows)
                if result:
                    errors.extend([str(err) for err in result])
                    
        except Exception as e:
            errors.append(str(e))
            logger.error(f"Error loading data: {e}")
        
        return {
            'rows_processed': len(rows),
            'errors': errors,
            'status': 'success' if not errors else 'error'
        }
    