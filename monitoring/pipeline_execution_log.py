#!/usr/bin/env python3
"""
Pipeline Execution Log - End-to-End Latency Tracking (P2-MON-2)

Provides granular event logging at each pipeline phase boundary for:
- Game-level execution tracking (game_id, phase, start_time, end_time)
- Phase latency calculation
- Total pipeline latency from Phase 1 to Phase 6
- Bottleneck identification and performance optimization

Architecture:
- Event-based logging: Each phase start/end creates an event
- BigQuery storage: nba_analytics.pipeline_execution_log table
- Integration points: Scrapers, Processors, Orchestrators
- Dashboard: Real-time latency visibility

Table Schema (nba_analytics.pipeline_execution_log):
- event_id: STRING (unique event identifier)
- game_id: STRING (NBA game ID for game-level tracking)
- game_date: DATE (date being processed)
- phase: STRING (phase1_scrape, phase2_raw, phase3_analytics, phase4_precompute, phase5_predictions, phase6_export)
- event_type: STRING (start, end, error)
- processor_name: STRING (specific processor or scraper name)
- started_at: TIMESTAMP (when the phase/processor started)
- ended_at: TIMESTAMP (when the phase/processor ended)
- duration_seconds: FLOAT64 (elapsed time)
- status: STRING (running, success, failed, skipped)
- records_processed: INT64 (number of records handled)
- error_message: STRING (error details if failed)
- metadata: JSON (additional context like trigger info)
- logged_at: TIMESTAMP (when this event was logged)

Usage:
    # In a processor or scraper:
    from monitoring.pipeline_execution_log import PipelineExecutionLogger

    logger = PipelineExecutionLogger()

    # Log phase start
    event_id = logger.log_phase_start(
        game_id='0022400123',
        game_date='2026-01-23',
        phase='phase3_analytics',
        processor_name='PlayerGameSummaryProcessor'
    )

    try:
        # ... processing logic ...
        logger.log_phase_end(event_id, status='success', records_processed=150)
    except Exception as e:
        logger.log_phase_end(event_id, status='failed', error=e)

    # Query latency metrics
    metrics = logger.get_game_latency('0022400123', '2026-01-23')

Created: 2026-01-23
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional, Any, Union

from google.cloud import bigquery

# Add project root to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config.gcp_config import get_project_id
from shared.utils.bigquery_batch_writer import get_batch_writer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = get_project_id()
EXECUTION_LOG_TABLE = 'nba_analytics.pipeline_execution_log'

# Phase definitions with expected order
PIPELINE_PHASES = [
    'phase1_scrape',
    'phase2_raw',
    'phase3_analytics',
    'phase4_precompute',
    'phase5_predictions',
    'phase6_export',
]

# Phase latency thresholds (seconds) - for alerting
PHASE_LATENCY_THRESHOLDS = {
    'phase1_scrape': 180,        # 3 minutes per game
    'phase2_raw': 300,           # 5 minutes
    'phase3_analytics': 300,     # 5 minutes
    'phase4_precompute': 600,    # 10 minutes
    'phase5_predictions': 300,   # 5 minutes
    'phase6_export': 180,        # 3 minutes
    'total_pipeline': 1800,      # 30 minutes end-to-end
}


class PipelineExecutionLogger:
    """
    Log pipeline execution events for end-to-end latency tracking.

    Provides methods to:
    - Log phase start/end events
    - Calculate phase and total latencies
    - Query historical execution data
    - Identify bottlenecks
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self._bq_client = None
        self._active_events: Dict[str, Dict] = {}  # Track in-progress events

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    # =========================================================================
    # EVENT LOGGING
    # =========================================================================

    def log_phase_start(
        self,
        game_id: str,
        game_date: Union[str, date],
        phase: str,
        processor_name: str,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Log the start of a pipeline phase for a game.

        Args:
            game_id: NBA game ID (e.g., '0022400123')
            game_date: Date being processed
            phase: Pipeline phase (phase1_scrape, phase2_raw, etc.)
            processor_name: Name of the processor/scraper
            metadata: Additional context (trigger info, etc.)

        Returns:
            event_id: Unique identifier for this event (use to log end)
        """
        # Generate event ID
        event_id = f"{phase}_{game_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        # Parse game_date
        if isinstance(game_date, str):
            game_date_str = game_date
        else:
            game_date_str = game_date.isoformat()

        started_at = datetime.now(timezone.utc)

        # Store in active events for duration calculation
        self._active_events[event_id] = {
            'game_id': game_id,
            'game_date': game_date_str,
            'phase': phase,
            'processor_name': processor_name,
            'started_at': started_at,
            'metadata': metadata,
        }

        # Build event record
        record = {
            'event_id': event_id,
            'game_id': game_id,
            'game_date': game_date_str,
            'phase': phase,
            'event_type': 'start',
            'processor_name': processor_name,
            'started_at': started_at.isoformat(),
            'status': 'running',
            'metadata': json.dumps(metadata) if metadata else None,
            'logged_at': started_at.isoformat(),
        }

        # Insert to BigQuery
        self._insert_event(record)

        logger.info(f"Phase start logged: {phase}/{processor_name} for game {game_id}")

        return event_id

    def log_phase_end(
        self,
        event_id: str,
        status: str = 'success',
        records_processed: int = 0,
        error: Optional[Exception] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Log the end of a pipeline phase.

        Args:
            event_id: Event ID from log_phase_start()
            status: Final status (success, failed, skipped)
            records_processed: Number of records processed
            error: Exception if failed
            metadata: Additional context
        """
        ended_at = datetime.now(timezone.utc)

        # Get start info from active events
        start_info = self._active_events.pop(event_id, None)

        if start_info:
            started_at = start_info['started_at']
            duration_seconds = (ended_at - started_at).total_seconds()
            game_id = start_info['game_id']
            game_date = start_info['game_date']
            phase = start_info['phase']
            processor_name = start_info['processor_name']

            # Merge metadata
            if start_info.get('metadata') and metadata:
                merged_metadata = {**start_info['metadata'], **metadata}
            elif metadata:
                merged_metadata = metadata
            else:
                merged_metadata = start_info.get('metadata')
        else:
            # Event not found in active events - try to extract from event_id
            logger.warning(f"Event {event_id} not found in active events")
            duration_seconds = None
            started_at = None
            game_id = None
            game_date = None
            phase = event_id.split('_')[0] if '_' in event_id else 'unknown'
            processor_name = None
            merged_metadata = metadata

        # Build error message
        error_message = None
        if error:
            error_message = f"{type(error).__name__}: {str(error)}"

        # Build event record
        record = {
            'event_id': event_id,
            'game_id': game_id,
            'game_date': game_date,
            'phase': phase,
            'event_type': 'end',
            'processor_name': processor_name,
            'started_at': started_at.isoformat() if started_at else None,
            'ended_at': ended_at.isoformat(),
            'duration_seconds': duration_seconds,
            'status': status,
            'records_processed': records_processed,
            'error_message': error_message,
            'metadata': json.dumps(merged_metadata) if merged_metadata else None,
            'logged_at': ended_at.isoformat(),
        }

        # Insert to BigQuery
        self._insert_event(record)

        # Log with appropriate level
        if status == 'failed':
            logger.error(f"Phase end logged: {phase} FAILED for game {game_id}: {error_message}")
        else:
            logger.info(f"Phase end logged: {phase}/{status} for game {game_id} ({duration_seconds:.1f}s, {records_processed} records)")

    def log_phase_event(
        self,
        game_id: str,
        game_date: Union[str, date],
        phase: str,
        processor_name: str,
        event_type: str,
        status: str = 'running',
        records_processed: int = 0,
        duration_seconds: float = None,
        error_message: str = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Log a standalone pipeline event (for external integrations).

        Useful when start/end pattern doesn't fit (e.g., async processing).

        Args:
            game_id: NBA game ID
            game_date: Date being processed
            phase: Pipeline phase
            processor_name: Name of processor/scraper
            event_type: Type of event (start, end, checkpoint, error)
            status: Current status
            records_processed: Records processed so far
            duration_seconds: Duration if known
            error_message: Error details if applicable
            metadata: Additional context

        Returns:
            event_id: Unique event identifier
        """
        event_id = f"{phase}_{game_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        # Parse game_date
        if isinstance(game_date, str):
            game_date_str = game_date
        else:
            game_date_str = game_date.isoformat()

        logged_at = datetime.now(timezone.utc)

        record = {
            'event_id': event_id,
            'game_id': game_id,
            'game_date': game_date_str,
            'phase': phase,
            'event_type': event_type,
            'processor_name': processor_name,
            'started_at': logged_at.isoformat() if event_type == 'start' else None,
            'ended_at': logged_at.isoformat() if event_type == 'end' else None,
            'duration_seconds': duration_seconds,
            'status': status,
            'records_processed': records_processed,
            'error_message': error_message,
            'metadata': json.dumps(metadata) if metadata else None,
            'logged_at': logged_at.isoformat(),
        }

        self._insert_event(record)

        return event_id

    def _insert_event(self, record: Dict) -> None:
        """Insert event record to BigQuery."""
        try:
            # Ensure table exists
            self._ensure_table_exists()

            # Remove None values
            record = {k: v for k, v in record.items() if v is not None}

            # Use BigQueryBatchWriter for efficient writes (bypasses load job quota)
            # See: shared/utils/bigquery_batch_writer.py
            table_ref = f"{self.project_id}.{EXECUTION_LOG_TABLE}"

            try:
                writer = get_batch_writer(table_ref)
                writer.add_record(record)

            except Exception as insert_error:
                logger.warning(f"Error inserting execution log: {insert_error}")

        except Exception as e:
            # Don't fail the pipeline if logging fails
            logger.error(f"Failed to insert execution log (non-fatal): {e}")

    def _ensure_table_exists(self) -> None:
        """Ensure the execution log table exists in BigQuery."""
        schema = [
            bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("game_id", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("game_date", "DATE", mode="NULLABLE"),
            bigquery.SchemaField("phase", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("event_type", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("processor_name", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("started_at", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("ended_at", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("duration_seconds", "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField("status", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("records_processed", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("error_message", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("metadata", "JSON", mode="NULLABLE"),
            bigquery.SchemaField("logged_at", "TIMESTAMP", mode="REQUIRED"),
        ]

        table_ref = f"{self.project_id}.{EXECUTION_LOG_TABLE}"

        try:
            self.bq_client.get_table(table_ref)
            logger.debug(f"Table {table_ref} exists")
        except Exception:
            # Table doesn't exist, create it
            logger.info(f"Creating table {table_ref}")
            table = bigquery.Table(table_ref, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="game_date"
            )
            self.bq_client.create_table(table)
            logger.info(f"Created table {table_ref}")

    # =========================================================================
    # LATENCY QUERIES
    # =========================================================================

    def get_game_latency(
        self,
        game_id: str,
        game_date: Union[str, date]
    ) -> Dict:
        """
        Get latency metrics for a specific game.

        Args:
            game_id: NBA game ID
            game_date: Date of the game

        Returns:
            Dict with phase latencies and total pipeline latency
        """
        if isinstance(game_date, date):
            game_date = game_date.isoformat()

        query = f"""
        WITH phase_times AS (
            SELECT
                phase,
                processor_name,
                MIN(started_at) as phase_start,
                MAX(ended_at) as phase_end,
                MAX(duration_seconds) as phase_duration,
                MAX(status) as final_status,
                SUM(records_processed) as total_records
            FROM `{self.project_id}.{EXECUTION_LOG_TABLE}`
            WHERE game_id = @game_id
              AND game_date = @game_date
              AND event_type = 'end'
            GROUP BY phase, processor_name
        )
        SELECT
            phase,
            processor_name,
            phase_start,
            phase_end,
            phase_duration,
            final_status,
            total_records
        FROM phase_times
        ORDER BY phase_start
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            results = list(self.bq_client.query(query, job_config=job_config).result(timeout=60))

            phase_latencies = {}
            pipeline_start = None
            pipeline_end = None

            for row in results:
                phase_key = f"{row.phase}_{row.processor_name}"
                phase_latencies[phase_key] = {
                    'phase': row.phase,
                    'processor': row.processor_name,
                    'started_at': row.phase_start.isoformat() if row.phase_start else None,
                    'ended_at': row.phase_end.isoformat() if row.phase_end else None,
                    'duration_seconds': row.phase_duration,
                    'status': row.final_status,
                    'records_processed': row.total_records,
                }

                # Track pipeline boundaries
                if row.phase_start:
                    if pipeline_start is None or row.phase_start < pipeline_start:
                        pipeline_start = row.phase_start
                if row.phase_end:
                    if pipeline_end is None or row.phase_end > pipeline_end:
                        pipeline_end = row.phase_end

            # Calculate total pipeline latency
            total_latency = None
            if pipeline_start and pipeline_end:
                total_latency = (pipeline_end - pipeline_start).total_seconds()

            return {
                'game_id': game_id,
                'game_date': game_date,
                'phase_latencies': phase_latencies,
                'pipeline_start': pipeline_start.isoformat() if pipeline_start else None,
                'pipeline_end': pipeline_end.isoformat() if pipeline_end else None,
                'total_latency_seconds': total_latency,
                'total_latency_minutes': round(total_latency / 60, 1) if total_latency else None,
                'phases_completed': len(phase_latencies),
            }

        except Exception as e:
            logger.error(f"Error querying game latency: {e}")
            return {
                'game_id': game_id,
                'game_date': game_date,
                'error': str(e),
            }

    def get_date_latency_summary(
        self,
        game_date: Union[str, date]
    ) -> Dict:
        """
        Get latency summary for all games on a date.

        Args:
            game_date: Date to query

        Returns:
            Dict with per-game latencies and aggregated stats
        """
        if isinstance(game_date, date):
            game_date = game_date.isoformat()

        query = f"""
        WITH game_phases AS (
            SELECT
                game_id,
                phase,
                MIN(started_at) as phase_start,
                MAX(ended_at) as phase_end,
                MAX(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as has_failure
            FROM `{self.project_id}.{EXECUTION_LOG_TABLE}`
            WHERE game_date = @game_date
              AND event_type = 'end'
              AND game_id IS NOT NULL
            GROUP BY game_id, phase
        ),
        game_summary AS (
            SELECT
                game_id,
                MIN(phase_start) as pipeline_start,
                MAX(phase_end) as pipeline_end,
                COUNT(DISTINCT phase) as phases_completed,
                MAX(has_failure) as has_failure
            FROM game_phases
            GROUP BY game_id
        )
        SELECT
            game_id,
            pipeline_start,
            pipeline_end,
            TIMESTAMP_DIFF(pipeline_end, pipeline_start, SECOND) as total_latency_seconds,
            phases_completed,
            has_failure
        FROM game_summary
        ORDER BY pipeline_start
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        try:
            results = list(self.bq_client.query(query, job_config=job_config).result(timeout=60))

            games = []
            total_latencies = []

            for row in results:
                game_data = {
                    'game_id': row.game_id,
                    'pipeline_start': row.pipeline_start.isoformat() if row.pipeline_start else None,
                    'pipeline_end': row.pipeline_end.isoformat() if row.pipeline_end else None,
                    'total_latency_seconds': row.total_latency_seconds,
                    'phases_completed': row.phases_completed,
                    'status': 'failed' if row.has_failure else 'success',
                }
                games.append(game_data)

                if row.total_latency_seconds:
                    total_latencies.append(row.total_latency_seconds)

            # Aggregate stats
            stats = {}
            if total_latencies:
                stats = {
                    'avg_latency_seconds': round(sum(total_latencies) / len(total_latencies), 1),
                    'min_latency_seconds': min(total_latencies),
                    'max_latency_seconds': max(total_latencies),
                    'p50_latency_seconds': sorted(total_latencies)[len(total_latencies) // 2],
                }

            return {
                'game_date': game_date,
                'games': games,
                'game_count': len(games),
                'completed_count': sum(1 for g in games if g['status'] == 'success'),
                'failed_count': sum(1 for g in games if g['status'] == 'failed'),
                'stats': stats,
            }

        except Exception as e:
            logger.error(f"Error querying date latency summary: {e}")
            return {
                'game_date': game_date,
                'error': str(e),
            }

    def get_phase_bottlenecks(
        self,
        days: int = 7
    ) -> List[Dict]:
        """
        Identify phase bottlenecks over the last N days.

        Args:
            days: Number of days to analyze

        Returns:
            List of phases sorted by average latency (slowest first)
        """
        query = f"""
        SELECT
            phase,
            processor_name,
            COUNT(*) as execution_count,
            ROUND(AVG(duration_seconds), 1) as avg_duration_seconds,
            ROUND(MIN(duration_seconds), 1) as min_duration_seconds,
            ROUND(MAX(duration_seconds), 1) as max_duration_seconds,
            ROUND(STDDEV(duration_seconds), 1) as stddev_duration_seconds,
            APPROX_QUANTILES(duration_seconds, 100)[OFFSET(50)] as p50_duration,
            APPROX_QUANTILES(duration_seconds, 100)[OFFSET(95)] as p95_duration,
            APPROX_QUANTILES(duration_seconds, 100)[OFFSET(99)] as p99_duration,
            COUNTIF(status = 'failed') as failure_count,
            ROUND(100.0 * COUNTIF(status = 'failed') / COUNT(*), 1) as failure_rate_pct
        FROM `{self.project_id}.{EXECUTION_LOG_TABLE}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
          AND event_type = 'end'
          AND duration_seconds IS NOT NULL
        GROUP BY phase, processor_name
        HAVING execution_count >= 5
        ORDER BY avg_duration_seconds DESC
        """

        try:
            results = list(self.bq_client.query(query).result(timeout=60))

            bottlenecks = []
            for row in results:
                threshold = PHASE_LATENCY_THRESHOLDS.get(row.phase, 300)

                bottlenecks.append({
                    'phase': row.phase,
                    'processor_name': row.processor_name,
                    'execution_count': row.execution_count,
                    'avg_duration_seconds': row.avg_duration_seconds,
                    'min_duration_seconds': row.min_duration_seconds,
                    'max_duration_seconds': row.max_duration_seconds,
                    'stddev_duration_seconds': row.stddev_duration_seconds,
                    'p50_duration': row.p50_duration,
                    'p95_duration': row.p95_duration,
                    'p99_duration': row.p99_duration,
                    'failure_count': row.failure_count,
                    'failure_rate_pct': row.failure_rate_pct,
                    'threshold_seconds': threshold,
                    'exceeds_threshold': row.avg_duration_seconds > threshold,
                })

            return bottlenecks

        except Exception as e:
            logger.error(f"Error querying phase bottlenecks: {e}")
            return []

    def get_recent_slow_executions(
        self,
        hours: int = 24,
        min_duration_seconds: int = 300
    ) -> List[Dict]:
        """
        Get recent slow executions for investigation.

        Args:
            hours: Hours to look back
            min_duration_seconds: Minimum duration to consider slow

        Returns:
            List of slow execution events
        """
        query = f"""
        SELECT
            event_id,
            game_id,
            game_date,
            phase,
            processor_name,
            started_at,
            ended_at,
            duration_seconds,
            status,
            records_processed,
            error_message
        FROM `{self.project_id}.{EXECUTION_LOG_TABLE}`
        WHERE logged_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
          AND event_type = 'end'
          AND duration_seconds >= {min_duration_seconds}
        ORDER BY duration_seconds DESC
        LIMIT 50
        """

        try:
            results = list(self.bq_client.query(query).result(timeout=60))

            return [
                {
                    'event_id': row.event_id,
                    'game_id': row.game_id,
                    'game_date': str(row.game_date) if row.game_date else None,
                    'phase': row.phase,
                    'processor_name': row.processor_name,
                    'started_at': row.started_at.isoformat() if row.started_at else None,
                    'ended_at': row.ended_at.isoformat() if row.ended_at else None,
                    'duration_seconds': row.duration_seconds,
                    'duration_minutes': round(row.duration_seconds / 60, 1),
                    'status': row.status,
                    'records_processed': row.records_processed,
                    'error_message': row.error_message[:200] if row.error_message else None,
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"Error querying slow executions: {e}")
            return []


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Global logger instance for simple usage
_execution_logger: Optional[PipelineExecutionLogger] = None


def get_execution_logger() -> PipelineExecutionLogger:
    """Get or create the global execution logger instance."""
    global _execution_logger
    if _execution_logger is None:
        _execution_logger = PipelineExecutionLogger()
    return _execution_logger


def log_phase_start(
    game_id: str,
    game_date: Union[str, date],
    phase: str,
    processor_name: str,
    metadata: Optional[Dict] = None
) -> str:
    """Convenience function to log phase start."""
    return get_execution_logger().log_phase_start(
        game_id=game_id,
        game_date=game_date,
        phase=phase,
        processor_name=processor_name,
        metadata=metadata
    )


def log_phase_end(
    event_id: str,
    status: str = 'success',
    records_processed: int = 0,
    error: Optional[Exception] = None,
    metadata: Optional[Dict] = None
) -> None:
    """Convenience function to log phase end."""
    get_execution_logger().log_phase_end(
        event_id=event_id,
        status=status,
        records_processed=records_processed,
        error=error,
        metadata=metadata
    )


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI for pipeline execution log queries."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Query pipeline execution logs and latency metrics"
    )
    parser.add_argument(
        '--game-id',
        type=str,
        help='Get latency for specific game ID'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Date to query (YYYY-MM-DD). Defaults to today.'
    )
    parser.add_argument(
        '--bottlenecks',
        action='store_true',
        help='Show phase bottlenecks'
    )
    parser.add_argument(
        '--slow',
        action='store_true',
        help='Show recent slow executions'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Days to look back for bottleneck analysis'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Hours to look back for slow executions'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )

    args = parser.parse_args()

    logger_instance = PipelineExecutionLogger()

    if args.bottlenecks:
        bottlenecks = logger_instance.get_phase_bottlenecks(days=args.days)
        if args.json:
            print(json.dumps(bottlenecks, indent=2))
        else:
            print("\nPHASE BOTTLENECKS (Last {} days)".format(args.days))
            print("=" * 80)
            for b in bottlenecks:
                status = "SLOW" if b['exceeds_threshold'] else "OK"
                print(f"{b['phase']}/{b['processor_name']}")
                print(f"  Avg: {b['avg_duration_seconds']}s, P95: {b['p95_duration']}s [{status}]")
                print(f"  Executions: {b['execution_count']}, Failures: {b['failure_rate_pct']}%")
        return

    if args.slow:
        slow_execs = logger_instance.get_recent_slow_executions(hours=args.hours)
        if args.json:
            print(json.dumps(slow_execs, indent=2))
        else:
            print("\nSLOW EXECUTIONS (Last {} hours)".format(args.hours))
            print("=" * 80)
            for s in slow_execs:
                print(f"{s['phase']}/{s['processor_name']} - {s['duration_minutes']}m")
                print(f"  Game: {s['game_id']}, Date: {s['game_date']}")
                if s['error_message']:
                    print(f"  Error: {s['error_message'][:100]}")
        return

    if args.game_id:
        game_date = args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
        result = logger_instance.get_game_latency(args.game_id, game_date)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\nGAME LATENCY: {args.game_id} ({game_date})")
            print("=" * 60)
            for key, phase in result.get('phase_latencies', {}).items():
                print(f"  {phase['phase']}/{phase['processor']}: {phase['duration_seconds']}s [{phase['status']}]")
            if result.get('total_latency_minutes'):
                print(f"\nTotal Pipeline: {result['total_latency_minutes']} minutes")
        return

    # Default: show date summary
    game_date = args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    result = logger_instance.get_date_latency_summary(game_date)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\nDATE SUMMARY: {game_date}")
        print("=" * 60)
        print(f"Games: {result['game_count']} (Completed: {result['completed_count']}, Failed: {result['failed_count']})")
        if result.get('stats'):
            print(f"Avg Latency: {result['stats']['avg_latency_seconds']}s")
            print(f"P50 Latency: {result['stats']['p50_latency_seconds']}s")
        print("\nPer-Game:")
        for g in result.get('games', []):
            print(f"  {g['game_id']}: {g['total_latency_seconds']}s [{g['status']}]")


if __name__ == '__main__':
    main()
