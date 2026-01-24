"""
Phase Execution Logger - Track orchestrator execution timing

Logs execution metrics at phase boundaries to track latency and identify gaps.
This fills the blind spot between Phase 2 completion and Phase 3 start.

Usage in orchestrators:
    from shared.utils.phase_execution_logger import log_phase_execution

    # At phase boundary (when triggering next phase):
    log_phase_execution(
        phase_name="phase2_to_phase3",
        game_date="2026-01-21",
        start_time=start_time,
        duration_seconds=duration,
        games_processed=len(completed_processors),
        status="complete",
        correlation_id="abc-123",
        metadata={"completed_processors": completed_processors}
    )

BigQuery Schema:
    TODO: Create table `nba_orchestration.phase_execution_log` with schema:
    - execution_timestamp TIMESTAMP NOT NULL (when orchestrator ran)
    - phase_name STRING NOT NULL (e.g., "phase2_to_phase3")
    - game_date DATE NOT NULL (date being processed)
    - start_time TIMESTAMP NOT NULL (when phase work started)
    - duration_seconds FLOAT64 NOT NULL (how long it took)
    - games_processed INT64 (number of games/processors completed)
    - status STRING NOT NULL (complete, partial, deadline_exceeded)
    - correlation_id STRING (links to scraper_execution_log)
    - metadata JSON (additional context)
    - created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()

Created: January 22, 2026
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


def log_phase_execution(
    phase_name: str,
    game_date: str,
    start_time: datetime,
    duration_seconds: float,
    games_processed: int,
    status: str,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    dry_run: bool = False
) -> bool:
    """
    Log phase execution metrics to BigQuery.

    Args:
        phase_name: Name of the phase (e.g., "phase2_to_phase3")
        game_date: Date being processed (YYYY-MM-DD)
        start_time: When the phase work started (datetime)
        duration_seconds: How long the phase took (seconds)
        games_processed: Number of games/processors completed
        status: Execution status (complete, partial, deadline_exceeded)
        correlation_id: Optional correlation ID for tracing
        metadata: Optional metadata dict (converted to JSON)
        dry_run: If True, don't write to BigQuery (for testing)

    Returns:
        True if logged successfully, False otherwise

    Example:
        start = datetime.now(timezone.utc)
        # ... do work ...
        duration = (datetime.now(timezone.utc) - start).total_seconds()

        log_phase_execution(
            phase_name="phase2_to_phase3",
            game_date="2026-01-21",
            start_time=start,
            duration_seconds=duration,
            games_processed=6,
            status="complete",
            correlation_id="abc-123",
            metadata={"completed_processors": ["proc1", "proc2"]}
        )
    """
    try:
        # Get environment config - uses GCP_PROJECT_ID with fallback to GCP_PROJECT
        project_id = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        dataset = os.environ.get('ORCHESTRATION_DATASET', 'nba_orchestration')
        table = os.environ.get('PHASE_EXECUTION_LOG_TABLE', 'phase_execution_log')

        execution_timestamp = datetime.now(timezone.utc)

        # Build row to insert
        row = {
            "execution_timestamp": execution_timestamp.isoformat(),
            "phase_name": phase_name,
            "game_date": game_date,
            "start_time": start_time.isoformat(),
            "duration_seconds": duration_seconds,
            "games_processed": games_processed,
            "status": status,
            "correlation_id": correlation_id,
            "metadata": metadata,  # BigQuery insert_rows_json handles dict -> JSON
        }

        logger.info(
            f"Phase execution logged: {phase_name} for {game_date} - "
            f"duration={duration_seconds:.2f}s, games={games_processed}, status={status}"
        )

        # Write to BigQuery (unless dry run)
        if not dry_run:
            from google.cloud import bigquery
            client = bigquery.Client(project=project_id)

            table_id = f"{project_id}.{dataset}.{table}"
            errors = client.insert_rows_json(table_id, [row])

            if errors:
                logger.error(f"BigQuery insert errors: {errors}", exc_info=True)
                return False
            else:
                logger.debug(f"Phase execution logged to {table_id}")
                return True
        else:
            logger.info(f"DRY RUN: Would log to BigQuery: {row}")
            return True

    except Exception as e:
        # Don't fail the orchestrator if logging fails
        logger.warning(f"Failed to log phase execution to BigQuery: {e}")
        return False


def log_orchestrator_start(
    phase_name: str,
    game_date: str,
    trigger_source: str,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> datetime:
    """
    Log orchestrator start and return start time for duration calculation.

    This is a convenience function that logs the start event and returns
    the timestamp so you can later calculate duration.

    Args:
        phase_name: Name of the phase (e.g., "phase2_to_phase3")
        game_date: Date being processed
        trigger_source: What triggered this (e.g., "pubsub", "http")
        correlation_id: Optional correlation ID
        metadata: Optional metadata

    Returns:
        datetime: Start timestamp (use for duration calculation)

    Example:
        start_time = log_orchestrator_start(
            phase_name="phase2_to_phase3",
            game_date="2026-01-21",
            trigger_source="pubsub",
            correlation_id="abc-123"
        )

        # ... do work ...

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        log_phase_execution(
            phase_name="phase2_to_phase3",
            game_date="2026-01-21",
            start_time=start_time,
            duration_seconds=duration,
            games_processed=6,
            status="complete"
        )
    """
    start_time = datetime.now(timezone.utc)

    logger.info(
        f"Orchestrator started: {phase_name} for {game_date} "
        f"(trigger={trigger_source}, correlation_id={correlation_id})"
    )

    # Optionally log to structured logging if available
    try:
        from shared.utils.structured_logging import log_phase_transition
        log_phase_transition(
            from_phase=phase_name.split('_to_')[0] if '_to_' in phase_name else 'unknown',
            to_phase=phase_name.split('_to_')[1] if '_to_' in phase_name else 'unknown',
            game_date=game_date,
            correlation_id=correlation_id,
            trigger_source=trigger_source,
            **(metadata or {})
        )
    except Exception as e:
        logger.debug(f"Could not log to structured logging: {e}")

    return start_time


def log_orchestrator_complete(
    phase_name: str,
    game_date: str,
    start_time: datetime,
    games_processed: int,
    status: str,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> float:
    """
    Log orchestrator completion and return duration.

    This is a convenience function that calculates duration and logs to BigQuery.

    Args:
        phase_name: Name of the phase
        game_date: Date being processed
        start_time: When orchestrator started (from log_orchestrator_start)
        games_processed: Number of games/processors completed
        status: Execution status (complete, partial, deadline_exceeded)
        correlation_id: Optional correlation ID
        metadata: Optional metadata

    Returns:
        float: Duration in seconds

    Example:
        start_time = log_orchestrator_start(...)

        # ... do work ...

        duration = log_orchestrator_complete(
            phase_name="phase2_to_phase3",
            game_date="2026-01-21",
            start_time=start_time,
            games_processed=6,
            status="complete",
            correlation_id="abc-123"
        )
    """
    duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()

    log_phase_execution(
        phase_name=phase_name,
        game_date=game_date,
        start_time=start_time,
        duration_seconds=duration_seconds,
        games_processed=games_processed,
        status=status,
        correlation_id=correlation_id,
        metadata=metadata
    )

    logger.info(
        f"Orchestrator complete: {phase_name} for {game_date} - "
        f"duration={duration_seconds:.2f}s, status={status}"
    )

    return duration_seconds


# Backward compatibility aliases
def log_phase2_to_phase3_execution(*args, **kwargs):
    """Alias for log_phase_execution with phase_name="phase2_to_phase3"."""
    return log_phase_execution(phase_name="phase2_to_phase3", *args, **kwargs)


def log_phase3_to_phase4_execution(*args, **kwargs):
    """Alias for log_phase_execution with phase_name="phase3_to_phase4"."""
    return log_phase_execution(phase_name="phase3_to_phase4", *args, **kwargs)


# Example usage and testing
if __name__ == "__main__":
    import time

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Demo: Phase Execution Logger\n")
    print("=" * 60)

    # Simulate orchestrator execution
    print("\nSimulating Phase 2→3 orchestrator execution...")

    start_time = log_orchestrator_start(
        phase_name="phase2_to_phase3",
        game_date="2026-01-21",
        trigger_source="pubsub",
        correlation_id="demo-123",
        metadata={"test_mode": True}
    )

    # Simulate some work
    print("Doing work...")
    time.sleep(0.5)

    # Log completion
    duration = log_orchestrator_complete(
        phase_name="phase2_to_phase3",
        game_date="2026-01-21",
        start_time=start_time,
        games_processed=6,
        status="complete",
        correlation_id="demo-123",
        metadata={
            "completed_processors": [
                "bdl_player_boxscores",
                "nbac_gamebook_player_stats",
                "odds_api_game_lines"
            ],
            "trigger_reason": "all_complete"
        }
    )

    print(f"\nDemo complete! Duration: {duration:.2f}s")
    print("\nNote: This demo runs in dry_run mode by default.")
    print("To write to BigQuery, create the table first (see schema in docstring).")
