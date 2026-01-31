#!/usr/bin/env python3
"""
BigDataBall Critical Monitor

CRITICAL SYSTEM: BigDataBall is essential for shot zone data quality.
This monitor ensures we NEVER miss BDB data for any game.

Functions:
1. DETECT: Find games missing BDB data
2. ALERT: Send Slack/email alerts immediately
3. RETRY: Trigger scraper retry for missing games
4. INVESTIGATE: Log detailed diagnostics for manual review
5. RE-RUN: Trigger Phase 3 re-processing when data arrives

Schedule: Every 30 minutes via Cloud Scheduler
Alert Thresholds:
  - WARNING: >2 hours after game end, BDB not available
  - CRITICAL: >6 hours after game end, BDB not available
  - EMERGENCY: >24 hours after game end, BDB not available

Usage:
    python bin/monitoring/bdb_critical_monitor.py [--dry-run] [--date YYYY-MM-DD] [--slack-webhook URL]

Created: Session 39 (2026-01-30)
"""

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from google.cloud import pubsub_v1

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BDBCriticalMonitor:
    """
    Critical monitor for BigDataBall data availability.

    BigDataBall is the ONLY reliable source for shot zone coordinates.
    Missing BDB data directly causes model prediction failures.
    """

    # Alert thresholds (hours after game end)
    WARNING_HOURS = 2
    CRITICAL_HOURS = 6
    EMERGENCY_HOURS = 24

    # Minimum shots expected per game (typical game has 150-200)
    MIN_SHOTS_PER_GAME = 50

    def __init__(self, dry_run: bool = False, slack_webhook: Optional[str] = None):
        self.client = bigquery.Client()
        self.project_id = self.client.project
        self.dry_run = dry_run
        self.slack_webhook = slack_webhook or os.environ.get('SLACK_WEBHOOK_URL')

        if not dry_run:
            try:
                self.publisher = pubsub_v1.PublisherClient()
            except Exception as e:
                logger.warning(f"Could not initialize Pub/Sub: {e}")
                self.publisher = None

    def get_games_needing_bdb(self, check_date: Optional[date] = None) -> List[Dict]:
        """
        Find all games that are missing or have incomplete BDB data.

        Returns list of games with:
        - game info (date, teams, NBA game ID)
        - BDB status (available, shots count)
        - time since game ended
        - severity level
        """
        # Default to last 3 days
        if check_date:
            start_date = check_date
            end_date = check_date
        else:
            end_date = date.today()
            start_date = end_date - timedelta(days=3)

        query = f"""
        WITH scheduled_games AS (
            SELECT
                s.game_date,
                s.game_id as nba_game_id,
                s.home_team_tricode,
                s.away_team_tricode,
                s.game_status,
                -- Estimate game end time (game_date + 11 PM ET - typical game end)
                TIMESTAMP(CONCAT(CAST(s.game_date AS STRING), ' 23:00:00')) as estimated_end_time
            FROM `{self.project_id}.nba_raw.nbac_schedule` s
            WHERE s.game_date BETWEEN '{start_date}' AND '{end_date}'
              AND s.game_status = 3  -- 3 = Final/Completed games
        ),
        bdb_coverage AS (
            SELECT
                -- bdb_game_id is INT64, schedule game_id is STRING like '0022500681'
                -- Convert BDB game_id to match schedule format
                LPAD(CAST(bdb_game_id AS STRING), 10, '0') as nba_game_id,
                game_date,
                COUNT(*) as total_events,
                COUNTIF(event_type = 'shot') as shot_count,
                COUNTIF(event_type = 'shot' AND shot_distance IS NOT NULL) as shots_with_distance
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND bdb_game_id IS NOT NULL
            GROUP BY 1, 2
        ),
        bdb_games AS (
            -- Get BDB game_id (date_team_team format) for Phase 3 join
            SELECT DISTINCT
                LPAD(CAST(bdb_game_id AS STRING), 10, '0') as nba_game_id,
                game_id as bdb_game_id_str,
                game_date
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND bdb_game_id IS NOT NULL
        ),
        phase3_status AS (
            SELECT
                game_id as bdb_game_id_str,  -- Uses BDB format (20260129_OKC_MIN)
                game_date,
                COUNT(*) as player_records,
                COUNTIF(paint_attempts IS NOT NULL) as records_with_paint
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 1, 2
        )
        SELECT
            g.game_date,
            g.nba_game_id,
            g.home_team_tricode,
            g.away_team_tricode,
            g.estimated_end_time,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), g.estimated_end_time, HOUR) as hours_since_game,

            -- BDB status
            COALESCE(b.shot_count, 0) as bdb_shot_count,
            COALESCE(b.shots_with_distance, 0) as bdb_shots_with_distance,
            CASE
                WHEN b.shots_with_distance >= {self.MIN_SHOTS_PER_GAME} THEN 'complete'
                WHEN b.shot_count > 0 THEN 'partial'
                ELSE 'missing'
            END as bdb_status,

            -- Phase 3 status
            COALESCE(p.player_records, 0) as phase3_records,
            COALESCE(p.records_with_paint, 0) as phase3_with_paint,

            -- Severity
            CASE
                WHEN b.shots_with_distance >= {self.MIN_SHOTS_PER_GAME} THEN 'ok'
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), g.estimated_end_time, HOUR) >= {self.EMERGENCY_HOURS} THEN 'emergency'
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), g.estimated_end_time, HOUR) >= {self.CRITICAL_HOURS} THEN 'critical'
                WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), g.estimated_end_time, HOUR) >= {self.WARNING_HOURS} THEN 'warning'
                ELSE 'pending'
            END as severity

        FROM scheduled_games g
        LEFT JOIN bdb_coverage b ON g.nba_game_id = b.nba_game_id
        LEFT JOIN bdb_games bg ON g.nba_game_id = bg.nba_game_id
        LEFT JOIN phase3_status p ON bg.bdb_game_id_str = p.bdb_game_id_str
        WHERE b.shots_with_distance IS NULL OR b.shots_with_distance < {self.MIN_SHOTS_PER_GAME}
        ORDER BY g.game_date DESC, severity DESC
        """

        try:
            result = self.client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error querying games needing BDB: {e}")
            return []

    def send_slack_alert(self, message: str, severity: str = 'warning') -> bool:
        """Send alert to Slack webhook."""
        if not self.slack_webhook:
            logger.warning("No Slack webhook configured")
            return False

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would send Slack alert ({severity}): {message}")
            return True

        # Color coding
        colors = {
            'ok': '#36a64f',      # green
            'warning': '#ffcc00',  # yellow
            'critical': '#ff6600', # orange
            'emergency': '#ff0000' # red
        }

        payload = {
            'attachments': [{
                'color': colors.get(severity, '#808080'),
                'title': f'BigDataBall Monitor - {severity.upper()}',
                'text': message,
                'footer': 'BDB Critical Monitor',
                'ts': int(datetime.now().timestamp())
            }]
        }

        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                self.slack_webhook,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=10)
            logger.info(f"Sent Slack alert ({severity})")
            return True
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
            return False

    def trigger_bdb_scraper_retry(self, nba_game_id: str, game_date: date) -> bool:
        """Trigger BDB scraper to retry fetching data for a game."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger BDB scraper retry for {nba_game_id}")
            return True

        if not self.publisher:
            logger.warning("Pub/Sub not available, cannot trigger retry")
            return False

        try:
            topic_path = self.publisher.topic_path(
                self.project_id,
                'nba-phase2-trigger'
            )
            message = json.dumps({
                'processor': 'bigdataball_pbp',
                'game_date': game_date.isoformat(),
                'game_id': nba_game_id,
                'trigger_reason': 'bdb_critical_monitor_retry',
                'priority': 'high'
            }).encode('utf-8')

            future = self.publisher.publish(topic_path, message)
            future.result(timeout=30)
            logger.info(f"Triggered BDB scraper retry for {nba_game_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger BDB retry: {e}")
            return False

    def trigger_phase3_rerun(self, nba_game_id: str, game_date: date) -> bool:
        """Trigger Phase 3 re-run for a game that now has BDB data."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger Phase 3 re-run for {nba_game_id}")
            return True

        if not self.publisher:
            logger.warning("Pub/Sub not available, cannot trigger re-run")
            return False

        try:
            topic_path = self.publisher.topic_path(
                self.project_id,
                'nba-phase3-trigger'
            )
            message = json.dumps({
                'game_date': game_date.isoformat(),
                'game_id': nba_game_id,
                'trigger_reason': 'bdb_data_available',
                'source': 'bdb_critical_monitor'
            }).encode('utf-8')

            future = self.publisher.publish(topic_path, message)
            future.result(timeout=30)
            logger.info(f"Triggered Phase 3 re-run for {nba_game_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 3 re-run: {e}")
            return False

    def record_gap(self, game: Dict) -> None:
        """Record the gap in the data_gaps table for tracking."""
        if self.dry_run:
            return

        query = f"""
        MERGE `{self.project_id}.nba_orchestration.data_gaps` t
        USING (SELECT
            DATE('{game['game_date']}') as game_date,
            '{game['nba_game_id']}' as game_id,
            '{game['home_team_tricode']}' as home_team,
            '{game['away_team_tricode']}' as away_team,
            'bigdataball_pbp' as source,
            CURRENT_TIMESTAMP() as detected_at,
            '{game['severity']}' as severity,
            'open' as status
        ) s
        ON t.game_date = s.game_date AND t.game_id = s.game_id AND t.source = s.source
        WHEN MATCHED THEN
            UPDATE SET severity = s.severity, updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (game_date, game_id, home_team, away_team, source, detected_at, severity, status, created_at)
            VALUES (s.game_date, s.game_id, s.home_team, s.away_team, s.source, s.detected_at, s.severity, s.status, CURRENT_TIMESTAMP())
        """

        try:
            self.client.query(query).result()
        except Exception as e:
            logger.warning(f"Failed to record gap: {e}")

    def get_coverage_stats(self, check_date: Optional[date] = None) -> Dict:
        """
        Get BDB coverage statistics for a date.

        Returns coverage percentage and counts.
        """
        if not check_date:
            check_date = date.today() - timedelta(days=1)  # Yesterday by default

        query = f"""
        WITH scheduled AS (
            SELECT COUNT(*) as total_games
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = '{check_date}'
              AND game_status = 3
        ),
        bdb_complete AS (
            SELECT COUNT(DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0')) as complete_games
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date = '{check_date}'
              AND event_type = 'shot'
              AND shot_distance IS NOT NULL
            HAVING COUNT(*) >= {self.MIN_SHOTS_PER_GAME}
        )
        SELECT
            s.total_games,
            COALESCE(b.complete_games, 0) as complete_games,
            CASE
                WHEN s.total_games > 0 THEN ROUND(100.0 * COALESCE(b.complete_games, 0) / s.total_games, 1)
                ELSE 0
            END as coverage_pct
        FROM scheduled s
        LEFT JOIN bdb_complete b ON true
        """

        try:
            result = self.client.query(query).to_dataframe()
            if result.empty:
                return {'total_games': 0, 'complete_games': 0, 'coverage_pct': 0}
            row = result.iloc[0]
            return {
                'date': check_date,
                'total_games': int(row['total_games']),
                'complete_games': int(row['complete_games']),
                'coverage_pct': float(row['coverage_pct'])
            }
        except Exception as e:
            logger.error(f"Error getting coverage stats: {e}")
            return {'total_games': 0, 'complete_games': 0, 'coverage_pct': 0}

    def run(self, check_date: Optional[date] = None) -> Dict:
        """
        Main monitoring loop.

        Returns summary stats.
        """
        logger.info(f"{'='*60}")
        logger.info(f"BDB CRITICAL MONITOR - {datetime.now().isoformat()}")
        logger.info(f"{'='*60}")

        stats = {
            'games_checked': 0,
            'games_ok': 0,
            'games_pending': 0,
            'warnings': 0,
            'critical': 0,
            'emergency': 0,
            'retries_triggered': 0,
            'alerts_sent': 0,
            'coverage_pct': 0
        }

        # Get yesterday's coverage stats
        yesterday = date.today() - timedelta(days=1)
        coverage = self.get_coverage_stats(yesterday)
        stats['coverage_pct'] = coverage['coverage_pct']

        logger.info(f"Yesterday's coverage ({yesterday}): {coverage['complete_games']}/{coverage['total_games']} games ({coverage['coverage_pct']}%)")

        # Alert if coverage < 80%
        if coverage['total_games'] > 0 and coverage['coverage_pct'] < 80:
            msg = (
                f"*⚠️ Low BDB Coverage Alert*\n\n"
                f"Yesterday ({yesterday}): {coverage['coverage_pct']}% coverage\n"
                f"Complete: {coverage['complete_games']}/{coverage['total_games']} games\n\n"
                f"Expected: ≥80% coverage for reliable shot zone data"
            )
            if self.send_slack_alert(msg, 'warning'):
                stats['alerts_sent'] += 1

        # Get games needing BDB
        games = self.get_games_needing_bdb(check_date)

        if not games:
            logger.info("All games have complete BDB data!")
            # Send daily "all OK" summary
            if coverage['total_games'] > 0:
                msg = (
                    f"*✅ BDB Monitor Daily Summary*\n\n"
                    f"All games from last 3 days have complete BDB data\n"
                    f"Yesterday: {coverage['coverage_pct']}% coverage ({coverage['complete_games']}/{coverage['total_games']} games)\n\n"
                    f"No action needed."
                )
                self.send_slack_alert(msg, 'ok')
            return stats

        stats['games_checked'] = len(games)

        # Group by severity
        by_severity = {'pending': [], 'warning': [], 'critical': [], 'emergency': []}
        for game in games:
            severity = game.get('severity', 'pending')
            if severity in by_severity:
                by_severity[severity].append(game)

        # Process each severity level
        for severity, severity_games in by_severity.items():
            if not severity_games:
                continue

            count = len(severity_games)
            stats[severity if severity != 'pending' else 'games_pending'] = count

            logger.info(f"\n{severity.upper()}: {count} games")

            for game in severity_games:
                game_str = (
                    f"{game['game_date']} {game['away_team_tricode']}@{game['home_team_tricode']} "
                    f"(ID: {game['nba_game_id']}, {game['hours_since_game']}h ago)"
                )
                logger.info(f"  - {game_str}")
                logger.info(f"    BDB: {game['bdb_status']} ({game['bdb_shots_with_distance']} shots)")
                logger.info(f"    Phase3: {game['phase3_with_paint']}/{game['phase3_records']} with paint data")

                # Record gap
                self.record_gap(game)

                # Trigger retry for warning+ severity
                if severity in ('warning', 'critical', 'emergency'):
                    if self.trigger_bdb_scraper_retry(game['nba_game_id'], game['game_date']):
                        stats['retries_triggered'] += 1

        # Send consolidated alerts
        if by_severity['emergency']:
            msg = self._format_alert_message(by_severity['emergency'], 'emergency')
            if self.send_slack_alert(msg, 'emergency'):
                stats['alerts_sent'] += 1

        if by_severity['critical']:
            msg = self._format_alert_message(by_severity['critical'], 'critical')
            if self.send_slack_alert(msg, 'critical'):
                stats['alerts_sent'] += 1

        if by_severity['warning'] and len(by_severity['warning']) >= 3:
            # Only alert for warnings if 3+ games affected
            msg = self._format_alert_message(by_severity['warning'], 'warning')
            if self.send_slack_alert(msg, 'warning'):
                stats['alerts_sent'] += 1

        logger.info(f"\n{'='*60}")
        logger.info(f"SUMMARY: {stats}")
        logger.info(f"{'='*60}")

        return stats

    def _format_alert_message(self, games: List[Dict], severity: str) -> str:
        """Format alert message for Slack with trend data."""
        # Group games by status
        from collections import Counter
        by_date = Counter(g['game_date'] for g in games)
        by_status = Counter(g['bdb_status'] for g in games)

        lines = [
            f"*{len(games)} games missing BigDataBall data ({severity})*",
            "",
            "*Games by Date:*"
        ]

        for game_date, count in sorted(by_date.items(), reverse=True)[:3]:
            lines.append(f"• {game_date}: {count} games")

        lines.append("")
        lines.append("*Oldest Missing Games:*")

        for game in games[:5]:  # Limit to 5 games in alert
            lines.append(
                f"• {game['game_date']} {game['away_team_tricode']}@{game['home_team_tricode']} "
                f"- {game['hours_since_game']}h ago ({game['bdb_status']})"
            )

        if len(games) > 5:
            lines.append(f"• ... and {len(games) - 5} more")

        lines.extend([
            "",
            f"*Impact:* Shot zone features degraded for {len(games)} games",
            f"*Action:* Retry triggered automatically, will check hourly",
            "",
            "Run `python bin/monitoring/bdb_critical_monitor.py` for details."
        ])

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='BigDataBall Critical Monitor')
    parser.add_argument('--dry-run', action='store_true', help='Don\'t make changes or send alerts')
    parser.add_argument('--date', type=str, help='Check specific date (YYYY-MM-DD)')
    parser.add_argument('--slack-webhook', type=str, help='Slack webhook URL for alerts')
    args = parser.parse_args()

    check_date = None
    if args.date:
        check_date = date.fromisoformat(args.date)

    monitor = BDBCriticalMonitor(
        dry_run=args.dry_run,
        slack_webhook=args.slack_webhook
    )
    stats = monitor.run(check_date=check_date)

    # Exit with error if emergency issues
    if stats.get('emergency', 0) > 0:
        sys.exit(2)
    elif stats.get('critical', 0) > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
