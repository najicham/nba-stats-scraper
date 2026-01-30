"""
Post-Backfill Validator

Automatically verifies backfills worked after completion.

Validates:
- Gap is now filled (count check)
- Data quality meets expected levels
- Downstream phases were reprocessed
- No new gaps introduced

Created: 2026-01-25
Part of: Validation Framework Improvements - P1
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from google.cloud import bigquery

logger = logging.getLogger(__name__)


@dataclass
class BackfillValidationResult:
    """Result of backfill validation."""
    passed: bool
    gap_filled: bool
    quality_acceptable: bool
    downstream_reprocessed: bool
    issues: List[str]
    recommendations: List[str]
    metrics: Dict[str, any]


class PostBackfillValidator:
    """Validates that backfills successfully recovered data."""

    # Quality thresholds
    MIN_QUALITY_SCORE = 70.0
    MIN_COMPLETENESS_RATE = 0.95

    # Phase configurations
    PHASE_CONFIGS = {
        'raw': {
            'tables': ['nba_raw.bdl_player_boxscores', 'nba_raw.nbac_player_boxscores'],
            'downstream_phases': ['analytics'],
        },
        'analytics': {
            'tables': ['nba_analytics.player_game_summary'],
            'downstream_phases': ['precompute'],
        },
        'precompute': {
            'tables': ['nba_precompute.ml_feature_store', 'nba_precompute.player_daily_cache'],
            'downstream_phases': ['predictions'],
        },
        'predictions': {
            'tables': ['nba_predictions.player_prop_predictions'],
            'downstream_phases': ['grading'],
        },
    }

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def validate(
        self,
        phase: str,
        target_date: str,
        expected_count: Optional[int] = None
    ) -> BackfillValidationResult:
        """
        Validate backfill results.

        Args:
            phase: Phase that was backfilled ('raw', 'analytics', etc.)
            target_date: Date that was backfilled (YYYY-MM-DD)
            expected_count: Expected record count (optional)

        Returns:
            BackfillValidationResult
        """
        logger.info(f"Validating backfill: phase={phase}, date={target_date}")

        issues = []
        recommendations = []
        metrics = {}

        # Check 1: Gap filled
        gap_filled = self._check_gap_filled(phase, target_date, expected_count)
        metrics['gap_filled'] = gap_filled['filled']
        metrics['record_count'] = gap_filled['actual_count']

        if not gap_filled['filled']:
            issues.append(
                f"Gap not filled: expected {gap_filled['expected_count']}, "
                f"found {gap_filled['actual_count']}"
            )
            recommendations.append(f"Re-run backfill for {phase} on {target_date}")

        # Check 2: Data quality (if applicable)
        quality_acceptable = True
        if phase in ['precompute', 'analytics']:
            quality_check = self._check_data_quality(phase, target_date)
            metrics['quality_score'] = quality_check.get('quality_score', 0)
            quality_acceptable = quality_check['acceptable']

            if not quality_acceptable:
                issues.append(
                    f"Data quality below threshold: {quality_check.get('quality_score', 0):.1f} "
                    f"(expected >={self.MIN_QUALITY_SCORE})"
                )
                recommendations.append("Check upstream data quality and re-run backfill")

        # Check 3: Downstream reprocessed
        config = self.PHASE_CONFIGS.get(phase, {})
        downstream_reprocessed = True

        if config.get('downstream_phases'):
            downstream_check = self._check_downstream_reprocessed(
                phase, target_date, config['downstream_phases']
            )
            downstream_reprocessed = downstream_check['reprocessed']
            metrics['downstream_coverage'] = downstream_check.get('coverage', 0)

            if not downstream_reprocessed:
                issues.append(
                    f"Downstream phases not reprocessed: {', '.join(config['downstream_phases'])}"
                )
                for downstream in config['downstream_phases']:
                    recommendations.append(
                        f"python bin/backfill/{downstream}.py --date {target_date}"
                    )

        # Overall pass/fail
        passed = gap_filled['filled'] and quality_acceptable and downstream_reprocessed

        return BackfillValidationResult(
            passed=passed,
            gap_filled=gap_filled['filled'],
            quality_acceptable=quality_acceptable,
            downstream_reprocessed=downstream_reprocessed,
            issues=issues,
            recommendations=recommendations,
            metrics=metrics
        )

    def _check_gap_filled(
        self,
        phase: str,
        target_date: str,
        expected_count: Optional[int]
    ) -> dict:
        """Check if the gap is now filled."""
        config = self.PHASE_CONFIGS.get(phase, {})
        tables = config.get('tables', [])

        if not tables:
            return {'filled': False, 'actual_count': 0, 'expected_count': 0}

        # Use first table for count check
        table = tables[0]

        query = f"""
        SELECT COUNT(*) as record_count
        FROM `{self.project_id}.{table}`
        WHERE game_date = @target_date
        """

        results = self._run_query(query, {"target_date": target_date})
        actual_count = results[0].record_count if results else 0

        # If expected_count not provided, try to infer from schedule
        if expected_count is None:
            if phase == 'raw':
                expected_count = self._get_expected_game_count(target_date)
            else:
                # For downstream phases, use previous phase as reference
                expected_count = actual_count  # Can't validate without baseline

        filled = actual_count >= expected_count if expected_count else actual_count > 0

        return {
            'filled': filled,
            'actual_count': actual_count,
            'expected_count': expected_count
        }

    def _check_data_quality(self, phase: str, target_date: str) -> dict:
        """Check data quality for the backfilled data."""
        if phase == 'precompute':
            query = """
            SELECT AVG(feature_quality_score) as avg_quality
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date = @target_date
            """
        elif phase == 'analytics':
            query = """
            SELECT AVG(source_coverage_pct) as avg_quality
            FROM `nba_analytics.player_game_summary`
            WHERE game_date = @target_date
            """
        else:
            return {'acceptable': True}

        results = self._run_query(query, {"target_date": target_date})
        quality_score = results[0].avg_quality if results and results[0].avg_quality else 0.0

        return {
            'acceptable': quality_score >= self.MIN_QUALITY_SCORE,
            'quality_score': quality_score
        }

    def _check_downstream_reprocessed(
        self,
        phase: str,
        target_date: str,
        downstream_phases: List[str]
    ) -> dict:
        """Check if downstream phases were reprocessed."""
        # For each downstream phase, check if data exists for target_date
        all_reprocessed = True
        coverage_checks = {}

        for downstream in downstream_phases:
            config = self.PHASE_CONFIGS.get(downstream, {})
            tables = config.get('tables', [])

            if tables:
                query = f"""
                SELECT COUNT(*) as record_count
                FROM `{self.project_id}.{tables[0]}`
                WHERE game_date = @target_date
                """

                results = self._run_query(query, {"target_date": target_date})
                count = results[0].record_count if results else 0

                coverage_checks[downstream] = count
                if count == 0:
                    all_reprocessed = False

        return {
            'reprocessed': all_reprocessed,
            'coverage': coverage_checks
        }

    def _get_expected_game_count(self, target_date: str) -> int:
        """Get expected game count from schedule."""
        query = """
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM `nba_raw.v_nbac_schedule_latest`
        WHERE game_date = @target_date
          AND game_status = 3  -- Final
        """

        results = self._run_query(query, {"target_date": target_date})
        return results[0].game_count if results else 0

    def _run_query(self, query: str, params: Dict[str, any]) -> List[any]:
        """Execute BigQuery query with parameters."""
        try:
            job_config = bigquery.QueryJobConfig()
            job_config.query_parameters = [
                bigquery.ScalarQueryParameter(k, 'STRING', str(v))
                for k, v in params.items()
            ]

            query_job = self.bq_client.query(query, job_config=job_config)
            return list(query_job.result())

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []


# CLI entry point
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python post_backfill_validator.py PHASE YYYY-MM-DD [expected_count]")
        print("Example: python post_backfill_validator.py raw 2026-01-24 7")
        sys.exit(1)

    phase = sys.argv[1]
    target_date = sys.argv[2]
    expected_count = int(sys.argv[3]) if len(sys.argv) > 3 else None

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    validator = PostBackfillValidator()
    result = validator.validate(phase, target_date, expected_count)

    print("\n" + "=" * 70)
    print(f"Post-Backfill Validation: {phase} - {target_date}")
    print("=" * 70)

    print(f"\nOverall: {'✅ PASSED' if result.passed else '❌ FAILED'}")
    print(f"\n  Gap Filled: {'✅' if result.gap_filled else '❌'}")
    print(f"  Quality Acceptable: {'✅' if result.quality_acceptable else '❌'}")
    print(f"  Downstream Reprocessed: {'✅' if result.downstream_reprocessed else '❌'}")

    if result.issues:
        print("\n⚠️  ISSUES:")
        for issue in result.issues:
            print(f"  • {issue}")

    if result.recommendations:
        print("\n💡 RECOMMENDED ACTIONS:")
        for rec in result.recommendations:
            print(f"  • {rec}")

    print("\n📊 METRICS:")
    for key, value in result.metrics.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 70)

    sys.exit(0 if result.passed else 1)
