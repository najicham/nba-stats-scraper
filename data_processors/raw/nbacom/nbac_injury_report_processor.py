#!/usr/bin/env python3
"""
File: processors/nbacom/nbac_injury_report_processor.py

Process NBA.com Injury Report data for player availability tracking.
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase

logger = logging.getLogger(__name__)

class NbacInjuryReportProcessor(ProcessorBase):
    """Process NBA.com Injury Report data."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_injury_report'
        self.processing_strategy = 'APPEND_ALWAYS'  # Keep all reports for history
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON data structure."""
        errors = []
        
        if 'metadata' not in data:
            errors.append("Missing 'metadata' section")
            
        if 'records' not in data:
            errors.append("Missing 'records' section")
            return errors
            
        if not isinstance(data['records'], list):
            errors.append("'records' should be a list")
            
        # Check first record structure if exists
        if data['records']:
            required_fields = ['date', 'gametime', 'matchup', 'team', 'player', 'status']
            first_record = data['records'][0]
            for field in required_fields:
                if field not in first_record:
                    errors.append(f"Missing required field in record: {field}")
                    
        return errors
    
    def _normalize_player_name(self, player_name: str) -> tuple[str, str]:
        """
        Parse "Last, First" format and create normalized lookup.
        Returns (full_name, player_lookup)
        """
        if not player_name:
            return ("", "")
            
        # Parse "Hayes, Killian" format
        parts = player_name.split(',')
        if len(parts) == 2:
            last_name = parts[0].strip()
            first_name = parts[1].strip()
            full_name = f"{first_name} {last_name}"
        else:
            # Handle cases without comma
            full_name = player_name.strip()
            
        # Create normalized lookup
        player_lookup = full_name.lower()
        for char in [' ', "'", '.', '-', ',', 'jr', 'sr', 'ii', 'iii', 'iv']:
            player_lookup = player_lookup.replace(char, '')
            
        return (full_name, player_lookup)
    
    def _parse_matchup(self, matchup: str, game_date: str) -> Dict:
        """
        Parse matchup string like "MIA@DET" to extract teams and create game_id.
        Returns dict with away_team, home_team, and game_id
        """
        parts = matchup.split('@')
        if len(parts) != 2:
            return {'away_team': '', 'home_team': '', 'game_id': ''}
            
        away_team = parts[0].strip()
        home_team = parts[1].strip()
        
        # Parse date to create game_id
        try:
            date_obj = datetime.strptime(game_date, '%m/%d/%Y')
            date_str = date_obj.strftime('%Y%m%d')
            game_id = f"{date_str}_{away_team}_{home_team}"
        except:
            game_id = f"{game_date}_{away_team}_{home_team}"
            
        return {
            'away_team': away_team,
            'home_team': home_team,
            'game_id': game_id
        }
    
    def _parse_game_time(self, gametime: str) -> Optional[str]:
        """Parse gametime like '07:00 (ET)' to standard format."""
        if not gametime:
            return None
        # Remove timezone indicator
        time_str = gametime.replace('(ET)', '').replace('(EST)', '').strip()
        return time_str
    
    def _categorize_reason(self, reason: str) -> str:
        """Categorize the reason for absence."""
        if not reason:
            return 'unknown'
            
        reason_lower = reason.lower()
        
        if 'injury/illness' in reason_lower:
            return 'injury'
        elif 'g league' in reason_lower:
            return 'g_league'
        elif 'suspension' in reason_lower:
            return 'suspension'
        elif 'health and safety' in reason_lower or 'protocol' in reason_lower:
            return 'health_safety_protocol'
        elif 'rest' in reason_lower:
            return 'rest'
        elif 'personal' in reason_lower:
            return 'personal'
        else:
            return 'other'
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform injury report data to BigQuery rows."""
        rows = []
        
        # Extract metadata
        metadata = raw_data.get('metadata', {})
        report_date = metadata.get('gamedate', '')
        report_hour = metadata.get('hour24', metadata.get('hour', ''))
        season = self._get_nba_season(report_date_obj)
        scrape_time = metadata.get('scrape_time', '')
        run_id = metadata.get('run_id', '')
        
        # Parse report date
        try:
            report_date_obj = datetime.strptime(report_date, '%Y%m%d').date()
        except:
            report_date_obj = date.today()
            
        # Get parsing stats
        parsing_stats = raw_data.get('parsing_stats', {})
        overall_confidence = parsing_stats.get('overall_confidence', 1.0)
        
        # Process each injury record
        for record in raw_data.get('records', []):
            try:
                # Parse player name
                player_full_name, player_lookup = self._normalize_player_name(record['player'])
                
                # Parse matchup
                matchup_info = self._parse_matchup(record['matchup'], record['date'])
                
                # Parse game time
                game_time = self._parse_game_time(record.get('gametime', ''))
                
                # Categorize reason
                reason_category = self._categorize_reason(record.get('reason', ''))
                
                row = {
                    'report_date': report_date_obj.isoformat(),
                    'report_hour': int(report_hour) if report_hour else None,
                    'season': season,
                    'game_date': datetime.strptime(record['date'], '%m/%d/%Y').date().isoformat(),
                    'game_time': game_time,
                    'game_id': matchup_info['game_id'],
                    'matchup': record['matchup'],
                    'away_team': matchup_info['away_team'],
                    'home_team': matchup_info['home_team'],
                    'team': record['team'],
                    'player_name_original': record['player'],
                    'player_full_name': player_full_name,
                    'player_lookup': player_lookup,
                    'injury_status': record['status'].lower(),
                    'reason': record.get('reason', ''),
                    'reason_category': reason_category,
                    'confidence_score': record.get('confidence', 1.0),
                    'overall_report_confidence': overall_confidence,
                    'scrape_time': scrape_time,
                    'run_id': run_id,
                    'source_file_path': file_path,
                    'processed_at': datetime.utcnow().isoformat()
                }
                
                rows.append(row)
                
            except Exception as e:
                logger.error(f"Error processing injury record: {e}")
                continue
        
        logger.info(f"Transformed {len(rows)} injury records")
        return rows
    
    def _get_nba_season(self, report_date_obj: date) -> str:
        """Determine NBA season from date. Season runs Oct-June."""
        year = report_date_obj.year
        month = report_date_obj.month
        
        # October-December is start of season
        if month >= 10:
            return f"{year}-{str(year+1)[2:]}"  # e.g., "2021-22"
        # January-September is end of season
        else:
            return f"{year-1}-{str(year)[2:]}"  # e.g., "2021-22"
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery using APPEND_ALWAYS strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        errors = []
        
        try:
            from google.cloud import bigquery
            client = bigquery.Client()
            table = client.get_table('nba_raw.nbac_injury_report')
            
            # APPEND_ALWAYS - just insert all rows
            errors_result = client.insert_rows_json(table, rows)
            if errors_result:
                errors.extend([str(e) for e in errors_result])
                logger.error(f"Insert errors: {errors_result}")
            else:
                logger.info(f"Successfully appended {len(rows)} injury records")
                
        except Exception as e:
            errors.append(str(e))
            logger.error(f"Error loading data: {e}")
        
        return {'rows_processed': len(rows), 'errors': errors}