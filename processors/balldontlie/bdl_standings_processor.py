#!/usr/bin/env python3
# processors/balldontlie/bdl_standings_processor.py
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class BdlStandingsProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_standings'
        self.processing_strategy = 'MERGE_UPDATE'
        
    def parse_record_string(self, record_str: str) -> Tuple[int, int]:
        """Parse '41-11' format into (wins, losses) tuple."""
        if not record_str or '-' not in record_str:
            return (0, 0)
        
        try:
            parts = record_str.split('-')
            wins = int(parts[0])
            losses = int(parts[1])
            return (wins, losses)
        except (ValueError, IndexError):
            logging.warning(f"Could not parse record string: {record_str}")
            return (0, 0)
    
    def calculate_season_display(self, season_year: int) -> str:
        """Convert 2024 to '2024-25'."""
        next_year = str(season_year + 1)[-2:]  # Get last 2 digits
        return f"{season_year}-{next_year}"
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate required fields in BDL standings data."""
        errors = []
        
        if 'season' not in data:
            errors.append("Missing season field")
        if 'standings' not in data:
            errors.append("Missing standings array")
        if 'timestamp' not in data:
            errors.append("Missing timestamp field")
            
        # Validate standings structure
        if 'standings' in data:
            for i, standing in enumerate(data['standings']):
                if 'team' not in standing:
                    errors.append(f"Standing {i}: Missing team object")
                elif 'abbreviation' not in standing['team']:
                    errors.append(f"Standing {i}: Missing team abbreviation")
                    
                required_fields = ['wins', 'losses', 'conference_rank', 'division_rank']
                for field in required_fields:
                    if field not in standing:
                        errors.append(f"Standing {i}: Missing {field}")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform BDL standings JSON into BigQuery rows."""
        rows = []
        
        # Extract metadata
        season_year = raw_data.get('season')
        scrape_timestamp = raw_data.get('timestamp')
        
        # Parse file path to get date_recorded
        # Path format: /ball-dont-lie/standings/{season_formatted}/{date}/{timestamp}.json
        path_parts = file_path.split('/')
        date_str = None
        for part in path_parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                date_str = part
                break
        
        if not date_str:
            logging.error(f"Could not extract date from file path: {file_path}")
            return rows
        
        try:
            date_recorded = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            logging.error(f"Invalid date format in path: {date_str}")
            return rows
        
        # Process each team's standing
        for standing in raw_data.get('standings', []):
            team_data = standing.get('team', {})
            
            # Parse record strings
            conf_wins, conf_losses = self.parse_record_string(standing.get('conference_record'))
            div_wins, div_losses = self.parse_record_string(standing.get('division_record'))
            home_wins, home_losses = self.parse_record_string(standing.get('home_record'))
            road_wins, road_losses = self.parse_record_string(standing.get('road_record'))
            
            # Calculate derived fields
            wins = standing.get('wins', 0)
            losses = standing.get('losses', 0)
            games_played = wins + losses
            win_percentage = round(wins / games_played, 3) if games_played > 0 else 0.0
            
            row = {
                # Core identifiers
                'season_year': season_year,
                'season_display': self.calculate_season_display(season_year),
                'date_recorded': date_recorded,
                'team_id': team_data.get('id'),
                'team_abbr': team_data.get('abbreviation'),
                'team_city': team_data.get('city'),
                'team_name': team_data.get('name'),
                'team_full_name': team_data.get('full_name'),
                
                # Conference/Division
                'conference': team_data.get('conference'),
                'division': team_data.get('division'),
                'conference_rank': standing.get('conference_rank'),
                'division_rank': standing.get('division_rank'),
                
                # Overall record
                'wins': wins,
                'losses': losses,
                'win_percentage': win_percentage,
                'games_played': games_played,
                
                # Conference record
                'conference_record': standing.get('conference_record'),
                'conference_wins': conf_wins,
                'conference_losses': conf_losses,
                
                # Division record
                'division_record': standing.get('division_record'),
                'division_wins': div_wins,
                'division_losses': div_losses,
                
                # Home/Road splits
                'home_record': standing.get('home_record'),
                'home_wins': home_wins,
                'home_losses': home_losses,
                'road_record': standing.get('road_record'),
                'road_wins': road_wins,
                'road_losses': road_losses,
                
                # Processing metadata
                'scrape_timestamp': datetime.fromisoformat(scrape_timestamp.replace('Z', '+00:00')) if scrape_timestamp else None,
                'source_file_path': file_path,
                'created_at': datetime.utcnow(),
                'processed_at': datetime.utcnow()
            }
            
            rows.append(row)
        
        logging.info(f"Transformed {len(rows)} team standings for {date_recorded}")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load standings data using MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # For MERGE_UPDATE: Delete existing data for this date
            date_recorded = rows[0]['date_recorded']
            season_year = rows[0]['season_year']
            
            delete_query = f"""
                DELETE FROM `{table_id}` 
                WHERE date_recorded = '{date_recorded}' 
                AND season_year = {season_year}
            """
            
            logging.info(f"Deleting existing data for {date_recorded}, season {season_year}")
            self.bq_client.query(delete_query).result()
            
            # Update created_at for existing records (set to current time for new records)
            for row in rows:
                row['processed_at'] = datetime.utcnow()
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                
        except Exception as e:
            error_msg = f"Error loading standings data: {str(e)}"
            logging.error(error_msg)
            errors.append(error_msg)
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }