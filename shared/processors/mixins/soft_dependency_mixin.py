"""
Soft Dependency Mixin for Processors
=====================================
Provides soft dependency checking that allows processors to proceed
with degraded upstream data when coverage meets minimum thresholds.

This replaces binary pass/fail dependency checks with threshold-based
soft dependencies, enabling graceful degradation.

Usage:
    class MyProcessor(SoftDependencyMixin, ProcessorBase):
        def run(self):
            # Check dependencies with soft thresholds
            dep_result = self.check_soft_dependencies(analysis_date)

            if dep_result['should_proceed']:
                if dep_result['degraded']:
                    logger.warning(f"Proceeding with degraded dependencies: {dep_result['warnings']}")
                # ... do processing ...
            else:
                raise DependencyNotMetError(dep_result['errors'])

Version: 1.0
Created: 2026-01-24
"""

import logging
from datetime import date
from typing import Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class SoftDependencyMixin:
    """
    Mixin that provides soft dependency checking for processors.

    Requires:
    - self.processor_name: Name of this processor
    - self.project_id: GCP project ID
    - self.bq_client: BigQuery client (optional, will create if needed)
    """

    def check_soft_dependencies(
        self,
        analysis_date: date,
        custom_thresholds: Dict[str, float] = None
    ) -> Dict:
        """
        Check upstream dependencies with soft thresholds.

        Args:
            analysis_date: Date to check dependencies for
            custom_thresholds: Override default thresholds {processor_name: min_coverage}

        Returns:
            Dictionary with:
            - should_proceed: bool - Whether to proceed with processing
            - degraded: bool - Whether proceeding with degraded data
            - coverage: dict - Coverage per upstream processor
            - warnings: list - Warning messages for degraded dependencies
            - errors: list - Error messages for unmet dependencies
        """
        from shared.config.dependency_config import get_dependency_config

        config = get_dependency_config()
        dependencies = config.get_dependencies(self.processor_name)

        result = {
            'should_proceed': True,
            'degraded': False,
            'coverage': {},
            'warnings': [],
            'errors': [],
            'details': []
        }

        if not dependencies:
            logger.debug(f"No dependencies configured for {self.processor_name}")
            return result

        for upstream_name, rule in dependencies.items():
            # Get actual coverage
            actual_coverage = self._get_upstream_coverage(upstream_name, analysis_date)
            result['coverage'][upstream_name] = actual_coverage

            # Check with custom threshold if provided
            min_coverage = (
                custom_thresholds.get(upstream_name, rule.min_coverage)
                if custom_thresholds
                else rule.min_coverage
            )

            # Determine status
            is_met, message, action = config.check_dependency(
                self.processor_name,
                upstream_name,
                actual_coverage
            )

            result['details'].append({
                'upstream': upstream_name,
                'coverage': actual_coverage,
                'min_required': min_coverage,
                'is_met': is_met,
                'action': action,
                'message': message
            })

            if not is_met:
                result['should_proceed'] = False
                result['errors'].append(message)
            elif action == 'warn_and_proceed':
                result['degraded'] = True
                result['warnings'].append(message)

        # Log summary
        if result['errors']:
            logger.error(f"Dependency check failed: {result['errors']}")
        elif result['warnings']:
            logger.warning(f"Proceeding with degraded dependencies: {result['warnings']}")
        else:
            logger.info(f"All dependencies met for {self.processor_name}")

        return result

    def _get_upstream_coverage(self, upstream_name: str, analysis_date: date) -> float:
        """
        Get coverage percentage for an upstream processor.

        Args:
            upstream_name: Name of upstream processor
            analysis_date: Date to check

        Returns:
            Coverage percentage (0.0-1.0)
        """
        # Get BigQuery client
        if not hasattr(self, 'bq_client') or self.bq_client is None:
            self.bq_client = bigquery.Client(project=self.project_id)

        # Query processor run history for the most recent successful run
        query = f"""
        WITH latest_run AS (
            SELECT
                status,
                records_processed,
                COALESCE(
                    JSON_EXTRACT_SCALAR(summary, '$.expected_count'),
                    JSON_EXTRACT_SCALAR(summary, '$.total_expected')
                ) as expected_count
            FROM `{self.project_id}.nba_reference.processor_run_history`
            WHERE processor_name = @upstream_name
              AND data_date = @analysis_date
            ORDER BY started_at DESC
            LIMIT 1
        )
        SELECT
            status,
            records_processed,
            expected_count,
            CASE
                WHEN status = 'success' THEN 1.0
                WHEN status = 'partial' AND records_processed > 0 AND expected_count IS NOT NULL
                    THEN SAFE_DIVIDE(records_processed, CAST(expected_count AS INT64))
                WHEN status = 'partial' THEN 0.5  # Assume 50% if we can't calculate
                ELSE 0.0
            END as coverage
        FROM latest_run
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("upstream_name", "STRING", upstream_name),
                bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date.isoformat()),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config))
            if result:
                return float(result[0].coverage or 0.0)
            else:
                # No run found - check if data exists in expected table
                return self._check_table_coverage(upstream_name, analysis_date)
        except Exception as e:
            logger.warning(f"Error checking coverage for {upstream_name}: {e}")
            return 0.0

    def _check_table_coverage(self, upstream_name: str, analysis_date: date) -> float:
        """
        Fallback: Check if data exists in the expected output table.

        Args:
            upstream_name: Name of upstream processor
            analysis_date: Date to check

        Returns:
            1.0 if data exists, 0.0 otherwise
        """
        # Map processor to output table
        PROCESSOR_TO_TABLE = {
            'PlayerGameSummaryProcessor': ('nba_analytics', 'player_game_summary', 'game_date'),
            'PlayerDailyCacheProcessor': ('nba_precompute', 'player_daily_cache', 'cache_date'),
            'PlayerCompositeFactorsProcessor': ('nba_precompute', 'player_composite_factors', 'game_date'),
            'UpcomingPlayerGameContextProcessor': ('nba_analytics', 'upcoming_player_game_context', 'game_date'),
            'MLFeatureStoreProcessor': ('nba_predictions', 'ml_feature_store_v2', 'game_date'),
        }

        if upstream_name not in PROCESSOR_TO_TABLE:
            return 0.0

        dataset, table, date_col = PROCESSOR_TO_TABLE[upstream_name]

        query = f"""
        SELECT COUNT(*) as record_count
        FROM `{self.project_id}.{dataset}.{table}`
        WHERE {date_col} = @analysis_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date.isoformat()),
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config))
            if result and result[0].record_count > 0:
                return 1.0
            return 0.0
        except Exception as e:
            logger.warning(f"Error checking table for {upstream_name}: {e}")
            return 0.0

    def log_dependency_metrics(self, dep_result: Dict):
        """
        Log dependency check metrics for monitoring/alerting.

        Args:
            dep_result: Result from check_soft_dependencies()
        """
        # Log to structured logging for alerting
        for detail in dep_result.get('details', []):
            if detail['action'] == 'warn_and_proceed':
                logger.warning(
                    f"SOFT_DEPENDENCY_DEGRADED: {self.processor_name} <- {detail['upstream']} "
                    f"(coverage={detail['coverage']:.1%}, min={detail['min_required']:.1%})"
                )
            elif not detail['is_met']:
                logger.error(
                    f"DEPENDENCY_NOT_MET: {self.processor_name} <- {detail['upstream']} "
                    f"(coverage={detail['coverage']:.1%}, min={detail['min_required']:.1%})"
                )
