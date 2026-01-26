"""
Gamebook Precedence Validator

Prevents roster registry from overriding gamebook data by ensuring
roster doesn't process dates that gamebook has already processed.

This is a cross-processor temporal check - gamebook data is authoritative
for historical dates since it represents verified game participation.
"""

import logging
from datetime import date
from typing import Tuple

import pandas as pd
from google.cloud import bigquery

from shared.utils.notification_system import notify_error

logger = logging.getLogger(__name__)


class GamebookPrecedenceValidator:
    """
    Validates that roster processing doesn't conflict with gamebook data.

    Business Rule:
    - If gamebook has processed ANY date >= data_date in this season,
      roster CANNOT process data_date
    - Prevents roster from going backwards relative to gamebook's progress
    - Works like temporal ordering but across processors
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str, run_history_table: str):
        """
        Initialize gamebook precedence validator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            run_history_table: Run history table name (e.g., "nba_raw.processor_run_history")
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.run_history_table = run_history_table

    def check_precedence(self, data_date: date, season_year: int) -> Tuple[bool, str]:
        """
        Check if gamebook processor has processed this date or any later date in the season.

        This is a TEMPORAL cross-processor check, not just an exact-date check.

        Example:
            Gamebook processed: Oct 5, 2024
            Roster tries: Oct 1, 2024
            Result: BLOCKED (gamebook is ahead, roster can't go backwards)

        Args:
            data_date: The date being processed
            season_year: The season year being processed

        Returns:
            Tuple of (is_blocked: bool, reason: str)
            - is_blocked=True: Processing should be blocked
            - is_blocked=False: Safe to proceed
            - reason: Explanation for the decision
        """
        query = f"""
        SELECT
            MAX(data_date) as latest_gamebook_date,
            MAX(processed_at) as last_gamebook_run,
            COUNT(*) as total_gamebook_runs,
            SUM(records_processed) as total_records
        FROM `{self.project_id}.{self.run_history_table}`
        WHERE processor_name = 'gamebook'
        AND season_year = @season_year
        AND status = 'success'
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()

            # Check if gamebook has processed anything for this season
            if results.empty or pd.isna(results.iloc[0]['latest_gamebook_date']):
                logger.info(f"No gamebook data found for season {season_year} - roster can proceed")
                return False, "no_gamebook_data"

            # Get latest date gamebook has processed
            latest_gamebook_date = results.iloc[0]['latest_gamebook_date']

            # Convert to date if timestamp
            if isinstance(latest_gamebook_date, pd.Timestamp):
                latest_gamebook_date = latest_gamebook_date.date()

            # TEMPORAL CHECK: Is roster trying to process a date <= gamebook's progress?
            if data_date <= latest_gamebook_date:
                last_run = results.iloc[0]['last_gamebook_run']
                total_runs = results.iloc[0]['total_gamebook_runs']
                total_records = results.iloc[0]['total_records']

                error_msg = (
                    f"Gamebook processor has already processed through {latest_gamebook_date} "
                    f"for season {season_year}. Cannot process {data_date} - roster must not "
                    f"go backwards relative to gamebook's progress. "
                    f"Last gamebook run: {last_run} ({total_runs} total runs, "
                    f"{total_records} total records processed)."
                )

                logger.error(error_msg)

                try:
                    notify_error(
                        title="Roster Processing Blocked by Gamebook Precedence",
                        message=f"Cannot process {data_date} - gamebook already at {latest_gamebook_date}",
                        details={
                            'data_date': str(data_date),
                            'latest_gamebook_date': str(latest_gamebook_date),
                            'season_year': season_year,
                            'total_gamebook_runs': int(total_runs) if pd.notna(total_runs) else 0,
                            'last_gamebook_run': str(last_run),
                            'total_records': int(total_records) if pd.notna(total_records) else 0,
                            'reason': 'gamebook_data_is_authoritative',
                            'action': 'Roster cannot go backwards relative to gamebook progress'
                        },
                        processor_name="Roster Registry Processor"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")

                return True, error_msg

            # Roster is ahead of gamebook - safe to proceed
            logger.info(
                f"Gamebook at {latest_gamebook_date}, roster processing {data_date} - "
                f"roster is ahead, safe to proceed"
            )
            return False, "roster_ahead_of_gamebook"

        except Exception as e:
            # Fail-closed to prevent stale roster data
            logger.error(
                f"Error checking gamebook precedence - BLOCKING to prevent stale data: {e}",
                exc_info=True
            )
            return True, f"check_failed: {str(e)}"
