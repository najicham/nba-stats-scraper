#!/usr/bin/env python3
"""
processors/balldontlie/bdl_injuries_processor.py

Ball Don't Lie Injuries Processor

Transforms Ball Don't Lie injuries data from GCS JSON files to BigQuery.
Provides backup/validation source for NBA.com injury reports.
"""

import json
import logging
import re
import os
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

logger = logging.getLogger(__name__)

class BdlInjuriesProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.bq_client = bigquery.Client()
        self.table_name = 'nba_raw.bdl_injuries'
        self.processing_strategy = 'APPEND_ALWAYS'  # Track intraday changes
        
        # Team ID mapping (Ball Don't Lie team_id -> standard abbreviation)
        self.team_mapping = {
            1: 'ATL',   # Atlanta Hawks
            2: 'BOS',   # Boston Celtics  
            3: 'BKN',   # Brooklyn Nets
            4: 'CHA',   # Charlotte Hornets
            5: 'CHI',   # Chicago Bulls
            6: 'CLE',   # Cleveland Cavaliers
            7: 'DAL',   # Dallas Mavericks
            8: 'DEN',   # Denver Nuggets
            9: 'DET',   # Detroit Pistons
            10: 'GSW',  # Golden State Warriors
            11: 'HOU',  # Houston Rockets
            12: 'IND',  # Indiana Pacers
            13: 'LAC',  # LA Clippers
            14: 'LAL',  # Los Angeles Lakers
            15: 'MEM',  # Memphis Grizzlies
            16: 'MIA',  # Miami Heat
            17: 'MIL',  # Milwaukee Bucks
            18: 'MIN',  # Minnesota Timberwolves
            19: 'NOP',  # New Orleans Pelicans
            20: 'NYK',  # New York Knicks
            21: 'OKC',  # Oklahoma City Thunder
            22: 'ORL',  # Orlando Magic
            23: 'PHI',  # Philadelphia 76ers
            24: 'PHX',  # Phoenix Suns
            25: 'POR',  # Portland Trail Blazers
            26: 'SAC',  # Sacramento Kings
            27: 'SAS',  # San Antonio Spurs
            28: 'TOR',  # Toronto Raptors
            29: 'UTA',  # Utah Jazz
            30: 'WAS',  # Washington Wizards
        }
    
    def normalize_text(self, text: str) -> str:
        """Aggressive normalization for player name consistency."""
        if not text:
            return ""
        
        normalized = text.lower().strip()
        
        # Handle name variations before aggressive normalization
        normalized = normalized.replace(".", "")
        normalized = normalized.replace("'", "")
        normalized = normalized.replace("-", "")
        
        # Remove all non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', normalized)
    
    def categorize_injury_reason(self, description: str, status: str) -> str:
        """Categorize injury reason from description."""
        if not description:
            return "other"
        
        desc_lower = description.lower()
        status_lower = status.lower() if status else ""
        
        # G-League related
        if any(term in desc_lower for term in ["g league", "two-way", "on assignment"]):
            return "g_league"
        
        # Rest/Load Management
        if any(term in desc_lower for term in ["rest", "load management", "maintenance"]):
            return "rest"
        
        # Personal reasons
        if any(term in desc_lower for term in ["personal", "family", "bereavement", "away from team"]):
            return "personal"
        
        # Suspension
        if any(term in desc_lower for term in ["suspension", "disciplinary", "team violation"]):
            return "suspension"
        
        # Injury (broad patterns)
        injury_terms = [
            "injury", "illness", "hip", "ankle", "knee", "shoulder", "back", "hamstring",
            "quad", "calf", "groin", "wrist", "elbow", "foot", "toe", "finger", "head",
            "concussion", "sprain", "strain", "tear", "surgery", "fracture", "bruise"
        ]
        
        if any(term in desc_lower for term in injury_terms):
            return "injury"
        
        return "other"
    
    def parse_return_date(self, return_date_str: str, scrape_date: date) -> tuple[Optional[date], bool, float]:
        """Parse return date with NBA season context."""
        if not return_date_str:
            return None, False, 0.5
        
        original = return_date_str.strip()
        
        # Handle special cases
        special_cases = ["tbd", "unknown", "end of season", "indefinite", "out for season"]
        if original.lower() in special_cases:
            return None, False, 0.8  # High confidence that it's intentionally unparseable
        
        try:
            # Current NBA season context
            # 2024-25 season: Oct 2024 - Jun 2025
            season_start_year = scrape_date.year if scrape_date.month >= 10 else scrape_date.year - 1
            
            # Parse common formats: "Jul 17", "Jan 15", "Dec 25"
            month_patterns = {
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
            }
            
            # Try "MMM DD" format
            import re
            match = re.match(r'(\w{3})\s+(\d{1,2})', original.lower())
            if match:
                month_str, day_str = match.groups()
                if month_str in month_patterns:
                    month = month_patterns[month_str]
                    day = int(day_str)
                    
                    # Determine year based on NBA season
                    if month >= 10:  # Oct-Dec: current season start year
                        year = season_start_year
                    else:  # Jan-Sep: next year
                        year = season_start_year + 1
                    
                    parsed_date = date(year, month, day)
                    return parsed_date, True, 1.0
            
            # If no pattern matches
            return None, False, 0.3
            
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse return date '{return_date_str}': {e}")
            return None, False, 0.2
    
    def normalize_status(self, status: str) -> str:
        """Normalize injury status to standard values."""
        if not status:
            return "unknown"
        
        status_lower = status.lower().strip()
        
        # Standard mappings
        if status_lower in ["out"]:
            return "out"
        elif status_lower in ["questionable"]:
            return "questionable"  
        elif status_lower in ["doubtful"]:
            return "doubtful"
        elif status_lower in ["probable"]:
            return "probable"
        elif status_lower in ["day-to-day", "day to day"]:
            return "day_to_day"
        else:
            return status_lower.replace(" ", "_").replace("-", "_")
    
    def calculate_confidence(self, player_data: Dict, return_date_parsed: bool, 
                           return_date_confidence: float, team_mapped: bool) -> tuple[float, List[str]]:
        """Calculate parsing confidence and identify issues."""
        confidence_factors = []
        issues = []
        
        # Required fields present
        if not player_data.get('player', {}).get('id'):
            confidence_factors.append(0.0)
            issues.append("missing_player_id")
        else:
            confidence_factors.append(1.0)
        
        if not player_data.get('status'):
            confidence_factors.append(0.3)
            issues.append("missing_status")
        else:
            confidence_factors.append(1.0)
        
        # Return date parsing
        confidence_factors.append(return_date_confidence)
        if not return_date_parsed and player_data.get('return_date'):
            issues.append("unparseable_return_date")
        
        # Team mapping
        if not team_mapped:
            confidence_factors.append(0.5)
            issues.append("unknown_team_mapping")
        else:
            confidence_factors.append(1.0)
        
        # Description quality
        description = player_data.get('description', '')
        if len(description) < 20:
            confidence_factors.append(0.7)
            issues.append("short_description")
        else:
            confidence_factors.append(1.0)
        
        # Calculate overall confidence
        overall_confidence = sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.0
        
        return overall_confidence, issues

    def validate_data(self, data: Dict) -> List[str]:
        """Validate Ball Don't Lie injuries JSON structure."""
        errors = []
        
        if 'injuries' not in data:
            errors.append("Missing 'injuries' array")
        if not isinstance(data['injuries'], list):
            errors.append("'injuries' field is not an array")
        
        return errors

    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform Ball Don't Lie injuries data to BigQuery rows."""
        if self.validate_data(raw_data):
            logger.error(f"Invalid data structure in {file_path}")
            return []
        
        rows = []
        
        # Extract scrape timestamp from file path
        # Expected: gs://nba-scraped-data/ball-dont-lie/injuries/2024-01-15/20240115_143022.json
        scrape_timestamp = self._extract_timestamp_from_path(file_path)
        scrape_date = scrape_timestamp.date() if scrape_timestamp else date.today()
        
        # Current NBA season
        season_year = scrape_date.year if scrape_date.month >= 10 else scrape_date.year - 1
        
        for injury_record in raw_data['injuries']:
            player = injury_record.get('player', {})
            
            # Extract player info
            bdl_player_id = player.get('id')
            if not bdl_player_id:
                continue
            
            first_name = player.get('first_name', '').strip()
            last_name = player.get('last_name', '').strip()
            player_full_name = f"{first_name} {last_name}".strip()
            player_lookup = self.normalize_text(player_full_name)
            
            # Team mapping
            bdl_team_id = player.get('team_id')
            team_abbr = self.team_mapping.get(bdl_team_id, 'UNK')
            team_mapped = bdl_team_id in self.team_mapping
            
            # Injury details
            status = injury_record.get('status', '')
            status_normalized = self.normalize_status(status)
            description = injury_record.get('description', '')
            reason_category = self.categorize_injury_reason(description, status)
            
            # Return date parsing
            return_date_str = injury_record.get('return_date', '')
            return_date, return_date_parsed, return_date_confidence = self.parse_return_date(
                return_date_str, scrape_date
            )
            
            # Calculate confidence and issues
            confidence, issues = self.calculate_confidence(
                injury_record, return_date_parsed, return_date_confidence, team_mapped
            )
            
            row = {
                # Core identifiers
                'scrape_date': scrape_date.isoformat(),
                'season_year': season_year,
                
                # Player identification
                'bdl_player_id': bdl_player_id,
                'player_full_name': player_full_name,
                'player_lookup': player_lookup,
                
                # Team assignment
                'bdl_team_id': bdl_team_id,
                'team_abbr': team_abbr,
                
                # Injury details
                'injury_status': status,
                'injury_status_normalized': status_normalized,
                'return_date': return_date.isoformat() if return_date else None,
                'return_date_original': return_date_str,
                'injury_description': description,
                'reason_category': reason_category,
                
                # Data quality tracking
                'parsing_confidence': round(confidence, 3),
                'data_quality_flags': ','.join(issues) if issues else None,
                'return_date_parsed': return_date_parsed,
                
                # Processing metadata
                'scrape_timestamp': scrape_timestamp.isoformat() if scrape_timestamp else None,
                'source_file_path': file_path,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            rows.append(row)
            
        logger.info(f"Transformed {len(rows)} injury records from {file_path}")
        return rows

    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery using APPEND_ALWAYS strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{os.environ['GCP_PROJECT_ID']}.{self.table_name}"
        errors = []
        
        try:
            # APPEND_ALWAYS: No deletion, just insert
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logger.error(f"BigQuery insert errors: {result}")
            else:
                logger.info(f"Successfully inserted {len(rows)} rows to {table_id}")
                
        except Exception as e:
            error_msg = f"Failed to insert data: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }
    
    def _extract_timestamp_from_path(self, file_path: str) -> Optional[datetime]:
        """Extract timestamp from GCS file path."""
        # Expected: gs://nba-scraped-data/ball-dont-lie/injuries/2024-01-15/20240115_143022.json
        try:
            import re
            pattern = r'(\d{8})_(\d{6})\.json'
            match = re.search(pattern, file_path)
            if match:
                date_str, time_str = match.groups()
                timestamp_str = f"{date_str} {time_str}"
                return datetime.strptime(timestamp_str, '%Y%m%d %H%M%S')
        except Exception as e:
            logger.warning(f"Could not extract timestamp from {file_path}: {e}")
        
        return None