#!/usr/bin/env python3
"""
Pipeline Canary Queries (Session 135 - Resilience Layer 2)

Tiered pipeline validation queries for cost-efficient monitoring.
Validates data quality across all 6 phases using yesterday's data.

Usage:
    python bin/monitoring/pipeline_canary_queries.py                # Run ALL checks
    python bin/monitoring/pipeline_canary_queries.py --tier critical # Revenue-impacting only (15-min cadence)
    python bin/monitoring/pipeline_canary_queries.py --tier routine  # Data quality / historical (60-min cadence)

Tier design (Session 509):
    CRITICAL (15-min): prediction freshness, grading, pick generation, model health, MLB predictions
    ROUTINE  (60-min): data quality, historical consistency, feature store, fleet info, duplicate audits

Sends alerts to #canary-alerts when validation fails.
"""

import argparse
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
            'records': {'min': 20},  # At least 20 player records (1 playoff game = 20+)
            'null_minutes': {'max': 0},  # No NULL minutes
            'null_points': {'max': 0},  # No NULL points
            'avg_minutes': {'min': 15},  # Average minutes should be reasonable
            'avg_points': {'min': 6}  # Lowered from 8 — playoff defense reduces scoring
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
            'players': {'min': 20},  # Lowered from 100 — playoffs have 1-2 games/night (20+ players)
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
        WITH enabled_models AS (
            SELECT model_id
            FROM `nba-props-platform.nba_predictions.model_registry`
            WHERE enabled = TRUE AND status = 'active'
        ),
        yesterday_models AS (
            SELECT system_id, COUNT(*) as predictions
            FROM `nba-props-platform.nba_predictions.player_prop_predictions`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
              AND is_active = TRUE
              AND system_id IN (SELECT model_id FROM enabled_models)
            GROUP BY 1
        )
        SELECT
            (SELECT COUNT(*) FROM enabled_models) as enabled_models,
            (SELECT COUNT(*) FROM yesterday_models) as active_models,
            (SELECT COUNT(*) FROM enabled_models e
             LEFT JOIN yesterday_models y ON e.model_id = y.system_id
             WHERE y.system_id IS NULL) as missing_models,
            CASE
                WHEN (SELECT COUNT(*) FROM enabled_models) = 0 THEN 0
                WHEN EXISTS(
                    SELECT 1 FROM enabled_models e
                    LEFT JOIN yesterday_models y ON e.model_id = y.system_id
                    WHERE y.system_id IS NULL
                ) THEN 1
                ELSE 0
            END as shadow_gap_detected
        """,
        thresholds={
            'shadow_gap_detected': {'max': 0},  # FAIL if any enabled model missing predictions
            'missing_models': {'max': 0},  # FAIL if enabled models have no predictions yesterday
        },
        description="Detects enabled models with zero prediction counts yesterday (per-model pipeline)"
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
            AND system_id IN (
                SELECT model_id FROM `nba-props-platform.nba_predictions.model_registry`
                WHERE enabled = TRUE
            )
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

    # Session 302: Partial game coverage detection
    # Feb 22 had 11 games but only 6 completed when Phase 3 ran.
    # Existing gap detection only catches 0/N, not 7/11 partial gaps.
    CanaryCheck(
        name="Phase 3 - Partial Game Coverage",
        phase="phase3_partial_coverage",
        query="""
        WITH scheduled AS (
            SELECT COUNT(*) as expected_games
            FROM `nba-props-platform.nba_reference.nba_schedule`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
              AND game_status = 3
        ),
        actual AS (
            SELECT COUNT(DISTINCT game_id) as actual_games
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        )
        SELECT
            s.expected_games,
            a.actual_games,
            CASE
                WHEN s.expected_games > 0 AND a.actual_games < s.expected_games THEN 1
                ELSE 0
            END as partial_gap_detected,
            s.expected_games - a.actual_games as missing_games
        FROM scheduled s
        CROSS JOIN actual a
        """,
        thresholds={
            'partial_gap_detected': {'max': 0},  # FAIL if ANY final game missing from analytics
        },
        description="Detects partial analytics gaps (some games processed but not all final games)"
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

    CanaryCheck(
        name="MLB Phase 5 - Pitcher Strikeout Predictions",
        phase="mlb_phase5_predictions",
        query="""
        SELECT COUNT(*) as prediction_count
        FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """,
        thresholds={
            'prediction_count': {'min': 3}
        },
        description="Validates MLB pitcher strikeout predictions generated for yesterday (min 3 on game days)"
    ),

    CanaryCheck(
        name="MLB Phase 6 - Best Bets Published",
        phase="mlb_phase6_best_bets",
        # Alerts when the BB pipeline silently produced zero picks despite having
        # predictions to work from. Previous version queried pitcher_strikeouts with
        # non-existent columns (recommended_bet, ensemble_prediction) and had min=0,
        # so 3+ days of zero-pick outages on Apr 15-17 passed silently.
        # Ratio: pick_count / pred_count. Expect >= 1% on game days. 0 preds → game-less
        # day (ratio = 1.0 as a pass-through).
        query="""
        WITH counts AS (
          SELECT
            (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
             WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) AS pick_count,
            (SELECT COUNT(*) FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
             WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)) AS pred_count
        )
        SELECT
          pick_count,
          pred_count,
          SAFE_DIVIDE(pick_count, NULLIF(pred_count, 0)) AS pick_ratio,
          IF(pred_count = 0, 1.0, SAFE_DIVIDE(pick_count, pred_count)) AS pick_ratio_with_floor
        FROM counts
        """,
        thresholds={
            # Fails when predictions exist but ZERO picks landed — signal-pipeline broke.
            # pick_ratio_with_floor returns 1.0 on no-game days so this only fires when
            # the pipeline actually ran and silently produced nothing.
            'pick_ratio_with_floor': {'min': 0.001}
        },
        description="Alerts when MLB best-bets pipeline produced 0 picks despite predictions existing (silent failure)"
    ),

    CanaryCheck(
        name="Signal Health Daily - Freshness",
        phase="monitoring_meta",
        query="""
        SELECT DATE_DIFF(CURRENT_DATE(), MAX(game_date), DAY) AS staleness_days
        FROM `nba-props-platform.nba_predictions.signal_health_daily`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        """,
        thresholds={
            'staleness_days': {'max': 2}
        },
        description="Alerts if signal_health_daily table is more than 2 days stale — decay detection runs on stale data"
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


def auto_retrigger_phase3(target_date: str) -> bool:
    """
    Auto-heal Phase 3 partial game coverage by re-triggering analytics processing.

    Session 302: When partial gap detected (e.g., 7/11 games processed),
    re-trigger Phase 3 for the affected date. Safe because Phase 3 uses
    MERGE_UPDATE strategy — already-processed games are skipped or updated.

    Args:
        target_date: Date string (YYYY-MM-DD) to reprocess

    Returns:
        True if reprocessing was triggered successfully
    """
    import google.auth
    import google.auth.transport.requests

    phase3_url = os.environ.get(
        "PHASE3_URL",
        "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
    )

    try:
        # Get identity token for Cloud Run auth
        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        from google.oauth2 import id_token
        token = id_token.fetch_id_token(auth_req, phase3_url)

        import urllib.request
        payload = json.dumps({
            "start_date": target_date,
            "end_date": target_date,
            "backfill_mode": True
        }).encode()

        req = urllib.request.Request(
            f"{phase3_url}/process-date-range",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            logger.info(f"Phase 3 reprocessing triggered for {target_date}: {result}")
            return True

    except Exception as e:
        logger.error(f"Failed to trigger Phase 3 reprocessing for {target_date}: {e}")
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
            # Skip jobs that have never run (no last_attempt_time) — these are
            # one-time reminders or future-dated jobs, not active failures.
            has_run = bool(job.last_attempt_time and job.last_attempt_time.seconds > 0)
            # Code 0 = OK, Code 5 = NOT_FOUND (expected on off-days for prediction jobs)
            if has_run and status_code is not None and status_code not in (0, 5):
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


def check_live_grading_content(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """
    Check live-grading JSON content quality (Session 302).

    Hybrid GCS+BQ check: reads yesterday's live-grading JSON from GCS,
    compares graded count against BQ final game count.

    Catches the Feb 22 scenario where live-grading file was updated every 3 min
    but contained ALL pending predictions with zero actuals (BDL_API_KEY missing).

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        from google.cloud import storage

        yesterday = (date.today() - timedelta(days=1)).isoformat()

        # Step 1: Check if yesterday had final games (skip if no games)
        game_query = f"""
        SELECT
            COUNTIF(game_status = 3) as final_games,
            COUNT(*) as total_games
        FROM `nba-props-platform.nba_reference.nba_schedule`
        WHERE game_date = '{yesterday}'
          AND game_status IN (1, 2, 3)
        """
        game_result = list(bq_client.query(game_query).result(timeout=30))[0]
        final_games = game_result.final_games or 0
        total_games = game_result.total_games or 0

        if total_games == 0:
            return True, {'skipped': True, 'reason': 'no_games_yesterday'}, None

        if final_games == 0:
            return True, {'skipped': True, 'reason': 'no_final_games_yesterday', 'total_games': total_games}, None

        # Step 2: Read live-grading JSON from GCS
        gcs_client = storage.Client()
        bucket = gcs_client.bucket("nba-props-platform-api")
        blob = bucket.blob("v1/live-grading/latest.json")

        if not blob.exists():
            return False, {'final_games': final_games}, "live-grading/latest.json not found in GCS"

        content = blob.download_as_text()
        data = json.loads(content)

        predictions = data.get("predictions", [])
        game_date_in_file = data.get("game_date", "")
        total_preds = len(predictions)

        if total_preds == 0:
            return False, {
                'final_games': final_games,
                'total_predictions': 0,
                'file_game_date': game_date_in_file,
            }, "Zero predictions in live-grading JSON"

        # Step 3: Analyze content quality
        graded = sum(1 for p in predictions if p.get("grade") not in (None, "pending", "PENDING"))
        null_actual = sum(1 for p in predictions if p.get("actual") is None and p.get("actual_points") is None)
        null_source = sum(1 for p in predictions if not p.get("score_source") and not p.get("actual_source"))

        metrics = {
            'final_games': final_games,
            'total_predictions': total_preds,
            'graded_predictions': graded,
            'graded_pct': round(graded * 100.0 / total_preds, 1) if total_preds > 0 else 0,
            'null_actual_count': null_actual,
            'null_source_count': null_source,
            'file_game_date': game_date_in_file,
        }

        # If all games were final but zero predictions graded, that's a failure
        if final_games > 0 and graded == 0 and null_actual == total_preds:
            return False, metrics, (
                f"ZERO graded predictions despite {final_games} final games. "
                f"All {total_preds} predictions have null actuals. "
                f"Likely cause: BDL_API_KEY missing from live-export."
            )

        # If >80% null sources when games should be final, that's a warning
        if total_preds > 0 and null_source / total_preds > 0.8 and final_games > 0:
            return False, metrics, (
                f"{null_source}/{total_preds} predictions ({null_source*100//total_preds}%) have no score source "
                f"despite {final_games} final games."
            )

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error checking live grading content: {e}")
        return False, {}, f"Live grading content check error: {e}"


def check_pick_drought(bq_client: bigquery.Client, lookback_days: int = 3) -> Tuple[bool, Dict, Optional[str]]:
    """Session 474: Alert when best-bets picks are zero for 2+ consecutive game days.

    Checks signal_best_bets_picks against the game schedule. Zero picks on scheduled
    game days means the BB pipeline is producing no output — the most critical failure mode.

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        query = f"""
        WITH game_days AS (
            SELECT DISTINCT game_date
            FROM `{PROJECT_ID}.nba_reference.nba_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
              AND game_date < CURRENT_DATE()
              AND game_status IN (1, 2, 3)
        ),
        pick_counts AS (
            SELECT game_date, COUNT(*) AS pick_count
            FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            g.game_date,
            COALESCE(p.pick_count, 0) AS pick_count
        FROM game_days g
        LEFT JOIN pick_counts p USING (game_date)
        ORDER BY g.game_date DESC
        """
        rows = list(bq_client.query(query).result(timeout=30))

        if not rows:
            return True, {'skipped': True, 'reason': 'no_game_days_in_window'}, None

        zero_days = [str(r.game_date) for r in rows if r.pick_count == 0]
        per_day = {str(r.game_date): r.pick_count for r in rows}
        metrics = {
            'game_days_checked': len(rows),
            'zero_pick_days': zero_days,
            'per_day': per_day,
        }

        if len(zero_days) >= 2:
            return False, metrics, (
                f"PICK DROUGHT: {len(zero_days)} consecutive game day(s) with 0 best-bet picks "
                f"({', '.join(zero_days)}). BB pipeline producing no output. "
                f"Check: model edge distribution (avg_abs_diff), filter audit, model registry."
            )
        if len(zero_days) == 1:
            return True, metrics, None  # Single zero day — warning only, check again next cycle

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in pick drought check: {e}")
        return False, {}, f"Pick drought check error: {e}"


def check_filter_audit_jammed(bq_client: bigquery.Client, lookback_days: int = 3) -> Tuple[bool, Dict, Optional[str]]:
    """Session 474: Alert when BB pipeline has candidates but 0 pass filters for 2+ game days.

    Distinguishes two drought modes:
    - candidates > 0 but passed = 0: filter blockage or edge floor blocking everything
    - candidates = 0: upstream problem (edge collapse, model coverage gap)

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        query = f"""
        WITH game_days AS (
            SELECT DISTINCT game_date
            FROM `{PROJECT_ID}.nba_reference.nba_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
              AND game_date < CURRENT_DATE()
              AND game_status IN (1, 2, 3)
        ),
        audit AS (
            SELECT game_date,
                   SUM(total_candidates) AS candidates,
                   SUM(passed_filters) AS passed
            FROM `{PROJECT_ID}.nba_predictions.best_bets_filter_audit`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
              AND game_date < CURRENT_DATE()
            GROUP BY game_date
        )
        SELECT
            g.game_date,
            COALESCE(a.candidates, 0) AS candidates,
            COALESCE(a.passed, 0) AS passed
        FROM game_days g
        LEFT JOIN audit a USING (game_date)
        ORDER BY g.game_date DESC
        """
        rows = list(bq_client.query(query).result(timeout=30))

        if not rows:
            return True, {'skipped': True, 'reason': 'no_game_days_in_window'}, None

        jammed_days = [str(r.game_date) for r in rows if r.candidates > 0 and r.passed == 0]
        empty_days = [str(r.game_date) for r in rows if r.candidates == 0]
        per_day = {str(r.game_date): {'candidates': r.candidates, 'passed': r.passed} for r in rows}
        metrics = {
            'game_days_checked': len(rows),
            'jammed_days': jammed_days,
            'empty_days': empty_days,
            'per_day': per_day,
        }

        if len(jammed_days) >= 2:
            return False, metrics, (
                f"BB PIPELINE JAMMED: {len(jammed_days)} game day(s) with candidates but 0 passed "
                f"({', '.join(jammed_days)}). Filters or edge floor blocking all candidates. "
                f"Check: avg_abs_diff on player_prop_predictions (edge collapse?), "
                f"signal count gates (real_sc), OVER edge 5+ floor."
            )

        if len(empty_days) >= 2:
            return False, metrics, (
                f"BB PIPELINE EMPTY: {len(empty_days)} game day(s) with 0 candidates entering "
                f"the pipeline ({', '.join(empty_days)}). Likely edge collapse (avg_abs_diff < 1.5) "
                f"or model coverage gap (enabled models not generating predictions)."
            )

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in filter audit check: {e}")
        return False, {}, f"Filter audit check error: {e}"


def check_registry_blocked_enabled(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 477: Alert when enabled models have status=blocked in the registry.

    This fires same-day. Root cause: decay CF sets status=blocked on degradation and
    never auto-unblocks. After manual re-enable or HR recovery, status stays blocked.
    BB pipeline skips ALL blocked models → 0 picks despite healthy predictions.

    Seen: Mar 20-21 2026 — v9_low_vegas + lgbm_0103_0227 both enabled=true but
    status=blocked. Produced 0 picks for 2 days undetected.
    Fix: ./bin/unblock-model.sh MODEL_ID
    """
    try:
        query = f"""
        SELECT
            COUNT(*) as blocked_enabled_count,
            STRING_AGG(model_id, ', ' ORDER BY model_id) as model_ids
        FROM `{PROJECT_ID}.nba_predictions.model_registry`
        WHERE enabled = TRUE AND status = 'blocked'
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows:
            return True, {}, None

        row = rows[0]
        count = row.blocked_enabled_count or 0
        model_ids = row.model_ids or ''
        metrics = {'blocked_enabled_count': count, 'model_ids': model_ids}

        if count > 0:
            return False, metrics, (
                f"REGISTRY MISMATCH: {count} model(s) enabled=TRUE but status='blocked'. "
                f"BB pipeline skips blocked models — these are invisible to best bets. "
                f"Models: {model_ids}. "
                f"Fix: `./bin/unblock-model.sh MODEL_ID` for each, then `./bin/refresh-model-cache.sh --verify`."
            )
        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in registry blocked enabled check: {e}")
        return False, {}, f"Registry blocked enabled check error: {e}"


def check_model_recovery_gap(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 477: Alert when a blocked model has recovered to HEALTHY performance.

    Decay CF is one-directional (HEALTHY→BLOCKED). Models that recover require manual
    unblock. This check surfaces models where model_performance_daily shows HEALTHY
    but registry still shows blocked — safe to unblock.
    """
    try:
        query = f"""
        WITH latest_perf AS (
            SELECT model_id, state AS model_state, rolling_hr_7d, rolling_n_7d AS n_graded_7d
            FROM (
                SELECT model_id, state, rolling_hr_7d, rolling_n_7d,
                    ROW_NUMBER() OVER (PARTITION BY model_id ORDER BY game_date DESC) as rn
                FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
                WHERE game_date >= CURRENT_DATE() - 7
            )
            WHERE rn = 1
        )
        SELECT
            mr.model_id,
            lp.model_state,
            ROUND(lp.rolling_hr_7d, 1) as rolling_hr_7d,
            lp.n_graded_7d
        FROM `{PROJECT_ID}.nba_predictions.model_registry` mr
        JOIN latest_perf lp ON mr.model_id = lp.model_id
        WHERE mr.enabled = TRUE
          AND mr.status = 'blocked'
          AND lp.model_state = 'HEALTHY'
          AND lp.rolling_hr_7d >= 52.4
          AND lp.n_graded_7d >= 10
        ORDER BY lp.rolling_hr_7d DESC
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows:
            return True, {'recovery_gap_count': 0}, None

        recovery_models = [
            f"{r.model_id} ({r.rolling_hr_7d}% HR, N={r.n_graded_7d})"
            for r in rows
        ]
        metrics = {'recovery_gap_count': len(rows), 'models': recovery_models}
        return False, metrics, (
            f"MODEL RECOVERY GAP: {len(rows)} model(s) HEALTHY in performance "
            f"but still blocked in registry. Safe to unblock. "
            f"Models: {', '.join(recovery_models)}. "
            f"Fix: `./bin/unblock-model.sh MODEL_ID` for each."
        )

    except Exception as e:
        logger.error(f"Error in model recovery gap check: {e}")
        return False, {}, f"Model recovery gap check error: {e}"


def check_bb_candidates_today(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 477: Alert when Phase 4 completed but BB pipeline produced 0 candidates.

    Distinguishes from normal 0-pick days: here the pipeline stalled entirely
    (0 rows in model_bb_candidates) vs. pipeline ran but found no picks.
    Only fires 2+ hours after Phase 4 completion to avoid false positives during normal run.
    """
    try:
        query = f"""
        WITH phase4_done AS (
            SELECT MAX(completed_at) as phase4_completed_at
            FROM `{PROJECT_ID}.nba_orchestration.phase_completions`
            WHERE game_date = CURRENT_DATE()
              AND phase IN ('phase4', 'ml_feature_store', 'precompute')
        ),
        bb_candidates AS (
            SELECT COUNT(*) as candidate_count
            FROM `{PROJECT_ID}.nba_predictions.model_bb_candidates`
            WHERE game_date = CURRENT_DATE()
        )
        SELECT
            p.phase4_completed_at,
            b.candidate_count,
            CASE
                WHEN p.phase4_completed_at IS NOT NULL
                  AND b.candidate_count = 0
                  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), p.phase4_completed_at, HOUR) >= 2
                THEN 1
                ELSE 0
            END as pipeline_stalled
        FROM phase4_done p
        CROSS JOIN bb_candidates b
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows:
            return True, {'skipped': True, 'reason': 'no_phase_completion_data'}, None

        row = rows[0]
        metrics = {
            'phase4_completed_at': str(row.phase4_completed_at) if row.phase4_completed_at else None,
            'candidate_count': row.candidate_count,
            'pipeline_stalled': row.pipeline_stalled,
        }
        if row.pipeline_stalled:
            return False, metrics, (
                f"BB PIPELINE STALLED: Phase 4 completed at {row.phase4_completed_at} "
                f"but 0 BB candidates after 2+ hours. BB pipeline did not run. "
                f"Fix: `gcloud pubsub topics publish nba-phase6-export-trigger "
                f"--project=nba-props-platform "
                f"--message='{{\"export_types\": [\"signal-best-bets\"], \"target_date\": \"YYYY-MM-DD\"}}'`"
            )
        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in BB candidates today check: {e}")
        return False, {}, f"BB candidates today check error: {e}"


def check_edge_collapse_alert(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 477 Error 004: Alert when enabled models drop below avg_abs_diff collapse threshold.

    CatBoost collapse threshold: 1.2 (below this, symmetric trees reconstruct the line —
    picks are indistinguishable from noise). LGBM/XGBoost threshold: 1.4.
    Only fires when model has >= 30 predictions (guards against early-morning false positives).

    Root cause: Models trained on tight-market data (Vegas MAE < 5.0) predict close to the
    line by design. Fix: Use Feb-trained LGBM models (train_end <= Feb 28).
    """
    try:
        query = f"""
        WITH enabled_models AS (
            SELECT model_id,
                   CASE
                       WHEN LOWER(model_id) LIKE '%lgbm%' OR LOWER(model_id) LIKE '%xgb%' THEN 'lgbm_xgb'
                       ELSE 'catboost'
                   END AS framework
            FROM `{PROJECT_ID}.nba_predictions.model_registry`
            WHERE enabled = TRUE AND status = 'active'
        ),
        model_edges AS (
            SELECT p.system_id,
                   COUNT(*) AS n_predictions,
                   ROUND(AVG(ABS(p.predicted_points - p.current_points_line)), 3) AS avg_abs_diff
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
            WHERE p.game_date = CURRENT_DATE()
              AND p.is_active = TRUE
              AND p.current_points_line IS NOT NULL
            GROUP BY p.system_id
        )
        SELECT
            m.model_id,
            m.framework,
            e.n_predictions,
            e.avg_abs_diff,
            CASE
                WHEN m.framework = 'catboost' AND e.avg_abs_diff < 1.2 THEN TRUE
                WHEN m.framework = 'lgbm_xgb' AND e.avg_abs_diff < 1.4 THEN TRUE
                ELSE FALSE
            END AS collapsed
        FROM enabled_models m
        JOIN model_edges e ON m.model_id = e.system_id
        WHERE e.n_predictions >= 30
        ORDER BY e.avg_abs_diff ASC
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows:
            return True, {'skipped': True, 'reason': 'no_model_predictions_yet'}, None

        collapsed = [r for r in rows if r.collapsed]
        all_models = {r.model_id: {'framework': r.framework, 'avg_abs_diff': float(r.avg_abs_diff), 'n': r.n_predictions} for r in rows}
        metrics = {
            'models_checked': len(rows),
            'collapsed_count': len(collapsed),
            'all_models': all_models,
        }

        healthy_count = len(rows) - len(collapsed)
        metrics['healthy_count'] = healthy_count

        if collapsed:
            details = ', '.join(f"{r.model_id} ({r.avg_abs_diff:.2f})" for r in collapsed)
            error_msg = (
                f"EDGE COLLAPSE ({len(collapsed)} model(s)): avg_abs_diff below threshold "
                f"(CatBoost<1.2, LGBM/XGB<1.4). Models: {details}. "
                f"Picks from collapsed models are statistically indistinguishable from noise. "
                f"Fix: Disable collapsed models, use Feb-trained LGBM (train_end <= Feb 28)."
            )
            # Session 478: escalate when only 1 healthy model remains — fleet is critically thin
            if healthy_count < 2:
                error_msg += (
                    f" CRITICAL: only {healthy_count} healthy-edge model(s) remain — "
                    f"entire BB pipeline depends on a single model."
                )
            return False, metrics, error_msg
        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in edge collapse alert check: {e}")
        return False, {}, f"Edge collapse alert check error: {e}"


def check_grading_freshness(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 478: Alert when prediction_accuracy has no records for 2+ recent game days.

    This is the catch-all for any grading outage regardless of cause. A SQL bug,
    CF crash, or Pub/Sub failure all produce the same symptom: no graded records.
    The 30-minute cadence means outages are caught within hours, not days.

    Root cause this prevented: multi-column IN subquery in prediction_accuracy_processor.py
    caused BadRequest that was silently swallowed, returning [] as if no predictions existed.
    This ran 6 days undetected because no canary checked prediction_accuracy freshness.
    """
    try:
        query = f"""
        WITH recent_game_days AS (
            SELECT DISTINCT game_date
            FROM `{PROJECT_ID}.nba_reference.nba_schedule`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 DAY)
              AND game_date < CURRENT_DATE()
              AND game_status = 3
            ORDER BY game_date DESC
            LIMIT 2
        ),
        graded AS (
            SELECT game_date, COUNT(*) AS graded_count
            FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
            WHERE game_date IN (SELECT game_date FROM recent_game_days)
              AND prediction_correct IS NOT NULL
            GROUP BY game_date
        )
        SELECT
            (SELECT COUNT(*) FROM recent_game_days) AS game_days_with_finals,
            (SELECT COUNT(*) FROM graded WHERE graded_count > 0) AS game_days_with_grades,
            ARRAY_AGG(gd.game_date ORDER BY gd.game_date DESC) AS recent_game_days,
            ARRAY_AGG(COALESCE(g.graded_count, 0) ORDER BY gd.game_date DESC) AS grade_counts
        FROM recent_game_days gd
        LEFT JOIN graded g USING (game_date)
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows or rows[0].game_days_with_finals == 0:
            return True, {'skipped': True, 'reason': 'no_recent_completed_games'}, None

        row = rows[0]
        finals = int(row.game_days_with_finals)
        graded = int(row.game_days_with_grades)
        game_days = [str(d) for d in (row.recent_game_days or [])]
        grade_counts = list(row.grade_counts or [])

        metrics = {
            'game_days_with_finals': finals,
            'game_days_with_grades': graded,
            'recent_game_days': game_days,
            'grade_counts': grade_counts,
        }

        if finals >= 2 and graded == 0:
            return False, metrics, (
                f"GRADING OUTAGE: prediction_accuracy has 0 graded records for "
                f"the last {finals} game days ({', '.join(game_days)}). "
                f"Grading pipeline is broken. Check phase5b-grading CF logs for BadRequest errors. "
                f"Recovery: fix the root cause, push, then run: "
                f"./bin/recover-grading.sh {game_days[-1] if game_days else 'DATE'} "
                f"{game_days[0] if game_days else 'DATE'}"
            )
        if finals >= 1 and graded == 0:
            return False, metrics, (
                f"GRADING STALE: no graded records for {game_days[0] if game_days else 'last game day'}. "
                f"Check phase5b-grading CF logs."
            )
        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in grading freshness check: {e}")
        return False, {}, f"Grading freshness check error: {e}"


def check_new_model_no_predictions(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 477 Error 005: Alert when a newly registered model has 0 predictions today.

    Models registered < 48h ago with enabled=TRUE and status='active' should appear
    in player_prop_predictions today if games are scheduled. Zero predictions means
    the worker hasn't loaded the new registry entry (4h TTL auto-refresh).

    Fix: ./bin/refresh-model-cache.sh --verify
    """
    try:
        query = f"""
        WITH new_models AS (
            SELECT model_id
            FROM `{PROJECT_ID}.nba_predictions.model_registry`
            WHERE enabled = TRUE
              AND status = 'active'
              AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
        ),
        games_today AS (
            SELECT COUNT(*) AS game_count
            FROM `{PROJECT_ID}.nba_reference.nba_schedule`
            WHERE game_date = CURRENT_DATE()
              AND game_status IN (1, 2, 3)
        ),
        model_predictions AS (
            SELECT system_id, COUNT(*) AS prediction_count
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE game_date = CURRENT_DATE()
              AND is_active = TRUE
            GROUP BY system_id
        )
        SELECT
            nm.model_id,
            COALESCE(mp.prediction_count, 0) AS prediction_count,
            (SELECT game_count FROM games_today) AS games_today
        FROM new_models nm
        LEFT JOIN model_predictions mp ON nm.model_id = mp.system_id
        WHERE (SELECT game_count FROM games_today) > 0
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows:
            return True, {'skipped': True, 'reason': 'no_new_models_or_no_games'}, None

        missing = [r for r in rows if r.prediction_count == 0]
        all_new = {r.model_id: r.prediction_count for r in rows}
        metrics = {
            'new_models_checked': len(rows),
            'missing_predictions_count': len(missing),
            'model_details': all_new,
        }

        if missing:
            model_ids = ', '.join(r.model_id for r in missing)
            return False, metrics, (
                f"NEW MODEL NO PREDICTIONS: {len(missing)} newly registered model(s) have 0 predictions today. "
                f"Models: {model_ids}. "
                f"Worker 4h TTL cache hasn't loaded new registry entries. "
                f"Fix: `./bin/refresh-model-cache.sh --verify`"
            )
        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in new model no predictions check: {e}")
        return False, {}, f"New model no predictions check error: {e}"


def check_all_json_duplicate_picks() -> Tuple[bool, Dict, Optional[str]]:
    """Session 493: Check all.json for duplicate (player_lookup, game_date) pairs.

    Downloads gs://nba-props-platform-api/v1/best-bets/all.json from GCS and
    scans every pick across today + all historical weeks for duplicate
    (player_lookup, game_date) entries. Zero tolerance — any duplicate is a FAIL.

    Duplicates in all.json mean the site is showing the same pick twice, which
    inflates the displayed W-L record and confuses users. Root cause: a dedup
    regression in the exporter or in _query_all_picks.

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        from google.cloud import storage

        gcs_client = storage.Client()
        bucket = gcs_client.bucket("nba-props-platform-api")
        blob = bucket.blob("v1/best-bets/all.json")

        if not blob.exists():
            return True, {'skipped': True, 'reason': 'all_json_not_found'}, None

        content = blob.download_as_text()
        data = json.loads(content)

        # Collect all (player_lookup, game_date) pairs across today + history
        seen: Dict[str, int] = {}  # key -> count
        duplicates = []

        # Today's picks (top-level 'today' array)
        file_date = data.get('date', '')
        today_picks = data.get('today', [])
        for pick in today_picks:
            pl = pick.get('player_lookup', '')
            if not pl:
                continue
            key = f"{pl}::{file_date}"
            seen[key] = seen.get(key, 0) + 1

        # Historical picks (weeks -> days -> picks)
        for week in data.get('weeks', []):
            for day in week.get('days', []):
                day_date = day.get('date', '')
                for pick in day.get('picks', []):
                    pl = pick.get('player_lookup', '')
                    if not pl:
                        continue
                    key = f"{pl}::{day_date}"
                    seen[key] = seen.get(key, 0) + 1

        for key, count in seen.items():
            if count > 1:
                duplicates.append({'key': key, 'count': count})

        metrics = {
            'file_date': file_date,
            'today_pick_count': len(today_picks),
            'total_pairs_checked': len(seen),
            'duplicate_pair_count': len(duplicates),
        }

        if duplicates:
            dup_summary = ', '.join(
                f"{d['key']} (x{d['count']})" for d in duplicates[:5]
            )
            if len(duplicates) > 5:
                dup_summary += f' ... and {len(duplicates) - 5} more'
            return False, metrics, (
                f"DUPLICATE PICKS IN all.json: {len(duplicates)} (player_lookup, game_date) "
                f"pair(s) appear more than once. "
                f"Duplicates: {dup_summary}. "
                f"Root cause: dedup regression in best_bets_all_exporter or _query_all_picks. "
                f"Check: Session 493 pre-export dedup safety net (best_bets_all_exporter.py) "
                f"and prediction_accuracy_deduped view."
            )

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in all.json duplicate picks check: {e}")
        return False, {}, f"all.json duplicate picks check error: {e}"


def check_fleet_diversity(bq_client: bigquery.Client) -> Tuple[bool, Dict, Optional[str]]:
    """Session 487: Alert when all enabled models are the same ML family.

    If every enabled model has 'lgbm' (or 'xgb', or 'catboost') in its model_id,
    cross-model signals like combo_3way and book_disagreement cannot fire because
    they require diverse model agreement. This check surfaces fleet monoculture
    before it silently kills those high-HR signals.

    Also alerts when ALL pairs of enabled models have pairwise r >= 0.95 — a proxy
    for clone-fleet detection without running the full correlation matrix.

    Returns:
        Tuple of (passed, metrics, error_message)
    """
    try:
        query = f"""
        SELECT
            model_id,
            CASE
                WHEN LOWER(model_id) LIKE '%lgbm%' OR LOWER(model_id) LIKE '%lightgbm%' THEN 'lgbm'
                WHEN LOWER(model_id) LIKE '%xgb%' OR LOWER(model_id) LIKE '%xgboost%' THEN 'xgb'
                WHEN LOWER(model_id) LIKE '%catboost%' OR LOWER(model_id) LIKE '%cb_%' THEN 'catboost'
                ELSE 'other'
            END AS model_family
        FROM `{PROJECT_ID}.nba_predictions.model_registry`
        WHERE enabled = TRUE AND status = 'active'
        ORDER BY model_id
        """
        rows = list(bq_client.query(query).result(timeout=30))
        if not rows:
            return True, {'skipped': True, 'reason': 'no_enabled_active_models'}, None

        model_ids = [r.model_id for r in rows]
        families = [r.model_family for r in rows]
        distinct_families = set(families)
        non_lgbm_count = sum(1 for f in families if f != 'lgbm')
        lgbm_count = sum(1 for f in families if f == 'lgbm')

        metrics = {
            'enabled_model_count': len(rows),
            'distinct_families': list(distinct_families),
            'distinct_family_count': len(distinct_families),
            'lgbm_count': lgbm_count,
            'non_lgbm_count': non_lgbm_count,
            'model_ids': model_ids,
        }

        warnings = []

        # Check 1: Only 1 distinct family across the entire fleet
        if len(distinct_families) == 1:
            only_family = list(distinct_families)[0]
            warnings.append(
                f"ALL {len(rows)} enabled model(s) are {only_family.upper()} family. "
                f"combo_3way and book_disagreement require model diversity to fire — "
                f"these signals will be dead. Add at least 1 non-{only_family} model."
            )

        # Check 2: Zero non-LGBM models (Session 487 root cause)
        if non_lgbm_count == 0 and lgbm_count > 0:
            if 'ALL' not in (warnings[0] if warnings else ''):
                warnings.append(
                    f"ZERO non-LGBM models in fleet ({lgbm_count} LGBM-only). "
                    f"Session 487 lesson: all-LGBM fleet = r>=0.95 clones = "
                    f"combo_3way/book_disagreement cannot fire."
                )

        if warnings:
            return False, metrics, (
                "FLEET DIVERSITY WARNING: " + " | ".join(warnings) + " "
                f"Models: {', '.join(model_ids)}. "
                f"Fix: `./bin/retrain.sh --all --enable` with a non-LGBM family, "
                f"or enable an existing CatBoost/XGBoost model from the registry."
            )

        return True, metrics, None

    except Exception as e:
        logger.error(f"Error in fleet diversity check: {e}")
        return False, {}, f"Fleet diversity check error: {e}"


def _is_break_window(client) -> bool:
    """Return True if no regular-season games in the last 3 days (i.e., we're in a break)."""
    from shared.utils.schedule_guard import has_regular_season_games
    for days_ago in range(1, 4):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        if has_regular_season_games(d, bq_client=client):
            return False  # Found a game — not in a break
    return True


# Tier classification (Session 509 — tiered canary monitoring):
# CRITICAL (15-min): Revenue-impacting checks needing fast detection
# ROUTINE  (60-min): Data quality, historical consistency, fleet info
CRITICAL_CHECKS = frozenset({
    # NBA prediction & pick generation
    "phase3_gap_detection",
    "phase5_predictions",
    "phase5_prediction_gap",
    "phase5_shadow_coverage",
    "phase6_publishing",
    "phase3_partial_coverage",
    # Best bets pipeline health
    "bb_pick_drought",
    "bb_filter_audit",
    "bb_candidates_today",
    # Model health
    "registry_blocked_enabled",
    "edge_collapse_alert",
    # Grading pipeline
    "grading_freshness",
    # MLB predictions (revenue-impacting)
    "mlb_phase5_predictions",
    "mlb_phase6_best_bets",
})


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Pipeline canary monitoring queries")
    parser.add_argument(
        "--tier",
        choices=["critical", "routine", "all"],
        default=None,
        help="Which tier of checks to run: critical (15-min), routine (60-min), or all (default). "
             "Falls back to CANARY_TIER env var, then 'all'."
    )
    args = parser.parse_args()

    # CLI --tier takes precedence over CANARY_TIER env var, default is "all"
    CANARY_TIER = args.tier or os.environ.get("CANARY_TIER", "all")
    logger.info(f"Starting pipeline canary queries (CANARY_TIER={CANARY_TIER})")

    def _should_run(phase: str) -> bool:
        """Return True if this phase should run for the current tier."""
        if CANARY_TIER == "all":
            return True
        if CANARY_TIER == "critical":
            return phase in CRITICAL_CHECKS
        if CANARY_TIER == "routine":
            return phase not in CRITICAL_CHECKS
        # Unknown tier — run everything to be safe
        return True

    client = bigquery.Client(project=PROJECT_ID)

    # Session 299: Skip Phase 1/2 checks on break days (no regular-season games in last 3 days)
    is_break = _is_break_window(client)
    if is_break:
        logger.info("Break day detected — Phase 1/2 canary checks will be skipped")
    BREAK_DAY_SKIP_PHASES = {'phase1_scrapers', 'phase2_raw_processing'}

    results = []
    for check in CANARY_CHECKS:
        if not _should_run(check.phase):
            logger.info(f"{check.name}: ⏭️  SKIPPED (tier={CANARY_TIER})")
            continue

        if is_break and check.phase in BREAK_DAY_SKIP_PHASES:
            logger.info(f"{check.name}: ⏭️  SKIPPED (break day — no recent regular-season games)")
            results.append((check, True, {'skipped': True, 'reason': 'break_day'}, None))
            continue

        passed, metrics, error = run_canary_query(client, check)

        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{check.name}: {status}")

        if not passed:
            logger.warning(f"  Error: {error}")

        results.append((check, passed, metrics, error))

    # Session 242: Check Cloud Scheduler job health
    if _should_run("scheduler_health"):
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

    # Session 474: Check best-bets pick drought (zero picks on game days)
    if not is_break:
        if _should_run("bb_pick_drought"):
            drought_check = CanaryCheck(
                name="Best Bets Pick Drought",
                phase="bb_pick_drought",
                query="",
                thresholds={},
                description="Alerts when 0 best-bet picks published for 2+ consecutive game days"
            )
            drought_passed, drought_metrics, drought_error = check_pick_drought(client)
            drought_status = "✅ PASS" if drought_passed else "❌ FAIL"
            logger.info(f"Best Bets Pick Drought: {drought_status}")
            if not drought_passed:
                logger.warning(f"  Error: {drought_error}")
            results.append((drought_check, drought_passed, drought_metrics, drought_error))

        if _should_run("bb_filter_audit"):
            filter_check = CanaryCheck(
                name="BB Filter Audit",
                phase="bb_filter_audit",
                query="",
                thresholds={},
                description="Alerts when candidates enter BB pipeline but 0 pass filters for 2+ game days"
            )
            filter_passed, filter_metrics, filter_error = check_filter_audit_jammed(client)
            filter_status = "✅ PASS" if filter_passed else "❌ FAIL"
            logger.info(f"BB Filter Audit: {filter_status}")
            if not filter_passed:
                logger.warning(f"  Error: {filter_error}")
            results.append((filter_check, filter_passed, filter_metrics, filter_error))

    # Session 302: Check live-grading content quality (hybrid GCS+BQ)
    if not is_break and _should_run("live_grading_content"):
        grading_check = CanaryCheck(
            name="Live-Grading Content Quality",
            phase="live_grading_content",
            query="",  # Not a BQ query — uses GCS + BQ hybrid
            thresholds={},
            description="Detects stale live-grading content (all pending, zero actuals) despite file updates (Session 302)"
        )
        grading_passed, grading_metrics, grading_error = check_live_grading_content(client)
        grading_status = "✅ PASS" if grading_passed else "❌ FAIL"
        if grading_metrics.get('skipped'):
            logger.info(f"Live-Grading Content: ⏭️  SKIPPED ({grading_metrics.get('reason')})")
        else:
            logger.info(f"Live-Grading Content: {grading_status}")
            if not grading_passed:
                logger.warning(f"  Error: {grading_error}")
        results.append((grading_check, grading_passed, grading_metrics, grading_error))
    elif is_break:
        logger.info("Break day — skipping live-grading content check")

    # Session 210: Auto-heal shadow model gaps (Session 299: skip on break days)
    if not is_break:
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
    else:
        logger.info("Break day — skipping shadow model auto-heal")

    # Session 477: Registry integrity checks — fire regardless of break day
    # (registry state is always relevant, not just on game days)
    if _should_run("registry_blocked_enabled"):
        registry_check = CanaryCheck(
            name="Registry Blocked Models",
            phase="registry_blocked_enabled",
            query="",
            thresholds={},
            description="Detects enabled models with status=blocked — invisible to BB pipeline (Session 477)"
        )
        registry_passed, registry_metrics, registry_error = check_registry_blocked_enabled(client)
        registry_status = "✅ PASS" if registry_passed else "❌ FAIL"
        logger.info(f"Registry Blocked Models: {registry_status}")
        if not registry_passed:
            logger.warning(f"  Error: {registry_error}")
        results.append((registry_check, registry_passed, registry_metrics, registry_error))

    if _should_run("model_recovery_gap"):
        recovery_check = CanaryCheck(
            name="Model Recovery Gap",
            phase="model_recovery_gap",
            query="",
            thresholds={},
            description="Detects HEALTHY models still blocked in registry — safe to unblock (Session 477)"
        )
        recovery_passed, recovery_metrics, recovery_error = check_model_recovery_gap(client)
        recovery_status = "✅ PASS" if recovery_passed else "❌ FAIL"
        logger.info(f"Model Recovery Gap: {recovery_status}")
        if not recovery_passed:
            logger.warning(f"  Error: {recovery_error}")
        results.append((recovery_check, recovery_passed, recovery_metrics, recovery_error))

    if not is_break and _should_run("bb_candidates_today"):
        bb_pipeline_check = CanaryCheck(
            name="BB Pipeline Today",
            phase="bb_candidates_today",
            query="",
            thresholds={},
            description="Detects Phase 4 complete but BB pipeline stalled with 0 candidates (Session 477)"
        )
        bb_pipeline_passed, bb_pipeline_metrics, bb_pipeline_error = check_bb_candidates_today(client)
        bb_pipeline_status = "✅ PASS" if bb_pipeline_passed else "❌ FAIL"
        logger.info(f"BB Pipeline Today: {bb_pipeline_status}")
        if not bb_pipeline_passed:
            logger.warning(f"  Error: {bb_pipeline_error}")
        results.append((bb_pipeline_check, bb_pipeline_passed, bb_pipeline_metrics, bb_pipeline_error))

    # Session 478: Grading freshness — runs every 30 min, catches any grading outage
    # regardless of cause. Highest-ROI canary added this session.
    if _should_run("grading_freshness"):
        grading_freshness_check = CanaryCheck(
            name="Grading Freshness",
            phase="grading_freshness",
            query="",
            thresholds={},
            description="Session 478: Alerts when prediction_accuracy has 0 graded records for 2+ recent game days — catches any grading outage within one canary cycle"
        )
        gf_passed, gf_metrics, gf_error = check_grading_freshness(client)
        gf_status = "✅ PASS" if gf_passed else "❌ FAIL"
        if gf_metrics.get('skipped'):
            logger.info(f"Grading Freshness: ⏭️  SKIPPED ({gf_metrics.get('reason')})")
        else:
            logger.info(f"Grading Freshness: {gf_status}")
            if not gf_passed:
                logger.warning(f"  Error: {gf_error}")
        results.append((grading_freshness_check, gf_passed, gf_metrics, gf_error))

    # Session 477 Error 004: Edge collapse alert (game-day only — needs today's predictions)
    if not is_break and _should_run("edge_collapse_alert"):
        edge_collapse_check = CanaryCheck(
            name="Edge Collapse Alert",
            phase="edge_collapse_alert",
            query="",
            thresholds={},
            description="Alerts when enabled CatBoost avg_abs_diff<1.2 or LGBM<1.4 — picks indistinguishable from noise (Session 477)"
        )
        edge_passed, edge_metrics, edge_error = check_edge_collapse_alert(client)
        edge_status = "✅ PASS" if edge_passed else "❌ FAIL"
        if edge_metrics.get('skipped'):
            logger.info(f"Edge Collapse Alert: ⏭️  SKIPPED ({edge_metrics.get('reason')})")
        else:
            logger.info(f"Edge Collapse Alert: {edge_status}")
            if not edge_passed:
                logger.warning(f"  Error: {edge_error}")
        results.append((edge_collapse_check, edge_passed, edge_metrics, edge_error))

    # Session 477 Error 005: New model with no predictions (game-day only)
    if not is_break and _should_run("new_model_no_predictions"):
        new_model_check = CanaryCheck(
            name="New Model No Predictions",
            phase="new_model_no_predictions",
            query="",
            thresholds={},
            description="Alerts when model registered <48h ago has 0 predictions — worker cache not refreshed (Session 477)"
        )
        nm_passed, nm_metrics, nm_error = check_new_model_no_predictions(client)
        nm_status = "✅ PASS" if nm_passed else "❌ FAIL"
        if nm_metrics.get('skipped'):
            logger.info(f"New Model No Predictions: ⏭️  SKIPPED ({nm_metrics.get('reason')})")
        else:
            logger.info(f"New Model No Predictions: {nm_status}")
            if not nm_passed:
                logger.warning(f"  Error: {nm_error}")
        results.append((new_model_check, nm_passed, nm_metrics, nm_error))

    # Session 302: Auto-heal Phase 3 partial game coverage gaps
    if not is_break:
        for check, passed, metrics, error in results:
            if check.phase == "phase3_partial_coverage" and not passed:
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                missing = metrics.get('missing_games', '?')
                logger.info(f"Phase 3 partial gap detected ({missing} missing games) — auto-triggering reprocessing for {yesterday}")

                retrigger_ok = auto_retrigger_phase3(yesterday)

                heal_msg = (
                    f"Phase 3 auto-heal {'triggered' if retrigger_ok else 'FAILED'}: "
                    f"reprocessing {yesterday} "
                    f"(expected={metrics.get('expected_games', '?')}, "
                    f"actual={metrics.get('actual_games', '?')}, "
                    f"missing={missing})"
                )
                logger.info(heal_msg)

                send_slack_alert(
                    message=f"{'🔧' if retrigger_ok else '🚨'} *Phase 3 Partial Coverage Auto-Heal*\n{heal_msg}",
                    channel="#nba-alerts",
                    alert_type="PHASE3_PARTIAL_COVERAGE_AUTO_HEAL"
                )
    else:
        logger.info("Break day — skipping Phase 3 partial coverage auto-heal")

    # Session 493: Check all.json published picks for duplicate (player_lookup, game_date) pairs
    if _should_run("all_json_duplicate_picks"):
        all_json_dup_check = CanaryCheck(
            name="all.json Duplicate Picks",
            phase="all_json_duplicate_picks",
            query="",  # Not a BQ query — uses GCS
            thresholds={},
            description="Alerts when all.json contains duplicate picks for the same (player_lookup, game_date) — zero tolerance (Session 493)"
        )
        all_json_passed, all_json_metrics, all_json_error = check_all_json_duplicate_picks()
        all_json_status = "✅ PASS" if all_json_passed else "❌ FAIL"
        if all_json_metrics.get('skipped'):
            logger.info(f"all.json Duplicate Picks: ⏭️  SKIPPED ({all_json_metrics.get('reason')})")
        else:
            logger.info(f"all.json Duplicate Picks: {all_json_status} (duplicate_pairs={all_json_metrics.get('duplicate_pair_count', '?')})")
            if not all_json_passed:
                logger.warning(f"  Error: {all_json_error}")
        results.append((all_json_dup_check, all_json_passed, all_json_metrics, all_json_error))

    # Session 487: Fleet diversity check — all enabled models same family kills combo signals
    if _should_run("fleet_diversity"):
        fleet_diversity_check = CanaryCheck(
            name="Fleet Diversity",
            phase="fleet_diversity",
            query="",
            thresholds={},
            description="Alerts when all enabled models are the same ML family (e.g. all LGBM) — kills combo_3way and book_disagreement signals (Session 487)"
        )
        fleet_passed, fleet_metrics, fleet_error = check_fleet_diversity(client)
        fleet_status = "✅ PASS" if fleet_passed else "❌ FAIL"
        logger.info(f"Fleet Diversity: {fleet_status} (families={fleet_metrics.get('distinct_families', '?')}, non_lgbm={fleet_metrics.get('non_lgbm_count', '?')})")
        if not fleet_passed:
            logger.warning(f"  Error: {fleet_error}")
        results.append((fleet_diversity_check, fleet_passed, fleet_metrics, fleet_error))

    # Session 493: Check prediction_accuracy for duplicate (player, game_date, system_id) groups
    if _should_run("pa_duplicate_groups"):
        pa_dup_check = CanaryCheck(
            name="prediction_accuracy Duplicate Groups",
            phase="pa_duplicate_groups",
            query=f"""
                SELECT COUNT(*) AS duplicate_group_count
                FROM (
                  SELECT player_lookup, game_date, system_id
                  FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
                  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
                    AND recommendation IN ('OVER', 'UNDER')
                  GROUP BY player_lookup, game_date, system_id
                  HAVING COUNT(*) > 1
                )
            """,
            thresholds={"duplicate_group_count": {"max": 50}},
            description="Alerts when prediction_accuracy has >50 duplicate (player,date,model) groups in last 7 days — indicates grading processor dedup regression (Session 493)"
        )
        pa_dup_passed, pa_dup_metrics, pa_dup_error = run_canary_query(client, pa_dup_check)
        pa_dup_status = "✅ PASS" if pa_dup_passed else "❌ FAIL"
        logger.info(f"prediction_accuracy Duplicates: {pa_dup_status} (count={pa_dup_metrics.get('duplicate_group_count', '?')})")
        if not pa_dup_passed:
            logger.warning(f"  Error: {pa_dup_error}")
        results.append((pa_dup_check, pa_dup_passed, pa_dup_metrics, pa_dup_error))

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
