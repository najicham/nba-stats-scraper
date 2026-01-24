"""
Data Freshness Checker

Utility to check if upstream data is fresh enough for processing.
Sends stale data warnings via email when data is older than expected.

Usage:
    from shared.utils.data_freshness_checker import check_data_freshness, DataFreshnessChecker

    # Simple function call
    is_fresh = check_data_freshness(
        bq_client=bq_client,
        table='nba_raw.nbacom_boxscores',
        max_age_hours=6,
        processor_name='PlayerGameSummaryProcessor'
    )

    # Or use checker class for multiple tables
    checker = DataFreshnessChecker(bq_client)
    results = checker.check_multiple_tables([
        {'table': 'nba_raw.nbacom_boxscores', 'max_age_hours': 6},
        {'table': 'nba_raw.pbpstats_player_boxscore', 'max_age_hours': 6},
    ])

Version: 1.0
Created: 2025-11-30
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DataFreshnessChecker:
    """
    Check data freshness for upstream tables.

    Queries BigQuery to determine when tables were last updated
    and sends alerts when data is stale.
    """

    def __init__(self, bq_client, project_id: str = None):
        """
        Initialize freshness checker.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID (defaults to centralized config)
        """
        from shared.config.gcp_config import get_project_id
        self.bq_client = bq_client
        self.project_id = project_id or get_project_id()

    def check_freshness(
        self,
        table: str,
        max_age_hours: int = 6,
        timestamp_column: str = None,
        processor_name: str = None,
        send_alert: bool = True
    ) -> Dict:
        """
        Check if table data is fresh enough.

        Args:
            table: Full table name (e.g., 'nba_raw.nbacom_boxscores')
            max_age_hours: Maximum acceptable age in hours
            timestamp_column: Column to check for freshness (default: auto-detect)
            processor_name: Processor name for alert context
            send_alert: If True, send stale data alert when stale

        Returns:
            Dict with freshness info:
            {
                'table': 'nba_raw.nbacom_boxscores',
                'is_fresh': True/False,
                'last_updated': datetime,
                'age_hours': 4.5,
                'max_age_hours': 6,
                'alert_sent': False
            }
        """
        try:
            # Auto-detect timestamp column if not specified
            if timestamp_column is None:
                timestamp_column = self._detect_timestamp_column(table)

            # Query for most recent data
            last_updated = self._get_last_updated(table, timestamp_column)

            if last_updated is None:
                logger.warning(f"Could not determine last update time for {table}")
                return {
                    'table': table,
                    'is_fresh': False,
                    'last_updated': None,
                    'age_hours': None,
                    'max_age_hours': max_age_hours,
                    'error': 'Could not determine last update time'
                }

            # Calculate age
            now = datetime.now(timezone.utc)
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=timezone.utc)

            age = now - last_updated
            age_hours = age.total_seconds() / 3600

            is_fresh = age_hours <= max_age_hours

            result = {
                'table': table,
                'is_fresh': is_fresh,
                'last_updated': last_updated,
                'age_hours': round(age_hours, 1),
                'max_age_hours': max_age_hours,
                'alert_sent': False
            }

            # Send alert if stale and alerts enabled
            if not is_fresh and send_alert:
                alert_sent = self._send_stale_alert(
                    table=table,
                    last_updated=last_updated,
                    age_hours=age_hours,
                    max_age_hours=max_age_hours,
                    processor_name=processor_name
                )
                result['alert_sent'] = alert_sent

            return result

        except Exception as e:
            logger.error(f"Error checking freshness for {table}: {e}")
            return {
                'table': table,
                'is_fresh': False,
                'last_updated': None,
                'age_hours': None,
                'max_age_hours': max_age_hours,
                'error': str(e)
            }

    def check_multiple_tables(
        self,
        tables: List[Dict],
        processor_name: str = None,
        send_alerts: bool = True
    ) -> Dict[str, Dict]:
        """
        Check freshness for multiple tables.

        Args:
            tables: List of table configs:
                [
                    {'table': 'nba_raw.nbacom_boxscores', 'max_age_hours': 6},
                    {'table': 'nba_raw.pbpstats_player_boxscore', 'max_age_hours': 6},
                ]
            processor_name: Processor name for alert context
            send_alerts: If True, send alerts for stale tables

        Returns:
            Dict mapping table name to freshness result
        """
        results = {}

        for config in tables:
            table = config['table']
            max_age = config.get('max_age_hours', 6)
            timestamp_col = config.get('timestamp_column')

            results[table] = self.check_freshness(
                table=table,
                max_age_hours=max_age,
                timestamp_column=timestamp_col,
                processor_name=processor_name,
                send_alert=send_alerts
            )

        return results

    def _detect_timestamp_column(self, table: str) -> str:
        """Auto-detect the timestamp column for a table."""
        # Common timestamp column names
        common_names = [
            'created_at', 'updated_at', 'processed_at',
            'ingested_at', 'loaded_at', 'timestamp'
        ]

        try:
            # Query table schema
            query = f"""
                SELECT column_name
                FROM `{self.project_id}.{table.replace('.', '.')}.INFORMATION_SCHEMA.COLUMNS`
                WHERE data_type IN ('TIMESTAMP', 'DATETIME')
            """
            # Fallback: just use a common column
            for name in common_names:
                try:
                    test_query = f"SELECT MAX({name}) FROM `{self.project_id}.{table}` LIMIT 1"
                    # Wait for completion with timeout to prevent indefinite hangs
                    self.bq_client.query(test_query).result(timeout=60)
                    return name
                except Exception as e:
                    logger.debug(f"Column '{name}' not valid for {table}: {e}")
                    continue

            # Default fallback
            return 'created_at'

        except Exception as e:
            logger.debug(f"Could not detect timestamp column: {e}")
            return 'created_at'

    def _get_last_updated(self, table: str, timestamp_column: str) -> Optional[datetime]:
        """Get the most recent timestamp from a table."""
        try:
            query = f"""
                SELECT MAX({timestamp_column}) as last_updated
                FROM `{self.project_id}.{table}`
            """
            # Wait for completion with timeout to prevent indefinite hangs
            result = list(self.bq_client.query(query).result(timeout=60))
            if result and result[0].last_updated:
                return result[0].last_updated
            return None
        except Exception as e:
            logger.error(f"Error getting last update for {table}: {e}")
            return None

    def _send_stale_alert(
        self,
        table: str,
        last_updated: datetime,
        age_hours: float,
        max_age_hours: int,
        processor_name: str = None
    ) -> bool:
        """Send stale data alert via email."""
        try:
            from shared.utils.email_alerting_ses import EmailAlerterSES

            stale_data = {
                'processor_name': processor_name or 'DataFreshnessChecker',
                'upstream_table': table,
                'last_updated': last_updated.strftime('%Y-%m-%d %H:%M:%S UTC'),
                'expected_freshness_hours': max_age_hours,
                'actual_age_hours': int(age_hours)
            }

            alerter = EmailAlerterSES()
            success = alerter.send_stale_data_warning(stale_data)

            if success:
                logger.info(f"🕐 Stale data alert sent for {table}")
            return success

        except ImportError as e:
            logger.warning(f"Email alerter not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending stale data alert: {e}")
            return False


def check_data_freshness(
    bq_client,
    table: str,
    max_age_hours: int = 6,
    timestamp_column: str = None,
    processor_name: str = None,
    send_alert: bool = True,
    project_id: str = 'nba-props-platform'
) -> bool:
    """
    Convenience function to check if table data is fresh.

    Args:
        bq_client: BigQuery client
        table: Table name (e.g., 'nba_raw.nbacom_boxscores')
        max_age_hours: Maximum acceptable age
        timestamp_column: Column to check (auto-detected if None)
        processor_name: Processor name for alerts
        send_alert: Send alert if stale
        project_id: GCP project ID

    Returns:
        True if data is fresh, False if stale

    Example:
        if not check_data_freshness(bq_client, 'nba_raw.nbacom_boxscores', max_age_hours=6):
            logger.warning("Proceeding with stale data")
    """
    checker = DataFreshnessChecker(bq_client, project_id)
    result = checker.check_freshness(
        table=table,
        max_age_hours=max_age_hours,
        timestamp_column=timestamp_column,
        processor_name=processor_name,
        send_alert=send_alert
    )
    return result.get('is_fresh', False)
