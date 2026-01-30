#!/usr/bin/env python3
"""
BigDataBall Pending Games Monitor

Monitors games that were processed without BigDataBall data and triggers
re-processing when BDB data becomes available.

Business Rules:
1. Track all games processed with NBAC fallback or no shot zone data
2. Check periodically if BigDataBall data is now available
3. Trigger Phase 3 re-run when BDB available
4. BUT: Don't re-run if prediction already exists for game day (too close to game)
5. Track all changes for audit trail

Usage:
    python bin/monitoring/bdb_pending_monitor.py [--dry-run] [--date YYYY-MM-DD]

Schedule: Run every 2 hours via Cloud Scheduler

Created: Session 39 (2026-01-30)
"""

import argparse
import logging
import os
import sys
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from google.cloud import pubsub_v1

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BDBPendingMonitor:
    """Monitor and resolve pending BigDataBall games."""

    def __init__(self, dry_run: bool = False):
        self.client = bigquery.Client()
        self.project_id = self.client.project
        self.dry_run = dry_run

        # Pub/Sub for triggering re-processing
        if not dry_run:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(
                self.project_id,
                'nba-phase3-trigger'  # Topic that triggers Phase 3 analytics
            )

    def check_pending_games(self, check_date: Optional[date] = None) -> List[Dict]:
        """
        Find games that are pending BDB data.

        Args:
            check_date: Specific date to check, or None for all pending

        Returns:
            List of pending game records
        """
        date_filter = f"AND game_date = '{check_date}'" if check_date else ""

        query = f"""
        SELECT
            game_date,
            game_id,
            nba_game_id,
            home_team,
            away_team,
            fallback_source,
            original_processed_at,
            prediction_exists,
            prediction_made_at,
            game_start_time,
            bdb_check_count,
            last_bdb_check_at
        FROM `{self.project_id}.nba_orchestration.pending_bdb_games`
        WHERE status = 'pending_bdb'
          {date_filter}
        ORDER BY game_date DESC
        """

        try:
            result = self.client.query(query).to_dataframe()
            return result.to_dict('records')
        except Exception as e:
            logger.error(f"Error querying pending games: {e}")
            return []

    def check_bdb_availability(self, game_ids: List[str], game_date: date) -> Dict[str, bool]:
        """
        Check if BigDataBall data is now available for given games.

        Args:
            game_ids: List of game IDs to check
            game_date: Date of the games

        Returns:
            Dict mapping game_id -> bool (True if BDB data available)
        """
        if not game_ids:
            return {}

        # Build game_id list for SQL
        game_ids_sql = ", ".join([f"'{gid}'" for gid in game_ids])

        query = f"""
        SELECT
            game_id,
            COUNT(*) as shot_count,
            COUNTIF(shot_distance IS NOT NULL) as shots_with_distance
        FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
        WHERE game_date = '{game_date}'
          AND game_id IN ({game_ids_sql})
          AND event_type = 'shot'
        GROUP BY game_id
        """

        try:
            result = self.client.query(query).to_dataframe()

            availability = {}
            for _, row in result.iterrows():
                # BDB is available if we have shots with distance data
                # Require at least 50 shots (typical game has 150-200)
                has_data = row['shot_count'] >= 50 and row['shots_with_distance'] >= 50
                availability[row['game_id']] = has_data

            # Games not in result have no BDB data
            for game_id in game_ids:
                if game_id not in availability:
                    availability[game_id] = False

            return availability
        except Exception as e:
            logger.error(f"Error checking BDB availability: {e}")
            return {gid: False for gid in game_ids}

    def check_prediction_exists(self, game_date: date) -> bool:
        """
        Check if predictions already exist for a game date.

        If predictions exist, we should NOT re-run Phase 3 as it could
        change predictions close to game time.

        Args:
            game_date: Date to check

        Returns:
            True if predictions exist for this date
        """
        query = f"""
        SELECT COUNT(*) as count
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{game_date}'
        """

        try:
            result = list(self.client.query(query).result())[0]
            return result.count > 0
        except Exception as e:
            logger.warning(f"Error checking predictions: {e}")
            return True  # Assume predictions exist (safe default)

    def trigger_phase3_rerun(self, game_date: date, game_id: str) -> bool:
        """
        Trigger Phase 3 re-processing for a specific game.

        Args:
            game_date: Date of the game
            game_id: Game ID to reprocess

        Returns:
            True if trigger was successful
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger Phase 3 re-run for {game_date} / {game_id}")
            return True

        try:
            import json
            message = json.dumps({
                'game_date': game_date.isoformat(),
                'game_id': game_id,
                'trigger_reason': 'bdb_data_available',
                'triggered_by': 'bdb_pending_monitor'
            }).encode('utf-8')

            future = self.publisher.publish(self.topic_path, message)
            future.result(timeout=30)
            logger.info(f"Triggered Phase 3 re-run for {game_date} / {game_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 3 re-run: {e}")
            return False

    def update_pending_status(
        self,
        game_id: str,
        game_date: date,
        status: str,
        resolution_type: Optional[str] = None,
        resolution_notes: Optional[str] = None,
        bdb_detected: bool = False
    ) -> None:
        """Update the status of a pending BDB game."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would update {game_id} to status={status}")
            return

        updates = [
            f"status = '{status}'",
            f"updated_at = CURRENT_TIMESTAMP()",
            f"bdb_check_count = bdb_check_count + 1",
            f"last_bdb_check_at = CURRENT_TIMESTAMP()"
        ]

        if bdb_detected:
            updates.append("bdb_detected_at = CURRENT_TIMESTAMP()")

        if resolution_type:
            updates.append(f"resolution_type = '{resolution_type}'")

        if resolution_notes:
            updates.append(f"resolution_notes = '{resolution_notes}'")

        if status == 'reran':
            updates.append("bdb_rerun_at = CURRENT_TIMESTAMP()")
            updates.append("quality_after_rerun = 'gold'")
            updates.append("shot_zones_complete_after = TRUE")

        query = f"""
        UPDATE `{self.project_id}.nba_orchestration.pending_bdb_games`
        SET {', '.join(updates)}
        WHERE game_id = '{game_id}' AND game_date = '{game_date}'
        """

        try:
            self.client.query(query).result()
            logger.debug(f"Updated {game_id} to status={status}")
        except Exception as e:
            logger.error(f"Failed to update status for {game_id}: {e}")

    def send_alert(self, message: str, severity: str = 'warning') -> None:
        """Send alert to Slack/notification system."""
        # TODO: Implement Slack webhook integration
        if severity == 'critical':
            logger.error(f"ALERT: {message}")
        else:
            logger.warning(f"ALERT: {message}")

    def run(self, check_date: Optional[date] = None) -> Dict:
        """
        Main monitoring loop.

        Args:
            check_date: Optional specific date to check

        Returns:
            Summary dict with counts
        """
        logger.info(f"Starting BDB pending monitor (dry_run={self.dry_run})")

        stats = {
            'pending_checked': 0,
            'bdb_available': 0,
            'rerun_triggered': 0,
            'blocked_by_prediction': 0,
            'still_pending': 0,
            'errors': 0
        }

        # Get pending games
        pending_games = self.check_pending_games(check_date)
        stats['pending_checked'] = len(pending_games)

        if not pending_games:
            logger.info("No pending BDB games found")
            return stats

        logger.info(f"Found {len(pending_games)} pending BDB games")

        # Group by date for efficient checking
        games_by_date: Dict[date, List[Dict]] = {}
        for game in pending_games:
            gd = game['game_date']
            if gd not in games_by_date:
                games_by_date[gd] = []
            games_by_date[gd].append(game)

        # Process each date
        for game_date, games in games_by_date.items():
            game_ids = [g['game_id'] for g in games]

            # Check BDB availability
            bdb_available = self.check_bdb_availability(game_ids, game_date)

            # Check if predictions exist for this date
            predictions_exist = self.check_prediction_exists(game_date)

            for game in games:
                game_id = game['game_id']

                if bdb_available.get(game_id, False):
                    stats['bdb_available'] += 1
                    logger.info(f"BDB data now available for {game_date} / {game_id}")

                    if predictions_exist:
                        # Don't re-run - predictions already made
                        stats['blocked_by_prediction'] += 1
                        self.update_pending_status(
                            game_id, game_date,
                            status='blocked',
                            resolution_type='blocked_by_prediction',
                            resolution_notes=f'Predictions already exist for {game_date}',
                            bdb_detected=True
                        )
                        logger.warning(
                            f"Skipping re-run for {game_id}: predictions already exist "
                            f"(would change predictions close to game time)"
                        )
                    else:
                        # Safe to re-run
                        if self.trigger_phase3_rerun(game_date, game_id):
                            stats['rerun_triggered'] += 1
                            self.update_pending_status(
                                game_id, game_date,
                                status='reran',
                                resolution_type='auto_rerun',
                                resolution_notes='BDB data became available, triggered re-run',
                                bdb_detected=True
                            )
                        else:
                            stats['errors'] += 1
                else:
                    # BDB still not available
                    stats['still_pending'] += 1
                    self.update_pending_status(
                        game_id, game_date,
                        status='pending_bdb'  # Keep pending
                    )

        # Send summary alert if issues found
        if stats['still_pending'] > 0:
            self.send_alert(
                f"BDB Pending Monitor: {stats['still_pending']} games still missing BDB data, "
                f"{stats['bdb_available']} now available, {stats['rerun_triggered']} re-runs triggered, "
                f"{stats['blocked_by_prediction']} blocked by existing predictions"
            )

        logger.info(f"BDB Pending Monitor complete: {stats}")
        return stats


def main():
    parser = argparse.ArgumentParser(description='Monitor pending BigDataBall games')
    parser.add_argument('--dry-run', action='store_true', help='Don\'t make changes')
    parser.add_argument('--date', type=str, help='Check specific date (YYYY-MM-DD)')
    args = parser.parse_args()

    check_date = None
    if args.date:
        check_date = date.fromisoformat(args.date)

    monitor = BDBPendingMonitor(dry_run=args.dry_run)
    stats = monitor.run(check_date=check_date)

    # Exit with error code if issues remain
    if stats['errors'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
