"""
Dependency checking logic for precompute processors.

Provides table data validation and dependency query building for Phase 4 processors.

Version: 1.0
Created: 2026-01-25
"""

import logging
from datetime import datetime, date, timezone
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)


class DependencyCheckingMixin:
    """
    Dependency checking logic for precompute processors.

    Provides methods to check if upstream tables have required data,
    including support for different check types (date_match, lookback, etc).

    Requires from base class:
    - self.bq_client: BigQuery client
    - self.project_id: GCP project ID
    - self.is_backfill_mode: bool indicating backfill mode
    """

    def _check_table_data(self, table_name: str, analysis_date: date, config: dict) -> tuple:
        """
        Check if table has data for the given date.

        Args:
            table_name: Full table name (project.dataset.table)
            analysis_date: Date to check for
            config: Dependency configuration dict

        Returns:
            (exists: bool, details: dict)
        """
        check_type = config.get('check_type', 'date_match')
        date_field = config.get('date_field', 'game_date')

        try:
            query = self._build_dependency_query(table_name, analysis_date, check_type, date_field, config)

            # Use shorter timeout in backfill mode
            query_timeout = 60 if self.is_backfill_mode else 300
            query_job = self.bq_client.query(query)
            result = list(query_job.result(timeout=query_timeout))

            if not result:
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'age_hours': None,
                    'last_updated': None,
                    'error': 'No query results'
                }

            row = result[0]
            row_count = row.row_count
            last_updated = row.last_updated

            # Calculate age using timezone-aware datetime
            if last_updated:
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - last_updated).total_seconds() / 3600
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
                'last_updated': last_updated.isoformat() if last_updated else None
            }

            return exists, details

        except GoogleAPIError as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {'exists': False, 'error': error_msg}

    def _build_dependency_query(self, table_name: str, analysis_date: date,
                                check_type: str, date_field: str, config: dict) -> str:
        """
        Build BigQuery query for dependency checking.

        Args:
            table_name: Table to check
            analysis_date: Date to check for
            check_type: Type of check (date_match, lookback, existence, per_player_game_count)
            date_field: Date field name in the table
            config: Dependency configuration dict

        Returns:
            SQL query string
        """
        if check_type == 'date_match':
            return f"""
            SELECT COUNT(*) as row_count, MAX(processed_at) as last_updated
            FROM `{self.project_id}.{table_name}`
            WHERE {date_field} = '{analysis_date}'
            """

        elif check_type == 'lookback':
            lookback_games = config.get('lookback_games', 10)
            limit = lookback_games * 100  # Conservative estimate
            return f"""
            SELECT COUNT(*) as row_count, MAX(processed_at) as last_updated
            FROM (
                SELECT * FROM `{self.project_id}.{table_name}`
                WHERE {date_field} <= '{analysis_date}'
                ORDER BY {date_field} DESC
                LIMIT {limit}
            )
            """

        elif check_type == 'existence':
            return f"""
            SELECT COUNT(*) as row_count, MAX(processed_at) as last_updated
            FROM `{self.project_id}.{table_name}`
            LIMIT 1
            """

        elif check_type == 'per_player_game_count':
            entity_field = config.get('entity_field', 'player_lookup')
            min_games = config.get('min_games_required', 10)
            lookback_days = min_games * 2  # Approximate days for min_games
            return f"""
            SELECT COUNT(*) as row_count, MAX(processed_at) as last_updated
            FROM `{self.project_id}.{table_name}`
            WHERE {date_field} >= DATE_SUB('{analysis_date}', INTERVAL {lookback_days} DAY)
              AND {date_field} <= '{analysis_date}'
            """

        else:
            raise ValueError(f"Unknown check_type: {check_type}")
