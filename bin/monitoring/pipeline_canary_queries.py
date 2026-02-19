#!/usr/bin/env python3
"""
Pipeline Canary Queries (Session 135 - Resilience Layer 2)

Runs end-to-end pipeline validation queries every 30 minutes.
Validates data quality across all 6 phases using yesterday's data.

Usage:
    python bin/monitoring/pipeline_canary_queries.py

Sends alerts to #canary-alerts when validation fails.
"""

import json
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
            'low_quality_count': {'max': 100},  # Session 199: Increased from 50 to reduce alert fatigue
            'quality_ready_pct': {'min': 60},  # Session 139: At least 60% quality-ready
            'red_alert_count': {'max': 30},  # Session 139: Not too many red alerts
            'avg_matchup_quality': {'min': 40},  # Session 139: Catches Session 132 scenario
            'cache_miss_rate_pct': {'max': 5}  # Session 147: Cache miss rate should be near 0% for daily
        },
        description="Validates precomputed ML features and quality visibility"
    ),

    # Session 199: Gap detection for Phase 3
    # Detects when games are scheduled but no analytics data produced
    # More precise than record count - distinguishes "no games" from "pipeline gap"
    CanaryCheck(
        name="Phase 3 - Gap Detection",
        phase="phase3_gap_detection",
        query="""
        WITH scheduled AS (
            SELECT COUNT(*) as expected_games
            FROM `nba-props-platform.nba_raw.nbac_schedule`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
              AND game_status_text = 'Final'
        ),
        actual AS (
            SELECT
                COUNT(DISTINCT game_id) as actual_games,
                COUNT(*) as player_records
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        )
        SELECT
            s.expected_games,
            a.actual_games,
            a.player_records,
            CASE
                WHEN s.expected_games > 0 AND a.actual_games = 0 THEN 1
                ELSE 0
            END as gap_detected
        FROM scheduled s
        CROSS JOIN actual a
        """,
        thresholds={
            'gap_detected': {'max': 0}  # FAIL if games scheduled but no analytics data
        },
        description="Detects complete analytics gaps (games scheduled but no data produced)"
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

    # Session 159: Prediction gap alerting
    # Feb 7-8 2026 had zero predictions with nobody alerted.
    # This check catches "games scheduled but no predictions" scenarios.
    CanaryCheck(
        name="Phase 5 - Prediction Gap",
        phase="phase5_prediction_gap",
        query="""
        WITH scheduled_games AS (
            SELECT COUNT(*) as games_today
            FROM `nba-props-platform.nba_reference.nba_schedule`
            WHERE game_date = CURRENT_DATE()
              AND game_status IN (1, 2, 3)  -- Scheduled, In Progress, or Final
        ),
        predictions_today AS (
            SELECT COUNT(*) as prediction_count,
                   COUNT(DISTINCT game_id) as games_with_predictions
            FROM `nba-props-platform.nba_predictions.player_prop_predictions`
            WHERE game_date = CURRENT_DATE()
              AND is_active = TRUE
        )
        SELECT
            g.games_today,
            p.prediction_count,
            p.games_with_predictions,
            CASE
                WHEN g.games_today > 0 AND p.prediction_count = 0 THEN 1
                ELSE 0
            END as prediction_gap
        FROM scheduled_games g
        CROSS JOIN predictions_today p
        """,
        thresholds={
            'prediction_gap': {'max': 0},  # FAIL if games exist but zero predictions
        },
        description="Detects days with scheduled games but no predictions generated"
    ),

    # Session 210: Cross-model prediction coverage parity
    # Session 209 discovered Q43/Q45 had 0 predictions for 2 days undetected.
    # This check catches when shadow models silently stop producing predictions.
    CanaryCheck(
        name="Phase 5 - Shadow Model Coverage",
        phase="phase5_shadow_coverage",
        query="""
        WITH champion AS (
            SELECT COUNT(*) as champion_count
            FROM `nba-props-platform.nba_predictions.player_prop_predictions`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
              AND system_id = 'catboost_v9'
              AND is_active = TRUE
        ),
        known_models AS (
            SELECT DISTINCT system_id
            FROM `nba-props-platform.nba_predictions.player_prop_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
              AND system_id LIKE 'catboost_v9_%'
        ),
        yesterday_models AS (
            SELECT system_id, COUNT(*) as predictions
            FROM `nba-props-platform.nba_predictions.player_prop_predictions`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
              AND system_id LIKE 'catboost_v9_%'
              AND is_active = TRUE
            GROUP BY 1
        )
        SELECT
            c.champion_count,
            (SELECT COUNT(*) FROM known_models) as known_shadow_models,
            (SELECT COUNT(*) FROM yesterday_models) as active_shadow_models,
            (SELECT COUNT(*) FROM known_models k
             LEFT JOIN yesterday_models y ON k.system_id = y.system_id
             WHERE y.system_id IS NULL) as missing_models,
            (SELECT COUNT(*) FROM yesterday_models y, champion c2
             WHERE c2.champion_count > 0
               AND 100.0 * y.predictions / c2.champion_count < 50) as critical_models,
            CASE
                WHEN c.champion_count = 0 THEN 0
                WHEN EXISTS(
                    SELECT 1 FROM known_models k
                    LEFT JOIN yesterday_models y ON k.system_id = y.system_id
                    WHERE y.system_id IS NULL
                ) THEN 1
                WHEN EXISTS(
                    SELECT 1 FROM yesterday_models y
                    WHERE 100.0 * y.predictions / c.champion_count < 50
                ) THEN 1
                ELSE 0
            END as shadow_gap_detected
        FROM champion c
        """,
        thresholds={
            'shadow_gap_detected': {'max': 0},  # FAIL if any model missing or <50%
            'missing_models': {'max': 0},  # FAIL if known models completely absent
        },
        description="Detects shadow models with zero or critically low prediction counts vs champion"
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

    # Session 209: Quality filtering validation checks
    CanaryCheck(
        name="Filter Consistency - Quality Required Subsets",
        phase="quality_filtering",
        query="""
        -- For subsets with require_quality_ready=TRUE, verify zero non-green picks
        -- Query materialized picks (not aggregated view) to validate filter application
        SELECT COUNT(*) as non_green_count
        FROM `nba-props-platform.nba_predictions.current_subset_picks` csp
        JOIN `nba-props-platform.nba_predictions.dynamic_subset_definitions` d USING (subset_id)
        WHERE d.require_quality_ready = TRUE
          AND csp.quality_alert_level != 'green'
          AND csp.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND csp.version_id = (
              SELECT MAX(version_id)
              FROM `nba-props-platform.nba_predictions.current_subset_picks`
              WHERE game_date = csp.game_date
          )
        """,
        thresholds={
            'non_green_count': {'max': 0}  # FAIL if any non-green predictions in quality-required subsets
        },
        description="Session 209: Validates quality filtering applied to quality-required subsets (12.1% vs 50.3% hit rate)"
    ),

    CanaryCheck(
        name="Phase 4 - Category Quality Breakdown",
        phase="phase4_quality",
        query="""
        -- Track category-level quality (not just aggregate)
        -- Session 132 lesson: aggregate feature_quality_score hid component failure
        SELECT
            ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality,
            ROUND(AVG(player_history_quality_pct), 1) as avg_player_history_quality,
            ROUND(AVG(vegas_quality_pct), 1) as avg_vegas_quality,
            COUNTIF(matchup_quality_pct < 40) as low_matchup_count,
            COUNTIF(player_history_quality_pct < 40) as low_player_history_count,
            COUNTIF(vegas_quality_pct < 40) as low_vegas_count
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date = CURRENT_DATE()
        """,
        thresholds={
            'avg_matchup_quality': {'min': 40},
            'avg_player_history_quality': {'min': 40},
            'avg_vegas_quality': {'min': 40}
        },
        description="Session 209: Tracks category-level quality to catch component failures hidden by aggregates"
    ),

    CanaryCheck(
        name="Filter Coverage - Quality Distribution",
        phase="quality_distribution",
        query="""
        -- Verify exported data contains only green predictions
        -- Session 209: Critical gap - exporters should never publish non-green quality
        SELECT
            COUNT(*) as total_picks,
            COUNTIF(quality_alert_level = 'green') as green_picks,
            COUNTIF(quality_alert_level != 'green') as non_green_picks
        FROM `nba-props-platform.nba_predictions.current_subset_picks`
        WHERE game_date = CURRENT_DATE()
          AND version_id = (
              SELECT MAX(version_id)
              FROM `nba-props-platform.nba_predictions.current_subset_picks`
              WHERE game_date = CURRENT_DATE()
          )
        """,
        thresholds={
            'non_green_picks': {'max': 0},  # FAIL if any non-green in exported picks
            'total_picks': {'min': 1}  # At least some picks
        },
        description="Session 209: Validates exported subset picks contain only green quality predictions"
    ),

    CanaryCheck(
        name="Phase 3 - Player Game Summary Duplicates",
        phase="phase3_duplicates",
        query="""
        -- Detect duplicate rows in player_game_summary (same player + game)
        -- Session 294: Duplicates caused -1 days_rest in tonight exports
        SELECT
            COUNT(*) as duplicate_player_games
        FROM (
            SELECT player_lookup, game_id
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date >= CURRENT_DATE() - 14
            GROUP BY player_lookup, game_id
            HAVING COUNT(*) > 1
        )
        """,
        thresholds={
            'duplicate_player_games': {'max': 0},  # FAIL if any duplicates
        },
        description="Session 294: Detects duplicate rows that cause -1 days_rest in exports"
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


def auto_backfill_shadow_models(target_date: str) -> bool:
    """
    Auto-heal shadow model prediction gaps by triggering BACKFILL.

    Session 210: Safe because /start with BACKFILL only generates predictions
    for models that don't already have them. Champion predictions are untouched.

    Args:
        target_date: Date string (YYYY-MM-DD) to backfill

    Returns:
        True if backfill was triggered successfully
    """
    import google.auth
    import google.auth.transport.requests

    coordinator_url = os.environ.get(
        "COORDINATOR_URL",
        "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"
    )

    try:
        # Get identity token for Cloud Run auth
        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        # Use ID token for Cloud Run
        from google.oauth2 import id_token
        token = id_token.fetch_id_token(auth_req, coordinator_url)

        import urllib.request
        payload = json.dumps({
            "game_date": target_date,
            "prediction_run_mode": "BACKFILL",
            "skip_completeness_check": True
        }).encode()

        req = urllib.request.Request(
            f"{coordinator_url}/start",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            batch_id = result.get("batch_id", "unknown")
            logger.info(f"Shadow model backfill triggered for {target_date}: batch={batch_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to trigger shadow model backfill for {target_date}: {e}")
        return False


def check_scheduler_health() -> Tuple[bool, Dict, Optional[str]]:
    """
    Check Cloud Scheduler job health (Session 242).

    Counts jobs with non-success last execution status.
    Alert threshold: > 3 failing jobs (Session 219 baseline was 0).
    Excludes NOT_FOUND (expected on no-game days for prediction jobs).

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        from google.cloud import scheduler_v1

        scheduler_client = scheduler_v1.CloudSchedulerClient()
        parent = f"projects/{PROJECT_ID}/locations/us-west2"

        failing_jobs = []
        total_jobs = 0

        for job in scheduler_client.list_jobs(parent=parent):
            total_jobs += 1
            status_code = job.status.code if job.status else None
            # Code 0 = OK, Code 5 = NOT_FOUND (expected on off-days for prediction jobs)
            if status_code is not None and status_code not in (0, 5):
                failing_jobs.append(f"{job.name.split('/')[-1]} (code={status_code})")

        metrics = {
            'total_jobs': total_jobs,
            'failing_jobs': len(failing_jobs),
            'failing_job_names': failing_jobs[:10],  # Cap at 10 for readability
        }

        threshold = 3
        if len(failing_jobs) > threshold:
            error_msg = (
                f"failing_jobs: {len(failing_jobs)} > {threshold} (max)\n"
                f"  Failing: {', '.join(failing_jobs[:10])}"
            )
            return False, metrics, error_msg

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error checking scheduler health: {e}")
        return False, {}, f"Scheduler health check error: {e}"


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

    # Session 242: Check Cloud Scheduler job health
    scheduler_check = CanaryCheck(
        name="Scheduler Health",
        phase="scheduler_health",
        query="",  # Not a BQ query — uses Cloud Scheduler API
        thresholds={'failing_jobs': {'max': 3}},
        description="Detects Cloud Scheduler job failures (regression from Session 219 baseline of 0)"
    )
    sched_passed, sched_metrics, sched_error = check_scheduler_health()
    sched_status = "✅ PASS" if sched_passed else "❌ FAIL"
    logger.info(f"Scheduler Health: {sched_status}")
    if not sched_passed:
        logger.warning(f"  Error: {sched_error}")
    results.append((scheduler_check, sched_passed, sched_metrics, sched_error))

    # Session 210: Auto-heal shadow model gaps
    for check, passed, metrics, error in results:
        if check.phase == "phase5_shadow_coverage" and not passed:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            logger.info(f"Shadow model gap detected — auto-triggering BACKFILL for {yesterday}")

            backfill_ok = auto_backfill_shadow_models(yesterday)

            heal_msg = (
                f"Auto-heal {'triggered' if backfill_ok else 'FAILED'}: "
                f"BACKFILL for {yesterday} "
                f"(missing_models={metrics.get('missing_models', '?')}, "
                f"critical_models={metrics.get('critical_models', '?')})"
            )
            logger.info(heal_msg)

            send_slack_alert(
                message=f"{'🔧' if backfill_ok else '🚨'} *Shadow Model Auto-Heal*\n{heal_msg}",
                channel="#nba-alerts",
                alert_type="SHADOW_MODEL_AUTO_HEAL"
            )

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
