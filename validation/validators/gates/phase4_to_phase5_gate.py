"""
Phase 4 → Phase 5 Gate Validator

Validates feature quality before predictions run.
BLOCKS Phase 5 if feature data is degraded.

Checks:
- Feature quality score >= 70 average
- Player count >= 80% of Phase 3 output
- Rolling window freshness <= 48 hours stale
- Critical features NULL rate <= 5%

Created: 2026-01-25
Part of: Validation Framework Improvements - P0
"""

import logging
from typing import Dict, List

from .base_gate import PhaseGate, GateResult, GateDecision

logger = logging.getLogger(__name__)


class Phase4ToPhase5Gate(PhaseGate):
    """Gate that validates feature quality before predictions run."""

    # Configuration thresholds
    QUALITY_THRESHOLD = 70.0
    PLAYER_COUNT_THRESHOLD = 0.80
    MAX_NULL_RATE = 0.05
    MAX_STALENESS_HOURS = 48

    # Critical features that must be populated
    CRITICAL_FEATURES = [
        'points_rolling_avg',
        'minutes_rolling_avg',
        'usage_rate_rolling_avg',
        'opponent_def_rating'
    ]

    def evaluate(self, target_date: str) -> GateResult:
        """
        Evaluate whether Phase 5 predictions should run.

        Args:
            target_date: Date to evaluate (YYYY-MM-DD)

        Returns:
            GateResult with decision to PROCEED, BLOCK, or WARN
        """
        blocking_reasons = []
        warnings = []
        metrics = {}

        logger.info(f"Evaluating Phase 4→5 gate for {target_date}")

        # Check 1: Feature quality score
        quality_check = self._check_feature_quality(target_date)
        metrics["avg_quality"] = quality_check["avg_quality"]

        if not quality_check["passed"]:
            blocking_reasons.append(
                f"Feature quality {quality_check['avg_quality']:.1f} "
                f"below threshold {self.QUALITY_THRESHOLD}"
            )
            logger.warning(f"Quality check FAILED: {blocking_reasons[-1]}")
        else:
            logger.info(f"Quality check PASSED: {quality_check['avg_quality']:.1f}")

        # Check 2: Player count (coverage from Phase 3 to Phase 4)
        player_check = self._check_player_count(target_date)
        metrics["player_coverage"] = player_check["coverage"]
        metrics["expected_players"] = player_check.get("expected_count", 0)
        metrics["actual_players"] = player_check.get("actual_count", 0)

        if not player_check["passed"]:
            blocking_reasons.append(
                f"Player coverage {player_check['coverage']:.1%} "
                f"below threshold {self.PLAYER_COUNT_THRESHOLD:.0%} "
                f"({player_check.get('actual_count', 0)}/{player_check.get('expected_count', 0)} players)"
            )
            logger.warning(f"Player count check FAILED: {blocking_reasons[-1]}")
        else:
            logger.info(f"Player count check PASSED: {player_check['coverage']:.1%}")

        # Check 3: Rolling window freshness
        freshness_check = self._check_rolling_window_freshness(target_date)
        metrics["staleness_hours"] = freshness_check["staleness_hours"]

        if not freshness_check["passed"]:
            blocking_reasons.append(
                f"Rolling window {freshness_check['staleness_hours']:.1f}h stale, "
                f"max allowed {self.MAX_STALENESS_HOURS}h"
            )
            logger.warning(f"Freshness check FAILED: {blocking_reasons[-1]}")
        else:
            logger.info(f"Freshness check PASSED: {freshness_check['staleness_hours']:.1f}h")

        # Check 4: Critical field NULL rates
        null_check = self._check_critical_nulls(target_date)
        metrics["null_rates"] = null_check["null_rates"]

        if not null_check["passed"]:
            blocking_reasons.append(
                f"Critical fields have high NULL rates: {', '.join(null_check['problem_fields'])}"
            )
            logger.warning(f"NULL rate check FAILED: {blocking_reasons[-1]}")
        else:
            logger.info("NULL rate check PASSED")

        # Determine decision
        checks_passed = 4 - len(blocking_reasons)
        checks_failed = len(blocking_reasons)

        if blocking_reasons:
            decision = GateDecision.BLOCK
            logger.error(f"Gate BLOCKING Phase 5: {len(blocking_reasons)} checks failed")
        elif warnings:
            decision = GateDecision.WARN_AND_PROCEED
            logger.warning(f"Gate allowing with WARNINGS: {len(warnings)} warnings")
        else:
            decision = GateDecision.PROCEED
            logger.info("Gate ALLOWING Phase 5: all checks passed")

        return GateResult(
            decision=decision,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            metrics=metrics
        )

    def _check_feature_quality(self, target_date: str) -> dict:
        """Check average feature quality score."""
        query = """
        SELECT AVG(feature_quality_score) as avg_quality
        FROM `nba_precompute.ml_feature_store`
        WHERE game_date = @target_date
        """

        results = self._run_query(query, {"target_date": target_date})
        avg_quality = results[0].avg_quality if results and results[0].avg_quality else 0.0

        return {
            "passed": avg_quality >= self.QUALITY_THRESHOLD,
            "avg_quality": avg_quality
        }

    def _check_player_count(self, target_date: str) -> dict:
        """Check player count coverage from Phase 3 to Phase 4."""
        query = """
        WITH expected AS (
            SELECT COUNT(DISTINCT player_lookup) as cnt
            FROM `nba_analytics.player_game_summary`
            WHERE game_date = @target_date
        ),
        actual AS (
            SELECT COUNT(DISTINCT player_lookup) as cnt
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date = @target_date
        )
        SELECT
            expected.cnt as expected_count,
            actual.cnt as actual_count,
            SAFE_DIVIDE(actual.cnt, expected.cnt) as coverage
        FROM expected, actual
        """

        results = self._run_query(query, {"target_date": target_date})

        if results and results[0].coverage is not None:
            coverage = float(results[0].coverage)
            expected_count = results[0].expected_count
            actual_count = results[0].actual_count
        else:
            coverage = 0.0
            expected_count = 0
            actual_count = 0

        return {
            "passed": coverage >= self.PLAYER_COUNT_THRESHOLD,
            "coverage": coverage,
            "expected_count": expected_count,
            "actual_count": actual_count
        }

    def _check_rolling_window_freshness(self, target_date: str) -> dict:
        """Check if rolling windows are fresh."""
        query = """
        SELECT
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as staleness_hours
        FROM `nba_precompute.ml_feature_store`
        WHERE game_date = @target_date
        """

        results = self._run_query(query, {"target_date": target_date})
        staleness = results[0].staleness_hours if results and results[0].staleness_hours else 999

        return {
            "passed": staleness <= self.MAX_STALENESS_HOURS,
            "staleness_hours": staleness
        }

    def _check_critical_nulls(self, target_date: str) -> dict:
        """Check NULL rates for critical features."""
        null_rates = {}
        problem_fields = []

        for field in self.CRITICAL_FEATURES:
            query = f"""
            SELECT
                COUNTIF({field} IS NULL) / COUNT(*) as null_rate
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date = @target_date
            """

            results = self._run_query(query, {"target_date": target_date})
            null_rate = results[0].null_rate if results and results[0].null_rate else 0.0

            null_rates[field] = null_rate

            if null_rate > self.MAX_NULL_RATE:
                problem_fields.append(f"{field}={null_rate:.1%}")

        return {
            "passed": len(problem_fields) == 0,
            "null_rates": null_rates,
            "problem_fields": problem_fields
        }


# Convenience function for integration
def evaluate_phase4_to_phase5_gate(target_date: str) -> GateResult:
    """
    Convenience function to evaluate Phase 4→5 gate.

    Args:
        target_date: Date to evaluate (YYYY-MM-DD)

    Returns:
        GateResult with decision and details
    """
    gate = Phase4ToPhase5Gate()
    return gate.evaluate(target_date)


# CLI entry point
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python phase4_to_phase5_gate.py YYYY-MM-DD")
        sys.exit(1)

    target_date = sys.argv[1]

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Evaluate gate
    result = evaluate_phase4_to_phase5_gate(target_date)

    # Print results
    print("\n" + "=" * 70)
    print(f"Phase 4→5 Gate Evaluation: {target_date}")
    print("=" * 70)
    print(f"\nDecision: {result.decision.value.upper()}")
    print(f"Checks Passed: {result.checks_passed}/4")
    print(f"Checks Failed: {result.checks_failed}/4")

    if result.blocking_reasons:
        print("\n❌ BLOCKING REASONS:")
        for reason in result.blocking_reasons:
            print(f"  • {reason}")

    if result.warnings:
        print("\n⚠️  WARNINGS:")
        for warning in result.warnings:
            print(f"  • {warning}")

    print("\n📊 METRICS:")
    for key, value in result.metrics.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 70)

    # Return appropriate exit code
    sys.exit(0 if result.decision != GateDecision.BLOCK else 1)
