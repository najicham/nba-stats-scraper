#!/usr/bin/env python3
"""
File: data_processors/reference/base/registry_processor_base.py

Base class for NBA registry processors.
Provides shared functionality for both gamebook and roster registry processors.
Enhanced with update source tracking and Universal Player ID integration.
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum
import pandas as pd
import numpy as np
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.universal_player_id_resolver import UniversalPlayerIDResolver
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class ProcessingStrategy(Enum):
    REPLACE = "replace"  # DELETE + INSERT 
    MERGE = "merge"      # MERGE statement


class UpdateSourceTrackingMixin:
    """Mixin to track which processor last updated each registry record."""
    
    def enhance_record_with_source_tracking(self, record: Dict, processor_type: str) -> Dict:
        """Add source tracking fields to registry record using actual schema field names."""
        current_time = datetime.now()
        
        # Update existing processed_at field and add new tracking fields
        record.update({
            'processed_at': current_time,  # Use existing field
            'last_processor': processor_type,  # 'gamebook' or 'roster'
            
            # Processor-specific timestamps
            f'last_{processor_type}_update': current_time,
            f'{processor_type}_update_count': record.get(f'{processor_type}_update_count', 0) + 1,
            
            # Update sequence for ordering
            'update_sequence_number': self._get_next_sequence_number()
        })
        
        return record
    
    def _get_next_sequence_number(self) -> int:
        """Generate sequence number for update ordering."""
        # Simple timestamp-based sequence
        return int(datetime.now().timestamp() * 1000)


class RegistryProcessorBase(ProcessorBase, UpdateSourceTrackingMixin):
    """
    Base class for NBA registry processors.
    
    Provides shared functionality for:
    - Database operations (MERGE/REPLACE strategies)
    - Type conversion utilities
    - Season calculations
    - Universal Player ID integration
    - Update source tracking
    - Basic validation and error handling
    """
    
    def __init__(self, test_mode: bool = False, strategy: str = "merge", 
                 confirm_full_delete: bool = False,
                 enable_name_change_detection: bool = True):
        super().__init__()
    
        # Configure processing strategy
        try:
            self.processing_strategy = ProcessingStrategy(strategy.lower())
        except ValueError as e:
            try:
                notify_error(
                    title="Registry Processor Initialization Failed",
                    message=f"Invalid processing strategy: {strategy}",
                    details={
                        'strategy': strategy,
                        'valid_strategies': ['merge', 'replace'],
                        'error': str(e)
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
        
        self.confirm_full_delete = confirm_full_delete
        self.enable_name_change_detection = enable_name_change_detection
        
        # Safety check for REPLACE mode
        if self.processing_strategy == ProcessingStrategy.REPLACE and not confirm_full_delete:
            error_msg = (
                "REPLACE strategy requires --confirm-full-delete flag to prevent accidental data loss. "
                "This will DELETE entire tables and rebuild from scratch. "
                "Use 'merge' strategy for incremental updates, or add --confirm-full-delete if full rebuild is intended."
            )
            
            try:
                notify_error(
                    title="Registry Processor Safety Check Failed",
                    message="REPLACE strategy attempted without confirmation",
                    details={
                        'strategy': 'REPLACE',
                        'confirm_full_delete': confirm_full_delete,
                        'required_action': 'Add --confirm-full-delete flag or use merge strategy'
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(error_msg)
        
        if self.processing_strategy == ProcessingStrategy.REPLACE and confirm_full_delete:
            logger.warning("🚨 REPLACE mode with FULL DELETE confirmation - this will rebuild tables from scratch")
            try:
                notify_warning(
                    title="Registry Processor in REPLACE Mode",
                    message="Full table rebuild mode active - all data will be deleted and rebuilt",
                    details={
                        'strategy': 'REPLACE',
                        'confirm_full_delete': True,
                        'impact': 'Complete table rebuild'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
        
        logger.info(f"Initialized with processing strategy: {self.processing_strategy.value}")
        logger.info(f"Name change detection: {'enabled' if enable_name_change_detection else 'disabled'}")
        
        # Initialize BigQuery client
        try:
            self.bq_client = bigquery.Client()
            self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            try:
                notify_error(
                    title="Registry Processor BigQuery Initialization Failed",
                    message="Unable to create BigQuery client",
                    details={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'project_id_env': os.environ.get('GCP_PROJECT_ID', 'not_set')
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

        # Processing tracking
        self.processing_run_id = f"registry_build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Configure test mode and table names
        self.test_mode = test_mode
        if test_mode:
            timestamp_suffix = "FIXED2"
            self.table_name = f'nba_reference.nba_players_registry_test_{timestamp_suffix}'
            self.unresolved_table_name = f'nba_reference.unresolved_player_names_test_{timestamp_suffix}'
            self.alias_table_name = f'nba_reference.player_aliases_test_{timestamp_suffix}'
            self.processing_run_id += f"_TEST_{timestamp_suffix}"
            logger.info(f"Running in TEST MODE with fixed table suffix: {timestamp_suffix}")
        else:
            self.table_name = 'nba_reference.nba_players_registry'
            self.unresolved_table_name = 'nba_reference.unresolved_player_names'
            self.alias_table_name = 'nba_reference.player_aliases'
            logger.info("Running in PRODUCTION MODE")
        
        # Initialize stats tracking
        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set(),
            'unresolved_players_found': 0,
            'alias_resolutions': 0
        }

        # Initialize universal ID resolver and tracking
        try:
            self.universal_id_resolver = UniversalPlayerIDResolver(self.bq_client, self.project_id)
        except Exception as e:
            logger.error(f"Failed to initialize Universal Player ID Resolver: {e}")
            try:
                notify_error(
                    title="Universal Player ID Resolver Initialization Failed",
                    message="Unable to initialize player ID resolver",
                    details={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'project_id': self.project_id
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
        
        self.new_players_discovered = set()
        self.players_seen_this_run = set()
        
        # Processor type (set by subclasses for source tracking)
        self.processor_type = None  # Must be set by subclasses
        
        logger.info(f"Initialized registry processor with run ID: {self.processing_run_id}")
    
    def calculate_season_string(self, season_year: int) -> str:
        """Convert season year to standard season string format."""
        return f"{season_year}-{str(season_year + 1)[-2:]}"
    
    def date_to_nba_season_years(self, date_range: Tuple[str, str]) -> Tuple[int, int]:
        """
        Convert date range to NBA season years.
        
        NBA season runs from October to June:
        - 2022-02-01 is in 2021-22 season (season_year=2021)
        - 2022-10-15 is in 2022-23 season (season_year=2022)
        """
        start_date = datetime.strptime(date_range[0], '%Y-%m-%d')
        end_date = datetime.strptime(date_range[1], '%Y-%m-%d')
        
        def get_season_year(date_obj):
            if date_obj.month >= 10:  # October-December
                return date_obj.year
            else:  # January-September (next calendar year)
                return date_obj.year - 1
        
        start_season_year = get_season_year(start_date)
        end_season_year = get_season_year(end_date)
        
        logger.info(f"Date range {date_range} maps to NBA season years: {start_season_year} to {end_season_year}")
        
        return (start_season_year, end_season_year)
    
    def _convert_pandas_types_for_json(self, record: Dict[str, Any], for_table_load: bool = False) -> Dict[str, Any]:
        """
        Convert pandas/numpy types to BigQuery-compatible types.
        
        Args:
            record: Dictionary with potentially problematic pandas/numpy types
            for_table_load: If True, prepare for load_table_from_json (preserve datetime objects)
                        If False, prepare for insert_rows_json (convert to strings)
        """
        converted_record = {}
        
        # Define fields that should be integers
        integer_fields = {'games_played', 'total_appearances', 'inactive_appearances', 
                'dnp_appearances', 'jersey_number', 'occurrences', 'gamebook_update_count', 
                'roster_update_count', 'update_sequence_number'}
        
        # Define TIMESTAMP fields that need special handling
        timestamp_fields = {'created_at', 'processed_at', 'reviewed_at',
                          'last_gamebook_update', 'last_roster_update'}
        
        for key, value in record.items():
            # Handle lists/arrays FIRST (before pd.isna check)
            if isinstance(value, list):
                converted_record[key] = value
                continue
            
            # Handle NaN/None values first
            if pd.isna(value):
                converted_record[key] = None
            
            # Handle numpy scalars
            elif hasattr(value, 'item'):  
                converted_record[key] = value.item()
            
            # Handle datetime objects
            elif isinstance(value, (pd.Timestamp, datetime)):
                if pd.notna(value):
                    if for_table_load and key in timestamp_fields:
                        converted_record[key] = value
                    else:
                        converted_record[key] = value.isoformat()
                else:
                    converted_record[key] = None
            
            # Handle date objects
            elif isinstance(value, date):
                converted_record[key] = value.isoformat()
            
            # Handle string values that should be integers
            elif key in integer_fields and isinstance(value, str):
                try:
                    converted_record[key] = int(value) if value.strip() else None
                except (ValueError, AttributeError):
                    converted_record[key] = None
            
            # Handle numpy/pandas types
            elif isinstance(value, (np.integer, int)) or (hasattr(value, 'dtype') and np.issubdtype(value.dtype, np.integer)):
                converted_record[key] = int(value)
            elif isinstance(value, (np.floating, float)) or (hasattr(value, 'dtype') and np.issubdtype(value.dtype, np.floating)):
                converted_record[key] = float(value)
            elif isinstance(value, (np.bool_, bool)) or (hasattr(value, 'dtype') and np.issubdtype(value.dtype, np.bool_)):
                converted_record[key] = bool(value)
            
            # Handle pandas Series scalars
            elif isinstance(value, pd.Series) and len(value) == 1:
                scalar_value = value.iloc[0]
                converted_record[key] = self._convert_pandas_types_for_json({'temp': scalar_value}, for_table_load)['temp']
            
            # Handle regular Python types
            else:
                converted_record[key] = value
        
        return converted_record
    
    def _check_player_aliases(self, player_lookup: str, team_abbr: str) -> bool:
        """Check if player exists under an alias in the registry."""
        alias_query = f"""
        SELECT r.player_lookup, r.team_abbr, r.games_played
        FROM `{self.project_id}.{self.alias_table_name}` a
        JOIN `{self.project_id}.{self.table_name}` r
        ON a.nba_canonical_lookup = r.player_lookup
        WHERE a.alias_lookup = @alias_lookup
        AND r.team_abbr = @team_abbr
        AND a.is_active = TRUE
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alias_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr)
        ])
        
        try:
            results = self.bq_client.query(alias_query, job_config=job_config).to_dataframe()
            found = not results.empty
            
            if found:
                self.stats['alias_resolutions'] += 1
                logger.info(f"ALIAS RESOLUTION SUCCESS: {player_lookup} for {team_abbr} found via alias mapping")
            
            return found
            
        except Exception as e:
            logger.warning(f"Error checking player aliases: {e}")
            try:
                notify_warning(
                    title="Player Alias Check Failed",
                    message=f"Unable to verify player alias for {player_lookup}",
                    details={
                        'player_lookup': player_lookup,
                        'team_abbr': team_abbr,
                        'error': str(e),
                        'error_type': type(e).__name__
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return False
    
    def resolve_universal_player_id(self, player_lookup: str) -> str:
        """Resolve or create universal player ID for a player."""
        try:
            universal_id = self.universal_id_resolver.resolve_or_create_universal_id(player_lookup)
            
            # Track new players discovered
            canonical_name = self.universal_id_resolver.get_canonical_player_name(player_lookup)
            if canonical_name not in self.players_seen_this_run:
                self.new_players_discovered.add(canonical_name)
            self.players_seen_this_run.add(canonical_name)
            
            return universal_id
            
        except Exception as e:
            logger.error(f"Error resolving universal ID for {player_lookup}: {e}")
            try:
                notify_error(
                    title="Universal Player ID Resolution Failed",
                    message=f"Unable to resolve player ID for {player_lookup}",
                    details={
                        'player_lookup': player_lookup,
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'fallback_action': 'Using simple ID fallback'
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Fallback: create simple ID to prevent failure
            return f"{player_lookup}_001"
    
    def bulk_resolve_universal_player_ids(self, player_lookups: List[str]) -> Dict[str, str]:
        """Resolve or create universal player IDs for a batch of players."""
        try:
            return self.universal_id_resolver.bulk_resolve_or_create_universal_ids(player_lookups)
        except Exception as e:
            logger.error(f"Error in bulk universal ID resolution: {e}")
            try:
                notify_error(
                    title="Bulk Universal Player ID Resolution Failed",
                    message=f"Unable to resolve IDs for batch of {len(player_lookups)} players",
                    details={
                        'player_count': len(player_lookups),
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'fallback_action': 'Using simple ID fallback for batch'
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Fallback: create simple mappings
            return {lookup: f"{lookup}_001" for lookup in player_lookups}
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate registry data structure."""
        errors = []
        
        if not isinstance(data, dict):
            errors.append("Data must be a dictionary")
            return errors
        
        # Basic validation - subclasses can override for specific requirements
        return errors
    
    def get_registry_summary(self) -> Dict:
        """Get summary statistics of the current registry with processor tracking."""
        try:
            query = f"""
            SELECT 
                COUNT(*) as total_records,
                COUNT(DISTINCT player_lookup) as unique_players,
                COUNT(DISTINCT universal_player_id) as unique_universal_ids,
                COUNT(DISTINCT season) as seasons_covered,
                COUNT(DISTINCT team_abbr) as teams_covered,
                SUM(games_played) as total_games_played,
                AVG(games_played) as avg_games_per_record,
                MAX(processed_at) as last_updated,
                
                -- Processor activity summary using actual field names
                COUNT(DISTINCT last_processor) as active_processors,
                COUNTIF(last_processor = 'gamebook') as gamebook_records,
                COUNTIF(last_processor = 'roster') as roster_records,
                MAX(last_gamebook_update) as last_gamebook_update,
                MAX(last_roster_update) as last_roster_update
            FROM `{self.project_id}.{self.table_name}`
            """
            
            result = self.bq_client.query(query).to_dataframe()
            
            if result.empty:
                return {'error': 'No data in registry'}
            
            summary = result.iloc[0].to_dict()
            
            # Get season breakdown with processor info
            season_query = f"""
            SELECT 
                season,
                COUNT(*) as records,
                COUNT(DISTINCT player_lookup) as players,
                COUNT(DISTINCT team_abbr) as teams,
                COUNT(DISTINCT last_processor) as processors_used,
                COUNTIF(last_processor = 'gamebook') as gamebook_records,
                COUNTIF(last_processor = 'roster') as roster_records
            FROM `{self.project_id}.{self.table_name}`
            GROUP BY season
            ORDER BY season DESC
            """
            
            seasons = self.bq_client.query(season_query).to_dataframe()
            summary['seasons_breakdown'] = seasons.to_dict('records')
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting registry summary: {e}")
            try:
                notify_error(
                    title="Registry Summary Query Failed",
                    message="Unable to retrieve registry statistics",
                    details={
                        'table_name': self.table_name,
                        'error': str(e),
                        'error_type': type(e).__name__
                    },
                    processor_name="Registry Processor Base"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return {'error': str(e)}
    
    def build_registry_for_season(self, season: str, team: str = None) -> Dict:
        """
        Build registry for a specific season.
        
        Args:
            season: NBA season string (e.g., '2024-25')
            team: Optional team filter
        """
        logger.info(f"Building registry for season {season}" + (f", team {team}" if team else ""))
        
        # Continue with season building - no conflict prevention
        return self._build_registry_for_season_impl(season, team)
    
    def _build_registry_for_season_impl(self, season: str, team: str = None) -> Dict:
        """Implementation of season building (to be overridden by subclasses)."""
        raise NotImplementedError("Subclasses must implement _build_registry_for_season_impl")
    
    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """Build registry from historical data (implementation varies by processor)."""
        raise NotImplementedError("Subclasses must implement build_historical_registry")