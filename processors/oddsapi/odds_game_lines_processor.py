#!/usr/bin/env python3
# File: processors/odds_api/odds_game_lines_processor.py
# Description: Processor for Odds API game lines history data transformation

import json, logging, re, os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class OddsGameLinesProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.odds_api_game_lines'
        self.processing_strategy = 'MERGE_UPDATE'  # Replace snapshots for same game/timestamp
        
        # CRITICAL: Initialize BigQuery client and project_id
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
    
    def normalize_team_name(self, team_name: str) -> str:
        """Aggressive normalization for team name consistency."""
        if not team_name:
            return ""
        
        normalized = team_name.lower().strip()
        
        # Handle common aliases first
        normalized = normalized.replace("la clippers", "los angeles clippers")
        normalized = normalized.replace("la lakers", "los angeles lakers")
        
        # Remove all non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', normalized)
    
    def get_team_abbreviation(self, team_name: str) -> str:
        """Convert team name to standard 3-letter abbreviation."""
        # Team name to abbreviation mapping
        team_mapping = {
            'atlantahawks': 'ATL',
            'bostonceltics': 'BOS',
            'brooklynnets': 'BKN',
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
        
        normalized = self.normalize_team_name(team_name)
        return team_mapping.get(normalized, team_name[:3].upper())
    
    def parse_timestamp(self, timestamp_str: str) -> Optional[str]:
        """Parse ISO timestamp string to proper format."""
        if not timestamp_str:
            return None
        try:
            # Parse ISO format and convert to isoformat for BigQuery
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return dt.isoformat()
        except:
            return None
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate required fields in the odds data."""
        errors = []
        
        if 'timestamp' not in data:
            errors.append("Missing timestamp")
        
        if 'data' not in data:
            errors.append("Missing data section")
            return errors
        
        game_data = data['data']
        required_fields = ['id', 'commence_time', 'home_team', 'away_team', 'bookmakers']
        
        for field in required_fields:
            if field not in game_data:
                errors.append(f"Missing required field in game data: {field}")
        
        if 'bookmakers' in game_data and not isinstance(game_data['bookmakers'], list):
            errors.append("Bookmakers must be an array")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform nested odds data into flat rows for BigQuery."""
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        
        # Parse timestamps
        snapshot_timestamp = self.parse_timestamp(raw_data.get('timestamp'))
        previous_timestamp = self.parse_timestamp(raw_data.get('previous_timestamp'))
        next_timestamp = self.parse_timestamp(raw_data.get('next_timestamp'))
        
        game_data = raw_data['data']
        
        # Game-level data
        game_id = game_data['id']
        sport_key = game_data['sport_key']
        sport_title = game_data['sport_title']
        commence_time = self.parse_timestamp(game_data['commence_time'])
        home_team = game_data['home_team']
        away_team = game_data['away_team']
        
        # Extract game date from commence_time
        game_date = None
        if commence_time:
            try:
                dt = datetime.fromisoformat(commence_time)
                game_date = dt.date().isoformat()
            except:
                pass
        
        # Get team abbreviations
        home_team_abbr = self.get_team_abbreviation(home_team)
        away_team_abbr = self.get_team_abbreviation(away_team)
        
        # Process each bookmaker
        for bookmaker in game_data.get('bookmakers', []):
            bookmaker_key = bookmaker.get('key', '')
            bookmaker_title = bookmaker.get('title', '')
            bookmaker_last_update = self.parse_timestamp(bookmaker.get('last_update'))
            
            # Process each market (spreads, totals, etc.)
            for market in bookmaker.get('markets', []):
                market_key = market.get('key', '')
                market_last_update = self.parse_timestamp(market.get('last_update'))
                
                # Process each outcome
                for outcome in market.get('outcomes', []):
                    row = {
                        # Snapshot metadata
                        'snapshot_timestamp': snapshot_timestamp,
                        'previous_snapshot_timestamp': previous_timestamp,
                        'next_snapshot_timestamp': next_timestamp,
                        
                        # Game identifiers
                        'game_id': game_id,
                        'sport_key': sport_key,
                        'sport_title': sport_title,
                        'commence_time': commence_time,
                        'game_date': game_date,
                        
                        # Teams
                        'home_team': home_team,
                        'away_team': away_team,
                        'home_team_abbr': home_team_abbr,
                        'away_team_abbr': away_team_abbr,
                        
                        # Bookmaker info
                        'bookmaker_key': bookmaker_key,
                        'bookmaker_title': bookmaker_title,
                        'bookmaker_last_update': bookmaker_last_update,
                        
                        # Market info
                        'market_key': market_key,
                        'market_last_update': market_last_update,
                        
                        # Outcome info
                        'outcome_name': outcome.get('name', ''),
                        'outcome_price': float(outcome.get('price', 0)),
                        'outcome_point': float(outcome.get('point', 0)) if outcome.get('point') is not None else None,
                        
                        # Processing metadata
                        'source_file_path': file_path,
                        'created_at': now,
                        'processed_at': now
                    }
                    rows.append(row)
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data into BigQuery with MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # Delete existing data for this game and snapshot timestamp
                game_id = rows[0]['game_id']
                snapshot_timestamp = rows[0]['snapshot_timestamp']
                game_date = rows[0]['game_date']
                
                delete_query = f"""
                DELETE FROM `{table_id}` 
                WHERE game_date = '{game_date}'
                AND game_id = '{game_id}' 
                AND snapshot_timestamp = '{snapshot_timestamp}'
                """
                self.bq_client.query(delete_query).result()
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
        except Exception as e:
            errors.append(str(e))
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}