"""
Cross-Phase Consistency Validator

Validates that data flows correctly through all pipeline phases.
Detects entity count mismatches and orphan records.

Checks:
- Schedule → Boxscores → Analytics → Features → Predictions
- Player coverage at each phase transition
- Orphan records (predictions without features, etc.)

Created: 2026-01-25
Part of: Validation Framework Improvements - P0
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

from google.cloud import bigquery

logger = logging.getLogger(__name__)


@dataclass
class PhaseMapping:
    """Configuration for a phase-to-phase mapping."""
    name: str
    source_table: str
    target_table: str
    source_field: str
    target_field: str
    date_field: str
    source_filter: Optional[str] = None
    target_filter: Optional[str] = None
    expected_rate: float = 0.95
    severity: str = 'error'


@dataclass
class ConsistencyResult:
    """Result of a consistency check."""
    check_name: str
    passed: bool
    severity: str
    source_count: int
    target_count: int
    match_rate: float
    expected_rate: float
    missing_count: int
    message: str


class CrossPhaseValidator:
    """Validates data consistency across pipeline phases."""

    # Phase mapping configurations
    PHASE_MAPPINGS = [
        PhaseMapping(
            name="schedule_to_boxscores",
            source_table="nba_raw.v_nbac_schedule_latest",
            target_table="nba_raw.bdl_player_boxscores",
            source_field="game_id",
            target_field="game_id",
            date_field="game_date",
            source_filter="game_status = 3",  # Only Final games
            expected_rate=0.98,
            severity="error"
        ),
        PhaseMapping(
            name="boxscores_to_analytics",
            source_table="nba_raw.bdl_player_boxscores",
            target_table="nba_analytics.player_game_summary",
            source_field="player_lookup",
            target_field="player_lookup",
            date_field="game_date",
            expected_rate=0.95,
            severity="error"
        ),
        PhaseMapping(
            name="analytics_to_features",
            source_table="nba_analytics.player_game_summary",
            target_table="nba_precompute.ml_feature_store",
            source_field="player_lookup",
            target_field="player_lookup",
            date_field="game_date",
            expected_rate=0.90,
            severity="warning"
        ),
        PhaseMapping(
            name="features_to_predictions",
            source_table="nba_precompute.ml_feature_store",
            target_table="nba_predictions.player_prop_predictions",
            source_field="player_lookup",
            target_field="player_lookup",
            date_field="game_date",
            source_filter="is_production_ready = TRUE",
            expected_rate=0.85,
            severity="warning"
        ),
    ]

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def validate(self, target_date: str) -> Dict[str, any]:
        """
        Validate cross-phase consistency for target date.

        Args:
            target_date: Date to validate (YYYY-MM-DD)

        Returns:
            Dict with validation results
        """
        logger.info(f"Validating cross-phase consistency for {target_date}")

        results = {
            'target_date': target_date,
            'checks': [],
            'passed': True,
            'errors': [],
            'warnings': []
        }

        # Check each phase mapping
        for mapping in self.PHASE_MAPPINGS:
            check_result = self._check_phase_consistency(mapping, target_date)
            results['checks'].append(check_result)

            if not check_result.passed:
                if check_result.severity == 'error':
                    results['errors'].append(check_result)
                    results['passed'] = False
                elif check_result.severity == 'warning':
                    results['warnings'].append(check_result)

        # Check for orphan records
        orphan_predictions = self._check_orphan_predictions(target_date)
        if orphan_predictions:
            results['warnings'].append({
                'check': 'orphan_predictions',
                'count': len(orphan_predictions),
                'message': f"Found {len(orphan_predictions)} predictions without feature records"
            })

        orphan_analytics = self._check_orphan_analytics(target_date)
        if orphan_analytics:
            results['warnings'].append({
                'check': 'orphan_analytics',
                'count': len(orphan_analytics),
                'message': f"Found {len(orphan_analytics)} analytics without boxscore records"
            })

        logger.info(
            f"Cross-phase validation complete: "
            f"{len(results['errors'])} errors, {len(results['warnings'])} warnings"
        )

        return results

    def _check_phase_consistency(
        self,
        mapping: PhaseMapping,
        target_date: str
    ) -> ConsistencyResult:
        """Check consistency between two phases."""
        source_filter = f"AND {mapping.source_filter}" if mapping.source_filter else ""
        target_filter = f"AND {mapping.target_filter}" if mapping.target_filter else ""

        query = f"""
        WITH source_records AS (
            SELECT DISTINCT {mapping.source_field}
            FROM `{self.project_id}.{mapping.source_table}`
            WHERE {mapping.date_field} = @target_date
            {source_filter}
        ),
        target_records AS (
            SELECT DISTINCT {mapping.target_field}
            FROM `{self.project_id}.{mapping.target_table}`
            WHERE {mapping.date_field} = @target_date
            {target_filter}
        )
        SELECT
            COUNT(DISTINCT s.{mapping.source_field}) as source_count,
            COUNT(DISTINCT t.{mapping.target_field}) as target_count,
            SAFE_DIVIDE(
                COUNT(DISTINCT t.{mapping.target_field}),
                COUNT(DISTINCT s.{mapping.source_field})
            ) as match_rate
        FROM source_records s
        LEFT JOIN target_records t
            ON s.{mapping.source_field} = t.{mapping.target_field}
        """

        results = self._run_query(query, {"target_date": target_date})

        if results:
            source_count = results[0].source_count or 0
            target_count = results[0].target_count or 0
            match_rate = results[0].match_rate or 0.0
        else:
            source_count = target_count = 0
            match_rate = 0.0

        missing_count = source_count - target_count
        passed = match_rate >= mapping.expected_rate

        message = (
            f"{mapping.name}: {target_count}/{source_count} records "
            f"({match_rate:.1%} coverage, expected >={mapping.expected_rate:.0%})"
        )

        return ConsistencyResult(
            check_name=mapping.name,
            passed=passed,
            severity=mapping.severity,
            source_count=source_count,
            target_count=target_count,
            match_rate=match_rate,
            expected_rate=mapping.expected_rate,
            missing_count=missing_count,
            message=message
        )

    def _check_orphan_predictions(self, target_date: str) -> List[Dict]:
        """Find predictions without corresponding features."""
        query = """
        SELECT
            p.player_lookup,
            p.player_name
        FROM `nba_predictions.player_prop_predictions` p
        LEFT JOIN `nba_precompute.ml_feature_store` f
            ON p.player_lookup = f.player_lookup
            AND p.game_date = f.game_date
        WHERE p.game_date = @target_date
        AND f.player_lookup IS NULL
        LIMIT 100
        """

        results = self._run_query(query, {"target_date": target_date})

        orphans = [
            {'player_lookup': r.player_lookup, 'player_name': r.player_name}
            for r in results
        ]

        return orphans

    def _check_orphan_analytics(self, target_date: str) -> List[Dict]:
        """Find analytics without corresponding boxscores."""
        query = """
        SELECT
            a.player_lookup,
            a.player_name
        FROM `nba_analytics.player_game_summary` a
        LEFT JOIN `nba_raw.bdl_player_boxscores` b
            ON a.player_lookup = b.player_lookup
            AND a.game_date = b.game_date
        WHERE a.game_date = @target_date
        AND b.player_lookup IS NULL
        LIMIT 100
        """

        results = self._run_query(query, {"target_date": target_date})

        orphans = [
            {'player_lookup': r.player_lookup, 'player_name': r.player_name}
            for r in results
        ]

        return orphans

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

    if len(sys.argv) < 2:
        print("Usage: python cross_phase_validator.py YYYY-MM-DD")
        sys.exit(1)

    target_date = sys.argv[1]

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    validator = CrossPhaseValidator()
    results = validator.validate(target_date)

    print("\n" + "=" * 70)
    print(f"Cross-Phase Consistency Validation: {target_date}")
    print("=" * 70)

    print(f"\nOverall: {'✅ PASSED' if results['passed'] else '❌ FAILED'}")

    if results['errors']:
        print("\n❌ ERRORS:")
        for result in results['errors']:
            print(f"  • {result.message}")

    if results['warnings']:
        print("\n⚠️  WARNINGS:")
        for result in results['warnings']:
            if isinstance(result, ConsistencyResult):
                print(f"  • {result.message}")
            else:
                print(f"  • {result['message']}")

    print("\n📊 PHASE COVERAGE:")
    for check in results['checks']:
        status = "✅" if check.passed else "❌"
        print(f"  {status} {check.check_name}: {check.match_rate:.1%} "
              f"({check.target_count}/{check.source_count})")

    print("\n" + "=" * 70)

    sys.exit(0 if results['passed'] else 1)
