#!/usr/bin/env python3
# File: processors/nbacom/nbac_player_movement_processor.py
# Description: Processor for NBA.com Player Movement data transformation

import logging
import os
from google.cloud import bigquery
from datetime import datetime, date
from typing import Dict, List, Optional, Set, Tuple
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase

logger = logging.getLogger(__name__)

class NbacPlayerMovementProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_player_movement'
        self.processing_strategy = 'INSERT_NEW_ONLY'  # Custom strategy
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Team slug to abbreviation mapping
        self.team_slug_to_abbr = {
            'hawks': 'ATL', 'celtics': 'BOS', 'nets': 'BKN', 'hornets': 'CHA',
            'bulls': 'CHI', 'cavaliers': 'CLE', 'mavericks': 'DAL', 'nuggets': 'DEN', 
            'pistons': 'DET', 'warriors': 'GSW', 'rockets': 'HOU', 'pacers': 'IND',
            'clippers': 'LAC', 'lakers': 'LAL', 'grizzlies': 'MEM', 'heat': 'MIA',
            'bucks': 'MIL', 'timberwolves': 'MIN', 'pelicans': 'NOP', 'knicks': 'NYK',
            'thunder': 'OKC', 'magic': 'ORL', 'sixers': 'PHI', 'suns': 'PHX',
            'blazers': 'POR', 'kings': 'SAC', 'spurs': 'SAS', 'raptors': 'TOR',
            'jazz': 'UTA', 'wizards': 'WAS'
        }
    
    def normalize_player_slug(self, slug: str) -> Tuple[str, str]:
        """Convert player slug to full name and lookup."""
        if not slug:
            return "", ""
        
        # "haywood-highsmith" -> "Haywood Highsmith" 
        full_name = slug.replace('-', ' ').title()
        
        # "Haywood Highsmith" -> "haywoodhighsmith"
        lookup = full_name.lower().replace(' ', '').replace("'", "")
        
        return full_name, lookup
    
    def calculate_season_year(self, transaction_date: str) -> int:
        """Calculate NBA season year from transaction date."""
        dt = datetime.fromisoformat(transaction_date.replace('T00:00:00', ''))
        year = dt.year
        
        # NBA season starts in October, so October+ = new season
        if dt.month >= 10:
            return year
        else:
            return year - 1
    
    def get_existing_records(self) -> Set[Tuple]:
        """Query BigQuery for existing primary keys to avoid duplicates."""
        query = f"""
        SELECT 
            player_id,
            team_id, 
            transaction_date,
            transaction_type,
            group_sort
        FROM `{self.project_id}.{self.table_name}`
        """
        
        try:
            result = self.bq_client.query(query)
            existing_keys = set()
            for row in result:
                key = (row.player_id, row.team_id, row.transaction_date, 
                      row.transaction_type, row.group_sort)
                existing_keys.add(key)
            
            logger.info(f"Found {len(existing_keys)} existing records in BigQuery")
            return existing_keys
            
        except Exception as e:
            logger.warning(f"Could not query existing records: {e}")
            return set()
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the player movement data structure."""
        errors = []
        
        if 'metadata' not in data:
            errors.append("Missing metadata section")
            return errors
        
        if 'rows' not in data:
            errors.append("Missing rows section")
            return errors
        
        metadata = data['metadata']
        if 'recordCount' not in metadata:
            errors.append("Missing recordCount in metadata")
        
        if 'fetchedUtc' not in metadata:
            errors.append("Missing fetchedUtc in metadata")
        
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform player movement data into BigQuery format."""
        if not raw_data.get('rows'):
            logger.warning("No rows found in data")
            return []
        
        metadata = raw_data.get('metadata', {})
        scrape_timestamp = metadata.get('fetchedUtc', datetime.utcnow().isoformat())
        
        # Get existing records to avoid duplicates
        existing_keys = self.get_existing_records()
        
        rows = []
        skipped_count = 0
        old_transactions = 0
        
        for transaction in raw_data['rows']:
            try:
                # Filter to 2021+ transactions only
                transaction_date_str = transaction['TRANSACTION_DATE']
                transaction_dt = datetime.fromisoformat(transaction_date_str.replace('T00:00:00', ''))
                
                if transaction_dt.date() < date(2021, 1, 1):
                    old_transactions += 1
                    continue
                
                # Check if this record already exists
                primary_key = (
                    transaction['PLAYER_ID'],
                    transaction['TEAM_ID'],
                    transaction_dt.date(),
                    transaction['Transaction_Type'],
                    transaction['GroupSort']
                )
                
                if primary_key in existing_keys:
                    skipped_count += 1
                    continue
                
                # Parse player information
                player_full_name, player_lookup = self.normalize_player_slug(
                    transaction.get('PLAYER_SLUG', '')
                )
                
                # Map team slug to abbreviation
                team_slug = transaction.get('TEAM_SLUG', '').lower()
                team_abbr = self.team_slug_to_abbr.get(team_slug, team_slug.upper())
                
                # Calculate season year
                season_year = self.calculate_season_year(transaction_date_str)
                
                row = {
                    'transaction_type': transaction['Transaction_Type'],
                    'transaction_date': transaction_dt.date().isoformat(),
                    'season_year': season_year,
                    'player_id': transaction['PLAYER_ID'],
                    'player_slug': transaction.get('PLAYER_SLUG', ''),
                    'player_full_name': player_full_name,
                    'player_lookup': player_lookup,
                    'is_player_transaction': transaction['PLAYER_ID'] != 0,
                    'team_id': transaction['TEAM_ID'],
                    'team_slug': team_slug,
                    'team_abbr': team_abbr,
                    'transaction_description': transaction['TRANSACTION_DESCRIPTION'],
                    'additional_sort': transaction.get('Additional_Sort', 0),
                    'group_sort': transaction['GroupSort'],
                    'source_file_path': file_path,
                    'scrape_timestamp': scrape_timestamp,
                    'created_at': datetime.utcnow().isoformat()
                }
                
                rows.append(row)
                
            except Exception as e:
                logger.error(f"Error transforming transaction: {e}")
                continue
        
        logger.info(f"Transformed {len(rows)} new records, skipped {skipped_count} existing, "
                   f"filtered {old_transactions} pre-2021 transactions")
        
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load new records into BigQuery (INSERT_NEW_ONLY strategy)."""
        if not rows:
            return {'rows_processed': 0, 'errors': [], 'skipped': 0}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Insert new rows only (we already filtered out existing ones)
            result = self.bq_client.insert_rows_json(table_id, rows)
            
            if result:
                errors.extend([str(e) for e in result])
                logger.error(f"BigQuery insert errors: {errors}")
                return {'rows_processed': 0, 'errors': errors}
            
            logger.info(f"Successfully inserted {len(rows)} new records")
            return {'rows_processed': len(rows), 'errors': []}
            
        except Exception as e:
            error_msg = f"Failed to insert rows: {str(e)}"
            logger.error(error_msg)
            return {'rows_processed': 0, 'errors': [error_msg]}