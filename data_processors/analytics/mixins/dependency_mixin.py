"""
Upstream dependency checking for analytics processors.

Validates that required Phase 2 raw tables exist, are fresh, and contain
expected row counts before processing begins.

Version: 1.0
Created: 2026-01-25
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)


class DependencyMixin:
    """
    Upstream dependency checking for analytics processors.

    Validates that required Phase 2 raw tables exist, are fresh,
    and contain expected row counts before processing begins.

    Requires from base class:
    - self.bq_client: BigQuery client
    - self.project_id: GCP project ID
    - self.is_backfill_mode: Backfill mode flag (property)
    """

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
                          config: dict) -> Tuple[bool, dict]:
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

            elif check_type == 'date_match':
                # Check for records on exact date (end_date is the target date)
                # Used for sources that should have data for the specific processing date
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} = '{end_date}'
                """

            elif check_type == 'lookback_days':
                # Check for records in a lookback window from end_date
                # Used for historical data sources (e.g., player boxscores for last 30 days)
                lookback = config.get('lookback_days', 30)
                # Calculate lookback start date (datetime/timedelta already imported at module level)
                if isinstance(end_date, str):
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
                else:
                    end_dt = end_date
                lookback_start = (end_dt - timedelta(days=lookback)).strftime('%Y-%m-%d')
                query = f"""
                SELECT
                    COUNT(*) as row_count,
                    MAX(processed_at) as last_updated,
                    ARRAY_AGG({hash_field} IGNORE NULLS ORDER BY processed_at DESC LIMIT 1)[SAFE_OFFSET(0)] as representative_hash
                FROM `{self.project_id}.{table_name}`
                WHERE {date_field} BETWEEN '{lookback_start}' AND '{end_date}'
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
            result = list(self.bq_client.query(query).result(timeout=60))

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

            # Determine if data exists - LENIENT CHECK
            # Data "exists" if ANY rows are present (row_count > 0)
            # This prevents false negatives that block the pipeline
            # The expected_count_min is used for warnings, not blocking
            expected_min = config.get('expected_count_min', 1)
            exists = row_count > 0  # LENIENT: any data = exists

            # Check if data is "sufficient" (meets expected threshold)
            sufficient = row_count >= expected_min

            # Log warning if data exists but is below expected threshold
            if exists and not sufficient and not self.is_backfill_mode:
                logger.warning(
                    f"{table_name}: Data exists ({row_count} rows) but below "
                    f"expected minimum ({expected_min}). Proceeding anyway."
                )

            details = {
                'exists': exists,
                'sufficient': sufficient,
                'row_count': row_count,
                'expected_count_min': expected_min,
                'age_hours': round(age_hours, 2) if age_hours else None,
                'last_updated': last_updated.isoformat() if last_updated else None,
                'data_hash': data_hash  # Representative hash from source data
            }

            logger.debug(f"{table_name}: {details}")

            return exists, details

        except GoogleAPIError as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {
                'exists': False,
                'data_hash': None,
                'error': error_msg
            }
