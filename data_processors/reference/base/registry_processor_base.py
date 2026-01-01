#!/usr/bin/env python3
"""
File: data_processors/reference/base/registry_processor_base.py

Base class for NBA registry processors.
Provides shared functionality for both gamebook and roster registry processors.
Enhanced with update source tracking, Universal Player ID integration, temporal ordering protection,
and data freshness validation.
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum
import pandas as pd
import numpy as np
import google
from google.cloud import bigquery

from data_processors.raw.processor_base import ProcessorBase
from shared.utils.player_registry import UniversalPlayerIDResolver
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class TemporalOrderingError(Exception):
    """Raised when attempting to process data out of temporal order."""
    pass


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
    - Temporal ordering protection
    - Data freshness validation
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
            self.run_history_table = f'nba_reference.processor_run_history_test_{timestamp_suffix}'
            self.processing_run_id += f"_TEST_{timestamp_suffix}"
            logger.info(f"Running in TEST MODE with fixed table suffix: {timestamp_suffix}")
        else:
            self.table_name = 'nba_reference.nba_players_registry'
            self.unresolved_table_name = 'nba_reference.unresolved_player_names'
            self.alias_table_name = 'nba_reference.player_aliases'
            self.run_history_table = 'nba_reference.processor_run_history'
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
        
        # Current run tracking for temporal ordering
        self.current_run_id = None
        self.current_season_year = None
        self.run_start_time = None  # Track in memory instead of DB
        self.run_metadata = {}  # Store metadata until completion
        
        logger.info(f"Initialized registry processor with run ID generation enabled")
    
    # =========================================================================
    # TEMPORAL ORDERING PROTECTION
    # =========================================================================
    
    def validate_temporal_ordering(self, data_date: date, season_year: int, 
                                   allow_backfill: bool = False) -> None:
        """
        Validate that we're not processing data out of temporal order.
        
        Prevents corruption by checking if we've already processed later dates
        for this season. If we have, and backfill mode is not enabled, raise an error.
        
        Args:
            data_date: The date of data being processed
            season_year: The season year (for season-aware validation)
            allow_backfill: If True, allow processing earlier dates (insert-only mode)
            
        Raises:
            TemporalOrderingError: If attempting to process earlier date after later date
        """
        if not self.processor_type:
            logger.warning("Processor type not set - skipping temporal validation")
            return
        
        # Query for latest processed date for this season (ANY status, including running)
        query = f"""
        SELECT 
            MAX(data_date) as latest_processed_date,
            MAX(started_at) as latest_run_time
        FROM `{self.project_id}.{self.run_history_table}`
        WHERE processor_name = @processor_name
        AND season_year = @season_year
        AND status IN ('success', 'running', 'partial')  -- ✅ Check any active runs
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("processor_name", "STRING", self.processor_type),
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty or pd.isna(results.iloc[0]['latest_processed_date']):
                logger.info(f"No prior successful runs found for {self.processor_type} season {season_year} - proceeding")
                return
            
            latest_processed_date = results.iloc[0]['latest_processed_date']
            
            # Convert to date if timestamp
            if isinstance(latest_processed_date, pd.Timestamp):
                latest_processed_date = latest_processed_date.date()
            
            # Check temporal ordering
            if data_date < latest_processed_date:
                if allow_backfill:
                    logger.warning(
                        f"⚠️ BACKFILL MODE: Processing {data_date} after {latest_processed_date} "
                        f"(insert-only, no updates)"
                    )
                    return
                else:
                    error_msg = (
                        f"Temporal ordering violation: Attempting to process {data_date} "
                        f"but already processed through {latest_processed_date} for season {season_year}. "
                        f"Use --allow-backfill flag to enable insert-only backfill mode."
                    )
                    logger.error(error_msg)
                    
                    try:
                        notify_error(
                            title="Temporal Ordering Violation",
                            message=f"Cannot process {data_date} - already processed {latest_processed_date}",
                            details={
                                'processor': self.processor_type,
                                'season_year': season_year,
                                'data_date': str(data_date),
                                'latest_processed_date': str(latest_processed_date),
                                'action_required': 'Use --allow-backfill flag if intentional'
                            },
                            processor_name=f"{self.processor_type.title()} Registry Processor"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
                    
                    raise TemporalOrderingError(error_msg)
            
            logger.info(f"✓ Temporal validation passed: {data_date} >= {latest_processed_date}")
            
        except google.cloud.exceptions.NotFound:
            # Table doesn't exist yet - first run
            logger.info(f"Run history table not found - first run, proceeding")
            return
        except TemporalOrderingError:
            raise
        except Exception as e:
            logger.warning(f"Error checking temporal ordering (proceeding anyway): {e}")
            # Don't block processing on validation errors
            return
    
    def record_run_complete(self, data_date: date, season_year: int, status: str, 
                   result: Dict = None, error: Exception = None,
                   data_source_primary: str = None,
                   data_source_enhancement: str = None,
                   validation_mode: str = None,
                   source_data_freshness_days: int = None,
                   backfill_mode: bool = False,
                   force_reprocess: bool = False) -> None:
        """
        Record completed processor run in single INSERT operation with source date tracking.
        
        This avoids BigQuery streaming buffer issues by only writing once at completion.
        
        Args:
            data_date: The date of data that was processed
            season_year: The season year processed
            status: Final status ('success', 'failed', 'partial')
            result: Processing result dictionary (if success/partial)
            error: Exception object (if failed)
            data_source_primary: Primary data source name
            data_source_enhancement: Enhancement data source name
            validation_mode: Validation mode ('full', 'partial', 'none')
            source_data_freshness_days: How stale source data is (in days)
            backfill_mode: Whether running in backfill mode
            force_reprocess: Whether forcing reprocessing
        """
        if not self.processor_type:
            logger.warning("Processor type not set - skipping run recording")
            return
        
        if not self.run_start_time:
            logger.warning("No run start time recorded - skipping run recording")
            return
        
        # Calculate duration
        processed_at = datetime.now(timezone.utc)
        duration_seconds = (processed_at - self.run_start_time).total_seconds()
        
        # Calculate season string
        season_str = self.calculate_season_string(season_year)
        
        # Get execution environment
        execution_host = os.environ.get('EXECUTION_HOST', 'local')
        triggered_by = os.environ.get('TRIGGERED_BY', 'manual')
        
        # Build errors JSON
        errors_json = None
        if error:
            errors_json = json.dumps([{
                'error_type': type(error).__name__,
                'error_message': str(error),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }])
        
        # Build summary JSON
        summary_json = None
        if result:
            summary_json = json.dumps(result, default=str)
        
        # Get source dates from tracking (if available)
        source_dates = getattr(self, 'source_dates_used', {})
        
        # Build complete record
        record = {
            'processor_name': self.processor_type,
            'run_id': self.current_run_id,
            'season_year': season_year,
            'status': status,
            'duration_seconds': duration_seconds,
            'records_processed': result.get('records_processed', 0) if result else 0,
            'records_created': result.get('records_created', 0) if result else 0,
            'records_updated': result.get('records_updated', 0) if result else 0,
            'records_skipped': result.get('records_skipped', 0) if result else 0,
            'data_source_primary': data_source_primary,
            'data_source_enhancement': data_source_enhancement,
            'data_records_queried': None,
            'validation_mode': validation_mode,
            'validation_skipped_reason': result.get('validation_skipped_reason') if result else None,
            'source_data_freshness_days': source_data_freshness_days,
            
            # NEW: Source date tracking
            'espn_roster_date': source_dates.get('espn_roster_date'),
            'nbacom_source_date': source_dates.get('nbacom_source_date'),
            'br_scrape_date': source_dates.get('br_scrape_date'),
            'gamebook_pdf_date': source_dates.get('gamebook_pdf_date'),
            'espn_matched_requested_date': source_dates.get('espn_matched'),
            'nbacom_matched_requested_date': source_dates.get('nbacom_matched'),
            'br_matched_requested_date': source_dates.get('br_matched'),
            'gamebook_matched_requested_date': source_dates.get('gamebook_matched'),
            'used_source_fallback': source_dates.get('used_fallback', False),
            
            'season_filter': season_str,
            'team_filter': None,
            'date_range_filter_start': None,
            'date_range_filter_end': None,
            'backfill_mode': True if backfill_mode else False,
            'force_reprocess': True if force_reprocess else False,
            'test_mode': True if self.test_mode else False,
            'execution_host': execution_host,
            'triggered_by': triggered_by,
            'errors': errors_json,
            'warnings': None,
            'summary': summary_json,
            'data_date': data_date,
            'started_at': self.run_start_time,
            'processed_at': processed_at
        }
        
        # Convert types for BigQuery
        converted_record = self._convert_pandas_types_for_json(record)
        
        # Single INSERT - no UPDATE, no streaming buffer issues
        table_id = f"{self.project_id}.{self.run_history_table}"

        try:
            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json([converted_record], table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
            else:
                logger.info(f"✓ Recorded run completion: {self.current_run_id} - {status} ({duration_seconds:.1f}s)")

            # Clear run tracking
            self.current_run_id = None
            self.current_season_year = None
            self.run_start_time = None
            self.run_metadata = {}

        except Exception as e:
            logger.warning(f"Failed to record run completion (non-fatal): {e}")
    
    # =========================================================================
    # DATA FRESHNESS PROTECTION
    # =========================================================================
    
    def get_existing_record(self, player_lookup: str, team_abbr: str, 
                           season: str) -> Optional[Dict]:
        """
        Get existing registry record for a player-team-season combination.
        
        Args:
            player_lookup: Normalized player name
            team_abbr: Team abbreviation
            season: Season string (e.g., '2024-25')
            
        Returns:
            Dictionary with existing record data or None if not found
        """
        query = f"""
        SELECT 
            player_lookup,
            team_abbr,
            season,
            games_played,
            last_game_date,
            last_processor,
            last_gamebook_activity_date,
            last_roster_activity_date,
            jersey_number,
            position,
            source_priority,
            processed_at
        FROM `{self.project_id}.{self.table_name}`
        WHERE player_lookup = @player_lookup
          AND team_abbr = @team_abbr
          AND season = @season
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                return None
            
            # Convert to dictionary
            record = results.iloc[0].to_dict()
            
            # Convert timestamps/dates to Python types
            for key, value in record.items():
                if pd.isna(value):
                    record[key] = None
                elif isinstance(value, pd.Timestamp):
                    record[key] = value.to_pydatetime()
                elif hasattr(value, 'date'):
                    record[key] = value.date()
            
            return record
            
        except Exception as e:
            logger.warning(f"Error fetching existing record for {player_lookup}: {e}")
            return None
    
    def should_update_record(self, existing_record: Optional[Dict], 
                            new_data_date: date, processor_type: str) -> Tuple[bool, str]:
        """
        Determine if we should update a record based on data freshness.
        
        This implements the core data protection logic:
        1. New records: Always allow
        2. Same processor with fresher data: Allow
        3. Same processor with stale data: Block
        4. Different processor: Check authority rules
        
        Args:
            existing_record: Existing record dict (or None if new record)
            new_data_date: Date of the data we want to write
            processor_type: 'gamebook' or 'roster'
            
        Returns:
            Tuple of (should_update: bool, reason: str)
        """
        if existing_record is None:
            # New record - always safe to write
            return True, "new_record"
        
        # Check activity date for this processor
        activity_field = f'last_{processor_type}_activity_date'
        existing_activity = existing_record.get(activity_field)
        
        if existing_activity is None:
            # This processor has never touched this record - safe to write
            return True, f"first_{processor_type}_activity"
        
        # Convert to date if timestamp
        if isinstance(existing_activity, datetime):
            existing_activity = existing_activity.date()
        
        # Freshness check
        if new_data_date > existing_activity:
            # Our data is fresher - allow update
            return True, f"fresher_data ({new_data_date} > {existing_activity})"
        
        elif new_data_date == existing_activity:
            # Same date - allow update (reprocessing same date)
            return True, f"same_date_reprocess ({new_data_date})"
        
        else:
            # Our data is staler - block update
            logger.warning(
                f"Blocking update for {existing_record['player_lookup']} on {existing_record['team_abbr']} - "
                f"existing {processor_type} data is fresher ({existing_activity} vs {new_data_date})"
            )
            return False, f"stale_data ({new_data_date} < {existing_activity})"
    
    def check_team_authority(self, existing_record: Optional[Dict], 
                            processor_type: str) -> Tuple[bool, str]:
        """
        Check if this processor has authority to update team_abbr field.
        
        Authority rules:
        1. Gamebook always has authority (verified via game participation)
        2. Roster has authority only if:
           - Record is new, OR
           - Record exists but has no games played (gamebook hasn't set team yet)
        
        Args:
            existing_record: Existing record dict (or None if new)
            processor_type: 'gamebook' or 'roster'
            
        Returns:
            Tuple of (has_authority: bool, reason: str)
        """
        if processor_type == 'gamebook':
            # Gamebook always has authority (verified via actual games)
            return True, "gamebook_authority"
        
        if processor_type == 'roster':
            if existing_record is None:
                # New record - roster can set initial team
                return True, "new_record"
            
            games_played = existing_record.get('games_played', 0)
            if games_played == 0:
                # No games played yet - roster can set/update team
                return True, "no_games_yet"
            else:
                # Games played - gamebook has set the team, roster shouldn't override
                logger.debug(
                    f"Roster processor does not have team authority for "
                    f"{existing_record['player_lookup']} - gamebook has set team "
                    f"({games_played} games played)"
                )
                return False, f"gamebook_owns_team ({games_played} games)"
        
        # Unknown processor type
        return False, "unknown_processor"
    
    def update_activity_date(self, record: Dict, processor_type: str, 
                            activity_date: date) -> Dict:
        """
        Update the activity date field for this processor.
        
        Args:
            record: Record dictionary to update
            processor_type: 'gamebook' or 'roster'
            activity_date: Date to set as activity date
            
        Returns:
            Updated record dictionary
        """
        activity_field = f'last_{processor_type}_activity_date'
        record[activity_field] = activity_date
        
        logger.debug(
            f"Updated {activity_field} to {activity_date} for "
            f"{record.get('player_lookup', 'unknown')}"
        )
        
        return record
    
    # =========================================================================
    # EXISTING METHODS (unchanged)
    # =========================================================================
    
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
                'roster_update_count', 'update_sequence_number', 'season_year', 
                'records_processed', 'records_created', 'records_updated', 'records_skipped',
                'data_records_queried', 'source_data_freshness_days'}
        
        # Define boolean fields that need explicit conversion
        boolean_fields = {'backfill_mode', 'force_reprocess', 'test_mode', 'is_active',
                 'espn_matched_requested_date', 'nbacom_matched_requested_date',
                 'br_matched_requested_date', 'gamebook_matched_requested_date',
                 'used_source_fallback'}
        
        # Define TIMESTAMP fields that need special handling
        timestamp_fields = {'created_at', 'processed_at', 'reviewed_at',
                        'last_gamebook_update', 'last_roster_update', 'started_at'}
        
        for key, value in record.items():
            # Handle lists/arrays FIRST (before pd.isna check)
            if isinstance(value, list):
                converted_record[key] = value
                continue
            
            # Handle NaN/None values first
            if pd.isna(value):
                converted_record[key] = None
            
            # Handle boolean fields explicitly for insert_rows_json
            elif key in boolean_fields:
                # Ensure we have actual Python bool, not numpy bool or int
                if value is None or pd.isna(value):
                    converted_record[key] = None
                else:
                    converted_record[key] = bool(value) if value else False
            
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