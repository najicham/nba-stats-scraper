#!/usr/bin/env python3
import json, logging, re, os
from typing import Dict, List, Optional
from datetime import datetime
from google.cloud import bigquery
from processors.processor_base import ProcessorBase
from processors.utils.name_utils import normalize_name

class BdlActivePlayersProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_active_players_current'
        self.processing_strategy = 'MERGE_UPDATE'  # Current-state data
        
        # Initialize BigQuery client explicitly
        self.bq_client = bigquery.Client()
        # Set project ID from environment or BigQuery client
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Load NBA.com player data for validation
        self.nba_com_players = self._load_nba_com_players()
    
    def parse_json(self, json_content: str, file_path: str) -> Dict:
        """Parse Ball Don't Lie Active Players JSON."""
        try:
            data = json.loads(json_content)
            
            # Convert Ball Don't Lie format to expected format
            if 'activePlayers' in data:
                return {
                    'data': data['activePlayers'],  # Convert activePlayers -> data
                    'metadata': {
                        'ident': data.get('ident'),
                        'timestamp': data.get('timestamp'),
                        'playerCount': data.get('playerCount'),
                        'source_file': file_path
                    }
                }
            else:
                logging.error(f"No 'activePlayers' field found in {file_path}")
                return None
                
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error in {file_path}: {e}")
            return None
        except Exception as e:
            logging.error(f"Error parsing JSON from {file_path}: {e}")
            return None
    
    def _load_nba_com_players(self) -> Dict[str, Dict]:
        """Load current NBA.com player data for validation."""
        try:
            if not self.bq_client:
                logging.error("BigQuery client not initialized")
                return {}
                
            query = """
            SELECT player_lookup, player_full_name, team_abbr, player_id
            FROM `nba-props-platform.nba_raw.nbac_player_list_current`
            WHERE is_active = TRUE
            """
            results = self.bq_client.query(query).result()
            
            players = {}
            for row in results:
                players[row.player_lookup] = {
                    'full_name': row.player_full_name,
                    'team_abbr': row.team_abbr,
                    'player_id': row.player_id
                }
            logging.info(f"Loaded {len(players)} NBA.com players for validation")
            return players
        except Exception as e:
            logging.warning(f"Could not load NBA.com players for validation: {e}")
            return {}
    
    def normalize_text(self, text: str) -> str:
        """Aggressive normalization for data consistency."""
        if not text:
            return ""
        normalized = text.lower().strip()
        # Remove all non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', normalized)
    
    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        
        if 'data' not in data:
            errors.append("Missing 'data' field in JSON")
            return errors
            
        if not isinstance(data['data'], list):
            errors.append("'data' field is not a list")
            return errors
        
        for i, player in enumerate(data['data']):
            if 'id' not in player:
                errors.append(f"Player {i}: Missing 'id' field")
            if 'first_name' not in player:
                errors.append(f"Player {i}: Missing 'first_name' field")
            if 'last_name' not in player:
                errors.append(f"Player {i}: Missing 'last_name' field")
            if 'team' not in player or not isinstance(player['team'], dict):
                errors.append(f"Player {i}: Missing or invalid 'team' field")
            elif 'abbreviation' not in player['team']:
                errors.append(f"Player {i}: Missing team abbreviation")
        
        return errors
    
    def _validate_against_nba_com(self, player_lookup: str, bdl_team_abbr: str, player_full_name: str) -> Dict[str, str]:
        """Validate BDL data against NBA.com data."""
        validation_issues = []
        nba_com_data = self.nba_com_players.get(player_lookup)
        
        if not nba_com_data:
            return {
                'has_issues': True,
                'status': 'missing_nba_com',
                'details': json.dumps({
                    'issues': [{'type': 'missing_nba_com', 'message': 'Player not found in NBA.com data'}]
                }),
                'nba_com_team': None
            }
        
        # Check team mismatch
        nba_team = nba_com_data['team_abbr']
        if bdl_team_abbr != nba_team:
            validation_issues.append({
                'type': 'team_mismatch',
                'bdl_team': bdl_team_abbr,
                'nba_com_team': nba_team,
                'severity': 'medium'
            })
        
        if validation_issues:
            return {
                'has_issues': True,
                'status': 'team_mismatch' if any(issue['type'] == 'team_mismatch' for issue in validation_issues) else 'data_quality_issue',
                'details': json.dumps({'issues': validation_issues}),
                'nba_com_team': nba_team
            }
        else:
            return {
                'has_issues': False,
                'status': 'validated',
                'details': json.dumps({'issues': []}),
                'nba_com_team': nba_team
            }
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        rows = []
        
        for player_data in raw_data['data']:
            # Basic player info
            first_name = player_data.get('first_name', '').strip()
            last_name = player_data.get('last_name', '').strip()
            player_full_name = f"{first_name} {last_name}".strip()
            player_lookup = normalize_name(player_full_name)
            
            # Team info
            team_info = player_data.get('team', {})
            team_abbr = team_info.get('abbreviation', '')
            
            # Perform validation against NBA.com data
            validation_result = self._validate_against_nba_com(
                player_lookup, team_abbr, player_full_name
            )
            
            row = {
                # Primary identifiers
                'player_lookup': player_lookup,
                'bdl_player_id': player_data.get('id'),
                'first_name': first_name,
                'last_name': last_name,
                'player_full_name': player_full_name,
                
                # Team assignment
                'bdl_team_id': team_info.get('id'),
                'team_abbr': team_abbr,
                'team_city': team_info.get('city', ''),
                'team_name': team_info.get('name', ''),
                'team_full_name': team_info.get('full_name', ''),
                'team_conference': team_info.get('conference', ''),
                'team_division': team_info.get('division', ''),
                
                # Player attributes  
                'position': player_data.get('position', ''),
                'height': player_data.get('height', ''),
                'weight': player_data.get('weight', ''),
                'jersey_number': player_data.get('jersey_number', ''),
                
                # Career information
                'college': player_data.get('college', ''),
                'country': player_data.get('country', ''),
                'draft_year': player_data.get('draft_year'),
                'draft_round': player_data.get('draft_round'),
                'draft_number': player_data.get('draft_number'),
                
                # Validation tracking
                'has_validation_issues': validation_result['has_issues'],
                'validation_status': validation_result['status'],
                'validation_details': validation_result['details'],
                'nba_com_team_abbr': validation_result['nba_com_team'],
                'validation_last_check': datetime.utcnow().isoformat(),
                
                # Processing metadata
                'last_seen_date': datetime.utcnow().date().isoformat(),
                'source_file_path': file_path,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            rows.append(row)
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # For current-state data, clear existing data before inserting
                delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
                self.bq_client.query(delete_query).result()
                logging.info(f"Cleared existing data from {table_id}")
            
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
            else:
                logging.info(f"Successfully inserted {len(rows)} rows into {table_id}")
        except Exception as e:
            errors.append(str(e))
            logging.error(f"Error loading data: {e}")
        
        # Log validation summary
        total_issues = sum(1 for row in rows if row['has_validation_issues'])
        logging.info(f"Validation summary: {total_issues}/{len(rows)} players have validation issues")
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}