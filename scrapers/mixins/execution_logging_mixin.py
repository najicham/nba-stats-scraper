"""
execution_logging_mixin.py

Handles execution logging to BigQuery for scraper orchestration tracking.

This mixin provides methods for:
- Logging successful executions to scraper_execution_log
- Logging failed executions with error details
- Logging failures for automatic backfill recovery
- Determining execution source, status, and environment
- Extracting game dates and scraper names for tracking
"""

import logging
import os
import json
from datetime import datetime, timezone
import sentry_sdk
from scrapers.utils.env_utils import is_local

# Initialize logger for this module
logger = logging.getLogger(__name__)


class ExecutionLoggingMixin:
    """
    Mixin that handles execution logging to BigQuery for orchestration tracking.

    Provides comprehensive logging capabilities for:
    - Successful scraper executions
    - Failed executions with error details
    - Automatic backfill failure tracking
    - Execution source and environment detection
    """

    def _get_scraper_name(self) -> str:
        """
        Extract clean scraper name from class name for orchestration logging.

        Converts class names like:
          - GetNBAComInjuryReport → nbac_injury_report
          - GetOddsAPIEvents → oddsa_events
          - GetBallDontLieBoxscores → bdl_boxscores

        Returns:
            str: Snake-case scraper name with source prefix
        """
        import re

        class_name = self.__class__.__name__

        # Remove 'Get' prefix if present
        if class_name.startswith('Get'):
            class_name = class_name[3:]

        # Convert CamelCase to snake_case
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

        # Apply standard source prefixes
        name = name.replace('nba_com_', 'nbac_')
        name = name.replace('odds_api_', 'oddsa_')
        name = name.replace('ball_dont_lie_', 'bdl_')
        name = name.replace('big_data_ball_', 'bdb_')
        name = name.replace('espn_', 'espn_')

        return name

    def _determine_execution_source(self) -> tuple[str, str, str]:
        """
        Determine execution source, environment, and triggered_by for logging.

        Source values:
          - CONTROLLER: Called by master workflow controller
          - MANUAL: Direct API call (testing)
          - LOCAL: Running on dev laptop
          - CLOUD_RUN: Direct endpoint call to Cloud Run service
          - SCHEDULER: Triggered by Cloud Scheduler job
          - RECOVERY: Republished by cleanup processor (self-healing)

        Returns:
            tuple: (source, environment, triggered_by)
        """
        import getpass

        # Check explicit source in opts (workflow controller sets this)
        if 'source' in self.opts:
            source = self.opts['source']
        # Check if running in Cloud Run
        elif os.getenv('K_SERVICE'):
            if self.opts.get('workflow') and self.opts['workflow'] != 'MANUAL':
                source = 'CONTROLLER'  # Called by master controller
            else:
                source = 'CLOUD_RUN'  # Direct endpoint call
        # Check if running locally
        elif is_local():
            source = 'LOCAL'
        else:
            source = 'MANUAL'

        # Determine environment (reuse existing ENV detection)
        environment = 'local' if is_local() else self.opts.get('group', 'prod')

        # Determine triggered_by based on source
        if source == 'CONTROLLER':
            triggered_by = 'master-controller'
        elif source == 'SCHEDULER':
            triggered_by = 'cloud-scheduler'
        elif source == 'RECOVERY':
            triggered_by = 'cleanup-processor'
        elif source == 'LOCAL':
            try:
                triggered_by = f"{getpass.getuser()}@local"
            except (KeyError, OSError):
                # KeyError: USER env var missing; OSError: getpwuid() fails in containers
                triggered_by = 'unknown@local'
        else:
            triggered_by = os.getenv('K_SERVICE', 'manual')

        return source, environment, triggered_by

    def _determine_execution_status(self) -> tuple[str, int]:
        """
        Determine execution status using 4-status system for orchestration.

        Status values:
          - 'success': Got complete data (record_count > 0, data_status != 'partial')
          - 'partial': Got incomplete data (record_count > 0, data_status == 'partial')
          - 'no_data': Tried but empty (record_count = 0)
          - 'failed': Error occurred (handled in _log_failed_execution_to_bigquery)

        This enables discovery mode: controller stops trying after 'success',
        keeps trying after 'no_data' or 'partial'.

        R-009 Fix: Added 'partial' status for cases like gamebooks with only
        roster data (DNP/inactive players) but no active player stats.

        Returns:
            tuple: (status, record_count)
        """
        # Count records in self.data
        if isinstance(self.data, dict):
            # Try multiple common patterns for record storage
            # Different scrapers use different keys
            record_count = 0

            # Pattern 1: Standard {'records': [...]}
            if 'records' in self.data:
                record_count = len(self.data.get('records', []))
            # Pattern 2: Schedule scrapers use {'games': [...]}
            elif 'games' in self.data:
                record_count = len(self.data.get('games', []))
            # Pattern 3: Some scrapers use {'players': [...]}
            elif 'players' in self.data:
                record_count = len(self.data.get('players', []))
            # Pattern 4: Some scrapers store explicit count
            elif 'game_count' in self.data:
                record_count = self.data.get('game_count', 0)
            elif 'record_count' in self.data:
                record_count = self.data.get('record_count', 0)
            elif 'rowCount' in self.data:
                # Odds scrapers use rowCount (camelCase)
                record_count = self.data.get('rowCount', 0)
            elif 'playerCount' in self.data:
                record_count = self.data.get('playerCount', 0)
            elif 'records_found' in self.data:
                record_count = self.data.get('records_found', 0)
            # Pattern 5: Check other common list fields
            else:
                # Look for any list-type values as potential records
                for key, value in self.data.items():
                    if isinstance(value, list) and len(value) > 0:
                        record_count = len(value)
                        break

            # Check if scraper marked this as intentionally empty
            is_empty = self.data.get('metadata', {}).get('is_empty_report', False)
        elif isinstance(self.data, list):
            # Simple list of records
            record_count = len(self.data)
            is_empty = False
        else:
            # Empty or unexpected format
            record_count = 0
            is_empty = False

        # R-009 Fix: Check for partial data status (e.g., roster-only gamebook data)
        is_partial = False
        if isinstance(self.data, dict):
            is_partial = self.data.get('data_status') == 'partial'

        # Determine status based on record count and data quality
        if is_partial and record_count > 0:
            # Has records but marked as partial (e.g., no active players in gamebook)
            status = 'partial'
        elif record_count > 0:
            status = 'success'
        elif is_empty or record_count == 0:
            status = 'no_data'
        else:
            # Fallback (shouldn't reach here)
            status = 'success'

        return status, record_count

    def _extract_game_date(self) -> str | None:
        """
        Extract and format game_date from opts.gamedate for orchestration logging.

        Converts gamedate from YYYYMMDD format to YYYY-MM-DD (DATE type).
        Returns None if gamedate is not present (for scrapers without dates).

        Examples:
            '20260102' → '2026-01-02'
            '2026-01-02' → '2026-01-02' (already formatted)
            None → None (scraper doesn't use gamedate)

        Returns:
            str | None: Formatted date string (YYYY-MM-DD) or None
        """
        gamedate = self.opts.get('gamedate')

        if not gamedate:
            return None

        # Handle both YYYYMMDD and YYYY-MM-DD formats
        gamedate_str = str(gamedate)

        # If already formatted (contains dashes), return as-is
        if '-' in gamedate_str:
            return gamedate_str

        # Convert YYYYMMDD → YYYY-MM-DD
        if len(gamedate_str) == 8:
            return f"{gamedate_str[0:4]}-{gamedate_str[4:6]}-{gamedate_str[6:8]}"

        # Invalid format, log warning and return None
        logger.warning(f"Invalid gamedate format: {gamedate_str}")
        return None

    def _log_execution_to_bigquery(self):
        """
        Log successful execution to nba_orchestration.scraper_execution_log.

        Uses 3-status system (success/no_data) based on record_count.
        Never fails the scraper - logs errors but continues.
        """
        try:
            from shared.utils.bigquery_utils import insert_bigquery_rows
            from shared.config.sport_config import get_orchestration_dataset

            source, environment, triggered_by = self._determine_execution_source()
            status, record_count = self._determine_execution_status()

            now = datetime.now(timezone.utc)

            # Get start_time, ensure it's a datetime, then convert to ISO
            start_time = self.stats.get('start_time', now)
            if isinstance(start_time, datetime):
                triggered_at_iso = start_time.isoformat()
            else:
                triggered_at_iso = now.isoformat()

            # Extract game_date from opts.gamedate (e.g., '20260102' → '2026-01-02')
            game_date = self._extract_game_date()

            record = {
                'execution_id': self.run_id,
                'scraper_name': self._get_scraper_name(),
                'workflow': self.opts.get('workflow', 'MANUAL'),
                'game_date': game_date,  # NEW: Track what date's data was found
                'status': status,
                'triggered_at': triggered_at_iso,  # ✅ FIXED: ISO string
                'completed_at': now.isoformat(),   # ✅ FIXED: ISO string
                'duration_seconds': self.stats.get('total_runtime', 0),
                'source': source,
                'environment': environment,
                'triggered_by': triggered_by,
                'gcs_path': self.opts.get('gcs_output_path'),
                'data_summary': json.dumps({
                    'record_count': record_count,
                    'scraper_stats': self.get_scraper_stats(),
                    'is_empty_report': status == 'no_data'
                }),
                'error_type': None,
                'error_message': None,
                'retry_count': self.download_retry_count,
                'recovery': self.opts.get('recovery', False),
                'run_id': self.run_id,
                'opts': json.dumps({k: v for k, v in self.opts.items()
                        if k not in ['password', 'api_key', 'token', 'proxyUrl']}),
                'created_at': now.isoformat()      # ✅ FIXED: ISO string
            }

            orchestration_dataset = get_orchestration_dataset()
            insert_bigquery_rows(f'{orchestration_dataset}.scraper_execution_log', [record])
            logger.info(f"✅ Orchestration logged: {status} ({record_count} records) from {source}")

        except Exception as e:
            # Don't fail the scraper if logging fails
            logger.error(f"Failed to log execution to orchestration: {e}")
            # Still capture in Sentry for alerting
            try:
                sentry_sdk.capture_exception(e)
            except ImportError:
                logger.debug("Sentry SDK not installed, skipping exception capture")
            except Exception as sentry_error:
                logger.debug(f"Sentry capture failed (non-critical): {sentry_error}")

    def _log_failed_execution_to_bigquery(self, error: Exception):
        """
        Log failed execution to nba_orchestration.scraper_execution_log.

        Status is always 'failed' with error details captured.
        Never fails the scraper - logs errors but continues.

        Args:
            error: The exception that caused the failure
        """
        try:
            from shared.utils.bigquery_utils import insert_bigquery_rows
            from shared.config.sport_config import get_orchestration_dataset

            source, environment, triggered_by = self._determine_execution_source()
            now = datetime.now(timezone.utc)

            # Get start_time, ensure it's a datetime, then convert to ISO
            start_time = self.stats.get('start_time', now)
            if isinstance(start_time, datetime):
                triggered_at_iso = start_time.isoformat()
            else:
                triggered_at_iso = now.isoformat()

            # Extract game_date from opts.gamedate (e.g., '20260102' → '2026-01-02')
            game_date = self._extract_game_date()

            record = {
                'execution_id': self.run_id,
                'scraper_name': self._get_scraper_name(),
                'workflow': self.opts.get('workflow', 'MANUAL'),
                'game_date': game_date,  # NEW: Track what date's data was found
                'status': 'failed',
                'triggered_at': triggered_at_iso,  # ✅ FIXED: ISO string
                'completed_at': None,
                'duration_seconds': None,
                'source': source,
                'environment': environment,
                'triggered_by': triggered_by,
                'gcs_path': None,
                'data_summary': None,
                'error_type': error.__class__.__name__,
                'error_message': str(error)[:1000],  # Truncate very long errors
                'retry_count': self.download_retry_count,
                'recovery': self.opts.get('recovery', False),
                'run_id': self.run_id,
                'opts': json.dumps({k: v for k, v in self.opts.items()
                        if k not in ['password', 'api_key', 'token', 'proxyUrl']}),
                'created_at': now.isoformat()      # ✅ FIXED: ISO string
            }

            orchestration_dataset = get_orchestration_dataset()
            insert_bigquery_rows(f'{orchestration_dataset}.scraper_execution_log', [record])
            logger.info(f"✅ Orchestration logged failure from {source}: {error.__class__.__name__}")

        except Exception as e:
            # Don't fail the scraper if logging fails
            logger.error(f"Failed to log failed execution to orchestration: {e}")
            # Still capture in Sentry
            try:
                sentry_sdk.capture_exception(e)
            except ImportError:
                logger.debug("Sentry SDK not installed, skipping exception capture")
            except Exception as sentry_error:
                logger.debug(f"Sentry capture failed (non-critical): {sentry_error}")

    def _log_scraper_failure_for_backfill(self, error: Exception):
        """
        Log scraper failure to nba_orchestration.scraper_failures for automatic backfill.

        When a scraper fails for a specific date, this logs it so the recovery system
        can automatically backfill when the scraper starts working again.

        Uses MERGE to upsert: if already failed for this date, increment retry_count.
        """
        try:
            game_date = self._extract_game_date()
            if not game_date:
                logger.debug("No game_date in opts - skipping backfill failure logging")
                return

            from google.cloud import bigquery
            client = bigquery.Client()

            # Use MERGE to upsert - increment retry_count if already exists
            from shared.config.gcp_config import get_project_id
            project_id = get_project_id()
            query = f"""
            MERGE INTO `{project_id}.nba_orchestration.scraper_failures` AS target
            USING (SELECT @game_date as game_date, @scraper_name as scraper_name) AS source
            ON target.game_date = source.game_date AND target.scraper_name = source.scraper_name
            WHEN MATCHED AND target.backfilled = FALSE THEN
                UPDATE SET
                    last_failed_at = CURRENT_TIMESTAMP(),
                    retry_count = target.retry_count + 1,
                    error_type = @error_type,
                    error_message = @error_message
            WHEN NOT MATCHED THEN
                INSERT (game_date, scraper_name, error_type, error_message, first_failed_at, last_failed_at, retry_count, backfilled)
                VALUES (@game_date, @scraper_name, @error_type, @error_message, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), 1, FALSE)
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                    bigquery.ScalarQueryParameter("scraper_name", "STRING", self._get_scraper_name()),
                    bigquery.ScalarQueryParameter("error_type", "STRING", error.__class__.__name__),
                    bigquery.ScalarQueryParameter("error_message", "STRING", str(error)[:500]),
                ]
            )

            client.query(query, job_config=job_config).result()
            logger.info(f"📋 Logged failure for backfill: {self._get_scraper_name()} / {game_date}")

        except Exception as e:
            # Don't fail the scraper if logging fails
            logger.warning(f"Failed to log scraper failure for backfill: {e}")
