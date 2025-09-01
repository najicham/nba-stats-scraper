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
            
            # Handle different ESPN JSON structures
            players_data = []
            team_info = {}
            
            if 'team' in raw_data:
                team_info = raw_data.get('team', {})
                players_data = team_info.get('roster', {}).get('athletes', [])
            elif 'roster' in raw_data:
                players_data = raw_data['roster']
                team_info = raw_data.get('team', {})
            elif 'players' in raw_data:
                players_data = raw_data['players']
                team_info = raw_data.get('team', {})
            else:
                # Assume the whole data is the roster
                players_data = raw_data if isinstance(raw_data, list) else [raw_data]
            
            # Extract team information
            team_display_name = team_info.get('displayName', team_info.get('name', ''))
            team_abbr = self.map_team_to_abbr(team_display_name)
            
            for player_data in players_data:
                if not isinstance(player_data, dict):
                    continue
                
                # Handle nested athlete structure common in ESPN
                athlete = player_data.get('athlete', player_data)
                
                # Extract player information
                espn_player_id = athlete.get('id')
                if not espn_player_id:
                    continue  # Skip players without IDs
                
                full_name = athlete.get('displayName', athlete.get('name', ''))
                if not full_name:
                    continue  # Skip players without names
                
                player_lookup = self.normalize_player_name(full_name)
                
                # Extract additional player details
                jersey_number = athlete.get('jersey', athlete.get('number', ''))
                position = athlete.get('position', {})
                if isinstance(position, dict):
                    position_name = position.get('name', '')
                    position_abbr = position.get('abbreviation', position.get('abbrev', ''))
                else:
                    position_name = str(position) if position else ''
                    position_abbr = position_name
                
                height = athlete.get('height', '')
                weight = athlete.get('weight', '')
                age = athlete.get('age')
                
                # Experience and background
                experience_years = athlete.get('experience', {}).get('years') if athlete.get('experience') else None
                college = athlete.get('college', athlete.get('school', ''))
                birth_place = athlete.get('birthPlace', athlete.get('hometown', ''))
                birth_date_str = athlete.get('birthDate', athlete.get('dateOfBirth', ''))
                
                birth_date = None
                if birth_date_str:
                    try:
                        # Handle various date formats
                        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%SZ', '%m/%d/%Y']:
                            try:
                                birth_date = datetime.strptime(birth_date_str, fmt).date()
                                break
                            except ValueError:
                                continue
                    except:
                        pass
                
                # Status information
                status = athlete.get('status', athlete.get('active', 'Active'))
                roster_status = athlete.get('rosterStatus', 'Active Roster')
                salary = athlete.get('salary', '')
                
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
                    'position': position_name,
                    'position_abbr': position_abbr,
                    'height': height if height else None,
                    'weight': weight if weight else None,
                    'age': age if isinstance(age, int) else None,
                    'experience_years': experience_years if isinstance(experience_years, int) else None,
                    'college': college if college else None,
                    'birth_place': birth_place if birth_place else None,
                    'birth_date': birth_date.isoformat() if birth_date else None,
                    'status': status if status else None,
                    'roster_status': roster_status if roster_status else None,
                    'salary': salary if salary else None,
                    'espn_roster_url': None,  # Could be extracted from metadata if available
                    'source_file_path': file_path,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                rows.append(row)
        
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