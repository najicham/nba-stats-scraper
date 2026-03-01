"""
Data Quality Alerts Cloud Function

Monitors critical data quality metrics and sends alerts when issues are detected.
Designed to catch issues like those discovered on 2026-01-26:
- Zero predictions generated
- Low usage_rate coverage
- Duplicate records
- Missing prop lines

Triggered by: Cloud Scheduler (recommended: run at 7 PM ET daily)

Deployment:
    gcloud functions deploy data-quality-alerts \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/data_quality_alerts \
        --entry-point check_data_quality \
        --trigger-http \
        --allow-unauthenticated \
        --timeout=540 \
        --memory=512MB \
        --set-env-vars GCP_PROJECT_ID=nba-props-platform

Scheduler:
    gcloud scheduler jobs create http data-quality-alerts-job \
        --schedule "0 19 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Author: Claude Code
Created: 2026-01-27
Version: 1.0
"""

import logging
import os
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
import functions_framework

# Performance diagnostics for model health monitoring (Session 57)
# This import may fail when deployed as Cloud Function without shared module
try:
    from shared.utils.performance_diagnostics import PerformanceDiagnostics
    HAS_PERFORMANCE_DIAGNOSTICS = True
except ImportError:
    HAS_PERFORMANCE_DIAGNOSTICS = False
    PerformanceDiagnostics = None

try:
    from shared.config.model_selection import get_champion_model_id
    CHAMPION_MODEL_ID = get_champion_model_id()
except ImportError:
    CHAMPION_MODEL_ID = 'catboost_v12'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL_ERROR = os.environ.get('SLACK_WEBHOOK_URL_ERROR')
SLACK_WEBHOOK_URL_WARNING = os.environ.get('SLACK_WEBHOOK_URL_WARNING')


class DataQualityMonitor:
    """Monitor data quality metrics and send alerts."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def check_zero_predictions(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check for zero predictions alert.

        Returns:
            (alert_level, message, details)
        """
        query = f"""
        WITH prediction_counts AS (
            SELECT
                COUNT(DISTINCT player_lookup) as players_predicted,
                COUNT(DISTINCT CASE WHEN recommendation IN ('OVER', 'UNDER') THEN player_lookup END) as actionable_predictions,
                COUNTIF(has_prop_line = FALSE OR has_prop_line IS NULL) as no_line_count
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date
                AND system_id = '{CHAMPION_MODEL_ID}'
        ),
        expected_games AS (
            SELECT
                COUNT(DISTINCT game_id) as games_today,
                COUNT(DISTINCT player_lookup) as eligible_players
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = @game_date
                AND (avg_minutes_per_game_last_7 >= 15 OR current_points_line IS NOT NULL)
                AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
                AND is_production_ready = TRUE
        )
        SELECT
            COALESCE(pc.players_predicted, 0) as players_predicted,
            COALESCE(pc.actionable_predictions, 0) as actionable_predictions,
            COALESCE(pc.no_line_count, 0) as no_line_count,
            eg.games_today,
            eg.eligible_players
        FROM expected_games eg
        LEFT JOIN prediction_counts pc ON TRUE
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        row = next(result, None)

        if not row or row.games_today == 0:
            return 'OK', 'No games scheduled', {}

        details = {
            'players_predicted': row.players_predicted,
            'actionable_predictions': row.actionable_predictions,
            'no_line_count': row.no_line_count,
            'games_today': row.games_today,
            'eligible_players': row.eligible_players,
            'coverage_percent': round(row.players_predicted / row.eligible_players * 100, 2) if row.eligible_players > 0 else 0
        }

        # Alert conditions
        if row.players_predicted == 0:
            return (
                'CRITICAL',
                f'ZERO PREDICTIONS: No predictions generated for {game_date} despite {row.games_today} games scheduled. Check coordinator logs and Phase 3 timing.',
                details
            )
        elif row.players_predicted < 10:
            return (
                'WARNING',
                f'LOW PREDICTIONS: Only {row.players_predicted} players predicted for {row.games_today} games. Expected ~{row.eligible_players}.',
                details
            )
        else:
            return 'OK', 'Predictions OK', details

    def check_usage_rate_coverage(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check for low usage rate coverage.

        Returns:
            (alert_level, message, details)
        """
        query = f"""
        WITH boxscore_stats AS (
            SELECT
                COUNT(*) as total_records,
                COUNTIF(usage_rate IS NOT NULL) as with_usage_rate,
                COUNTIF(usage_rate IS NULL) as null_usage_rate
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
        ),
        game_completion AS (
            SELECT
                COUNT(*) as total_games,
                COUNTIF(game_status_text = 'Final') as completed_games
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = @game_date
        )
        SELECT
            bs.total_records,
            bs.with_usage_rate,
            bs.null_usage_rate,
            gc.completed_games,
            gc.total_games
        FROM boxscore_stats bs, game_completion gc
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        row = next(result, None)

        if not row or row.total_records == 0:
            return 'OK', 'No boxscore data yet', {}

        coverage_pct = row.with_usage_rate / row.total_records * 100 if row.total_records > 0 else 0
        all_games_complete = row.completed_games == row.total_games

        details = {
            'total_records': row.total_records,
            'with_usage_rate': row.with_usage_rate,
            'null_usage_rate': row.null_usage_rate,
            'coverage_percent': round(coverage_pct, 2),
            'completed_games': row.completed_games,
            'total_games': row.total_games
        }

        # Alert conditions
        if coverage_pct < 50 and all_games_complete:
            return (
                'CRITICAL',
                f'CRITICAL: Only {coverage_pct:.1f}% of records have usage_rate after all games completed. Boxscores may be incomplete.',
                details
            )
        elif coverage_pct < 80 and all_games_complete:
            return (
                'WARNING',
                f'LOW COVERAGE: Only {coverage_pct:.1f}% of records have usage_rate. Expected >80% after games complete.',
                details
            )
        else:
            return 'OK', 'Usage rate coverage is healthy', details

    def check_duplicates(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check for duplicate records.

        Returns:
            (alert_level, message, details)
        """
        query = f"""
        WITH duplicate_check AS (
            SELECT
                player_lookup,
                game_id,
                COUNT(*) as record_count
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
            GROUP BY player_lookup, game_id
            HAVING COUNT(*) > 1
        )
        SELECT
            COUNT(*) as duplicate_groups,
            SUM(record_count) as total_duplicate_records,
            SUM(record_count - 1) as excess_records
        FROM duplicate_check
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        row = next(result, None)

        duplicate_groups = row.duplicate_groups if row else 0
        excess_records = row.excess_records if row else 0

        details = {
            'duplicate_groups': duplicate_groups,
            'excess_records': excess_records
        }

        # Alert conditions
        if duplicate_groups == 0:
            return 'OK', 'No duplicate records detected', details
        elif duplicate_groups <= 5:
            return 'INFO', f'{duplicate_groups} minor duplicates found (likely acceptable)', details
        elif duplicate_groups <= 20:
            return 'WARNING', f'{duplicate_groups} duplicate groups detected. Check processor deduplication logic.', details
        else:
            return (
                'CRITICAL',
                f'CRITICAL: {duplicate_groups} duplicate groups ({excess_records} excess records). Processor may have run multiple times.',
                details
            )

    def check_prop_lines(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check for missing prop lines.

        Returns:
            (alert_level, message, details)
        """
        query = f"""
        WITH prop_line_stats AS (
            SELECT
                COUNT(*) as total_players,
                COUNTIF(has_prop_line = TRUE) as players_with_lines,
                COUNTIF(has_prop_line = FALSE OR has_prop_line IS NULL) as players_without_lines
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = @game_date
                AND is_production_ready = TRUE
        )
        SELECT
            total_players,
            players_with_lines,
            players_without_lines
        FROM prop_line_stats
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        row = next(result, None)

        if not row or row.total_players == 0:
            return 'OK', 'No player context data yet', {}

        coverage_pct = row.players_with_lines / row.total_players * 100 if row.total_players > 0 else 0

        details = {
            'total_players': row.total_players,
            'players_with_lines': row.players_with_lines,
            'players_without_lines': row.players_without_lines,
            'coverage_percent': round(coverage_pct, 2)
        }

        # Alert conditions
        if row.players_with_lines == 0:
            return (
                'CRITICAL',
                f'CRITICAL: 0% of {row.total_players} players have prop lines. Phase 3 likely ran before betting lines arrived.',
                details
            )
        elif coverage_pct < 20:
            return (
                'CRITICAL',
                f'CRITICAL: Only {coverage_pct:.1f}% of players have prop lines. Phase 3 may need to be re-run.',
                details
            )
        elif coverage_pct < 50:
            return (
                'WARNING',
                f'WARNING: Only {coverage_pct:.1f}% of players have prop lines. Check prop scraper timing.',
                details
            )
        elif coverage_pct < 80:
            return (
                'INFO',
                f'LOW COVERAGE: {coverage_pct:.1f}% prop line coverage. Some players missing betting lines.',
                details
            )
        else:
            return 'OK', 'Prop line coverage is healthy', details

    def check_bdl_quality(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check BDL data quality by comparing against NBA.com gamebook.

        BDL is currently disabled as backup source due to data quality issues.
        This check monitors if/when quality improves enough to re-enable.

        Also stores discrepancies in source_discrepancies table for trend analysis.

        Returns:
            (alert_level, message, details)
        """
        # Compare BDL vs NBAC for the date
        query = f"""
        WITH gamebook AS (
            SELECT
                player_lookup,
                player_name,
                SAFE_CAST(REGEXP_EXTRACT(minutes, r'^([0-9]+)') AS INT64) as minutes_int,
                points
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date = @game_date
              AND player_status = 'active'
        ),
        bdl AS (
            SELECT
                player_lookup,
                player_full_name,
                SAFE_CAST(minutes AS INT64) as minutes_int,
                points
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date = @game_date
        ),
        comparison AS (
            SELECT
                g.player_lookup,
                g.player_name,
                g.minutes_int as gamebook_min,
                g.points as gamebook_pts,
                b.minutes_int as bdl_min,
                b.points as bdl_pts,
                ABS(COALESCE(g.minutes_int, 0) - COALESCE(b.minutes_int, 0)) as minutes_diff,
                ABS(COALESCE(g.points, 0) - COALESCE(b.points, 0)) as points_diff,
                CASE
                    WHEN b.minutes_int IS NULL THEN 'missing_in_bdl'
                    WHEN ABS(g.minutes_int - b.minutes_int) > 5 OR ABS(g.points - b.points) > 5 THEN 'major'
                    WHEN ABS(g.minutes_int - b.minutes_int) > 2 OR ABS(g.points - b.points) > 2 THEN 'minor'
                    ELSE 'match'
                END as discrepancy_severity
            FROM gamebook g
            LEFT JOIN bdl b ON g.player_lookup = b.player_lookup
        )
        SELECT
            COUNT(*) as total_players,
            COUNTIF(bdl_min IS NOT NULL) as bdl_coverage,
            COUNTIF(discrepancy_severity = 'match') as exact_matches,
            COUNTIF(discrepancy_severity = 'minor') as minor_discrepancies,
            COUNTIF(discrepancy_severity = 'major') as major_discrepancies,
            COUNTIF(discrepancy_severity = 'missing_in_bdl') as missing_in_bdl,
            AVG(CASE WHEN bdl_min IS NOT NULL THEN minutes_diff END) as avg_minutes_diff,
            AVG(CASE WHEN bdl_pts IS NOT NULL THEN points_diff END) as avg_points_diff
        FROM comparison
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        row = next(result, None)

        if not row or row.total_players == 0:
            return 'OK', 'No gamebook data yet to compare', {}

        coverage_pct = (row.bdl_coverage / row.total_players * 100) if row.total_players > 0 else 0
        major_pct = (row.major_discrepancies / row.total_players * 100) if row.total_players > 0 else 0
        accuracy_pct = (row.exact_matches / row.bdl_coverage * 100) if row.bdl_coverage > 0 else 0

        details = {
            'total_players': row.total_players,
            'bdl_coverage': row.bdl_coverage,
            'coverage_percent': round(coverage_pct, 1),
            'exact_matches': row.exact_matches,
            'minor_discrepancies': row.minor_discrepancies,
            'major_discrepancies': row.major_discrepancies,
            'missing_in_bdl': row.missing_in_bdl,
            'major_discrepancy_pct': round(major_pct, 1),
            'accuracy_pct': round(accuracy_pct, 1),
            'avg_minutes_diff': round(row.avg_minutes_diff, 1) if row.avg_minutes_diff else 0,
            'avg_points_diff': round(row.avg_points_diff, 1) if row.avg_points_diff else 0,
            'bdl_status': 'DISABLED',  # Current status
            'recommendation': 'Keep disabled' if major_pct > 5 else 'Consider re-enabling'
        }

        # Store discrepancies in BigQuery for trend analysis
        self._store_bdl_quality_metrics(game_date, details)

        # Determine alert level - this is INFO only since BDL is disabled
        # We want to track trends, not block anything
        if major_pct > 20:
            return (
                'INFO',
                f'BDL QUALITY POOR: {major_pct:.1f}% major discrepancies. Keep BDL disabled.',
                details
            )
        elif major_pct > 10:
            return (
                'INFO',
                f'BDL QUALITY FAIR: {major_pct:.1f}% major discrepancies. Keep monitoring.',
                details
            )
        elif major_pct > 5:
            return (
                'INFO',
                f'BDL QUALITY IMPROVING: {major_pct:.1f}% major discrepancies. Not yet safe to enable.',
                details
            )
        else:
            return (
                'INFO',
                f'BDL QUALITY GOOD: Only {major_pct:.1f}% major discrepancies. Consider re-enabling.',
                details
            )

    def _store_bdl_quality_metrics(self, game_date: date, metrics: Dict) -> None:
        """Store BDL quality metrics in BigQuery for trend analysis."""
        try:
            # Store summary in source_discrepancies table
            table_id = f"{self.project_id}.nba_orchestration.source_discrepancies"

            rows = [{
                'game_date': game_date.isoformat(),
                'player_lookup': '_SUMMARY_',  # Special marker for summary row
                'player_name': 'BDL Quality Summary',
                'backup_source': 'bdl',
                'severity': 'info',
                'discrepancies_json': json.dumps(metrics),
                'detected_at': datetime.utcnow().isoformat()
            }]

            errors = self.bq_client.insert_rows_json(table_id, rows)
            if errors:
                logger.warning(f"Failed to store BDL quality metrics: {errors}")
            else:
                logger.info(f"Stored BDL quality metrics for {game_date}")
        except Exception as e:
            logger.warning(f"Could not store BDL quality metrics: {e}")

    def check_shot_zone_quality(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check shot zone data quality for potential corruption or data source issues.

        Monitors:
        - Shot zone completeness (% with has_complete_shot_zones = TRUE)
        - Paint/three/mid-range rate distributions
        - Anomalies indicating data corruption

        Returns:
            (alert_level, message, details)
        """
        query = f"""
        WITH shot_zone_metrics AS (
            SELECT
                COUNT(*) as total_records,
                COUNTIF(has_complete_shot_zones = TRUE) as complete_records,
                ROUND(SAFE_DIVIDE(COUNTIF(has_complete_shot_zones = TRUE) * 100.0, COUNT(*)), 1) as pct_complete,

                -- Average rates for complete records only
                ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
                    THEN SAFE_DIVIDE(paint_attempts * 100.0,
                         paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_paint_rate,
                ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
                    THEN SAFE_DIVIDE(three_attempts_pbp * 100.0,
                         paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_three_rate,
                ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
                    THEN SAFE_DIVIDE(mid_range_attempts * 100.0,
                         paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_mid_rate,

                -- Anomaly detection (data corruption indicators)
                COUNTIF(has_complete_shot_zones = TRUE
                    AND SAFE_DIVIDE(paint_attempts * 100.0,
                         paint_attempts + mid_range_attempts + three_attempts_pbp) < 25) as low_paint_count,
                COUNTIF(has_complete_shot_zones = TRUE
                    AND SAFE_DIVIDE(three_attempts_pbp * 100.0,
                         paint_attempts + mid_range_attempts + three_attempts_pbp) > 55) as high_three_count
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
              AND minutes_played > 0
        )
        SELECT * FROM shot_zone_metrics
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        row = next(result, None)

        if not row or row.total_records == 0:
            return 'OK', 'No player game data yet', {}

        pct_complete = row.pct_complete if row.pct_complete is not None else 0
        avg_paint = row.avg_paint_rate if row.avg_paint_rate is not None else 0
        avg_three = row.avg_three_rate if row.avg_three_rate is not None else 0
        avg_mid = row.avg_mid_rate if row.avg_mid_rate is not None else 0

        details = {
            'total_records': row.total_records,
            'complete_records': row.complete_records,
            'pct_complete': pct_complete,
            'avg_paint_rate': avg_paint,
            'avg_three_rate': avg_three,
            'avg_mid_rate': avg_mid,
            'low_paint_anomalies': row.low_paint_count,
            'high_three_anomalies': row.high_three_count
        }

        # Store metrics for trend analysis
        self._store_shot_zone_quality_metrics(game_date, details)

        # Alert conditions (Session 53 thresholds)
        # CRITICAL: Data corruption detected
        if avg_paint < 25 or avg_three > 55:
            return (
                'CRITICAL',
                f'SHOT ZONE DATA CORRUPTION: Paint rate {avg_paint}% (expected 30-45%) or Three rate {avg_three}% (expected 20-50%). Code regression or mixed data sources detected.',
                details
            )
        # CRITICAL: Very low completeness
        elif pct_complete < 30:
            return (
                'CRITICAL',
                f'CRITICAL: Only {pct_complete}% shot zone completeness. BigDataBall PBP data missing or scraper failure.',
                details
            )
        # WARNING: Degraded completeness
        elif pct_complete < 50:
            return (
                'WARNING',
                f'WARNING: Shot zone completeness at {pct_complete}% (expected >85%). BDB coverage degraded.',
                details
            )
        # WARNING: Marginal completeness
        elif pct_complete < 75:
            return (
                'WARNING',
                f'LOW COMPLETENESS: Shot zone data at {pct_complete}%. Monitor BDB availability.',
                details
            )
        # OK: Good quality
        else:
            return 'OK', f'Shot zone quality good: {pct_complete}% complete, rates within expected ranges', details

    def _store_shot_zone_quality_metrics(self, game_date: date, metrics: Dict) -> None:
        """Store shot zone quality metrics in BigQuery for trend analysis."""
        try:
            # Store in dedicated shot_zone_quality_trend table
            table_id = f"{self.project_id}.nba_orchestration.shot_zone_quality_trend"

            rows = [{
                'game_date': game_date.isoformat(),
                'total_records': metrics['total_records'],
                'complete_records': metrics['complete_records'],
                'pct_complete': metrics['pct_complete'],
                'avg_paint_rate': metrics['avg_paint_rate'],
                'avg_three_rate': metrics['avg_three_rate'],
                'avg_mid_rate': metrics['avg_mid_rate'],
                'low_paint_anomalies': metrics['low_paint_anomalies'],
                'high_three_anomalies': metrics['high_three_anomalies'],
                'checked_at': datetime.utcnow().isoformat()
            }]

            errors = self.bq_client.insert_rows_json(table_id, rows)
            if errors:
                logger.warning(f"Failed to store shot zone quality metrics: {errors}")
            else:
                logger.info(f"Stored shot zone quality metrics for {game_date}")
        except Exception as e:
            logger.warning(f"Could not store shot zone quality metrics (table may not exist yet): {e}")

    def check_model_performance(self, game_date: date) -> Tuple[str, str, Dict]:
        """
        Check model performance using unified diagnostics system.

        Monitors:
        - Model vs Vegas accuracy
        - Hit rate trends
        - Model drift score
        - Root cause attribution

        Returns:
            (alert_level, message, details)

        Added: Session 57 (2026-01-31)
        """
        # Check if performance diagnostics module is available
        if not HAS_PERFORMANCE_DIAGNOSTICS:
            return 'INFO', 'Model performance diagnostics not available (shared module not deployed)', {}

        try:
            # Use yesterday's date for grading data (today's games not yet complete)
            analysis_date = game_date - timedelta(days=1)

            # Initialize diagnostics
            diagnostics = PerformanceDiagnostics(game_date=analysis_date)

            # Run full analysis
            results = diagnostics.run_full_analysis()

            # Extract key metrics
            alert = results.get('alert', {})
            level = alert.get('level', 'OK')
            message = alert.get('message', 'No diagnostics available')
            recommendations = alert.get('recommendations', [])

            # Extract details for response
            details = {
                'analysis_date': analysis_date.isoformat(),
                'root_cause': results.get('root_cause', 'UNKNOWN'),
                'root_cause_confidence': results.get('root_cause_confidence', 0.0),
                'contributing_factors': results.get('contributing_factors', []),
                'vegas_metrics': results.get('vegas', {}),
                'drift_metrics': results.get('drift', {}),
                'data_quality': results.get('quality', {}),
                'recommendations': recommendations
            }

            # Persist results for tracking
            try:
                diagnostics.persist_results()
            except Exception as e:
                logger.warning(f"Could not persist diagnostics results: {e}")

            return level, message, details

        except Exception as e:
            logger.error(f"Error running model performance diagnostics: {e}", exc_info=True)
            return 'ERROR', f'Model performance check failed: {str(e)}', {}


def send_slack_alert(level: str, check_name: str, message: str, details: Dict, game_date: date) -> bool:
    """Send alert to Slack webhook."""
    if level == 'OK':
        return True  # Don't send alerts for OK status

    webhook_url = SLACK_WEBHOOK_URL_ERROR if level == 'CRITICAL' else SLACK_WEBHOOK_URL_WARNING

    if not webhook_url:
        logger.warning(f"No Slack webhook configured for level: {level}")
        return False

    try:
        import requests

        emoji_map = {
            'CRITICAL': ':rotating_light:',
            'WARNING': ':warning:',
            'INFO': ':information_source:'
        }

        color_map = {
            'CRITICAL': '#FF0000',
            'WARNING': '#FFA500',
            'INFO': '#0000FF'
        }

        # Build details fields
        fields = []
        for key, value in details.items():
            fields.append({
                "type": "mrkdwn",
                "text": f"*{key.replace('_', ' ').title()}:*\n{value}"
            })

        payload = {
            "attachments": [{
                "color": color_map.get(level, '#808080'),
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji_map.get(level, ':bell:')} Data Quality Alert: {check_name}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Date:* {game_date}\n*Level:* {level}\n\n{message}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": fields[:10]  # Limit to 10 fields
                    }
                ]
            }]
        }

        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully: {check_name} ({level})")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
        return False


@functions_framework.http
def check_data_quality(request):
    """
    Main Cloud Function entry point.

    Checks all data quality metrics and sends alerts if issues detected.

    Query params:
        game_date: Optional date to check (default: today)
        dry_run: If 'true', don't send alerts, just return status
        checks: Comma-separated list of checks to run (default: all)

    Returns:
        JSON response with all check results.
    """
    try:
        # Parse request parameters
        game_date_str = request.args.get('game_date')
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'
        checks_filter = request.args.get('checks', 'all')

        if game_date_str:
            try:
                game_date = date.fromisoformat(game_date_str)
            except ValueError:
                return {'error': f'Invalid date format: {game_date_str}. Expected YYYY-MM-DD'}, 400
        else:
            game_date = date.today()

        logger.info(f"Checking data quality for {game_date} (dry_run={dry_run}, checks={checks_filter})")

        # Initialize monitor
        monitor = DataQualityMonitor(PROJECT_ID)

        # Run checks
        results = {}
        alerts_sent = []

        # Define checks
        all_checks = {
            'zero_predictions': monitor.check_zero_predictions,
            'usage_rate': monitor.check_usage_rate_coverage,
            'duplicates': monitor.check_duplicates,
            'prop_lines': monitor.check_prop_lines,
            'bdl_quality': monitor.check_bdl_quality,  # Added Session 41 - track BDL quality for potential re-enable
            'shot_zone_quality': monitor.check_shot_zone_quality,  # Added Session 54 - shot zone data quality monitoring
            'model_performance': monitor.check_model_performance  # Added Session 57 - daily model performance diagnostics
        }

        # Filter checks
        if checks_filter != 'all':
            checks_to_run = {k: v for k, v in all_checks.items() if k in checks_filter.split(',')}
        else:
            checks_to_run = all_checks

        # Run each check
        for check_name, check_func in checks_to_run.items():
            try:
                level, message, details = check_func(game_date)
                results[check_name] = {
                    'level': level,
                    'message': message,
                    'details': details
                }

                # Send alert if needed
                if level != 'OK' and not dry_run:
                    alert_sent = send_slack_alert(level, check_name, message, details, game_date)
                    if alert_sent:
                        alerts_sent.append(check_name)

            except Exception as e:
                logger.error(f"Error running check {check_name}: {e}", exc_info=True)
                results[check_name] = {
                    'level': 'ERROR',
                    'message': f'Check failed: {str(e)}',
                    'details': {}
                }

        # Build response
        critical_count = sum(1 for r in results.values() if r['level'] == 'CRITICAL')
        warning_count = sum(1 for r in results.values() if r['level'] == 'WARNING')

        response = {
            'game_date': game_date.isoformat(),
            'timestamp': datetime.utcnow().isoformat(),
            'overall_status': 'CRITICAL' if critical_count > 0 else 'WARNING' if warning_count > 0 else 'OK',
            'checks_run': len(results),
            'critical_issues': critical_count,
            'warnings': warning_count,
            'results': results,
            'alerts_sent': alerts_sent,
            'dry_run': dry_run
        }

        logger.info(f"Data quality check complete: {critical_count} critical, {warning_count} warnings")
        return response, 200

    except Exception as e:
        logger.exception(f"Error in data quality check: {e}")
        return {'error': str(e)}, 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return json.dumps({
        'status': 'healthy',
        'function': 'data_quality_alerts',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
