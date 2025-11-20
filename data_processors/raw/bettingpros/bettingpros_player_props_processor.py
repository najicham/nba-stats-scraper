#!/usr/bin/env python3
# File: data_processors/raw/bettingpros/bettingpros_player_props_processor.py
# Strategy: CHECK_BEFORE_INSERT - Track processed files, preserve time-series data

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
        self.processing_strategy = 'CHECK_BEFORE_INSERT'  # Preserve time-series data

        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.unknown_bookmakers = set()
        
        # Bookmaker mappings (unchanged)
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
        
        self.book_id_mapping = {
            0: 'BettingPros Consensus',
            2: 'SuperBook',
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
            33: 'Fanatics',
            36: 'ESPN Bet',
            37: 'Hard Rock',
            49: 'Fliff',
        }
    
    def file_already_processed(self, file_path: str) -> bool:
        """
        Check if this specific GCS file has already been processed.
        
        This prevents duplicate processing of the same scrape snapshot
        while allowing multiple scrapes per day to track line movements.
        """
        table_id = f"{self.project_id}.{self.table_name}"
        
        # Query to check if this file path exists
        query = f"""
        SELECT COUNT(*) as count
        FROM `{table_id}`
        WHERE source_file_path = @file_path
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("file_path", "STRING", file_path)
            ]
        )
        
        try:
            query_job = self.bq_client.query(query, job_config=job_config)
            results = list(query_job.result())
            
            if results and results[0]['count'] > 0:
                logger.info(f"File already processed, skipping: {file_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking if file processed: {e}")
            # If check fails, assume not processed to avoid data loss
            return False
    
    def normalize_player_name(self, player_name: str) -> str:
        """Create normalized player lookup key."""
        if not player_name:
            return ""
        
        normalized = player_name.lower().strip()
        normalized = re.sub(r'\s+(jr\.?|sr\.?|ii|iii|iv)$', '', normalized)
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def extract_scrape_timestamp_from_path(self, file_path: str) -> Optional[datetime]:
        """Extract when the scraper actually ran from filename timestamp."""
        try:
            filename = file_path.split('/')[-1]
            timestamp_part = filename.split('.')[0]
            return datetime.strptime(timestamp_part, '%Y%m%d_%H%M%S')
        except Exception as e:
            logger.warning(f"Could not parse scrape timestamp from {file_path}: {e}")
            return None
    
    def extract_game_date_from_path(self, file_path: str) -> Optional[datetime]:
        """Extract game date from BettingPros file path."""
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
            
        days_diff = abs((scrape_time.date() - game_date.date()).days)
        
        if days_diff == 0:
            return 0.95
        elif days_diff <= 7:
            return 0.7
        elif days_diff <= 30:
            return 0.5
        elif days_diff <= 365:
            return 0.3
        else:
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
        
        normalized_key = book_name.lower().strip()
        mapped_name = self.bookmaker_mapping.get(normalized_key, book_name)
        
        if book_id is not None and (mapped_name == book_name or mapped_name.startswith('Unknown Book')):
            mapped_name = self.book_id_mapping.get(book_id, f"Unknown Book {book_id}")
            
            if mapped_name.startswith('Unknown Book'):
                self.unknown_bookmakers.add(f"{book_name} (ID: {book_id})")
        
        elif mapped_name.startswith('Unknown Book'):
            try:
                extracted_id = int(mapped_name.split()[-1])
                mapped_name = self.book_id_mapping.get(extracted_id, mapped_name)
                
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
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform BettingPros nested JSON into flattened records."""
        rows = []
        
        try:
            actual_scrape_time = self.extract_scrape_timestamp_from_path(file_path)
            game_date = None
            if 'date' in raw_data:
                try:
                    game_date = datetime.strptime(raw_data['date'], '%Y-%m-%d')
                except ValueError:
                    logger.warning(f"Could not parse game date: {raw_data.get('date')}")
            
            if not game_date:
                game_date = self.extract_game_date_from_path(file_path)
            
            market_type = raw_data.get('market_type', 'points')
            market_id = raw_data.get('market_id')
            current_time = datetime.utcnow()
            
            for prop in raw_data.get('props', []):
                offer_id = prop.get('offer_id')
                bp_event_id = prop.get('event_id')
                bp_player_id = prop.get('player_id')
                player_name = prop.get('player_name', '')
                player_team = prop.get('player_team', '')
                player_position = prop.get('player_position', '')
                
                player_lookup = self.normalize_player_name(player_name)
                
                if game_date:
                    processing_time = current_time
                    validation_confidence = self.calculate_validation_confidence(processing_time, game_date)
                    validation_method = "bettingpros_freshness_based"
                    days_diff = abs((processing_time.date() - game_date.date()).days)
                    validation_notes = self.determine_validation_notes(player_team, validation_confidence, days_diff)
                else:
                    validation_confidence = 0.1
                    validation_method = "bettingpros_no_game_date"
                    validation_notes = "game_date_extraction_failed"

                has_team_issues = True
                team_source = "bettingpros"
                
                for bet_side in ['over', 'under']:
                    side_data = prop.get(bet_side)
                    if not side_data:
                        continue
                    
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
                    
                    for sportsbook in side_data.get('sportsbooks', []):
                        book_id = sportsbook.get('book_id')
                        book_name = sportsbook.get('book_name', '')
                        line_id = sportsbook.get('line_id')
                        points_line = sportsbook.get('line')
                        odds_american = sportsbook.get('odds')
                        is_active = sportsbook.get('active', True)
                        is_best_line = sportsbook.get('best', False)
                        
                        bookmaker_last_update = current_time
                        if sportsbook.get('updated'):
                            try:
                                bookmaker_last_update = datetime.strptime(sportsbook['updated'], '%Y-%m-%d %H:%M:%S')
                            except ValueError:
                                pass
                        
                        row = {
                            'game_date': game_date.date().isoformat() if game_date else None,
                            'market_type': market_type,
                            'market_id': market_id,
                            'bp_event_id': bp_event_id,
                            'offer_id': offer_id,
                            'bet_side': bet_side,
                            'bp_player_id': bp_player_id,
                            'player_name': player_name,
                            'player_lookup': player_lookup,
                            'player_team': player_team,
                            'player_position': player_position,
                            'team_source': team_source,
                            'has_team_issues': has_team_issues,
                            'validated_team': None,
                            'validation_confidence': validation_confidence,
                            'validation_method': validation_method,
                            'validation_notes': validation_notes,
                            'player_complications': None,
                            'book_id': book_id,
                            'bookmaker': self.normalize_bookmaker_name(book_name, book_id),
                            'line_id': line_id,
                            'points_line': points_line,
                            'odds_american': odds_american,
                            'is_active': is_active,
                            'is_best_line': is_best_line,
                            'bookmaker_last_update': bookmaker_last_update.isoformat() if bookmaker_last_update else None,
                            'opening_line': opening_line,
                            'opening_odds': opening_odds,
                            'opening_book_id': opening_book_id,
                            'opening_timestamp': opening_timestamp.isoformat() if opening_timestamp else None,
                            'source_file_path': file_path,
                            'created_at': current_time.isoformat(),
                            'processed_at': current_time.isoformat()
                        }
                        
                        rows.append(row)
        
        except Exception as e:
            logger.error(f"Transform failed for {file_path}: {e}", exc_info=True)
            
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
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """
        Load flattened records to BigQuery using BATCH LOADING.
        
        Preserves time-series data (multiple scrapes per day) while avoiding
        streaming buffer issues that would block future operations.
        """
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # BATCH LOADING: Use load_table_from_json instead of insert_rows_json
            # This avoids streaming buffer and allows immediate DML operations
            job_config = bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            )
            
            load_job = self.bq_client.load_table_from_json(
                rows, 
                table_id, 
                job_config=job_config
            )
            load_result = load_job.result()  # Wait for completion (2-5 seconds)
            
            # Check for errors
            if load_job.errors:
                errors.extend([str(e) for e in load_job.errors])
                logger.error(f"BigQuery batch load errors: {errors}")
                
                try:
                    notify_error(
                        title="BettingPros Props BigQuery Batch Load Failed",
                        message=f"Failed to batch load {len(rows)} BettingPros prop records",
                        details={
                            'processor': 'BettingPropsProcessor',
                            'table': self.table_name,
                            'rows_attempted': len(rows),
                            'error_count': len(load_job.errors),
                            'errors': [str(e) for e in load_job.errors[:3]]
                        },
                        processor_name="BettingPros Props Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            else:
                # Success
                unique_players = len(set(row['player_lookup'] for row in rows))
                unique_bookmakers = len(set(row['bookmaker'] for row in rows))
                props_processed = len(set(row['offer_id'] for row in rows))
                game_dates = set(row['game_date'] for row in rows)
                
                logger.info(f"✅ Batch loaded {len(rows)} rows successfully")
                
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
                            'table': self.table_name,
                            'strategy': 'CHECK_BEFORE_INSERT (Batch Loading)',
                            'dates_processed': sorted(game_dates)
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                if self.unknown_bookmakers:
                    try:
                        notify_warning(
                            title="Unknown Bookmakers Detected",
                            message=f"Found {len(self.unknown_bookmakers)} unknown bookmakers",
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
            logger.error(f"Failed to load to BigQuery: {error_msg}", exc_info=True)
            
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
        """
        Main processing method called by backfill jobs.
        
        Checks if file already processed to prevent duplicates while
        allowing multiple scrapes per day for line movement tracking.
        """
        try:
            # CHECK: Has this specific file been processed before?
            if self.file_already_processed(file_path):
                return {
                    'rows_processed': 0,
                    'errors': [],
                    'unique_players': 0,
                    'unique_bookmakers': 0,
                    'props_processed': 0,
                    'skipped': True,
                    'reason': 'file_already_processed'
                }
            
            # Parse JSON
            raw_data = json.loads(json_content)
            
            # Validate
            validation_errors = self.validate_data(raw_data)
            if validation_errors:
                logger.error(f"Validation errors for {file_path}: {validation_errors}")
                
                try:
                    notify_warning(
                        title="BettingPros Props Data Validation Errors",
                        message=f"Validation errors: {', '.join(validation_errors[:3])}",
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
            
            # Transform
            rows = self.transform_data(raw_data, file_path)
            
            # Load (batch loading, preserves time-series)
            result = self.load_data(rows)
            
            return result
            
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON: {str(e)}"
            logger.error(f"{error_msg} in {file_path}")
            
            try:
                notify_error(
                    title="BettingPros Props JSON Parse Failed",
                    message=f"Failed to parse JSON from file",
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
            
            try:
                notify_error(
                    title="BettingPros Props Processing Failed",
                    message=f"Unexpected error processing file: {str(e)}",
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