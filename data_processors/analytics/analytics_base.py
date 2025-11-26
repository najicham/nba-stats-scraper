"""
Path: analytics_processors/analytics_base.py

Base class for Phase 3 analytics processors that handles:
 - Dependency checking (upstream Phase 2 data validation)
 - Source metadata tracking (audit trail per v4.0 guide)
 - Querying raw BigQuery tables
 - Calculating analytics metrics
 - Loading to analytics tables
 - Error handling and quality tracking
 - Multi-channel notifications (Email + Slack)

Version: 2.0 (with dependency tracking)
Updated: January 2025
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from google.cloud import pubsub_v1
import sentry_sdk

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("analytics_base")


class AnalyticsProcessorBase:
    """
    Base class for Phase 3 analytics processors with full dependency tracking.
    
    Phase 3 processors depend on Phase 2 (Raw) tables.
    This base class provides dependency checking, source tracking, and validation.
    
    Lifecycle:
      1) Check dependencies (are upstream Phase 2 tables ready?)
      2) Extract data from raw BigQuery tables
      3) Validate extracted data
      4) Calculate analytics
      5) Load to analytics BigQuery tables
      6) Log processing run with source metadata
    """
    
    # Class-level configs
    required_opts: List[str] = ['start_date', 'end_date']
    additional_opts: List[str] = []
    
    # Processing settings
    validate_on_extract: bool = True
    save_on_error: bool = True
    
    # BigQuery settings
    dataset_id: str = "nba_analytics"
    table_name: str = ""  # Child classes must set
    processing_strategy: str = "MERGE_UPDATE"  # Default for analytics
    
    # Time tracking
    time_markers: Dict = {}
    
    def __init__(self):
        """Initialize analytics processor."""
        self.opts = {}
        self.raw_data = None
        self.validated_data = {}
        self.transformed_data = {}
        self.stats = {}
        
        # Source metadata tracking (populated by track_source_usage)
        self.source_metadata = {}
        
        # Quality issue tracking
        self.quality_issues = []
        
        # Generate run_id
        self.run_id = str(uuid.uuid4())[:8]
        self.stats["run_id"] = self.run_id
        
        # GCP clients
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - returns True on success, False on failure.
        """
        if opts is None:
            opts = {}
            
        try:
            # Re-init but preserve run_id
            saved_run_id = self.run_id
            self.__init__()
            self.run_id = saved_run_id
            self.stats["run_id"] = saved_run_id
            
            self.mark_time("total")
            self.step_info("start", "Analytics processor run starting", extra={"opts": opts})
            
            # Setup
            self.set_opts(opts)
            self.validate_opts()
            self.set_additional_opts()
            self.validate_additional_opts()
            self.init_clients()
            
            # Check dependencies BEFORE extracting (if processor defines them)
            if hasattr(self, 'get_dependencies') and callable(self.get_dependencies):
                self.mark_time("dependency_check")
                dep_check = self.check_dependencies(
                    self.opts['start_date'], 
                    self.opts['end_date']
                )
                dep_check_seconds = self.get_elapsed_seconds("dependency_check")
                self.stats["dependency_check_time"] = dep_check_seconds
                
                # Handle critical dependency failures
                if not dep_check['all_critical_present']:
                    error_msg = f"Missing critical dependencies: {dep_check['missing']}"
                    logger.error(error_msg)
                    notify_error(
                        title=f"Analytics Processor: Missing Dependencies - {self.__class__.__name__}",
                        message=error_msg,
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                            'missing': dep_check['missing'],
                            'stale_fail': dep_check.get('stale_fail', []),
                            'dependency_details': dep_check['details']
                        },
                        processor_name=self.__class__.__name__
                    )
                    raise ValueError(error_msg)
                
                # Handle stale data FAIL threshold
                if dep_check.get('has_stale_fail'):
                    error_msg = f"Stale dependencies (FAIL threshold): {dep_check['stale_fail']}"
                    notify_error(
                        title=f"Analytics Processor: Stale Data - {self.__class__.__name__}",
                        message=error_msg,
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                            'stale_sources': dep_check['stale_fail']
                        },
                        processor_name=self.__class__.__name__
                    )
                    raise ValueError(error_msg)
                
                # Warn about stale data (WARN threshold only)
                if dep_check.get('has_stale_warn'):
                    logger.warning(f"Stale upstream data detected: {dep_check['stale_warn']}")
                    notify_warning(
                        title=f"Analytics Processor: Stale Data Warning - {self.__class__.__name__}",
                        message=f"Some sources are stale: {dep_check['stale_warn']}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                            'stale_sources': dep_check['stale_warn']
                        }
                    )
                
                # Track source metadata from dependency check
                self.track_source_usage(dep_check)
                
                self.step_info("dependency_check_complete", 
                              f"Dependencies validated in {dep_check_seconds:.1f}s")
            else:
                logger.info("No dependency checking configured for this processor")
            
            # Extract from raw tables
            self.mark_time("extract")
            self.extract_raw_data()
            extract_seconds = self.get_elapsed_seconds("extract")
            self.stats["extract_time"] = extract_seconds
            self.step_info("extract_complete", f"Data extracted in {extract_seconds:.1f}s")
            
            # Validate
            if self.validate_on_extract:
                self.validate_extracted_data()
            
            # Transform/calculate analytics
            self.mark_time("transform")
            self.calculate_analytics()
            transform_seconds = self.get_elapsed_seconds("transform")
            self.stats["transform_time"] = transform_seconds
            
            # Save to analytics tables
            self.mark_time("save")
            self.save_analytics()
            save_seconds = self.get_elapsed_seconds("save")
            self.stats["save_time"] = save_seconds
            
            # Complete
            total_seconds = self.get_elapsed_seconds("total")
            self.stats["total_runtime"] = total_seconds
            self.step_info("finish", 
                          f"Analytics processor completed in {total_seconds:.1f}s")
            
            # Log processing run
            self.log_processing_run(success=True)
            self.post_process()
            return True
            
        except Exception as e:
            logger.error("AnalyticsProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)
            
            # Send notification for failure
            try:
                notify_error(
                    title=f"Analytics Processor Failed: {self.__class__.__name__}",
                    message=f"Analytics calculation failed: {str(e)}",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'error_type': type(e).__name__,
                        'step': self._get_current_step(),
                        'date_range': f"{opts.get('start_date')} to {opts.get('end_date')}",
                        'table': self.table_name,
                        'stats': self.stats
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))

            # Publish failure message (if target table is set)
            if self.table_name:
                self._publish_completion_message(success=False, error=str(e))

            if self.save_on_error:
                self._save_partial_data(e)

            self.report_error(e)
            return False
        
        finally:
            # Always run finalize, even on error
            try:
                self.finalize()
            except Exception as finalize_ex:
                logger.warning(f"Error in finalize(): {finalize_ex}")

    def finalize(self) -> None:
        """
        Cleanup hook that runs regardless of success/failure.
        Child classes override this for cleanup operations.
        Base implementation does nothing.
        """
        pass
    
    def _get_current_step(self) -> str:
        """Helper to determine current processing step for error context."""
        if not self.bq_client:
            return "initialization"
        elif not self.raw_data:
            return "extract"
        elif not self.transformed_data:
            return "calculate"
        else:
            return "save"
    
    # =========================================================================
    # Dependency Checking System (Phase 3 - Date Range Pattern)
    # =========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define required upstream Phase 2 tables and their constraints.
        Child classes can optionally implement this.
        
        Returns:
            dict: {
                'table_name': {
                    'field_prefix': str,          # Prefix for source tracking fields
                    'description': str,           # Human-readable description
                    'date_field': str,            # Field to check for date
                    'check_type': str,            # 'date_range', 'existence'
                    'expected_count_min': int,    # Minimum acceptable rows
                    'max_age_hours_warn': int,    # Warning threshold (hours)
                    'max_age_hours_fail': int,    # Failure threshold (hours)
                    'critical': bool              # Fail if missing?
                }
            }
        
        Example:
            return {
                'nba_raw.nbac_team_boxscore': {
                    'field_prefix': 'source_nbac_boxscore',
                    'description': 'Team box score statistics',
                    'date_field': 'game_date',
                    'check_type': 'date_range',
                    'expected_count_min': 20,  # ~10 games × 2 teams
                    'max_age_hours_warn': 24,
                    'max_age_hours_fail': 72,
                    'critical': True
                }
            }
        """
        # Default: no dependencies (for backwards compatibility)
        return {}
    
    def check_dependencies(self, start_date: str, end_date: str) -> dict:
        """
        Check if required upstream Phase 2 data exists and is fresh enough.
        
        Adapted from PrecomputeProcessorBase for Phase 3 date range pattern.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            dict: {
                'all_critical_present': bool,
                'all_fresh': bool,
                'has_stale_fail': bool,
                'has_stale_warn': bool,
                'missing': List[str],
                'stale_fail': List[str],
                'stale_warn': List[str],
                'details': Dict[str, Dict]
            }
        """
        dependencies = self.get_dependencies()
        
        # If no dependencies defined, return success
        if not dependencies:
            return {
                'all_critical_present': True,
                'all_fresh': True,
                'has_stale_fail': False,
                'has_stale_warn': False,
                'missing': [],
                'stale_fail': [],
                'stale_warn': [],
                'details': {}
            }
        
        results = {
            'all_critical_present': True,
            'all_fresh': True,
            'has_stale_fail': False,
            'has_stale_warn': False,
            'missing': [],
            'stale_fail': [],
            'stale_warn': [],
            'details': {}
        }
        
        for table_name, config in dependencies.items():
            logger.info(f"Checking dependency: {table_name}")
            
            # Check existence and metadata
            exists, details = self._check_table_data(
                table_name=table_name,
                start_date=start_date,
                end_date=end_date,
                config=config
            )
            
            # Check if missing
            if not exists:
                if config.get('critical', True):
                    results['all_critical_present'] = False
                    results['missing'].append(table_name)
                    logger.error(f"Missing critical dependency: {table_name}")
                else:
                    logger.warning(f"Missing optional dependency: {table_name}")
            
            # Check freshness (if exists)
            if exists and details.get('age_hours') is not None:
                max_age_warn = config.get('max_age_hours_warn', 24)
                max_age_fail = config.get('max_age_hours_fail', 72)
                
                if details['age_hours'] > max_age_fail:
                    results['all_fresh'] = False
                    results['has_stale_fail'] = True
                    stale_msg = (f"{table_name}: {details['age_hours']:.1f}h old "
                               f"(max: {max_age_fail}h)")
                    results['stale_fail'].append(stale_msg)
                    logger.error(f"Stale dependency (FAIL threshold): {stale_msg}")
                    
                elif details['age_hours'] > max_age_warn:
                    results['has_stale_warn'] = True
                    stale_msg = (f"{table_name}: {details['age_hours']:.1f}h old "
                               f"(warn: {max_age_warn}h)")
                    results['stale_warn'].append(stale_msg)
                    logger.warning(f"Stale dependency (WARN threshold): {stale_msg}")
            
            results['details'][table_name] = details
        
        logger.info(f"Dependency check complete: "
                   f"critical_present={results['all_critical_present']}, "
                   f"fresh={results['all_fresh']}")
        
        return results
    
    def _check_table_data(self, table_name: str, start_date: str, end_date: str,
                          config: dict) -> tuple:
        """
        Check if table has data for the given date range.

        Adapted from PrecomputeProcessorBase for Phase 3 date ranges.
        Enhanced with data_hash tracking for smart idempotency integration.

        Returns:
            (exists: bool, details: dict)
        """
        check_type = config.get('check_type', 'date_range')
        date_field = config.get('date_field', 'game_date')

        try:
            # Check if source table has data_hash column (Phase 2 smart idempotency)
            hash_field = "data_hash"  # Standard field name from SmartIdempotencyMixin

            if check_type == 'date_range':
                # Check for records in date range (most common for Phase 3)
                # Include data_hash if available (for smart idempotency tracking)
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'
                """

            elif check_type == 'existence':
                # Just check if any data exists (for reference tables)
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                LIMIT 1
                """

            else:
                raise ValueError(f"Unknown check_type: {check_type}")

            # Execute query
            result = list(self.bq_client.query(query).result())

            if not result:
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'age_hours': None,
                    'last_updated': None,
                    'data_hash': None,
                    'error': 'No query results'
                }

            row = result[0]
            row_count = row.row_count
            last_updated = row.last_updated
            data_hash = row.representative_hash if hasattr(row, 'representative_hash') else None

            # Calculate age
            if last_updated:
                # Handle both timezone-aware and naive datetimes
                now_utc = datetime.now(timezone.utc)
                if last_updated.tzinfo is None:
                    # If last_updated is naive, assume UTC
                    age_hours = (now_utc.replace(tzinfo=None) - last_updated).total_seconds() / 3600
                else:
                    # Both are timezone-aware
                    age_hours = (now_utc - last_updated).total_seconds() / 3600
            else:
                age_hours = None

            # Determine if exists based on minimum count
            expected_min = config.get('expected_count_min', 1)
            exists = row_count >= expected_min

            details = {
                'exists': exists,
                'row_count': row_count,
                'expected_count_min': expected_min,
                'age_hours': round(age_hours, 2) if age_hours else None,
                'last_updated': last_updated.isoformat() if last_updated else None,
                'data_hash': data_hash  # NEW: Representative hash from source data
            }

            logger.debug(f"{table_name}: {details}")

            return exists, details

        except Exception as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {
                'exists': False,
                'data_hash': None,
                'error': error_msg
            }
    
    def track_source_usage(self, dep_check: dict) -> None:
        """
        Record what sources were used during processing.
        Populates source_metadata dict AND per-source attributes.

        Enhanced to include data_hash tracking for smart idempotency integration.
        Copied from PrecomputeProcessorBase with Phase 3 adaptations.
        """
        self.source_metadata = {}

        for table_name, dep_result in dep_check['details'].items():
            config = self.get_dependencies()[table_name]
            prefix = config['field_prefix']

            if not dep_result.get('exists', False):
                # Source missing - use NULL for all fields (including hash)
                setattr(self, f'{prefix}_last_updated', None)
                setattr(self, f'{prefix}_rows_found', None)
                setattr(self, f'{prefix}_completeness_pct', None)
                setattr(self, f'{prefix}_hash', None)  # NEW: Hash tracking
                continue

            # Source exists - store raw values
            row_count = dep_result.get('row_count', 0)
            expected = dep_result.get('expected_count_min', 1)
            data_hash = dep_result.get('data_hash')  # NEW: Extract hash from dependency check

            # Calculate completeness
            if expected > 0:
                completeness_pct = (row_count / expected) * 100
                completeness_pct = min(completeness_pct, 100.0)  # Cap at 100%
            else:
                completeness_pct = 100.0

            # Store in metadata dict
            self.source_metadata[table_name] = {
                'last_updated': dep_result.get('last_updated'),
                'rows_found': row_count,
                'rows_expected': expected,
                'completeness_pct': round(completeness_pct, 2),
                'age_hours': dep_result.get('age_hours'),
                'data_hash': data_hash  # NEW: Include hash in metadata
            }

            # Store as attributes for easy access (4 fields per source now)
            setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
            setattr(self, f'{prefix}_rows_found', row_count)
            setattr(self, f'{prefix}_completeness_pct', round(completeness_pct, 2))
            setattr(self, f'{prefix}_hash', data_hash)  # NEW: Store hash attribute

        logger.info(f"Source tracking complete: {len(self.source_metadata)} sources tracked")
    
    def build_source_tracking_fields(self) -> dict:
        """
        Build dict of all source tracking fields for output records.

        Enhanced to include data_hash tracking for smart idempotency integration.
        Copied from PrecomputeProcessorBase.

        Returns:
            dict: All source tracking fields ready to merge into record (4 fields per source)
        """
        fields = {}

        # Only build if processor has dependencies
        if not hasattr(self, 'get_dependencies'):
            return fields

        # Per-source fields (4 fields per source: last_updated, rows_found, completeness_pct, hash)
        for table_name, config in self.get_dependencies().items():
            prefix = config['field_prefix']
            fields[f'{prefix}_last_updated'] = getattr(self, f'{prefix}_last_updated', None)
            fields[f'{prefix}_rows_found'] = getattr(self, f'{prefix}_rows_found', None)
            fields[f'{prefix}_completeness_pct'] = getattr(self, f'{prefix}_completeness_pct', None)
            fields[f'{prefix}_hash'] = getattr(self, f'{prefix}_hash', None)  # NEW: Hash field

        return fields

    def get_previous_source_hashes(self, game_date: str, game_id: str = None) -> Dict[str, Optional[str]]:
        """
        Get previous source hashes from BigQuery for smart reprocessing.

        Queries the Phase 3 table to find the most recent hash values for each
        source that was used in previous processing. This enables smart reprocessing
        by comparing current Phase 2 hashes with previous values.

        Args:
            game_date: Game date to query (YYYY-MM-DD)
            game_id: Optional game ID for more specific lookup

        Returns:
            Dict mapping source prefix to hash value:
            {
                'source_gamebook_hash': 'a3f5c2...',
                'source_boxscore_hash': 'b7e2d9...',
                ...
            }
            Returns empty dict if no previous data found or on error.

        Example:
            previous_hashes = processor.get_previous_source_hashes('2024-11-20', '0022400089')
            if previous_hashes.get('source_gamebook_hash') == current_hash:
                logger.info("Source unchanged, can skip processing")
        """
        if not hasattr(self, 'table_name') or not self.table_name:
            logger.warning("table_name not set - cannot get previous hashes")
            return {}

        dependencies = self.get_dependencies()
        if not dependencies:
            logger.debug("No dependencies defined - no previous hashes to check")
            return {}

        # Build WHERE clause
        where_clause = f"game_date = '{game_date}'"
        if game_id:
            where_clause += f" AND game_id = '{game_id}'"

        # Build SELECT for all hash fields
        hash_fields = []
        for table_name, config in dependencies.items():
            prefix = config['field_prefix']
            hash_fields.append(f'{prefix}_hash')

        if not hash_fields:
            return {}

        query = f"""
        SELECT {', '.join(hash_fields)}
        FROM `{self.project_id}.{self.dataset_id}.{self.table_name}`
        WHERE {where_clause}
        ORDER BY processed_at DESC
        LIMIT 1
        """

        try:
            result = self.bq_client.query(query).result()
            for row in result:
                # Convert row to dict
                hashes = {}
                for field in hash_fields:
                    hashes[field] = row.get(field)
                return hashes

            # No previous data found
            logger.debug(f"No previous data found for {game_date} {game_id or ''}")
            return {}

        except Exception as e:
            logger.warning(f"Error querying previous hashes: {e}")
            return {}

    def should_skip_processing(self, game_date: str, game_id: str = None,
                               check_all_sources: bool = False) -> tuple[bool, str]:
        """
        Determine if processing can be skipped based on source hash comparison.

        Implements smart reprocessing pattern: skip Phase 3 processing if Phase 2
        source data hashes are unchanged from previous run. This is the Phase 3
        equivalent of Phase 2's smart idempotency pattern.

        Args:
            game_date: Game date being processed
            game_id: Optional game ID for more specific matching
            check_all_sources: If True, ALL sources must be unchanged to skip.
                             If False, only check primary (first) source.

        Returns:
            Tuple of (should_skip: bool, reason: str)
            - (True, "All sources unchanged") - can skip processing
            - (False, "Source X changed") - must process
            - (False, "No previous data") - first time processing

        Example:
            skip, reason = processor.should_skip_processing('2024-11-20', '0022400089')
            if skip:
                logger.info(f"Skipping processing: {reason}")
                return []  # Skip extract_raw_data
        """
        dependencies = self.get_dependencies()
        if not dependencies:
            return False, "No dependencies defined"

        # Get previous hashes from BigQuery
        previous_hashes = self.get_previous_source_hashes(game_date, game_id)
        if not previous_hashes:
            return False, "No previous data (first time processing)"

        # Get current hashes from dependency check (already tracked)
        current_hashes = {}
        for table_name, config in dependencies.items():
            prefix = config['field_prefix']
            hash_attr = f'{prefix}_hash'
            current_hash = getattr(self, hash_attr, None)
            if current_hash:
                current_hashes[hash_attr] = current_hash

        if not current_hashes:
            return False, "No current hashes available"

        # Determine which sources to check
        if check_all_sources:
            sources_to_check = list(dependencies.keys())
        else:
            # Check only primary (first) source
            sources_to_check = [list(dependencies.keys())[0]]

        # Compare hashes
        changed_sources = []
        unchanged_sources = []

        for table_name in sources_to_check:
            config = dependencies[table_name]
            prefix = config['field_prefix']
            hash_field = f'{prefix}_hash'

            previous_hash = previous_hashes.get(hash_field)
            current_hash = current_hashes.get(hash_field)

            if previous_hash is None or current_hash is None:
                changed_sources.append(f"{table_name} (new/missing)")
                continue

            if previous_hash != current_hash:
                changed_sources.append(f"{table_name} (hash changed)")
                logger.debug(f"{table_name} hash changed: {previous_hash[:8]}... -> {current_hash[:8]}...")
            else:
                unchanged_sources.append(table_name)
                logger.debug(f"{table_name} hash unchanged: {current_hash[:8]}...")

        # Decision
        if changed_sources:
            reason = f"Sources changed: {', '.join(changed_sources)}"
            return False, reason
        else:
            reason = f"All {len(unchanged_sources)} source(s) unchanged"
            return True, reason

    def find_backfill_candidates(self, lookback_days: int = 30,
                                 primary_source_only: bool = True) -> List[Dict]:
        """
        Find games that have Phase 2 data but are missing Phase 3 analytics.

        Implements historical backfill awareness pattern from dependency docs.
        This enables Phase 3 to detect and process historical games that were
        backfilled in Phase 2 after the normal processing window.

        Args:
            lookback_days: How many days to look back (default: 30)
            primary_source_only: Only check primary source table (default: True)

        Returns:
            List[Dict]: Each dict contains:
                {
                    'game_date': str (YYYY-MM-DD),
                    'game_id': str,
                    'phase2_last_updated': str (ISO timestamp),
                    'phase2_row_count': int
                }

        Example:
            # Find games needing processing
            candidates = processor.find_backfill_candidates(lookback_days=7)
            for game in candidates:
                logger.info(f"Backfill needed: {game['game_date']} - {game['game_id']}")
                processor.run({
                    'start_date': game['game_date'],
                    'end_date': game['game_date']
                })
        """
        if not hasattr(self, 'table_name') or not self.table_name:
            logger.warning("table_name not set - cannot find backfill candidates")
            return []

        dependencies = self.get_dependencies()
        if not dependencies:
            logger.warning("No dependencies defined - cannot find backfill candidates")
            return []

        # Use first dependency as primary source (typically the critical one)
        if primary_source_only:
            primary_table = list(dependencies.keys())[0]
            source_tables = [primary_table]
        else:
            # Check all critical dependencies
            source_tables = [
                table for table, config in dependencies.items()
                if config.get('critical', True)
            ]

        if not source_tables:
            logger.warning("No source tables to check for backfill")
            return []

        # Build queries to find games with Phase 2 data but no Phase 3 data
        # NOTE: Using two separate queries to avoid cross-region JOIN issues
        #       (nba_raw may be in different region than nba_analytics)
        source_table = source_tables[0]
        source_config = dependencies[source_table]
        date_field = source_config.get('date_field', 'game_date')

        phase3_table = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        try:
            logger.info(f"Searching for backfill candidates (last {lookback_days} days)...")

            # Query 1: Get all Phase 2 games in date range
            phase2_query = f"""
            SELECT DISTINCT
                {date_field} as game_date,
                game_id,
                MAX(processed_at) as phase2_last_updated,
                COUNT(*) as phase2_row_count
            FROM `{self.project_id}.{source_table}`
            WHERE {date_field} >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
                AND {date_field} < CURRENT_DATE()
            GROUP BY game_date, game_id
            """

            phase2_games = {}
            for row in self.bq_client.query(phase2_query).result():
                key = f"{row.game_date}_{row.game_id}"
                phase2_games[key] = {
                    'game_date': row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date),
                    'game_id': row.game_id,
                    'phase2_last_updated': row.phase2_last_updated.isoformat() if row.phase2_last_updated else None,
                    'phase2_row_count': row.phase2_row_count
                }

            if not phase2_games:
                logger.info("No Phase 2 games found in date range")
                return []

            # Query 2: Get all Phase 3 games in same date range
            phase3_query = f"""
            SELECT DISTINCT
                game_date,
                game_id
            FROM `{phase3_table}`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
                AND game_date < CURRENT_DATE()
            """

            phase3_games = set()
            for row in self.bq_client.query(phase3_query).result():
                game_date = row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date)
                key = f"{game_date}_{row.game_id}"
                phase3_games.add(key)

            # Find games in Phase 2 but not in Phase 3
            candidates = []
            for key, game_info in phase2_games.items():
                if key not in phase3_games:
                    candidates.append(game_info)

            # Sort by game_date ascending (oldest first)
            candidates.sort(key=lambda x: x['game_date'])

            if candidates:
                logger.info(f"Found {len(candidates)} games needing backfill processing")
                # Log first few for visibility
                for candidate in candidates[:5]:
                    logger.info(f"  - {candidate['game_date']}: {candidate['game_id']} "
                              f"({candidate['phase2_row_count']} Phase 2 records)")
                if len(candidates) > 5:
                    logger.info(f"  ... and {len(candidates) - 5} more games")
            else:
                logger.info("No backfill candidates found - all games processed")

            return candidates

        except Exception as e:
            logger.error(f"Error finding backfill candidates: {e}")
            return []

    # =========================================================================
    # Options Management
    # =========================================================================
    
    def set_opts(self, opts: Dict) -> None:
        """Set options."""
        self.opts = opts
        self.opts["run_id"] = self.run_id
        
    def validate_opts(self) -> None:
        """Validate required options."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                error_msg = f"Missing required option [{required_opt}]"
                
                try:
                    notify_error(
                        title=f"Analytics Processor Configuration Error: {self.__class__.__name__}",
                        message=f"Missing required option: {required_opt}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'missing_option': required_opt,
                            'required_opts': self.required_opts,
                            'provided_opts': list(self.opts.keys())
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(error_msg)
    
    def set_additional_opts(self) -> None:
        """Add additional options - child classes override and call super()."""
        if "timestamp" not in self.opts:
            self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    def validate_additional_opts(self) -> None:
        """Validate additional options - child classes override."""
        pass
    
    def init_clients(self) -> None:
        """Initialize GCP clients with error notification."""
        try:
            self.project_id = self.opts.get("project_id", "nba-props-platform")
            self.bq_client = bigquery.Client(project=self.project_id)
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            try:
                notify_error(
                    title=f"Analytics Processor Client Initialization Failed: {self.__class__.__name__}",
                    message="Unable to initialize BigQuery client",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'project_id': self.opts.get('project_id', 'nba-props-platform'),
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    # =========================================================================
    # Abstract Methods (Child Classes Must Implement)
    # =========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract data from raw BigQuery tables.
        Child classes must implement.
        
        Note: Dependency checking happens BEFORE this is called.
        """
        raise NotImplementedError("Child classes must implement extract_raw_data()")
    
    def validate_extracted_data(self) -> None:
        """Validate extracted data - child classes override."""
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            try:
                notify_warning(
                    title=f"Analytics Processor No Data Extracted: {self.__class__.__name__}",
                    message="No data extracted from raw tables",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError("No data extracted")
    
    def calculate_analytics(self) -> None:
        """
        Calculate analytics metrics and include source metadata.
        Child classes must implement.
        
        Should populate self.transformed_data with records that include:
        - Business logic fields
        - Source tracking fields (via **self.build_source_tracking_fields())
        """
        raise NotImplementedError("Child classes must implement calculate_analytics()")
    
    # =========================================================================
    # Save to BigQuery
    # =========================================================================
    
    def save_analytics(self) -> None:
        """
        Save to analytics BigQuery table using batch INSERT.
        Uses NDJSON load job with schema enforcement.
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            try:
                notify_warning(
                    title=f"Analytics Processor No Data to Save: {self.__class__.__name__}",
                    message="No analytics data calculated to save",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_exists': self.raw_data is not None,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                notify_error(
                    title=f"Analytics Processor Data Type Error: {self.__class__.__name__}",
                    message=error_msg,
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'data_type': str(type(self.transformed_data)),
                        'expected_types': ['list', 'dict']
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError(error_msg)
        
        if not rows:
            logger.warning("No rows to insert")
            return
        
        # Apply processing strategy - delete existing data first
        if self.processing_strategy == 'MERGE_UPDATE':
            try:
                self._delete_existing_data_batch(rows)
            except Exception as e:
                if "streaming buffer" not in str(e).lower():
                    logger.error(f"Delete failed with non-streaming error: {e}")
                    raise
        
        # Use batch INSERT via BigQuery load job
        logger.info(f"Inserting {len(rows)} rows to {table_id} using batch INSERT")
        
        try:
            import io
            
            # Get target table schema
            try:
                table = self.bq_client.get_table(table_id)
                table_schema = table.schema
                logger.info(f"Using schema with {len(table_schema)} fields")
            except Exception as schema_e:
                logger.warning(f"Could not get table schema: {schema_e}")
                table_schema = None
            
            # Convert to NDJSON
            ndjson_data = "\n".join(json.dumps(row) for row in rows)
            ndjson_bytes = ndjson_data.encode('utf-8')
            
            # Configure load job
            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=False,
                schema_update_options=None
            )
            
            # Load to target table
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )
            
            # Wait for completion
            try:
                load_job.result()
                logger.info(f"✅ Successfully loaded {len(rows)} rows")
                self.stats["rows_processed"] = len(rows)
                
            except Exception as load_e:
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    self.stats["rows_processed"] = 0
                    return
                else:
                    raise load_e
            
        except Exception as e:
            error_msg = f"Batch insert failed: {str(e)}"
            logger.error(error_msg)
            try:
                notify_error(
                    title=f"Analytics Processor Batch Insert Failed: {self.__class__.__name__}",
                    message=f"Failed to batch insert {len(rows)} analytics rows",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def _delete_existing_data_batch(self, rows: List[Dict]) -> None:
        """Delete existing data using batch DELETE query."""
        if not rows:
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Get date range from opts
        start_date = self.opts.get('start_date')
        end_date = self.opts.get('end_date')
        
        if start_date and end_date:
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            """
            
            logger.info(f"Deleting existing data for {start_date} to {end_date}")
            
            try:
                delete_job = self.bq_client.query(delete_query)
                delete_job.result()
                
                if delete_job.num_dml_affected_rows is not None:
                    logger.info(f"✅ Deleted {delete_job.num_dml_affected_rows} existing rows")
                else:
                    logger.info(f"✅ Delete completed for date range")
                    
            except Exception as e:
                if "streaming buffer" in str(e).lower():
                    logger.warning("⚠️ Delete blocked by streaming buffer")
                    logger.info("Duplicates will be cleaned up on next run")
                    return
                else:
                    raise e
    
    # =========================================================================
    # Quality Tracking
    # =========================================================================
    
    def log_quality_issue(self, issue_type: str, severity: str, identifier: str, 
                         details: Dict):
        """
        Log data quality issues for review.
        Enhanced with notifications for high-severity issues.
        """
        issue_record = {
            'issue_id': str(uuid.uuid4()),
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'issue_type': issue_type,
            'severity': severity,
            'identifier': identifier,
            'issue_description': json.dumps(details),
            'resolved': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Track locally
        self.quality_issues.append(issue_record)
        
        try:
            table_id = f"{self.project_id}.nba_processing.analytics_data_issues"
            self.bq_client.insert_rows_json(table_id, [issue_record])
            
            # Send notification for high-severity issues
            if severity in ['CRITICAL', 'HIGH']:
                try:
                    notify_func = notify_error if severity == 'CRITICAL' else notify_warning
                    notify_func(
                        title=f"Analytics Data Quality Issue: {self.__class__.__name__}",
                        message=f"{severity} severity {issue_type} detected for {identifier}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'issue_type': issue_type,
                            'severity': severity,
                            'identifier': identifier,
                            'issue_details': details,
                            'table': self.table_name
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
        except Exception as e:
            logger.warning(f"Failed to log quality issue: {e}")
    
    # =========================================================================
    # Logging & Monitoring
    # =========================================================================
    
    def log_processing_run(self, success: bool, error: str = None) -> None:
        """Log processing run to monitoring table."""
        run_record = {
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'run_date': datetime.now(timezone.utc).isoformat(),
            'success': success,
            'date_range_start': self.opts.get('start_date'),
            'date_range_end': self.opts.get('end_date'),
            'records_processed': self.stats.get('rows_processed', 0),
            'duration_seconds': self.stats.get('total_runtime', 0),
            'errors_json': json.dumps([error] if error else []),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            table_id = f"{self.project_id}.nba_processing.analytics_processor_runs"
            self.bq_client.insert_rows_json(table_id, [run_record])
        except Exception as e:
            logger.warning(f"Failed to log processing run: {e}")
    
    def post_process(self) -> None:
        """Post-processing - log summary stats and publish completion message."""
        summary = {
            "run_id": self.run_id,
            "processor": self.__class__.__name__,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_runtime": self.stats.get("total_runtime", 0),
        }

        # Merge analytics stats
        analytics_stats = self.get_analytics_stats()
        if isinstance(analytics_stats, dict):
            summary.update(analytics_stats)

        logger.info("ANALYTICS_STATS %s", json.dumps(summary))

        # Publish completion message to trigger Phase 4 (if target table is set)
        if self.table_name:
            self._publish_completion_message(success=True)
    
    def get_analytics_stats(self) -> Dict:
        """Get analytics stats - child classes override."""
        return {}

    def _publish_completion_message(self, success: bool, error: str = None) -> None:
        """
        Publish completion message to nba-phase3-analytics-complete topic.
        This triggers Phase 4 precompute processors that depend on this analytics table.

        Args:
            success: Whether processing completed successfully
            error: Optional error message if failed
        """
        try:
            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(self.project_id, 'nba-phase3-analytics-complete')

            # Get the analysis date (use end_date for single-date processing)
            analysis_date = self.opts.get('end_date')
            if isinstance(analysis_date, date):
                analysis_date = analysis_date.strftime('%Y-%m-%d')

            message_data = {
                'source_table': self.table_name,
                'analysis_date': str(analysis_date),
                'processor_name': self.__class__.__name__,
                'success': success,
                'run_id': self.run_id
            }

            if error:
                message_data['error'] = error

            # Publish message
            message_json = json.dumps(message_data)
            future = publisher.publish(topic_path, message_json.encode('utf-8'))
            message_id = future.result()  # Block until published

            logger.info(f"Published completion message to nba-phase3-analytics-complete (message_id: {message_id})")
            logger.debug(f"Message data: {message_json}")

        except Exception as e:
            logger.warning(f"Failed to publish completion message: {e}")
            # Don't fail the whole processor if Pub/Sub publishing fails
    
    # =========================================================================
    # Time Tracking
    # =========================================================================
    
    def mark_time(self, label: str) -> str:
        """Mark time."""
        now = datetime.now()
        if label not in self.time_markers:
            self.time_markers[label] = {
                "start": now,
                "last": now
            }
            return "0.0"
        else:
            last_time = self.time_markers[label]["last"]
            delta = (now - last_time).total_seconds()
            self.time_markers[label]["last"] = now
            return f"{delta:.1f}"
    
    def get_elapsed_seconds(self, label: str) -> float:
        """Get elapsed seconds."""
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()
    
    def step_info(self, step_name: str, message: str, extra: Optional[Dict] = None) -> None:
        """Log structured step."""
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"ANALYTICS_STEP {message}", extra=extra)
    
    # =========================================================================
    # Error Handling
    # =========================================================================
    
    def report_error(self, exc: Exception) -> None:
        """Report error to Sentry."""
        sentry_sdk.capture_exception(exc)
    
    def _save_partial_data(self, exc: Exception) -> None:
        """Save partial data on error for debugging."""
        try:
            debug_file = f"/tmp/analytics_debug_{self.run_id}.json"
            debug_data = {
                "error": str(exc),
                "opts": self.opts,
                "raw_data_sample": str(self.raw_data)[:1000] if self.raw_data is not None else None,
                "transformed_data_sample": str(self.transformed_data)[:1000] if self.transformed_data else None,
                "source_metadata": getattr(self, 'source_metadata', {})
            }
            with open(debug_file, "w") as f:
                json.dump(debug_data, f, indent=2)
            logger.info(f"Saved debug data to {debug_file}")
        except Exception as save_exc:
            logger.warning(f"Failed to save debug data: {save_exc}")