#!/usr/bin/env python3
# File: validation/base_validator.py
# Description: Universal Data Validation Framework - Base validator with config-driven validation logic
# Version: 2.0 - Improved with better error handling, caching, and partition filtering
"""
Universal Data Validation Framework
Base validator with config-driven validation logic

Improvements in v2.0:
- Fixed GCS path handling
- Consistent partition filtering across all queries
- Batch loading for BigQuery results
- Config validation on initialization
- Better error handling with retries
- Query result caching
- Improved remediation command generation
"""

import os
import sys
import yaml
import logging
import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from google.cloud import bigquery
from google.cloud import storage
from google.api_core import retry
from pathlib import Path
import time

# Notification system integration
from shared.utils.notification_system import notify_warning, notify_info, notify_error

# BigQuery batch writer for quota-efficient writes
from shared.utils.bigquery_batch_writer import get_batch_writer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Validation severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationStatus(Enum):
    """Overall validation status"""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


@dataclass
class ValidationResult:
    """Single validation check result"""
    check_name: str
    check_type: str  # "completeness", "team_presence", "field_validation", etc.
    layer: str  # "gcs", "bigquery", "schedule"
    passed: bool
    severity: str
    message: str
    affected_count: int = 0
    affected_items: List[Any] = None
    remediation: List[str] = None
    query_used: Optional[str] = None
    execution_duration: Optional[float] = None
    
    def __post_init__(self):
        if self.affected_items is None:
            self.affected_items = []
        if self.remediation is None:
            self.remediation = []


@dataclass
class ValidationReport:
    """Complete validation report for a processor"""
    processor_name: str
    processor_type: str
    validation_timestamp: str
    validation_run_id: str
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    season_year: Optional[int]
    total_checks: int
    passed_checks: int
    failed_checks: int
    overall_status: str
    results: List[ValidationResult]
    remediation_commands: List[str]
    summary: Dict[str, Any]
    execution_duration: float


class BaseValidator:
    """
    Base validator class for all processors.
    
    Usage:
        validator = ProcessorValidator('validation/configs/processor_name.yaml')
        report = validator.validate(start_date='2024-01-01', end_date='2024-01-31')
    
    Version 2.0 Improvements:
    - Better error handling with retries
    - Query result caching
    - Consistent partition filtering
    - Config validation
    - Batch BigQuery operations
    """
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_and_validate_config(config_path)
        
        self.processor_name = self.config['processor']['name']
        self.processor_type = self.config['processor'].get('type', 'raw')
        
        self.bq_client = bigquery.Client()
        self.gcs_client = storage.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        
        self.results: List[ValidationResult] = []
        self._query_cache: Dict[str, Any] = {}
        self._start_time: float = 0
        
        # Set up partition filtering if required
        self.partition_handler = self._init_partition_handler()
        
        logger.info(f"Initialized {self.processor_name} validator (type: {self.processor_type})")
    
    def _load_and_validate_config(self, config_path: str) -> Dict:
        """Load and validate configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            raise ValidationError(f"Config file not found: {config_path}")
        except yaml.YAMLError as e:
            raise ValidationError(f"Invalid YAML in config: {e}")
        
        # Validate required fields
        required_fields = ['processor']
        for field in required_fields:
            if field not in config:
                raise ValidationError(f"Config missing required field: {field}")
        
        processor_config = config['processor']
        required_processor_fields = ['name', 'description', 'table']
        for field in required_processor_fields:
            if field not in processor_config:
                raise ValidationError(f"Processor config missing required field: {field}")
        
        logger.info(f"Config validated: {processor_config['name']}")
        return config
    
    def _init_partition_handler(self):
        """Initialize partition filter handler if table requires it"""
        from validation.utils.partition_filter import PartitionFilterHandler
        
        processor_config = self.config.get('processor', {})
        partition_required = processor_config.get('partition_required', False)
        
        if not partition_required:
            return None
        
        table = processor_config.get('table')
        partition_field = processor_config.get('partition_field', 'game_date')
        
        logger.info(f"Table {table} requires partition filter on {partition_field}")
        
        return PartitionFilterHandler(
            table=table,
            partition_field=partition_field,
            required=True
        )
    
    @retry.Retry(predicate=retry.if_exception_type(Exception), initial=1.0, maximum=10.0, multiplier=2.0, deadline=60.0)
    def _execute_query(self, query: str, start_date: str = None, end_date: str = None, cache_key: str = None):
        """
        Execute query with automatic partition filtering and caching.
        
        Args:
            query: SQL query to execute
            start_date: Start date for partition filter (if needed)
            end_date: End date for partition filter (if needed)
            cache_key: Optional cache key to avoid re-running identical queries
        
        Returns:
            Query results
        """
        # Check cache first
        if cache_key and cache_key in self._query_cache:
            logger.debug(f"Using cached result for: {cache_key}")
            return self._query_cache[cache_key]
        
        # Apply partition filter if handler exists
        if self.partition_handler and start_date and end_date:
            query = self.partition_handler.ensure_partition_filter(query, start_date, end_date)
        
        try:
            result = self.bq_client.query(query).result(timeout=60)
            
            # Cache if key provided
            if cache_key:
                # Convert to list to cache (can't cache iterator)
                result_list = list(result)
                self._query_cache[cache_key] = result_list
                return result_list
            
            return result
            
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            logger.error(f"Query: {query[:500]}...")
            raise
    
    # ========================================================================
    # Main Validation Entry Point
    # ========================================================================
    
    def validate(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        season_year: Optional[int] = None,
        notify: bool = True,
        output_mode: str = 'summary',
        output_file: Optional[str] = None,  # NEW: Add output_file parameter
        layers: Optional[List[str]] = None
    ) -> ValidationReport:
        """
        Run all validations for this processor

        Args:
            start_date: Start date (YYYY-MM-DD) or None for auto-detect
            end_date: End date (YYYY-MM-DD) or None for auto-detect
            season_year: Season year or None
            notify: Send notifications on failure
            output_mode: 'summary' (default), 'detailed', or 'quiet'
            layers: List of layers to validate ['gcs', 'bigquery'] or None for default

        Returns:
            ValidationReport with results
        """
        self._start_time = time.time()
        self.results = []
        self._query_cache = {}  # Reset cache for each run
        
        # Generate unique run ID
        run_id = f"{self.processor_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        # Auto-detect date range if not provided
        # Auto-detect date range if not provided
        if not start_date or not end_date:
            start_date, end_date = self._auto_detect_date_range(season_year)
        
        # Store as instance variables for custom validators
        self.start_date = start_date
        self.end_date = end_date
        self.season_year = season_year
        
        logger.info("=" * 80)
        logger.info(f"Starting validation: {self.processor_name}")
        logger.info(f"Run ID: {run_id}")
        logger.info(f"Date range: {start_date} to {end_date}")
        if season_year:
            logger.info(f"Season: {season_year}-{season_year + 1}")
        logger.info("=" * 80)
        
        # Determine which layers to validate
        if layers is None:
            layers = self.config['processor'].get('layers', ['bigquery'])
        
        try:
            # Run validation layers
            if 'gcs' in layers and self.config.get('gcs_validations', {}).get('enabled'):
                self._validate_gcs_layer(start_date, end_date, season_year)
            
            if 'bigquery' in layers and self.config.get('bigquery_validations', {}).get('enabled'):
                self._validate_bigquery_layer(start_date, end_date, season_year)
            
            if 'schedule' in layers and self.config.get('schedule_validations', {}).get('enabled'):
                self._validate_schedule_layer(start_date, end_date)
            
            # Run custom validations (override in subclass)
            logger.info(f"DEBUG: About to call _run_custom_validations, layers={layers}")
            logger.info(f"DEBUG: Method exists? {hasattr(self, '_run_custom_validations')}")
            
            # Run custom validations (override in subclass)
            self._run_custom_validations(start_date, end_date, season_year)
            logger.info(f"DEBUG: Finished _run_custom_validations, results count: {len(self.results)}")
            
        except Exception as e:
            logger.error(f"Validation failed with error: {e}")
            # Add error result
            self.results.append(ValidationResult(
                check_name="validation_execution",
                check_type="system",
                layer="framework",
                passed=False,
                severity="critical",
                message=f"Validation execution failed: {str(e)}"
            ))
        
        # Generate report
        report = self._generate_report(run_id, start_date, end_date, season_year)
        
        # Print based on output mode
        if output_mode == 'summary':
            self._print_validation_summary(report)
        elif output_mode == 'detailed':
            self._print_detailed_report(report)
        elif output_mode == 'dates':
            # Special mode: output dates
            self._print_dates_only(report, output_file)  # Pass output_file
        elif output_mode == 'quiet':
            pass  # No console output
        else:
            # Default to summary for unknown modes
            self._print_validation_summary(report)
        
        # Save results to BigQuery (existing)
        try:
            self._save_results(report)
        except Exception as e:
            logger.error(f"Failed to save results to BigQuery: {e}")
        
        # Send notifications (existing)
        if notify and report.overall_status != "pass":
            try:
                self._send_notification(report)
            except Exception as e:
                logger.error(f"Failed to send notifications: {e}")
        
        return report
    
    def _print_validation_summary(self, report: ValidationReport):
        """Print concise validation summary (10-20 lines)"""
        status_emoji = "✅" if report.overall_status == "pass" else "❌"
        status_text = report.overall_status.upper()
        
        print("=" * 80)
        print(f"VALIDATION SUMMARY: {report.processor_name}")
        print("=" * 80)
        print(f"Status: {status_emoji} {status_text}")
        print(f"Checks: {report.passed_checks}/{report.total_checks} passed")
        print(f"Duration: {report.execution_duration:.1f}s")
        print(f"Date Range: {report.date_range_start} to {report.date_range_end}")
        print()
        
        if report.overall_status == "pass":
            print("✅ All validations passed!")
        else:
            # Show failed checks
            failed_results = [r for r in report.results if r.status in ['fail', 'error']]
            if failed_results:
                print(f"❌ Failed Checks ({len(failed_results)}):")
                for result in failed_results:
                    severity_emoji = "🔴" if result.severity == 'critical' else "🟡"
                    # Truncate message to 60 chars
                    msg = result.message[:60] + "..." if len(result.message) > 60 else result.message
                    affected = f"Affected: {result.affected_count} items" if result.affected_count else ""
                    print(f"  {severity_emoji} {result.check_name}: {msg}")
                    if affected:
                        print(f"     {affected}")
        
        # Show layer stats
        print()
        print("📊 By Layer:")
        layer_stats = self._get_layer_stats(report)
        for layer, stats in layer_stats.items():
            print(f"  {layer}: {stats['passed']} passed, {stats['failed']} failed")
        
        print("=" * 80)

    def _print_detailed_report(self, report: ValidationReport):
        """Print detailed validation report (existing behavior)"""
        # Print the existing detailed report
        logger.info("=" * 80)
        logger.info(f"VALIDATION REPORT: {report.processor_name}")
        logger.info("=" * 80)
        logger.info(f"Run ID: {report.validation_run_id}")
        logger.info(f"Date Range: {report.date_range_start} to {report.date_range_end}")
        logger.info(f"Status: {report.overall_status}")
        logger.info(f"Checks: {report.passed_checks}/{report.total_checks} passed")
        logger.info(f"Duration: {report.execution_duration:.2f} seconds")
        logger.info("")
        
        if report.overall_status == "pass":
            logger.info("✅ All validations passed!")
        else:
            logger.info("❌ Validation failures detected")
        
        logger.info("")
        logger.info("📊 Summary:")
        for key, value in report.summary.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 80)

    def _print_dates_only(self, report: ValidationReport, output_file: Optional[str] = None):
        """
        Print or write missing dates.
        
        If output_file is provided, writes dates to file.
        Otherwise, prints to stdout (for backward compatibility).
        
        Args:
            report: ValidationReport with results
            output_file: Optional file path to write dates to
        """
        # Extract dates from validation results
        missing_dates = set()
        
        # Check if validator has custom date extraction method
        if hasattr(self, '_extract_dates_from_results'):
            missing_dates = self._extract_dates_from_results()
        else:
            # Fallback: generic extraction from affected_items
            for result in report.results:
                if not result.passed and result.affected_items:
                    for item in result.affected_items:
                        item_str = str(item).strip()
                        
                        # Try to extract date
                        if ':' in item_str:
                            potential_date = item_str.split(':')[0].strip()
                        else:
                            potential_date = item_str
                        
                        # Validate date format YYYY-MM-DD
                        if (len(potential_date) == 10 and 
                            potential_date[4] == '-' and 
                            potential_date[7] == '-' and
                            potential_date[:4].isdigit() and
                            potential_date[5:7].isdigit() and
                            potential_date[8:10].isdigit()):
                            missing_dates.add(potential_date)
        
        # Sort dates chronologically
        sorted_dates = sorted(missing_dates)
        
        # Write to file or print to stdout
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    for date in sorted_dates:
                        f.write(f"{date}\n")
                logger.info(f"✅ Wrote {len(sorted_dates)} dates to {output_file}")
            except Exception as e:
                logger.error(f"Failed to write dates to file: {e}")
                raise
        else:
            # Print to stdout (backward compatibility)
            for date in sorted_dates:
                print(date)

    def _get_layer_stats(self, report: ValidationReport):
        """Get pass/fail stats by layer"""
        stats = {}
        
        for result in report.results:
            layer = result.layer or "Other"
            if layer not in stats:
                stats[layer] = {"passed": 0, "failed": 0}
            
            if result.status == "pass":
                stats[layer]["passed"] += 1
            else:
                stats[layer]["failed"] += 1
        
        return stats
    
    # ========================================================================
    # Layer Validation Methods
    # ========================================================================
    
    def _validate_gcs_layer(self, start_date: str, end_date: str, season_year: Optional[int]):
        """Validate GCS scraped data"""
        logger.info("Validating GCS layer...")
        
        gcs_config = self.config.get('gcs_validations', {})
        
        # File presence check
        if 'file_presence' in gcs_config:
            self._check_file_presence(
                gcs_config['file_presence'], 
                start_date, 
                end_date, 
                season_year
            )
    
    def _validate_bigquery_layer(self, start_date: str, end_date: str, season_year: Optional[int]):
        """Validate BigQuery processed data"""
        logger.info("Validating BigQuery layer...")
        
        bq_config = self.config.get('bigquery_validations', {})
        
        # Completeness checks
        if 'completeness' in bq_config:
            self._check_completeness(
                bq_config['completeness'],
                start_date,
                end_date,
                season_year
            )
        
        # Team presence check
        if 'team_presence' in bq_config:
            self._check_team_presence(
                bq_config['team_presence'],
                start_date,
                end_date,
                season_year
            )
        
        # Field validation
        if 'field_validation' in bq_config:
            self._check_field_validation(
                bq_config['field_validation'],
                start_date,
                end_date
            )
    
    def _validate_schedule_layer(self, start_date: str, end_date: str):
        """Validate schedule adherence checks"""
        logger.info("Validating schedule adherence...")
        
        schedule_config = self.config.get('schedule_checks', {})
        
        # Data freshness check
        if schedule_config.get('data_freshness', {}).get('enabled', False):
            # UPDATED: Pass start_date and end_date as parameters
            self._check_data_freshness(
                schedule_config['data_freshness'],
                start_date,
                end_date
            )
        
        # Processing schedule check
        if schedule_config.get('processing_schedule', {}).get('enabled', False):
            self._check_processing_schedule(
                schedule_config['processing_schedule'],
                start_date,
                end_date
            )
    
    # ========================================================================
    # Specific Validation Checks
    # ========================================================================
    
    def _check_completeness(
        self, 
        config: Dict, 
        start_date: str, 
        end_date: str,
        season_year: Optional[int]
    ):
        """Check if all expected records are present"""
        
        check_start = time.time()
        
        target_table = config['target_table']
        reference_table = config['reference_table']
        match_field = config['match_field']
        
        season_filter = f"AND season_year = {season_year}" if season_year else ""
        reference_filter = config.get('reference_filter', '')
        if reference_filter:
            reference_filter = f"AND {reference_filter}"
        
        query = f"""
        WITH expected AS (
          SELECT DISTINCT {match_field}
          FROM `{self.project_id}.{reference_table}`
          WHERE {match_field} >= '{start_date}'
            AND {match_field} <= '{end_date}'
            {season_filter}
            {reference_filter}
        ),
        actual AS (
          SELECT DISTINCT {match_field}
          FROM `{self.project_id}.{target_table}`
          WHERE {match_field} >= '{start_date}'
            AND {match_field} <= '{end_date}'
            {season_filter}
        )
        SELECT e.{match_field} as missing_date
        FROM expected e
        LEFT JOIN actual a ON e.{match_field} = a.{match_field}
        WHERE a.{match_field} IS NULL
        ORDER BY e.{match_field}
        """
        
        result = self._execute_query(query, start_date, end_date)
        missing = [str(row.missing_date) for row in result]
        
        passed = len(missing) == 0
        severity = config.get('severity', 'error')
        
        duration = time.time() - check_start
        
        self.results.append(ValidationResult(
            check_name=f"completeness_{match_field}",
            check_type="completeness",
            layer="bigquery",
            passed=passed,
            severity=severity,
            message=f"Found {len(missing)} missing {match_field}s" if not passed else "All dates present",
            affected_count=len(missing),
            affected_items=missing[:20],  # First 20
            remediation=self._generate_backfill_commands(missing) if not passed else [],
            query_used=query,
            execution_duration=duration
        ))
        
        if not passed:
            logger.warning(f"Completeness check found {len(missing)} missing dates")
            if missing[:5]:
                logger.warning(f"First 5 missing: {missing[:5]}")
    
    def _check_team_presence(
        self,
        config: Dict,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Check if all 30 NBA teams are represented"""
        
        check_start = time.time()
        
        target_table = config['target_table']
        expected_teams = config.get('expected_teams', 30)
        
        season_filter = f"AND season_year = {season_year}" if season_year else ""
        
        # Check both home and away teams
        query = f"""
        WITH all_teams AS (
          SELECT DISTINCT home_team_abbr as team FROM `{self.project_id}.{target_table}`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}' {season_filter}
          UNION DISTINCT
          SELECT DISTINCT away_team_abbr as team FROM `{self.project_id}.{target_table}`
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}' {season_filter}
        )
        SELECT team
        FROM all_teams
        ORDER BY team
        """
        
        result = self._execute_query(query, start_date, end_date)
        teams_found = [row.team for row in result]
        actual_teams = len(teams_found)
        
        passed = actual_teams >= expected_teams
        severity = config.get('severity', 'warning')
        
        duration = time.time() - check_start
        
        self.results.append(ValidationResult(
            check_name="team_presence",
            check_type="team_presence",
            layer="bigquery",
            passed=passed,
            severity=severity,
            message=f"Found {actual_teams}/{expected_teams} teams",
            affected_count=expected_teams - actual_teams if not passed else 0,
            affected_items=teams_found,
            execution_duration=duration
        ))
        
        if not passed:
            logger.warning(f"Team presence check: only {actual_teams}/{expected_teams} teams found")
    
    def _check_field_validation(self, config: Dict, start_date: str, end_date: str):
        """Check required fields are not NULL"""
        
        target_table = config['target_table']
        required_fields = config.get('required_not_null', [])
        
        for field in required_fields:
            check_start = time.time()
            
            query = f"""
            SELECT COUNT(*) as null_count
            FROM `{self.project_id}.{target_table}`
            WHERE {field} IS NULL
              AND game_date >= '{start_date}'
              AND game_date <= '{end_date}'
            """
            
            result = self._execute_query(query, start_date, end_date)
            row = next(result, None)
            null_count = row.null_count if row else 0
            
            passed = null_count == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name=f"field_not_null_{field}",
                check_type="field_validation",
                layer="bigquery",
                passed=passed,
                severity="error",
                message=f"Found {null_count} NULL {field} values" if not passed else f"{field} has no NULLs",
                affected_count=null_count,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Field validation failed: {field} has {null_count} NULL values")
    
    def _check_file_presence(
        self,
        config: Dict,
        start_date: str,
        end_date: str,
        season_year: Optional[int]
    ):
        """Check if expected files exist in GCS"""
        
        check_start = time.time()
        
        bucket_name = config['bucket']
        path_pattern = config['path_pattern']
        
        # Get expected dates (with caching)
        expected_dates = self._get_expected_dates(start_date, end_date, season_year)
        
        try:
            bucket = self.gcs_client.bucket(bucket_name)
            missing_dates = []
            
            for date_str in expected_dates:
                # IMPROVED: Better path handling for various patterns
                # Examples: "espn/scoreboard/{date}/*.json" or "nba-com/schedule/{date}/data.json"
                path = path_pattern.replace('{date}', date_str)
                
                # Extract prefix (everything before wildcard or filename)
                if '*' in path:
                    prefix = path.split('*')[0]
                elif '{timestamp}' in path:
                    prefix = path.split('{timestamp}')[0]
                else:
                    # No wildcard, check exact file
                    prefix = path.rsplit('/', 1)[0] + '/' if '/' in path else ''
                
                # Check if any files exist with this prefix
                blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))
                
                if not blobs:
                    missing_dates.append(date_str)
            
            passed = len(missing_dates) == 0
            duration = time.time() - check_start
            
            self.results.append(ValidationResult(
                check_name="gcs_file_presence",
                check_type="file_presence",
                layer="gcs",
                passed=passed,
                severity="error",
                message=f"Found {len(missing_dates)} dates with missing GCS files" if not passed else "All GCS files present",
                affected_count=len(missing_dates),
                affected_items=missing_dates[:20],
                remediation=self._generate_scraper_commands(missing_dates) if not passed else [],
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"GCS file presence check: {len(missing_dates)} dates missing files")
                if missing_dates[:5]:
                    logger.warning(f"First 5 missing: {missing_dates[:5]}")
                    
        except Exception as e:
            logger.error(f"GCS check failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="gcs_file_presence",
                check_type="file_presence",
                layer="gcs",
                passed=False,
                severity="error",
                message=f"GCS check failed: {str(e)}",
                execution_duration=duration
            ))
    
    def _check_data_freshness(self, config: Dict, start_date: str, end_date: str):
        """Check if data is recent enough within the validation date range"""
        
        check_start = time.time()
        
        target_table = config['target_table']
        max_age_hours = config.get('max_age_hours', 24)
        timestamp_field = config.get('timestamp_field', 'processed_at')
        
        # Use validation date range to check freshness within that window
        # This ensures we check the data we're actually validating
        query = f"""
        SELECT 
          MAX({timestamp_field}) as last_processed,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX({timestamp_field}), HOUR) as hours_old
        FROM `{self.project_id}.{target_table}`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        """
        
        try:
            # Freshness check uses direct query (partition filter already in WHERE clause)
            result = self.bq_client.query(query).result(timeout=60)
            row = next(result, None)

            hours_old = row.hours_old if row and row.hours_old else 9999
            passed = hours_old <= max_age_hours
            
            duration = time.time() - check_start
            
            # Adjust severity based on how stale the data is
            if hours_old <= max_age_hours:
                severity = "info"
            elif hours_old <= max_age_hours * 2:
                severity = "warning"
            else:
                severity = "error"
            
            self.results.append(ValidationResult(
                check_name="data_freshness",
                check_type="freshness",
                layer="schedule",
                passed=passed,
                severity=severity,
                message=f"Data is {hours_old:.1f} hours old (max: {max_age_hours})" if row.hours_old else "No data found in date range",
                affected_count=int(hours_old) if not passed and row.hours_old else 0,
                execution_duration=duration
            ))
            
            if not passed:
                logger.warning(f"Data freshness check: {hours_old:.1f} hours old (max: {max_age_hours})")
                
        except Exception as e:
            logger.error(f"Freshness check failed: {e}")
            duration = time.time() - check_start
            self.results.append(ValidationResult(
                check_name="data_freshness",
                check_type="freshness",
                layer="schedule",
                passed=False,
                severity="error",
                message=f"Freshness check failed: {str(e)}",
                execution_duration=duration
            ))
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _get_expected_dates(
        self, 
        start_date: str, 
        end_date: str,
        season_year: Optional[int]
    ) -> List[str]:
        """
        Get list of expected dates from schedule (with caching).
        
        This query is used by multiple checks, so we cache it.
        """
        cache_key = f"expected_dates_{start_date}_{end_date}_{season_year}"
        
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]
        
        season_filter = f"AND season_year = {season_year}" if season_year else ""
        
        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          {season_filter}
          AND game_status = 3  -- Completed games only
        ORDER BY game_date
        """
        
        # Use execute_query for consistent partition filtering
        result = self._execute_query(query, start_date, end_date, cache_key=cache_key)
        dates = [str(row.game_date) for row in result]
        
        return dates
    
    def _auto_detect_date_range(self, season_year: Optional[int]) -> Tuple[str, str]:
        """Auto-detect date range based on season or recent data"""
        
        if season_year:
            # Use season boundaries
            start_date = f"{season_year}-10-01"
            end_date = f"{season_year + 1}-06-30"
            logger.info(f"Auto-detected season range: {start_date} to {end_date}")
        else:
            # Use last 30 days
            end_date = date.today().isoformat()
            start_date = (date.today() - timedelta(days=30)).isoformat()
            logger.info(f"Auto-detected recent range: {start_date} to {end_date}")
        
        return start_date, end_date
    
    def _generate_backfill_commands(self, missing_dates: List[str]) -> List[str]:
        """Generate gcloud commands to backfill missing data"""
        
        if not missing_dates:
            return []
        
        remediation_config = self.config.get('remediation', {})
        command_template = remediation_config.get('processor_backfill_template', '')
        
        if not command_template:
            return []
        
        # Group consecutive dates for efficiency
        date_groups = self._group_consecutive_dates(missing_dates)
        
        commands = []
        for start, end in date_groups:
            cmd = command_template.format(start_date=start, end_date=end).strip()
            commands.append(cmd)
        
        return commands
    
    def _generate_scraper_commands(self, missing_dates: List[str]) -> List[str]:
        """Generate scraper commands for missing dates"""
        
        remediation_config = self.config.get('remediation', {})
        scraper_template = remediation_config.get('scraper_backfill_template', '')
        
        if not scraper_template:
            return []
        
        commands = []
        # Limit to 10 commands to avoid overwhelming output
        for date_str in missing_dates[:10]:
            cmd = scraper_template.format(date=date_str).strip()
            commands.append(cmd)
        
        if len(missing_dates) > 10:
            commands.append(f"# ... and {len(missing_dates) - 10} more dates")
        
        return commands
    
    def _group_consecutive_dates(self, date_strings: List[str]) -> List[Tuple[str, str]]:
        """Group consecutive dates into ranges for efficient backfill"""
        
        if not date_strings:
            return []
        
        try:
            dates = sorted([datetime.strptime(d, '%Y-%m-%d').date() for d in date_strings])
        except ValueError as e:
            logger.warning(f"Date parsing error: {e}, using individual dates")
            return [(d, d) for d in date_strings[:10]]
        
        groups = []
        current_start = dates[0]
        current_end = dates[0]
        
        for i in range(1, len(dates)):
            if (dates[i] - current_end).days == 1:
                current_end = dates[i]
            else:
                groups.append((current_start.isoformat(), current_end.isoformat()))
                current_start = dates[i]
                current_end = dates[i]
        
        groups.append((current_start.isoformat(), current_end.isoformat()))
        
        return groups
    
    # ========================================================================
    # Custom Validations (Override in Subclass)
    # ========================================================================
    
    def _run_custom_validations(self, start_date: str, end_date: str, season_year: Optional[int]):
        """
        Run odds-specific custom validations (overrides base class method)
        
        Args:
            start_date: Start date for validation
            end_date: End date for validation
            season_year: Season year (optional)
        """
        logger.info("Running Odds API custom validations...")
        logger.info(f"DEBUG: start_date={start_date}, end_date={end_date}")
        logger.info(f"DEBUG: self.start_date={getattr(self, 'start_date', 'NOT SET')}")
        logger.info(f"DEBUG: self.end_date={getattr(self, 'end_date', 'NOT SET')}")
        
        # 1. Game completeness check
        logger.info("DEBUG: Calling _validate_game_completeness...")
        result = self._validate_game_completeness()
        logger.info(f"DEBUG: Got result: {result}")
        self.results.append(result)
        logger.info(f"DEBUG: Results now has {len(self.results)} items")
    
    # ========================================================================
    # Reporting
    # ========================================================================
    
    def _generate_report(
        self, 
        run_id: str, 
        start_date: str, 
        end_date: str,
        season_year: Optional[int]
    ) -> ValidationReport:
        """Generate validation report"""
        
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        # Determine overall status
        has_critical = any(r.severity == 'critical' and not r.passed for r in self.results)
        has_error = any(r.severity == 'error' and not r.passed for r in self.results)
        has_warning = any(r.severity == 'warning' and not r.passed for r in self.results)
        
        if has_critical or has_error:
            overall_status = ValidationStatus.FAIL.value
        elif has_warning:
            overall_status = ValidationStatus.WARN.value
        else:
            overall_status = ValidationStatus.PASS.value
        
        # Collect all remediation commands
        remediation = []
        for result in self.results:
            if not result.passed and result.remediation:
                remediation.extend(result.remediation)
        
        # Remove duplicates while preserving order
        remediation = list(dict.fromkeys(remediation))
        
        total_duration = time.time() - self._start_time
        
        report = ValidationReport(
            processor_name=self.processor_name,
            processor_type=self.processor_type,
            validation_timestamp=datetime.utcnow().isoformat() + 'Z',
            validation_run_id=run_id,
            date_range_start=start_date,
            date_range_end=end_date,
            season_year=season_year,
            total_checks=len(self.results),
            passed_checks=passed,
            failed_checks=failed,
            overall_status=overall_status,
            results=self.results,
            remediation_commands=remediation,
            summary=self._build_summary(),
            execution_duration=total_duration
        )
        
        self._log_report(report)
        
        return report
    
    def _build_summary(self) -> Dict[str, Any]:
        """Build summary statistics"""
        
        summary = {
            'by_layer': {},
            'by_severity': {},
            'by_type': {},
            'execution_times': {}
        }
        
        for result in self.results:
            # By layer
            if result.layer not in summary['by_layer']:
                summary['by_layer'][result.layer] = {'passed': 0, 'failed': 0}
            
            if result.passed:
                summary['by_layer'][result.layer]['passed'] += 1
            else:
                summary['by_layer'][result.layer]['failed'] += 1
            
            # By severity (only failures)
            if not result.passed:
                if result.severity not in summary['by_severity']:
                    summary['by_severity'][result.severity] = 0
                summary['by_severity'][result.severity] += 1
            
            # By type
            if result.check_type not in summary['by_type']:
                summary['by_type'][result.check_type] = {'passed': 0, 'failed': 0}
            
            if result.passed:
                summary['by_type'][result.check_type]['passed'] += 1
            else:
                summary['by_type'][result.check_type]['failed'] += 1
            
            # Execution times
            if result.execution_duration:
                summary['execution_times'][result.check_name] = round(result.execution_duration, 2)
        
        return summary
    
    def _log_report(self, report: ValidationReport):
        """Log validation report"""
        
        logger.info("=" * 80)
        logger.info(f"VALIDATION REPORT: {report.processor_name}")
        logger.info("=" * 80)
        logger.info(f"Run ID: {report.validation_run_id}")
        logger.info(f"Date Range: {report.date_range_start} to {report.date_range_end}")
        if report.season_year:
            logger.info(f"Season: {report.season_year}-{report.season_year + 1}")
        logger.info(f"Status: {report.overall_status.upper()}")
        logger.info(f"Checks: {report.passed_checks}/{report.total_checks} passed")
        logger.info(f"Duration: {report.execution_duration:.2f} seconds")
        
        if report.failed_checks > 0:
            logger.warning(f"\n❌ Failed Checks ({report.failed_checks}):")
            for result in report.results:
                if not result.passed:
                    icon = "🔴" if result.severity in ['error', 'critical'] else "🟡"
                    logger.warning(f"  {icon} [{result.severity.upper()}] {result.check_name}")
                    logger.warning(f"     {result.message}")
                    if result.affected_count:
                        logger.warning(f"     Affected: {result.affected_count} items")
                    if result.affected_items and len(result.affected_items) <= 5:
                        logger.warning(f"     Items: {result.affected_items}")
                    if result.execution_duration:
                        logger.warning(f"     Duration: {result.execution_duration:.2f}s")
            
            if report.remediation_commands:
                logger.info(f"\n🔧 Remediation Commands ({len(report.remediation_commands)}):")
                for i, cmd in enumerate(report.remediation_commands[:5], 1):
                    logger.info(f"  {i}. {cmd}")
                if len(report.remediation_commands) > 5:
                    logger.info(f"  ... and {len(report.remediation_commands) - 5} more")
        else:
            logger.info("\n✅ All validations passed!")
        
        # Log summary stats
        logger.info("\n📊 Summary:")
        for layer, stats in report.summary.get('by_layer', {}).items():
            logger.info(f"  {layer}: {stats['passed']} passed, {stats['failed']} failed")
        
        logger.info("=" * 80)
    
    def _send_notification(self, report: ValidationReport):
        """Send notification via existing system"""
        
        try:
            if report.overall_status == ValidationStatus.FAIL.value:
                notify_error(
                    title=f"❌ Validation Failed: {report.processor_name}",
                    message=f"{report.failed_checks} checks failed for {report.date_range_start} to {report.date_range_end}",
                    details={
                        'run_id': report.validation_run_id,
                        'date_range': f"{report.date_range_start} to {report.date_range_end}",
                        'failed_checks': report.failed_checks,
                        'critical_count': report.summary.get('by_severity', {}).get('critical', 0),
                        'error_count': report.summary.get('by_severity', {}).get('error', 0),
                        'remediation_available': len(report.remediation_commands) > 0,
                        'remediation_commands': report.remediation_commands[:3],
                        'duration': f"{report.execution_duration:.2f}s"
                    }
                )
            elif report.overall_status == ValidationStatus.WARN.value:
                notify_warning(
                    title=f"⚠️ Validation Warnings: {report.processor_name}",
                    message=f"{report.failed_checks} checks have warnings",
                    details={
                        'run_id': report.validation_run_id,
                        'date_range': f"{report.date_range_start} to {report.date_range_end}",
                        'warnings': [r.message for r in report.results if not r.passed and r.severity == 'warning'][:5],
                        'duration': f"{report.execution_duration:.2f}s"
                    },
                    processor_name=self.__class__.__name__
                )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
    
    def _save_results(self, report: ValidationReport):
        """Save validation results to BigQuery using batch load"""
        
        # Save to validation_results table
        results_table_id = f"{self.project_id}.validation.validation_results"
        runs_table_id = f"{self.project_id}.validation.validation_runs"
        
        # Prepare result rows
        result_rows = []
        for result in report.results:
            row = {
                'validation_run_id': report.validation_run_id,
                'validation_timestamp': report.validation_timestamp,
                'processor_name': report.processor_name,
                'processor_type': report.processor_type,
                'date_range_start': report.date_range_start,
                'date_range_end': report.date_range_end,
                'season_year': report.season_year,
                'check_name': result.check_name,
                'check_type': result.check_type,
                'validation_layer': result.layer,
                'passed': result.passed,
                'severity': result.severity,
                'message': result.message,
                'affected_count': result.affected_count,
                'affected_items': json.dumps(result.affected_items[:20]) if result.affected_items else None,
                'remediation_commands': json.dumps(result.remediation[:10]) if result.remediation else None,
                'remediation_generated': bool(result.remediation),
                'query_used': result.query_used,
                'execution_duration_seconds': result.execution_duration,
                'overall_status': report.overall_status,
                'validator_version': '2.0'
            }
            result_rows.append(row)
        
        # Prepare run metadata row
        run_row = {
            'validation_run_id': report.validation_run_id,
            'validation_timestamp': report.validation_timestamp,
            'processor_name': report.processor_name,
            'processor_type': report.processor_type,
            'date_range_start': report.date_range_start,
            'date_range_end': report.date_range_end,
            'season_year': report.season_year,
            'layers_validated': json.dumps(list(report.summary.get('by_layer', {}).keys())),
            'total_checks': report.total_checks,
            'passed_checks': report.passed_checks,
            'failed_checks': report.failed_checks,
            'overall_status': report.overall_status,
            'execution_duration_seconds': report.execution_duration,
            'triggered_by': 'manual',
            'notification_sent': report.overall_status != ValidationStatus.PASS.value,
            'notification_channels': json.dumps(['slack']) if report.overall_status != ValidationStatus.PASS.value else None,
            'remediation_available': len(report.remediation_commands) > 0,
            'remediation_commands_count': len(report.remediation_commands),
            'validator_version': '2.0'
        }
        
        try:
            # Insert results using batch loading (avoids streaming buffer)
            # See: docs/05-development/guides/bigquery-best-practices.md
            # Streaming inserts create a 90-minute buffer that blocks DML operations.
            # Batch loading avoids this issue and allows immediate MERGE/UPDATE/DELETE.

            # Get table reference for schema validation
            results_table_ref = self.bq_client.get_table(results_table_id)

            # Use batch loading instead of streaming inserts
            job_config = bigquery.LoadJobConfig(
                schema=results_table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json(result_rows, results_table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
            else:
                logger.info(f"✅ Saved {len(result_rows)} validation results to BigQuery")

            # Insert run metadata using batch writer for quota efficiency
            # This uses streaming inserts to bypass load job quota limits
            writer = get_batch_writer(runs_table_id)
            writer.add_record(run_row)

            logger.info(f"✅ Saved validation run metadata to BigQuery")
                
        except Exception as e:
            logger.error(f"Failed to save results to BigQuery: {e}")
            raise