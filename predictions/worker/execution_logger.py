# predictions/worker/execution_logger.py

"""
Execution Logger for Phase 5 Prediction Worker

Logs worker execution to prediction_worker_runs table for:
- Monitoring and debugging
- Performance tracking
- Data quality analysis
- Circuit breaker support
- Pattern #4: Processing Metadata
- Trigger tracing (Pub/Sub correlation)

Tracks:
- Which prediction systems ran (and which succeeded/failed)
- Data quality metrics (feature_quality_score, missing features)
- Performance breakdown (data load, compute, write times)
- Circuit breaker triggers
- Error details
- Trigger source and Pub/Sub message ID for tracing

Version: 1.1
Date: 2025-11-27
"""

import logging
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class ExecutionLogger:
    """
    Logs Phase 5 prediction worker execution to BigQuery.

    Each worker request generates one log entry with:
    - Request details (player, game, lines)
    - Execution results (success, duration, predictions generated)
    - System-specific results (which systems succeeded/failed)
    - Data quality metrics
    - Performance breakdown
    - Error tracking
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str, worker_version: str = "1.0"):
        """
        Initialize execution logger.

        Args:
            bq_client: BigQuery client
            project_id: GCP project ID
            worker_version: Worker code version
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.worker_version = worker_version
        self.table_id = f'{project_id}.nba_predictions.prediction_worker_runs'

        # Capture Cloud Run metadata from environment
        self.cloud_run_service = os.environ.get('K_SERVICE')
        self.cloud_run_revision = os.environ.get('K_REVISION')

        logger.info(f"Initialized ExecutionLogger for {self.table_id}")

    def log_execution(
        self,
        # Request details
        player_lookup: str,
        universal_player_id: Optional[str],
        game_date: str,  # ISO format string
        game_id: str,
        line_values_requested: List[float],

        # Execution results
        success: bool,
        duration_seconds: float,
        predictions_generated: int,

        # Pattern support
        skip_reason: Optional[str] = None,

        # System results
        systems_attempted: Optional[List[str]] = None,
        systems_succeeded: Optional[List[str]] = None,
        systems_failed: Optional[List[str]] = None,
        system_errors: Optional[Dict[str, str]] = None,

        # Data quality
        feature_quality_score: Optional[float] = None,
        missing_features: Optional[List[str]] = None,
        feature_load_time_seconds: Optional[float] = None,

        # Historical data
        historical_games_count: Optional[int] = None,
        historical_load_time_seconds: Optional[float] = None,

        # Error tracking
        error_message: Optional[str] = None,
        error_system: Optional[str] = None,
        error_type: Optional[str] = None,

        # Performance breakdown
        data_load_seconds: Optional[float] = None,
        prediction_compute_seconds: Optional[float] = None,
        write_bigquery_seconds: Optional[float] = None,
        pubsub_publish_seconds: Optional[float] = None,

        # Circuit breaker
        circuit_breaker_triggered: bool = False,
        circuits_opened: Optional[List[str]] = None,

        # NEW: Tracing fields
        trigger_source: Optional[str] = None,
        trigger_message_id: Optional[str] = None,
        retry_attempt: Optional[int] = None,
        batch_id: Optional[str] = None
    ) -> None:
        """
        Log worker execution to BigQuery.

        Args:
            See prediction_worker_runs schema for field descriptions
        """
        try:
            # Generate unique request ID
            request_id = str(uuid.uuid4())

            # Build log entry
            log_entry = {
                # Execution identifiers
                'request_id': request_id,
                'worker_id': None,  # TODO: Get from environment
                'run_date': datetime.now(timezone.utc).isoformat(),

                # Request details
                'player_lookup': player_lookup,
                'universal_player_id': universal_player_id,
                'game_date': game_date,
                'game_id': game_id,
                'line_values_requested': line_values_requested,

                # Execution results
                'success': success,
                'duration_seconds': duration_seconds,
                'predictions_generated': predictions_generated,

                # Pattern support
                'skip_reason': skip_reason,

                # System results
                'systems_attempted': systems_attempted or [],
                'systems_succeeded': systems_succeeded or [],
                'systems_failed': systems_failed or [],
                'system_errors': json.dumps(system_errors) if system_errors else None,

                # Data quality
                'feature_quality_score': feature_quality_score,
                'missing_features': missing_features or [],
                'feature_load_time_seconds': feature_load_time_seconds,

                # Historical data
                'historical_games_count': historical_games_count,
                'historical_load_time_seconds': historical_load_time_seconds,

                # Error tracking
                'error_message': error_message,
                'error_system': error_system,
                'error_type': error_type,

                # Performance breakdown
                'data_load_seconds': data_load_seconds,
                'prediction_compute_seconds': prediction_compute_seconds,
                'write_bigquery_seconds': write_bigquery_seconds,
                'pubsub_publish_seconds': pubsub_publish_seconds,

                # Circuit breaker
                'circuit_breaker_triggered': circuit_breaker_triggered,
                'circuits_opened': circuits_opened or [],

                # Metadata
                'worker_version': self.worker_version,
                'created_at': datetime.now(timezone.utc).isoformat(),

                # NEW: Tracing fields
                'trigger_source': trigger_source,
                'trigger_message_id': trigger_message_id,
                'cloud_run_service': self.cloud_run_service,
                'cloud_run_revision': self.cloud_run_revision,
                'retry_attempt': retry_attempt,
                'batch_id': batch_id
            }

            # Write to BigQuery using batch loading (not streaming insert)
            # This avoids the 20 DML limit when 100+ workers run concurrently
            table = self.bq_client.get_table(self.table_id)

            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            load_job = self.bq_client.load_table_from_json(
                [log_entry],
                self.table_id,
                job_config=job_config
            )

            load_job.result(timeout=60)
            logger.debug(f"Logged execution for {player_lookup} (request_id={request_id})")

        except Exception as e:
            logger.error(f"Error logging execution: {e}")
            # Don't fail the request on logging errors

    def log_success(
        self,
        player_lookup: str,
        universal_player_id: Optional[str],
        game_date: str,
        game_id: str,
        line_values: List[float],
        duration_seconds: float,
        predictions_generated: int,
        systems_succeeded: List[str],
        systems_failed: List[str],
        system_errors: Dict[str, str],
        feature_quality_score: float,
        historical_games_count: int,
        performance_breakdown: Dict[str, float]
    ) -> None:
        """
        Convenience method to log successful execution.

        Args:
            See log_execution for parameter descriptions
        """
        self.log_execution(
            player_lookup=player_lookup,
            universal_player_id=universal_player_id,
            game_date=game_date,
            game_id=game_id,
            line_values_requested=line_values,
            success=True,
            duration_seconds=duration_seconds,
            predictions_generated=predictions_generated,
            systems_attempted=['moving_average', 'zone_matchup_v1', 'similarity_balanced_v1', 'xgboost_v1', 'ensemble_v1'],
            systems_succeeded=systems_succeeded,
            systems_failed=systems_failed,
            system_errors=system_errors if system_errors else None,
            feature_quality_score=feature_quality_score,
            historical_games_count=historical_games_count,
            data_load_seconds=performance_breakdown.get('data_load'),
            prediction_compute_seconds=performance_breakdown.get('prediction_compute'),
            write_bigquery_seconds=performance_breakdown.get('write_bigquery'),
            pubsub_publish_seconds=performance_breakdown.get('pubsub_publish')
        )

    def log_failure(
        self,
        player_lookup: str,
        universal_player_id: Optional[str],
        game_date: str,
        game_id: str,
        line_values: List[float],
        duration_seconds: float,
        error_message: str,
        error_type: str,
        skip_reason: Optional[str] = None,
        systems_attempted: Optional[List[str]] = None,
        systems_failed: Optional[List[str]] = None,
        circuit_breaker_triggered: bool = False,
        circuits_opened: Optional[List[str]] = None
    ) -> None:
        """
        Convenience method to log failed execution.

        Args:
            See log_execution for parameter descriptions
        """
        self.log_execution(
            player_lookup=player_lookup,
            universal_player_id=universal_player_id,
            game_date=game_date,
            game_id=game_id,
            line_values_requested=line_values,
            success=False,
            duration_seconds=duration_seconds,
            predictions_generated=0,
            skip_reason=skip_reason,
            systems_attempted=systems_attempted,
            systems_succeeded=[],
            systems_failed=systems_failed,
            error_message=error_message,
            error_type=error_type,
            circuit_breaker_triggered=circuit_breaker_triggered,
            circuits_opened=circuits_opened
        )
