#!/usr/bin/env python3
"""
BigDataBall Retry Processor

Processes games in pending_bdb_games table and retries when data becomes available.

Functions:
1. READ: Query pending_bdb_games for games needing retry
2. CHECK: Verify if BDB data is now available
3. TRIGGER: Start Phase 3 re-processing when BDB data available
4. UPDATE: Mark games as completed or increment retry count
5. CLEANUP: Remove old completed/failed records

Schedule: Every hour via Cloud Scheduler

Retry Strategy:
- Check BDB data availability every hour
- Max 72 checks (3 days)
- After 72 checks, mark as failed and alert

Usage:
    python bin/monitoring/bdb_retry_processor.py [--dry-run] [--max-age-days N]

Created: Session 53 (2026-01-31)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from google.cloud import pubsub_v1

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BDBRetryProcessor:
    """
    Process pending BDB games and retry when data becomes available.
    """

    # Minimum shots expected per game for "complete" data
    MIN_SHOTS_PER_GAME = 50

    # Maximum checks before giving up (72 checks × 1 hour = 3 days)
    MAX_CHECK_COUNT = 72

    def __init__(self, dry_run: bool = False):
        self.client = bigquery.Client()
        self.project_id = self.client.project
        self.dry_run = dry_run

        if not dry_run:
            try:
                self.publisher = pubsub_v1.PublisherClient()
            except Exception as e:
                logger.warning(f"Could not initialize Pub/Sub: {e}")
                self.publisher = None

    def get_pending_games(self, max_age_days: int = 7) -> List[Dict]:
        """
        Get games from pending_bdb_games that need retry.

        Returns games with status='pending_bdb' and check_count < MAX_CHECK_COUNT.
        """
        cutoff_date = date.today() - timedelta(days=max_age_days)

        query = f"""
        SELECT
            game_date,
            game_id,
            home_team,
            away_team,
            fallback_source,
            original_processed_at,
            status,
            quality_before_rerun,
            shot_zones_complete_before,
            bdb_check_count,
            last_bdb_check_at
        FROM `{self.project_id}.nba_orchestration.pending_bdb_games`
        WHERE status = 'pending_bdb'
          AND bdb_check_count < {self.MAX_CHECK_COUNT}
          AND game_date >= '{cutoff_date}'
        ORDER BY game_date ASC, bdb_check_count ASC
        """

        try:
            result = self.client.query(query).to_dataframe()
            games = result.to_dict('records')
            logger.info(f"Found {len(games)} games pending BDB retry")
            return games
        except Exception as e:
            logger.error(f"Error querying pending games: {e}")
            return []

    def check_bdb_availability(self, game_id: str, game_date: date) -> Dict:
        """
        Check if BDB data is now available for a game.

        Returns dict with:
        - available: bool (True if data meets quality threshold)
        - shot_count: int
        - shots_with_distance: int
        """
        # Convert game_id to match BDB format (string with leading zeros)
        game_id_padded = game_id.zfill(10) if game_id.isdigit() else game_id

        query = f"""
        SELECT
            COUNT(*) as total_events,
            COUNTIF(event_type = 'shot') as shot_count,
            COUNTIF(event_type = 'shot' AND shot_distance IS NOT NULL) as shots_with_distance
        FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
        WHERE LPAD(CAST(bdb_game_id AS STRING), 10, '0') = '{game_id_padded}'
          AND game_date = '{game_date}'
        """

        try:
            result = self.client.query(query).to_dataframe()
            if result.empty:
                return {
                    'available': False,
                    'shot_count': 0,
                    'shots_with_distance': 0
                }

            row = result.iloc[0]
            shots_with_distance = int(row['shots_with_distance']) if row['shots_with_distance'] else 0

            return {
                'available': shots_with_distance >= self.MIN_SHOTS_PER_GAME,
                'shot_count': int(row['shot_count']) if row['shot_count'] else 0,
                'shots_with_distance': shots_with_distance
            }
        except Exception as e:
            logger.error(f"Error checking BDB availability for {game_id}: {e}")
            return {
                'available': False,
                'shot_count': 0,
                'shots_with_distance': 0,
                'error': str(e)
            }

    def trigger_phase3_rerun(self, game: Dict) -> bool:
        """Trigger Phase 3 re-processing for a game that now has BDB data."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger Phase 3 re-run for {game['game_id']}")
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
                'game_date': game['game_date'].isoformat() if isinstance(game['game_date'], date) else str(game['game_date']),
                'game_id': game['game_id'],
                'trigger_reason': 'bdb_data_available',
                'source': 'bdb_retry_processor',
                'original_quality': game.get('quality_before_rerun', 'unknown'),
                'priority': 'normal'
            }).encode('utf-8')

            future = self.publisher.publish(topic_path, message)
            future.result(timeout=30)
            logger.info(f"✅ Triggered Phase 3 re-run for {game['game_id']}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 3 re-run for {game['game_id']}: {e}")
            return False

    def _trigger_phase4_rerun(self, game_date: str) -> bool:
        """Trigger Phase 4 precompute processors for specific date."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger Phase 4 re-run for {game_date}")
            return True

        if not self.publisher:
            logger.warning("Pub/Sub not available, cannot trigger Phase 4")
            return False

        try:
            topic_path = self.publisher.topic_path(
                self.project_id,
                'nba-phase4-trigger'
            )
            message = json.dumps({
                'game_date': game_date if isinstance(game_date, str) else game_date.isoformat(),
                'reason': 'bdb_data_available',
                'mode': 'reprocess_specific_date',
                'processors': [
                    'player_shot_zone_analysis',
                    'player_composite_factors',
                    'player_daily_cache',
                    'ml_feature_store'
                ],
                'priority': 'normal',
                'source': 'bdb_retry_processor'
            }).encode('utf-8')

            future = self.publisher.publish(topic_path, message)
            future.result(timeout=30)
            logger.info(f"✅ Triggered Phase 4 re-run for {game_date}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 4: {e}")
            return False

    def _trigger_phase5_regeneration(self, game_date: str, game: Dict) -> bool:
        """Trigger Phase 5 prediction regeneration with superseding."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger Phase 5 regeneration for {game_date}")
            return True

        if not self.publisher:
            logger.warning("Pub/Sub not available, cannot trigger Phase 5")
            return False

        try:
            topic_path = self.publisher.topic_path(
                self.project_id,
                'nba-prediction-trigger'
            )
            message = json.dumps({
                'game_date': game_date if isinstance(game_date, str) else game_date.isoformat(),
                'reason': 'bdb_upgrade',
                'mode': 'regenerate_with_supersede',
                'metadata': {
                    'original_source': game.get('fallback_source'),
                    'upgrade_from': 'nbac_fallback',
                    'upgrade_to': 'bigdataball',
                    'quality_before': game.get('quality_before_rerun', 'silver'),
                    'trigger_type': 'bdb_retry_processor',
                    'bdb_check_count': game.get('bdb_check_count', 0),
                    'bdb_available_at': datetime.now(timezone.utc).isoformat()
                }
            }).encode('utf-8')

            future = self.publisher.publish(topic_path, message)
            future.result(timeout=30)
            logger.info(f"✅ Triggered Phase 5 regeneration for {game_date}")
            return True
        except Exception as e:
            logger.error(f"Failed to trigger Phase 5: {e}")
            return False

    def _is_game_complete(self, game_date: str) -> bool:
        """Check if game is complete (for re-grading)."""
        try:
            game_dt = date.fromisoformat(game_date) if isinstance(game_date, str) else game_date
            return game_dt < date.today()
        except Exception:
            return False

    def _trigger_regrading(self, game_date: str) -> bool:
        """Trigger re-grading of predictions for completed game (future enhancement)."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would trigger re-grading for {game_date}")
            return True

        # Placeholder for future implementation
        logger.debug(f"Re-grading trigger for {game_date} (not yet implemented)")
        return True

    def trigger_full_reprocessing_pipeline(self, game: Dict) -> bool:
        """
        Trigger complete re-processing when BDB data arrives.

        Pipeline:
        1. Phase 3: player_game_summary
        2. Phase 4: precompute processors
        3. Phase 5: prediction regeneration
        4. Grading: re-grade if game complete (future)

        Args:
            game: Game metadata from pending_bdb_games table

        Returns:
            True if all triggers succeeded, False otherwise
        """
        game_date = game['game_date']
        if isinstance(game_date, date):
            game_date = game_date.isoformat()

        game_id = game['game_id']
        success = True

        logger.info(f"🚀 Starting full reprocessing pipeline for {game_id} ({game_date})")

        # Step 1: Phase 3 Re-run
        if not self.trigger_phase3_rerun(game):
            logger.error(f"Phase 3 trigger failed for {game_id}")
            success = False
            # Continue anyway - partial pipeline is better than nothing

        # Step 2: Phase 4 Re-run
        if not self._trigger_phase4_rerun(game_date):
            logger.error(f"Phase 4 trigger failed for {game_date}")
            success = False

        # Step 3: Phase 5 Prediction Regeneration
        if not self._trigger_phase5_regeneration(game_date, game):
            logger.error(f"Phase 5 trigger failed for {game_date}")
            success = False

        # Step 4: Re-grade if game complete (future enhancement)
        if self._is_game_complete(game_date):
            if not self._trigger_regrading(game_date):
                logger.warning(f"Re-grading trigger failed for {game_date}")
                # Don't fail overall - re-grading is nice-to-have

        logger.info(
            f"{'✅' if success else '⚠️'} Full reprocessing pipeline "
            f"{'succeeded' if success else 'partially failed'} for {game_id}"
        )
        return success

    def update_game_status(self, game: Dict, new_status: str, bdb_info: Optional[Dict] = None) -> None:
        """
        Update the status of a game in pending_bdb_games table.

        Args:
            game: Game record
            new_status: 'completed_bdb', 'failed_max_retries', or 'pending_bdb'
            bdb_info: Optional BDB availability info (shot counts)
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would update {game['game_id']} status to {new_status}")
            return

        # Build update fields
        update_fields = []
        if new_status != 'pending_bdb':
            update_fields.append(f"status = '{new_status}'")
            update_fields.append("completed_at = CURRENT_TIMESTAMP()")

        # Always increment check count and update last_bdb_check_at
        update_fields.append("bdb_check_count = bdb_check_count + 1")
        update_fields.append("last_bdb_check_at = CURRENT_TIMESTAMP()")
        update_fields.append("updated_at = CURRENT_TIMESTAMP()")

        # Add BDB info if available
        if bdb_info:
            update_fields.append(f"bdb_shots_found = {bdb_info.get('shots_with_distance', 0)}")
            if bdb_info.get('available'):
                update_fields.append("bdb_available_at = CURRENT_TIMESTAMP()")

        update_sql = ", ".join(update_fields)

        query = f"""
        UPDATE `{self.project_id}.nba_orchestration.pending_bdb_games`
        SET {update_sql}
        WHERE game_date = '{game['game_date']}'
          AND game_id = '{game['game_id']}'
          AND status = 'pending_bdb'
        """

        try:
            self.client.query(query).result()
            logger.info(f"Updated {game['game_id']} → {new_status} (check #{game['bdb_check_count'] + 1})")
        except Exception as e:
            logger.error(f"Failed to update game {game['game_id']}: {e}")

    def cleanup_old_records(self, days: int = 30) -> int:
        """
        Remove completed/failed records older than N days.

        Returns number of records deleted.
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would cleanup records older than {days} days")
            return 0

        cutoff_date = date.today() - timedelta(days=days)

        query = f"""
        DELETE FROM `{self.project_id}.nba_orchestration.pending_bdb_games`
        WHERE status IN ('completed_bdb', 'failed_max_retries')
          AND game_date < '{cutoff_date}'
        """

        try:
            result = self.client.query(query).result()
            deleted = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old records (>{days} days)")
            return deleted
        except Exception as e:
            logger.error(f"Failed to cleanup old records: {e}")
            return 0

    def run(self, max_age_days: int = 7) -> Dict:
        """
        Main processing loop.

        Returns summary stats.
        """
        logger.info(f"{'='*60}")
        logger.info(f"BDB RETRY PROCESSOR - {datetime.now().isoformat()}")
        logger.info(f"{'='*60}")

        stats = {
            'games_checked': 0,
            'games_available': 0,
            'games_still_pending': 0,
            'games_failed': 0,
            'full_pipeline_triggered': 0,
            'cleanup_count': 0
        }

        # Get pending games
        games = self.get_pending_games(max_age_days)

        if not games:
            logger.info("No games pending BDB retry")
            # Still run cleanup
            stats['cleanup_count'] = self.cleanup_old_records()
            return stats

        stats['games_checked'] = len(games)

        # Process each game
        for game in games:
            game_str = f"{game['game_date']} {game.get('away_team', 'UNK')}@{game.get('home_team', 'UNK')} (ID: {game['game_id']})"
            check_num = game.get('bdb_check_count', 0) + 1

            logger.info(f"Checking {game_str} (check #{check_num}/{self.MAX_CHECK_COUNT})")

            # Check if BDB data is now available
            bdb_info = self.check_bdb_availability(game['game_id'], game['game_date'])

            if bdb_info.get('available'):
                # SUCCESS: BDB data is now available
                logger.info(f"  ✅ BDB data available ({bdb_info['shots_with_distance']} shots)")
                stats['games_available'] += 1

                # Trigger full reprocessing pipeline (Phase 3-4-5)
                if self.trigger_full_reprocessing_pipeline(game):
                    stats['full_pipeline_triggered'] += 1
                    self.update_game_status(game, 'completed_bdb', bdb_info)
                else:
                    # Failed to trigger, keep pending
                    self.update_game_status(game, 'pending_bdb', bdb_info)
                    stats['games_still_pending'] += 1

            elif check_num >= self.MAX_CHECK_COUNT:
                # FAILED: Hit max retry count
                logger.warning(f"  ❌ Max retries reached ({self.MAX_CHECK_COUNT} checks)")
                stats['games_failed'] += 1
                self.update_game_status(game, 'failed_max_retries', bdb_info)

            else:
                # PENDING: Still waiting for BDB data
                logger.info(f"  ⏳ BDB data not available yet ({bdb_info['shots_with_distance']} shots)")
                stats['games_still_pending'] += 1
                self.update_game_status(game, 'pending_bdb', bdb_info)

        # Cleanup old records
        stats['cleanup_count'] = self.cleanup_old_records()

        logger.info(f"\n{'='*60}")
        logger.info(f"SUMMARY: {stats}")
        logger.info(f"{'='*60}")

        return stats


def main():
    parser = argparse.ArgumentParser(description='BigDataBall Retry Processor')
    parser.add_argument('--dry-run', action='store_true', help='Don\'t make changes or trigger re-runs')
    parser.add_argument('--max-age-days', type=int, default=7, help='Only process games from last N days (default: 7)')
    args = parser.parse_args()

    processor = BDBRetryProcessor(dry_run=args.dry_run)
    stats = processor.run(max_age_days=args.max_age_days)

    # Exit with error if failures detected
    if stats.get('games_failed', 0) > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
