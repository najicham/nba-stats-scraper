#!/usr/bin/env python3
# File: processors/espn/espn_team_roster_processor.py
# Description: Processor for ESPN team roster data transformation

import json, logging, re, os
from typing import Dict, List, Optional
from datetime import datetime, timezone, date
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class EspnTeamRosterProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.espn_team_rosters'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
    
    def normalize_player_name(self, name: str) -> str:
        """Normalize player name for consistent lookup."""
        if not name:
            return ""
        
        # Convert to lowercase and remove common suffixes
        normalized = name.lower().strip()
        suffixes = [' jr.', ' jr', ' sr.', ' sr', ' ii', ' iii', ' iv', ' v']
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        return normalized
    
    def normalize_team_name(self, team_name: str) -> str:
        """Normalize team name for consistent mapping."""
        if not team_name:
            return ""
        
        normalized = team_name.lower().strip()
        
        # Handle common ESPN variations
        normalized = normalized.replace("la lakers", "los angeles lakers")
        normalized = normalized.replace("la clippers", "los angeles clippers")
        normalized = normalized.replace("ny knicks", "new york knicks")
        
        # Remove all non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', normalized)
    
    def map_team_to_abbr(self, team_name: str) -> str:
        """Map ESPN team names to standard abbreviations."""
        normalized = self.normalize_team_name(team_name)
        
        team_mapping = {
            'atlantahawks': 'ATL',
            'bostonceltics': 'BOS', 
            'brooklynnets': 'BRK',
            'charlottehornets': 'CHA',
            'chicagobulls': 'CHI',
            'clevelandcavaliers': 'CLE',
            'dallasmavericks': 'DAL',
            'denvernuggets': 'DEN',
            'detroitpistons': 'DET',
            'goldenstatewarriors': 'GSW',
            'houstonrockets': 'HOU',
            'indianapacers': 'IND',
            'losangelesclippers': 'LAC',
            'losangeleslakers': 'LAL',
            'memphisgrizzlies': 'MEM',
            'miamiheat': 'MIA',
            'milwaukeebucks': 'MIL',
            'minnesotatimberwolves': 'MIN',
            'neworleanspelicans': 'NOP',
            'newyorkknicks': 'NYK',
            'oklahomacitythunder': 'OKC',
            'orlandomagic': 'ORL',
            'philadelphia76ers': 'PHI',
            'phoenixsuns': 'PHX',
            'portlandtrailblazers': 'POR',
            'sacramentokings': 'SAC',
            'sanantoniospurs': 'SAS',
            'torontoraptors': 'TOR',
            'utahjazz': 'UTA',
            'washingtonwizards': 'WAS'
        }
        
        return team_mapping.get(normalized, normalized.upper()[:3])
    
    def extract_date_from_path(self, file_path: str) -> date:
        """Extract date from GCS file path."""
        # Path format: espn/rosters/{date}/team_{team_abbr}/{timestamp}.json
        parts = file_path.split('/')
        for part in parts:
            if len(part) == 10 and part.count('-') == 2:  # YYYY-MM-DD format
                try:
                    return datetime.strptime(part, '%Y-%m-%d').date()
                except ValueError:
                    continue
        
        # Fallback to today's date
        return date.today()
    
    def extract_season_year(self, roster_date: date) -> int:
        """Calculate NBA season year from roster date."""
        # NBA season starts in October, so Oct-Dec = current year, Jan-Sep = previous year
        if roster_date.month >= 10:
            return roster_date.year
        else:
            return roster_date.year - 1
    
    def extract_scrape_hour(self, file_path: str) -> int:
        """Extract scrape hour from timestamp or default to 8 AM."""
        # For now, default to 8 (8 AM PT morning operations)
        # Future: could parse timestamp from filename if available
        return 8
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate ESPN roster data structure."""
        errors = []
        
        if not isinstance(data, dict):
            errors.append("Data is not a dictionary")
            return errors
        
        # Check for players array or similar structure
        if 'players' not in data and 'roster' not in data and 'team' not in data:
            errors.append("Missing expected roster data structure (players/roster/team)")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform ESPN roster data to BigQuery schema."""
        rows = []
        
        try:
            roster_date = self.extract_date_from_path(file_path)
            season_year = self.extract_season_year(roster_date)
            scrape_hour = self.extract_scrape_hour(file_path)
            
            # Handle actual ESPN JSON structure
            if 'players' not in raw_data:
                logging.error(f"Expected 'players' field not found in {file_path}")
                return rows
                
            players_data = raw_data['players']
            
            # Extract team information from the top-level data
            team_display_name = raw_data.get('teamName', '')
            team_abbr = raw_data.get('team_abbr', '')  # Already provided in ESPN structure
            espn_team_id = raw_data.get('espn_team_id')
            
            if not team_abbr and team_display_name:
                # Fallback: try to map team name to abbreviation
                team_abbr = self.map_team_to_abbr(team_display_name)
            
            for player_data in players_data:
                if not isinstance(player_data, dict):
                    continue
                
                # Extract player information from actual ESPN structure
                espn_player_id = player_data.get('playerId')
                if not espn_player_id:
                    continue  # Skip players without IDs
                
                full_name = player_data.get('fullName', '')
                if not full_name:
                    continue  # Skip players without names
                
                player_lookup = self.normalize_player_name(full_name)
                
                # Extract ESPN-specific fields
                jersey_number = player_data.get('jersey', '')
                position_name = player_data.get('position', '')
                
                # Convert height from inches to feet-inches format
                height_in = player_data.get('heightIn')
                height = None
                if height_in and isinstance(height_in, (int, float)):
                    feet = int(height_in // 12)
                    inches = int(height_in % 12)
                    height = f"{feet}' {inches}\""
                
                # Convert weight to string with "lbs" suffix
                weight_lb = player_data.get('weightLb')
                weight = None
                if weight_lb and isinstance(weight_lb, (int, float)):
                    weight = f"{int(weight_lb)} lbs"
                
                # Handle injuries - determine status from injuries array
                injuries = player_data.get('injuries', [])
                status = 'Active'
                if injuries:
                    # If there are injuries, check the most recent one
                    if len(injuries) > 0:
                        recent_injury = injuries[0]  # Assume first is most recent
                        injury_status = recent_injury.get('status', '')
                        if injury_status:
                            status = injury_status
                
                row = {
                    'roster_date': roster_date.isoformat(),
                    'scrape_hour': scrape_hour,
                    'season_year': season_year,
                    'team_abbr': team_abbr,
                    'team_display_name': team_display_name,
                    'espn_player_id': int(espn_player_id),
                    'player_full_name': full_name,
                    'player_lookup': player_lookup,
                    'jersey_number': str(jersey_number) if jersey_number else None,
                    'position': position_name if position_name else None,
                    'position_abbr': position_name if position_name else None,  # ESPN doesn't separate these
                    'height': height,
                    'weight': weight,
                    'age': None,  # Not provided in this ESPN structure
                    'experience_years': None,  # Not provided in this ESPN structure
                    'college': None,  # Not provided in this ESPN structure
                    'birth_place': None,  # Not provided in this ESPN structure
                    'birth_date': None,  # Not provided in this ESPN structure
                    'status': status,
                    'roster_status': 'Active Roster',  # Default since not specified
                    'salary': None,  # Not provided in this ESPN structure
                    'espn_roster_url': None,  # Could be extracted from metadata if available
                    'source_file_path': file_path,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                rows.append(row)
                
            logging.info(f"Transformed {len(rows)} players from {team_abbr} roster")
        
        except Exception as e:
            logging.error(f"Error transforming ESPN roster data from {file_path}: {str(e)}")
            raise
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load ESPN roster data to BigQuery with MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this roster_date + scrape_hour + team_abbr
                roster_date = rows[0]['roster_date']
                scrape_hour = rows[0]['scrape_hour']
                team_abbr = rows[0]['team_abbr']
                
                delete_query = f"""
                DELETE FROM `{table_id}` 
                WHERE roster_date = '{roster_date}' 
                  AND scrape_hour = {scrape_hour}
                  AND team_abbr = '{team_abbr}'
                """
                self.bq_client.query(delete_query).result()
                
                logging.info(f"Deleted existing records for {roster_date} hour {scrape_hour} team {team_abbr}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
            else:
                logging.info(f"Successfully loaded {len(rows)} ESPN roster records for {team_abbr}")
                
        except Exception as e:
            errors.append(f"BigQuery load error: {str(e)}")
            logging.error(f"Failed to load ESPN roster data: {str(e)}")
        
        return {
            'rows_processed': len(rows) if not errors else 0, 
            'errors': errors,
            'team_abbr': rows[0].get('team_abbr') if rows else None,
            'roster_date': rows[0].get('roster_date') if rows else None
        }