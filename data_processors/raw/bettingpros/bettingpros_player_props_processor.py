#!/usr/bin/env python3
# File: processors/bettingpros/bettingpros_player_props_processor.py
# Description: Processor for BettingPros player props data transformation
# Fixed: Validation confidence calculation and bookmaker mapping

import json
import logging
import re
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

class BettingPropsProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bettingpros_player_points_props'
        self.processing_strategy = 'APPEND_ALWAYS'  # Track all historical snapshots

        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.unknown_bookmakers = set()  # Track unknown bookmakers for batch warning
        
        # Enhanced bookmaker name normalization with comprehensive mapping
        self.bookmaker_mapping = {
            'bettingpros consensus': 'BettingPros Consensus',
            'betmgm': 'BetMGM',
            'betrivers': 'BetRivers', 
            'sugarhouse': 'SugarHouse',
            'partycasino': 'PartyCasino',
            'draftkings': 'DraftKings',
            'fanduel': 'FanDuel',
            'caesars': 'Caesars',
            'bet365': 'bet365',
            'pointsbet': 'PointsBet',
            'wynnbet': 'WynnBET',
            'barstool': 'Barstool',
            'unibet': 'UniBet',
            'betamerica': 'BetAmerica',
            'twinspires': 'TwinSpires',
            'fox bet': 'FOX Bet',
            'oregon lottery': 'Oregon Lottery',
            'tipico': 'Tipico',
            'betway': 'Betway',
            'fubo': 'Fubo',
        }
        
        # Handle unknown books by ID (from your query results and scraper BOOKS mapping)
        self.book_id_mapping = {
            0: 'BettingPros Consensus',
            2: 'SuperBook',           # Unknown Book 2
            10: 'FanDuel',
            12: 'DraftKings', 
            13: 'Caesars',
            14: 'PointsBet',
            15: 'SugarHouse',
            18: 'BetRivers',
            19: 'BetMGM',
            20: 'FOX Bet',
            21: 'BetAmerica',
            22: 'Oregon Lottery',
            24: 'bet365',
            25: 'WynnBET',
            26: 'Tipico',
            27: 'PartyCasino',
            28: 'UniBet',
            29: 'TwinSpires',
            30: 'Betway',
            31: 'Fubo',
            33: 'Fanatics',          # Unknown Book 33
            36: 'ESPN Bet',          # Unknown Book 36  
            37: 'Hard Rock',         # Unknown Book 37
            49: 'Fliff',             # Unknown Book 49
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
    
    def extract_scrape_timestamp_from_path(self, file_path: str) -> Optional[datetime]:
        """Extract when the scraper actually ran from filename timestamp."""
        # Pattern: /2021-12-04/20250813_011358.json -> actual scrape time
        try:
            filename = file_path.split('/')[-1]  # Get "20250813_011358.json"
            timestamp_part = filename.split('.')[0]  # Get "20250813_011358"
            return datetime.strptime(timestamp_part, '%Y%m%d_%H%M%S')
        except Exception as e:
            logger.warning(f"Could not parse scrape timestamp from {file_path}: {e}")
            return None
    
    def extract_game_date_from_path(self, file_path: str) -> Optional[datetime]:
        """Extract game date from BettingPros file path."""
        # Pattern: /bettingpros/player-props/points/2021-12-04/timestamp.json
        try:
            parts = file_path.split('/')
            for part in parts:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', part):
                    return datetime.strptime(part, '%Y-%m-%d')
            return None
        except Exception as e:
            logger.warning(f"Could not parse game date from {file_path}: {e}")
            return None
    
    def calculate_validation_confidence(self, scrape_time: datetime, game_date: datetime) -> float:
        """Calculate data freshness confidence using processing time vs game date."""
        if not scrape_time or not game_date:
            return 0.1
            
        # Compare actual scrape timestamp vs game date
        days_diff = abs((scrape_time.date() - game_date.date()).days)
        
        logger.debug(f"Validation confidence: scrape_time={scrape_time.date()}, game_date={game_date.date()}, days_diff={days_diff}")
        
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
    
    def determine_validation_notes(self, player_team: str, confidence: float, days_diff: int = None, forced_historical: bool = False) -> str:
        """Determine validation notes based on team and confidence."""
        if player_team == "FA":
            if forced_historical:
                return "free_agent_historical"
            return "free_agent"
        elif forced_historical:
            return "low_confidence_historical_old"
        elif confidence >= 0.8:
            return "high_confidence_gameday"
        elif confidence >= 0.5:
            return "medium_confidence_recent"
        elif days_diff and days_diff > 365:
            return "low_confidence_historical_old"
        else:
            return "low_confidence_historical"
    
    def normalize_bookmaker_name(self, book_name: str, book_id: int = None) -> str:
        """Enhanced bookmaker normalization with ID fallback."""
        if not book_name:
            if book_id is not None:
                return self.book_id_mapping.get(book_id, f"Unknown Book {book_id}")
            return ""
        
        # First try name mapping
        normalized_key = book_name.lower().strip()
        mapped_name = self.bookmaker_mapping.get(normalized_key, book_name)
        
        # If still unknown and we have book_id, try ID mapping
        if book_id is not None and (mapped_name == book_name or mapped_name.startswith('Unknown Book')):
            mapped_name = self.book_id_mapping.get(book_id, f"Unknown Book {book_id}")
            
            # Track unknown bookmaker if we're using fallback
            if mapped_name.startswith('Unknown Book'):
                self.unknown_bookmakers.add(f"{book_name} (ID: {book_id})")
        
        # Handle existing "Unknown Book X" format by extracting ID
        elif mapped_name.startswith('Unknown Book'):
            try:
                # Extract ID from "Unknown Book 33" format
                extracted_id = int(mapped_name.split()[-1])
                mapped_name = self.book_id_mapping.get(extracted_id, mapped_name)
                
                # Track if still unknown after ID lookup
                if mapped_name.startswith('Unknown Book'):
                    self.unknown_bookmakers.add(f"{book_name} (ID: {extracted_id})")
            except (ValueError, IndexError):
                self.unknown_bookmakers.add(book_name)
        
        return mapped_name
    
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
        
        try:
            # Extract metadata - Use actual scrape timestamp vs game date
            actual_scrape_time = self.extract_scrape_timestamp_from_path(file_path)
            game_date = None
            if 'date' in raw_data:
                try:
                    game_date = datetime.strptime(raw_data['date'], '%Y-%m-%d')
                except ValueError:
                    logger.warning(f"Could not parse game date: {raw_data.get('date')}")
            
            # Fallback for game date if not in JSON
            if not game_date:
                game_date = self.extract_game_date_from_path(file_path)
            
            market_type = raw_data.get('market_type', 'points')
            market_id = raw_data.get('market_id')
            current_time = datetime.utcnow()
            
            # Debug logging once per file
            if actual_scrape_time and game_date:
                days_diff = abs((actual_scrape_time.date() - game_date.date()).days)
                logger.debug(f"Processing {file_path}: scrape={actual_scrape_time.date()}, game={game_date.date()}, days_diff={days_diff}")
            else:
                logger.warning(f"Missing timestamps for {file_path}: scrape_time={actual_scrape_time}, game_date={game_date}")
            
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
                
                # Calculate validation confidence using processing time vs game date
                # This measures how "fresh" the game data is for current betting decisions
                # processing_time = today (Sept 2025), game_date = historical (2021) = ~1400 days = 0.1 confidence
                if game_date:
                    processing_time = current_time  # When we're inserting into database
                    validation_confidence = self.calculate_validation_confidence(processing_time, game_date)
                    validation_method = "bettingpros_freshness_based"
                    days_diff = abs((processing_time.date() - game_date.date()).days)
                    
                    # Debug logging for troubleshooting
                    logger.debug(f"Processing {file_path}: processing_time={processing_time.date()}, game_date={game_date.date()}, days_diff={days_diff}, confidence={validation_confidence}")
                    
                    validation_notes = self.determine_validation_notes(player_team, validation_confidence, days_diff)
                else:
                    # Fallback when game date extraction fails
                    validation_confidence = 0.1
                    validation_method = "bettingpros_no_game_date"
                    validation_notes = "game_date_extraction_failed"
                    logger.warning(f"Game date extraction failed for {file_path}")

                has_team_issues = True
                team_source = "bettingpros"
                
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
                            'game_date': game_date.date().isoformat() if game_date else None,
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
                            
                            # Team validation - FIXED: Consistent confidence calculation
                            'team_source': team_source,
                            'has_team_issues': has_team_issues,
                            'validated_team': None,  # To be filled by future validation
                            'validation_confidence': validation_confidence,
                            'validation_method': validation_method,
                            'validation_notes': validation_notes,
                            'player_complications': None,  # To be filled if complications detected
                            
                            # Sportsbook details - ENHANCED: Better normalization
                            'book_id': book_id,
                            'bookmaker': self.normalize_bookmaker_name(book_name, book_id),
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
        
        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            
            # Send error notification
            try:
                notify_error(
                    title="BettingPros Props Transform Failed",
                    message=f"Failed to transform BettingPros props data: {str(e)}",
                    details={
                        'processor': 'BettingPropsProcessor',
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="BettingPros Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise
        
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
                logger.error(f"BigQuery insert errors: {errors}")
                
                # Send error notification for BigQuery failures
                try:
                    notify_error(
                        title="BettingPros Props BigQuery Insert Failed",
                        message=f"Failed to insert {len(rows)} BettingPros prop records into BigQuery",
                        details={
                            'processor': 'BettingPropsProcessor',
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'error_count': len(result),
                            'errors': [str(e) for e in result[:3]]  # First 3 errors
                        },
                        processor_name="BettingPros Props Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            else:
                # Success - send info notification
                unique_players = len(set(row['player_lookup'] for row in rows))
                unique_bookmakers = len(set(row['bookmaker'] for row in rows))
                props_processed = len(set(row['offer_id'] for row in rows))
                
                try:
                    notify_info(
                        title="BettingPros Props Processing Complete",
                        message=f"Successfully processed {len(rows)} prop records",
                        details={
                            'processor': 'BettingPropsProcessor',
                            'rows_processed': len(rows),
                            'unique_players': unique_players,
                            'unique_bookmakers': unique_bookmakers,
                            'props_processed': props_processed,
                            'table': self.table_name
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                # Warn about unknown bookmakers if any were found
                if self.unknown_bookmakers:
                    try:
                        notify_warning(
                            title="Unknown Bookmakers Detected",
                            message=f"Found {len(self.unknown_bookmakers)} unknown bookmakers in BettingPros data",
                            details={
                                'processor': 'BettingPropsProcessor',
                                'unknown_bookmakers': list(self.unknown_bookmakers)
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Failed to insert to BigQuery: {error_msg}", exc_info=True)
            
            # Send critical error notification
            try:
                notify_error(
                    title="BettingPros Props Load Exception",
                    message=f"Critical failure loading BettingPros props data: {str(e)}",
                    details={
                        'processor': 'BettingPropsProcessor',
                        'table': self.table_name,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="BettingPros Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors,
            'unique_players': len(set(row['player_lookup'] for row in rows)) if not errors else 0,
            'unique_bookmakers': len(set(row['bookmaker'] for row in rows)) if not errors else 0,
            'props_processed': len(set(row['offer_id'] for row in rows)) if not errors else 0
        }

    def process_file_content(self, json_content: str, file_path: str) -> Dict:
        """Main processing method called by backfill jobs."""
        try:
            # Parse JSON
            raw_data = json.loads(json_content)
            
            # Validate data structure
            validation_errors = self.validate_data(raw_data)
            if validation_errors:
                logger.error(f"Validation errors for {file_path}: {validation_errors}")
                
                # Send warning notification for validation errors
                try:
                    notify_warning(
                        title="BettingPros Props Data Validation Errors",
                        message=f"Validation errors found in BettingPros props data: {', '.join(validation_errors[:3])}",
                        details={
                            'processor': 'BettingPropsProcessor',
                            'file_path': file_path,
                            'error_count': len(validation_errors),
                            'errors': validation_errors
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {
                    'rows_processed': 0,
                    'errors': validation_errors,
                    'unique_players': 0,
                    'unique_bookmakers': 0,
                    'props_processed': 0
                }
            
            # Transform data
            rows = self.transform_data(raw_data, file_path)
            
            # Load to BigQuery
            result = self.load_data(rows)
            
            return result
            
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON: {str(e)}"
            logger.error(f"{error_msg} in {file_path}")
            
            # Send error notification for JSON parse failure
            try:
                notify_error(
                    title="BettingPros Props JSON Parse Failed",
                    message=f"Failed to parse JSON from BettingPros props file",
                    details={
                        'processor': 'BettingPropsProcessor',
                        'file_path': file_path,
                        'error': str(e)
                    },
                    processor_name="BettingPros Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'rows_processed': 0,
                'errors': [error_msg],
                'unique_players': 0,
                'unique_bookmakers': 0,
                'props_processed': 0
            }
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            logger.error(f"{error_msg} in {file_path}", exc_info=True)
            
            # Send error notification for general processing failure
            try:
                notify_error(
                    title="BettingPros Props Processing Failed",
                    message=f"Unexpected error processing BettingPros props file: {str(e)}",
                    details={
                        'processor': 'BettingPropsProcessor',
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    },
                    processor_name="BettingPros Props Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'rows_processed': 0,
                'errors': [error_msg],
                'unique_players': 0,
                'unique_bookmakers': 0,
                'props_processed': 0
            }