"""
Subset Picks Daily Notifier

Sends daily subset picks via Slack and Email.
Queries the dynamic subset system and formats picks for consumption.

Usage:
    from shared.notifications.subset_picks_notifier import SubsetPicksNotifier

    notifier = SubsetPicksNotifier()
    notifier.send_daily_notifications(subset_id='v9_high_edge_top5')

Session: 83 (2026-02-02)
"""

import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

from shared.utils.slack_channels import send_to_slack
from shared.utils.email_alerting import EmailAlerter
from shared.utils.sms_notifier import SMSNotifier

logger = logging.getLogger(__name__)


class SubsetPicksNotifier:
    """Send daily subset picks via Slack and Email."""

    def __init__(self, project_id: str = None):
        """Initialize notifier with BigQuery client."""
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.client = bigquery.Client(project=self.project_id)

        # Initialize email alerter (optional - may not be configured in test environments)
        try:
            self.email_alerter = EmailAlerter()
        except ValueError as e:
            logger.warning(f"Email alerter not configured: {e}")
            self.email_alerter = None

        # Initialize SMS notifier (optional)
        self.sms_notifier = SMSNotifier()
        if not self.sms_notifier.is_configured():
            logger.debug("SMS notifier not configured (optional)")

        # Slack webhook for betting signals
        self.slack_webhook = os.environ.get('SLACK_WEBHOOK_URL_SIGNALS')

    def send_daily_notifications(
        self,
        subset_id: str = 'v9_high_edge_top5',
        game_date: Optional[str] = None,
        send_slack: bool = True,
        send_email: bool = True,
        send_sms: bool = True
    ) -> Dict[str, bool]:
        """
        Send daily subset picks via Slack, Email, and SMS.

        Args:
            subset_id: Subset to query (default: v9_high_edge_top5)
            game_date: Game date (YYYY-MM-DD) or None for today
            send_slack: Whether to send Slack notification
            send_email: Whether to send Email notification
            send_sms: Whether to send SMS notification

        Returns:
            Dict with success status: {'slack': bool, 'email': bool, 'sms': bool}
        """
        if game_date is None:
            game_date = date.today().isoformat()

        logger.info(f"Fetching subset picks for {subset_id} on {game_date}")

        # Query picks and signal data
        picks_data = self._query_subset_picks(subset_id, game_date)

        if not picks_data:
            logger.warning(f"No picks data found for {subset_id} on {game_date}")
            return {'slack': False, 'email': False, 'sms': False}

        results = {}

        # Send Slack notification
        if send_slack and self.slack_webhook:
            results['slack'] = self._send_slack_notification(picks_data, subset_id)
        else:
            results['slack'] = False
            if send_slack and not self.slack_webhook:
                logger.warning("SLACK_WEBHOOK_URL_SIGNALS not configured, skipping Slack")

        # Send Email notification
        if send_email:
            if self.email_alerter:
                results['email'] = self._send_email_notification(picks_data, subset_id)
            else:
                logger.warning("Email alerter not configured, skipping email")
                results['email'] = False
        else:
            results['email'] = False

        # Send SMS notification
        if send_sms:
            if self.sms_notifier.is_configured():
                results['sms'] = self._send_sms_notification(picks_data, subset_id)
            else:
                logger.debug("SMS notifier not configured, skipping SMS")
                results['sms'] = False
        else:
            results['sms'] = False

        return results

    def _query_subset_picks(self, subset_id: str, game_date: str) -> Optional[Dict]:
        """Query today's subset picks from BigQuery."""

        query = f"""
        WITH daily_signal AS (
          SELECT * FROM `{self.project_id}.nba_predictions.daily_prediction_signals`
          WHERE game_date = DATE('{game_date}') AND system_id = 'catboost_v9'
        ),
        subset_def AS (
          SELECT * FROM `{self.project_id}.nba_predictions.dynamic_subset_definitions`
          WHERE subset_id = '{subset_id}'
        ),
        ranked_picks AS (
          SELECT
            p.player_lookup,
            ROUND(p.predicted_points, 1) as predicted,
            p.current_points_line as line,
            ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
            p.recommendation,
            ROUND(p.confidence_score, 2) as confidence,
            ROUND((ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5), 1) as composite_score,
            ROW_NUMBER() OVER (
              ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
            ) as pick_rank
          FROM `{self.project_id}.nba_predictions.player_prop_predictions` p
          CROSS JOIN subset_def d
          WHERE p.game_date = DATE('{game_date}')
            AND p.system_id = d.system_id
            AND p.is_active = TRUE
            AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
            AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
            AND p.current_points_line IS NOT NULL
        ),
        historical_performance AS (
          SELECT
            COUNT(*) as total_picks,
            COUNTIF(
              actual_points IS NOT NULL
              AND actual_points != current_points_line
            ) as graded_picks,
            COUNTIF(
              actual_points IS NOT NULL
              AND actual_points != current_points_line
              AND (
                (actual_points > current_points_line AND recommendation = 'OVER') OR
                (actual_points < current_points_line AND recommendation = 'UNDER')
              )
            ) as wins,
            ROUND(100.0 * COUNTIF(
              actual_points IS NOT NULL
              AND actual_points != current_points_line
              AND (
                (actual_points > current_points_line AND recommendation = 'OVER') OR
                (actual_points < current_points_line AND recommendation = 'UNDER')
              )
            ) / NULLIF(COUNTIF(actual_points IS NOT NULL AND actual_points != current_points_line), 0), 1) as hit_rate,
            COUNT(DISTINCT game_date) as days
          FROM (
            SELECT
              p.game_date,
              p.player_lookup,
              p.predicted_points,
              p.current_points_line,
              p.recommendation,
              p.confidence_score,
              (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
              ROW_NUMBER() OVER (
                PARTITION BY p.game_date
                ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
              ) as daily_rank,
              pgs.points as actual_points
            FROM `{self.project_id}.nba_predictions.player_prop_predictions` p
            JOIN `{self.project_id}.nba_analytics.player_game_summary` pgs
              ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
            CROSS JOIN subset_def d
            WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 23 DAY)
              AND p.game_date < CURRENT_DATE()
              AND p.system_id = d.system_id
              AND p.is_active = TRUE
              AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
              AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
              AND p.current_points_line IS NOT NULL
          )
          CROSS JOIN subset_def d
          WHERE daily_rank <= COALESCE(d.top_n, 999)
        )
        SELECT
          -- Subset info
          d.subset_id,
          d.subset_name,
          d.top_n,

          -- Signal info
          s.pct_over,
          s.daily_signal,
          s.total_picks as total_predictions,
          s.high_edge_picks,

          -- Historical performance
          h.total_picks as historical_picks,
          h.graded_picks,
          h.wins,
          h.hit_rate,
          h.days,

          -- Today's picks (as array)
          ARRAY_AGG(
            STRUCT(
              r.pick_rank,
              r.player_lookup,
              r.predicted,
              r.line,
              r.edge,
              r.recommendation,
              r.confidence,
              r.composite_score
            )
            ORDER BY r.pick_rank
          ) as picks
        FROM ranked_picks r
        CROSS JOIN daily_signal s
        CROSS JOIN subset_def d
        CROSS JOIN historical_performance h
        WHERE r.pick_rank <= COALESCE(d.top_n, 999)
        GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12
        """

        try:
            query_job = self.client.query(query)
            results = list(query_job.result())

            if not results:
                logger.warning(f"No picks found for {subset_id} on {game_date}")
                return None

            row = results[0]

            # Convert to dict
            picks_data = {
                'game_date': game_date,
                'subset_id': row.subset_id,
                'subset_name': row.subset_name,
                'top_n': row.top_n,
                'pct_over': row.pct_over,
                'daily_signal': row.daily_signal,
                'total_predictions': row.total_predictions,
                'high_edge_picks': row.high_edge_picks,
                'historical_picks': row.historical_picks,
                'graded_picks': row.graded_picks,
                'wins': row.wins,
                'hit_rate': row.hit_rate,
                'days': row.days,
                'picks': []
            }

            # Convert picks array
            for pick in row.picks:
                # Handle both dict and object-style access
                if isinstance(pick, dict):
                    picks_data['picks'].append({
                        'rank': pick['pick_rank'],
                        'player': pick['player_lookup'],
                        'predicted': pick['predicted'],
                        'line': pick['line'],
                        'edge': pick['edge'],
                        'recommendation': pick['recommendation'],
                        'confidence': pick['confidence'],
                        'composite_score': pick['composite_score']
                    })
                else:
                    picks_data['picks'].append({
                        'rank': pick.pick_rank,
                        'player': pick.player_lookup,
                        'predicted': pick.predicted,
                        'line': pick.line,
                        'edge': pick.edge,
                        'recommendation': pick.recommendation,
                        'confidence': pick.confidence,
                        'composite_score': pick.composite_score
                    })

            logger.info(f"Found {len(picks_data['picks'])} picks for {subset_id}")
            return picks_data

        except Exception as e:
            logger.error(f"Error querying subset picks: {e}", exc_info=True)
            return None

    def _send_slack_notification(self, picks_data: Dict, subset_id: str) -> bool:
        """Send Slack notification with picks."""

        game_date = picks_data['game_date']
        signal = picks_data['daily_signal']
        pct_over = picks_data['pct_over']
        hit_rate = picks_data.get('hit_rate', 0)
        days = picks_data.get('days', 0)
        picks = picks_data['picks'][:5]  # Top 5

        # Signal emoji and warning
        if signal == 'RED':
            signal_emoji = ':red_circle:'
            signal_text = f"{signal_emoji} **RED SIGNAL** ({pct_over}% OVER)\n⚠️ *Reduce bet sizing or skip today*"
        elif signal == 'YELLOW':
            signal_emoji = ':large_yellow_circle:'
            signal_text = f"{signal_emoji} **YELLOW SIGNAL** ({pct_over}% OVER)\n⚠️ *Proceed with caution*"
        else:  # GREEN
            signal_emoji = ':large_green_circle:'
            signal_text = f"{signal_emoji} **GREEN SIGNAL** ({pct_over}% OVER)\n✅ *Normal confidence - bet as usual*"

        # Format picks
        picks_text = ""
        for pick in picks:
            player = pick['player'].replace('_', ' ').title()
            picks_text += f"{pick['rank']}. **{player}** - {pick['recommendation']} {pick['line']} pts\n"
            picks_text += f"   _Edge: {pick['edge']} | Conf: {pick['confidence']}%_\n"

        # Build message
        text = f"""🏀 *Today's Top Picks - {game_date}*

{signal_text}

*{picks_data['subset_name']}:*
{picks_text}
*Historical Performance:*
• {hit_rate}% hit rate ({picks_data['wins']}/{picks_data['graded_picks']} wins)
• Last {days} days | {picks_data['historical_picks']} total picks

_View all subsets: /subset-picks_"""

        try:
            success = send_to_slack(
                self.slack_webhook,
                text,
                username="NBA Props Bot",
                icon_emoji=":basketball:"
            )

            if success:
                logger.info(f"Sent Slack notification for {subset_id}")
            else:
                logger.error(f"Failed to send Slack notification for {subset_id}")

            return success

        except Exception as e:
            logger.error(f"Error sending Slack notification: {e}", exc_info=True)
            return False

    def _send_email_notification(self, picks_data: Dict, subset_id: str) -> bool:
        """Send email notification with picks."""

        game_date = picks_data['game_date']
        signal = picks_data['daily_signal']
        pct_over = picks_data['pct_over']
        hit_rate = picks_data.get('hit_rate', 0)
        days = picks_data.get('days', 0)
        picks = picks_data['picks'][:10]  # Top 10 for email

        # Signal styling
        if signal == 'RED':
            signal_color = '#f44336'
            signal_emoji = '🔴'
            signal_warning = """
            <div style="background-color: #fff3e0; border-left: 4px solid #ff9800; padding: 12px; margin: 16px 0;">
                <strong>⚠️ RED Signal Day</strong><br>
                Historical RED days show 62.5% hit rate vs 79.6% on GREEN days.<br>
                <strong>Recommendation:</strong> Reduce bet sizing or skip today.
            </div>
            """
        elif signal == 'YELLOW':
            signal_color = '#ff9800'
            signal_emoji = '🟡'
            signal_warning = """
            <div style="background-color: #fff9e6; border-left: 4px solid #ffc107; padding: 12px; margin: 16px 0;">
                <strong>⚠️ YELLOW Signal Day</strong><br>
                Unusual market conditions detected.<br>
                <strong>Recommendation:</strong> Proceed with caution.
            </div>
            """
        else:  # GREEN
            signal_color = '#4caf50'
            signal_emoji = '🟢'
            signal_warning = """
            <div style="background-color: #e8f5e9; border-left: 4px solid #4caf50; padding: 12px; margin: 16px 0;">
                <strong>✅ GREEN Signal Day</strong><br>
                Historical GREEN days show 79.6% hit rate.<br>
                <strong>Recommendation:</strong> Normal confidence - bet as usual.
            </div>
            """

        # Format picks table
        picks_rows = ""
        for pick in picks:
            player = pick['player'].replace('_', ' ').title()
            rec_color = '#4caf50' if pick['recommendation'] == 'OVER' else '#2196f3'
            picks_rows += f"""
            <tr>
                <td style="padding: 8px; text-align: center;">{pick['rank']}</td>
                <td style="padding: 8px;"><strong>{player}</strong></td>
                <td style="padding: 8px; text-align: center;">{pick['line']}</td>
                <td style="padding: 8px; text-align: center;">{pick['predicted']}</td>
                <td style="padding: 8px; text-align: center; color: {rec_color};">
                    <strong>{pick['recommendation']}</strong>
                </td>
                <td style="padding: 8px; text-align: center;">{pick['edge']}</td>
                <td style="padding: 8px; text-align: center;">{pick['confidence']}%</td>
            </tr>
            """

        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
                th {{ background-color: #f5f5f5; padding: 12px 8px; text-align: left; font-weight: bold; border-bottom: 2px solid #ddd; }}
                td {{ border-bottom: 1px solid #eee; }}
                .stats {{ background-color: #f9f9f9; padding: 16px; border-radius: 4px; margin: 16px 0; }}
            </style>
        </head>
        <body>
            <h2 style="color: #1976d2;">🏀 NBA Props - {game_date}</h2>

            <h3 style="color: {signal_color};">{signal_emoji} {signal} Signal ({pct_over}% OVER)</h3>
            {signal_warning}

            <h3>{picks_data['subset_name']}</h3>

            <table>
                <thead>
                    <tr>
                        <th style="text-align: center;">Rank</th>
                        <th>Player</th>
                        <th style="text-align: center;">Line</th>
                        <th style="text-align: center;">Pred</th>
                        <th style="text-align: center;">Dir</th>
                        <th style="text-align: center;">Edge</th>
                        <th style="text-align: center;">Conf</th>
                    </tr>
                </thead>
                <tbody>
                    {picks_rows}
                </tbody>
            </table>

            <div class="stats">
                <h4 style="margin-top: 0;">Historical Performance (Last {days} Days)</h4>
                <p>
                    <strong>Hit Rate:</strong> {hit_rate}% ({picks_data['wins']}/{picks_data['graded_picks']} wins)<br>
                    <strong>Total Picks:</strong> {picks_data['historical_picks']}<br>
                    <strong>Sample Size:</strong> {days} game days
                </p>
            </div>

            <hr style="margin: 24px 0; border: none; border-top: 1px solid #ddd;">

            <p style="color: #666; font-size: 12px;">
                This is an automated daily picks digest from the NBA Props Platform.<br>
                Use <code>/subset-picks</code> to view all subsets and historical performance.
            </p>
        </body>
        </html>
        """

        try:
            subject = f"NBA Props - {game_date} - {signal_emoji} {signal} Signal"

            # Use EmailAlerter to send
            recipients = self.email_alerter.alert_recipients
            if not recipients:
                logger.warning("No email recipients configured (EMAIL_ALERTS_TO)")
                return False

            success = self.email_alerter._send_email(
                subject=subject,
                body_html=html_body,
                recipients=recipients,
                alert_level="PICKS"
            )

            if success:
                logger.info(f"Sent email notification for {subset_id} to {len(recipients)} recipients")
            else:
                logger.error(f"Failed to send email notification for {subset_id}")

            return success

        except Exception as e:
            logger.error(f"Error sending email notification: {e}", exc_info=True)
            return False

    def _send_sms_notification(self, picks_data: Dict, subset_id: str) -> bool:
        """Send SMS notification with picks."""
        try:
            success = self.sms_notifier.send_picks_sms(
                picks_data,
                max_picks=3,  # SMS length limit
                include_historical=True
            )

            if success:
                logger.info(f"Sent SMS notification for {subset_id}")
            else:
                logger.error(f"Failed to send SMS notification for {subset_id}")

            return success

        except Exception as e:
            logger.error(f"Error sending SMS notification: {e}", exc_info=True)
            return False


def send_daily_picks(
    subset_id: str = 'v9_high_edge_top5',
    game_date: Optional[str] = None,
    send_sms: bool = True
) -> Dict[str, bool]:
    """
    Convenience function to send daily picks.

    Args:
        subset_id: Subset to send (default: v9_high_edge_top5)
        game_date: Game date or None for today
        send_sms: Whether to send SMS (default: True)

    Returns:
        Dict with success status: {'slack': bool, 'email': bool, 'sms': bool}
    """
    notifier = SubsetPicksNotifier()
    return notifier.send_daily_notifications(
        subset_id=subset_id,
        game_date=game_date,
        send_sms=send_sms
    )


if __name__ == '__main__':
    # Test/manual execution
    import sys

    subset = sys.argv[1] if len(sys.argv) > 1 else 'v9_high_edge_top5'
    game_date = sys.argv[2] if len(sys.argv) > 2 else None

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info(f"Sending daily picks for {subset}")
    results = send_daily_picks(subset_id=subset, game_date=game_date)

    logger.info(f"Results: Slack={results['slack']}, Email={results['email']}")
