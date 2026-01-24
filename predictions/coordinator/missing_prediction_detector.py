#!/usr/bin/env python3
"""
Missing Prediction Detector

Detects which specific players are missing predictions and sends critical Slack alerts.
Runs after Phase 5 completes to validate prediction coverage.

Alert Level: CRITICAL for ANY missing player with betting lines

Author: Claude Code
Created: 2026-01-18
Session: 106
"""

import logging
import os
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery
import json

logger = logging.getLogger(__name__)


class MissingPredictionDetector:
    """Detects and alerts on missing predictions."""

    def __init__(self, project_id: str = None):
        """
        Initialize detector.

        Args:
            project_id: GCP project ID (defaults to env var)
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def detect_missing_predictions(self, game_date: date) -> Tuple[List[Dict], Dict]:
        """
        Detect which players are missing predictions.

        Compares:
        - Players in upcoming_player_game_context with betting lines
        - Players who actually received predictions

        Args:
            game_date: Date to check

        Returns:
            (missing_players_list, summary_stats)
        """
        try:
            # Query to find eligible players vs predicted players
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat()),
                ]
            )
            query = f"""
            WITH eligible_players AS (
                SELECT
                    player_lookup,
                    team_abbr,
                    opponent_team_abbr,
                    current_points_line,
                    avg_minutes_per_game_last_7,
                    player_status,
                    is_production_ready
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = @game_date
                    AND (
                        avg_minutes_per_game_last_7 >= 15
                        OR current_points_line IS NOT NULL
                    )
                    AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
                    AND is_production_ready = TRUE
            ),
            predicted_players AS (
                SELECT DISTINCT
                    player_lookup
                FROM `{self.project_id}.nba_predictions.player_prop_predictions`
                WHERE DATE(game_date) = @game_date
            ),
            missing AS (
                SELECT
                    e.player_lookup,
                    e.team_abbr,
                    e.opponent_team_abbr,
                    e.current_points_line,
                    e.avg_minutes_per_game_last_7,
                    e.player_status
                FROM eligible_players e
                LEFT JOIN predicted_players p
                    ON e.player_lookup = p.player_lookup
                WHERE p.player_lookup IS NULL
                    AND e.current_points_line IS NOT NULL  -- Has betting lines
                ORDER BY e.current_points_line DESC  -- High-value players first
            )
            SELECT * FROM missing
            """

            result = self.bq_client.query(query, job_config=job_config).result()
            missing_players = []

            for row in result:
                missing_players.append({
                    'player_lookup': row.player_lookup,
                    'team_abbr': row.team_abbr,
                    'opponent_team_abbr': row.opponent_team_abbr,
                    'current_points_line': float(row.current_points_line) if row.current_points_line else None,
                    'avg_minutes_per_game_last_7': float(row.avg_minutes_per_game_last_7) if row.avg_minutes_per_game_last_7 else None,
                    'player_status': row.player_status
                })

            # Calculate summary stats
            summary = self._calculate_summary_stats(game_date, missing_players)

            return missing_players, summary

        except Exception as e:
            logger.error(f"Error detecting missing predictions: {e}", exc_info=True)
            return [], {'error': str(e)}

    def _calculate_summary_stats(self, game_date: date, missing_players: List[Dict]) -> Dict:
        """Calculate summary statistics."""
        try:
            # Get total eligible and predicted counts
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat()),
                ]
            )
            query = f"""
            WITH eligible AS (
                SELECT COUNT(*) as count
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = @game_date
                    AND (
                        avg_minutes_per_game_last_7 >= 15
                        OR current_points_line IS NOT NULL
                    )
                    AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
                    AND is_production_ready = TRUE
            ),
            predicted AS (
                SELECT COUNT(DISTINCT player_lookup) as count
                FROM `{self.project_id}.nba_predictions.player_prop_predictions`
                WHERE DATE(game_date) = @game_date
            )
            SELECT
                e.count as eligible_count,
                p.count as predicted_count
            FROM eligible e, predicted p
            """

            result = self.bq_client.query(query, job_config=job_config).result()
            row = next(result, None)

            if row:
                eligible_count = row.eligible_count
                predicted_count = row.predicted_count
                coverage_pct = (predicted_count / eligible_count * 100) if eligible_count > 0 else 0
            else:
                eligible_count = 0
                predicted_count = 0
                coverage_pct = 0

            # Count high-value missing players (>= 20 PPG)
            high_value_missing = [p for p in missing_players if p.get('current_points_line', 0) >= 20]

            return {
                'game_date': game_date.isoformat(),
                'eligible_players': eligible_count,
                'predicted_players': predicted_count,
                'missing_players': len(missing_players),
                'high_value_missing': len(high_value_missing),
                'coverage_percent': round(coverage_pct, 2),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error calculating summary stats: {e}", exc_info=True)
            return {}

    def send_slack_alert(self, missing_players: List[Dict], summary: Dict) -> bool:
        """
        Send critical Slack alert for missing predictions.

        Args:
            missing_players: List of missing player dicts
            summary: Summary statistics

        Returns:
            True if alert sent successfully
        """
        if not missing_players:
            logger.info("No missing predictions - no alert needed")
            return True

        # Import slack utilities
        try:
            from shared.utils.slack_channels import send_to_slack
        except ImportError:
            logger.error("Cannot import slack_channels, skipping alert", exc_info=True)
            return False

        webhook_url = os.environ.get('SLACK_WEBHOOK_URL_ERROR')  # Critical alerts
        if not webhook_url:
            logger.warning("SLACK_WEBHOOK_URL_ERROR not set, cannot send alert")
            return False

        # Build alert message
        game_date = summary.get('game_date', 'Unknown')
        missing_count = summary.get('missing_players', 0)
        eligible = summary.get('eligible_players', 0)
        predicted = summary.get('predicted_players', 0)
        coverage = summary.get('coverage_percent', 0)
        high_value = summary.get('high_value_missing', 0)

        # Determine severity emoji
        if coverage >= 95:
            severity_emoji = "⚠️"  # Warning
        elif coverage >= 80:
            severity_emoji = "🚨"  # Alert
        else:
            severity_emoji = "🔥"  # Critical

        # Build player list (top 10 by line value)
        player_lines = []
        for player in sorted(missing_players, key=lambda p: p.get('current_points_line', 0), reverse=True)[:10]:
            name = player['player_lookup'].replace('_', ' ').title()
            line = player.get('current_points_line')
            team = player.get('team_abbr', '???')
            opp = player.get('opponent_team_abbr', '???')
            status = player.get('player_status') or 'Active'

            player_lines.append(f"• {name} ({team} vs {opp}): {line} pts - {status}")

        if len(missing_players) > 10:
            player_lines.append(f"• ...and {len(missing_players) - 10} more players")

        players_text = "\n".join(player_lines)

        # Build full message
        text = f"""{severity_emoji} *MISSING PREDICTIONS ALERT - {game_date}*

*Coverage: {predicted}/{eligible} players ({coverage}%)*

{missing_count} players with betting lines did NOT receive predictions:
{'' if high_value == 0 else f'🌟 *{high_value} high-value players* (≥20 PPG) missing' + chr(10)}
*Missing Players:*
{players_text}

*Investigation Needed:*
1. Check if Phase 3 (upcoming_player_game_context) ran before Phase 5
2. Verify betting lines data was available
3. Check coordinator logs for errors
4. Review data pipeline timing

*Dashboard:* Check BigQuery for details
*Logs:* Cloud Run → prediction-coordinator-prod"""

        # Send to Slack
        try:
            success = send_to_slack(
                webhook_url=webhook_url,
                text=text,
                username="Prediction Monitor",
                icon_emoji=":rotating_light:"
            )

            if success:
                logger.info(f"Sent missing prediction alert to Slack ({missing_count} missing)")
            else:
                logger.error("Failed to send Slack alert", exc_info=True)

            return success

        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}", exc_info=True)
            return False

    def check_and_alert(self, game_date: date) -> Dict:
        """
        Main entry point: Detect missing predictions and send alert if needed.

        Args:
            game_date: Date to check

        Returns:
            Dict with detection results and alert status
        """
        logger.info(f"Checking for missing predictions on {game_date}")

        # Detect missing players
        missing_players, summary = self.detect_missing_predictions(game_date)

        # Send alert if any missing
        alert_sent = False
        if missing_players:
            logger.warning(f"Found {len(missing_players)} missing predictions for {game_date}")
            alert_sent = self.send_slack_alert(missing_players, summary)
        else:
            logger.info(f"All eligible players received predictions for {game_date}")

        return {
            'game_date': game_date.isoformat(),
            'missing_count': len(missing_players),
            'missing_players': missing_players,
            'summary': summary,
            'alert_sent': alert_sent,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }


def get_missing_prediction_detector() -> MissingPredictionDetector:
    """Get singleton detector instance."""
    global _detector_instance
    if '_detector_instance' not in globals():
        _detector_instance = MissingPredictionDetector()
    return _detector_instance
