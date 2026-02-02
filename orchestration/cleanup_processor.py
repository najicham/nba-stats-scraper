"""
orchestration/cleanup_processor.py

Cleanup Processor - Self-healing for Phase 1→2 handoff failures

Finds GCS files that were never processed by Phase 2 and republishes them.

How it works:
1. Query scraper_execution_log for successful scrapes (last hour)
2. Check if those files have corresponding BigQuery records in Phase 2 tables
3. If missing, republish Pub/Sub message
4. Log cleanup operation
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import pytz

from google.cloud import pubsub_v1
from google.api_core.exceptions import GoogleAPIError
from shared.utils.bigquery_utils import execute_bigquery, insert_bigquery_rows
from shared.utils.notification_system import notify_warning, notify_error
from shared.config.pubsub_topics import TOPICS
from shared.config.gcp_config import get_project_id
from orchestration.config_loader import WorkflowConfig

logger = logging.getLogger(__name__)

# Global config instance for cleanup settings
_workflow_config = WorkflowConfig()


class CleanupProcessor:
    """
    Finds GCS files that were never processed by Phase 2 and republishes them.
    
    How it works:
    1. Query scraper_execution_log for successful scrapes (last hour)
    2. Check if those files have corresponding BigQuery records in Phase 2 tables
    3. If missing, republish Pub/Sub message
    4. Log cleanup operation
    """
    
    VERSION = "1.0"
    
    # Default notification threshold if not configured
    DEFAULT_NOTIFICATION_THRESHOLD = 5

    def __init__(self, lookback_hours: int = None, min_file_age_minutes: int = 30, project_id: str = None):
        """
        Initialize cleanup processor.

        Args:
            lookback_hours: How far back to check for files (default: from config or 4 hours)
            min_file_age_minutes: Only process files older than this (avoid race conditions)
            project_id: GCP project ID for Pub/Sub publishing
        """
        # Load settings from config
        try:
            settings = _workflow_config.get_settings()
            cleanup_config = settings.get('cleanup_processor', {})
        except Exception as e:
            logger.warning(f"Failed to load cleanup config: {e}, using defaults")
            cleanup_config = {}

        # Lookback hours: parameter > env var > config > default
        default_lookback = cleanup_config.get('lookback_hours', 4)
        env_lookback = os.environ.get('CLEANUP_LOOKBACK_HOURS')
        if lookback_hours is not None:
            self.lookback_hours = lookback_hours
        elif env_lookback:
            self.lookback_hours = int(env_lookback)
        else:
            self.lookback_hours = default_lookback

        self.min_file_age_minutes = min_file_age_minutes
        self.ET = pytz.timezone('America/New_York')

        # Notification threshold: how many files need cleanup before alerting
        # This prevents noisy alerts for occasional missed files
        self.notification_threshold = cleanup_config.get(
            'notification_threshold',
            self.DEFAULT_NOTIFICATION_THRESHOLD
        )

        # Initialize Pub/Sub publisher for republishing missed files
        self.project_id = project_id or get_project_id()
        try:
            from shared.clients import get_pubsub_publisher
            self.publisher = get_pubsub_publisher()
        except ImportError:
            self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(
            self.project_id,
            TOPICS.PHASE1_SCRAPERS_COMPLETE
        )
        logger.info(f"CleanupProcessor initialized with topic: {self.topic_path}")
    
    def run(self) -> Dict[str, Any]:
        """
        Main cleanup operation.
        
        Returns:
            Dict with cleanup summary
        """
        cleanup_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)
        
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🔧 Cleanup Processor: Starting self-healing check")
        logger.info(f"   Cleanup ID: {cleanup_id}")
        logger.info(f"   Lookback: {self.lookback_hours}h")
        logger.info(f"   Min Age: {self.min_file_age_minutes}min")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        try:
            # Step 1: Find successful scraper executions
            scraper_files = self._get_recent_scraper_files()
            logger.info(f"📊 Found {len(scraper_files)} scraper files in last {self.lookback_hours}h")
            
            if not scraper_files:
                logger.info("✅ No files to check, cleanup complete")
                return self._log_cleanup(cleanup_id, start_time, [], 0, 0)
            
            # Step 2: Check which were processed by Phase 2
            processed_files = self._get_processed_files()
            logger.info(f"📊 Found {len(processed_files)} files processed by Phase 2")
            
            # Step 3: Find the gap (files not processed)
            missing_files = self._find_missing_files(scraper_files, processed_files)
            
            if not missing_files:
                logger.info("✅ All files processed, no cleanup needed")
                return self._log_cleanup(cleanup_id, start_time, [], len(scraper_files), 0)
            
            logger.warning(f"⚠️  Found {len(missing_files)} files not processed by Phase 2")
            
            # Step 4: Republish Pub/Sub messages
            republished_count = self._republish_messages(missing_files)
            
            # Step 5: Log cleanup operation
            summary = self._log_cleanup(
                cleanup_id, 
                start_time, 
                missing_files, 
                len(scraper_files),
                republished_count
            )
            
            # CRITICAL: Detect retry storm (likely bug in table name or config)
            # If >80% of files are "missing", something is wrong with our detection
            # NOTE: Lowered threshold from 50 to 10 to catch small scrapers at 100% missing
            missing_percentage = (len(missing_files) / len(scraper_files) * 100) if scraper_files else 0
            if missing_percentage > 80 and len(missing_files) > 10:
                logger.critical(
                    f"🚨 RETRY STORM DETECTED: {missing_percentage:.1f}% of files ({len(missing_files)}/{len(scraper_files)}) "
                    f"appear missing. This likely indicates a bug in CleanupProcessor table names or config. "
                    f"Check that all table names in phase2_tables match actual BigQuery tables."
                )
                try:
                    notify_error(
                        title="🚨 CRITICAL: CleanupProcessor Retry Storm Detected",
                        message=f"{missing_percentage:.1f}% of files appear missing - likely a bug causing excessive republishes",
                        details={
                            'cleanup_id': cleanup_id,
                            'files_checked': len(scraper_files),
                            'missing_files': len(missing_files),
                            'missing_percentage': f"{missing_percentage:.1f}%",
                            'likely_cause': 'Table name mismatch in phase2_tables list',
                            'fix': 'Verify all table names in cleanup_processor.py match actual BigQuery tables',
                            'scrapers_affected': list(set(f['scraper_name'] for f in missing_files))[:10]  # Limit to 10
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send retry storm notification: {notify_ex}")

            # Send notification if significant cleanup needed (configurable threshold)
            # This prevents noisy alerts for occasional missed files
            elif len(missing_files) >= self.notification_threshold:
                try:
                    notify_warning(
                        title="Phase 1 Cleanup: Multiple Files Republished",
                        message=f"Republished {republished_count} missed Pub/Sub messages (threshold: {self.notification_threshold})",
                        details={
                            'cleanup_id': cleanup_id,
                            'files_checked': len(scraper_files),
                            'missing_files': len(missing_files),
                            'republished': republished_count,
                            'notification_threshold': self.notification_threshold,
                            'scrapers_affected': list(set(f['scraper_name'] for f in missing_files))
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"✅ Cleanup complete: {republished_count}/{len(missing_files)} republished")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            
            return summary
            
        except Exception as e:
            logger.error(f"Cleanup processor failed: {e}", exc_info=True)
            
            try:
                notify_error(
                    title="Phase 1 Cleanup Processor Failed",
                    message=f"Self-healing cleanup failed: {str(e)}",
                    details={
                        'cleanup_id': cleanup_id,
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="cleanup_processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send error notification: {notify_ex}")
            
            # Log failed cleanup
            self._log_cleanup(
                cleanup_id,
                start_time,
                [],
                0,
                0,
                errors=[str(e)]
            )
            
            raise
    
    def _get_recent_scraper_files(self) -> List[Dict[str, Any]]:
        """
        Get successful scraper executions from last N hours.
        Only include files old enough to have been processed.
        """
        query = f"""
            SELECT 
                execution_id,
                scraper_name,
                gcs_path,
                triggered_at,
                TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), triggered_at, MINUTE) as age_minutes
            FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
            WHERE status = 'success'
              AND triggered_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.lookback_hours} HOUR)
              AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), triggered_at, MINUTE) >= {self.min_file_age_minutes}
              AND gcs_path IS NOT NULL
            ORDER BY triggered_at DESC
        """
        
        return execute_bigquery(query)
    
    def _get_processed_files(self) -> set:
        """
        Get files that were processed by Phase 2.
        Checks all Phase 2 raw tables for source_file_path.
        
        Note: This assumes Phase 2 tables have source_file_path field
        Adjust query based on your actual Phase 2 schema
        """
        # All Phase 2 raw tables that track source_file_path AND have processed_at column
        # IMPORTANT: Table names must match actual processor output tables
        # Verified against: grep -rh "table_name = 'nba_raw" data_processors/raw/
        # Last verified: Session 73 (2026-02-02)
        #
        # NOTE: Some tables (nbac_player_movement, nbac_team_rosters, nbac_player_list,
        # nbac_gamebook_game_info) do not have processed_at column and are excluded
        # from this cleanup query to prevent BigQuery errors.
        phase2_tables = [
            # NBAC (nba.com) tables
            'nbac_schedule',
            'nbac_team_boxscore',
            'nbac_play_by_play',
            'nbac_injury_report',
            'nbac_scoreboard_v2',
            'nbac_gamebook_player_stats',  # Was: nbac_gamebook_pdf
            # Excluded: 'nbac_player_movement' - no processed_at column
            'nbac_referee_game_assignments',  # Was: nbac_referee
            # BallDontLie tables
            'bdl_player_boxscores',
            'bdl_active_players_current',  # Was: bdl_active_players
            'bdl_injuries',
            'bdl_standings',
            'bdl_live_boxscores',
            # ESPN tables
            'espn_scoreboard',
            'espn_team_rosters',  # Was: espn_rosters
            'espn_boxscores',  # Was: espn_box_scores
            # Basketball Reference tables
            'br_rosters_current',  # Was: br_rosters
            # BigDataBall tables
            'bigdataball_play_by_play',
            # Odds API tables
            'odds_api_game_lines',  # Was: odds_game_lines
            'odds_api_player_points_props',  # Was: odds_player_props
            # BettingPros tables
            'bettingpros_player_points_props',  # Was: bp_player_props
        ]

        # Build UNION ALL query for all tables
        table_queries = []
        for table in phase2_tables:
            table_queries.append(f"""
                SELECT source_file_path FROM `nba-props-platform.nba_raw.{table}`
                WHERE processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.lookback_hours + 1} HOUR)
            """)

        query = f"""
            SELECT DISTINCT source_file_path
            FROM (
                {' UNION ALL '.join(table_queries)}
            )
            WHERE source_file_path IS NOT NULL
        """
        
        try:
            result = execute_bigquery(query)
            return {row['source_file_path'] for row in result}
        except GoogleAPIError as e:
            logger.error(f"Failed to get processed files: {e}", exc_info=True)
            # Return empty set to be safe - will trigger republish
            return set()
    
    def _find_missing_files(self, scraper_files: List[Dict], processed_files: set) -> List[Dict]:
        """Find files that weren't processed by Phase 2."""
        missing = []
        
        for file_info in scraper_files:
            gcs_path = file_info['gcs_path']
            
            if gcs_path not in processed_files:
                missing.append(file_info)
                logger.warning(
                    f"⚠️  Missing: {file_info['scraper_name']} - {gcs_path} "
                    f"(age: {file_info['age_minutes']}min)"
                )
        
        return missing
    
    def _republish_messages(self, missing_files: List[Dict]) -> int:
        """
        Republish Pub/Sub messages for missing files to trigger Phase 2 reprocessing.

        Publishes to the Phase 1 scrapers-complete topic, which will trigger
        the Phase 2 raw processors to re-process the GCS files.

        Implements exponential backoff retry (3 attempts per message) to handle
        transient Pub/Sub failures.

        Args:
            missing_files: List of file info dicts with scraper_name, gcs_path, etc.

        Returns:
            Number of successfully republished messages
        """
        import random
        import time

        MAX_RETRIES = 3
        BASE_DELAY = 1.0  # seconds
        MAX_DELAY = 10.0  # seconds

        republished_count = 0
        failed_files = []

        for file_info in missing_files:
            success = False
            last_error = None

            for attempt in range(MAX_RETRIES):
                try:
                    # Create recovery message matching the scraper output format
                    message = {
                        'scraper_name': file_info['scraper_name'],
                        'gcs_path': file_info['gcs_path'],
                        'execution_id': f"recovery-{uuid.uuid4().hex[:8]}",
                        'original_execution_id': file_info['execution_id'],
                        'original_triggered_at': file_info['triggered_at'].isoformat() if hasattr(file_info.get('triggered_at'), 'isoformat') else str(file_info.get('triggered_at')),
                        'recovery': True,
                        'recovery_reason': 'cleanup_processor',
                        'recovery_timestamp': datetime.now(timezone.utc).isoformat(),
                        'recovery_attempt': attempt + 1,
                        'status': 'success',  # Mimics scraper success message
                    }

                    # Publish to Phase 1 complete topic
                    message_data = json.dumps(message).encode('utf-8')
                    future = self.publisher.publish(self.topic_path, data=message_data)

                    # Wait for publish to complete (with timeout)
                    message_id = future.result(timeout=10.0)

                    logger.info(
                        f"🔄 Republished {file_info['scraper_name']} to Pub/Sub "
                        f"(message_id={message_id}, gcs_path={file_info['gcs_path']}, attempt={attempt + 1})"
                    )
                    republished_count += 1
                    success = True
                    break  # Success, exit retry loop

                except (GoogleAPIError, TimeoutError) as e:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        # Calculate delay with exponential backoff and jitter
                        delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                        logger.warning(
                            f"⚠️ Pub/Sub publish failed for {file_info['scraper_name']} "
                            f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"❌ Failed to republish {file_info['scraper_name']} after {MAX_RETRIES} attempts: {e}",
                            exc_info=True
                        )

            if not success:
                failed_files.append({
                    'scraper_name': file_info['scraper_name'],
                    'gcs_path': file_info['gcs_path'],
                    'error': str(last_error)
                })

        if republished_count > 0:
            logger.info(f"✅ Successfully republished {republished_count}/{len(missing_files)} messages")

        if failed_files:
            logger.error(
                f"❌ {len(failed_files)} files failed all retry attempts: "
                f"{[f['scraper_name'] for f in failed_files]}"
            )
            # Send notification for failed files
            try:
                notify_error(
                    title="Cleanup Processor: Pub/Sub Publish Failures",
                    message=f"{len(failed_files)} files failed to republish after {MAX_RETRIES} retries",
                    details={
                        'failed_files': failed_files,
                        'total_attempted': len(missing_files),
                        'successful': republished_count
                    },
                    processor_name="cleanup_processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send failure notification: {notify_ex}")

        return republished_count
    
    def _log_cleanup(
        self,
        cleanup_id: str,
        start_time: datetime,
        missing_files: List[Dict],
        files_checked: int,
        republished_count: int,
        errors: List[str] = None
    ) -> Dict[str, Any]:
        """Log cleanup operation to BigQuery."""
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # Prepare missing files details
        missing_files_records = []
        for f in missing_files:
            # Convert datetime to ISO format string for JSON serialization
            triggered_at = f['triggered_at']
            if hasattr(triggered_at, 'isoformat'):
                triggered_at = triggered_at.isoformat()
            elif not isinstance(triggered_at, str):
                triggered_at = str(triggered_at)

            missing_files_records.append({
                'scraper_name': f['scraper_name'],
                'gcs_path': f['gcs_path'],
                'triggered_at': triggered_at,
                'age_minutes': f['age_minutes'],
                'republished': True  # Assume success if in this list
            })
        
        record = {
            'cleanup_id': cleanup_id,
            'cleanup_time': datetime.now(timezone.utc).isoformat(),
            'files_checked': files_checked,
            'missing_files_found': len(missing_files),
            'republished_count': republished_count,
            'missing_files': missing_files_records,
            'errors': errors or [],
            'duration_seconds': duration
        }
        
        try:
            insert_bigquery_rows('nba_orchestration.cleanup_operations', [record])
            logger.info(f"✅ Logged cleanup operation to BigQuery")
        except GoogleAPIError as e:
            logger.error(f"Failed to log cleanup operation: {e}", exc_info=True)
        
        return {
            'cleanup_id': cleanup_id,
            'files_checked': files_checked,
            'missing_files_found': len(missing_files),
            'republished_count': republished_count,
            'duration_seconds': duration
        }
