#!/usr/bin/env python3
"""
File: processors/nba_com/nbac_player_list_processor.py

Process NBA.com Player List data for current player-team assignments.
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase

logger = logging.getLogger(__name__)

class NbacPlayerListProcessor(ProcessorBase):
    """Process NBA.com Player List for current roster assignments."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_player_list_current'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON data structure."""
        errors = []
        
        if 'resultSets' not in data:
            errors.append("Missing 'resultSets' in data")
            return errors
            
        # NBA.com uses array format, need to find PlayerIndex result set
        player_result = None
        for result_set in data.get('resultSets', []):
            if result_set.get('name') == 'PlayerIndex':
                player_result = result_set
                break
                
        if not player_result:
            errors.append("No 'PlayerIndex' result set found")
            return errors
            
        if 'headers' not in player_result or 'rowSet' not in player_result:
            errors.append("Missing headers or rowSet in player data")
            
        return errors
    
    def _normalize_player_name(self, full_name: str) -> str:
        """Create normalized player lookup key."""
        if not full_name:
            return ""
        # Remove spaces, apostrophes, periods, hyphens
        # Convert to lowercase
        normalized = full_name.lower()
        for char in [' ', "'", '.', '-', ',', 'jr', 'sr', 'ii', 'iii', 'iv']:
            normalized = normalized.replace(char, '')
        return normalized
    
    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string from NBA.com format."""
        if not date_str or date_str == 'null':
            return None
        try:
            # NBA.com format: "1984-12-30T00:00:00"
            return datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        except:
            return None
    
    def _calculate_age(self, birth_date: date) -> Optional[float]:
        """Calculate age in years."""
        if not birth_date:
            return None
        today = date.today()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        return float(age)
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform NBA.com player list to BigQuery rows."""
        rows = []
        
        # Find PlayerIndex result set
        player_result = None
        for result_set in raw_data.get('resultSets', []):
            if result_set.get('name') == 'PlayerIndex':
                player_result = result_set
                break
        
        if not player_result:
            logger.error("No PlayerIndex result set found")
            return rows
            
        headers = player_result['headers']
        
        # Map headers to indices
        header_map = {h: i for i, h in enumerate(headers)}
        
        # Get current season year (2024 for 2024-25 season)
        current_date = datetime.now()
        season_year = current_date.year if current_date.month >= 10 else current_date.year - 1
        
        # Track duplicates for alerting
        seen_lookups = {}
        
        for player_row in player_result['rowSet']:
            try:
                # Extract fields using header mapping
                player_id = player_row[header_map.get('PERSON_ID', 0)]
                full_name = f"{player_row[header_map.get('PLAYER_FIRST_NAME', 2)]} {player_row[header_map.get('PLAYER_LAST_NAME', 1)]}"
                team_id = player_row[header_map.get('TEAM_ID', 4)]
                team_abbr = player_row[header_map.get('TEAM_ABBREVIATION', 9)] or ""

                # Generate player_lookup
                player_lookup = self._normalize_player_name(full_name)

                # Check for duplicates
                if player_lookup in seen_lookups:
                    logger.warning(f"Duplicate player_lookup '{player_lookup}': {full_name} ({team_abbr}) vs {seen_lookups[player_lookup]}")
                seen_lookups[player_lookup] = f"{full_name} ({team_abbr})"

                # Determine roster status
                roster_status_code = player_row[header_map.get('ROSTER_STATUS', 19)]
                is_active = roster_status_code == 1
                roster_status = 'active' if is_active else 'inactive'

                row = {
                    'player_lookup': player_lookup,
                    'player_id': player_id,
                    'player_full_name': full_name,
                    'team_id': team_id,
                    'team_abbr': team_abbr,
                    'jersey_number': player_row[header_map.get('JERSEY_NUMBER', 10)],
                    'position': player_row[header_map.get('POSITION', 11)],
                    'height': player_row[header_map.get('HEIGHT', 12)],
                    'weight': player_row[header_map.get('WEIGHT', 13)],
                    'birth_date': None,  # Not in this data
                    'age': None,  # Not in this data
                    'draft_year': player_row[header_map.get('DRAFT_YEAR', 16)],
                    'draft_round': player_row[header_map.get('DRAFT_ROUND', 17)],
                    'draft_pick': player_row[header_map.get('DRAFT_NUMBER', 18)],
                    'years_pro': None,  # Calculate from FROM_YEAR/TO_YEAR if needed
                    'college': player_row[header_map.get('COLLEGE', 14)],
                    'country': player_row[header_map.get('COUNTRY', 15)],
                    'is_active': is_active,
                    'roster_status': roster_status,
                    'season_year': season_year,
                    'last_seen_date': date.today().isoformat(),
                    'source_file_path': file_path,
                    'processed_at': datetime.utcnow().isoformat()
                }
                
                rows.append(row)
                
            except Exception as e:
                logger.error(f"Error processing player row: {e}")
                continue
        
        logger.info(f"Transformed {len(rows)} players from NBA.com player list")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
      """Load data to BigQuery using MERGE UPDATE strategy."""
      if not rows:
          return {'rows_processed': 0, 'errors': []}
      
      errors = []
      
      try:
          # Simple insert for now - we can implement MERGE later
          from google.cloud import bigquery
          client = bigquery.Client()
          table = client.get_table('nba_raw.nbac_player_list_current')
          
          errors_result = client.insert_rows_json(table, rows)
          if errors_result:
              errors.extend([str(e) for e in errors_result])
              logger.error(f"Insert errors: {errors_result}")
          else:
              logger.info(f"Successfully inserted {len(rows)} rows")
              
      except Exception as e:
          errors.append(str(e))
          logger.error(f"Error loading data: {e}")
      
      return {'rows_processed': len(rows), 'errors': errors}
    