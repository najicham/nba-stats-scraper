#!/usr/bin/env python3
# File: processors/bettingpros/bettingpros_player_props_processor.py
# Description: Processor for BettingPros player props data transformation

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from processors.processor_base import ProcessorBase

class BettingPropsProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bettingpros_player_points_props'
        self.processing_strategy = 'APPEND_ALWAYS'  # Track all historical snapshots
        
        # Bookmaker name normalization
        self.bookmaker_mapping = {
            'bettingpros consensus': 'BettingPros Consensus',
            'betmgm': 'BetMGM',
            'betrivers': 'BetRivers', 
            'sugarhouse': 'SugarHouse',
            'partycasino': 'PartyCasino',
            'draftkings': 'DraftKings',
            'fanduel': 'FanDuel'
        }
    
    def normalize_player_name(self, player_name: str) -> str:
        """Create normalized player lookup key."""
        if not player_name:
            return ""
        
        # Convert to lowercase and remove common suffixes
        normalized = player_name.lower().strip()
        normalized = re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', normalized)
        
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def calculate_validation_confidence(self, scrape_date: datetime, game_date: datetime) -> float:
        """Calculate time-based validation confidence."""
        if not scrape_date or not game_date:
            return 0.1
            
        days_diff = abs((scrape_date.date() - game_date.date()).days)
        
        if days_diff == 0:          # Same day - high confidence
            return 0.95
        elif days_diff <= 7:        # Within week
            return 0.7
        elif days_diff <= 30:       # Within month
            return 0.5
        elif days_diff <= 365:      # Within year
            return 0.3
        else:                       # Over year old
            return 0.1
    
    def determine_validation_notes(self, player_team: str, confidence: float) -> str:
        """Determine validation notes based on team and confidence."""
        if player_team == "FA":
            return "free_agent"
        elif confidence >= 0.8:
            return "high_confidence_gameday"
        elif confidence >= 0.5:
            return "medium_confidence_recent"
        else:
            return "low_confidence_historical"
    
    def normalize_bookmaker_name(self, book_name: str) -> str:
        """Normalize bookmaker names for consistency."""
        if not book_name:
            return ""
        
        normalized_key = book_name.lower().strip()
        return self.bookmaker_mapping.get(normalized_key, book_name)
    
    def extract_game_date_from_path(self, file_path: str) -> Optional[datetime]:
        """Extract game date from BettingPros file path."""
        # Pattern: /bettingpros/player-props/points/2021-12-04/timestamp.json
        try:
            parts = file_path.split('/')
            for part in parts:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', part):
                    return datetime.strptime(part, '%Y-%m-%d')
            return None
        except Exception:
            return None
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate BettingPros JSON structure."""
        errors = []
        
        if 'props' not in data:
            errors.append("Missing 'props' array")
        elif not isinstance(data['props'], list):
            errors.append("'props' is not an array")
        
        if 'date' not in data:
            errors.append("Missing 'date' field")
        
        if 'market_type' not in data:
            errors.append("Missing 'market_type' field")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform BettingPros nested JSON into flattened records."""
        rows = []
        
        # Extract metadata
        scrape_date = self.extract_game_date_from_path(file_path)
        game_date = None
        if 'date' in raw_data:
            try:
                game_date = datetime.strptime(raw_data['date'], '%Y-%m-%d')
            except ValueError:
                logging.warning(f"Could not parse game date: {raw_data.get('date')}")
        
        market_type = raw_data.get('market_type', 'points')
        market_id = raw_data.get('market_id')
        current_time = datetime.utcnow()
        
        # Process each prop
        for prop in raw_data.get('props', []):
            offer_id = prop.get('offer_id')
            bp_event_id = prop.get('event_id')
            bp_player_id = prop.get('player_id')
            player_name = prop.get('player_name', '')
            player_team = prop.get('player_team', '')
            player_position = prop.get('player_position', '')
            
            # Normalize player lookup
            player_lookup = self.normalize_player_name(player_name)
            
            # Calculate validation fields
            validation_confidence = self.calculate_validation_confidence(scrape_date, game_date) if scrape_date and game_date else 0.1
            has_team_issues = True  # All records require validation initially
            team_source = "bettingpros"
            validation_method = "bettingpros_unvalidated"
            validation_notes = self.determine_validation_notes(player_team, validation_confidence)
            
            # Process over and under sides
            for bet_side in ['over', 'under']:
                side_data = prop.get(bet_side)
                if not side_data:
                    continue
                
                # Get opening line data
                opening_line_data = side_data.get('opening_line', {})
                opening_line = opening_line_data.get('line')
                opening_odds = opening_line_data.get('cost')
                opening_book_id = opening_line_data.get('book_id')
                opening_timestamp = None
                if opening_line_data.get('created'):
                    try:
                        opening_timestamp = datetime.strptime(opening_line_data['created'], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        pass
                
                # Process each sportsbook for this side
                for sportsbook in side_data.get('sportsbooks', []):
                    book_id = sportsbook.get('book_id')
                    book_name = sportsbook.get('book_name', '')
                    line_id = sportsbook.get('line_id')
                    points_line = sportsbook.get('line')
                    odds_american = sportsbook.get('odds')
                    is_active = sportsbook.get('active', True)
                    is_best_line = sportsbook.get('best', False)
                    
                    # Parse bookmaker last update
                    bookmaker_last_update = current_time
                    if sportsbook.get('updated'):
                        try:
                            bookmaker_last_update = datetime.strptime(sportsbook['updated'], '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            pass
                    
                    # Create flattened record
                    row = {
                        # Core identifiers
                        'game_date': game_date.date() if game_date else scrape_date.date() if scrape_date else None,
                        'market_type': market_type,
                        'market_id': market_id,
                        'bp_event_id': bp_event_id,
                        'offer_id': offer_id,
                        'bet_side': bet_side,
                        
                        # Player identification
                        'bp_player_id': bp_player_id,
                        'player_name': player_name,
                        'player_lookup': player_lookup,
                        'player_team': player_team,
                        'player_position': player_position,
                        
                        # Team validation
                        'team_source': team_source,
                        'has_team_issues': has_team_issues,
                        'validated_team': None,  # To be filled by future validation
                        'validation_confidence': validation_confidence,
                        'validation_method': validation_method,
                        'validation_notes': validation_notes,
                        'player_complications': None,  # To be filled if complications detected
                        
                        # Sportsbook details
                        'book_id': book_id,
                        'bookmaker': self.normalize_bookmaker_name(book_name),
                        'line_id': line_id,
                        'points_line': points_line,
                        'odds_american': odds_american,
                        'is_active': is_active,
                        'is_best_line': is_best_line,
                        'bookmaker_last_update': bookmaker_last_update.isoformat() if bookmaker_last_update else None,
                        
                        # Opening line tracking
                        'opening_line': opening_line,
                        'opening_odds': opening_odds,
                        'opening_book_id': opening_book_id,
                        'opening_timestamp': opening_timestamp.isoformat() if opening_timestamp else None,
                        
                        # Processing metadata
                        'source_file_path': file_path,
                        'created_at': current_time.isoformat(),
                        'processed_at': current_time.isoformat()
                    }
                    
                    rows.append(row)
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load flattened records to BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # APPEND_ALWAYS strategy - just insert all records
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logging.error(f"Failed to insert to BigQuery: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors,
            'unique_players': len(set(row['player_lookup'] for row in rows)),
            'unique_bookmakers': len(set(row['bookmaker'] for row in rows)),
            'props_processed': len(set(row['offer_id'] for row in rows))
        }