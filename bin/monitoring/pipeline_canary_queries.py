#!/usr/bin/env python3
"""
Pipeline Canary Queries (Session 135 - Resilience Layer 2)

Runs end-to-end pipeline validation queries every 30 minutes.
Validates data quality across all 6 phases using yesterday's data.

Usage:
    python bin/monitoring/pipeline_canary_queries.py

Sends alerts to #canary-alerts when validation fails.
"""

import logging
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from shared.utils.slack_alerts import send_slack_alert

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")


class CanaryCheck:
    """Represents a single canary check."""

    def __init__(
        self,
        name: str,
        phase: str,
        query: str,
        thresholds: Dict[str, Dict[str, float]],
        description: str
    ):
        self.name = name
        self.phase = phase
        self.query = query
        self.thresholds = thresholds
        self.description = description


# Define canary queries for each phase
CANARY_CHECKS = [
    CanaryCheck(
        name="Phase 1 - Scrapers",
        phase="phase1_scrapers",
        query="""
        SELECT
            COUNT(DISTINCT game_date) as game_dates,
            COUNT(DISTINCT game_id) as games
        FROM
            `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
        WHERE
            game_date >= CURRENT_DATE() - 2
        """,
        thresholds={
            'game_dates': {'min': 1},  # At least 1 recent game date
            'games': {'min': 2}  # At least 2 games in last 2 days
        },
        description="Validates scrapers populated raw data"
    ),

    CanaryCheck(
        name="Phase 2 - Raw Processing",
        phase="phase2_raw_processing",
        query="""
        SELECT
            COUNT(DISTINCT game_id) as games,
            COUNT(*) as player_records,
            COUNTIF(player_name IS NULL) as null_player_names,
            COUNTIF(team_abbr IS NULL) as null_team_abbr
        FROM
            `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
        WHERE
            game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """,
        thresholds={
            'games': {'min': 2},  # Expect at least 2 games
            'player_records': {'min': 40},  # At least 40 player records (20 per game)
            'null_player_names': {'max': 0},  # No NULL player names
            'null_team_abbr': {'max': 0}  # No NULL team abbreviations
        },
        description="Validates raw game data processing"
    ),

    CanaryCheck(
        name="Phase 3 - Analytics",
        phase="phase3_analytics",
        query="""
        SELECT
            COUNT(*) as records,
            COUNTIF(minutes_played IS NULL AND is_dnp = FALSE) as null_minutes,
            COUNTIF(points IS NULL AND is_dnp = FALSE) as null_points,
            AVG(CASE WHEN is_dnp = FALSE THEN minutes_played END) as avg_minutes,
            AVG(CASE WHEN is_dnp = FALSE THEN points END) as avg_points
        FROM
            `nba-props-platform.nba_analytics.player_game_summary`
        WHERE
            game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """,
        thresholds={
            'records': {'min': 40},  # At least 40 player records
            'null_minutes': {'max': 0},  # No NULL minutes
            'null_points': {'max': 0},  # No NULL points
            'avg_minutes': {'min': 15},  # Average minutes should be reasonable
            'avg_points': {'min': 8}  # Average points should be reasonable
        },
        description="Validates analytics processing and player stats"
    ),

    CanaryCheck(
        name="Phase 4 - Precompute",
        phase="phase4_precompute",
        query="""
        SELECT
            COUNT(DISTINCT player_lookup) as players,
            AVG(feature_quality_score) as avg_quality,
            COUNTIF(feature_quality_score < 70) as low_quality_count,
            COUNTIF(early_season_flag) as early_season_count,
            -- Session 139: Quality visibility canaries
            ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / NULLIF(COUNT(*), 0), 1) as quality_ready_pct,
            COUNTIF(quality_alert_level = 'red') as red_alert_count,
            ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality,
            -- Session 147: Cache miss rate tracking
            ROUND(COUNTIF(cache_miss_fallback_used) * 100.0 / NULLIF(COUNT(*), 0), 1) as cache_miss_rate_pct
        FROM
            `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE
            game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """,
        thresholds={
            'players': {'min': 100},  # At least 100 players tracked
            'avg_quality': {'min': 70},  # Average quality score > 70
            'low_quality_count': {'max': 50},  # Not too many low quality features
            'quality_ready_pct': {'min': 60},  # Session 139: At least 60% quality-ready
            'red_alert_count': {'max': 30},  # Session 139: Not too many red alerts
            'avg_matchup_quality': {'min': 40},  # Session 139: Catches Session 132 scenario
            'cache_miss_rate_pct': {'max': 5}  # Session 147: Cache miss rate should be near 0% for daily
        },
        description="Validates precomputed ML features and quality visibility"
    ),

    CanaryCheck(
        name="Phase 5 - Predictions",
        phase="phase5_predictions",
        query="""
        SELECT
            COUNT(*) as predictions,
            COUNT(DISTINCT player_lookup) as players,
            COUNTIF(predicted_points IS NULL) as null_predictions,
            COUNTIF(current_points_line IS NOT NULL) as predictions_with_lines,
            AVG(confidence_score) as avg_confidence
        FROM
            `nba-props-platform.nba_predictions.player_prop_predictions`
        WHERE
            game_date = CURRENT_DATE()
            AND is_active = TRUE
        """,
        thresholds={
            'predictions': {'min': 50},  # At least 50 active predictions
            'players': {'min': 20},  # At least 20 players
            'null_predictions': {'max': 0},  # No NULL predicted values
            'predictions_with_lines': {'min': 20},  # At least 20 predictions have lines
            'avg_confidence': {'min': 0.4}  # Average confidence should be reasonable
        },
        description="Validates prediction generation"
    ),

    CanaryCheck(
        name="Phase 6 - Publishing",
        phase="phase6_publishing",
        query="""
        SELECT
            COUNT(*) as signal_records,
            COUNTIF(daily_signal IS NULL) as null_signal,
            COUNTIF(pct_over IS NULL) as null_pct_over
        FROM
            `nba-props-platform.nba_predictions.daily_prediction_signals`
        WHERE
            game_date = CURRENT_DATE()
            AND system_id = 'catboost_v9'
        """,
        thresholds={
            'signal_records': {'min': 1},  # At least 1 signal record
            'null_signal': {'max': 0},  # No NULL signals
            'null_pct_over': {'max': 0}  # No NULL pct_over
        },
        description="Validates prediction publishing and signals"
    ),
]


def run_canary_query(client: bigquery.Client, check: CanaryCheck) -> Tuple[bool, Dict, Optional[str]]:
    """
    Run a canary query and validate thresholds.

    Args:
        client: BigQuery client
        check: CanaryCheck to run

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        logger.info(f"Running canary: {check.name}")

        query_job = client.query(check.query)
        results = list(query_job.result())

        if not results:
            return False, {}, f"Query returned no results"

        row = results[0]
        metrics = dict(row.items())

        # Validate thresholds
        violations = []
        for metric_name, threshold in check.thresholds.items():
            if metric_name not in metrics:
                violations.append(f"{metric_name}: metric not found")
                continue

            value = metrics[metric_name]
            if value is None:
                violations.append(f"{metric_name}: NULL value")
                continue

            if 'min' in threshold and value < threshold['min']:
                violations.append(
                    f"{metric_name}: {value} < {threshold['min']} (min)"
                )

            if 'max' in threshold and value > threshold['max']:
                violations.append(
                    f"{metric_name}: {value} > {threshold['max']} (max)"
                )

        if violations:
            error_msg = "\n".join(f"  • {v}" for v in violations)
            return False, metrics, error_msg

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error running canary {check.name}: {e}")
        return False, {}, str(e)


def format_canary_results(results: List[Tuple[CanaryCheck, bool, Dict, Optional[str]]]) -> str:
    """
    Format canary results for Slack.

    Args:
        results: List of (check, passed, metrics, error) tuples

    Returns:
        Formatted Slack message
    """
    failed_checks = [(check, metrics, error) for check, passed, metrics, error in results if not passed]
    passed_checks = [check for check, passed, _, _ in results if passed]

    if not failed_checks:
        lines = [
            "✅ *Pipeline Canary - All Checks Passed*",
            "",
            f"All {len(passed_checks)} phases validated successfully:",
        ]
        for check in passed_checks:
            lines.append(f"• {check.name}")

        return "\n".join(lines)

    # Failed checks
    lines = [
        "🚨 *Pipeline Canary - Failures Detected*",
        "",
        f"❌ {len(failed_checks)} failed | ✅ {len(passed_checks)} passed",
        ""
    ]

    for check, metrics, error in failed_checks:
        lines.append(f"*{check.name}*")
        lines.append(f"_{check.description}_")

        if error:
            lines.append("```")
            lines.append(error)
            lines.append("```")

        if metrics:
            lines.append("Metrics:")
            for key, value in metrics.items():
                lines.append(f"  • {key}: {value}")

        lines.append("")

    lines.append("*Investigation Steps:*")
    lines.append("1. Check recent deployments: `./bin/whats-deployed.sh`")
    lines.append("2. Review pipeline logs for affected phase")
    lines.append("3. Run manual validation queries")
    lines.append("")
    lines.append("_Canary queries run against yesterday's data for stability_")

    return "\n".join(lines)


def main():
    """Main entry point."""
    logger.info("Starting pipeline canary queries")

    client = bigquery.Client(project=PROJECT_ID)

    results = []
    for check in CANARY_CHECKS:
        passed, metrics, error = run_canary_query(client, check)

        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{check.name}: {status}")

        if not passed:
            logger.warning(f"  Error: {error}")

        results.append((check, passed, metrics, error))

    # Check if any failures
    failures = [r for r in results if not r[1]]

    if failures:
        logger.warning(f"Found {len(failures)} canary failures")

        message = format_canary_results(results)

        # Send to #canary-alerts
        success = send_slack_alert(
            message=message,
            channel="#canary-alerts",
            alert_type="PIPELINE_CANARY_FAILURE"
        )

        if success:
            logger.info("Sent canary failure alert to Slack")
        else:
            logger.error("Failed to send canary alert")

        return 1
    else:
        logger.info("All canary checks passed - no alerts sent")
        return 0


if __name__ == "__main__":
    sys.exit(main())
