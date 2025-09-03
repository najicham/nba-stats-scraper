#!/usr/bin/env python3
"""
File: processors/nbacom/nbac_gamebook_processor.py

Process NBA.com gamebook data (box scores with DNP/inactive players) for BigQuery storage.
Resolves inactive player names using Basketball Reference rosters.
Updated with aggressive team name normalization to handle all case/formatting variations.
"""

import json
import logging
import re
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from google.cloud import bigquery

# Support both module execution and direct execution
try:
    # Module execution: python -m processors.nbacom.nbac_gamebook_processor
    from ..processor_base import ProcessorBase
except ImportError:
    # Direct execution: python processors/nbacom/nbac_gamebook_processor.py
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from processors.processor_base import ProcessorBase

# Simple team mapper import now that shared/utils/__init__.py is clean
from shared.utils.nba_team_mapper import get_nba_tricode, get_nba_tricode_fuzzy

logger = logging.getLogger(__name__)


class NbacGamebookProcessor(ProcessorBase):
    """Process NBA.com gamebook data including active, DNP, and inactive players."""
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_gamebook_player_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.br_roster_cache = {}  # Cache for Basketball Reference rosters
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
    
    def log_quality_issue(self, issue_type: str, severity: str, identifier: str, details: Dict):
        """Log data quality issues for review."""
        # For now, just log to console. Could write to BigQuery quality table later
        logger.warning(f"Quality issue [{severity}] {issue_type}: {identifier} - {details}")
        
    def load_br_rosters_for_season(self, season_year: int) -> None:
        """Cache Basketball Reference rosters for a season to resolve inactive player names."""
        if season_year in self.br_roster_cache:
            return
            
        query = f"""
        SELECT DISTINCT
            team_abbrev,
            player_last_name,
            player_full_name,
            player_lookup
        FROM `nba_raw.br_rosters_current`
        WHERE season_year = {season_year}
        """
        
        try:
            results = self.bq_client.query(query).to_dataframe()
            
            # Build lookup: {(team, last_name): [list of players]}
            roster_lookup = defaultdict(list)
            for _, row in results.iterrows():
                key = (row['team_abbrev'], row['player_last_name'].lower())
                roster_lookup[key].append({
                    'full_name': row['player_full_name'],
                    'lookup': row['player_lookup']
                })
            
            self.br_roster_cache[season_year] = roster_lookup
            logger.info(f"Loaded {len(results)} roster entries for {season_year} season")
        except Exception as e:
            logger.warning(f"Could not load BR rosters for {season_year}: {e}")
            self.br_roster_cache[season_year] = {}
    
    def resolve_inactive_player_enhanced(self, last_name: str, team_abbr: str, season_year: int) -> Dict:
        """Enhanced name resolution with database integration."""
        resolution_id = f"{team_abbr}_{last_name}_{season_year}"
        
        # Check if resolution already exists
        existing_resolution = self.get_existing_resolution(resolution_id)
        if existing_resolution:
            if existing_resolution['resolution_status'] == 'validated':
                return {
                    'name': existing_resolution['resolved_name'] or last_name,
                    'lookup': existing_resolution['resolved_lookup'] or self.normalize_name(last_name),
                    'status': 'validated',
                    'confidence': existing_resolution['confidence_score'],
                    'resolution_id': resolution_id,
                    'method': existing_resolution['resolution_method']
                }
        
        # Perform new resolution
        roster_matches = self.get_roster_matches(last_name, team_abbr, season_year)
        
        if len(roster_matches) == 1:
            # Auto-resolve with high confidence
            resolved_name = roster_matches[0]['full_name']
            resolved_lookup = roster_matches[0]['lookup']
            
            self.create_resolution_record({
                'resolution_id': resolution_id,
                'team_abbr': team_abbr,
                'original_name': last_name,
                'season_year': season_year,
                'resolved_name': resolved_name,
                'resolved_lookup': resolved_lookup,
                'resolution_method': 'auto_exact',
                'resolution_status': 'validated',
                'confidence_score': 1.0,
                'possible_matches': json.dumps(roster_matches)
            })
            
            return {
                'name': resolved_name,
                'lookup': resolved_lookup,
                'status': 'validated',
                'confidence': 1.0,
                'resolution_id': resolution_id,
                'method': 'auto_exact'
            }
        
        elif len(roster_matches) > 1:
            # Multiple matches - needs manual review
            self.create_resolution_record({
                'resolution_id': resolution_id,
                'team_abbr': team_abbr,
                'original_name': last_name,
                'season_year': season_year,
                'resolved_name': None,
                'resolved_lookup': None,
                'resolution_method': 'auto_fuzzy',
                'resolution_status': 'pending',
                'confidence_score': 0.6,
                'possible_matches': json.dumps(roster_matches),
                'context_notes': f"Multiple matches found: {[m['full_name'] for m in roster_matches]}"
            })
            
            return {
                'name': last_name,  # Use original until resolved
                'lookup': self.normalize_name(last_name),
                'status': 'multiple_matches',
                'confidence': 0.6,
                'resolution_id': resolution_id,
                'method': 'pending_review'
            }
        
        else:
            # No matches found
            self.create_resolution_record({
                'resolution_id': resolution_id,
                'team_abbr': team_abbr,
                'original_name': last_name,
                'season_year': season_year,
                'resolved_name': None,
                'resolved_lookup': None,
                'resolution_method': 'not_found',
                'resolution_status': 'pending',
                'confidence_score': 0.0,
                'possible_matches': json.dumps([]),
                'context_notes': f"No roster match found for {last_name} on {team_abbr}"
            })
            
            return {
                'name': last_name,
                'lookup': self.normalize_name(last_name),
                'status': 'not_found',
                'confidence': 0.0,
                'resolution_id': resolution_id,
                'method': 'not_found'
            }
        
    def get_existing_resolution(self, resolution_id: str) -> Optional[Dict]:
        """Check if resolution already exists in database."""
        query = """
        SELECT * FROM `nba-props-platform.nba_raw.player_name_resolutions`
        WHERE resolution_id = @resolution_id
        """
        # Execute query and return result

    def create_resolution_record(self, resolution_data: Dict):
        """Insert new resolution record into database."""
        # Insert into player_name_resolutions table
        # Update games_affected count
        # Set first_seen_date and last_seen_date

    def update_resolution_games_count(self, resolution_id: str):
        """Update the count of games affected by this resolution."""
        # Count games using this resolution_id
        # Update games_affected field
    
    def normalize_name(self, name: str) -> str:
        """Create normalized lookup key from name."""
        return name.lower().replace(' ', '').replace('-', '').replace("'", '')
    
    def normalize_team_name(self, team_name: str) -> str:
        """Aggressively normalize team name for consistent mapping."""
        if not team_name:
            return ""
        
        # Convert to lowercase and strip whitespace
        normalized = team_name.lower().strip()
        
        # Handle known aliases first (before aggressive normalization)
        normalized = normalized.replace("la clippers", "los angeles clippers")
        normalized = normalized.replace("la lakers", "los angeles lakers")
        
        # Aggressive normalization: remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def extract_game_info(self, file_path: str, data: Dict) -> Dict:
        """Extract game metadata from file path and data."""
        # Path format: nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL/20250827_234400.json
        path_parts = file_path.split('/')
        date_str = path_parts[-3]  # 2021-10-19
        game_code = path_parts[-2]  # 20211019-BKNMIL
        
        # Parse game code
        date_part = game_code[:8]  # 20211019
        teams_part = game_code[9:]  # BKNMIL
        
        # Extract teams (first 3 chars = away, last 3 = home)
        away_team = teams_part[:3] if len(teams_part) >= 6 else None
        home_team = teams_part[3:6] if len(teams_part) >= 6 else None
        
        # Build game_id in standard format
        game_id = f"{date_part}_{away_team}_{home_team}" if away_team and home_team else game_code
        
        # Extract season year (Oct-Dec = current year, Jan-Jun = previous year)
        game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        month = game_date.month
        season_year = game_date.year if month >= 10 else game_date.year - 1
        
        return {
            'game_id': game_id,
            'game_code': data.get('game_code', game_code),
            'game_date': game_date,
            'season_year': season_year,
            'home_team_abbr': home_team,
            'away_team_abbr': away_team
        }
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the gamebook JSON structure."""
        errors = []
        
        # Check for required fields
        if 'game_code' not in data:
            errors.append("Missing 'game_code' field")
        
        # Check for at least one player array
        player_arrays = ['active_players', 'dnp_players', 'inactive_players']
        if not any(arr in data for arr in player_arrays):
            errors.append(f"No player arrays found. Expected at least one of: {player_arrays}")
        
        return errors
    
    def convert_minutes(self, minutes_str: str) -> Optional[float]:
        """Convert minutes string (MM:SS) to decimal."""
        if not minutes_str or minutes_str == '-':
            return None
        try:
            parts = minutes_str.split(':')
            if len(parts) == 2:
                return float(parts[0]) + float(parts[1]) / 60
        except (ValueError, AttributeError):
            pass
        return None
    
    def get_team_abbreviation(self, team_name: str) -> Optional[str]:
        """Map team name to NBA tricode using shared utility."""
        if not team_name:
            return None
        
        # Try exact match first (fast)
        result = get_nba_tricode(team_name)
        if result:
            return result
        
        # Try fuzzy match (robust)
        result = get_nba_tricode_fuzzy(team_name, min_confidence=80)
        if result:
            return result
        
        # Log unmapped for debugging
        logger.warning(f"Could not map team name: '{team_name}'")
        return None
    
    def process_active_player(self, player: Dict, game_info: Dict) -> Dict:
        """Process an active player with stats."""
        stats = player.get('stats', {})
        
        # Determine team abbreviation
        team_abbr = None
        if player.get('team'):
            # Map full team name to abbreviation using aggressive normalization
            team_abbr = self.get_team_abbreviation(player['team'])
        
        return {
            'game_id': game_info['game_id'],
            'game_code': game_info['game_code'],
            'game_date': game_info['game_date'].isoformat() if hasattr(game_info['game_date'], 'isoformat') else game_info['game_date'],
            'season_year': game_info['season_year'],
            'home_team_abbr': game_info['home_team_abbr'],
            'away_team_abbr': game_info['away_team_abbr'],
            'player_name': player.get('name'),
            'player_name_original': player.get('name'),
            'player_lookup': self.normalize_name(player.get('name', '')),
            'team_abbr': team_abbr,
            'player_status': 'active',
            'dnp_reason': None,
            'name_resolution_status': 'original',
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
            'total_rebounds': stats.get('rebounds_total', stats.get('rebounds')),
            'assists': stats.get('assists'),
            'steals': stats.get('steals'),
            'blocks': stats.get('blocks'),
            'turnovers': stats.get('turnovers'),
            'personal_fouls': stats.get('fouls', stats.get('personal_fouls')),
            'plus_minus': stats.get('plus_minus'),
            'source_file_path': None  # Will be set by transform_data
        }
    
    def process_inactive_player(self, player: Dict, game_info: Dict, status: str) -> Dict:
        """Process a DNP or inactive player."""
        # Determine team abbreviation
        team_abbr = None
        if player.get('team'):
            team_abbr = self.get_team_abbreviation(player['team'])
        
        # For inactive players, try to resolve full name
        player_name = player.get('name', '')
        player_lookup = self.normalize_name(player_name)
        resolution_status = 'original'
        confidence = None
        method = None
        
        if status == 'inactive' and player_name and not ' ' in player_name:
            # Likely just a last name, try to resolve
            if team_abbr:
                resolved_name, resolved_lookup, resolution_status = self.resolve_inactive_player(
                    player_name, team_abbr, game_info['season_year']
                )
                player_lookup = resolved_lookup
                if resolution_status == 'resolved':
                    player_name = resolved_name
                    confidence = 1.0
                    method = 'auto_exact'
                elif resolution_status == 'multiple_matches':
                    confidence = 0.6
                    method = 'pending_review'
                elif resolution_status == 'not_found':
                    confidence = 0.0
                    method = 'not_found'
        
        return {
            'game_id': game_info['game_id'],
            'game_code': game_info['game_code'],
            'game_date': game_info['game_date'].isoformat() if hasattr(game_info['game_date'], 'isoformat') else game_info['game_date'],
            'season_year': game_info['season_year'],
            'home_team_abbr': game_info['home_team_abbr'],
            'away_team_abbr': game_info['away_team_abbr'],
            'player_name': player_name,
            'player_name_original': player.get('name'),
            'player_lookup': player_lookup,
            'team_abbr': team_abbr,
            'player_status': status,
            'dnp_reason': player.get('dnp_reason') or player.get('reason'),
            'name_resolution_status': resolution_status,
            # All stats are NULL for inactive players
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

            'name_resolution_confidence': confidence,
            'name_resolution_method': method,
            'resolution_id': None,  # Keep simple for now
            'name_last_validated': None,

            'source_file_path': None  # Will be set by transform_data
        }
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform gamebook data to BigQuery rows."""
        rows = []
        
        # Extract game information
        game_info = self.extract_game_info(file_path, raw_data)
        
        # Process active players
        for player in raw_data.get('active_players', []):
            row = self.process_active_player(player, game_info)
            row['source_file_path'] = file_path
            rows.append(row)
        
        # Process DNP players
        for player in raw_data.get('dnp_players', []):
            row = self.process_inactive_player(player, game_info, 'dnp')
            row['source_file_path'] = file_path
            rows.append(row)
        
        # Process inactive players
        for player in raw_data.get('inactive_players', []):
            row = self.process_inactive_player(player, game_info, 'inactive')
            row['source_file_path'] = file_path
            rows.append(row)
        
        logger.info(f"Processed {len(rows)} players from {file_path}")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery using MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # For MERGE_UPDATE, we'll delete existing game data first
                game_id = rows[0]['game_id']
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE game_id = '{game_id}'
                """
                self.bq_client.query(delete_query).result()
                logger.info(f"Deleted existing data for game {game_id}")
            
            # Insert new rows
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
        except Exception as e:
            errors.append(str(e))
            logger.error(f"Failed to load data: {e}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }