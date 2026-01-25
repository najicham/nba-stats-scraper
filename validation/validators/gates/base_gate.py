"""
Base Phase Gate Validator

Provides framework for validating data quality before phase transitions.
Gates can BLOCK, WARN, or PROCEED based on validation results.

Created: 2026-01-25
Part of: Validation Framework Improvements
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import logging

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class GateDecision(Enum):
    """Decision outcome from gate evaluation."""
    PROCEED = "proceed"
    BLOCK = "block"
    WARN_AND_PROCEED = "warn_and_proceed"


@dataclass
class GateResult:
    """Result of gate evaluation."""
    decision: GateDecision
    checks_passed: int
    checks_failed: int
    blocking_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return {
            'decision': self.decision.value,
            'checks_passed': self.checks_passed,
            'checks_failed': self.checks_failed,
            'blocking_reasons': self.blocking_reasons,
            'warnings': self.warnings,
            'metrics': self.metrics,
        }


class PhaseGate(ABC):
    """Base class for phase transition gates."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    @abstractmethod
    def evaluate(self, target_date: str) -> GateResult:
        """
        Evaluate whether processing should proceed.

        Args:
            target_date: Date to evaluate (YYYY-MM-DD format)

        Returns:
            GateResult with decision and details
        """
        pass

    def should_block(self, target_date: str) -> bool:
        """Quick check if gate blocks processing."""
        result = self.evaluate(target_date)
        return result.decision == GateDecision.BLOCK

    def _run_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Execute BigQuery query with parameters."""
        try:
            job_config = bigquery.QueryJobConfig()

            if params:
                job_config.query_parameters = [
                    bigquery.ScalarQueryParameter(k, 'STRING', str(v))
                    for k, v in params.items()
                ]

            query_job = self.bq_client.query(query, job_config=job_config)
            results = list(query_job.result())

            return results

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def _check_quality_threshold(
        self,
        table: str,
        quality_field: str,
        threshold: float,
        target_date: str
    ) -> dict:
        """Check if quality metric meets threshold."""
        query = f"""
        SELECT AVG({quality_field}) as avg_quality
        FROM `{self.project_id}.{table}`
        WHERE game_date = @target_date
        """

        results = self._run_query(query, {"target_date": target_date})
        avg_quality = results[0].avg_quality if results and results[0].avg_quality else 0.0

        return {
            "passed": avg_quality >= threshold,
            "avg_quality": avg_quality,
            "threshold": threshold
        }

    def _check_completeness(
        self,
        source_table: str,
        target_table: str,
        join_field: str,
        target_date: str,
        threshold: float = 0.80
    ) -> dict:
        """Check if target has sufficient coverage of source."""
        query = f"""
        WITH source AS (
            SELECT DISTINCT {join_field}
            FROM `{self.project_id}.{source_table}`
            WHERE game_date = @target_date
        ),
        target AS (
            SELECT DISTINCT {join_field}
            FROM `{self.project_id}.{target_table}`
            WHERE game_date = @target_date
        )
        SELECT
            COUNT(DISTINCT s.{join_field}) as source_count,
            COUNT(DISTINCT t.{join_field}) as target_count,
            SAFE_DIVIDE(
                COUNT(DISTINCT t.{join_field}),
                COUNT(DISTINCT s.{join_field})
            ) as coverage
        FROM source s
        LEFT JOIN target t USING ({join_field})
        """

        results = self._run_query(query, {"target_date": target_date})

        if results and results[0].coverage is not None:
            coverage = float(results[0].coverage)
            source_count = results[0].source_count
            target_count = results[0].target_count
        else:
            coverage = 0.0
            source_count = 0
            target_count = 0

        return {
            "passed": coverage >= threshold,
            "coverage": coverage,
            "threshold": threshold,
            "source_count": source_count,
            "target_count": target_count
        }

    def _check_null_rate(
        self,
        table: str,
        field: str,
        target_date: str,
        max_null_rate: float = 0.05
    ) -> dict:
        """Check NULL rate for a field."""
        query = f"""
        SELECT
            COUNTIF({field} IS NULL) / COUNT(*) as null_rate
        FROM `{self.project_id}.{table}`
        WHERE game_date = @target_date
        """

        results = self._run_query(query, {"target_date": target_date})
        null_rate = results[0].null_rate if results and results[0].null_rate else 0.0

        return {
            "passed": null_rate <= max_null_rate,
            "null_rate": null_rate,
            "max_null_rate": max_null_rate,
            "field": field
        }

    def _check_staleness(
        self,
        table: str,
        timestamp_field: str,
        target_date: str,
        max_staleness_hours: int = 48
    ) -> dict:
        """Check if data is fresh enough."""
        query = f"""
        SELECT
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX({timestamp_field}), HOUR) as staleness_hours
        FROM `{self.project_id}.{table}`
        WHERE game_date = @target_date
        """

        results = self._run_query(query, {"target_date": target_date})
        staleness = results[0].staleness_hours if results and results[0].staleness_hours else 999

        return {
            "passed": staleness <= max_staleness_hours,
            "staleness_hours": staleness,
            "max_staleness_hours": max_staleness_hours
        }
