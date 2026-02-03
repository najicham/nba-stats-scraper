#!/usr/bin/env python3
"""
BigDataBall Play-by-Play Data Monitor

Monitors BigDataBall PBP data availability and tracks gaps.
Triggers Phase 3 reprocessing when missing data becomes available.

Usage:
    # Check yesterday's games
    python bdb_pbp_monitor.py

    # Check specific date
    python bdb_pbp_monitor.py --date 2026-01-27

    # Dry run (no BigQuery updates, no alerts)
    python bdb_pbp_monitor.py --dry-run

Created: 2026-01-28
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from google.cloud import bigquery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')

# BDB Release Timing (Session 94):
# BigDataBall typically uploads play-by-play files 6+ hours AFTER games end.
# Games usually end around 10-11 PM PT, so files appear around 4-7 AM PT next day.
#
# Thresholds based on hours since game ended:
# - 0-6 hours: 'pending' - Files not expected yet, normal delay
# - 6-24 hours: 'warning' - Files should be available soon
# - 24+ hours: 'critical' - Something is wrong, investigate
WARNING_THRESHOLD_HOURS = 6   # Don't alert until 6+ hours after game ends
CRITICAL_THRESHOLD_HOURS = 24  # Only critical after 24+ hours


class BDBPBPMonitor:
    """Monitor BigDataBall Play-by-Play data availability.

    IMPORTANT: BDB releases files 6+ hours after games end. This is NORMAL behavior.
    - Games end: ~10-11 PM PT
    - Files uploaded: ~4-7 AM PT next day
    - Our scraper retries automatically until files appear

    When checking recent dates:
    - Before 6 AM PT: Missing data is EXPECTED (files not uploaded yet)
    - After 6 AM PT: Missing data should be investigated
    - After 24 hours: Missing data is CRITICAL
    """

    def __init__(self, project_id: str = PROJECT_ID, dry_run: bool = False):
        self.project_id = project_id
        self.dry_run = dry_run
        self.bq_client = bigquery.Client(project=project_id)
        self.stats = {
            'games_expected': 0,
            'games_with_pbp': 0,
            'gaps_detected': 0,
            'gaps_resolved': 0,
            'alerts_sent': 0
        }

    def check_date(self, game_date: date) -> Dict:
        """
        Check BDB PBP availability for a specific date.

        Returns dict with:
        - expected_games: List of games from schedule
        - available_games: List of games with BDB PBP data
        - missing_games: List of games without BDB PBP data
        - gaps: List of gap records for tracking
        """
        logger.info(f"Checking BDB PBP availability for {game_date}")

        # Get expected games from schedule
        expected_games = self._get_expected_games(game_date)
        self.stats['games_expected'] = len(expected_games)

        if not expected_games:
            logger.info(f"No games found for {game_date}")
            return {'expected_games': [], 'available_games': [], 'missing_games': [], 'gaps': []}

        # Get games with BDB PBP data
        available_games = self._get_bdb_available_games(game_date)
        self.stats['games_with_pbp'] = len(available_games)

        # Find missing games using matchup keys (away_home)
        def get_matchup_key(game):
            return f"{game.get('away_team_abbr', '')}_{game.get('home_team_abbr', '')}"

        expected_matchups = {get_matchup_key(g): g for g in expected_games}
        available_matchups = set(available_games)  # Now returns matchup keys like "MIL_PHI"

        missing_matchups = set(expected_matchups.keys()) - available_matchups
        missing_games = [expected_matchups[m] for m in missing_matchups if m in expected_matchups]

        # For gap tracking, we need a unique key - use matchup since game_ids differ
        for game in expected_games:
            game['matchup_key'] = get_matchup_key(game)

        # Get existing gaps from database (keyed by game_id)
        existing_gaps = self._get_existing_gaps(game_date)

        # Process gaps - use matchup_key for BDB availability check but game_id for storage
        gaps = []
        for game in expected_games:
            game_id = game['game_id']
            matchup_key = game.get('matchup_key', '')
            existing_gap = existing_gaps.get(game_id)

            is_missing = matchup_key not in available_matchups

            if is_missing:
                # Game is missing - create or update gap
                gap = self._create_gap_record(game, existing_gap)
                gaps.append(gap)
                self.stats['gaps_detected'] += 1
            elif existing_gap and existing_gap.get('status') == 'open':
                # Game now has data - resolve gap
                gap = self._resolve_gap_record(game, existing_gap)
                gaps.append(gap)
                self.stats['gaps_resolved'] += 1

        return {
            'expected_games': expected_games,
            'available_games': list(available_matchups),
            'missing_games': missing_games,
            'gaps': gaps
        }

    def _get_expected_games(self, game_date: date) -> List[Dict]:
        """Get expected games from schedule."""
        # game_status = 3 means Final in the schedule table
        query = f"""
        SELECT
            game_id,
            game_date,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_status
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = '{game_date.isoformat()}'
          AND game_status = 3
        """
        try:
            result = self.bq_client.query(query).result()
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Error querying schedule: {e}")
            return []

    def _get_bdb_available_games(self, game_date: date) -> List[str]:
        """Get matchup keys for games that have BDB PBP data.

        BDB uses game_id format: 20260127_MIL_PHI
        We convert to matchup key: MIL_PHI (away_home)
        """
        query = f"""
        SELECT DISTINCT game_id
        FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
        WHERE game_date = '{game_date.isoformat()}'
        """
        try:
            result = self.bq_client.query(query).result()
            matchup_keys = []
            for row in result:
                # BDB game_id format: 20260127_MIL_PHI (date_away_home)
                parts = row.game_id.split('_')
                if len(parts) == 3:
                    # Extract away_home matchup key
                    matchup_keys.append(f"{parts[1]}_{parts[2]}")
            return matchup_keys
        except Exception as e:
            logger.error(f"Error querying BDB PBP: {e}")
            return []

    def _get_existing_gaps(self, game_date: date) -> Dict[str, Dict]:
        """Get existing gap records for a date."""
        query = f"""
        SELECT *
        FROM `{self.project_id}.nba_orchestration.data_gaps`
        WHERE game_date = '{game_date.isoformat()}'
          AND source = 'bigdataball_pbp'
        """
        try:
            result = self.bq_client.query(query).result()
            return {row.game_id: dict(row) for row in result}
        except Exception as e:
            logger.warning(f"Error querying existing gaps: {e}")
            return {}

    def _create_gap_record(self, game: Dict, existing_gap: Optional[Dict]) -> Dict:
        """Create or update a gap record for a missing game."""
        now = datetime.now(timezone.utc)
        game_end = game.get('game_datetime')

        # Calculate hours since game ended
        if game_end:
            if isinstance(game_end, str):
                game_end = datetime.fromisoformat(game_end.replace('Z', '+00:00'))
            hours_since = (now - game_end).total_seconds() / 3600
        else:
            hours_since = 24  # Assume old if no end time

        # Determine severity
        if hours_since >= CRITICAL_THRESHOLD_HOURS:
            severity = 'critical'
        elif hours_since >= WARNING_THRESHOLD_HOURS:
            severity = 'warning'
        else:
            severity = 'pending'  # Still within expected window

        if existing_gap:
            # Update existing gap
            return {
                'game_date': game['game_date'],
                'game_id': game['game_id'],
                'home_team': game.get('home_team_abbr'),
                'away_team': game.get('away_team_abbr'),
                'source': 'bigdataball_pbp',
                'game_finished_at': game.get('game_datetime'),
                'expected_at': existing_gap.get('expected_at'),
                'detected_at': existing_gap.get('detected_at'),
                'resolved_at': None,
                'severity': severity,
                'status': 'open',
                'auto_retry_count': existing_gap.get('auto_retry_count', 0),
                'last_retry_at': existing_gap.get('last_retry_at'),
                'next_retry_at': None,
                'resolution_type': None,
                'resolution_notes': None,
                'updated_at': now.isoformat()
            }
        else:
            # Create new gap
            return {
                'game_date': game['game_date'],
                'game_id': game['game_id'],
                'home_team': game.get('home_team_abbr'),
                'away_team': game.get('away_team_abbr'),
                'source': 'bigdataball_pbp',
                'game_finished_at': game.get('game_datetime'),
                'expected_at': (now + timedelta(hours=6)).isoformat(),  # Expected within 6 hours
                'detected_at': now.isoformat(),
                'resolved_at': None,
                'severity': severity,
                'status': 'open',
                'auto_retry_count': 0,
                'last_retry_at': None,
                'next_retry_at': None,
                'resolution_type': None,
                'resolution_notes': None,
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }

    def _resolve_gap_record(self, game: Dict, existing_gap: Dict) -> Dict:
        """Mark a gap as resolved when data becomes available."""
        now = datetime.now(timezone.utc)

        gap = existing_gap.copy()
        gap['resolved_at'] = now.isoformat()
        gap['status'] = 'resolved'
        gap['resolution_type'] = 'auto_resolved'
        gap['resolution_notes'] = 'BDB PBP data became available'
        gap['updated_at'] = now.isoformat()

        return gap

    def save_gaps(self, gaps: List[Dict]) -> bool:
        """Save gap records to BigQuery."""
        if not gaps:
            return True

        if self.dry_run:
            logger.info(f"[DRY RUN] Would save {len(gaps)} gap records")
            return True

        try:
            table_id = f"{self.project_id}.nba_orchestration.data_gaps"

            # Use MERGE to upsert
            for gap in gaps:
                # Helper to format timestamp values for SQL
                def ts_val(val):
                    if val:
                        return f"TIMESTAMP('{val}')"
                    return "CAST(NULL AS TIMESTAMP)"

                def str_val(val):
                    if val:
                        return f"'{val}'"
                    return "CAST(NULL AS STRING)"

                merge_query = f"""
                MERGE `{table_id}` T
                USING (SELECT
                    DATE('{gap['game_date']}') as game_date,
                    '{gap['game_id']}' as game_id,
                    '{gap.get('home_team', '')}' as home_team,
                    '{gap.get('away_team', '')}' as away_team,
                    '{gap['source']}' as source,
                    {ts_val(gap.get('game_finished_at'))} as game_finished_at,
                    {ts_val(gap.get('expected_at'))} as expected_at,
                    TIMESTAMP('{gap['detected_at']}') as detected_at,
                    {ts_val(gap.get('resolved_at'))} as resolved_at,
                    '{gap['severity']}' as severity,
                    '{gap['status']}' as status,
                    {gap.get('auto_retry_count', 0)} as auto_retry_count,
                    {str_val(gap.get('resolution_type'))} as resolution_type,
                    {str_val(gap.get('resolution_notes'))} as resolution_notes,
                    CURRENT_TIMESTAMP() as updated_at
                ) S
                ON T.game_id = S.game_id AND T.source = S.source AND T.game_date = S.game_date
                WHEN MATCHED THEN
                    UPDATE SET
                        severity = S.severity,
                        status = S.status,
                        resolved_at = S.resolved_at,
                        auto_retry_count = S.auto_retry_count,
                        resolution_type = S.resolution_type,
                        resolution_notes = S.resolution_notes,
                        updated_at = S.updated_at
                WHEN NOT MATCHED THEN
                    INSERT (game_date, game_id, home_team, away_team, source, game_finished_at,
                            expected_at, detected_at, resolved_at, severity, status,
                            auto_retry_count, resolution_type, resolution_notes, created_at, updated_at)
                    VALUES (S.game_date, S.game_id, S.home_team, S.away_team, S.source, S.game_finished_at,
                            S.expected_at, S.detected_at, S.resolved_at, S.severity, S.status,
                            S.auto_retry_count, S.resolution_type, S.resolution_notes, CURRENT_TIMESTAMP(), S.updated_at)
                """
                self.bq_client.query(merge_query).result()

            logger.info(f"Saved {len(gaps)} gap records to BigQuery")
            return True
        except Exception as e:
            logger.error(f"Error saving gaps: {e}")
            return False

    def trigger_reprocessing(self, resolved_gaps: List[Dict]) -> bool:
        """Trigger Phase 3 reprocessing for games that now have PBP data."""
        if not resolved_gaps:
            return True

        if self.dry_run:
            logger.info(f"[DRY RUN] Would trigger reprocessing for {len(resolved_gaps)} games")
            return True

        # Group by date for efficiency
        dates_to_reprocess = set()
        for gap in resolved_gaps:
            if gap.get('status') == 'resolved':
                dates_to_reprocess.add(gap['game_date'])

        if not dates_to_reprocess:
            return True

        # Trigger Phase 3 analytics for each date
        for game_date in dates_to_reprocess:
            try:
                # Use the existing process-date-range endpoint
                url = "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range"
                payload = {
                    "start_date": str(game_date),
                    "end_date": str(game_date),
                    # Only run processors that need PBP data
                    "processors": ["ShotZoneAnalyticsProcessor"],
                    "backfill_mode": True
                }

                # Get auth token
                import google.auth.transport.requests
                import google.oauth2.id_token

                auth_req = google.auth.transport.requests.Request()
                token = google.oauth2.id_token.fetch_id_token(auth_req, url)

                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=30
                )

                if response.ok:
                    logger.info(f"Triggered reprocessing for {game_date}")
                else:
                    logger.warning(f"Failed to trigger reprocessing for {game_date}: {response.text}")

            except Exception as e:
                logger.error(f"Error triggering reprocessing for {game_date}: {e}")

        return True

    def send_alert(self, result: Dict) -> bool:
        """Send Slack alert for gaps."""
        missing_games = result.get('missing_games', [])
        if not missing_games:
            return True

        # Only alert for warnings and criticals
        gaps = [g for g in result.get('gaps', []) if g.get('severity') in ('warning', 'critical')]
        if not gaps:
            return True

        if self.dry_run:
            logger.info(f"[DRY RUN] Would send alert for {len(gaps)} gaps")
            return True

        webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
        if not webhook_url:
            logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
            return False

        # Build message
        critical_count = len([g for g in gaps if g.get('severity') == 'critical'])
        warning_count = len([g for g in gaps if g.get('severity') == 'warning'])

        emoji = ":rotating_light:" if critical_count > 0 else ":warning:"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} BigDataBall PBP Data Gap"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Date:* {result['gaps'][0]['game_date'] if gaps else 'Unknown'}\n"
                           f"*Missing Games:* {len(missing_games)}\n"
                           f"*Critical (>24h):* {critical_count}\n"
                           f"*Warning (>6h):* {warning_count}"
                }
            }
        ]

        # Add game details
        game_list = []
        for game in missing_games[:5]:  # Limit to 5 games
            gap = next((g for g in gaps if g['game_id'] == game['game_id']), None)
            severity_emoji = ":red_circle:" if gap and gap.get('severity') == 'critical' else ":large_yellow_circle:"
            game_list.append(f"{severity_emoji} {game.get('away_team_abbr', '?')} @ {game.get('home_team_abbr', '?')}")

        if game_list:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Missing Games:*\n" + "\n".join(game_list)}
            })

        try:
            response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
            if response.ok:
                logger.info("Sent Slack alert")
                self.stats['alerts_sent'] += 1
                return True
            else:
                logger.error(f"Failed to send alert: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending alert: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Monitor BigDataBall PBP data availability')
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD), default: yesterday')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no writes or alerts')
    parser.add_argument('--days', type=int, default=1, help='Number of days to check (default: 1)')
    args = parser.parse_args()

    # Determine date(s) to check
    if args.date:
        start_date = date.fromisoformat(args.date)
    else:
        start_date = date.today() - timedelta(days=1)

    dates_to_check = [start_date - timedelta(days=i) for i in range(args.days)]

    # Create monitor
    monitor = BDBPBPMonitor(dry_run=args.dry_run)

    all_results = []
    for check_date in dates_to_check:
        result = monitor.check_date(check_date)
        all_results.append(result)

        # Save gaps to BigQuery
        monitor.save_gaps(result.get('gaps', []))

        # Trigger reprocessing for resolved gaps
        resolved = [g for g in result.get('gaps', []) if g.get('status') == 'resolved']
        monitor.trigger_reprocessing(resolved)

        # Send alert if needed
        monitor.send_alert(result)

    # Print summary
    print(f"\n{'='*60}")
    print(f"BigDataBall PBP Monitor Summary")
    print(f"{'='*60}")
    for i, (check_date, result) in enumerate(zip(dates_to_check, all_results)):
        print(f"\n{check_date}:")
        print(f"  Expected games: {len(result.get('expected_games', []))}")
        print(f"  With PBP data:  {len(result.get('available_games', []))}")
        print(f"  Missing:        {len(result.get('missing_games', []))}")

        for game in result.get('missing_games', [])[:5]:
            gap = next((g for g in result.get('gaps', []) if g['game_id'] == game['game_id']), None)
            sev = f"[{gap.get('severity', '?').upper()}]" if gap else ""
            print(f"    - {game.get('away_team_abbr', '?')} @ {game.get('home_team_abbr', '?')} {sev}")

    print(f"\n{'='*60}")
    print(f"Stats: {json.dumps(monitor.stats, indent=2)}")

    # Exit with error if critical gaps found
    critical_gaps = sum(
        len([g for g in r.get('gaps', []) if g.get('severity') == 'critical'])
        for r in all_results
    )
    if critical_gaps > 0:
        sys.exit(1)

    return 0


if __name__ == '__main__':
    main()
